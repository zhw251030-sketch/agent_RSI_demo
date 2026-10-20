"""Flat model-facing evidence declarations with the existing bounded SDK transport.

The model supplies controller-issued IDs, never identity fields or hashes. The
trusted controller alone resolves IDs and parses the exact JSON value string.
Invalid evidence semantics remain recorded feedback, not an execution gate.
This module does not repair old responses or interpret JSON-looking prose.
"""
import copy
import json
from pathlib import Path
import re
from typing import ClassVar

from openhands.sdk import Action, Tool, ToolDefinition
from openhands.sdk.agent.utils import (
    fix_malformed_tool_arguments, normalize_tool_call, parse_tool_call_arguments,
)
from openhands.sdk.tool import ToolExecutor, register_tool
from pydantic import Field, StrictInt, StrictStr, field_validator, model_validator

from .checked_agent import StatePacketLLM
from .pilot_agent import SubmitCandidateObservation, run_session, write_json


class CompactCandidateAction(Action):
    source: StrictStr = Field(min_length=1, max_length=16384,
                             description='Complete candidate Python source, at most 16384 UTF-8 bytes.')
    n_params: StrictInt = Field(ge=0, le=16)
    rationale: StrictStr = Field(max_length=2000)
    claim_id: StrictStr = Field(max_length=128,
        description='Copy one exact current evidence catalog ID; do not construct or shorten it.')
    claim_op: StrictStr = Field(max_length=32,
        description='Scalar comparison or exact ordered atom membership.',
        json_schema_extra={'enum': ['eq', 'lt', 'le', 'gt', 'ge', 'contains', 'not_contains']})
    claim_value_json: StrictStr = Field(max_length=2048,
        description=('A JSON-encoded finite number for a scalar, such as "1.0", or a JSON-encoded '
            'ordered string array for a fact, such as "[\\"edge\\",\\"$0\\",\\"$1\\"]". '
            'No objects, booleans, null, NaN, Infinity, comments, or trailing content. '
            'At most 2048 UTF-8 bytes. This field itself is a string.'))
    prediction_id: StrictStr = Field(max_length=128,
        description='Copy one current scalar evidence ID for the parent value to predict against.')
    prediction_direction: StrictStr = Field(max_length=32,
        description='Direction of the absolute child-versus-parent change.',
        json_schema_extra={'enum': ['increase', 'decrease']})
    prediction_min_delta: float = Field(strict=True, allow_inf_nan=False,
        description='Nonnegative absolute minimum change; not a percentage.',
        json_schema_extra={'minimum': 0})

    @classmethod
    def to_mcp_schema(cls):
        schema = super().to_mcp_schema()
        # Preserve authored primitive-field limits through SDK 1.55.1's generic
        # simplifier. There are no nested declarations or union schemas here.
        original = cls.model_json_schema()
        # The SDK removes its internal discriminant (kind); restore only fields
        # actually exposed by to_mcp_schema, never that internal metadata.
        for key in schema['properties']:
            schema['properties'][key].update(copy.deepcopy(original['properties'][key]))
        schema['additionalProperties'] = False
        return schema

    @field_validator('source')
    @classmethod
    def bounded_source(cls, value):
        if not value.strip() or len(value.encode('utf-8')) > 16384:
            raise ValueError('Candidate must be nonempty and at most 16384 UTF-8 bytes')
        return value

    @field_validator('claim_value_json')
    @classmethod
    def bounded_value_bytes(cls, value):
        if len(value.encode('utf-8')) > 2048:
            raise ValueError('Claim value string exceeds 2048 UTF-8 bytes')
        return value

    @model_validator(mode='after')
    def bounded_declarations(self):
        declaration = self.model_dump(exclude={'source', 'n_params', 'rationale'})
        try:
            encoded = json.dumps(declaration, ensure_ascii=False, allow_nan=False).encode('utf-8')
        except (TypeError, ValueError, OverflowError, RecursionError, UnicodeError) as error:
            raise ValueError('Declarations must be finite UTF-8 JSON') from error
        if len(encoded) > 4096:
            raise ValueError('Declarations exceed 4096 serialized UTF-8 bytes')
        return self


class _CompactExecutor(ToolExecutor[CompactCandidateAction, SubmitCandidateObservation]):
    def __init__(self, controller):
        self.controller = controller

    def __call__(self, action, conversation=None):
        try:
            action = CompactCandidateAction.model_validate(action.model_dump())
            feedback = self.controller.submit(action.source, action.n_params, action.rationale,
                claim_id=action.claim_id, claim_op=action.claim_op,
                claim_value_json=action.claim_value_json, prediction_id=action.prediction_id,
                prediction_direction=action.prediction_direction,
                prediction_min_delta=action.prediction_min_delta)
            text = json.dumps(feedback, ensure_ascii=False, allow_nan=False, sort_keys=True)
            return SubmitCandidateObservation.from_text(text, feedback=feedback)
        except Exception as error:
            # SDK 1.55.1 catches tool-executor exceptions as AgentErrorEvent.
            # A one-iteration conversation then looks like ordinary iteration
            # exhaustion, with model_error_type=None. Preserve the fatal host
            # state explicitly so the runner cannot start another paid session.
            self.controller.halted = True
            error_type = type(error).__name__
            if re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,127}', error_type) is None:
                error_type = 'Exception'
            self.controller.infrastructure_error_type = error_type
            try:
                write_json(Path(self.controller.output_dir) / 'controller-error.json', {
                    'status': 'infrastructure_error', 'error_kind': 'compact_executor_exception',
                    'error_type': error_type})
            except Exception:
                # The original exception may itself be a storage failure. The
                # in-memory halt remains authoritative even if this write fails.
                pass
            raise


def compact_candidate_tool(controller, session_id):
    """One bounded candidate, one exact evidence claim and one preregistered prediction."""
    class CompactCandidateTool(ToolDefinition[CompactCandidateAction, SubmitCandidateObservation]):
        name: ClassVar[str] = 'submit_candidate'

        @classmethod
        def create(cls, conv_state=None, **params):
            if params:
                raise ValueError('Candidate tool accepts no initialization options')
            return [cls(action_type=CompactCandidateAction,
                        observation_type=SubmitCandidateObservation,
                        executor=_CompactExecutor(controller),
                        description=('Submit one complete candidate with one evidence claim and '
                            'one before/after prediction. All fields are top-level primitive values. '
                            'Copy current short evidence IDs exactly. claim_value_json is a string '
                            'containing one finite JSON number or one ordered string array. '
                            'The controller owns full evidence binding and evaluation. Semantic '
                            'check failures never gate candidate execution or selection.'))]

    registry_name = 'CompactSubmitCandidate_' + session_id
    register_tool(registry_name, CompactCandidateTool)
    return Tool(name=registry_name)


class CompactStatePacketLLM(StatePacketLLM):
    """Reuse whole-input packing, budget accounting and incomplete-call protection."""
    def _observe_submission_schema(self, response):
        calls = response.choices[0].message.tool_calls
        if not calls or calls[0].function.name != 'submit_candidate':
            return
        try:
            # Match SDK 1.55.1's action boundary, including its metadata handling.
            # This observes acceptance, not an independent repair of the response.
            arguments = parse_tool_call_arguments(calls[0].function.arguments)
            _, arguments = normalize_tool_call('submit_candidate', arguments,
                                               ('submit_candidate', 'finish'))
            arguments = fix_malformed_tool_arguments(arguments, CompactCandidateAction)
            arguments.pop('security_risk', None)
            arguments.pop('summary', None)
            CompactCandidateAction.model_validate(arguments)
        except (ValueError, TypeError, OverflowError, RecursionError):
            self._last_submission_schema_error = 'submission_schema'
            self._active_input_audit['response_tool_validation'] = {
                'status': 'invalid_request', 'error_kind': 'submission_schema'}
        else:
            self._last_submission_schema_error = None
            self._active_input_audit['response_tool_validation'] = {'status': 'valid_submission'}
