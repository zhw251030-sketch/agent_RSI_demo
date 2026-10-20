"""One bounded SDK action selects four rules from a fixed external-policy DSL.

The update tool cannot execute candidates. Rule rendering, evidence support,
policy validation and immutable storage belong to PolicyUpdateController.
Free-text rationale is forwarded for host-only archival, never used as policy.
"""
import copy
import json
from pathlib import Path
import re
from typing import ClassVar, Literal

from openhands.sdk import Action, Observation, Tool, ToolDefinition
from openhands.sdk.agent.utils import (
    fix_malformed_tool_arguments, normalize_tool_call, parse_tool_call_arguments,
)
from openhands.sdk.tool import ToolExecutor, register_tool
from pydantic import Field, StrictStr, model_validator

from .checked_agent import StatePacketLLM
from .pilot_agent import run_session, write_json


Rule = Literal['R01', 'R02', 'R03', 'R04', 'R05', 'R06', 'R07', 'R08']
Support = Literal['U-P', 'U-S', 'both']


class PolicyAction(Action):
    rule_1: Rule = Field(description='First rule from the fixed catalog.')
    rule_2: Rule = Field(description='Second rule from the fixed catalog.')
    rule_3: Rule = Field(description='Third rule from the fixed catalog.')
    rule_4: Rule = Field(description='Fourth rule from the fixed catalog.')
    support_1: Support = Field(description='Update case supporting rule_1.')
    support_2: Support = Field(description='Update case supporting rule_2.')
    support_3: Support = Field(description='Update case supporting rule_3.')
    support_4: Support = Field(description='Update case supporting rule_4.')
    rationale: StrictStr = Field(max_length=2000,
        description='Brief explanation archived by the host only; never rendered into the repair policy.')

    @classmethod
    def to_mcp_schema(cls):
        schema = super().to_mcp_schema()
        original = cls.model_json_schema()
        for key in schema['properties']:
            schema['properties'][key].update(copy.deepcopy(original['properties'][key]))
        schema['additionalProperties'] = False
        return schema

    @model_validator(mode='after')
    def bounded_utf8(self):
        try:
            encoded = json.dumps(self.model_dump(), ensure_ascii=False, allow_nan=False).encode('utf-8')
        except (ValueError, TypeError, OverflowError, RecursionError, UnicodeError) as error:
            raise ValueError('Policy submission must be finite UTF-8 JSON') from error
        if len(encoded) > 8192:
            raise ValueError('Policy submission exceeds 8192 UTF-8 bytes')
        return self


class PolicyObservation(Observation):
    feedback: dict = Field(default_factory=dict)


class _PolicyExecutor(ToolExecutor[PolicyAction, PolicyObservation]):
    def __init__(self, controller):
        self.controller = controller

    def __call__(self, action, conversation=None):
        try:
            action = PolicyAction.model_validate(action.model_dump())
            values = {key: getattr(action, key) for key in (
                'rule_1', 'rule_2', 'rule_3', 'rule_4', 'support_1', 'support_2',
                'support_3', 'support_4', 'rationale')}
            feedback = self.controller.submit_policy(**values)
            text = json.dumps(feedback, ensure_ascii=False, allow_nan=False, sort_keys=True)
            return PolicyObservation.from_text(text, feedback=feedback)
        except Exception as error:
            # SDK catches tool exceptions. Preserve fatal host state so a normal
            # iteration-limit result cannot authorize subsequent evaluation.
            self.controller.halted = True
            error_type = type(error).__name__
            if re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,127}', error_type) is None:
                error_type = 'Exception'
            self.controller.infrastructure_error_type = error_type
            try:
                write_json(Path(self.controller.output_dir) / 'controller-error.json', {
                    'status': 'infrastructure_error', 'error_kind': 'policy_executor_exception',
                    'error_type': error_type})
            except Exception:
                pass
            raise


def policy_tool(controller, session_id):
    class PolicyTool(ToolDefinition[PolicyAction, PolicyObservation]):
        name: ClassVar[str] = 'submit_policy'

        @classmethod
        def create(cls, conv_state=None, **params):
            if params:
                raise ValueError('Policy tool accepts no initialization options')
            return [cls(action_type=PolicyAction, observation_type=PolicyObservation,
                executor=_PolicyExecutor(controller),
                description=('Submit one ordered selection of four rules from R01 through R08, '
                    'with update-case support U-P, U-S, or both for each. The host validates '
                    'and freezes the policy. Rationale is host-only archival text. This tool '
                    'cannot execute candidate programs or formulas, read files, or evaluate tasks.'))]

    name = 'PolicySubmit_' + session_id
    register_tool(name, PolicyTool)
    return Tool(name=name)


class PolicyStatePacketLLM(StatePacketLLM):
    _pilot_allowed_tools: ClassVar[frozenset[str]] = frozenset({'submit_policy', 'finish'})

    def _observe_submission_schema(self, response):
        calls = response.choices[0].message.tool_calls
        if not calls or calls[0].function.name != 'submit_policy':
            return
        try:
            arguments = parse_tool_call_arguments(calls[0].function.arguments)
            _, arguments = normalize_tool_call('submit_policy', arguments, ('submit_policy', 'finish'))
            arguments = fix_malformed_tool_arguments(arguments, PolicyAction)
            arguments.pop('security_risk', None)
            arguments.pop('summary', None)
            PolicyAction.model_validate(arguments)
        except (ValueError, TypeError, OverflowError, RecursionError):
            self._last_submission_schema_error = 'policy_submission_schema'
            self._active_input_audit['response_tool_validation'] = {
                'status': 'invalid_request', 'error_kind': 'policy_submission_schema'}
        else:
            self._last_submission_schema_error = None
            self._active_input_audit['response_tool_validation'] = {'status': 'valid_submission'}


def run_policy_session(controller, llm, session_id, output_dir):
    """Exactly one SDK iteration; callers separately require a frozen valid policy."""
    return run_session(controller, llm, session_id, output_dir, tool_factory=policy_tool,
                       max_iterations=1, purpose='policy')
