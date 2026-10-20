"""Flat premise declarations over the existing single-request policy transport.

This boundary validates field structure and bounded UTF-8 text only. The trusted
controller checks premises, stores every valid-structure attempt and owns
feedback visibility. A false premise never becomes a transport-level rejection.
"""
import copy
import json
from pathlib import Path
import re
from typing import ClassVar, Literal

from openhands.sdk import Action, Tool, ToolDefinition
from openhands.sdk.agent.utils import (
    fix_malformed_tool_arguments, normalize_tool_call, parse_tool_call_arguments,
)
from openhands.sdk.tool import ToolExecutor, register_tool
from pydantic import Field, StrictBool, StrictStr, model_validator

from .pilot_agent import run_session, write_json
from .policy_agent import PolicyObservation, PolicyStatePacketLLM, Rule


Support = Literal['F1', 'F2', 'both']
_FIELDS = tuple(
    [f'{prefix}_{i}' for prefix in ('rule', 'parent', 'quote') for i in range(1, 5)]
    + [f'fact_{i}_{part}' for i in (1, 2) for part in ('id', 'value', 'scope')]
    + [f'{prefix}_{i}' for prefix in ('support', 'hypothesis', 'edit') for i in range(1, 5)]
)


class GroundedPolicyAction(Action):
    rule_1: Rule = Field(description='First selected fixed-catalog rule.')
    rule_2: Rule = Field(description='Second selected fixed-catalog rule.')
    rule_3: Rule = Field(description='Third selected fixed-catalog rule.')
    rule_4: Rule = Field(description='Fourth selected fixed-catalog rule.')
    parent_1: StrictBool = Field(description='Whether rule_1 is present in the supplied parent policy.')
    parent_2: StrictBool = Field(description='Whether rule_2 is present in the supplied parent policy.')
    parent_3: StrictBool = Field(description='Whether rule_3 is present in the supplied parent policy.')
    parent_4: StrictBool = Field(description='Whether rule_4 is present in the supplied parent policy.')
    quote_1: StrictStr = Field(max_length=1000, description='Copy the complete catalog instruction for rule_1.')
    quote_2: StrictStr = Field(max_length=1000, description='Copy the complete catalog instruction for rule_2.')
    quote_3: StrictStr = Field(max_length=1000, description='Copy the complete catalog instruction for rule_3.')
    quote_4: StrictStr = Field(max_length=1000, description='Copy the complete catalog instruction for rule_4.')
    fact_1_id: StrictStr = Field(max_length=80, description='Exact supplied fact identifier for F1.')
    fact_2_id: StrictStr = Field(max_length=80, description='Exact supplied fact identifier for F2.')
    fact_1_value: StrictStr = Field(max_length=160,
        description='F1 value encoded as a single JSON scalar within this string; no arrays or objects.')
    fact_2_value: StrictStr = Field(max_length=160,
        description='F2 value encoded as a single JSON scalar within this string; no arrays or objects.')
    fact_1_scope: StrictStr = Field(max_length=160, description='Copy the exact supplied scope for F1.')
    fact_2_scope: StrictStr = Field(max_length=160, description='Copy the exact supplied scope for F2.')
    support_1: Support = Field(description='Facts motivating the hypothesis for rule_1.')
    support_2: Support = Field(description='Facts motivating the hypothesis for rule_2.')
    support_3: Support = Field(description='Facts motivating the hypothesis for rule_3.')
    support_4: Support = Field(description='Facts motivating the hypothesis for rule_4.')
    hypothesis_1: StrictStr = Field(max_length=240, description='Unverified applicability hypothesis for rule_1.')
    hypothesis_2: StrictStr = Field(max_length=240, description='Unverified applicability hypothesis for rule_2.')
    hypothesis_3: StrictStr = Field(max_length=240, description='Unverified applicability hypothesis for rule_3.')
    hypothesis_4: StrictStr = Field(max_length=240, description='Unverified applicability hypothesis for rule_4.')
    edit_1: StrictStr = Field(max_length=180, description='Proposed future repair action for rule_1; no source code.')
    edit_2: StrictStr = Field(max_length=180, description='Proposed future repair action for rule_2; no source code.')
    edit_3: StrictStr = Field(max_length=180, description='Proposed future repair action for rule_3; no source code.')
    edit_4: StrictStr = Field(max_length=180, description='Proposed future repair action for rule_4; no source code.')

    @classmethod
    def to_mcp_schema(cls):
        schema = super().to_mcp_schema()
        original = cls.model_json_schema()
        # SDK 1.55.1 simplifies JSON Schema. Restore primitive limits without
        # exposing its internal kind discriminator or adding nested contracts.
        for key in schema['properties']:
            schema['properties'][key].update(copy.deepcopy(original['properties'][key]))
        schema['additionalProperties'] = False
        return schema

    @model_validator(mode='after')
    def finite_utf8(self):
        try:
            encoded = json.dumps({key: getattr(self, key) for key in _FIELDS},
                ensure_ascii=False, allow_nan=False, sort_keys=True,
                separators=(',', ':')).encode('utf-8')
        except (ValueError, TypeError, UnicodeError, OverflowError, RecursionError) as error:
            raise ValueError('Grounded policy fields must be finite UTF-8 JSON') from error
        if len(encoded) > 16384:
            raise ValueError('Grounded policy fields exceed 16384 canonical UTF-8 bytes')
        return self


class _GroundedPolicyExecutor(ToolExecutor[GroundedPolicyAction, PolicyObservation]):
    def __init__(self, controller):
        self.controller = controller

    def __call__(self, action, conversation=None):
        try:
            action = GroundedPolicyAction.model_validate(action.model_dump())
            feedback = self.controller.submit_policy(**{key: getattr(action, key) for key in _FIELDS})
            text = json.dumps(feedback, ensure_ascii=False, allow_nan=False, sort_keys=True)
            return PolicyObservation.from_text(text, feedback=feedback)
        except Exception as error:
            # The SDK may absorb executor exceptions and return iteration
            # exhaustion. Preserve a fatal controller state independently.
            self.controller.halted = True
            error_type = type(error).__name__
            if re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,127}', error_type) is None:
                error_type = 'Exception'
            self.controller.infrastructure_error_type = error_type
            try:
                write_json(Path(self.controller.output_dir)/'controller-error.json', {
                    'status': 'infrastructure_error',
                    'error_kind': 'grounded_policy_executor_exception', 'error_type': error_type})
            except Exception:
                pass
            raise


def grounded_policy_tool(controller, session_id):
    class GroundedPolicyTool(ToolDefinition[GroundedPolicyAction, PolicyObservation]):
        name: ClassVar[str] = 'submit_policy'

        @classmethod
        def create(cls, conv_state=None, **params):
            if params:
                raise ValueError('Grounded policy tool accepts no initialization options')
            return [cls(action_type=GroundedPolicyAction, observation_type=PolicyObservation,
                executor=_GroundedPolicyExecutor(controller),
                description=('Submit four ordered fixed-catalog rules and two factual premises. '
                    'All 30 fields are required top-level primitive values, at most 16384 '
                    'canonical UTF-8 JSON bytes in total. State parent membership, '
                    'quote each full rule, cite F1/F2/both, and separate applicability hypotheses '
                    'from intended edits. The controller records premise checks without using '
                    'them as a policy selection gate. Only fixed catalog rule text transfers to '
                    'repair. No rationale field, source execution, files, network, or task evaluation.'))]

    name = 'GroundedPolicySubmit_' + session_id
    register_tool(name, GroundedPolicyTool)
    return Tool(name=name)


class GroundedPolicyStatePacketLLM(PolicyStatePacketLLM):
    """Reuse the policy allowlist, replacing only the structural observer."""
    def _observe_submission_schema(self, response):
        calls = response.choices[0].message.tool_calls
        if not calls or calls[0].function.name != 'submit_policy':
            return
        try:
            arguments = parse_tool_call_arguments(calls[0].function.arguments)
            _, arguments = normalize_tool_call('submit_policy', arguments, ('submit_policy', 'finish'))
            arguments = fix_malformed_tool_arguments(arguments, GroundedPolicyAction)
            arguments.pop('security_risk', None)
            arguments.pop('summary', None)
            GroundedPolicyAction.model_validate(arguments)
        except (ValueError, TypeError, OverflowError, RecursionError):
            self._last_submission_schema_error = 'grounded_policy_submission_schema'
            self._active_input_audit['response_tool_validation'] = {
                'status': 'invalid_request', 'error_kind': 'grounded_policy_submission_schema'}
        else:
            self._last_submission_schema_error = None
            self._active_input_audit['response_tool_validation'] = {'status': 'valid_submission'}


def run_grounded_policy_session(controller, llm, session_id, output_dir):
    return run_session(controller, llm, session_id, output_dir,
        tool_factory=grounded_policy_tool, max_iterations=1, purpose='policy')
