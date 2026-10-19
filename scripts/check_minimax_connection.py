#!/usr/bin/env python3
"""Make at most two LLM calls to verify a harmless in-memory tool round trip.

No shell/file tool is exposed. Each response is capped at 256 tokens and the
model client has automatic retries disabled. This is not a research benchmark.
"""
import argparse
import contextlib
import importlib.metadata
import io
import json
import logging
import os
from pathlib import Path

os.environ['LITELLM_LOCAL_MODEL_COST_MAP'] = 'True'
os.environ['OPENHANDS_SUPPRESS_BANNER'] = '1'
os.environ['DO_NOT_TRACK'] = '1'

from configure_minimax import CONFIG, auth_path, read_key

ATTEMPTED_REQUESTS = 0
PROGRESS = {}


def check(source):
    global ATTEMPTED_REQUESTS
    from openhands.sdk import LLM, Message, TextContent
    from openhands.sdk.tool import Action, ToolDefinition

    class AddNumbersAction(Action):
        a: int
        b: int

    class AddNumbersTool(ToolDefinition):
        @classmethod
        def create(cls, *args, **kwargs):
            return [cls(description='Add two integers in memory.', action_type=AddNumbersAction)]

    config = json.loads(CONFIG.read_text())
    config.update(api_key=read_key(source), max_output_tokens=256, num_retries=0)
    llm = LLM(**config)
    tool = AddNumbersTool.create()[0]
    messages = [Message(role='user', content=[TextContent(
        text='Use the provided tool to add 19 and 23. After receiving the tool result, reply with only the resulting integer.')])]
    ATTEMPTED_REQUESTS += 1
    first = llm.completion(messages, tools=[tool], tool_choice='required')
    calls = first.message.tool_calls
    PROGRESS['tool_count'] = len(calls or [])
    PROGRESS['expected_tool'] = tool.name
    PROGRESS['returned_tools'] = [call.name for call in calls or []]
    PROGRESS['first_reply'] = ''.join(x.text for x in first.message.content if isinstance(x, TextContent))
    assert calls and len(calls) == 1 and calls[0].name == tool.name, 'tool selection'
    action = AddNumbersAction.model_validate_json(calls[0].arguments)
    PROGRESS['arguments'] = {'a': action.a, 'b': action.b}
    assert (action.a, action.b) == (19, 23), 'tool arguments'
    total = action.a + action.b
    messages.extend([first.message, Message(role='tool', tool_call_id=calls[0].id,
        name=tool.name, content=[TextContent(text=str(total))])])
    ATTEMPTED_REQUESTS += 1
    second = llm.completion(messages, tools=[tool], tool_choice='none')
    reply = ''.join(x.text for x in second.message.content if isinstance(x, TextContent)).strip()
    PROGRESS['final_reply'] = reply
    assert reply == '42', 'final answer'
    usage = []
    for response in (first, second):
        raw_usage = response.raw_response.usage
        usage.append({name: getattr(raw_usage, name, None)
                      for name in ('prompt_tokens', 'completion_tokens', 'total_tokens')})
    return {'passed': True, 'sdk_version': importlib.metadata.version('openhands-sdk'),
            'model': config['model'], 'base_url': config['base_url'],
            'thinking': 'disabled', 'tool_arguments_valid': True,
            'tool_result': total, 'final_reply': reply, 'llm_requests': 2,
            'agent_rollouts': 0, 'output_cap_per_request': 256, 'usage': usage}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--auth-file')
    parser.add_argument('--output', required=True, help='Path for sanitized verification JSON.')
    args = parser.parse_args()
    # Suppress third-party diagnostic output, which can include request details.
    logging.disable(logging.CRITICAL)
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            report = check(auth_path(args.auth_file))
    except Exception as error:
        report = {'passed': False, 'error_type': type(error).__name__,
                  'attempted_requests': ATTEMPTED_REQUESTS,
                  'http_status': getattr(error, 'status_code', None),
                  'progress': PROGRESS}
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report['passed'] else 1)
