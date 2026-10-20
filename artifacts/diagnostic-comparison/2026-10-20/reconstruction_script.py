"""Offline-only request reconstruction: never imports authentication helpers.

Uses saved responses and saved feedback. Socket connects and candidate evaluation
are blocked; the capture ledger is in memory and the original run is read-only.
"""
from pathlib import Path
import contextlib
import copy
import hashlib
import json
import logging
import os
import tempfile
from unittest.mock import patch

ROOT = Path('/home/hanwen/Project/project/agent_RSI_demo')
RUN = ROOT / 'runs/diagnostic-comparison/20261020-diagnostic-comparison-v01'
SESSION = RUN / 'planning_B'
os.chdir(ROOT)
os.environ['LITELLM_LOCAL_MODEL_COST_MAP'] = 'True'
import sys
sys.path.insert(0, str(ROOT))


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False).encode('utf-8')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def run_hashes():
    return {str(path.relative_to(RUN)): digest(path.read_bytes())
            for path in RUN.rglob('*') if path.is_file()}


before = run_hashes()
request_paths = sorted((SESSION / 'requests').glob('*.request.json'))
response_paths = sorted((SESSION / 'requests').glob('*.response.json'))
requests = [json.loads(path.read_text()) for path in request_paths]
responses = [json.loads(path.read_text()) for path in response_paths]
records = json.loads((SESSION / 'candidates.json').read_text())
prompt = (SESSION / 'task-prompt.txt').read_text()
summary = json.loads((RUN / 'summary.json').read_text())
original_ledger = json.loads((RUN / 'budget-ledger.json').read_text())
assert len(requests) == len(responses) == 3
assert len(records) == 4
output = Path(tempfile.mkdtemp(prefix='planning-b-request-reconstruction-', dir=ROOT / 'tmp'))

with contextlib.ExitStack() as stack:
    socket_guard = stack.enter_context(patch('socket.socket.connect', side_effect=AssertionError('Offline replay: network blocked')))
    stack.enter_context(patch('socket.socket.connect_ex', side_effect=AssertionError('Offline replay: network blocked')))
    stack.enter_context(patch('socket.create_connection', side_effect=AssertionError('Offline replay: network blocked')))
    from litellm.types.utils import ModelResponse
    from rsi_eval.pilot_agent import BoundedPilotLLM, run_session
    from rsi_eval.pilot_budget import BudgetExceeded
    stack.enter_context(patch('rsi_eval.executor.evaluate_candidate', side_effect=AssertionError('Offline replay: evaluation blocked')))
    logging.disable(logging.CRITICAL)

    class SavedController:
        def __init__(self):
            self.calls = []

        def task_prompt(self):
            return prompt

        def submit(self, source, n_params=3, rationale=''):
            index = len(self.calls)
            assert index < 3, 'Unexpected offline candidate submission'
            expected = json.loads(responses[index]['choices'][0]['message']['tool_calls'][0]['function']['arguments'])
            assert source == expected['source']
            assert n_params == expected.get('n_params', 3)
            assert rationale == expected.get('rationale', '')
            assert digest(source.encode()) == records[index+1]['source_sha256']
            self.calls.append({'source_sha256': digest(source.encode()), 'saved_record': index+1})
            return copy.deepcopy(records[index+1])

        def summary(self):
            return {'offline_saved_feedback_replay': True, 'generated_candidates': len(self.calls),
                    'new_candidate_executions': 0}

    class CaptureLedger:
        def __init__(self):
            self.captured = []
            self.settlements = []

        def reserve(self, session_id, payload, output_tokens):
            assert session_id == 'planning_B'
            index = len(self.captured)
            assert index < 4, 'Unexpected fifth request'
            data = canonical(payload)
            entry = {'ordinal': index+1, 'input_bytes': len(data), 'payload_sha256': digest(data),
                     'output_tokens': output_tokens}
            if index < 3:
                expected = canonical(requests[index])
                entry['matches_original_payload_bytes'] = data == expected
                entry['original_payload_sha256'] = digest(expected)
                self.captured.append(entry)
                assert data == expected, 'First three reconstructed requests must match saved bytes exactly'
                return 'offline-' + str(index+1)
            self.captured.append(entry)
            (output / 'reconstructed-fourth-payload.json').write_bytes(data)
            assert len(data) > original_ledger['config']['max_input_bytes'], 'Fourth input did not exceed cap'
            raise BudgetExceeded('input byte cap exceeded')

        def settle(self, request_id, usage, error_type=None):
            self.settlements.append({'request_id': request_id, 'usage': usage, 'error_type': error_type})

    transport_responses = [ModelResponse(id=item['response_id'], model=requests[0]['model'],
                                        choices=item['choices'], usage=item['usage'])
                           for item in responses]
    transport = stack.enter_context(patch('openhands.sdk.llm.llm.litellm_completion', side_effect=transport_responses))
    stack.enter_context(patch('openhands.sdk.conversation.impl.local_conversation.load_available_plugins', side_effect=AssertionError('No ambient plugins')))
    stack.enter_context(patch('openhands.sdk.conversation.impl.local_conversation.register_file_agents', side_effect=AssertionError('No ambient agents')))
    controller, ledger = SavedController(), CaptureLedger()
    configuration = dict(summary['effective_model_config'])
    configuration['base_url'] = 'https://example.invalid'
    configuration['api_key'] = 'offline-placeholder-not-a-real-key'
    llm = BoundedPilotLLM(**configuration).bind_pilot(ledger, 'planning_B', output / 'requests')
    result = run_session(controller, llm, 'planning_B', output)
    assert transport.call_count == 3, 'Only three recorded model responses may be consumed'
    assert len(ledger.captured) == 4, 'Fourth payload was not reconstructed'
    assert len(controller.calls) == 3
    assert socket_guard.call_count == 0, 'A network connection was attempted'

assert before == run_hashes(), 'Original run files changed'
cap = original_ledger['config']['max_input_bytes']
fourth = ledger.captured[-1]
evidence = {
    'label': 'Offline SDK reconstruction; fourth payload was not captured during the original run',
    'run_id': RUN.name, 'session_id': 'planning_B', 'sdk_version': result['sdk_version'],
    'method': 'Replayed three saved ModelResponses and exact saved tool feedback through real SDK and BoundedPilotLLM; in-memory capture ledger; socket connections and evaluator blocked.',
    'requests': ledger.captured,
    'fourth_input_cap_bytes': cap, 'fourth_input_over_cap_bytes': fourth['input_bytes'] - cap,
    'reconstructed_stop': {key: result.get(key) for key in ('status', 'model_error_type', 'cause_type')},
    'saved_response_transport_calls': transport.call_count,
    'new_model_calls': 0, 'new_candidate_executions': 0,
    'original_run_files_unchanged': True, 'original_run_file_count': len(before),
    'input_artifacts_sha256': {str(path.relative_to(RUN)): before[str(path.relative_to(RUN))]
                               for path in request_paths + response_paths + [SESSION/'candidates.json', SESSION/'task-prompt.txt']},
    'original_run_hashes_sha256': digest(canonical(before)),
    'script_sha256': digest(Path(__file__).read_bytes()),
}
(output / 'reconstruction-evidence.json').write_text(json.dumps(evidence, indent=2) + '\n')
print(json.dumps({'output_directory': str(output), 'evidence': evidence}, indent=2))
