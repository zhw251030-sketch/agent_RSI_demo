#!/usr/bin/env python3
"""Independently audit saved policy-selection and repair records without execution.

Requests are saved SDK pre-transport envelopes, not separately captured provider
HTTP messages. Only repair_policy and experience_memory are removed for each
three-condition comparison. Files prove value consistency; final records do not
independently timestamp a prediction registration or a process boundary.
"""
import argparse
import ast
from collections import Counter
import copy
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True

from scripts.analyze_paired_repair import (canonical, classify_response, digest,
    inside, parse_json, read_json, record_score, require, tree_hashes, verify_audit)
from rsi_eval.evidence_ids import EvidenceRegistry
from rsi_eval.revision_policy import S0, catalog, load_frozen_policy, render_policy

CHANNELS = ('repair_policy', 'experience_memory')
ARMS = ('fixed', 'memory', 'updated')


def expected_order():
    result = []
    sequence = [('E-P','fixed'), ('E-S','memory'), ('E-P','updated'),
                ('E-S','fixed'), ('E-P','memory'), ('E-S','updated')]
    for repeat in (1, 2):
        for state, arm in sequence if repeat == 1 else reversed(sequence):
            pair = state.replace('-', '')+'-r'+str(repeat)
            result.append({'state_id':state, 'family':'planning' if state == 'E-P' else 'symbolic',
                'condition':arm, 'repeat':repeat, 'pair_id':pair, 'session_id':pair+'-'+arm})
    return result


def validate_layout(config, summary):
    order = expected_order()
    require(config.get('order') == order and config.get('max_iterations') == 1
            and config.get('max_generated_candidates') == 1, 'Frozen evaluation order or one-step bound changed')
    rows = summary.get('sessions')
    require(type(rows) is list and len(rows) == 12, 'Missing or extra evaluation session')
    require([{key: row.get(key) for key in spec} for row, spec in zip(rows, order)] == order,
            'Session identity, condition, or order changed')
    return order


def verify_dispatch(summary, reservations, session_ids):
    require(len(reservations) <= 13 and [r['request_id'] for r in reservations]
            == ['request-'+str(i).zfill(4) for i in range(1,len(reservations)+1)],
            'Ledger request identities are not unique and sequential')
    requested = [row['session_id'] for row in reservations]
    require(requested == session_ids[:len(requested)], 'Actual dispatch order differs from frozen protocol')
    if summary['status'] == 'attempts_completed':
        require(requested == session_ids, 'Completed run is missing an assigned request')


def verify_budget_state(summary, ledger):
    rows = ledger['requests']; reported = summary['budget']
    require(type(ledger.get('halted')) is bool and type(ledger.get('halt_reasons')) is list,
            'Ledger halt state is malformed')
    require(all(row.get('status') in ('reserved','settled','failed')
                and row.get('usage_state') in ('known','unknown','invalid') for row in rows),
            'Unknown ledger settlement or usage state')
    counts = {'request_count':len(rows),
        'reserved_count':sum(row['status']=='reserved' for row in rows),
        'failed_count':sum(row['status']=='failed' for row in rows),
        'usage_unknown_count':sum(row['usage_state']!='known' for row in rows)}
    for key,value in counts.items():
        require(type(reported.get(key)) is int and reported[key] == value,
                'Reported '+key+' differs from actual ledger settlement state')
    sessions = {name:sum(row['session_id']==name for row in rows)
                for name in ledger['config']['session_ids']}
    require(reported.get('session_counts') == sessions and reported.get('config') == ledger['config'],
            'Reported budget session scope differs from the ledger')
    require(reported.get('halted') is ledger['halted']
            and reported.get('halt_reasons') == ledger['halt_reasons'],
            'Reported halt state differs from the ledger')
    require(ledger.get('recovery') is None and reported.get('recovery') is None,
            'Recovery is prohibited in this frozen one-request protocol')
    if summary['status'] == 'attempts_completed':
        require(counts['reserved_count'] == 0 and counts['usage_unknown_count'] == 0
                and ledger['halted'] is False and ledger['halt_reasons'] == [],
                'Completed run contains unsettled, unknown-usage, or halted requests')
    return {**counts, 'halted':ledger['halted'], 'halt_reasons':ledger['halt_reasons'],
            'recovery':None}


def request_packet(request):
    messages = request.get('messages')
    require(type(messages) is list and len(messages) == 2
            and [row.get('role') for row in messages] == ['system', 'user']
            and type(messages[1].get('content')) is str,
            'Expected fixed system message and one replacement JSON packet')
    packet = parse_json(messages[1]['content'])
    require(type(packet) is dict, 'Request packet must be an object')
    return packet


def request_common(request):
    value = copy.deepcopy(request)
    packet = request_packet(value)
    for field in CHANNELS:
        packet.pop(field, None)
    value['messages'][1]['content'] = canonical(packet).decode('utf-8')
    return value


def verify_channels(packet, arm, selected, bundle, expected_task_text=None):
    require(arm in ARMS, 'Unknown policy comparison condition')
    policy = selected if arm == 'updated' else S0
    require(packet.get('repair_policy') == render_policy(policy),
            'Actual repair policy differs from exact host renderer or includes free model text')
    require(packet.get('experience_memory') == (bundle['cases'] if arm == 'memory' else []),
            'Actual memory differs from the exact authorized update cards')
    require(packet.get('available_revision_rules') == catalog(), 'Shared rule catalog changed')
    if expected_task_text is not None:
        require(packet.get('task_text') == expected_task_text, 'Frozen actor task text changed')


def verify_request_groups(requests, order):
    allowed = {row['session_id'] for row in order}
    require(set(requests) <= allowed, 'Unknown session in actual request groups')
    result = {}
    for pair in sorted({row['pair_id'] for row in order}):
        group = [row for row in order if row['pair_id'] == pair]
        require(len(group) == 3 and {row['condition'] for row in group} == set(ARMS),
                'A comparison group does not contain three distinct conditions')
        present = [row for row in group if row['session_id'] in requests]
        common = [canonical(request_common(requests[row['session_id']])) for row in present]
        require(len(set(common)) <= 1, 'Actual common requests differ beyond the two allowed channels')
        result[pair] = {'sessions':[row['session_id'] for row in group],
            'requested_sessions':[row['session_id'] for row in present],
            'all_three_requested':len(present) == 3,
            'exact_common_request_equality':len(present) == 3,
            'common_request_sha256':digest(common[0]) if common else None,
            'common_request_bytes':len(common[0]) if common else None,
            'removed_packet_fields':list(CHANNELS)}
    return result


def compute_endpoint(records, family):
    require(type(records) is list and 1 <= len(records) <= 2, 'Expected one copied baseline and at most one child')
    baseline = record_score(records[0], family)
    require(baseline is not None, 'Copied baseline score is incomplete')
    children = records[1:]
    child_score = record_score(children[0], family) if children else None
    improvement = ((child_score-baseline if family == 'planning' else baseline-child_score)
                   if child_score is not None else None)
    return {'baseline_score':baseline, 'child_score':child_score, 'improvement':improvement,
        'submitted_and_improved':improvement is not None and improvement > 1e-12,
        'generated_candidate_records':len(children),
        'new_task_result_records':sum(len(child.get('results', [])) for child in children),
        'archived_task_result_records':len(records[0]['results'])}


def cost_breakdown(ledger, order):
    arms = {row['session_id']:row['condition'] for row in order}
    arms['policy_update'] = 'policy_update'
    config = ledger['config']
    def price(inputs, outputs):
        return float((Decimal(inputs)*Decimal(str(config['input_cny_per_million']))
                      + Decimal(outputs)*Decimal(str(config['output_cny_per_million'])))/1000000)
    groups = {key:[] for key in ('all', 'policy_update', *ARMS, 'updated_plus_update')}
    for row in ledger['requests']:
        require(row['session_id'] in arms, 'Unknown ledger session')
        require(row['input_token_reservation'] == row['input_bytes']+8192,
                'Input reservation differs from saved byte bound')
        require(row['reserved_cost_cny'] == price(row['input_token_reservation'], row['output_token_reservation']),
                'Reserved cost differs from configured prices')
        if row['usage_state'] == 'known':
            usage = row['usage']
            require(type(usage) is dict and set(usage) == {'prompt_tokens','completion_tokens','total_tokens'}
                    and all(type(x) is int and x >= 0 for x in usage.values())
                    and usage['total_tokens'] == usage['prompt_tokens']+usage['completion_tokens'],
                    'Known usage is invalid')
            require(row['actual_estimated_cost_cny'] == price(usage['prompt_tokens'], usage['completion_tokens']),
                    'Known request cost differs from configured prices')
        key = arms[row['session_id']]
        groups['all'].append(row); groups[key].append(row)
        if key in ('policy_update','updated'):
            groups['updated_plus_update'].append(row)
    result = {}
    for key, rows in groups.items():
        known = [row['usage'] for row in rows if row['usage_state'] == 'known']
        inputs = sum(x['prompt_tokens'] for x in known); outputs = sum(x['completion_tokens'] for x in known)
        unknown = len(rows)-len(known)
        reserved_in = sum(row['input_token_reservation'] for row in rows)
        reserved_out = sum(row['output_token_reservation'] for row in rows)
        result[key] = {'requests':len(rows), 'known_prompt_tokens':inputs,
            'known_completion_tokens':outputs, 'known_total_tokens':inputs+outputs,
            'known_estimated_cost_cny':price(inputs, outputs), 'unknown_usage_requests':unknown,
            'actual_total_tokens':None if unknown else inputs+outputs,
            'actual_estimated_cost_cny':None if unknown else price(inputs, outputs),
            'reserved_tokens':reserved_in+reserved_out, 'reserved_cost_cny':price(reserved_in,reserved_out),
            'input_bytes':sum(row['input_bytes'] for row in rows),
            'cost_basis':'configured_uncached_prices_estimate_not_provider_invoice'}
    return result


def verify_sources(summary, project_root):
    commit = summary.get('code_commit'); sources = summary.get('source_sha256')
    require(type(commit) is str and re.fullmatch(r'[0-9a-f]{40}', commit) is not None,
            'Runtime commit is not a full Git identity')
    require(type(sources) is dict and sources, 'Runtime source manifest is missing')
    paths = sorted(sources)
    for relative in paths:
        path = Path(relative)
        require(type(relative) is str and not path.is_absolute() and '..' not in path.parts
                and not any(c in relative for c in '\n\r:\\')
                and relative.split('/')[0] in ('rsi_eval','scripts','configs','prompts','fixtures','docs'),
                'Invalid runtime source path')
    tracked = subprocess.run(['git','ls-tree','-r','--name-only','-z',commit],
        capture_output=True,check=True,cwd=project_root).stdout.decode('utf-8').split('\0')
    expected = {name for name in tracked if name and ((name.split('/')[0]
        in ('rsi_eval','scripts','configs','prompts','fixtures') and Path(name).suffix in ('.py','.json','.md'))
        or name == 'docs/protocols/2026-10-20-policy-transfer-v0.1.md')}
    require(set(paths) == expected, 'Runtime source manifest omits or adds frozen source files')
    queries = ''.join(commit+':'+relative+'\n' for relative in paths).encode('utf-8')
    response = subprocess.run(['git','cat-file','--batch'], input=queries, capture_output=True,
                              check=True, cwd=project_root).stdout
    offset = 0; blobs = {}
    for relative in paths:
        end = response.index(b'\n', offset); header = response[offset:end].split()
        require(len(header) == 3 and header[1] == b'blob', 'Runtime source is missing from frozen Git commit')
        size = int(header[2]); start = end+1; blob = response[start:start+size]
        require(len(blob) == size and response[start+size:start+size+1] == b'\n', 'Invalid Git blob response')
        require(digest(blob) == sources[relative], 'Frozen runtime source digest mismatch')
        blobs[relative] = blob; offset = start+size+1
    require(offset == len(response), 'Unexpected trailing Git source response')
    return blobs


def _literal_assignment(source, name):
    # Parsing literal constants never imports or executes the SDK source.
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            value = ast.literal_eval(node.value)
            require(type(value) is str, 'Expected frozen literal system prompt')
            return value
    raise ValueError('Frozen system prompt literal missing')


def _system_text(request):
    value = request['messages'][0]['content']
    if type(value) is str:
        return value
    require(type(value) is list and len(value) == 1 and value[0].get('type') == 'text'
            and set(value[0]) == {'type','text'}, 'Unexpected system message structure')
    return value[0]['text']


def _actor_task_text(base_prompt, policy_text):
    require('## Fixed revision procedure' in base_prompt, 'Base task/policy boundary missing')
    value = base_prompt.split('## Fixed revision procedure')[0]
    value = value.replace('Semantic failure feedback currently says that a precondition or final goal is unsatisfied; '
        'it does not provide a complete state trace or exact missing precondition.',
        'Feedback may include bounded diagnostic observations according to the assigned condition.')
    return value+'\n## Revision policy\n\n'+policy_text+(
        '\n\nDiagnostic observations use stable evidence IDs within each candidate/task. '
        'Plan replay is host-derived; Python tracing is candidate-process debugging evidence '
        'and can be incomplete or interfered with. Missing line hits do not prove nonexecution. '
        'Residuals are prediction minus target; marginal bins describe association, not causes. '
        'Do not treat any of these as automatic proof of a causal explanation.')


def _request_record(directory, reservation, budget_config, expected_system):
    files = sorted((directory/'requests').glob('*.request.json'))
    require(len(files) == 1 and files[0].name == reservation['request_id']+'.request.json',
            'One-request ledger and saved request files disagree')
    request = read_json(files[0]); packet = request_packet(request)
    require(_system_text(request) == expected_system, 'Actual system prompt differs from frozen source')
    require(packet == read_json(directory/'requests/packet-0001.json'), 'Saved state packet differs from actual request')
    audit = read_json(directory/'requests/input-audit-0001.json'); encoded = canonical(request)
    require(digest(encoded) == reservation['payload_sha256'] == audit['payload_sha256']
            and len(encoded) == reservation['input_bytes'] == audit['actual_input_bytes'],
            'Request, ledger, and input audit disagree on exact payload')
    require(audit['request_id'] == reservation['request_id'] and audit['request_reserved']
            and audit['network_dispatch_attempted'] and audit['transport_called'],
            'Saved request has no matching transport dispatch')
    require(len(encoded) <= budget_config['max_input_bytes']
            and request['max_output_tokens'] == reservation['output_token_reservation']
            and request['max_output_tokens'] <= budget_config['max_output_tokens'], 'Request exceeds frozen budget')
    response_path = directory/'requests'/(reservation['request_id']+'.response.json')
    response = read_json(response_path)
    error = response.get('error_type')
    require(error is None or (type(error) is str and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,127}',error)),
            'Saved response error type is malformed')
    require(reservation.get('status') == ('failed' if error is not None else 'settled')
            and reservation.get('error_type') == error,
            'Ledger settlement status or error differs from the saved response')
    if reservation['usage_state'] == 'known':
        require(response.get('usage') == reservation['usage'], 'Saved response usage differs from ledger')
        require(digest(canonical(reservation['usage'])) == reservation.get('usage_sha256'),
                'Ledger usage digest differs from exact known usage')
    return request, packet, response, {'request_id':reservation['request_id'],
        'input_bytes':len(encoded), 'payload_sha256':digest(encoded),
        'response_sha256':digest(response_path.read_bytes()), 'usage_state':reservation['usage_state'],
        'usage':reservation['usage'], 'settlement_status':reservation['status'],
        'transport_error_type':error, 'response_tool_validation':audit.get('response_tool_validation')}


def _policy_call(response):
    choices = response.get('choices', [])
    require(len(choices) == 1, 'Policy response missing its single choice')
    calls = choices[0]['message'].get('tool_calls') or []
    require(len(calls) == 1 and calls[0]['function']['name'] == 'submit_policy',
            'Frozen policy has no literal saved submit_policy call')
    arguments = parse_json(calls[0]['function']['arguments'])
    require(type(arguments) is dict, 'Policy arguments must be an object; SDK replay required')
    return arguments


def _verify_policy_stage(run, summary, bundle, blobs, ledger):
    require(read_json(run/'policy-S0.json') == S0, 'Persisted S0 differs from frozen parent policy')
    selected = load_frozen_policy(run/'policy_update', bundle, S0)
    freeze_path = run/'policy_update/freeze.json'; frozen = read_json(freeze_path)
    marker = read_json(run/'evaluation-started.json')
    require(marker == {'mode':'evaluate', 'freeze_sha256':digest(freeze_path.read_bytes())},
            'Evaluation phase marker differs from frozen policy file')
    require(summary.get('freeze_file_sha256') == digest(freeze_path.read_bytes()),
            'External summary freeze digest differs from the frozen policy file')
    require(summary.get('selected_policy') == selected and summary.get('freeze') == frozen
            and summary.get('strategy_changed') == (selected != S0), 'Summary policy differs from frozen selection')
    require(ledger['requests'] and ledger['requests'][0]['session_id'] == 'policy_update'
            and ledger['requests'][0]['request_id'] == frozen['request_id']
            and ledger['requests'][0]['usage_state'] == 'known'
            and ledger['requests'][0]['status'] == 'settled',
            'Policy was not tied to the first known settled request')
    system = _literal_assignment(blobs['rsi_eval/pilot_agent.py'], 'POLICY_UPDATE_SYSTEM_PROMPT')
    request, packet, response, detail = _request_record(run/'policy_update', ledger['requests'][0],ledger['config'],system)
    require(request['model'] == summary['effective_model_config']['model'], 'Updater request model changed')
    expected = {'version':'policy-update-state-v0.1',
        'task_text':blobs['prompts/policy-transfer/update.md'].decode('utf-8'),
        'catalog':catalog(), 'parent_policy':render_policy(S0), 'experience_cases':bundle['cases']}
    require(packet == expected and read_json(run/'policy_update/task-packet.json') == expected,
            'Update request contains unexpected content or differs from the exact update-only bundle')
    tools = {tool['function']['name'] for tool in request['tools']}
    require(tools == {'submit_policy','finish'}, 'Updater was offered an unauthorized task tool')
    arguments = _policy_call(response)
    submission = read_json(run/'policy_update/policy-submission.json')
    require([arguments.get('rule_'+str(i)) for i in range(1,5)] == selected['rule_ids'],
            'Frozen rules differ from literal model selection')
    require([{'rule_id':arguments.get('rule_'+str(i)), 'support':arguments.get('support_'+str(i))}
             for i in range(1,5)] == submission['rule_support']
            and arguments.get('rationale') == submission['rationale'],
            'Host policy submission differs from literal saved model response')
    events = [parse_json(line) for line in (run/'policy_update/events.jsonl').read_text().splitlines() if line]
    require(sum(e['type']=='ActionEvent' and e.get('tool_name')=='submit_policy' for e in events) == 1
            and sum(e['type']=='ObservationEvent' and e.get('tool_name')=='submit_policy' for e in events) == 1,
            'Accepted policy has no matching action/observation events')
    require(not list((run/'policy_update').glob('candidates/*.py')), 'Updater unexpectedly contains candidate execution artifacts')
    detail.update(parent_policy=S0, selected_policy=selected, no_op=selected == S0,
        policy_changed=selected != S0, freeze_file_sha256=digest(freeze_path.read_bytes()),
        added_rules=[x for x in selected['rule_ids'] if x not in S0['rule_ids']],
        removed_rules=[x for x in S0['rule_ids'] if x not in selected['rule_ids']],
        host_rationale_rendered=False, rule_support=submission['rule_support'])
    return selected, detail


def analyze(run, output, *, project_root=ROOT):
    run, output, project_root = Path(run).resolve(), Path(output).resolve(), Path(project_root).resolve()
    require(not output.exists() and output.parent.is_dir() and not output.is_relative_to(run),
            'Audit output must be a new file outside the immutable run')
    before = tree_hashes(run)
    report = {'version':'policy-transfer-analysis-v0.1', 'status':'error', 'new_model_calls':0,
        'new_candidate_executions':0, 'sessions':[],
        'request_comparison_scope':'Saved SDK pre-transport envelopes; raw provider HTTP messages were not separately captured.',
        'registration_timing_independently_proven':False,
        'scope':'Two reused development repair states with two attempts per condition; no held-out, independent-task, or significance claim.'}
    try:
        summary, config, ledger = (read_json(run/name) for name in ('summary.json','config.json','budget-ledger.json'))
        order = validate_layout(config, summary); blobs = verify_sources(summary, project_root)
        report.update(run_id=summary['run_id'],runtime_commit=summary['code_commit'],reported_run_status=summary['status'],
                      source_provenance_files_verified=len(blobs),stop_reason=summary.get('stop_reason'))
        for relative in ('rsi_eval/revision_policy.py','rsi_eval/evidence_ids.py',
                         'rsi_eval/evidence_checks.py','rsi_eval/policy_cases.py'):
            require(relative in blobs and (project_root/relative).read_bytes() == blobs[relative],
                    'Audit helper differs from the frozen runtime implementation')
        require(digest(blobs['configs/pilots/policy-transfer-v0.1.json']) == summary['config_sha256']
                and parse_json(blobs['configs/pilots/policy-transfer-v0.1.json']) == config,
                'Run configuration differs from frozen source and recorded digest')
        base = read_json(run/'base-config.json')
        require(parse_json(blobs[config['base_config']]) == base, 'Base configuration differs from frozen source')
        require(digest(blobs[base['model_configuration']]) == summary['model_config_sha256'],
                'Model configuration digest differs from frozen source')
        public_model = parse_json(blobs[base['model_configuration']])
        effective_model = dict(public_model, max_output_tokens=config['budgets']['max_output_tokens'],
            num_retries=0, stream=False, caching_prompt=False, api_mode='chat',
            fallback_strategy=None, log_completions=False)
        require(summary['model_config'] == public_model and summary['effective_model_config'] == effective_model,
                'Recorded effective model settings differ from the frozen model configuration')
        require(summary.get('mode') == 'evaluate' and summary.get('sealed_test_evaluations') == 0
                and summary.get('baseline_reexecutions') == 0 and summary.get('automatic_recovery_enabled') is False,
                'Run mode or protected execution boundary changed')
        from rsi_eval.policy_cases import load_evaluation_states, load_update_bundle
        bundle = read_json(run/'update-bundle.json')
        require(bundle == load_update_bundle(project_root), 'Persisted update bundle differs from pinned archived observations')
        states = {state['state_id']:state for state in load_evaluation_states(project_root)}
        session_ids = ['policy_update']+[row['session_id'] for row in order]
        require(ledger['config'] == {**config['budgets'],'session_ids':session_ids}, 'Ledger budget or session scope changed')
        reservations = ledger['requests']
        verify_dispatch(summary, reservations, session_ids)
        report['settlement_state'] = verify_budget_state(summary, ledger)
        by_session = {}
        for row in reservations:
            require(row['session_id'] in session_ids and row['session_id'] not in by_session,
                    'Unknown or repeated one-request session in ledger')
            by_session[row['session_id']] = row
        selected, report['policy_update'] = _verify_policy_stage(run, summary, bundle, blobs, ledger)
        requests = {}; claims = Counter(); predictions = Counter(); registrations = Counter()
        base_sessions = {s['family']:s for s in base['sessions']}
        actor_system = _literal_assignment(blobs['rsi_eval/pilot_agent.py'],'SINGLE_REVISION_SYSTEM_PROMPT')
        actor_policy = blobs[config['policy_file']].decode('utf-8')
        for spec, reported in zip(order, summary['sessions']):
            name, family = spec['session_id'], spec['family']; directory = run/name
            require(directory.is_dir(), 'An assigned evaluation session directory is missing')
            records = read_json(directory/'candidates.json'); endpoint = compute_endpoint(records,family)
            state = states[spec['state_id']]; baseline = records[0]
            require(baseline['candidate_id'] == family+'-000' and baseline['parent_id'] is None
                    and baseline['origin'] == 'archived_model_proposed_initial'
                    and baseline['source_sha256'] == state['record']['source_sha256']
                    and baseline['n_params'] == state['n_params']
                    and baseline['metrics'] == state['record']['metrics']
                    and baseline['results'] == state['record']['results'], 'Copied baseline differs from its pinned evaluation state')
            provenance = read_json(directory/'repair-state-provenance.json')
            require(provenance == state['provenance'], 'Copied baseline provenance changed')
            for record in records:
                source = inside(directory,'candidates/'+record['candidate_id']+'.py').read_bytes()
                require(digest(source) == record['source_sha256'], 'Candidate source hash mismatch')
                require(all(result.get('candidate_hash',record['source_sha256']) == record['source_sha256']
                            for result in record.get('results',[])), 'Task execution is bound to another source')
            children = records[1:]; entry = {**spec,**endpoint,'request_count':0,'audits':[],
                'baseline_source_sha256':baseline['source_sha256'], 'sdk_status':reported.get('status'),
                'sdk_conversation_status':reported.get('conversation_status'), 'step_status':reported.get('step_status')}
            evidence = read_json(directory/'evidence.json')
            for record in records:
                snapshots = evidence.get(record['candidate_id'],[])
                require(bool(snapshots), 'Candidate evidence is missing')
                for snapshot in snapshots:
                    binding=snapshot['binding']
                    require(binding['session_id'] == summary['run_id']+':'+spec['pair_id']
                            and binding['candidate_id'] == record['candidate_id']
                            and binding['candidate_sha256'] == record['source_sha256'], 'Evidence identity or shared namespace changed')
                if record_score(record,family) is not None:
                    primary=[s for s in snapshots if s['binding']['task_id'] == ('planning_batch' if family=='planning' else 'oscillator1')]
                    require(len(primary)==1 and all(primary[0]['scalars'].get(k)==v for k,v in record['metrics'].items()),
                            'Evidence score differs from task outcomes')
            arguments = None
            if name in by_session:
                request, packet, response, detail = _request_record(directory,by_session[name],ledger['config'],actor_system)
                require(request['model'] == summary['effective_model_config']['model'], 'Request model changed')
                require({t['function']['name'] for t in request['tools']} == {'finish','submit_candidate'}, 'Unexpected evaluation tool')
                task_text = _actor_task_text(blobs[base_sessions[family]['prompt_file']].decode('utf-8'), actor_policy)
                verify_channels(packet,spec['condition'],selected,bundle,task_text)
                require(packet['session_id'] == summary['run_id']+':'+spec['pair_id']
                        and packet['checks_visible'] is False and packet['frozen_history_common'] == {}
                        and packet['declared_hypotheses'] == [] and 'audits' not in packet,
                        'Evaluation input contains unauthorized history or different check visibility')
                require(packet['metadata']['records_sha256'] == digest(canonical([baseline])), 'Initial packet record hash differs from copied baseline')
                require(packet['incumbent'] == {'candidate_id':family+'-000', 'source_sha256':baseline['source_sha256'],
                    'n_params':baseline['n_params'], 'source':state['source']}, 'Actual request starting source differs from pinned evaluation state')
                registry = EvidenceRegistry(evidence[family+'-000'],session_id=packet['session_id'])
                require(packet['evidence'] == registry.entries()
                        and packet['metadata']['evidence_sha256'] == digest(canonical(registry.entries())), 'Actual evidence catalog differs from bound parent evidence')
                require((directory/'task-prompt.txt').read_bytes() == canonical(packet), 'Prepared prompt differs from actual first request')
                kind, arguments = classify_response(response)
                entry.update(detail,request_count=1,response_kind=kind)
                requests[name] = request
                if children:
                    require(type(arguments) is dict and type(arguments.get('source')) is str
                            and digest(arguments['source'].encode('utf-8')) == children[0]['source_sha256']
                            and arguments.get('n_params') == children[0]['n_params'], 'Executed child differs from literal model response; SDK replay required')
            else:
                require(not children and not list((directory/'requests').glob('*.request.json')),
                        'Candidate or request exists without ledger reservation')
                entry['response_kind']='not_requested'
            audits=read_json(directory/'audits.json') if (directory/'audits.json').exists() else []
            require(len(audits)==len(children), 'Each executed candidate must have exactly one prior registration record')
            for audit in audits:
                checked=verify_audit(directory,audit,evidence,arguments);entry['audits'].append(checked)
                claims[checked['claim_result']['status']]+=1;registrations[checked['registration']['status']]+=1
                predictions[checked['prediction_result']['status']]+=1
            if children:
                events=[parse_json(line) for line in (directory/'events.jsonl').read_text().splitlines() if line]
                require(sum(e['type']=='ActionEvent' and e.get('tool_name')=='submit_candidate' for e in events)==1
                        and sum(e['type']=='ObservationEvent' and e.get('tool_name')=='submit_candidate' for e in events)==1,
                        'Executed child has no unique candidate action and observation')
            reported_endpoint=reported.get('endpoint')
            if reported_endpoint is not None:
                require(reported_endpoint['generated_candidates_executed']==endpoint['generated_candidate_records']
                        and reported_endpoint['actual_task_executions']==endpoint['new_task_result_records']
                        and reported_endpoint['archived_task_records']==endpoint['archived_task_result_records']
                        and reported_endpoint['improvement']==endpoint['improvement']
                        and reported_endpoint['submitted_and_improved']==endpoint['submitted_and_improved'],
                        'Reported endpoint differs from independent recomputation')
            report['sessions'].append(entry)
        report['actual_request_triplets']=verify_request_groups(requests,order)
        for pair, proof in report['actual_request_triplets'].items():
            names=proof['requested_sessions']
            if names:
                packet=request_packet(requests[names[0]])
                for field in CHANNELS:packet.pop(field,None)
                expected=summary['triplet_input_proofs'][pair]
                require(expected['common_sha256']==digest(canonical(packet)) and expected['common_bytes']==len(canonical(packet)),
                        'Prepared group proof differs from actual request common packet')
        report['cost_by_stage_and_condition']=cost_breakdown(ledger,order)
        all_cost=report['cost_by_stage_and_condition']['all']; reported_budget=summary['budget']
        for key in ('known_prompt_tokens','known_completion_tokens','known_total_tokens','known_estimated_cost_cny','reserved_tokens','reserved_cost_cny'):
            require(reported_budget[key]==all_cost[key], 'Reported total budget differs from request-level recomputation')
        require(reported_budget['request_count']==len(reservations)
                and reported_budget['usage_unknown_count']==all_cost['unknown_usage_requests'], 'Reported request or unknown-usage count differs')
        require(reported_budget['actual_tokens'] == all_cost['actual_total_tokens']
                and reported_budget['actual_estimated_cost_cny'] == all_cost['actual_estimated_cost_cny'],
                'Reported actual usage totals differ from request-level known/unknown state')
        report['counts']={'requests':len(reservations),'update_requests':1,'evaluation_requests':len(requests),
            'generated_candidate_records':sum(row['generated_candidate_records'] for row in report['sessions']),
            'new_task_result_records':sum(row['new_task_result_records'] for row in report['sessions']),
            'archived_task_result_records':sum(row['archived_task_result_records'] for row in report['sessions']),
            'claim_statuses':dict(claims),'registration_statuses':dict(registrations),'prediction_statuses':dict(predictions)}
        report['condition_endpoints']={arm:{'assigned_sessions':4,
            'generated_candidates':sum(row['generated_candidate_records'] for row in report['sessions'] if row['condition']==arm),
            'submitted_and_improved':sum(row['submitted_and_improved'] for row in report['sessions'] if row['condition']==arm)} for arm in ARMS}
        report['status']='verified'
    except Exception as error:
        report['error_type']=type(error).__name__
        if type(error) is ValueError:report['verification_failure']=str(error)
    finally:
        after=tree_hashes(run)
        report.update(run_file_count=len(before),run_files_unchanged=before==after,
            run_tree_before_sha256=digest(canonical(before)),run_tree_after_sha256=digest(canonical(after)),
            input_file_sha256=before,analysis_script_sha256=digest(Path(__file__).read_bytes()))
        if before!=after:report.update(status='error',error_type='RunChangedDuringAnalysis')
        output.write_text(json.dumps(report,ensure_ascii=False,allow_nan=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    return report


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args(argv)
    try:result=analyze(args.run,args.output)
    except (ValueError,OSError) as error:
        print(json.dumps({'status':'error','error_type':type(error).__name__}));return 1
    print(json.dumps({key:result.get(key) for key in ('status','counts','cost_by_stage_and_condition',
        'run_files_unchanged','error_type','verification_failure')},ensure_ascii=False,indent=2))
    return 0 if result['status']=='verified' else 1


if __name__=='__main__':raise SystemExit(main())
