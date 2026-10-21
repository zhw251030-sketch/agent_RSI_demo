"""One cold-start source submission through OpenHands SDK 1.55.1.

Only an actual SDK tool dispatch may produce a source archive. This adapter
never evaluates a program, selects a strategy, or infers a submission from text.
The controller owns source.py/candidate.json; transport and normalized SDK
receipts are separate records. Historical adapters are reused without edits.
"""
import importlib.metadata
import json
import os
from pathlib import Path
import re
from typing import ClassVar
from unittest.mock import patch

from openhands.sdk import Agent, Tool, ToolDefinition
from openhands.sdk.tool import ToolExecutor, register_tool
from pydantic import Field, StrictInt, StrictStr, field_validator

from .pilot_agent import ControlledPilotConversation, safe_error_metadata, write_json
from .two_stage_agent import _SubmissionAction, _TwoStagePacketLLM, TwoStageObservation

VERSION = 'state-generation-agent-v0.1'
GENERATION_SYSTEM_PROMPT = """Generate one initial Python artifact from the supplied task specification.
This is cold-start generation. There is no earlier candidate, task score, probe
feedback, or strategy update in this session. You have exactly one model request.
Use submit_candidate once with only source and n_params: the complete source and
its parameter count, following the packet's interface and planning convention.
The trusted controller only archives your source; it does not execute or evaluate
it in this stage. Do not claim tests have run or that the artifact has succeeded.
Do not read files, access networks, create processes, or exploit an evaluator.
The finish tool ends the session without creating a candidate. A missing source
is recorded as missing, never reconstructed from prose or a claimed result.
"""
TOOL_DESCRIPTION = """Archive exactly one complete initial source and parameter count. The controller stores source.py and candidate.json without executing, evaluating, repairing, or scoring the source."""


class GenerationAction(_SubmissionAction):
    source: StrictStr = Field(min_length=1, max_length=16384,
        description='Complete initial Python source, at most 16384 UTF-8 bytes.')
    n_params: StrictInt = Field(ge=0, le=16,
        description='Number of independent formula parameters; use zero for planning.')

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


def _packet_bytes(controller):
    packet = controller.task_packet()
    if type(packet) is not dict:
        raise ValueError('Generation packet must be an object')
    try:
        encoded = json.dumps(packet, ensure_ascii=False, allow_nan=False,
            sort_keys=True, separators=(',', ':')).encode('utf-8')
    except (ValueError, TypeError, UnicodeError, OverflowError, RecursionError) as error:
        raise ValueError('Generation packet must be finite UTF-8 JSON') from error
    if len(encoded) > 65536:
        raise ValueError('Generation packet exceeds 65536 bytes')
    return encoded


class _FrozenPacketView:
    def __init__(self, controller):
        self.controller = controller
        self.encoded = _packet_bytes(controller)

    def state_packet(self):
        if _packet_bytes(self.controller) != self.encoded:
            raise ValueError('Generation packet changed after binding')
        return json.loads(self.encoded)


class GenerationStatePacketLLM(_TwoStagePacketLLM):
    _pilot_allowed_tools: ClassVar[frozenset[str]] = frozenset({'submit_candidate', 'finish'})
    _business_action: ClassVar[type[_SubmissionAction]] = GenerationAction
    _business_tool: ClassVar[str] = 'submit_candidate'

    def bind_controller(self, controller):
        frozen = _FrozenPacketView(controller)
        super().bind_controller(controller)
        self._state_controller = frozen
        return self


class _GenerationExecutor(ToolExecutor):
    def __init__(self, controller, llm, session_id, output_dir):
        self.controller = controller
        self.llm = llm
        self.session_id = session_id
        self.output_dir = output_dir

    def __call__(self, action, conversation=None):
        try:
            action = GenerationAction.model_validate(action.model_dump())
            business = action.model_dump(exclude={'kind'})
            receipt = {'stage': 'generation', 'tool': 'submit_candidate',
                       'session_id': self.session_id, 'business': business}
            encoded = (json.dumps(receipt, ensure_ascii=False, allow_nan=False,
                sort_keys=True, separators=(',', ':'))+'\n').encode('utf-8')
            # This certifies SDK dispatch, not controller acceptance or execution.
            with (self.output_dir/'sdk-submission.json').open('xb') as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            self.llm._state_controller.state_packet()
            budget = self.llm._pilot_ledger.summary()
            if (budget['halted'] or budget['reserved_count'] or budget['usage_unknown_count']
                    or budget['session_counts'].get(self.session_id) != 1):
                raise RuntimeError('Submission requires one settled request with known usage')
            if self.controller.halted or self.controller.candidate is not None:
                raise RuntimeError('Generation controller already halted or submitted')
            feedback = self.controller.submit(self.session_id, business['source'], business['n_params'])
            text = json.dumps(feedback, ensure_ascii=False, allow_nan=False, sort_keys=True)
            return TwoStageObservation.from_text(text, feedback=feedback)
        except Exception as error:
            self.controller.halted = True
            error_type = type(error).__name__
            if re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,127}', error_type) is None:
                error_type = 'Exception'
            self.controller.infrastructure_error_type = error_type
            try:
                write_json(self.output_dir/'controller-error.json', {
                    'status': 'infrastructure_error', 'stage': 'generation',
                    'error_kind': 'generation_executor_exception', 'error_type': error_type})
            except Exception:
                pass
            raise


def _submission_tool(controller, llm, session_id, output_dir):
    class GenerationTool(ToolDefinition):
        name: ClassVar[str] = 'submit_candidate'

        @classmethod
        def create(cls, conv_state=None, **params):
            if params:
                raise ValueError('Generation tool accepts no initialization options')
            return [cls(action_type=GenerationAction, observation_type=TwoStageObservation,
                executor=_GenerationExecutor(controller, llm, session_id, output_dir),
                description=TOOL_DESCRIPTION)]

    registry_name = 'Generation_'+session_id
    register_tool(registry_name, GenerationTool)
    return Tool(name=registry_name)


def _validate_binding(controller, llm, session_id, output_dir):
    if type(llm) is not GenerationStatePacketLLM:
        raise ValueError('Generation requires its bounded LLM adapter')
    if (any(not callable(getattr(controller, method, None)) for method in
            ('task_packet', 'task_prompt', 'submit', 'summary'))
            or llm._business_controller is not controller or llm._pilot_session != session_id
            or llm._pilot_output != output_dir/'requests' or llm._pilot_ledger is None
            or Path(controller.output_dir) != output_dir
            or controller.halted or controller.candidate is not None):
        raise ValueError('Generation controller, session or output binding mismatch')
    config = llm._pilot_ledger.config
    if (config['max_requests_per_session'] != 1 or config['max_input_bytes'] > 65536
            or config['max_output_tokens'] != 8192 or llm.max_output_tokens != 8192):
        raise ValueError('Generation requires one request, at most 64 KiB input and 8192 output tokens')
    if any(path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction())
           for path in (output_dir/'requests', output_dir, *output_dir.parents)):
        raise ValueError('Symlinked generation output')
    llm._state_controller.state_packet()
    if importlib.metadata.version('openhands-sdk') != '1.55.1':
        raise RuntimeError('Generation adapter requires OpenHands SDK 1.55.1')


def _create_conversation(controller, llm, session_id, output_dir, callback):
    expected_tools = {'submit_candidate', 'finish'}
    if llm._pilot_allowed_tools != expected_tools:
        raise ValueError('Generation tool allowlist differs')
    agent = Agent(llm=llm, tools=[_submission_tool(controller, llm, session_id, output_dir)],
        include_default_tools=['FinishTool'], system_prompt=GENERATION_SYSTEM_PROMPT,
        agent_context=None, mcp_config={}, condenser=None, critic=None, tool_concurrency_limit=1)
    conversation = ControlledPilotConversation(agent, workspace=output_dir/'workspace',
        persistence_dir=None, callbacks=[callback], max_iteration_per_run=1,
        stuck_detection=False, visualizer=None, plugins=[], delete_on_close=False,
        profile_store_dir=output_dir/'empty-profiles')
    try:
        with patch('openhands.sdk.agent.base.has_vision_profile_available', return_value=False):
            conversation.send_message(controller.task_prompt())
        if (set(conversation.agent.tools_map) != expected_tools or conversation.agent.mcp_config
                or conversation.agent.agent_context is not None or conversation._hook_processor is not None):
            raise RuntimeError('Unexpected generation tools or ambient context')
    except Exception:
        conversation.close()
        raise
    return conversation


def run_generation_session(controller, llm, session_id, directory):
    """Run one cold-start request; a finish/no-call/invalid tool yields no source.

    Unknown usage halts acceptance. SDK receipts remain truthful even if the
    subsequent controller call fails; only controller.candidate means archived.
    """
    output_dir = Path(directory)
    _validate_binding(controller, llm, session_id, output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    events_path = output_dir/'events.jsonl'
    if events_path.exists() or (output_dir/'session-summary.json').exists():
        raise FileExistsError('Refusing to overwrite a generation session')

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
    result = {'session_id': session_id, 'stage': 'generation', 'adapter_version': VERSION,
              'status': 'error', 'model_error_type': None,
              'sdk_version': importlib.metadata.version('openhands-sdk')}
    try:
        conversation = _create_conversation(controller, llm, session_id, output_dir, record)
        result['tools'] = sorted(conversation.agent.tools_map)
        conversation.run()
        result['conversation_status'] = str(conversation.state.execution_status)
        result['status'] = ('completed' if result['conversation_status'].lower().endswith('finished') else 'stopped')
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
