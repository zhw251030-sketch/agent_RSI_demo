#!/usr/bin/env python3
"""Offline goal-rule calibration. Reads complete archives, never executes code.

The new acceptance rule is applied retrospectively; this does not estimate what
a new policy would have generated. Full old audits precede the new projection.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rsi_eval.goal_alignment import assess_planning, assess_symbolic, symbolic_opportunity

CONFIG = 'configs/analysis/goal-alignment-v0.1.json'
CONFIG_SHA256 = 'd1ad6f3f1dc10ad4d10af8e6a4759a5a980307ddbd477559f39e7f4c3af41911'
IMPLEMENTATION_FILES = (
    CONFIG, 'rsi_eval/goal_alignment.py', 'scripts/analyze_goal_alignment.py',
    'docs/protocols/2026-10-21-goal-alignment-v0.1.md',
)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'),
                      allow_nan=False).encode('utf-8')


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read_json(path):
    def pairs(values):
        result = {}
        for key, value in values:
            require(key not in result, 'Duplicate JSON key')
            result[key] = value
        return result
    def reject(value):
        raise ValueError('Nonfinite JSON constant')
    return json.loads(Path(path).read_text(encoding='utf-8'), object_pairs_hook=pairs,
                      parse_constant=reject)


def relative_file(root, value, *, is_directory=False):
    require(type(value) is str and '\\' not in value, 'Invalid relative path')
    pure = PurePosixPath(value)
    require(not pure.is_absolute() and '..' not in pure.parts and str(pure) == value
            and ':' not in value, 'Invalid relative path')
    root = Path(root).resolve()
    current = root
    for part in pure.parts:
        current = current/part
        require(not current.is_symlink(), 'Symlink in input path')
    require(current.is_dir() if is_directory else current.is_file(), 'Missing input path')
    return current


def verify_archive(root, spec):
    directory = relative_file(root, spec['path'], is_directory=True)
    manifest_path = directory/'manifest.json'
    require(not manifest_path.is_symlink(), 'Symlink in manifest')
    require(sha(manifest_path.read_bytes()) == spec['manifest_sha256'], 'Manifest hash')
    manifest = read_json(manifest_path)
    mapping = manifest.get(spec['map_key'])
    require(type(mapping) is dict and len(mapping) == spec['raw_file_count']
            == manifest.get('raw_file_count'), 'Archive file count')
    require(sha(canonical(mapping)) == spec['raw_tree_sha256']
            == manifest.get('raw_tree_sha256'), 'Archive tree hash')
    for name, digest in mapping.items():
        path = relative_file(directory, name)
        require(type(digest) is str and re.fullmatch('[0-9a-f]{64}', digest), 'Invalid raw digest')
        require(sha(path.read_bytes()) == digest, 'Raw file hash: ' + name)
    all_paths = list(directory.rglob('*'))
    require(not any(p.is_symlink() for p in all_paths), 'Symlink in archive inventory')
    actual = {p.relative_to(directory).as_posix() for p in all_paths if p.is_file()}
    require(actual - {'README.md', 'manifest.json'} == set(mapping), 'Archive inventory mismatch')
    return {k: spec[k] for k in ('path', 'manifest_sha256', 'raw_file_count', 'raw_tree_sha256')}


def _bound_results(case, candidate):
    require(type(candidate) is dict and candidate.get('status') == 'evaluated',
            'Evaluated candidate required')
    require(candidate.get('parent_id') == case['source_sha256'], 'Candidate parent binding')
    rows = candidate.get('results')
    require(type(rows) is list and [r.get('task_id') for r in rows] == case['task_ids'],
            'Evaluation allocation mismatch')
    for record in rows:
        require(record.get('candidate_hash') == candidate.get('source_sha256')
                and record.get('family') == case['family'], 'Evaluation source binding')
    baseline = case['baseline_results']
    require([r.get('task_id') for r in baseline] == case['task_ids'], 'Baseline allocation')
    require(all(r.get('candidate_hash') == case['source_sha256'] for r in baseline),
            'Baseline source binding')
    return baseline, rows


def outcome_for(case, candidate):
    baseline, rows = _bound_results(case, candidate)
    if case['family'] == 'planning':
        return assess_planning(baseline, rows, development_ids=case['development_task_ids'],
                               public_ids=case['prompt_task_ids'])
    require(len(rows) == len(baseline) == 1 and rows[0].get('metric_split') == 'train'
            and all(r.get('task_id') == 'oscillator1' for r in baseline + rows),
            'Evaluation symbolic scope')
    # The older pinned baseline stores per-task metrics in a compressed row;
    # its scope is on the source-bound outer candidate, not each result row.
    historical = case['historical_record']
    require(historical.get('metric_split') == 'train'
            and historical.get('source_sha256') == case['source_sha256']
            and historical.get('results') == baseline
            and historical.get('n_params') == case['n_params'], 'Baseline symbolic scope')
    require(all(r.get('status') == 'success' for r in baseline + rows),
            'This complete replay expects measured symbolic success')
    return assess_symbolic(
        {'nmse': baseline[0]['metrics']['nmse'], 'n_params': case['n_params']},
        {'nmse': rows[0]['metrics']['nmse'], 'n_params': candidate['n_params']})


def probe_projection(case):
    feedback = case['archive_feedback']
    require(feedback.get('source_sha256') == case['source_sha256'], 'Probe source binding')
    if case['family'] == 'planning':
        observations = feedback['observations']
        require([r['task_id'] for r in observations] == case['prompt_task_ids'], 'Probe task scope')
        rows = []
        for observation in observations:
            require(observation['status'] == 'completed', 'Incomplete probe')
            original, changed = observation['original'], observation['intervention']
            truth = None if original['status'] == 'success' else changed['status'] == 'success'
            expected = 'unknown' if truth is None else ('supported' if truth else 'contradicted')
            require(observation['verdict'] == expected, 'Probe verdict differs from outcomes')
            rows.append(dict(task_id=observation['task_id'],
                proposition={'quantity': 'same_plan_valid_after_edge_normalization', 'truth': truth},
                original_status=original['status'], intervention_status=changed['status']))
        eligible = all(r['proposition']['truth'] is True for r in rows)
        return dict(case_id=case['id'], family='planning', source_sha256=case['source_sha256'],
            rows=rows, opportunity='eligible_for_format_trial' if eligible else 'no_format_repair_support',
            scope=feedback['scope'], final_candidate_evaluated=False,
            diagnostic_copy_repair_deployed=False)
    require(feedback.get('status') == 'completed', 'Incomplete symbolic probe')
    observations = feedback['observations']
    require([r['variant'] for r in observations] == ['original', 'canonical_full', 'removed'],
            'Probe variant allocation')
    require(all(r['status'] == 'success' for r in observations), 'Unsuccessful probe variant')
    original, sham, removed = observations
    require(original['n_params'] == sham['n_params'] == case['n_params'], 'Probe parameter binding')
    result = symbolic_opportunity(original['nmse'], removed['nmse'], sham['nmse'],
                                  original['n_params'], removed['n_params'])
    truth = result['proposition']['truth']
    expected = 'unknown' if truth is None else ('supported' if truth else 'contradicted')
    require(feedback['verdict'] == expected, 'Probe verdict differs from measured loss')
    require(abs((removed['nmse'] - original['nmse']) - feedback['delta_nmse']) <= 1e-15,
            'Probe saved delta differs')
    return {**result, 'case_id': case['id'], 'family': 'symbolic',
            'source_sha256': case['source_sha256'], 'scope': feedback['scope'],
            'target_id': feedback['target_id'], 'archived_label': feedback['verdict'],
            'final_candidate_evaluated': False}


def analyze(root):
    root = Path(root).resolve()
    config_path = relative_file(root, CONFIG)
    require(sha(config_path.read_bytes()) == CONFIG_SHA256, 'Frozen replay config differs')
    config = read_json(config_path)
    from scripts.analyze_decision_replay import audit as audit_decision
    from scripts.analyze_edit_commitment import audit as audit_commitment
    from rsi_eval.decision_cases import load_cases
    cases = {c['id']: c for c in load_cases(root)}
    require(list(cases) == config['expected_case_ids'], 'Frozen case inventory')
    evidence, rows = [], []
    for spec, audit in zip(config['archives'], (audit_decision, audit_commitment)):
        verified = verify_archive(root, spec)
        directory = root/spec['path']
        audited = audit(root, directory)
        require(audited['status'] == 'passed', 'Historical audit failed')
        slots = read_json(directory/'summary.json')[spec['summary_key']]
        require(len(slots) == spec['candidate_count'], 'All historical slots required')
        for slot in slots:
            case = cases[slot['case_id']]
            require(slot['disposition'] == 'available', 'Historical candidate missing')
            relative = f"{spec['directory']}/{slot['session_id']}/candidate.json"
            candidate = read_json(relative_file(directory, relative))
            require(candidate == slot['candidate'], 'Historical summary/candidate binding')
            outcome = outcome_for(case, candidate)
            declaration = ({'edit_claim': candidate['edit_claim'],
                            'check': candidate['commitment_check']['edit_claim'],
                            'review_change': candidate['review_change']}
                           if 'edit_claim' in candidate else
                           {'edit_claim': None, 'note': 'No structured claim in this historical protocol.'})
            rows.append(dict(archive_id=spec['id'], session_id=slot['session_id'],
                condition=slot['condition'], case_id=case['id'], family=case['family'],
                candidate_path=spec['path']+'/'+relative,
                candidate_record_sha256=sha((directory/relative).read_bytes()),
                source_sha256=candidate['source_sha256'], base_source_sha256=case['source_sha256'],
                source_changed=candidate['source_sha256'] != case['source_sha256'],
                parameters_changed=candidate['n_params'] != case['n_params'],
                declaration=declaration, proposed_outcome=outcome,
                retrospective_rule_action=outcome['decision'],
                actual_policy_or_artifact_promoted=False))
        evidence.append({**verified, 'id': spec['id'], 'historical_runtime_commit': audited['runtime_commit'],
                         'historical_audit_status': audited['status'], 'submissions': len(slots)})
    require(len(rows) == config['expected_submissions'], 'Full replay cardinality')
    counts = dict(sorted(Counter(r['retrospective_rule_action'] for r in rows).items()))
    by_archive = {s['id']: dict(sorted(Counter(r['retrospective_rule_action'] for r in rows
                                            if r['archive_id'] == s['id']).items()))
                  for s in config['archives']}
    return dict(version=config['version'], mode=config['mode'], status='passed',
        implementation_files_sha256={p: sha(relative_file(root, p).read_bytes()) for p in IMPLEMENTATION_FILES},
        archives=evidence, historical_submissions=len(rows), historical_case_count=len(cases),
        distinct_final_source_count=len({r['source_sha256'] for r in rows}),
        decisions=counts, decisions_by_archive=by_archive,
        probes=[probe_projection(c) for c in cases.values()], rows=rows,
        new_model_calls=0, new_candidate_executions=0, new_probe_executions=0,
        new_task_evaluations=0, sealed_data_reads=0,
        strategy_selection_executed=False, persistent_strategy_updated=False,
        limitations=['Retrospective human-designed rule calibration, not counterfactual policy performance.',
            'All four states already used in mechanism design; repeated submissions are correlated.',
            'Historical scores are replayed without rerunning candidates or recomputing raw predictions.',
            'No new program/formula states or independent selection/evaluation scores created.',
            'Declaration truth and measured utility remain distinct; no automatic claim endorsement.',
            'The strategy selector is tested with synthetic fixtures only.'])


def write_output(root, path, result):
    root = Path(root).resolve()
    path = Path(path)
    if not path.is_absolute():
        path = root/path
    require(not any(p.is_symlink() for p in (path, *path.parents)), 'Symlink in output scope')
    path = path.resolve()
    allowed = (root/'tmp', root/'docs/analysis')
    require(any(path.is_relative_to(base) for base in allowed) and path.suffix == '.json',
            'Invalid output scope')
    raw = (json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)+'\n').encode('utf-8')
    if path.exists():
        require(path.read_bytes() == raw, 'Refusing different existing output')
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('xb') as stream:
            stream.write(raw)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    result = analyze(ROOT)
    write_output(ROOT, args.output, result)
    print(json.dumps({k: result[k] for k in ('status', 'historical_submissions', 'historical_case_count',
        'distinct_final_source_count', 'decisions', 'decisions_by_archive', 'new_model_calls',
        'new_candidate_executions', 'strategy_selection_executed', 'persistent_strategy_updated')}, indent=2))


if __name__ == '__main__':
    main()
