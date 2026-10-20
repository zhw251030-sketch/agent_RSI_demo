#!/usr/bin/env python3
"""Audit frozen policy reviews and repair responses without task or SDK execution."""
import argparse
from collections import Counter
import copy
from decimal import Decimal
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True

from scripts.analyze_paired_repair import (canonical, classify_response, digest, inside,
    parse_json, read_json, record_score, require, tree_hashes, verify_audit)
from scripts.analyze_policy_transfer import (_request_record, _policy_call,
    _literal_assignment, _actor_task_text, compute_endpoint, request_packet, verify_budget_state)
from rsi_eval.evidence_ids import EvidenceRegistry
from rsi_eval.grounded_policy import (CONTROLLER_VERSION, _COMMON_INSTRUCTIONS,
    check_submission, factual_catalogue, load_frozen_policy, validate_submission)
from rsi_eval.revision_policy import S0, catalog, render_policy

PROTOCOL = 'docs/protocols/2026-10-20-grounded-policy-v0.1.md'
CONFIG = 'configs/pilots/grounded-policy-v0.1.json'


def expected_updates():
    return [dict(pair_id=pair, condition=condition, session_id=pair+'-'+condition)
            for pair, conditions in [('p1', ('proposal', 'self', 'checked')),
                                     ('p2', ('proposal', 'checked', 'self'))]
            for condition in conditions]


def expected_actors():
    order = [('p1', 'P-A002', 'self'), ('p1', 'S-poly5', 'checked'),
        ('p1', 'P-A002', 'checked'), ('p1', 'S-poly5', 'self'),
        ('p2', 'S-odd4', 'self'), ('p2', 'P-B002', 'checked'),
        ('p2', 'S-odd4', 'checked'), ('p2', 'P-B002', 'self')]
    return [dict(policy_pair=pair, pair_id=pair+'-'+state, state_id=state, condition=arm,
        family='planning' if state.startswith('P-') else 'symbolic',
        session_id=pair+'-'+state+'-'+arm) for pair, state, arm in order]


def validate_layout(config, summary):
    require(config.get('update_order') == expected_updates()
            and config.get('evaluation_order') == expected_actors()
            and config.get('max_iterations') == 1 and config.get('max_generated_candidates') == 1,
            'Frozen update/evaluation layout or one-step bound changed')
    for field, order in [('updates', expected_updates()), ('sessions', expected_actors())]:
        rows = summary.get(field)
        require(type(rows) is list and len(rows) == len(order)
                and [{key: row.get(key) for key in spec} for row, spec in zip(rows, order)] == order,
                'Assigned '+field+' identities or order changed')


def verify_dispatch(summary, rows, names):
    require(len(rows) <= 14 and [r['request_id'] for r in rows]
            == ['request-'+str(i).zfill(4) for i in range(1, len(rows)+1)],
            'Ledger request IDs are not sequential and unique')
    actual = [r['session_id'] for r in rows]
    require(actual == names[:len(actual)], 'Dispatch differs from frozen prefix')
    if summary['status'] == 'attempts_completed':
        require(actual == names, 'Completed run is missing assigned requests')


def common_request(request, field):
    require(field in ('premise_feedback', 'repair_policy'), 'Unauthorized comparison removal')
    result = copy.deepcopy(request); packet = request_packet(result)
    require(field in packet, 'Comparison channel missing')
    packet.pop(field)
    result['messages'][1]['content'] = canonical(packet).decode('utf-8')
    return result


def verify_pairs(requests, order, field):
    require(set(requests) <= {r['session_id'] for r in order}, 'Unexpected paired session')
    results = []
    for pair in sorted({r['pair_id'] for r in order}):
        rows = [r for r in order if r['pair_id'] == pair]
        require(len(rows) == 2 and {r['condition'] for r in rows} == {'self', 'checked'},
                'Pair must contain self and checked exactly once')
        present = [r['session_id'] for r in rows if r['session_id'] in requests]
        common = [canonical(common_request(requests[name], field)) for name in present]
        require(len(set(common)) <= 1, 'Common request differs beyond '+field)
        results.append({'pair_id': pair, 'assigned_sessions': [r['session_id'] for r in rows],
            'requested_sessions': present, 'both_requested': len(present) == 2,
            'exact_common_request_equality': len(present) == 2,
            'removed_packet_fields': [field],
            'common_request_sha256': digest(common[0]) if common else None,
            'common_request_bytes': len(common[0]) if common else None})
    return results


def policy_arguments(response):
    arguments = _policy_call(response)
    return {key: value for key, value in arguments.items() if key not in ('summary', 'security_risk')}


def schema_length_issues(arguments, request):
    tool = next(t for t in request['tools'] if t['function']['name'] == 'submit_policy')
    properties = tool['function'].get('parameters', {}).get('properties', {})
    issues = []
    for field, value in arguments.items():
        limit = properties.get(field, {}).get('maxLength')
        if type(value) is str and type(limit) is int and len(value) > limit:
            issues.append({'field': field, 'actual_characters': len(value), 'maximum_characters': limit,
                           'source': 'exact_dispatched_tool_schema', 'status': 'exceeds_maxLength'})
    return issues


def expected_update_packet(bundle, pair_id, proposal, feedback):
    phase = ('Produce an initial proposal. ' if proposal is None
             else 'Produce your final revision of the supplied proposal. ')
    return {'version': CONTROLLER_VERSION, 'pair_id': pair_id,
        'task_text': phase+_COMMON_INSTRUCTIONS, 'catalog': catalog(),
        'parent_policy': render_policy(S0), 'experience_cases': copy.deepcopy(bundle['cases']),
        'factual_catalogue': factual_catalogue(bundle), 'proposal': copy.deepcopy(proposal),
        'premise_feedback': copy.deepcopy(feedback)}


def cost_breakdown(ledger):
    groups = {key: [] for key in ('all', 'update_proposal', 'update_self', 'update_checked',
                                  'actor_self', 'actor_checked')}
    roles = {r['session_id']: 'update_'+r['condition'] for r in expected_updates()}
    roles.update({r['session_id']: 'actor_'+r['condition'] for r in expected_actors()})
    config = ledger['config']
    def price(inputs, outputs):
        return float((Decimal(inputs)*Decimal(str(config['input_cny_per_million']))
            + Decimal(outputs)*Decimal(str(config['output_cny_per_million'])))/1000000)
    for row in ledger['requests']:
        require(row['session_id'] in roles, 'Unknown cost session')
        require(row['input_token_reservation'] == row['input_bytes']+8192
                and row['reserved_cost_cny'] == price(row['input_token_reservation'], row['output_token_reservation']),
                'Reserved input or cost disagrees with frozen accounting')
        if row['usage_state'] == 'known':
            usage = row['usage']
            require(type(usage) is dict and set(usage) == {'prompt_tokens', 'completion_tokens', 'total_tokens'}
                and all(type(v) is int and v >= 0 for v in usage.values())
                and usage['total_tokens'] == usage['prompt_tokens']+usage['completion_tokens']
                and row['actual_estimated_cost_cny'] == price(usage['prompt_tokens'], usage['completion_tokens']),
                'Actual usage or configured cost estimate is inconsistent')
            require(usage['prompt_tokens'] <= row['input_token_reservation']
                    and usage['completion_tokens'] <= row['output_token_reservation'],
                    'Known usage exceeds request reservation')
        groups['all'].append(row); groups[roles[row['session_id']]].append(row)
    result = {}
    for key, rows in groups.items():
        known = [r['usage'] for r in rows if r['usage_state'] == 'known']
        inputs = sum(r['prompt_tokens'] for r in known); outputs = sum(r['completion_tokens'] for r in known)
        reserved_in = sum(r['input_token_reservation'] for r in rows)
        reserved_out = sum(r['output_token_reservation'] for r in rows)
        unknown = len(rows)-len(known)
        result[key] = {'requests': len(rows), 'known_prompt_tokens': inputs,
            'known_completion_tokens': outputs, 'known_total_tokens': inputs+outputs,
            'known_estimated_cost_cny': price(inputs, outputs), 'unknown_usage_requests': unknown,
            'actual_total_tokens': None if unknown else inputs+outputs,
            'actual_estimated_cost_cny': None if unknown else price(inputs, outputs),
            'reserved_tokens': reserved_in+reserved_out, 'reserved_cost_cny': price(reserved_in, reserved_out),
            'cost_basis': 'configured_uncached_prices_estimate_not_provider_invoice'}
    if 'max_reserved_tokens' in config:
        require(result['all']['reserved_tokens'] <= config['max_reserved_tokens']
                and result['all']['reserved_cost_cny'] <= config['max_cost_cny'], 'Total reservation exceeds frozen caps')
    return result


def verify_sources(summary, project_root):
    commit, sources = summary.get('code_commit'), summary.get('source_sha256')
    require(type(commit) is str and re.fullmatch(r'[0-9a-f]{40}', commit) is not None
            and type(sources) is dict and sources, 'Missing frozen runtime provenance')
    for name in sources:
        require(type(name) is str and not Path(name).is_absolute() and '..' not in Path(name).parts
                and not any(c in name for c in '\n\r:\\'), 'Unsafe runtime source path')
    tracked = subprocess.run(['git', 'ls-tree', '-r', '--name-only', '-z', commit],
        capture_output=True, check=True, cwd=project_root).stdout.decode('utf-8').split('\0')
    expected = {name for name in tracked if name and ((name.split('/')[0] in
        ('rsi_eval', 'scripts', 'configs', 'prompts', 'fixtures') and Path(name).suffix in ('.py', '.json', '.md'))
        or name == PROTOCOL)}
    require(set(sources) == expected, 'Source manifest omits or adds frozen runtime files')
    paths = sorted(sources)
    response = subprocess.run(['git', 'cat-file', '--batch'],
        input=''.join(commit+':'+name+'\n' for name in paths).encode(), capture_output=True,
        check=True, cwd=project_root).stdout
    blobs = {}; offset = 0
    for name in paths:
        end = response.index(b'\n', offset); header = response[offset:end].split()
        require(len(header) == 3 and header[1] == b'blob', 'Frozen source blob unavailable')
        size = int(header[2]); start = end+1; blob = response[start:start+size]
        require(len(blob) == size and response[start+size:start+size+1] == b'\n'
                and digest(blob) == sources[name], 'Frozen source digest mismatch')
        blobs[name] = blob; offset = start+size+1
    require(offset == len(response), 'Trailing source blob data')
    return blobs


def verify_update(directory, spec, reported, reservation, bundle, proposal, feedback, blobs,
                  ledger, summary, phase):
    entry = {**spec, 'requested': reservation is not None, 'accepted': False, 'frozen': False}
    request = None; policy = None
    if reservation is None:
        require(not (directory/'submission.json').exists() and not (directory/'freeze.json').exists()
                and not list((directory/'requests').glob('*.request.json')), 'Unrequested update has model artifacts')
        return entry, request, policy
    system = _literal_assignment(blobs['rsi_eval/pilot_agent.py'], 'POLICY_UPDATE_SYSTEM_PROMPT')
    request, packet, response, detail = _request_record(directory, reservation, ledger['config'], system)
    require(request['model'] == summary['effective_model_config']['model'], 'Updater model changed')
    require({t['function']['name'] for t in request['tools']} == {'submit_policy', 'finish'}, 'Updater tools changed')
    expected = expected_update_packet(bundle, spec['pair_id'], proposal, feedback)
    require(packet == expected == read_json(directory/'task-packet.json'), 'Updater input differs from expected evidence and proposal')
    entry.update(detail)
    entry.update(sdk_status=reported.get('status'), sdk_conversation_status=reported.get('conversation_status'),
                 saved_controller_summary=copy.deepcopy(reported.get('controller')))
    events = [parse_json(line) for line in (directory/'events.jsonl').read_text(encoding='utf-8').splitlines() if line]
    actions = [e for e in events if e.get('type') == 'ActionEvent' and e.get('tool_name') == 'submit_policy']
    observations = [e for e in events if e.get('type') == 'ObservationEvent' and e.get('tool_name') == 'submit_policy']
    errors = [e for e in events if e.get('type') == 'AgentErrorEvent' and e.get('tool_name') == 'submit_policy']
    try:
        literal = policy_arguments(response)
    except ValueError:
        literal = None
    if literal is not None:
        call = response['choices'][0]['message']['tool_calls'][0]
        call_id, response_id = call.get('id'), response.get('response_id')
        require(type(call_id) is str and type(response_id) is str and len(actions) == 1
                and actions[0].get('tool_call_id') == call_id and actions[0].get('llm_response_id') == response_id
                and all(e.get('tool_call_id') == call_id for e in observations+errors),
                'SDK events do not bind exact saved tool call and response IDs')
        try:
            validate_submission(literal); structural = 'valid'
        except ValueError:
            structural = 'invalid'
        entry.update(literal_submission=literal, literal_structural_status=structural,
            schema_length_issues=schema_length_issues(literal, request),
            event_counts={'actions': len(actions), 'observations': len(observations), 'agent_errors': len(errors)},
            tool_call_id=call_id, llm_response_id=response_id)
    else:
        entry['literal_structural_status'] = 'no_single_parseable_submit_policy_call'
    submission_path = directory/'submission.json'
    if submission_path.exists():
        arguments = policy_arguments(response); submission = read_json(submission_path)
        require(arguments == submission, 'Saved submission differs from exact model call arguments')
        _, policy = validate_submission(submission)
        checks = check_submission(submission, bundle, S0)
        require(checks == read_json(directory/'checks.json') and policy == read_json(directory/'policy.json'),
                'Saved policy or facts differ from recomputation')
        require(reported.get('selected_policy') in (None, policy), 'Reported selected policy differs')
        if 'all_checked_pass' in reported:
            require(reported['all_checked_pass'] == checks['all_checked_pass'], 'Reported premise checks differ')
        entry.update(accepted=True, selected_policy=policy, no_op=policy == S0, checks=checks,
                     submission=submission, applicability_certified=False)
        require(len(actions) == 1 and len(observations) == 1 and not errors,
                'Accepted policy lacks one matching SDK action and observation')
    else:
        require(not (directory/'policy.json').exists() and not (directory/'checks.json').exists(),
                'Unaccepted submission has a saved policy or checks')
        entry.update(outcome='no_accepted_policy', factual_checks_available=False,
                     fixed_factual_obligations=11,
                     controller_attempt_record_exists=(directory/'attempt.json').exists())
    if (directory/'freeze.json').exists():
        require(policy is not None and reservation['usage_state'] == 'known' and reservation['status'] == 'settled',
                'Frozen policy lacks accepted call and known settled usage')
        anchor = phase['freezes'][spec['session_id']] if phase else None
        selected = load_frozen_policy(directory, bundle, S0, proposal=proposal, feedback=feedback,
            condition=spec['condition'], pair_id=spec['pair_id'], expected_freeze_sha256=anchor)
        frozen = read_json(directory/'freeze.json')
        require(selected == policy and frozen['request_id'] == reservation['request_id'], 'Freeze differs from actual request')
        entry.update(frozen=True, freeze_sha256=digest((directory/'freeze.json').read_bytes()))
    require(not list(directory.glob('candidates/*.py')), 'Updater unexpectedly contains executable candidates')
    return entry, request, policy


def verify_actor(directory, spec, reported, reservation, state, policy, blobs, base, ledger, summary):
    entry = {**spec, 'request_count': 0, 'generated_candidate_records': 0,
             'new_task_result_records': 0, 'archived_task_result_records': 0,
             'child_score': None, 'improvement': None, 'submitted_and_improved': False, 'audits': []}
    if not (directory/'candidates.json').exists():
        require(reservation is None, 'Requested actor has no baseline records')
        return entry, None, [], []
    records = read_json(directory/'candidates.json'); baseline = records[0]
    endpoint = compute_endpoint(records, spec['family']); family = spec['family']
    require(baseline.get('candidate_id') == family+'-000' and baseline.get('parent_id') is None
        and baseline.get('origin') == 'archived_model_proposed_initial'
        and all(baseline.get(key) == state['record'][key] for key in ('source_sha256', 'n_params', 'metrics', 'results')),
        'Copied actor baseline differs from pinned state')
    require(read_json(directory/'repair-state-provenance.json') == state['provenance'], 'Copied baseline provenance differs')
    for index, record in enumerate(records):
        require(record['candidate_id'] == family+'-'+str(index).zfill(3), 'Unexpected candidate identity')
        require(digest(inside(directory, 'candidates/'+record['candidate_id']+'.py').read_bytes()) == record['source_sha256'],
                'Candidate source digest differs')
        require(all(result.get('candidate_hash') == record['source_sha256'] for result in record.get('results', [])),
                'Execution source identity differs')
    evidence = read_json(directory/'evidence.json')
    for record in records:
        snapshots = evidence.get(record['candidate_id'], [])
        require(snapshots, 'Candidate evidence missing')
        for snapshot in snapshots:
            binding = snapshot['binding']
            require(binding['session_id'] == summary['run_id']+':'+spec['pair_id']
                and binding['candidate_id'] == record['candidate_id']
                and binding['candidate_sha256'] == record['source_sha256'], 'Evidence identity changed')
        if record_score(record, family) is not None:
            primary = [s for s in snapshots if s['binding']['task_id'] == ('planning_batch' if family == 'planning' else 'oscillator1')]
            require(len(primary) == 1 and all(primary[0]['scalars'].get(k) == v for k, v in record['metrics'].items()),
                    'Evidence scores differ from actual outcome records')
    entry.update(endpoint, baseline_source_sha256=baseline['source_sha256'], sdk_status=reported.get('status'),
                 sdk_conversation_status=reported.get('conversation_status'))
    request = None; arguments = None
    if reservation is not None:
        require(policy is not None, 'Actor requested without frozen selected policy')
        system = _literal_assignment(blobs['rsi_eval/pilot_agent.py'], 'SINGLE_REVISION_SYSTEM_PROMPT')
        request, packet, response, detail = _request_record(directory, reservation, ledger['config'], system)
        require(request['model'] == summary['effective_model_config']['model']
                and {t['function']['name'] for t in request['tools']} == {'submit_candidate', 'finish'},
                'Actor model or tools changed')
        session = next(s for s in base['sessions'] if s['family'] == family)
        task = _actor_task_text(blobs[session['prompt_file']].decode('utf-8'),
                                blobs['prompts/policy-transfer/actor.md'].decode('utf-8'))
        require(packet['task_text'] == task and packet['repair_policy'] == render_policy(policy)
                and packet['experience_memory'] == [] and packet['available_revision_rules'] == catalog(),
                'Actor policy, task, catalog or experience differs')
        require(packet['session_id'] == summary['run_id']+':'+spec['pair_id']
                and packet['checks_visible'] is False and packet['frozen_history_common'] == {}
                and packet['declared_hypotheses'] == [] and 'audits' not in packet,
                'Actor input contains unauthorized history')
        require(packet['metadata']['records_sha256'] == digest(canonical([baseline]))
                and packet['incumbent'] == {'candidate_id': family+'-000', 'source_sha256': baseline['source_sha256'],
                    'n_params': baseline['n_params'], 'source': state['source']}, 'Actor starting source differs')
        registry = EvidenceRegistry(evidence[family+'-000'], session_id=packet['session_id'])
        require(packet['evidence'] == registry.entries()
                and packet['metadata']['evidence_sha256'] == digest(canonical(registry.entries())), 'Actual actor evidence changed')
        require(read_json(directory/'task-prompt.json') == packet, 'Prepared actor packet differs from request')
        kind, arguments = classify_response(response)
        entry.update(detail, request_count=1, response_kind=kind)
        if records[1:]:
            child = records[1]
            require(type(arguments) is dict and type(arguments.get('source')) is str
                and digest(arguments['source'].encode('utf-8')) == child['source_sha256']
                and arguments.get('n_params') == child['n_params']
                and arguments.get('rationale') == child.get('rationale'), 'Child differs from literal model submission')
    else:
        require(len(records) == 1 and not list((directory/'requests').glob('*.request.json')), 'Unrequested actor has child or request')
        entry['response_kind'] = 'not_requested'
    audits = read_json(directory/'audits.json') if (directory/'audits.json').exists() else []
    require(len(audits) == len(records)-1, 'Every executed child needs one declaration audit')
    entry['audits'] = [verify_audit(directory, item, evidence, arguments) for item in audits]
    if 'endpoint' in reported:
        endpoint_keys = {'generated_candidates_executed': endpoint['generated_candidate_records'],
            'actual_task_executions': endpoint['new_task_result_records'],
            'archived_task_records': endpoint['archived_task_result_records'],
            'baseline_metrics': baseline['metrics'],
            'child_metrics': records[1]['metrics'] if endpoint['child_score'] is not None else None,
            'improvement': endpoint['improvement'], 'submitted_and_improved': endpoint['submitted_and_improved']}
        require(reported['endpoint'] == endpoint_keys, 'Reported actor endpoint differs from records')
    old_ids = [r['run_id'] for r in baseline['results']]
    new_ids = [r['run_id'] for child in records[1:] for r in child.get('results', [])]
    return entry, request, old_ids, new_ids


def analyze(run, output, *, project_root=ROOT):
    run, output, project_root = Path(run).resolve(), Path(output).resolve(), Path(project_root).resolve()
    require(run.is_dir() and not output.exists() and output.parent.is_dir() and not output.is_relative_to(run),
            'Audit output must be a new file outside an existing immutable run')
    before = tree_hashes(run)
    report = {'version': 'grounded-policy-analysis-v0.1', 'status': 'error', 'updates': [],
        'review_pairs': [], 'actors': [], 'actor_pairs': [], 'counts': {}, 'costs': {},
        'new_model_calls': 0, 'new_candidate_executions': 0,
        'scope': 'Two learned policy pairs and four researcher-seen development states; no independent-task or significance claim.',
        'request_comparison_scope': 'Saved SDK pre-transport envelopes, not independently captured HTTP.',
        'registration_timing_independently_proven': False, 'verification': {}}
    try:
        summary, config, ledger = (read_json(run/name) for name in ('summary.json', 'config.json', 'budget-ledger.json'))
        validate_layout(config, summary); blobs = verify_sources(summary, project_root)
        report.update(run_id=summary['run_id'], runtime_commit=summary['code_commit'],
                      reported_run_status=summary['status'], stop_reason=summary.get('stop_reason'))
        for name in ('rsi_eval/grounded_policy.py', 'rsi_eval/grounded_states.py', 'rsi_eval/revision_policy.py',
                     'rsi_eval/policy_cases.py', 'rsi_eval/repair_states.py',
                     'rsi_eval/evidence_ids.py', 'rsi_eval/evidence_checks.py',
                     'scripts/analyze_policy_transfer.py', 'scripts/analyze_paired_repair.py'):
            require(name in blobs and (project_root/name).read_bytes() == blobs[name], 'Audit helper differs from runtime: '+name)
        require(parse_json(blobs[CONFIG]) == config and digest(blobs[CONFIG]) == summary['config_sha256'], 'Frozen run config changed')
        base = read_json(run/'base-config.json')
        require(base == parse_json(blobs[config['base_config']]), 'Base configuration changed')
        public = parse_json(blobs[base['model_configuration']])
        effective = dict(public, max_output_tokens=config['budgets']['max_output_tokens'], num_retries=0,
            stream=False, caching_prompt=False, api_mode='chat', fallback_strategy=None, log_completions=False)
        require(digest(blobs[base['model_configuration']]) == summary['model_config_sha256']
                and summary['model_config'] == public and summary['effective_model_config'] == effective,
                'Frozen model settings changed')
        require(summary.get('mode') in ('update', 'evaluate') and summary.get('sealed_test_evaluations') == 0
                and summary.get('baseline_reexecutions') == 0 and summary.get('automatic_recovery_enabled') is False,
                'Protected execution boundary changed')
        from rsi_eval.policy_cases import load_update_bundle
        from rsi_eval.grounded_states import load_grounded_states
        bundle = read_json(run/'update-bundle.json')
        require(bundle == load_update_bundle(project_root), 'Update evidence differs from pinned cards')
        states = {s['state_id']: s for s in load_grounded_states(project_root)}
        require(read_json(run/'state-provenance.json') == {k:v['provenance'] for k,v in states.items()}, 'Pinned state provenance changed')
        names = [r['session_id'] for r in expected_updates()+expected_actors()]
        require(ledger['config'] == {**config['budgets'], 'session_ids': names}, 'Ledger scope or budgets changed')
        reservations = ledger['requests']; verify_dispatch(summary, reservations, names)
        report['verification']['settlement'] = verify_budget_state(summary, ledger)
        by_session = {r['session_id']: r for r in reservations}
        phase = None
        if (run/'update-phase-freeze.json').exists():
            phase = read_json(run/'update-phase-freeze.json')
            require(phase.get('version') == 'grounded-policy-phase-v0.1'
                    and set(phase.get('freezes', {})) == {r['session_id'] for r in expected_updates()}
                    and summary.get('phase_freeze_sha256') == digest((run/'update-phase-freeze.json').read_bytes()),
                    'Update phase freeze anchor changed')
        if (run/'evaluation-started.json').exists():
            require(phase is not None and read_json(run/'evaluation-started.json') ==
                    {'phase_freeze_sha256': summary['phase_freeze_sha256']}, 'Evaluation phase marker changed')
        elif any(r['session_id'] in by_session for r in expected_actors()):
            raise ValueError('Actor request lacks frozen evaluation phase marker')
        policies = {}; review_requests = {}; actor_requests = {}; old_ids = []; new_ids = []
        for spec, reported in zip(expected_updates(), summary['updates']):
            proposal_path = run/(spec['pair_id']+'-proposal')/'submission.json'
            proposal = None if spec['condition'] == 'proposal' or not proposal_path.exists() else read_json(proposal_path)
            feedback = check_submission(proposal, bundle, S0) if spec['condition'] == 'checked' and proposal else None
            if spec['condition'] != 'proposal' and spec['session_id'] in by_session:
                require(proposal is not None, 'Requested review lacks initial proposal')
            entry, request, policy = verify_update(run/spec['session_id'], spec, reported,
                by_session.get(spec['session_id']), bundle, proposal, feedback, blobs, ledger, summary, phase)
            report['updates'].append(entry)
            if entry['frozen']: policies[spec['session_id']] = policy
            if request is not None and spec['condition'] != 'proposal': review_requests[spec['session_id']] = request
        if phase is not None:
            require(all(e['frozen'] for e in report['updates']), 'Phase claims missing frozen updates')
        for spec, reported in zip(expected_actors(), summary['sessions']):
            entry, request, old, new = verify_actor(run/spec['session_id'], spec, reported,
                by_session.get(spec['session_id']), states[spec['state_id']],
                policies.get(spec['policy_pair']+'-'+spec['condition']), blobs, base, ledger, summary)
            report['actors'].append(entry); old_ids.extend(old); new_ids.extend(new)
            if request is not None: actor_requests[spec['session_id']] = request
        require(len(new_ids) == len(set(new_ids)) and not set(new_ids) & set(old_ids),
                'New execution IDs duplicate each other or copied baseline IDs')
        report['review_pairs'] = verify_pairs(review_requests,
            [r for r in expected_updates() if r['condition'] != 'proposal'], 'premise_feedback')
        report['actor_pairs'] = verify_pairs(actor_requests, expected_actors(), 'repair_policy')
        for proof in report['review_pairs']:
            first = policies.get(proof['pair_id']+'-self')
            second = policies.get(proof['pair_id']+'-checked')
            proof.update(both_policies_frozen=first is not None and second is not None,
                policies_identical=(first == second) if first is not None and second is not None else None,
                self_policy=first, checked_policy=second)
        for proof in report['review_pairs']:
            if proof['both_requested'] and 'review_input_proofs' in summary:
                packet = request_packet(review_requests[proof['requested_sessions'][0]])
                packet.pop('premise_feedback')
                require(summary['review_input_proofs'].get(proof['pair_id']) == digest(canonical(packet)),
                        'Prepared review pair digest differs from actual common input')
        for proof in report['actor_pairs']:
            if proof['requested_sessions']:
                packet = request_packet(actor_requests[proof['requested_sessions'][0]])
                packet.pop('repair_policy'); prepared = summary['pair_input_proofs'][proof['pair_id']]
                require(prepared['common_sha256'] == digest(canonical(packet))
                        and prepared['common_bytes'] == len(canonical(packet))
                        and prepared['source_sha256'] == packet['incumbent']['source_sha256'],
                        'Prepared actor pair proof differs from actual common input')
        report['costs'] = cost_breakdown(ledger)
        totals = report['costs']['all']; reported_budget = summary['budget']
        for field, key in [('reserved_tokens', 'reserved_tokens'), ('reserved_cost_cny', 'reserved_cost_cny'),
                           ('known_prompt_tokens', 'known_prompt_tokens'), ('known_completion_tokens', 'known_completion_tokens'),
                           ('known_total_tokens', 'known_total_tokens'), ('known_estimated_cost_cny', 'known_estimated_cost_cny'),
                           ('actual_tokens', 'actual_total_tokens'), ('actual_estimated_cost_cny', 'actual_estimated_cost_cny')]:
            require(reported_budget.get(field) == totals[key], 'Budget summary '+field+' differs from ledger')
        claims = Counter(); predictions = Counter(); registrations = Counter()
        for row in report['actors']:
            for audit in row['audits']:
                claims[audit['claim_result']['status']] += 1
                predictions[audit['prediction_result']['status']] += 1
                registrations[audit['registration']['status']] += 1
        report['counts'] = {'requests': len(reservations),
            'update_requests': sum(e['requested'] for e in report['updates']),
            'frozen_updates': sum(e['frozen'] for e in report['updates']),
            'evaluation_requests': len(actor_requests),
            'generated_candidate_records': sum(e['generated_candidate_records'] for e in report['actors']),
            'new_task_result_records': len(new_ids), 'unique_new_evaluator_run_ids': len(set(new_ids)),
            'archived_task_result_records': len(old_ids), 'unique_archived_evaluator_run_ids': len(set(old_ids)),
            'claim_statuses': dict(claims), 'prediction_statuses': dict(predictions),
            'registration_statuses': dict(registrations)}
        report['verification'].update(source_provenance_files_verified=len(blobs),
            request_order_verified=True, accepted_policy_calls_match_saved_arguments=True,
            accepted_policy_checks_recomputed=sum(e['accepted'] for e in report['updates']),
            unaccepted_requested_updates_not_scored=sum(e['requested'] and not e['accepted'] for e in report['updates']),
            evaluator_id_sets_disjoint=True,
            completed_all_assigned_requests=len(reservations) == 14,
            accepted_policies_do_not_certify_applicability=True)
        report['verification']['full_actor_packet_reconstructed_from_executor'] = False
        report['verification']['actor_pair_equality_observed'] = any(p['both_requested'] for p in report['actor_pairs'])
        report['verification']['review_pair_equality_observed'] = any(p['both_requested'] for p in report['review_pairs'])
        report['status'] = 'verified' if len(reservations) == 14 else 'verified_partial'
    except Exception as error:
        report['error_type'] = type(error).__name__
        if type(error) is ValueError: report['verification_failure'] = str(error)
    finally:
        after = tree_hashes(run)
        report.update(run_file_count=len(before), run_files_unchanged=before == after,
            run_tree_before_sha256=digest(canonical(before)), run_tree_after_sha256=digest(canonical(after)),
            input_file_sha256=before, analysis_script_sha256=digest(Path(__file__).read_bytes()))
        if before != after: report.update(status='error', error_type='RunChangedDuringAnalysis')
        with output.open('x', encoding='utf-8', newline='\n') as stream:
            stream.write(json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2)+'\n')
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--project-root', type=Path, default=ROOT)
    args = parser.parse_args(argv)
    try: report = analyze(args.run, args.output, project_root=args.project_root)
    except (ValueError, OSError) as error:
        print(json.dumps({'status': 'error', 'error_type': type(error).__name__})); return 1
    print(json.dumps({key: report.get(key) for key in ('status', 'counts', 'costs',
        'run_files_unchanged', 'error_type', 'verification_failure')}, ensure_ascii=False, indent=2))
    return 0 if report['status'] in ('verified', 'verified_partial') else 1


if __name__ == '__main__': raise SystemExit(main())
