"""One bounded SDK submission for probe registration or subsequent revision.

The trusted runner owns phase freezes, probe execution and paired inputs. This
adapter neither executes probes nor interprets auxiliary predictions. It keeps
the original provider response and the SDK-normalized submission distinct.
"""
import copy
import importlib.metadata
import json
import math
import os
from pathlib import Path
import re
from typing import Any, ClassVar
from unittest.mock import patch

from openhands.sdk import Action, Agent, Observation, Tool, ToolDefinition
from openhands.sdk.agent.utils import (
    fix_malformed_tool_arguments, normalize_tool_call, parse_tool_call_arguments,
)
from openhands.sdk.tool import ToolExecutor, register_tool
from pydantic import Field, PrivateAttr, StrictInt, StrictStr, field_validator, model_validator

from .checked_agent import StatePacketLLM
from .pilot_agent import ControlledPilotConversation, safe_error_metadata, write_json


PROBE_SYSTEM_PROMPT = """You are registering one scoped executable check for a development revision.
The task packet binds the current artifact, allowed probe and target identifiers.
You have exactly one model request. Use submit_probe now with one supplied probe
and target identifier. Put any expected result or explanation in auxiliary.
The host executes the registered check only after this submission is frozen.
Do not submit candidate source, invent tool results, or claim a hypothesis is
verified before the external check. Do not read files, access networks, create
processes or use another task. These are development observations, not held-out
results or proof of an effective self-improvement method.
"""

REVISION_SYSTEM_PROMPT = """You are making one revision after a frozen check registration.
The task packet binds the starting artifact, registration and available evidence.
You have exactly one model request and at most one candidate submission. Use
submit_candidate now with complete source and its parameter count. Inspect any
visible probe feedback within its stated scope; an unavailable result is not a
successful check. Explain your edit and uncertainty briefly in rationale and
place optional predictions in auxiliary. Do not claim the new candidate has
succeeded before evaluation. Do not read files, access networks, create processes
or exploit the evaluator. These are development observations, not held-out results
or proof of an effective self-improvement method.
"""


def _finite_json(value, depth=0):
    if depth > 20:
        raise ValueError('Submission JSON nesting exceeds 20')
    kind = type(value)
    if value is None or kind in (str, bool, int):
        return
    if kind is float and math.isfinite(value):
        return
    if kind is list:
        for item in value:
            _finite_json(item, depth+1)
        return
    if kind is dict and all(type(key) is str for key in value):
        for item in value.values():
            _finite_json(item, depth+1)
        return
    raise ValueError('Submission must contain finite JSON values')


class _SubmissionAction(Action):
    @classmethod
    def to_mcp_schema(cls):
        schema = super().to_mcp_schema()
        original = cls.model_json_schema()
        # Keep authored primitive bounds and the open finite-JSON auxiliary
        # object through SDK 1.55.1's generic schema simplifier. Never restore
        # its internal action discriminator as a model-facing business field.
        for key in schema['properties']:
            schema['properties'][key] = copy.deepcopy(original['properties'][key])
        schema['additionalProperties'] = False
        return schema

    @model_validator(mode='after')
    def bounded_business_json(self):
        try:
            values = self.model_dump(exclude={'kind'})
            _finite_json(values)
            encoded = json.dumps(values, ensure_ascii=False, allow_nan=False,
                sort_keys=True, separators=(',', ':')).encode('utf-8')
        except (ValueError, TypeError, UnicodeError, OverflowError, RecursionError) as error:
            raise ValueError('Submission must be finite UTF-8 JSON') from error
        if len(encoded) > 65536:
            raise ValueError('Submission exceeds 65536 canonical UTF-8 bytes')
        return self


class ProbeAction(_SubmissionAction):
    probe_id: StrictStr = Field(min_length=1, max_length=128,
        description='Copy one allowed probe identifier from the supplied task packet.')
    target_id: StrictStr = Field(min_length=1, max_length=128,
        description='Copy one allowed target identifier bound to the starting artifact.')
    auxiliary: dict[str, Any] = Field(default_factory=dict,
        description=('Optional finite JSON object containing expected result, scoped hypothesis '
            'and uncertainty. Prediction semantics are recorded, not transport requirements.'))

    @field_validator('probe_id', 'target_id')
    @classmethod
    def nonblank_identifier(cls, value):
        if not value.strip():
            raise ValueError('Identifier cannot be blank')
        return value


class RevisionAction(_SubmissionAction):
    source: StrictStr = Field(min_length=1, max_length=16384,
        description='Complete candidate Python source, at most 16384 UTF-8 bytes.')
    n_params: StrictInt = Field(ge=0, le=16,
        description='Number of independent formula parameters; use the packet convention for planning.')
    rationale: StrictStr = Field(default='', max_length=4000,
        description='Unverified explanation of the one edit, its evidence and uncertainty.')
    auxiliary: dict[str, Any] = Field(default_factory=dict,
        description='Optional finite JSON predictions or declarations, archived without semantic coercion.')

    @field_validator('source')
    @classmethod
    def bounded_source(cls, value):
        try:
            valid = bool(value.strip()) and len(value.encode('utf-8')) <= 16384
        except UnicodeError as error:
            raise ValueError('Source must be UTF-8 text') from error
        if not valid:
            raise ValueError('Source must be nonempty and at most 16384 UTF-8 bytes')
        return value


class TwoStageObservation(Observation):
    feedback: dict = Field(default_factory=dict)


class _PacketView:
    def __init__(self, controller):
        self.controller = controller

    def state_packet(self):
        return self.controller.task_packet()


class _TwoStagePacketLLM(StatePacketLLM):
    _business_controller: object = PrivateAttr(default=None)
    _business_action: ClassVar[type[Action]]
    _business_tool: ClassVar[str]

    def bind_controller(self, controller):
        if not callable(getattr(controller, 'task_packet', None)):
            raise ValueError('Two-stage controller requires task_packet')
        self._business_controller = controller
        return super().bind_controller(_PacketView(controller))

    def _observe_submission_schema(self, response):
        calls = response.choices[0].message.tool_calls
        if not calls or calls[0].function.name != self._business_tool:
            return
        try:
            arguments = parse_tool_call_arguments(calls[0].function.arguments)
            _, arguments = normalize_tool_call(self._business_tool, arguments,
                                               (self._business_tool, 'finish'))
            arguments = fix_malformed_tool_arguments(arguments, self._business_action)
            arguments.pop('security_risk', None)
            arguments.pop('summary', None)
            self._business_action.model_validate(arguments)
        except (ValueError, TypeError, OverflowError, RecursionError):
            self._last_submission_schema_error = 'two_stage_submission_schema'
            self._active_input_audit['response_tool_validation'] = {
                'status': 'invalid_request', 'error_kind': 'two_stage_submission_schema'}
        else:
            self._last_submission_schema_error = None
            self._active_input_audit['response_tool_validation'] = {'status': 'valid_submission'}


class ProbeStatePacketLLM(_TwoStagePacketLLM):
    _pilot_allowed_tools: ClassVar[frozenset[str]] = frozenset({'submit_probe', 'finish'})
    _business_action: ClassVar[type[Action]] = ProbeAction
    _business_tool: ClassVar[str] = 'submit_probe'


class RevisionStatePacketLLM(_TwoStagePacketLLM):
    _pilot_allowed_tools: ClassVar[frozenset[str]] = frozenset({'submit_candidate', 'finish'})
    _business_action: ClassVar[type[Action]] = RevisionAction
    _business_tool: ClassVar[str] = 'submit_candidate'


class _SubmissionExecutor(ToolExecutor):
    def __init__(self, controller, session_id, stage, output_dir):
        self.controller = controller
        self.session_id = session_id
        self.stage = stage
        self.output_dir = Path(output_dir)

    def __call__(self, action, conversation=None):
        try:
            action_type = ProbeAction if self.stage == 'probe' else RevisionAction
            action = action_type.model_validate(action.model_dump())
            # Persist exactly the business values accepted by the installed
            # SDK before the controller can register or execute anything. The
            # immutable raw provider response remains a separate artifact: SDK
            # repairs/defaults can legitimately make these values differ.
            submission = {'stage': self.stage,
                'tool': 'submit_probe' if self.stage == 'probe' else 'submit_candidate',
                'session_id': self.session_id,
                'business': action.model_dump(exclude={'kind'})}
            encoded = (json.dumps(submission, ensure_ascii=False, allow_nan=False,
                sort_keys=True, separators=(',', ':'))+'\n').encode('utf-8')
            with (self.output_dir/'sdk-submission.json').open('xb') as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            if self.stage == 'probe':
                feedback = self.controller.submit_probe(self.session_id, action.probe_id,
                    action.target_id, action.auxiliary)
            else:
                feedback = self.controller.submit(self.session_id, action.source,
                    action.n_params, action.rationale, action.auxiliary)
            text = json.dumps(feedback, ensure_ascii=False, allow_nan=False, sort_keys=True)
            return TwoStageObservation.from_text(text, feedback=feedback)
        except Exception as error:
            # SDK turns executor failures into events and may then report only
            # iteration exhaustion. Preserve fatal host state independently.
            self.controller.halted = True
            error_type = type(error).__name__
            if re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,127}', error_type) is None:
                error_type = 'Exception'
            self.controller.infrastructure_error_type = error_type
            try:
                write_json(self.output_dir/'controller-error.json', {
                    'status': 'infrastructure_error', 'stage': self.stage,
                    'error_kind': 'two_stage_executor_exception', 'error_type': error_type})
            except Exception:
                pass
            raise


def _submission_tool(controller, session_id, output_dir, stage):
    action_type = ProbeAction if stage == 'probe' else RevisionAction
    tool_name = 'submit_probe' if stage == 'probe' else 'submit_candidate'
    description = (
        'Register exactly one allowed probe and target. The host binds source and task, '
        'archives this request, and executes the check after phase freezing. This tool '
        'does not read files or run candidate programs. Auxiliary predictions are unverified.'
        if stage == 'probe' else
        'Submit exactly one complete candidate for the fixed development task. The host '
        'archives and evaluates it with the existing isolated evaluator. Task identities, '
        'paths and execution settings are not model arguments. Auxiliary predictions are unverified.')

    class SubmissionTool(ToolDefinition):
        name: ClassVar[str] = tool_name

        @classmethod
        def create(cls, conv_state=None, **params):
            if params:
                raise ValueError('Two-stage tool accepts no initialization options')
            return [cls(action_type=action_type, observation_type=TwoStageObservation,
                executor=_SubmissionExecutor(controller, session_id, stage, output_dir),
                description=description)]

    registry_name = 'TwoStage_' + stage + '_' + session_id
    register_tool(registry_name, SubmissionTool)
    return Tool(name=registry_name)


def _validate_binding(controller, llm, session_id, output_dir, stage):
    expected_class = {'probe': ProbeStatePacketLLM, 'revision': RevisionStatePacketLLM}.get(stage)
    if expected_class is None or type(llm) is not expected_class:
        raise ValueError('Unknown stage or mismatched trusted LLM class')
    if (llm._business_controller is not controller or llm._pilot_session != session_id
            or llm._pilot_output != Path(output_dir)/'requests'
            or llm._pilot_ledger is None
            or llm._pilot_ledger.config['max_requests_per_session'] != 1):
        raise ValueError('Two-stage session, controller, output or request cap binding mismatch')
    if importlib.metadata.version('openhands-sdk') != '1.55.1':
        raise RuntimeError('Two-stage lifecycle adapter requires OpenHands SDK 1.55.1')


def _create_conversation(controller, llm, session_id, output_dir, stage, callback):
    expected_tools = {'submit_probe', 'finish'} if stage == 'probe' else {'submit_candidate', 'finish'}
    if llm._pilot_allowed_tools != expected_tools:
        raise ValueError('Stage and trusted tool allowlist differ')
    agent = Agent(llm=llm, tools=[_submission_tool(controller, session_id, output_dir, stage)],
        include_default_tools=['FinishTool'],
        system_prompt=PROBE_SYSTEM_PROMPT if stage == 'probe' else REVISION_SYSTEM_PROMPT,
        agent_context=None, mcp_config={}, condenser=None, critic=None, tool_concurrency_limit=1)
    conversation = ControlledPilotConversation(agent,
        workspace=output_dir/'workspace', persistence_dir=None, callbacks=[callback],
        max_iteration_per_run=1, stuck_detection=False, visualizer=None,
        plugins=[], delete_on_close=False, profile_store_dir=output_dir/'empty-profiles')
    try:
        with patch('openhands.sdk.agent.base.has_vision_profile_available', return_value=False):
            conversation.send_message(controller.task_prompt())
        if (set(conversation.agent.tools_map) != expected_tools
                or conversation.agent.mcp_config or conversation.agent.agent_context is not None
                or conversation._hook_processor is not None):
            raise RuntimeError('Unexpected two-stage tools or ambient context')
    except Exception:
        conversation.close()
        raise
    return conversation


def run_two_stage_session(controller, llm, session_id, output_dir, *, stage):
    """Run one SDK iteration. Submission availability remains a host judgment.

    Bind the stage-specific LLM using
    ``ProbeStatePacketLLM(**settings).bind_controller(controller).bind_pilot(
    ledger, session_id, Path(output_dir)/'requests')``; use
    ``RevisionStatePacketLLM`` analogously for the revision stage.
    ``settings`` must use the project's frozen public configuration; this module
    never discovers credentials or selects a provider.
    """
    output_dir = Path(output_dir)
    _validate_binding(controller, llm, session_id, output_dir, stage)
    output_dir.mkdir(parents=True, exist_ok=True)
    events_path = output_dir/'events.jsonl'
    if events_path.exists() or (output_dir/'session-summary.json').exists():
        raise FileExistsError('Refusing to overwrite a two-stage session')

    def record(event):
        value = {'type': type(event).__name__, 'source': getattr(event, 'source', None)}
        if type(event).__name__ == 'ConversationErrorEvent':
            value['code'] = getattr(event, 'code', None)
        else:
            for key in ('tool_name', 'tool_call_id', 'llm_response_id'):
                if getattr(event, key, None) is not None:
                    value[key] = getattr(event, key)
        with events_path.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(value, ensure_ascii=False, allow_nan=False)+'\n')

    conversation = None
    result = {'session_id': session_id, 'stage': stage, 'status': 'error',
              'model_error_type': None, 'sdk_version': importlib.metadata.version('openhands-sdk')}
    try:
        conversation = _create_conversation(controller, llm, session_id, output_dir, stage, record)
        result['tools'] = sorted(conversation.agent.tools_map)
        conversation.run()
        result['conversation_status'] = str(conversation.state.execution_status)
        result['status'] = ('completed' if result['conversation_status'].lower().endswith('finished')
                            else 'stopped')
    except Exception as error:
        result['model_error_type'] = type(error).__name__
        result.update(safe_error_metadata(error))
        if error.__cause__ is not None:
            result['cause_type'] = type(error.__cause__).__name__
    finally:
        if conversation is not None:
            conversation.close()
        result['controller'] = controller.summary()
        write_json(output_dir/'session-summary.json', result)
    return result
