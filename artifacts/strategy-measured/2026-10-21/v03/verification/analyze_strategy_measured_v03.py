"""Read saved observed-run receipts; never execute candidate code or call a model.

Use after the host has written a terminal summary and exported all original
files. This is a descriptive cross-check, not a replacement for audit_run.
Only the requested output below tmp/ is written. All records and candidate
sources are read as data; ast.parse is syntax inspection only.
"""
from pathlib import Path
from collections import Counter, defaultdict
from decimal import Decimal
import argparse
import ast
import copy
import hashlib
import json
import sys


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False).encode('utf-8')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_bytes())


def count(values):
    return dict(sorted(Counter('none' if x is None else str(x) for x in values).items()))


def request_parts(request):
    users = [i for i, message in enumerate(request['messages']) if message.get('role') == 'user']
    assert len(users) == 1
    index = users[0]
    content = request['messages'][index]['content']
    if isinstance(content, list):
        assert len(content) == 1 and content[0]['type'] == 'text'
        content = content[0]['text']
    packet = json.loads(content)
    normalized = copy.deepcopy(request)
    normalized['messages'][index]['content'] = None
    return packet, normalized


def choice_summary(choice):
    """A valid text-only response may carry tool_calls=None, not an array."""
    message = choice.get('message') or {}
    calls = message.get('tool_calls') or []
    return dict(finish_reason=choice.get('finish_reason'),
        tool_calls_field_present='tool_calls' in message,
        tool_calls_is_null='tool_calls' in message and message['tool_calls'] is None,
        tool_names=[(call.get('function') or {}).get('name') for call in calls],
        tool_types=[call.get('type') for call in calls])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-id', default='measured-v03')
    parser.add_argument('--export')
    parser.add_argument('--output', default='tmp/strategy-measured-v03-analysis.json')
    parser.add_argument('--prior-requests', type=int, default=134)
    parser.add_argument('--prior-tokens', type=int, default=1079042)
    parser.add_argument('--prior-estimate', default='3.2916156')
    parser.add_argument('--prior-reserved', default='14.7462378')
    parser.add_argument('--prior-unknown', type=int, default=2)
    args = parser.parse_args()
    root = Path.cwd().resolve()
    sys.path.insert(0, str(root))
    from rsi_eval import goal_alignment
    from rsi_eval.strategy_pair_transport import verify_dispatch_record
    assert args.run_id and '/' not in args.run_id and '\\' not in args.run_id

    def safe(relative):
        path = (root / relative).resolve()
        assert path.is_relative_to(root), relative
        assert not (root / relative).is_symlink(), relative
        return path

    def ref(value):
        path = safe(value['path'])
        assert sha(path) == value['sha256'], value['path']
        return read(path)

    output = safe(args.output)
    assert output.is_relative_to(root / 'tmp')
    run = root / 'runs/strategy-pair' / args.run_id
    experiment = run / 'experiment'
    export_path = safe(args.export or ('tmp/strategy-' + args.run_id + '-export.json'))
    export = read(export_path)
    assert export.get('run_id', args.run_id) == args.run_id
    files = export['files']
    assert files and len(files) == export.get('file_count', len(files))
    assert output.relative_to(root).as_posix() not in files
    before = {name: sha(safe(name)) for name in files}
    assert before == files, 'Original files differ from export before analysis'
    assert {p.relative_to(root).as_posix() for p in run.rglob('*') if p.is_file()} <= set(files)

    summary = read(experiment / 'summary.json')
    assert summary['status'] in ('complete', 'stopped'), 'Wait for terminal host summary'
    assert summary['evidence_kind'] == 'observed', 'Do not count a simulation as research'
    result = read(run / 'result.json')
    budget = result['budget']
    ledger = read(run / 'budget-ledger.json')
    settings = read(run / 'preparation/settings.json')['effective']
    parent_policy = read(experiment / 'parent-policy.json')
    rows = ledger['requests']
    slots = {x['slot']['id']: x for x in summary['slots']}
    assert len(rows) == budget['request_count']
    assert len({r['request_id'] for r in rows}) == len(rows)
    assert len({r['session_id'] for r in rows}) == len(rows)
    assert summary['slot_counts'] == {key: sum(s['status'] == key for s in slots.values())
                                    for key in ('completed', 'failed', 'not_started')}

    # Only already-generated result receipts and their adjacent request/source
    # files are inspected; no task datasets or unexecuted starting source files.
    measurements = []
    event_groups = defaultdict(list)
    seen_receipts = set()
    for event in summary['events']:
        if event['kind'] != 'measurement_recorded':
            continue
        receipt = event['receipt']
        assert receipt['path'] not in seen_receipts
        seen_receipts.add(receipt['path'])
        record = ref(receipt)
        assert record.get('evidence_kind') != 'synthetic'
        assert record.get('record_kind') == 'executor_observation'
        assert record['journal_path'] == receipt['path']
        assert record['status'] == event['status']
        assert record['model_calls'] == 0 and record['sealed_tasks_executed'] == 0
        measurements.append(record)
        event_groups[record['candidate_id']].append(record)
    assert len(measurements) == summary['measurement_record_count']

    def stats(records):
        return dict(task_count=len(records), successes=sum(r['status'] == 'success' for r in records),
            task_roles=count(r['task_role'] for r in records),
            metric_scopes=count(r['metric_scope'] for r in records),
            statuses=count(r['status'] for r in records),
            errors=count(r.get('error_kind') for r in records),
            exceptions=count(r.get('exception_type') for r in records),
            empty_plans=sum(r.get('plan_length') == 0 for r in records),
            n_params=sorted({r['n_params'] for r in records}),
            policy_sha256=sorted({r['strategy_version'] for r in records}),
            metrics=[dict(task_id=r['task_id'], metric_scope=r['metric_scope'],
                          n_params=r['n_params'], metrics=r['metrics'])
                     for r in records if 'metrics' in r],
            task_ids=[r['task_id'] for r in records],
            receipt_paths=[r['journal_path'] for r in records])

    baselines = {}
    for candidate, records in sorted(event_groups.items()):
        if not candidate.endswith('-baseline'):
            continue
        state_id = candidate[:-len('-baseline')]
        baselines[state_id] = stats(records)
        frozen = [e for e in summary['events'] if e['kind'] == 'baseline_frozen'
                  and e['state_id'] == state_id]
        assert len(frozen) <= 1
        baselines[state_id]['complete_and_frozen'] = bool(frozen)
        if frozen:
            context = ref(frozen[0]['context'])
            assert set(r['path'] for r in frozen[0]['measurements']) == set(baselines[state_id]['receipt_paths'])
            assert hashlib.sha256(context['source'].encode()).hexdigest() == context['source_sha256']
            baselines[state_id]['context'] = frozen[0]['context']
            baselines[state_id]['source_sha256'] = context['source_sha256']

    actors = {}
    packets = {}
    for slot_id, slot in slots.items():
        if slot['slot']['phase'] == 'update' or 'session' not in slot:
            continue
        session = slot['session']
        item = dict(phase=slot['slot']['phase'], replicate=slot['slot']['replicate'],
                    arm=slot['slot']['arm'], state_id=slot['slot']['state_id'],
                    slot_status=slot['status'], session_status=session['status'],
                    measurements=stats(event_groups.get(slot_id, [])))
        if session.get('source'):
            source_path = safe(session['source']['path'])
            assert sha(source_path) == session['source']['sha256']
            item['source'] = session['source']
            try:
                ast.parse(source_path.read_text(encoding='utf-8'))
                item['syntax'] = dict(valid=True)
            except SyntaxError as error:
                item['syntax'] = dict(valid=False, line=error.lineno, message=error.msg)
        if session.get('submission'):
            submission = ref(session['submission'])
            item['accepted_n_params'] = submission.get('n_params')
        baseline = baselines.get(item['state_id'])
        item['matched_baseline'] = ({k: baseline[k] for k in ('task_roles', 'metric_scopes',
            'n_params', 'metrics', 'task_count', 'complete_and_frozen')} if baseline else None)
        item['baseline_tasks_equal_actor_tasks'] = (baseline['task_ids'] == item['measurements']['task_ids']
            if baseline and item['measurements']['task_count'] else None)
        if session.get('request'):
            packet, template = request_parts(ref(session['request']))
            assert set(packet) == {'version', 'task_text', 'current_state', 'repair_policy'}
            item['policy'] = packet['repair_policy']
            packets[slot_id] = ({k: v for k, v in packet.items() if k != 'repair_policy'}, template)
        bound_path = experiment / 'bound-sessions' / (slot_id + '.json')
        item['bound_measurements_complete'] = bound_path.is_file()
        if bound_path.is_file():
            bound = read(bound_path)
            assert set(r['path'] for r in bound['evaluations']) == set(item['measurements']['receipt_paths'])
            for value in bound['evaluations']:
                ref(value)
        actors[slot_id] = item

    pair_comparisons = []
    groups = defaultdict(dict)
    for slot_id, item in actors.items():
        groups[item['replicate'], item['phase'], item['state_id']][item['arm']] = slot_id
    for (replicate, phase, state_id), arms in sorted(groups.items()):
        entry = dict(replicate=replicate, phase=phase, state_id=state_id, arm_slots=arms,
                     both_requests_present=all(arms.get(a) in packets for a in ('fixed', 'updated')))
        if entry['both_requests_present']:
            left, right = (packets[arms[a]] for a in ('fixed', 'updated'))
            entry['common_actor_packet_equal'] = left[0] == right[0]
            entry['common_request_template_equal'] = left[1] == right[1]
            assert entry['common_actor_packet_equal'] and entry['common_request_template_equal']
            old, new = (actors[arms[a]] for a in ('fixed', 'updated'))
            entry['policy_equal'] = old.get('policy') == new.get('policy')
            entry['both_arms_measured'] = all(x['bound_measurements_complete'] for x in (old, new))
            if entry['both_arms_measured']:
                assert old['measurements']['task_ids'] == new['measurements']['task_ids']
                entry['task_count_per_arm'] = old['measurements']['task_count']
                entry['success_delta'] = new['measurements']['successes'] - old['measurements']['successes']
                entry['actual_policy_hashes_equal'] = old['measurements']['policy_sha256'] == new['measurements']['policy_sha256']
                entry['attribution'] = ('no_policy_change' if entry['actual_policy_hashes_equal']
                                        else 'paired_policy_comparison')
                assert entry['policy_equal'] == entry['actual_policy_hashes_equal']
                old_records, new_records = (event_groups[arms[a]] for a in ('fixed', 'updated'))
                if old_records[0]['family'] == 'planning':
                    entry['goal_assessment'] = goal_alignment.assess_planning(old_records, new_records,
                        development_ids=old['measurements']['task_ids'], public_ids=[])
                else:
                    def symbolic_projection(records):
                        if len(records) != 1 or records[0]['status'] != 'success':
                            return {}
                        row = records[0]
                        return dict(nmse=row['metrics']['nmse'], n_params=row['n_params'],
                            **{k: row[k] for k in ('task_id', 'metric_scope', 'data_sha256', 'evaluator_sha256')})
                    entry['goal_assessment'] = goal_alignment.assess_symbolic(
                        symbolic_projection(old_records), symbolic_projection(new_records))
                if len(old['measurements']['metrics']) == len(new['measurements']['metrics']) == 1:
                    p, q = old['measurements']['metrics'][0], new['measurements']['metrics'][0]
                    entry['nmse_delta'] = q['metrics']['nmse'] - p['metrics']['nmse']
                    entry['parameter_delta'] = q['n_params'] - p['n_params']
        pair_comparisons.append(entry)

    proposals = {name: ref(value)['content']['rule_ids'] for name, value in summary['proposals'].items()}
    decisions = {}
    for rep, value in summary['decisions'].items():
        decision = ref(value)
        replay = decision['replay']
        assert replay['evidence_kind'] == 'observed'
        chosen = replay['candidate_policy'] if replay['decision']['decision'] == 'promote' else replay['parent_policy']
        assert decision['selected_policy'] == chosen
        decisions[rep] = dict(reference=value, stored_selector_decision=replay['decision'],
                             selected_policy=decision['selected_policy'],
                             selected_parent_S0=decision['selected_policy']['sha256'] == parent_policy['sha256'])
    gate = summary['production_evaluation_gate']
    if gate is not None:
        gate_value = ref(gate)
        assert set(decisions) == {'r1', 'r2'} and gate_value['decisions'] == summary['decisions']
        assert gate_value['selected_policy_sha256'] == {k: d['selected_policy']['sha256'] for k, d in decisions.items()}
    decision_events = [e['ordinal'] for e in summary['events'] if e['kind'] == 'decision_frozen']
    gate_events = [e['ordinal'] for e in summary['events'] if e['kind'] == 'both_decisions_frozen']
    eval_states = {s['slot']['state_id'] for s in slots.values() if s['slot']['phase'] == 'evaluation'}
    eval_access_events = [e['ordinal'] for e in summary['events']
                          if e['kind'] in ('baseline_started', 'measurement_recorded')
                          and e.get('state_id') in eval_states]
    if eval_access_events:
        assert gate is not None and len(decision_events) == 2 and len(gate_events) == 1
        assert max(decision_events) < gate_events[0] < min(eval_access_events)

    requests = []
    total_prompt = total_completion = total_tokens = unknown = 0
    cost = Decimal(0)
    for row in rows:
        session_dir = experiment / 'sessions' / row['session_id']
        request_path = session_dir / 'requests' / (row['request_id'] + '.request.json')
        response_path = session_dir / 'requests' / (row['request_id'] + '.response.json')
        request = read(request_path) if request_path.is_file() else None
        response = read(response_path) if response_path.is_file() else None
        entry = dict(request_id=row['request_id'], slot_id=row['session_id'],
                     ledger_status=row['status'], usage_state=row['usage_state'],
                     ledger_error_type=row.get('error_type'), usage=row.get('usage'),
                     session_status=slots[row['session_id']].get('session', {}).get('status'),
                     request_present=request is not None, response_present=response is not None)
        if request is not None:
            entry['request_sha256'] = sha(request_path)
            entry['advertised_tools'] = [t['function']['name'] for t in request['tools']]
            entry['tool_choice'] = request.get('tool_choice')
        if response is not None:
            entry['response_sha256'] = sha(response_path)
            entry['response_error_type'] = response.get('error_type')
            choices = response.get('choices') or []
            entry['choice_count'] = len(choices)
            entry['choices'] = [choice_summary(choice) for choice in choices]
        if row['usage_state'] == 'known':
            usage = row['usage']
            assert response is not None and usage == response['usage']
            assert row['usage_sha256'] == hashlib.sha256(canonical(usage)).hexdigest()
            assert usage['total_tokens'] == usage['prompt_tokens'] + usage['completion_tokens']
            total_prompt += usage['prompt_tokens']; total_completion += usage['completion_tokens']
            total_tokens += usage['total_tokens']
            item_cost = (Decimal(usage['prompt_tokens']) * Decimal(str(ledger['config']['input_cny_per_million']))
                         + Decimal(usage['completion_tokens']) * Decimal(str(ledger['config']['output_cny_per_million']))) / Decimal(1000000)
            assert item_cost == Decimal(str(row['actual_estimated_cost_cny']))
            cost += item_cost
        else:
            unknown += 1
        for key in ('transport-request', 'transport-result'):
            path = session_dir / (key + '.json')
            if path.is_file():
                entry[key.replace('-', '_')] = read(path)
        if 'transport_request' in entry:
            assert request is not None and entry['transport_request']['request_sha256'] == sha(request_path)
        if 'transport_result' in entry:
            assert entry['transport_result']['request_receipt_sha256'] == sha(session_dir / 'transport-request.json')
        proof_path = session_dir / 'sdk-dispatch.json'
        # Current transport writes the proof under this filename. If no proof
        # exists, preserve the absence (e.g. refusal before network dispatch).
        if proof_path.is_file():
            entry['dispatch'] = verify_dispatch_record(session_dir, settings)
            entry['dispatch_verified'] = True
        else:
            entry['dispatch_verified'] = False
        # A response file containing only a locally raised error is not itself
        # provider evidence. Returned transport, provider id/choices or any
        # supplied usage requires the actual SDK-to-LiteLLM attempt receipt.
        has_provider_response = (entry.get('transport_result', {}).get('status') == 'returned'
            or (response is not None and (bool(response.get('response_id'))
                or bool(response.get('choices')) or response.get('usage') is not None))
            or row.get('usage') is not None)
        assert not (has_provider_response and not entry['dispatch_verified']), (
            'Provider response or usage without verified SDK dispatch', row['session_id'])
        assert not (entry['session_status'] == 'accepted' and not entry['dispatch_verified']), (
            'Accepted session without verified SDK dispatch', row['session_id'])
        entry['provider_response_or_usage_present'] = has_provider_response
        entry['acceptance_files_present'] = {name: (session_dir / name).is_file()
            for name in ('sdk-submission.json', 'submission.json', 'acceptance-attempt.json', 'source.py')}
        requests.append(entry)
    assert total_prompt == budget['known_prompt_tokens'] and total_completion == budget['known_completion_tokens']
    assert total_tokens == budget['known_total_tokens'] and unknown == budget['usage_unknown_count']
    assert cost == Decimal(str(budget['known_estimated_cost_cny']))
    assert sum(Decimal(str(r['reserved_cost_cny'])) for r in rows) == Decimal(str(budget['reserved_cost_cny']))
    dispatch_requests = [r for r in requests if r['dispatch_verified']]
    dispatch_count = len(dispatch_requests)
    actual_proof_sessions = {p.parent.name for p in (experiment / 'sessions').glob('*/sdk-dispatch.json')}
    assert actual_proof_sessions == {r['slot_id'] for r in dispatch_requests}, 'Unbound SDK dispatch record'
    dispatched_unknown = sum(r['usage_state'] != 'known' for r in dispatch_requests)
    assert len(rows) - unknown == dispatch_count - dispatched_unknown
    update_hashes = [r.get('request_sha256') for r in requests if slots[r['slot_id']]['slot']['phase'] == 'update']
    if len(update_hashes) > 1:
        assert len(set(update_hashes)) == 1
    known_requests = dispatch_count - dispatched_unknown
    activity = dict(model_requests=dispatch_count, sdk_dispatch_attempts=dispatch_count,
        ledger_reserved_requests=len(rows), ledger_reservations_equal_dispatch_attempts=len(rows) == dispatch_count,
        accepted_policy_proposals=len(proposals),
        candidate_S1_proposals=sum(k.endswith('-updated') for k in proposals),
        distinct_proposals=len({tuple(v) for v in proposals.values()}),
        selected_S_star=len(decisions),
        accepted_new_candidate_programs=sum(s.get('session', {}).get('status') == 'accepted'
            and s['slot']['phase'] != 'update' for s in slots.values()),
        task_measurements=len(measurements), planning_measurements=sum(r['family'] == 'planning' for r in measurements),
        symbolic_measurements=sum(r['family'] == 'symbolic' for r in measurements),
        sandbox_executions=sum(len(r.get('executions', [])) for r in measurements),
        val_calls=sum('validator' in r for r in measurements),
        symbolic_fits=sum(any(x.get('phase') == 'fit' for x in r.get('executions', [])) for r in measurements),
        evaluation_states_executed=len({r['parent_id'] for r in measurements if r['parent_id'] in eval_states}),
        sealed_evaluations=sum(r['sealed_tasks_executed'] for r in measurements),
        weight_updates=0, new_probes=0)
    after = {name: sha(safe(name)) for name in files}
    assert before == after, 'Original files changed during analysis'
    report = dict(version='strategy-measured-readonly-analysis-v0.1', status='passed', run_id=args.run_id,
        run_status=summary['status'], slot_counts=summary['slot_counts'],
        source_export=dict(path=export_path.relative_to(root).as_posix(), sha256=sha(export_path)),
        raw_files_unchanged=len(files), raw_files_before_sha256=hashlib.sha256(canonical(before)).hexdigest(),
        raw_files_after_sha256=hashlib.sha256(canonical(after)).hexdigest(),
        research_activity=activity, proposals=proposals, update_request_count=len(update_hashes),
        update_requests_identical=(len(set(update_hashes)) == 1 if update_hashes else None),
        decisions=decisions, production_evaluation_gate=gate,
        evaluation_opening=dict(decision_event_ordinals=decision_events, gate_event_ordinals=gate_events,
                               first_evaluation_access_ordinal=min(eval_access_events) if eval_access_events else None),
        baselines=baselines, actors=actors, pairs=pair_comparisons,
        stored_evaluation_pairs=summary['evaluation_pairs'],
        failure=summary['failure'], requests=requests,
        budget=dict(requests=dispatch_count, ledger_reserved_requests=len(rows),
            sdk_dispatch_attempts=dispatch_count, ledger_reservations_equal_dispatch_attempts=len(rows) == dispatch_count,
            known_usage_requests=known_requests, unknown_usage_requests=dispatched_unknown,
            ledger_unknown_usage_rows=unknown,
            known_prompt_tokens=total_prompt, known_completion_tokens=total_completion,
            known_total_tokens=total_tokens, known_estimated_cost_cny=float(cost),
            reserved_cost_cny=budget['reserved_cost_cny'], actual_total_cost_cny=None),
        cumulative_research=dict(requests=args.prior_requests + dispatch_count, known_tokens=args.prior_tokens + total_tokens,
            known_estimated_cost_cny=float(Decimal(args.prior_estimate) + cost),
            reserved_cost_cny=float(Decimal(args.prior_reserved) + Decimal(str(budget['reserved_cost_cny']))),
            unknown_usage_requests=args.prior_unknown + dispatched_unknown, actual_total_cost_cny=None),
        analysis_activity=dict(model_requests=0, candidate_executions=0, task_measurements=0, strategy_updates=0),
        boundary='Read-only summary of observed client-persisted records. Real model requests count verified SDK-to-LiteLLM dispatch attempts, not budget reservations; the proof is written immediately before invoking the underlying provider callable and is not HTTP/provider attestation. Returned transport/provider responses or usage without a proof are rejected. Does not rerun providers, candidates, fits, or selector. Pure goal acceptance is recomputed from saved task observations; stored decision hashes and chosen-policy correspondence checked. Production audit remains required. Proposals are not selected S*, and train metrics are not sealed predictive generalization.')
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(canonical(report) + b'\n')
    print(json.dumps({k: report[k] for k in ('status', 'run_id', 'run_status', 'slot_counts', 'raw_files_unchanged',
                                           'research_activity', 'budget', 'cumulative_research')}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
