"""Single-request policy transport with auxiliary declarations checked softly.

The provider schema requests flat strings. Runtime validation deliberately
retains finite JSON auxiliary values of other types, so the trusted controller
can record malformed declarations without discarding a valid rule selection.
Only the four rule fields and the complete 64 KiB submission are hard bounds.
SDK 1.55.1 drops top-level JSON null arguments before action validation. Their
original values remain in the immutable response; the core sees omitted-field
defaults instead. Strings and nested auxiliary JSON are not rewritten here.
"""
import copy
import json
import math
from pathlib import Path
import re
from typing import Any, ClassVar

from openhands.sdk import Action, Tool, ToolDefinition
from openhands.sdk.agent.utils import (
    fix_malformed_tool_arguments, normalize_tool_call, parse_tool_call_arguments,
)
from openhands.sdk.tool import ToolExecutor, register_tool
from pydantic import Field, model_validator

from .pilot_agent import run_session, write_json
from .policy_agent import PolicyObservation, PolicyStatePacketLLM, Rule


_RULE_FIELDS = tuple(f'rule_{i}' for i in range(1, 5))
_AUX_FIELDS = tuple(f'{prefix}_{i}' for prefix in ('verdict', 'evidence')
                   for i in range(1, 5)) + ('notes',)
_FIELDS = _RULE_FIELDS + _AUX_FIELDS


def _finite_json(value):
    """Reject values that cannot be preserved as strict finite JSON."""
    kind = type(value)
    if value is None or kind in (str, bool, int):
        return
    if kind is float and math.isfinite(value):
        return
    if kind is list:
        for item in value:
            _finite_json(item)
        return
    if kind is dict and all(type(key) is str for key in value):
        for item in value.values():
            _finite_json(item)
        return
    raise ValueError('Inference policy auxiliary values must be finite JSON')


class InferencePolicyAction(Action):
    rule_1: Rule = Field(description='First selected fixed-catalog rule.')
    rule_2: Rule = Field(description='Second selected fixed-catalog rule.')
    rule_3: Rule = Field(description='Third selected fixed-catalog rule.')
    rule_4: Rule = Field(description='Fourth selected fixed-catalog rule.')
    verdict_1: Any = Field(default='', description='Verdict for supplied inference 1; use the task packet labels.')
    verdict_2: Any = Field(default='', description='Verdict for supplied inference 2; use the task packet labels.')
    verdict_3: Any = Field(default='', description='Verdict for supplied inference 3; use the task packet labels.')
    verdict_4: Any = Field(default='', description='Verdict for supplied inference 4; use the task packet labels.')
    evidence_1: Any = Field(default='', description='Supplied evidence identifier for inference 1.')
    evidence_2: Any = Field(default='', description='Supplied evidence identifier for inference 2.')
    evidence_3: Any = Field(default='', description='Supplied evidence identifier for inference 3.')
    evidence_4: Any = Field(default='', description='Supplied evidence identifier for inference 4.')
    notes: Any = Field(default='', description='Optional unverified explanation, archived verbatim by the host.')

    @classmethod
    def to_mcp_schema(cls):
        schema = super().to_mcp_schema()
        original = cls.model_json_schema()
        schema['properties'] = {
            key: copy.deepcopy(original['properties'][key]) for key in _RULE_FIELDS}
        # The requested representation stays simple, but an incorrect auxiliary
        # type must reach the core's soft checker instead of blocking the policy.
        for key in _AUX_FIELDS:
            schema['properties'][key] = {
                'type': 'string', 'default': '',
                'description': original['properties'][key]['description']}
        schema['required'] = list(_RULE_FIELDS)
        schema['additionalProperties'] = False
        return schema

    @model_validator(mode='after')
    def bounded_finite_json(self):
        try:
            values = {key: getattr(self, key) for key in _FIELDS}
            _finite_json(values)
            encoded = json.dumps(values, ensure_ascii=False, allow_nan=False,
                sort_keys=True, separators=(',', ':')).encode('utf-8')
        except (ValueError, TypeError, UnicodeError, OverflowError, RecursionError) as error:
            raise ValueError('Inference policy fields must be finite UTF-8 JSON') from error
        if len(encoded) > 65536:
            raise ValueError('Inference policy fields exceed 65536 canonical UTF-8 bytes')
        return self


class _InferencePolicyExecutor(ToolExecutor[InferencePolicyAction, PolicyObservation]):
    def __init__(self, controller):
        self.controller = controller

    def __call__(self, action, conversation=None):
        try:
            action = InferencePolicyAction.model_validate(action.model_dump())
            feedback = self.controller.submit_policy(**{key: getattr(action, key) for key in _FIELDS})
            text = json.dumps(feedback, ensure_ascii=False, allow_nan=False, sort_keys=True)
            return PolicyObservation.from_text(text, feedback=feedback)
        except Exception as error:
            # Core returns ordinary structural rejection without raising. An
            # exception here means infrastructure failure, never a missing arm.
            self.controller.halted = True
            error_type = type(error).__name__
            if re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,127}', error_type) is None:
                error_type = 'Exception'
            self.controller.infrastructure_error_type = error_type
            try:
                write_json(Path(self.controller.output_dir)/'controller-error.json', {
                    'status': 'infrastructure_error',
                    'error_kind': 'inference_policy_executor_exception', 'error_type': error_type})
            except Exception:
                pass
            raise


def inference_policy_tool(controller, session_id):
    class InferencePolicyTool(ToolDefinition[InferencePolicyAction, PolicyObservation]):
        name: ClassVar[str] = 'submit_policy'

        @classmethod
        def create(cls, conv_state=None, **params):
            if params:
                raise ValueError('Inference policy tool accepts no initialization options')
            return [cls(action_type=InferencePolicyAction, observation_type=PolicyObservation,
                executor=_InferencePolicyExecutor(controller),
                description=('Submit four distinct ordered catalog rule IDs. Optional verdict_1 through '
                    'verdict_4 and evidence_1 through evidence_4 declare the supplied inferences. '
                    'Use the labels and evidence identifiers in the task packet. Optional notes '
                    'contain unverified reasoning; there is no rationale field. Auxiliary '
                    'declarations are checked separately and never select or reject a valid policy. '
                    'The complete 13 business fields must fit within 65536 canonical UTF-8 JSON bytes. '
                    'Text is archived without truncation. Only fixed-catalog rule text transfers '
                    'to repair. This tool cannot execute source, read files, access networks or evaluate tasks.'))]

    name = 'InferencePolicySubmit_' + session_id
    register_tool(name, InferencePolicyTool)
    return Tool(name=name)


class InferencePolicyStatePacketLLM(PolicyStatePacketLLM):
    """Observe hard transport bounds; auxiliary truth and type checks are core-owned."""
    def _observe_submission_schema(self, response):
        calls = response.choices[0].message.tool_calls
        if not calls or calls[0].function.name != 'submit_policy':
            return
        try:
            arguments = parse_tool_call_arguments(calls[0].function.arguments)
            _, arguments = normalize_tool_call('submit_policy', arguments, ('submit_policy', 'finish'))
            arguments = fix_malformed_tool_arguments(arguments, InferencePolicyAction)
            arguments.pop('security_risk', None)
            arguments.pop('summary', None)
            InferencePolicyAction.model_validate(arguments)
        except (ValueError, TypeError, OverflowError, RecursionError):
            self._last_submission_schema_error = 'inference_policy_submission_schema'
            self._active_input_audit['response_tool_validation'] = {
                'status': 'invalid_request', 'error_kind': 'inference_policy_submission_schema'}
        else:
            self._last_submission_schema_error = None
            self._active_input_audit['response_tool_validation'] = {'status': 'valid_submission'}


def run_inference_policy_session(controller, llm, session_id, output_dir):
    return run_session(controller, llm, session_id, output_dir,
        tool_factory=inference_policy_tool, max_iterations=1, purpose='policy')
