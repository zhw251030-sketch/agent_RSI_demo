#!/usr/bin/env python3
"""Audit frozen drafts and matched final reviews without running any candidate.

This verifies saved request/SDK/core/source/evaluation consistency, not provider
authenticity or historical execution. Strict JSON and the documented SDK
metadata/null/default normalization are supported; other argument repairs fail
closed. Candidate programs are only read or parsed by the static checker.
"""
import argparse
from collections import Counter
import copy
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from rsi_eval.two_stage_audit import (
    _canonical as canonical, _json, _read as read, _usage,
    _require as require, audit_budget,
)

EDIT_CLAIMS = {'keep_bytes', 'keep_ast', 'apply_format_patch',
               'remove_selected_term', 'general_edit'}
DEPLOYMENT_CLAIMS = {'raw_validation', 'probe_repair_deployed', 'unspecified'}
BUSINESS_FIELDS = {'source', 'n_params', 'rationale', 'auxiliary',
                   'edit_claim', 'deployment_claim'}
COUNTS = ('sandbox_calls', 'new_candidate_executions', 'host_validations',
          'val_calls', 'fit_calls', 'predict_calls')


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def _finite_json(value, depth=0):
    if depth > 20:
        raise ValueError('Submission JSON nesting exceeds 20')
    kind = type(value)
    if value is None or kind in (str, bool, int):
        return
    if kind is float and math.isfinite(value):
        return
    if kind is list:
        for item in value: _finite_json(item, depth+1)
        return
    if kind is dict and all(type(k) is str for k in value):
        for item in value.values(): _finite_json(item, depth+1)
        return
    raise ValueError('Submission must contain finite JSON values')


def _normalized_business(raw):
    require(type(raw) is dict, 'Unsupported SDK argument JSON repair')
    business = {k: copy.deepcopy(v) for k, v in raw.items()
                if k not in ('summary', 'security_risk') and v is not None}
    business.setdefault('rationale', '')
    business.setdefault('auxiliary', {})
    return business


def _valid_business(value):
    try:
        if type(value) is not dict or set(value) != BUSINESS_FIELDS:
            return False
        _finite_json(value)
        return (len(canonical(value)) <= 65536
            and type(value['source']) is str and bool(value['source'].strip())
            and len(value['source'].encode('utf-8')) <= 16384
            and type(value['n_params']) is int and 0 <= value['n_params'] <= 16
            and type(value['rationale']) is str and len(value['rationale']) <= 4000
            and type(value['auxiliary']) is dict
            and type(value['edit_claim']) is str and value['edit_claim'] in EDIT_CLAIMS
            and type(value['deployment_claim']) is str
            and value['deployment_claim'] in DEPLOYMENT_CLAIMS)
    except (ValueError, TypeError, UnicodeError, OverflowError, RecursionError):
        return False


def audit_request(directory, request_row, *, stage, session_id, artifact=None):
    """Bind a known response's six fields to SDK dispatch and source bytes."""
    require(stage in ('draft', 'review'), 'Unknown commitment audit stage')
    directory = Path(directory)
    require(not directory.is_symlink() and not (directory/'requests').is_symlink(),
            'Symlinked session')
    row = request_row; rid = row.get('request_id')
    require(type(rid) is str and re.fullmatch(r'request-\d{4}', rid), 'Request identifier')
    require(row.get('session_id') == session_id, 'Request/session binding')
    usage = _usage(row)
    payload = read(directory/'requests'/f'{rid}.request.json')
    encoded = canonical(payload)
    require(type(row.get('input_bytes')) is int and len(encoded) == row['input_bytes']
            and digest(encoded) == row.get('payload_sha256'), 'Actual request bytes/digest')
    require(type(payload.get('max_output_tokens')) is int
            and payload['max_output_tokens'] == row['output_token_reservation'], 'Actual output cap')
    response = read(directory/'requests'/f'{rid}.response.json')
    require(canonical(response.get('usage')) == canonical(usage), 'Received usage differs from ledger')
    require(row.get('status') == ('failed' if row.get('error_type') is not None else 'settled'),
            'Ledger status/error mismatch')
    require(response.get('error_type') == row.get('error_type'), 'Received error differs from ledger')
    tool = 'submit_draft' if stage == 'draft' else 'submit_candidate'
    choices = response.get('choices'); calls = None; shape = False
    if type(choices) is list and len(choices) == 1 and type(choices[0]) is dict:
        message = choices[0].get('message')
        if type(message) is dict:
            shape = True; calls = message.get('tool_calls')
    allowed = shape and (not calls or type(calls) is list and len(calls) == 1
        and type(calls[0]) is dict and type(calls[0].get('function')) is dict
        and calls[0]['function'].get('name') in (tool, 'finish'))
    if row.get('error_type') == 'PilotResponseContractError':
        require(not allowed, 'Contract error needs offending choices/tools')
    elif row.get('error_type') is not None:
        raise ValueError('Completed audit does not accept other failed transports')
    else:
        require(allowed, 'Unauthorized response choices/tools')
    called_tool = calls[0]['function'].get('name') if allowed and calls else None
    business = None
    if row.get('error_type') is None and called_tool == tool:
        args = calls[0]['function'].get('arguments')
        require(type(args) is str, 'Unsupported nonstring SDK arguments')
        try:
            business = _normalized_business(_json(args))
        except (ValueError, TypeError, UnicodeError, OverflowError, RecursionError) as error:
            raise ValueError('Unsupported raw JSON normalization; audit SDK separately') from error
    valid = business is not None and _valid_business(business)
    source_name = 'draft.py' if stage == 'draft' else 'candidate.py'
    saved_path = directory/'sdk-submission.json'
    if saved_path.exists():
        require(valid, 'SDK dispatch has no matching valid six-field call')
        expected = dict(stage=stage, tool=tool, session_id=session_id, business=business)
        require(canonical(read(saved_path)) == canonical(expected), 'SDK normalized submission mismatch')
        require(row['status'] == 'settled', 'SDK dispatch after failed transport')
        if artifact is None:
            attempts = read(directory/'attempts.json')
            require(type(attempts) is list and len(attempts) == 1
                and attempts[0].get('session_id') == session_id
                and attempts[0].get('status') == 'invalid_request',
                'Missing result requires core rejection')
            require(not (directory/source_name).exists(), 'Missing result has source artifact')
        else:
            require(artifact.get('status') == ('accepted' if stage == 'draft' else 'evaluated'),
                    'Artifact acceptance status')
            require(artifact.get('source_file') == source_name, 'Artifact source file')
            source_path = directory/source_name
            require(not source_path.is_symlink(), 'Symlinked source artifact')
            raw_source = source_path.read_bytes()
            require(raw_source == business['source'].encode('utf-8'), 'Source is not SDK-submitted bytes')
            require(digest(raw_source) == artifact.get('source_sha256'), 'Artifact source digest')
            for key in BUSINESS_FIELDS - {'source'}:
                require(canonical(artifact.get(key)) == canonical(business[key]),
                        'Artifact/business field: '+key)
            if stage == 'draft' or 'source' in artifact:
                require(artifact.get('source') == business['source'], 'Artifact source text')
    else:
        require(artifact is None and not (directory/source_name).exists(), 'Artifact without SDK dispatch')
        require(not valid, 'Valid business call has no SDK dispatch record')
    return dict(status='passed', submitted=saved_path.exists(), tool_name=called_tool,
                request_id=rid, usage=copy.deepcopy(usage),
                normalization_scope='strict_json_metadata_top_level_null_defaults_only')


def validate_draft(case, draft, directory):
    require(type(draft) is dict and draft.get('status') == 'accepted', 'Accepted draft required')
    require(draft.get('source_file') == 'draft.py', 'Draft source path')
    raw = (Path(directory)/'draft.py').read_bytes()
    require(draft.get('source') == raw.decode('utf-8')
            and draft.get('source_sha256') == digest(raw), 'Draft source binding')
    require(draft.get('base_source_sha256') == case['source_sha256']
            and draft.get('case_id') == case['id'], 'Draft case/base binding')
    require(_valid_business({k: draft.get(k) for k in BUSINESS_FIELDS}), 'Draft business contract')
    require(not ({'results', 'evaluation_files', 'score', 'forecast', 'executions'} & set(draft)),
            'A draft cannot carry evaluation results')
    require(not (Path(directory)/'evaluations').exists(), 'A draft has an evaluation directory')
    if 'parent_id' in draft:
        require(draft['parent_id'] == case['source_sha256'], 'Draft base binding')
    return raw.decode('utf-8')


def _relative_file(root, relative):
    require(type(relative) is str and '\\' not in relative, 'Invalid relative path')
    path = PurePosixPath(relative)
    require(not path.is_absolute() and '..' not in path.parts and ':' not in relative,
            'Audit path escapes root')
    result = Path(root)
    for component in path.parts:
        result = result/component
        require(not result.is_symlink(), 'Symlink in audit path')
    require(result.resolve().is_relative_to(Path(root).resolve()), 'Audit path outside root')
    return result


def _tree_hashes(directory):
    directory = Path(directory)
    require(not directory.is_symlink(), 'Symlinked frozen directory')
    result = {}
    for path in directory.rglob('*'):
        require(not path.is_symlink(), 'Symlink in frozen tree')
        if path.is_file(): result[path.relative_to(directory).as_posix()] = digest(path.read_bytes())
    return result


def validate_phase_freezes(run, report, drafts, feedback):
    run = Path(run)
    draft_file = run/'draft-freeze.json'; feedback_file = run/'feedback-freeze.json'
    require(digest(draft_file.read_bytes()) == report.get('draft_freeze_sha256'), 'Draft phase digest')
    frozen = read(draft_file)
    require(canonical(frozen.get('drafts')) == canonical(drafts), 'Frozen draft objects differ')
    require(frozen.get('files') == _tree_hashes(run/'drafts'), 'Frozen draft files differ')
    require(digest(feedback_file.read_bytes()) == report.get('feedback_freeze_sha256'), 'Feedback phase digest')
    checked = read(feedback_file)
    require(checked.get('draft_freeze_sha256') == report['draft_freeze_sha256'], 'Feedback draft-phase link')
    require(canonical(checked.get('feedback')) == canonical(feedback), 'Frozen feedback differs')


def validate_execution(execution, summary, counts, expected_events):
    require(type(execution.get('max_sandbox_calls')) is int
            and execution['max_sandbox_calls'] == 48, 'Execution cap')
    reserved = execution.get('reserved_sandbox_calls')
    require(type(reserved) is int and 0 <= reserved <= 48, 'Execution reservation total')
    events = execution.get('events')
    require(type(events) is list and len(events) == len(expected_events), 'Execution event cardinality')
    for event, expected in zip(events, expected_events):
        require(type(event) is dict and event.get('complete') is True, 'Incomplete execution')
        require(event.get('label') == expected[0]
                and type(event.get('reserved')) is int and event['reserved'] == expected[1],
                'Execution event scope/reservation')
        actual = event.get('counts')
        require(type(actual) is dict and set(actual) == set(COUNTS)
                and all(type(v) is int and v >= 0 for v in actual.values()), 'Execution count types')
        require(canonical(actual) == canonical(expected[2]), 'Per-event execution counts')
        require(actual['sandbox_calls'] <= event['reserved'], 'Execution exceeds reservation')
    require(sum(e['reserved'] for e in events) == reserved, 'Reservation sum')
    actual = {key: sum(e['counts'][key] for e in events) for key in COUNTS}
    require(canonical(actual) == canonical(counts) == canonical(summary.get('actual')), 'Execution total')
    require(type(summary.get('reserved_sandbox_calls')) is int
            and summary['reserved_sandbox_calls'] == reserved
            and summary.get('accounting_complete') is True, 'Execution summary')


def validate_candidate(root, case, draft, candidate, directory):
    from rsi_eval.commitment_core import check_submission, review_change
    from rsi_eval.decision_core import summarize_scores
    from rsi_eval.two_stage_core import classify_edit, check_forecast
    require(type(candidate) is dict and candidate.get('status') == 'evaluated', 'Evaluated candidate required')
    raw = (directory/'candidate.py').read_bytes(); source = raw.decode('utf-8')
    sha = digest(raw)
    require(candidate.get('source_file') == 'candidate.py'
            and candidate.get('source_sha256') == sha, 'Candidate source digest/path')
    require(candidate.get('parent_id') == case['source_sha256'], 'Candidate base binding')
    results = candidate.get('results'); files = candidate.get('evaluation_files')
    require(type(results) is list and type(files) is list
            and len(results) == len(files) == len(case['task_ids']), 'Evaluation cardinality')
    require([r.get('task_id') for r in results] == case['task_ids'], 'Evaluation task scope')
    for index, (record, relative) in enumerate(zip(results, files)):
        require(relative == f'evaluations/evaluation-{index:02d}.json', 'Evaluation path')
        require(canonical(read(directory/relative)) == canonical(record), 'Evaluation record differs')
        require(record.get('candidate_hash') == sha and record.get('family') == case['family']
                and record.get('parent_id') == case['source_sha256']
                and record.get('candidate_id') == candidate['candidate_id']
                and record.get('strategy_version') == 'edit-commitment-v0.1', 'Evaluation identity')
        for field in ('sealed_tasks_executed', 'model_calls'):
            require(type(record.get(field)) is int and record[field] == 0, 'Evaluation zero scope: '+field)
    require(canonical(candidate.get('score')) == canonical(summarize_scores(case, results, candidate['n_params'])),
            'Recomputed score')
    require(canonical(candidate.get('edit')) == canonical(classify_edit(case, source, candidate['n_params'])),
            'Recomputed old edit label')
    require(canonical(candidate.get('forecast')) == canonical(check_forecast(
        case, candidate['auxiliary'].get('forecast'), candidate['score'])), 'Recomputed forecast')
    submitted = dict(candidate, source=source)
    require(canonical(candidate.get('commitment_check')) == canonical(check_submission(case, submitted, root=root)),
            'Final claim check differs')
    require(canonical(candidate.get('review_change')) == canonical(review_change(case, draft, submitted, root=root)),
            'Original/final commitment comparison differs')
    final = {key: submitted[key] for key in BUSINESS_FIELDS}
    final.update(source_sha256=sha, commitment_check=candidate['commitment_check'],
                 review_change=candidate['review_change'])
    require(canonical(read(directory/'final-commitment.json')) == canonical(final),
            'Final pre-evaluation commitment record differs')
    return source


def audit(root, run):
    """Audit a completed allocation, including known contract-missing slots."""
    from rsi_eval.decision_cases import load_cases
    from rsi_eval.commitment_core import (
        DraftController, ReviewController, check_submission, common_request,
    )
    from scripts.run_edit_commitment import (
        PROTOCOL, CASE_ORDER, draft_order, review_order, validate_config,
    )
    from scripts.run_decision_replay import verify_inputs, checked_execution_counts
    from scripts.analyze_two_stage import packet_from_request
    root = Path(root).resolve(); run = Path(run).resolve()
    config = validate_config(read(run/'config.json')); report = read(run/'summary.json')
    require(report.get('status') == 'attempts_completed', 'Only completed allocation audit supported')
    cases = {case['id']: case for case in load_cases(root)}
    require(set(cases) == set(CASE_ORDER), 'Case inventory')
    verify_inputs(run, report['inputs_freeze_sha256'])
    require(canonical(read(run/'inputs/cases.json')) == canonical(cases), 'Pinned inputs differ')
    require(read(run/'inputs-freeze.json').get('new_probe_executions') == 0, 'No new probes')
    freeze = read(run/'runtime-freeze.json'); commit = freeze.get('runtime_commit')
    require(type(commit) is str and re.fullmatch(r'[0-9a-f]{40}', commit), 'Runtime commit')
    require(freeze.get('checkout_clean') is True and report.get('runtime_commit') == commit,
            'Clean runtime anchor')
    require(freeze.get('runtime_files_sha256') == report.get('runtime_files_sha256'), 'Runtime summary')
    require(PROTOCOL in freeze['runtime_files_sha256'], 'Protocol not frozen')
    for path, sha in freeze['runtime_files_sha256'].items():
        checked_path = _relative_file(root, path)
        blob = subprocess.check_output(['git', '-C', str(root), 'show', commit+':'+path])
        require(digest(blob) == sha == digest(checked_path.read_bytes()), 'Frozen runtime file: '+path)

    expected_drafts = draft_order(); expected_reviews = review_order()
    for field, expected, keys in [('drafts', expected_drafts, ('case_id', 'session_id', 'stage')),
                                  ('reviews', expected_reviews, ('case_id', 'condition', 'session_id', 'stage'))]:
        require(type(report.get(field)) is list
                and [{k: row.get(k) for k in keys} for row in report[field]] == expected,
                'Frozen '+field+' allocation differs')
    ledger = read(run/'budget-ledger.json')
    sessions = [r['session_id'] for r in expected_drafts+expected_reviews]
    audit_budget(ledger, report['budget'], dict(config['budgets'], session_ids=sessions))
    requests = ledger['requests']
    by_session = {r['session_id']: r for r in requests}
    require(len(by_session) == len(requests), 'One request per session required')
    drafts = {}; feedback = {}; request_sessions = []; draft_results = []
    for slot in report['drafts']:
        case_id = slot['case_id']; case = cases[case_id]
        session = slot['session_id']; directory = run/'drafts'/case_id
        require(session in by_session, 'Every allocated draft needs its one request')
        req = by_session[session]; request_sessions.append(session)
        require(slot.get('request_id') == req['request_id'], 'Draft request link')
        draft = slot.get('draft')
        require(slot.get('disposition') == ('available' if draft is not None else 'missing'), 'Draft disposition')
        audit_request(directory, req, stage='draft', session_id=session, artifact=draft)
        controller = object.__new__(DraftController); controller.case = case
        packet = controller.task_packet()
        payload = read(directory/'requests'/f'{req["request_id"]}.request.json')
        require(canonical(read(directory/'task-packet.json')) == canonical(packet)
                == canonical(packet_from_request(payload)), 'Draft actual task packet')
        if draft is not None:
            require(canonical(read(directory/'draft.json')) == canonical(draft), 'Draft summary differs')
            validate_draft(case, draft, directory)
            drafts[case_id] = draft
            feedback[case_id] = check_submission(case, draft, root=root)
            draft_results.append(dict(case_id=case_id, source_sha256=draft['source_sha256'],
                                      edit_claim=feedback[case_id]['edit_claim'],
                                      deployment_claim=feedback[case_id]['deployment_claim']))
        else:
            require(not (directory/'draft.json').exists(), 'Missing draft has record')
    validate_phase_freezes(run, report, drafts, feedback)

    common = {}; counts = {key: 0 for key in COUNTS}; events = []; finals = []; missing = 0
    for slot in report['reviews']:
        case_id = slot['case_id']; case = cases[case_id]; session = slot['session_id']
        directory = run/'reviews'/session
        if case_id not in drafts:
            require(slot.get('disposition') == 'skipped_missing_draft'
                and slot.get('candidate') is None and slot.get('request_id') is None
                and session not in by_session and not directory.exists(), 'Skipped review acquired work')
            continue
        require(session in by_session, 'Eligible review needs its one request')
        req = by_session[session]; request_sessions.append(session)
        require(slot.get('request_id') == req['request_id'], 'Review request link')
        candidate = slot.get('candidate')
        require(slot.get('disposition') == ('available' if candidate is not None else 'missing'),
                'Review disposition')
        audit_request(directory, req, stage='review', session_id=session, artifact=candidate)
        controller = object.__new__(ReviewController)
        controller.case = case
        controller.draft = {key: drafts[case_id][key] for key in BUSINESS_FIELDS}
        controller.checker_feedback = feedback[case_id] if slot['condition'] == 'checked' else None
        controller.root = root
        packet = controller.task_packet()
        payload = read(directory/'requests'/f'{req["request_id"]}.request.json')
        require(canonical(read(directory/'task-packet.json')) == canonical(packet)
                == canonical(packet_from_request(payload)), 'Review actual task packet')
        shared = canonical(common_request(payload))
        common.setdefault(case_id, []).append(shared)
        if candidate is None:
            require(not (directory/'candidate.json').exists(), 'Missing candidate has record')
            missing += 1
        else:
            require(canonical(read(directory/'candidate.json')) == canonical(candidate), 'Candidate summary differs')
            validate_candidate(root, case, drafts[case_id], candidate, directory)
            for record in candidate['results']:
                actual = checked_execution_counts(record)
                current = {key: actual.get(key, 0) for key in COUNTS}
                for key in COUNTS: counts[key] += current[key]
                events.append((session+':'+record['task_id'], 1 if case['family'] == 'planning' else 2, current))
            finals.append(dict(case_id=case_id, condition=slot['condition'], session_id=session,
                source_sha256=candidate['source_sha256'], score=candidate['score'],
                commitment_check=candidate['commitment_check'], review_change=candidate['review_change']))
    require([r['session_id'] for r in requests] == request_sessions, 'All drafts precede eligible reviews')
    actual_request_files = list((run/'drafts').rglob('*.request.json')) + list((run/'reviews').rglob('*.request.json'))
    require(len(actual_request_files) == len(requests), 'Actual request file cardinality')
    require({p.name for p in (run/'drafts').iterdir()} == {r['case_id'] for r in expected_drafts},
            'Draft directory allocation')
    review_directories = {p.name for p in (run/'reviews').iterdir()} if (run/'reviews').exists() else set()
    require(review_directories == {
        r['session_id'] for r in expected_reviews if r['case_id'] in drafts}, 'Review directory allocation')
    proof = {}
    for case_id, values in common.items():
        require(len(values) == 2 and values[0] == values[1], 'Two complete review requests differ')
        proof[case_id] = digest(values[0])
    require(report.get('common_request_sha256', {}) == proof, 'Paired actual-request proofs differ')
    validate_execution(read(run/'execution-ledger.json'), report['execution_budget'], counts, events)
    for field in ('sealed_tasks_executed', 'new_probe_executions', 'draft_executions'):
        require(type(report.get(field)) is int and report[field] == 0, 'Zero scope: '+field)
    for field in ('strategy_updated', 'model_weights_updated', 'resumed'):
        require(report.get(field) is False, 'Fixed scope: '+field)
    return dict(status='passed', runtime_commit=commit, model_requests=len(requests),
        accepted_drafts=len(drafts), candidate_submissions=len(finals), missing_review_submissions=missing,
        skipped_reviews=sum(s.get('disposition') == 'skipped_missing_draft' for s in report['reviews']),
        matched_request_pairs=len(common), known_tokens=report['budget']['known_total_tokens'],
        known_estimated_cost_cny=report['budget']['known_estimated_cost_cny'],
        reserved_cost_cny=report['budget']['reserved_cost_cny'], executions=counts,
        draft_claim_counts=dict(Counter(r['edit_claim']['status'] for r in draft_results)),
        draft_deployment_counts=dict(Counter(r['deployment_claim']['status'] for r in draft_results)),
        drafts=draft_results, finals=finals,
        limitations=['record_and_source_consistency_only_not_provider_authentication',
            'no_candidate_VAL_or_probe_rerun', 'drafts_have_no_task_performance_measurement',
            'fixed_seen_base_tasks_new_frozen_drafts_not_independent_tasks',
            'one_pair_per_state_not_statistical_or_generalization_evidence',
            'narrow_claim_support_does_not_certify_rationale_or_utility',
            'no_strategy_or_weight_update'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', required=True); parser.add_argument('--output')
    args = parser.parse_args(); result = audit(ROOT, Path(args.run_dir))
    if args.output:
        output = Path(args.output).resolve()
        require(not output.is_relative_to((ROOT/'artifacts').resolve()), 'No writing into historical archives')
        encoded = (json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)+'\n').encode('utf-8')
        if output.exists(): require(output.read_bytes() == encoded, 'Refusing to replace differing audit')
        else:
            output.parent.mkdir(parents=True, exist_ok=True); output.write_bytes(encoded)
    print(json.dumps({k: v for k, v in result.items() if k not in ('drafts', 'finals')}, indent=2))


if __name__ == '__main__': main()
