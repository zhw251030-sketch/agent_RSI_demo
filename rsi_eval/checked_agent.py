"""SDK boundary for typed submissions and deterministic whole-history replacement.

The controller owns checks, evaluations and selection. This module enforces
only bounded submission structure and pre-transport accounting. It performs
no claim-semantic gate and never persists provider error text or credentials.
"""
import hashlib
import json
from pathlib import Path
from typing import ClassVar

from openhands.sdk import Action, Tool, ToolDefinition
from openhands.sdk.tool import ToolExecutor, register_tool
from pydantic import Field, PrivateAttr, StrictInt, StrictStr, field_validator, model_validator

from .pilot_agent import BoundedPilotLLM, SubmitCandidateObservation, run_session, write_json
from .pilot_budget import BudgetExceeded
from .state_packet import MAX_PACKET_BYTES, payload_bytes, replace_messages, wire_payload


_BUDGET_REASONS = {
    'input byte cap exceeded': 'input_byte_cap_exceeded',
    'per-request output token cap exceeded': 'output_token_cap_exceeded',
    'budget ledger locked; no request allowed': 'budget_ledger_locked',
    'budget halted after invalid or excessive usage': 'budget_halted',
    'total request cap exceeded': 'total_request_cap_exceeded',
    'per-session request cap exceeded': 'session_request_cap_exceeded',
    'cumulative reserved token cap exceeded': 'reserved_token_cap_exceeded',
    'cumulative reserved cost cap exceeded': 'reserved_cost_cap_exceeded',
}


class CheckedCandidateAction(Action):
    source: StrictStr = Field(min_length=1, max_length=16384)
    n_params: StrictInt = Field(default=3, ge=0, le=16)
    rationale: StrictStr = Field(default='', max_length=2000)
    claims: list[dict] = Field(min_length=1, max_length=2)
    prediction: dict

    @field_validator('source')
    @classmethod
    def bounded_source(cls, value):
        if not value.strip() or len(value.encode('utf-8')) > 16384:
            raise ValueError('Candidate must be nonempty and at most 16384 UTF-8 bytes')
        return value

    @field_validator('claims', mode='before')
    @classmethod
    def strict_claims(cls, value):
        if type(value) is not list or any(type(claim) is not dict for claim in value):
            raise ValueError('Claims must be a list of objects')
        return value

    @field_validator('prediction', mode='before')
    @classmethod
    def strict_prediction(cls, value):
        if type(value) is not dict:
            raise ValueError('Prediction must be an object')
        return value

    @model_validator(mode='after')
    def bounded_declarations(self):
        try:
            encoded = json.dumps({'claims': self.claims, 'prediction': self.prediction},
                                 allow_nan=False).encode('utf-8')
        except (TypeError, ValueError, OverflowError, RecursionError) as error:
            raise ValueError('Declarations must be finite JSON') from error
        if len(encoded) > 2048:
            raise ValueError('Declarations exceed the 2048-byte JSON bound')
        return self


class _CheckedExecutor(ToolExecutor[CheckedCandidateAction, SubmitCandidateObservation]):
    def __init__(self, controller):
        self.controller = controller

    def __call__(self, action, conversation=None):
        action = CheckedCandidateAction.model_validate(action.model_dump())
        feedback = self.controller.submit(action.source, action.n_params, action.rationale,
                                          claims=action.claims, prediction=action.prediction)
        text = json.dumps(feedback, ensure_ascii=False, allow_nan=False, sort_keys=True)
        return SubmitCandidateObservation.from_text(text, feedback=feedback)


def checked_candidate_tool(controller, session_id):
    """Expose one bounded submission tool; trusted task identity is never an argument."""
    class CheckedCandidateTool(ToolDefinition[CheckedCandidateAction, SubmitCandidateObservation]):
        name: ClassVar[str] = 'submit_candidate'

        @classmethod
        def create(cls, conv_state=None, **params):
            if params:
                raise ValueError('Candidate tool accepts no initialization options')
            return [cls(action_type=CheckedCandidateAction,
                        observation_type=SubmitCandidateObservation,
                        executor=_CheckedExecutor(controller),
                        description=('Submit one complete candidate with 1–2 structured claims and '
                            'one before/after prediction. Source is at most 16384 UTF-8 bytes; '
                            'claims plus prediction at most 2048 JSON bytes. The controller '
                            'owns task identity, evidence binding, evaluation and selection. '
                            'Checks provide feedback and never gate candidate execution.'))]

    registry_name = 'CheckedSubmitCandidate_' + session_id
    register_tool(registry_name, CheckedCandidateTool)
    return Tool(name=registry_name)


class StatePacketLLM(BoundedPilotLLM):
    _state_controller: object = PrivateAttr(default=None)
    _packet_attempt: int = PrivateAttr(default=0)
    _active_input_audit: dict | None = PrivateAttr(default=None)
    _active_input_audit_path: Path | None = PrivateAttr(default=None)
    _last_submission_schema_error: str | None = PrivateAttr(default=None)

    def bind_controller(self, controller):
        self._state_controller = controller
        return self

    def _save_input_audit(self):
        if self._active_input_audit_path is not None and self._active_input_audit is not None:
            write_json(self._active_input_audit_path, self._active_input_audit)

    def _observe_submission_schema(self, response):
        """Remember only the last submission's structural error for the next packet.

        The unchanged response still reaches the SDK, which owns validation and
        rejection. No semantic checker runs here and no error details or model
        arguments enter this bounded feedback channel.
        """
        calls = response.choices[0].message.tool_calls
        if not calls or calls[0].function.name != 'submit_candidate':
            return
        try:
            arguments = json.loads(calls[0].function.arguments)
            CheckedCandidateAction.model_validate(arguments)
        except (ValueError, TypeError, OverflowError, RecursionError):
            self._last_submission_schema_error = 'submission_schema'
            self._active_input_audit['response_tool_validation'] = {
                'status': 'invalid_request', 'error_kind': 'submission_schema'}
        else:
            self._last_submission_schema_error = None
            self._active_input_audit['response_tool_validation'] = {'status': 'valid_submission'}

    def _pilot_transport_started(self, request_id):
        """Called by the bounded parent after reservation/request logging, before dispatch."""
        if self._active_input_audit is None:
            raise RuntimeError('State-packet transport has no input audit')
        self._active_input_audit.update(request_id=request_id, request_reserved=True,
                                        status='dispatch_ready')
        self._save_input_audit()
        # Mark dispatch in memory only after the pre-dispatch audit write succeeds.
        # The outer finally persists this on return/error from the actual transport.
        self._active_input_audit.update(network_dispatch_attempted=True,
                                        transport_called=True, status='dispatched')

    def _transport_call(self, *, messages, enable_streaming=False, on_token=None, **kwargs):
        if (self._state_controller is None or self._pilot_ledger is None
                or self._pilot_output is None):
            raise RuntimeError('State-packet LLM requires controller and budget bindings')
        self._packet_attempt += 1
        number = self._packet_attempt
        packet_path = self._pilot_output / f'packet-{number:04d}.json'
        audit_path = self._pilot_output / f'input-audit-{number:04d}.json'
        if packet_path.exists() or audit_path.exists():
            raise FileExistsError('Refusing to overwrite a state-packet attempt')
        cap = self._pilot_ledger.config['max_input_bytes']
        audit = {'version': 'input-audit-v0.1', 'attempt_index': number,
                 'session_id': self._pilot_session, 'max_input_bytes': cap,
                 'actual_input_bytes': None, 'excess_bytes': None, 'payload_sha256': None,
                 'request_reserved': False, 'network_dispatch_attempted': False,
                 'transport_called': False, 'status': 'pending', 'reason': None}
        self._active_input_audit = audit
        self._active_input_audit_path = audit_path
        self._save_input_audit()
        reserved_before = None
        try:
            try:
                packet = self._state_controller.state_packet()
                if self._last_submission_schema_error is not None:
                    packet['last_tool_validation'] = {'status': 'invalid_request',
                                                       'error_kind': self._last_submission_schema_error}
                if payload_bytes(packet) > MAX_PACKET_BYTES:
                    raise ValueError('Complete state packet exceeds its byte bound')
                replacement = replace_messages(messages, packet)
                output_tokens = kwargs.get('max_tokens', kwargs.get(
                    'max_completion_tokens', self.max_output_tokens))
                payload = wire_payload(self.model, replacement, kwargs.get('tools'),
                                       kwargs.get('tool_choice'), output_tokens)
                encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False,
                                     sort_keys=True, separators=(',', ':')).encode('utf-8')
            except (ValueError, TypeError, OverflowError, RecursionError):
                audit.update(status='denied', reason='state_packet_contract')
                raise
            write_json(packet_path, packet)
            audit.update(actual_input_bytes=len(encoded), excess_bytes=max(0, len(encoded) - cap),
                         payload_sha256=hashlib.sha256(encoded).hexdigest())
            self._save_input_audit()
            if len(encoded) > cap:
                raise BudgetExceeded('input byte cap exceeded')
            reserved_before = self._pilot_ledger.summary()['session_counts'][self._pilot_session]
            response = super()._transport_call(messages=replacement,
                enable_streaming=enable_streaming, on_token=on_token, **kwargs)
            self._observe_submission_schema(response)
            audit.update(status='completed')
            return response
        except BudgetExceeded as error:
            audit.update(status='denied', reason=_BUDGET_REASONS.get(str(error), 'budget_denied'))
            raise
        except Exception as error:
            if audit['reason'] is None:
                audit.update(status='error', reason='transport_error' if audit['transport_called']
                             else 'pretransport_error')
            # Class only; never preserve an exception's provider/body text.
            audit['error_type'] = type(error).__name__
            raise
        finally:
            if reserved_before is not None and not audit['request_reserved']:
                # Reservation may succeed and subsequent request-log IO fail before
                # the dispatch hook. Count only this session; never imply transport.
                try:
                    after = self._pilot_ledger.summary()['session_counts'][self._pilot_session]
                    audit['request_reserved'] = after > reserved_before
                except Exception:
                    audit['reservation_observation_unavailable'] = True
            self._save_input_audit()
            self._active_input_audit = None
            self._active_input_audit_path = None
