#!/usr/bin/env python3
"""Read-only verification of paired repair records; no model or candidate execution.

Actual serialized provider-bound request records are compared, including the
system message and complete tool schema. Only the three predeclared check
channels are removed from the user state packet. Final files can establish
binding/value consistency, but cannot independently timestamp preregistration.
"""
import argparse
from collections import Counter
import copy
from decimal import Decimal
import hashlib
import json
import math
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True
from rsi_eval.evidence_checks import check_prediction
from rsi_eval.evidence_ids import EvidenceRegistry


CHECK_FIELDS = ('checks_visible', 'audits', 'frozen_history_checks')
DECLARATION_FIELDS = ('claim_id', 'claim_op', 'claim_value_json', 'prediction_id',
                      'prediction_direction', 'prediction_min_delta')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True,
                      separators=(',', ':')).encode('utf-8')


def digest(value):
    return hashlib.sha256(value).hexdigest()


def no_constant(value):
    raise ValueError('Nonfinite JSON constant')


def no_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'Duplicate JSON object key')
        result[key] = value
    return result


def parse_json(value):
    return json.loads(value, parse_constant=no_constant, object_pairs_hook=no_duplicate_keys)


def read_json(path):
    return parse_json(path.read_text(encoding='utf-8'))


def tree_hashes(root):
    require(root.is_dir(), 'Run directory is missing')
    result = {}
    for path in sorted(root.rglob('*')):
        require(not path.is_symlink(), 'Run must not contain symlinks')
        if path.is_file():
            result[path.relative_to(root).as_posix()] = digest(path.read_bytes())
    require(bool(result), 'Run directory is empty')
    return result


def inside(root, relative):
    path = (root / relative).resolve()
    require(path.is_relative_to(root.resolve()) and path.is_file(), 'Recorded path escapes its run directory')
    return path


def request_common(request):
    value = copy.deepcopy(request)
    messages = value.get('messages')
    require(type(messages) is list and len(messages) == 2
            and [row.get('role') for row in messages] == ['system', 'user'],
            'Expected exactly the fixed system and replacement user messages')
    require(type(messages[1].get('content')) is str, 'Replacement packet must be a JSON string')
    packet = parse_json(messages[1]['content'])
    require(type(packet) is dict, 'State packet must be an object')
    for field in CHECK_FIELDS:
        packet.pop(field, None)
    messages[1]['content'] = canonical(packet).decode('utf-8')
    return value


def request_packet(request):
    # request_common validates the exact role/content contract first.
    request_common(request)
    return parse_json(request['messages'][1]['content'])


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def record_score(record, family):
    results = record.get('results', [])
    tasks = (['spannerlearning/seed0/problem'+str(i) for i in range(10)]
             if family == 'planning' else ['oscillator1'])
    if (record.get('status') != 'evaluated'
            or [row.get('task_id') for row in results] != tasks
            or any(row.get('status') in (None, 'infrastructure_error', 'invalid_request') for row in results)):
        return None
    metrics = record.get('metrics', {})
    if family == 'planning':
        prompt = sum(row['status'] == 'success' for row in results[:2])
        development = sum(row['status'] == 'success' for row in results[2:])
        expected = dict(prompt_successes=prompt, prompt_total=2, development_successes=development,
                        development_total=8, total_successes=prompt+development, total_tasks=10)
        require(metrics == expected, 'Planning score disagrees with task result statuses')
        return float(prompt+development)
    if results[0]['status'] != 'success':
        return None
    require(metrics == results[0].get('metrics') and set(metrics) == {'mse', 'nmse'}
            and all(finite(value) and value >= 0 for value in metrics.values()),
            'Symbolic score disagrees with the successful train result')
    return float(metrics['nmse'])


def classify_response(response):
    if 'choices' not in response:
        return 'recorded_provider_or_transport_error', None
    require(len(response['choices']) == 1, 'Unexpected number of response choices')
    choice = response['choices'][0]
    calls = choice['message'].get('tool_calls') or []
    if not calls:
        return ('incomplete_tool_response' if choice['finish_reason'] == 'tool_calls'
                else 'assistant_message_without_tool_call'), None
    if len(calls) != 1:
        return 'multiple_tool_calls_rejected', None
    tool = calls[0]['function']
    if tool['name'] == 'finish':
        return 'finish_tool', None
    if tool['name'] != 'submit_candidate':
        return 'unknown_tool_rejected', None
    try:
        arguments = parse_json(tool['arguments'])
    except (ValueError, TypeError, OverflowError, RecursionError):
        return 'submit_tool_arguments_not_plain_json', None
    return 'submit_candidate_tool', arguments


def verify_audit(directory, audit, evidence, arguments):
    reference = audit['registry']
    manifest = read_json(inside(directory, reference['file']))
    require(digest(canonical(manifest)) == reference['sha256'], 'Preregistration registry digest mismatch')
    baseline_id = 'planning-000' if 'planning-000' in evidence else 'symbolic-000'
    registry = EvidenceRegistry(evidence[baseline_id], session_id=manifest['session_id'])
    require(registry.export_manifest() == manifest, 'Parent registry does not match exact parent evidence')
    declaration = audit['compact_declaration']
    require(set(declaration) == set(DECLARATION_FIELDS), 'Audit declaration fields changed')
    raw_matches = (type(arguments) is dict
                   and all(arguments.get(key) == declaration[key] for key in DECLARATION_FIELDS))
    # A transformed SDK argument would need a separate exact SDK replay, not a
    # guessed reconstruction in this stdlib analysis. All current valid flat
    # responses are expected to match their literal saved declarations.
    require(raw_matches, 'Executed declaration differs from literal saved response; SDK replay required')
    try:
        value = parse_json(declaration['claim_value_json'])
        canonical(value)
    except (ValueError, TypeError, OverflowError, RecursionError, UnicodeError):
        value = None
    claim = dict(evidence_id=declaration['claim_id'], op=declaration['claim_op'], value=value)
    prediction = dict(evidence_id=declaration['prediction_id'], direction=declaration['prediction_direction'],
                      min_delta=declaration['prediction_min_delta'])
    claim_expansion, prediction_expansion = registry.expand_claim(claim), registry.expand_prediction(prediction)
    claim_result, registration = registry.check_claim(claim), registry.register_prediction(prediction)
    require(claim_expansion == audit['claim_expansion'] and prediction_expansion == audit['prediction_expansion'],
            'Audit short-ID expansion does not match exact registry lookup')
    require([claim_result] == audit['claim_results'] and registration == audit['registration'],
            'Archived claim/registration differs from independent pure predicate recomputation')
    child = evidence.get(audit['candidate_id'])
    require(child is not None, 'Audit child evidence missing')
    prediction_result = check_prediction(registration, child)
    require(prediction_result == audit['prediction_result'], 'Prediction result differs from exact child evidence')
    return dict(candidate_id=audit['candidate_id'], registry_file=reference['file'],
                registry_sha256=reference['sha256'], raw_response_declaration_exact=True,
                expansion_and_predicates_recomputed=True, declaration=declaration,
                claim_result=claim_result, registration=registration, prediction_result=prediction_result)


def analyze(run, output):
    run, output = Path(run).resolve(), Path(output).resolve()
    require(not output.exists() and output.parent.is_dir(), 'Output must be a new file with an existing parent')
    require(not output.is_relative_to(run), 'Analysis output must be outside the immutable run')
    before = tree_hashes(run)
    report = dict(version='paired-repair-analysis-v0.1', status='error', new_model_calls=0,
                  new_candidate_executions=0, sessions=[], actual_request_pairs={},
                  request_comparison_scope=('Exact saved SDK pre-transport request envelopes, including '
                      'system messages and tools; raw provider HTTP payloads were not separately captured.'),
                  registration_timing_independently_proven=False,
                  timing_evidence_limit=('Final files independently verify exact response declarations, registry '
                      'mapping, parent values and child outcomes. Their write order is supported by frozen '
                      'controller source and tests; the final archive is not an independently timestamped attestation.'))
    try:
        summary = read_json(run/'summary.json')
        config = read_json(run/'config.json')
        ledger = read_json(run/'budget-ledger.json')
        order, reservations = config['order'], ledger['requests']
        require(config['max_iterations'] == config['max_generated_candidates'] == 1,
                'Analysis expects the frozen one-step protocol')
        report.update(run_id=summary['run_id'], runtime_commit=summary['code_commit'],
                      reported_run_status=summary['status'], stop_reason=summary.get('stop_reason'))
        require(len({r['request_id'] for r in reservations}) == len(reservations), 'Duplicate ledger request ID')
        ledger_by_session = {}
        for entry in reservations:
            ledger_by_session.setdefault(entry['session_id'], []).append(entry)
        require(set(ledger_by_session) <= {entry['session_id'] for entry in order}, 'Unknown ledger session')
        reported_by_session = {entry['session_id']: entry for entry in summary['sessions']}
        request_by_session = {}
        claim_counts, prediction_counts, registration_counts = Counter(), Counter(), Counter()
        known_prompt = known_completion = known_total = 0
        for spec in order:
            session = spec['session_id']
            directory = run/session
            records = read_json(directory/'candidates.json')
            require(1 <= len(records) <= 2, 'Expected one copied starting candidate and at most one child')
            family = spec['family']
            expected_baseline = family+'-000'
            require(records[0]['candidate_id'] == expected_baseline
                    and records[0]['origin'] == 'archived_model_proposed_initial', 'Unexpected baseline provenance')
            for record in records:
                source = inside(directory, 'candidates/'+record['candidate_id']+'.py').read_bytes()
                require(digest(source) == record['source_sha256'], 'Candidate source digest mismatch')
                for result in record.get('results', []):
                    if 'candidate_hash' in result:
                        require(result['candidate_hash'] == record['source_sha256'], 'Task result source binding mismatch')
            before_score = record_score(records[0], family)
            require(before_score is not None, 'Archived starting score is incomplete')
            provenance = read_json(directory/'repair-state-provenance.json')
            require(provenance.get('candidate_executions_during_load') == 0,
                    'Baseline was not declared an archived copy')
            source_entries = [x for x in provenance['source_files'] if x['path'].endswith('.py')]
            require(len(source_entries) == 1 and source_entries[0]['sha256'] == records[0]['source_sha256'],
                    'Copied baseline differs from its pinned archived source')
            children = records[1:]
            child_score = record_score(children[0], family) if children else None
            improvement = ((child_score-before_score if family == 'planning' else before_score-child_score)
                           if child_score is not None else None)
            row = dict(spec, request_count=0, generated_candidate_records=len(children),
                candidate_evaluation_attempted=bool(children and children[0].get('results')),
                new_task_result_records=sum(len(c.get('results', [])) for c in children),
                archived_task_result_records=len(records[0]['results']),
                baseline_source_sha256=records[0]['source_sha256'], baseline_score=before_score,
                child_source_sha256=children[0]['source_sha256'] if children else None,
                child_score=child_score, improvement=improvement,
                submitted_and_improved=improvement is not None and improvement > 1e-12,
                audits=[], sdk_status=reported_by_session[session].get('status'),
                sdk_conversation_status=reported_by_session[session].get('conversation_status'),
                model_error_type=reported_by_session[session].get('model_error_type'),
                cause_type=reported_by_session[session].get('cause_type'))
            files = sorted((directory/'requests').glob('*.request.json'))
            received = ledger_by_session.get(session, [])
            require(len(files) == len(received) <= 1, 'Request files and one-request ledger disagree')
            args = None
            if files:
                reservation = received[0]
                identifier = reservation['request_id']
                require(files[0].name == identifier+'.request.json', 'Request identity differs from ledger')
                request = read_json(files[0])
                request_by_session[session] = request
                packed = canonical(request)
                audit = read_json(directory/'requests/input-audit-0001.json')
                packet = request_packet(request)
                saved_packet = read_json(directory/'requests/packet-0001.json')
                require(packet == saved_packet, 'Actual user message differs from saved packet')
                require(digest(packed) == reservation['payload_sha256'] == audit['payload_sha256']
                        and len(packed) == reservation['input_bytes'] == audit['actual_input_bytes'],
                        'Request, ledger and input-audit bytes/hash disagree')
                require(len(packed) <= ledger['config']['max_input_bytes'], 'Request exceeds input budget')
                require(audit['request_id'] == identifier and audit['network_dispatch_attempted']
                        and audit['request_reserved'], 'Request audit has no matching dispatch reservation')
                response = read_json(directory/'requests'/f'{identifier}.response.json')
                kind, args = classify_response(response)
                row.update(request_count=1, request_id=identifier, response_kind=kind,
                    request_bytes=len(packed), request_payload_sha256=digest(packed),
                    common_request_sha256=digest(canonical(request_common(request))),
                    response_sha256=digest((directory/'requests'/f'{identifier}.response.json').read_bytes()),
                    request_usage_state=reservation['usage_state'], request_settlement=reservation['status'],
                    sdk_argument_validation=audit.get('response_tool_validation'))
                if reservation['usage_state'] == 'known':
                    usage = reservation['usage']
                    require(response.get('usage') == usage, 'Response usage differs from settled ledger')
                    require(usage['total_tokens'] == usage['prompt_tokens']+usage['completion_tokens'],
                            'Known usage totals disagree')
                    known_prompt += usage['prompt_tokens']
                    known_completion += usage['completion_tokens']
                    known_total += usage['total_tokens']
                    row['usage'] = usage
                if children:
                    require(type(args) is dict and type(args.get('source')) is str
                            and digest(args['source'].encode('utf-8')) == children[0]['source_sha256'],
                            'Executed child differs from literal saved tool source; SDK replay required')
                    require(args.get('n_params') == children[0]['n_params'], 'Child parameter count differs from response')
            else:
                require(not children, 'Child exists without a reserved request')
                row['response_kind'] = 'not_requested'
            evidence = read_json(directory/'evidence.json')
            for record in records:
                snapshots = evidence.get(record['candidate_id'], [])
                for snapshot in snapshots:
                    binding = snapshot['binding']
                    require(binding['candidate_id'] == record['candidate_id']
                            and binding['candidate_sha256'] == record['source_sha256'],
                            'Evidence source/candidate identity mismatch')
                if record_score(record, family) is not None:
                    primary_task = 'planning_batch' if family == 'planning' else 'oscillator1'
                    primary = [snapshot for snapshot in snapshots
                               if snapshot['binding']['task_id'] == primary_task]
                    require(len(primary) == 1 and all(primary[0]['scalars'].get(key) == value
                            for key, value in record['metrics'].items()),
                            'Bound evidence metrics differ from complete task result metrics')
            audits = read_json(directory/'audits.json') if (directory/'audits.json').exists() else []
            require(len(audits) <= len(children), 'More audit registrations than child records')
            for audit in audits:
                verified = verify_audit(directory, audit, evidence, args)
                row['audits'].append(verified)
                claim_counts[verified['claim_result']['status']] += 1
                registration_counts[verified['registration']['status']] += 1
                prediction_counts[verified['prediction_result']['status']] += 1
            report['sessions'].append(row)
        by_session = {row['session_id']: row for row in report['sessions']}
        for pair in sorted({entry['pair_id'] for entry in order}):
            members = [entry for entry in order if entry['pair_id'] == pair]
            require(len(members) == 2 and {r['condition'] for r in members} == {'hidden', 'checked'},
                    'Pair does not contain both conditions')
            hidden = by_session[next(r['session_id'] for r in members if r['condition'] == 'hidden')]
            checked = by_session[next(r['session_id'] for r in members if r['condition'] == 'checked')]
            pair_report = dict(state_id=hidden['state_id'], family=hidden['family'], repeat=hidden['repeat'],
                both_requested=hidden['request_count'] == checked['request_count'] == 1,
                baseline_source_identical=hidden['baseline_source_sha256'] == checked['baseline_source_sha256'],
                hidden_score=hidden['child_score'], checked_score=checked['child_score'],
                hidden_improvement=hidden['improvement'], checked_improvement=checked['improvement'],
                checked_minus_hidden_improvement=None)
            require(pair_report['baseline_source_identical'], 'Paired baseline source differs')
            if pair_report['both_requested']:
                first = canonical(request_common(request_by_session[hidden['session_id']]))
                second = canonical(request_common(request_by_session[checked['session_id']]))
                require(first == second, 'ACTUAL complete provider-bound common requests differ')
                pair_report.update(complete_common_request_identical=True,
                                   common_request_sha256=digest(first), common_request_bytes=len(first))
            else:
                pair_report['complete_common_request_identical'] = None
            if hidden['improvement'] is not None and checked['improvement'] is not None:
                pair_report['checked_minus_hidden_improvement'] = checked['improvement']-hidden['improvement']
            report['actual_request_pairs'][pair] = pair_report
        estimated = ((Decimal(known_prompt)*Decimal(str(ledger['config']['input_cny_per_million']))
                      + Decimal(known_completion)*Decimal(str(ledger['config']['output_cny_per_million'])))/1000000)
        report['budget'] = dict(request_count=len(reservations),
            usage_unknown_count=sum(row['usage_state'] != 'known' for row in reservations),
            unsettled_request_count=sum(row['status'] == 'reserved' for row in reservations),
            known_prompt_tokens=known_prompt, known_completion_tokens=known_completion,
            known_total_tokens=known_total, known_estimated_cost_cny=float(estimated),
            reserved_cost_cny=float(sum(Decimal(str(row['reserved_cost_cny'])) for row in reservations)),
            cost_basis='Configured uncached prices; estimate, not a provider invoice')
        for key in ('request_count', 'usage_unknown_count', 'known_prompt_tokens',
                    'known_completion_tokens', 'known_total_tokens', 'known_estimated_cost_cny'):
            require(report['budget'][key] == summary['budget'][key], 'Reported run budget differs from independent total')
        report['counts'] = dict(assigned_sessions=len(order),
            generated_candidate_records=sum(row['generated_candidate_records'] for row in report['sessions']),
            candidate_evaluation_attempts=sum(row['candidate_evaluation_attempted'] for row in report['sessions']),
            candidates_with_complete_score=sum(row['child_score'] is not None for row in report['sessions']),
            new_task_result_records=sum(row['new_task_result_records'] for row in report['sessions']),
            archived_task_result_records=sum(row['archived_task_result_records'] for row in report['sessions']),
            claim_statuses=dict(claim_counts), registration_statuses=dict(registration_counts),
            prediction_statuses=dict(prediction_counts),
            response_kinds=dict(Counter(row['response_kind'] for row in report['sessions'])))
        report['arm_endpoints'] = {condition: dict(assigned_sessions=sum(row['condition'] == condition for row in report['sessions']),
            submitted_and_improved=sum(row['condition'] == condition and row['submitted_and_improved'] for row in report['sessions']),
            generated_candidate_records=sum(row['generated_candidate_records'] for row in report['sessions'] if row['condition'] == condition))
            for condition in ('hidden', 'checked')}
        report['status'] = 'verified'
    except Exception as error:
        report['error_type'] = type(error).__name__
        if type(error) is ValueError:
            report['verification_failure'] = str(error)
    finally:
        after = tree_hashes(run)
        report.update(run_file_count=len(before), run_files_unchanged=before == after,
                      run_tree_before_sha256=digest(canonical(before)),
                      run_tree_after_sha256=digest(canonical(after)), input_file_sha256=before,
                      analysis_script_sha256=digest(Path(__file__).read_bytes()))
        if before != after:
            report.update(status='error', error_type='RunChangedDuringAnalysis')
        output.write_text(json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2)+'\n',
                          encoding='utf-8', newline='\n')
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = analyze(args.run, args.output)
    except (ValueError, OSError) as error:
        print(json.dumps({'status': 'error', 'error_type': type(error).__name__}))
        return 1
    print(json.dumps({key: result.get(key) for key in ('status', 'counts', 'budget', 'run_files_unchanged',
        'error_type', 'verification_failure')}, ensure_ascii=False, indent=2))
    return 0 if result['status'] == 'verified' else 1


if __name__ == '__main__':
    raise SystemExit(main())
