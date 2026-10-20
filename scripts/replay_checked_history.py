#!/usr/bin/env python3
"""Replay the saved planning_B artifacts through the new real SDK boundary.

This is compatibility/size verification, not a new model run or task evaluation.
Three saved source/rationale arguments receive explicitly synthetic typed
declarations; a fourth synthetic response finishes the conversation. Saved
feedback replaces all candidate evaluation, and socket connections are blocked.
No model-configuration or credential helper is imported or read.
"""
import argparse
import contextlib
import copy
import hashlib
import io
import json
import logging
import os
from pathlib import Path
import sys
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OLD_RUN = ROOT / 'runs/diagnostic-comparison/20261020-diagnostic-comparison-v01/planning_B'
FIXTURE_USAGE = {'prompt_tokens': 100, 'completion_tokens': 20, 'total_tokens': 120}
INPUT_CAP = 98304
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False).encode('utf-8')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False,
                               indent=2) + '\n', encoding='utf-8')


def require(condition, message):
    # Explicit checks remain active under python -O.
    if not condition:
        raise ValueError(message)


def tree_hashes(directory):
    require(directory.is_dir(), 'Saved run directory is missing')
    result = {}
    for path in sorted(directory.rglob('*')):
        require(not path.is_symlink(), 'Saved run must not contain symlinks')
        if path.is_file():
            result[path.relative_to(directory).as_posix()] = digest(path.read_bytes())
    require(bool(result), 'Saved run directory is empty')
    return result


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def load_history(old_session):
    """Validate exact old candidate/response bindings before SDK construction."""
    records = read_json(old_session / 'candidates.json')
    diagnostics = read_json(old_session / 'diagnostics.json')
    response_paths = sorted((old_session / 'requests').glob('*.response.json'))
    require(type(records) is list and len(records) == 4, 'Expected baseline plus three old candidates')
    require(len(response_paths) == 3, 'Expected exactly three saved old responses')
    require([record['candidate_id'] for record in records] ==
            [f'planning-{index:03d}' for index in range(4)], 'Unexpected old candidate IDs')
    sources, submissions, feedback = [], [], {}
    task_ids = [f'spannerlearning/seed0/problem{index}' for index in range(10)]
    for record in records:
        source = (old_session / 'candidates' / (record['candidate_id'] + '.py')).read_text(encoding='utf-8')
        require(digest(source.encode('utf-8')) == record['source_sha256'], 'Saved candidate source hash mismatch')
        require([item['task_id'] for item in record['results']] == task_ids,
                'Saved candidate does not contain the fixed ten task results')
        sources.append(source)
        observations = diagnostics.get(record['candidate_id'], [])
        require(type(observations) is list and len(observations) == 2,
                'Expected two public diagnostic observations per old candidate')
        by_task = {item['task_id']: item for item in observations}
        require(set(by_task) == set(task_ids[:2]), 'Saved diagnostics must be exactly the two public tasks')
        for saved in record['results']:
            item = copy.deepcopy(saved)
            item.pop('diagnostics', None)
            if item['task_id'] in by_task:
                observation = copy.deepcopy(by_task[item['task_id']])
                require(observation['candidate_sha256'] == record['source_sha256'],
                        'Saved diagnostic source hash mismatch')
                # This field is added by DiagnosticController, not by the worker.
                observation.pop('evidence_ids', None)
                item['diagnostics'] = observation
            key = (record['source_sha256'], item['task_id'])
            require(key not in feedback, 'Duplicate old source/task binding is ambiguous')
            feedback[key] = item
    for index, path in enumerate(response_paths):
        response = read_json(path)
        require(len(response['choices']) == 1, 'Old response must have one choice')
        calls = response['choices'][0]['message'].get('tool_calls', [])
        require(len(calls) == 1 and calls[0]['function']['name'] == 'submit_candidate',
                'Old response must submit exactly one candidate')
        arguments = json.loads(calls[0]['function']['arguments'])
        require(arguments['source'] == sources[index + 1], 'Saved response/source mismatch')
        require(arguments.get('n_params', 3) == records[index + 1]['n_params'],
                'Saved response parameter count mismatch')
        require(arguments.get('rationale', '') == records[index + 1]['rationale'],
                'Saved response rationale mismatch')
        submissions.append({'source': arguments['source'],
            'n_params': arguments.get('n_params', 3), 'rationale': arguments.get('rationale', '')})
    return records, submissions, feedback, response_paths


def fixture_declarations(controller):
    """A fixture derived from current evidence, never attributed to an old LLM."""
    selected = controller.summary()['best']
    require(selected is not None, 'Offline fixture requires a selected incumbent')
    snapshots = controller.evidence_for(selected)
    summary = [item for item in snapshots if item['binding']['task_id'] == 'planning_batch']
    require(len(summary) == 1, 'Missing planning summary for fixture declaration')
    snapshot = summary[0]
    reference = {**snapshot['binding'], 'key': 'total_successes'}
    return ([{'kind': 'scalar', 'reference': reference, 'op': 'eq',
              'value': snapshot['scalars']['total_successes']}],
            {'reference': reference, 'direction': 'increase', 'min_delta': 1.0})


def replay(old_session, output):
    old_session, output = Path(old_session).resolve(), Path(output).resolve()
    old_tree = old_session.parent
    require(old_session.is_dir(), 'Saved planning_B session directory is missing')
    require(not output.is_relative_to(old_tree) and not old_tree.is_relative_to(output),
            'Output must be separate from the entire old run tree')
    require(not output.exists() and output.parent.is_dir(), 'Output must be a new directory with an existing parent')
    before = tree_hashes(old_tree)
    output.mkdir(exist_ok=False)
    write_json(output / 'old-tree-before.json', before)
    report = {'version': 'offline-checked-replay-v0.1', 'status': 'error',
        'purpose': 'SDK compatibility and serialized input size only; not a new scientific measurement.',
        'old_session': str(old_session), 'new_model_calls': 0, 'new_candidate_executions': 0,
        'fixture_usage_note': 'All usage and derived costs in the replay ledger are synthetic fixtures, not billable usage.',
        'fixture_annotation_note': 'Typed claims/predictions are newly constructed test fixtures, not old model-generated annotations.',
        'transport_note': 'SDK LLM._transport_call is replaced in process; adapter dispatch flags refer to that fake boundary, not network traffic.',
        'requests': [], 'script_sha256': digest(Path(__file__).read_bytes())}
    previous_logging = logging.root.manager.disable
    ledger = None
    try:
        records, submissions, feedback, response_paths = load_history(old_session)
        report['old_response_files'] = [path.relative_to(old_tree).as_posix() for path in response_paths]
        report['source_sha256'] = [record['source_sha256'] for record in records]
        config = read_json(ROOT / 'configs/pilots/development-v0.1.json')
        sessions = [entry for entry in config['sessions'] if entry['family'] == 'planning']
        require(len(sessions) == 1, 'Expected one fixed planning session configuration')
        session = sessions[0]
        require(session['initial_candidate_sha256'] == records[0]['source_sha256'],
                'Current baseline does not match the old baseline')
        policy = (ROOT / 'prompts/checked/policy.md').read_text(encoding='utf-8')
        replayed, captured, annotations = [], [], []
        with contextlib.ExitStack() as stack:
            guards = [stack.enter_context(patch(target, side_effect=RuntimeError('Offline replay blocks network')))
                      for target in ('socket.socket.connect', 'socket.socket.connect_ex', 'socket.create_connection')]
            stack.enter_context(patch.dict(os.environ, {
                'OPENHANDS_SUPPRESS_BANNER': '1', 'LITELLM_LOCAL_MODEL_COST_MAP': 'True', 'DO_NOT_TRACK': '1'}))
            logging.disable(logging.CRITICAL)
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            stack.enter_context(contextlib.redirect_stderr(io.StringIO()))
            from litellm.types.utils import ModelResponse
            from openhands.sdk import LLM
            from rsi_eval.checked_agent import StatePacketLLM, checked_candidate_tool, run_session
            from rsi_eval.checked_controller import CheckedController
            from rsi_eval.pilot_budget import BudgetLedger
            from rsi_eval.state_packet import payload_bytes, wire_payload

            def blocked_evaluation(*args, **kwargs):
                raise RuntimeError('Offline replay blocks candidate execution')

            stack.enter_context(patch('rsi_eval.executor.evaluate_candidate', side_effect=blocked_evaluation))
            stack.enter_context(patch('rsi_eval.pilot_controller.evaluate_candidate', side_effect=blocked_evaluation))
            stack.enter_context(patch('openhands.sdk.conversation.impl.local_conversation.load_available_plugins',
                                      side_effect=RuntimeError('Offline replay blocks ambient plugins')))
            stack.enter_context(patch('openhands.sdk.conversation.impl.local_conversation.register_file_agents',
                                      side_effect=RuntimeError('Offline replay blocks ambient agents')))

            def saved_feedback(family, task_id, source, **kwargs):
                require(family == 'planning', 'Unexpected replay task family')
                key = (digest(source.encode('utf-8')), task_id)
                require(key in feedback, 'Candidate/source has no exact saved feedback binding')
                expected_index = len(replayed) // 10
                require(expected_index < 4 and key[0] == records[expected_index]['source_sha256'],
                        'Candidate artifact replay order changed')
                require(task_id == session['task_ids'][len(replayed) % 10], 'Task artifact replay order changed')
                require(kwargs.get('candidate_id') == records[expected_index]['candidate_id'],
                        'Candidate identity changed during artifact replay')
                replayed.append({'source_sha256': key[0], 'task_id': task_id,
                                 'candidate_id': kwargs['candidate_id']})
                return copy.deepcopy(feedback[key])

            stack.enter_context(patch('rsi_eval.diagnostic_controller.evaluate_candidate', side_effect=saved_feedback))
            session_id = 'planning_checked_replay'
            controller = CheckedController(ROOT, session, output / 'session', condition='checked',
                session_id='offline-replay:' + session_id, policy_text=policy)
            controller.baseline()
            ledger = BudgetLedger(output / 'budget-ledger.json', session_ids=[session_id],
                max_requests=4, max_requests_per_session=4, max_input_bytes=INPUT_CAP)
            llm = StatePacketLLM(model='anthropic/MiniMax-M3',
                api_key='offline-placeholder-not-a-real-key', base_url='https://example.invalid',
                max_output_tokens=4096, num_retries=0, caching_prompt=False, api_mode='chat',
                stream=False, reasoning_effort='none', native_tool_calling=True,
                force_string_serializer=False, fallback_strategy=None, log_completions=False
            ).bind_pilot(ledger, session_id, output / 'requests').bind_controller(controller)

            def fake_transport(instance, *, messages, enable_streaming=False, on_token=None, **kwargs):
                require(not enable_streaming, 'Streaming is not allowed in offline replay')
                ordinal = len(captured) + 1
                require(ordinal <= 4, 'Unexpected fifth offline model request')
                payload = wire_payload(instance.model, messages, kwargs.get('tools'), kwargs.get('tool_choice'),
                    kwargs.get('max_tokens', kwargs.get('max_completion_tokens', instance.max_output_tokens)))
                encoded = canonical(payload)
                require(payload_bytes(payload) == len(encoded), 'Canonical payload byte counters disagree')
                require(len(encoded) <= INPUT_CAP, 'New offline payload exceeds the request cap')
                packet = json.loads(messages[-1]['content'])
                require([message['role'] for message in messages] == ['system', 'user'],
                        'Accumulated SDK message history was not replaced')
                captured.append({'ordinal': ordinal, 'actual_input_bytes': len(encoded),
                    'payload_sha256': digest(encoded), 'incumbent_candidate_id': packet['incumbent']['candidate_id'],
                    'latest_candidate_id': packet['latest_candidate']['candidate_id'],
                    'source_ids': [{'candidate_id': row['candidate_id'], 'source_sha256': row['source_sha256']}
                                   for row in packet['history']]})
                message = {'role': 'assistant', 'content': 'Synthetic offline fixture response; no new model inference.'}
                if ordinal <= 3:
                    claims, prediction = fixture_declarations(controller)
                    arguments = {**submissions[ordinal - 1], 'claims': claims, 'prediction': prediction}
                    annotations.append({'ordinal': ordinal, 'origin': 'synthetic_test_fixture_not_model',
                                        'claims': claims, 'prediction': prediction})
                    message['tool_calls'] = [{'id': f'offline-call-{ordinal}', 'type': 'function',
                        'function': {'name': 'submit_candidate', 'arguments': canonical(arguments).decode('utf-8')}}]
                return ModelResponse(id=f'offline-fixture-response-{ordinal}', model='minimax-m3',
                    choices=[{'message': message, 'finish_reason': 'tool_calls' if ordinal <= 3 else 'stop'}],
                    usage=dict(FIXTURE_USAGE))

            stack.enter_context(patch.object(LLM, '_transport_call', new=fake_transport))
            result = run_session(controller, llm, session_id, output / 'session', tool_factory=checked_candidate_tool)
            report['session_status'] = {key: result.get(key) for key in
                ('status', 'conversation_status', 'model_error_type', 'cause_type', 'sdk_version', 'tools')}
            report['requests'] = captured
            report['network_connection_attempts'] = sum(guard.call_count for guard in guards)
            write_json(output / 'fixture-annotations.json', annotations)
            write_json(output / 'artifact-feedback-replays.json', replayed)
            require(result['status'] == 'completed', 'Offline SDK conversation did not complete')
            require(len(captured) == 4 and len(replayed) == 40, 'Expected four SDK inputs and forty saved task feedback replays')
            require(len(controller.records) == 4 and len(controller.audits) == 3, 'Offline candidate or audit count changed')
            require(report['network_connection_attempts'] == 0, 'A real network connection was attempted')
            for old, replayed_record in zip(records, controller.records):
                require(old['source_sha256'] == replayed_record['source_sha256'] and
                        old['metrics'] == replayed_record['metrics'], 'Replay changed saved artifact scores')
            state = read_json(output / 'budget-ledger.json')
            require(len(state['requests']) == 4 and not state['halted'], 'Offline ledger failed its four-request contract')
            for ordinal, (entry, request) in enumerate(zip(state['requests'], captured), 1):
                saved = read_json(output / 'requests' / f'request-{ordinal:04d}.request.json')
                audit = read_json(output / 'requests' / f'input-audit-{ordinal:04d}.json')
                require(entry['status'] == 'settled' and entry['usage_state'] == 'known' and
                        entry['usage'] == FIXTURE_USAGE, 'Offline ledger usage must be the known synthetic fixture')
                require(entry['input_bytes'] == request['actual_input_bytes'] == len(canonical(saved)) and
                        entry['payload_sha256'] == request['payload_sha256'] == digest(canonical(saved)) == audit['payload_sha256'],
                        'Ledger, saved request, input audit and actual transport bytes disagree')
                require(audit['actual_input_bytes'] == request['actual_input_bytes'] and audit['excess_bytes'] == 0,
                        'Input audit did not verify the byte limit')
            report.update(status='completed', new_input_cap_bytes=INPUT_CAP,
                artifact_candidates_replayed=4, artifact_task_feedback_replayed=40,
                all_four_new_inputs_fit=True, known_synthetic_usage_requests=4)
    except Exception as error:
        report['error_type'] = type(error).__name__
        # Only our fixed contract messages are included; no provider is called.
        if type(error) is ValueError:
            report['contract_failure'] = str(error)
    finally:
        logging.disable(previous_logging)
        after = tree_hashes(old_tree)
        write_json(output / 'old-tree-after.json', after)
        report['old_tree_unchanged'] = before == after
        report['old_tree_file_count'] = len(before)
        report['old_tree_before_sha256'] = digest(canonical(before))
        report['old_tree_after_sha256'] = digest(canonical(after))
        if before != after:
            report.update(status='error', error_type='OldRunChanged')
        if ledger is not None:
            report['fixture_ledger_summary'] = ledger.summary()
        write_json(output / 'replay-evidence.json', report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--old-run', type=Path, default=DEFAULT_OLD_RUN,
                        help='Saved planning_B session, containing candidates and requests directories.')
    parser.add_argument('--output', type=Path, required=True,
                        help='New temporary output directory; parent must exist; outside the old run tree.')
    args = parser.parse_args(argv)
    try:
        result = replay(args.old_run, args.output)
    except (ValueError, OSError) as error:
        print(json.dumps({'status': 'error', 'error_type': type(error).__name__,
                          'new_model_calls': 0, 'new_candidate_executions': 0}))
        return 1
    print(json.dumps({'status': result['status'], 'evidence_file': str(args.output.resolve() / 'replay-evidence.json'),
        'request_bytes': [entry['actual_input_bytes'] for entry in result['requests']],
        'old_tree_unchanged': result['old_tree_unchanged'], 'error_type': result.get('error_type'),
        'new_model_calls': 0, 'new_candidate_executions': 0}, ensure_ascii=False, indent=2))
    return 0 if result['status'] == 'completed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
