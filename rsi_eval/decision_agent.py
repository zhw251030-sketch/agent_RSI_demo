"""SDK 1.55.1 single-request decision using the unchanged revision tool schema.

Only the system prompt and lifecycle wrapper are new. The old revision action,
LLM capture/budget boundary and pre-dispatch SDK submission evidence are reused.
This module never monkeypatches historical prompt globals or selects credentials.
"""
import importlib.metadata
import json
from pathlib import Path
from unittest.mock import patch

from openhands.sdk import Agent
from .pilot_agent import ControlledPilotConversation, safe_error_metadata, write_json
from .two_stage_agent import RevisionStatePacketLLM, _submission_tool, _validate_binding


DECISION_SYSTEM_PROMPT = """You are deciding whether to keep or revise one development artifact.
The task packet binds the current artifact and any available archived diagnostic
evidence. A diagnostic intervention is temporary; it is not an instruction to
deploy that intervention. Keeping the starting artifact unchanged is legal.
There is no registered planned edit to follow. Evidence against deleting a term
does not establish that adding another term is useful.
You have exactly one model request and at most one candidate submission. Use
submit_candidate with complete source and its parameter count, including when
keeping the original. Explain the decision and uncertainty briefly in rationale;
put optional predictions inside auxiliary using the supplied JSON examples.
An absent or unknown observation is not a successful check. Do not claim your
candidate has succeeded before evaluation. Do not read files, access networks,
create processes or exploit the evaluator. These are development observations,
not held-out results or proof of an effective self-improvement method.
"""


def _create_conversation(controller, llm, session_id, output_dir, callback):
    expected_tools = {'submit_candidate', 'finish'}
    if llm._pilot_allowed_tools != expected_tools:
        raise ValueError('Decision tool allowlist differs')
    agent = Agent(llm=llm,
        tools=[_submission_tool(controller, session_id, output_dir, 'revision')],
        include_default_tools=['FinishTool'], system_prompt=DECISION_SYSTEM_PROMPT,
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
            raise RuntimeError('Unexpected decision tools or ambient context')
    except Exception:
        conversation.close()
        raise
    return conversation


def run_decision_session(controller, llm, session_id, output_dir):
    """Run one model request; only an actual dispatched artifact is a candidate."""
    output_dir = Path(output_dir)
    _validate_binding(controller, llm, session_id, output_dir, 'revision')
    output_dir.mkdir(parents=True, exist_ok=True)
    events_path = output_dir/'events.jsonl'
    if events_path.exists() or (output_dir/'session-summary.json').exists():
        raise FileExistsError('Refusing to overwrite a decision session')

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
    result = {'session_id': session_id, 'stage': 'revision', 'decision_protocol': 'decision-replay-v0.1',
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
