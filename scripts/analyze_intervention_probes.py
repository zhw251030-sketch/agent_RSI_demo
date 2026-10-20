#!/usr/bin/env python3
"""Audit frozen sources and probe record consistency; never execute candidates.

VAL verdicts, replay observations and reported training metrics remain trusted
inputs. This is not a fresh validation, prediction or NMSE calculation.
"""
import argparse
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

COUNT_KEYS = ('sandbox_calls', 'new_candidate_executions', 'host_validations',
              'val_calls', 'fit_calls', 'predict_calls')
CONFIG_PATH = 'configs/pilots/intervention-probes-v0.1.json'
EXPECTED = {'version': 'intervention-probes-v0.1',
    'protocol': 'docs/protocols/2026-10-21-intervention-probes-v0.1.md',
    'epsilon': 1e-5, 'numeric_tolerance': 1e-10, 'max_sandbox_calls': 40,
    'model_calls': 0, 'sealed_tasks_executed': 0,
    'case_order': ['planning', 'format_patch', 'symbolic', 'unsupported_fixture'],
    'format_patch_requires_all_public_supported': True, 'resume': False}
LIMITS = {'timeout_seconds': 20, 'memory_mb': 2048, 'cpu_seconds': 10,
          'max_output_bytes': 2000000}
LIMITATIONS = [
    'Saved VAL and replay observations are trusted; neither is rerun.',
    'NMSE differences are recomputed from saved scores, not raw predictions.',
    'No task data, sealed data, candidate code or model is executed/read.',
    'Git objects bind source identity, not authenticity of recorded observations.']


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def integer(value, minimum=0):
    return type(value) is int and value >= minimum


def path_inside(root, relative):
    require(type(relative) is str and '\\' not in relative, 'Invalid relative path')
    path = PurePosixPath(relative)
    require(not path.is_absolute() and '..' not in path.parts
            and str(path) == relative and ':' not in relative, 'Unsafe relative path')
    target = Path(root)
    for part in path.parts:
        target /= part
        require(not target.is_symlink(), 'Symlinked audit input')
    return target


def read(root, relative):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'Duplicate JSON key')
            result[key] = value
        return result

    def invalid(value):
        raise ValueError('Nonfinite JSON value')

    def number(value):
        result = float(value)
        require(math.isfinite(result), 'Nonfinite JSON number')
        return result

    return json.loads(path_inside(root, relative).read_bytes(), object_pairs_hook=pairs,
                      parse_constant=invalid, parse_float=number)


def expected_scope(family, result):
    actions = {
        'planning': {'supported': 'consider_format_patch_under_AST_contract',
                     'contradicted': 'formatting_not_sufficient_check_semantics',
                     'unknown': 'no_repair_inference'},
        'symbolic': {'supported': 'retain_selected_term_under_fixed_train_protocol',
                     'contradicted': 'consider_evaluated_term_removal',
                     'unknown': 'no_term_value_decision'}}
    return {'action': actions[family][result['verdict']],
            'scope': result['task_id'] if family == 'planning' else 'oscillator1/train',
            'excludes': ['physical_necessity', 'held_out_generalization',
                         'optimal_rule_selection', 'agent_autonomous_improvement']}


def planning_verdict(raw, normalized, normalization_available):
    if not normalization_available:
        return 'unknown', 'normalization_contract_unavailable'
    if raw['validation']['status'] == 'success':
        return 'unknown', 'original_already_valid_not_applicable'
    if normalized['validation']['status'] == 'success':
        return 'supported', 'edge_normalization_sufficient_on_this_plan'
    return 'contradicted', 'edge_normalization_insufficient_on_this_plan'


def symbolic_verdict(delta, epsilon, tolerance):
    require(all(finite(x) for x in (delta, epsilon, tolerance)) and
            0 < tolerance < epsilon, 'Invalid numeric comparison')
    if delta < -tolerance:
        return 'unknown', 'nested_fit_inconsistent'
    if delta > epsilon + tolerance:
        return 'supported', 'removal_loss_exceeds_threshold'
    if delta < epsilon - tolerance:
        return 'contradicted', 'removal_loss_below_threshold'
    return 'unknown', 'threshold_boundary'


def check_validation(observation, plan):
    require(type(observation) is dict, 'Missing validation observation')
    val, replay = observation.get('validation'), observation.get('replay')
    require(type(val) is dict and type(replay) is dict, 'Incomplete validation/replay')
    status, rs = val.get('status'), replay.get('status')
    length = len(plan) if type(plan) is list else None
    require(val.get('plan_length') == length and replay.get('plan_length') == length,
            'Plan length mismatch')
    n = replay.get('executed_actions')
    require(integer(n) and (length is None or n <= length), 'Invalid replay prefix')
    if status == 'success':
        require(val.get('validator', {}).get('status') == 'valid' and rs == 'valid'
                and n == length and replay.get('first_failed_action') is None
                and not replay.get('unsatisfied_goals'), 'Invalid successful validation')
    elif status == 'task_failure':
        require(val.get('validator', {}).get('status') == 'invalid'
                and rs in ('precondition_failure', 'goal_unsatisfied'), 'Semantic verdict disagreement')
        if rs == 'goal_unsatisfied':
            require(n == length and replay.get('first_failed_action') is None
                    and bool(replay.get('unsatisfied_goals')), 'Invalid unsatisfied-goal replay')
        else:
            require(type(length) is int and n < length and
                    replay.get('first_failed_action', {}).get('index') == n,
                    'Invalid precondition replay')
    elif status == 'invalid_output':
        require('validator' not in val and rs == 'invalid_output' and n == 0
                and val.get('error_kind') == replay.get('error_kind'), 'Invalid format rejection')
    else:
        raise ValueError('Validation is not a usable observation')


def metric_pair(metrics):
    require(type(metrics) is dict and set(metrics) == {'mse', 'nmse'}, 'Metric keys')
    mse, nmse = metrics['mse'], metrics['nmse']
    require(finite(mse) and finite(nmse) and mse >= 0 and nmse >= 0
            and ((mse == 0) == (nmse == 0)), 'Invalid metric pair')
    return mse, nmse


def check_budget(budget, counts, expected_reserved, maximum):
    require(set(budget) == {'maximum', 'reserved', 'actual'}
            and all(integer(x) for x in budget.values()), 'Invalid budget fields')
    require(budget['maximum'] == maximum and budget['reserved'] == expected_reserved
            and budget['actual'] == counts['sandbox_calls']
            and budget['actual'] <= budget['reserved'] <= maximum, 'Budget mismatch')


def freeze_check(root, freeze):
    require(freeze.get('version') == 'intervention-runtime-freeze-v0.1', 'Freeze version')
    commit = freeze.get('runtime_commit')
    require(type(commit) is str and re.fullmatch('[0-9a-f]{40}', commit), 'Invalid commit')
    hashes = freeze.get('runtime_files_sha256')
    require(type(hashes) is dict and hashes, 'Missing runtime hashes')
    names = subprocess.check_output(['git', '-C', str(root), 'ls-tree', '-r', '--name-only', commit],
                                    text=True, encoding='utf-8').splitlines()
    expected = {name for name in names if
                (name.startswith(('rsi_eval/', 'scripts/')) and name.count('/') == 1 and name.endswith('.py'))
                or (name.startswith('configs/tasks/') and name.count('/') == 2 and name.endswith('.json'))}
    expected.update((CONFIG_PATH, EXPECTED['protocol']))
    require(set(hashes) == expected, 'Incomplete or extra frozen runtime set')
    for relative, digest in hashes.items():
        path_inside(root, relative)
        require(type(digest) is str and re.fullmatch('[0-9a-f]{64}', digest), 'Invalid frozen hash')
        blob = subprocess.check_output(['git', '-C', str(root), 'show', commit + ':' + relative])
        require(sha(blob) == digest, 'Git object/hash mismatch: ' + relative)
        # Static rebuilding must use the same implementation/config as the run.
        if relative.startswith(('rsi_eval/', 'configs/tasks/')) or relative == CONFIG_PATH:
            require(sha(path_inside(root, relative).read_bytes()) == digest,
                    'Current reconstruction source differs: ' + relative)
    return commit


def record_identity(record, family, task, candidate, source_hash, parent, strategy, seen):
    require(type(record) is dict and record.get('family') == family
            and record.get('task_id') == task and record.get('candidate_id') == candidate
            and record.get('candidate_hash') == source_hash and record.get('parent_id') == parent
            and record.get('strategy_version') == strategy and record.get('limits') == LIMITS
            and type(record.get('model_calls')) is int and record['model_calls'] == 0
            and type(record.get('sealed_tasks_executed')) is int and record['sealed_tasks_executed'] == 0,
            'Executor identity or scope mismatch')
    run_id = record.get('run_id')
    require(type(run_id) is str and run_id and run_id not in seen, 'Duplicate/missing execution ID')
    seen.add(run_id)
    executions = record.get('executions')
    require(type(executions) is list and all(type(x) is dict for x in executions), 'Execution list missing')
    return executions


def check_planning(result, case, task, manifest, manifest_sha):
    from rsi_eval.planning_probe import normalize_plan
    require(result.get('version') == 'planning-format-probe-v0.1'
            and result.get('source_sha256') == case['source_sha256']
            and result.get('task_id') == task and result.get('model_calls') == 0
            and result.get('changes_historical_scores') is False, 'Planning probe identity')
    require(result.get('next_edit_scope') == expected_scope('planning', result), 'Planning next scope')
    binding = result.get('task_binding')
    if binding is not None:
        entry = next(t for t in manifest['tasks'] if t['id'] == task)
        require(binding.get('pilot_role') == entry['pilot_role'] == 'prompt'
                and binding.get('manifest_sha256') == manifest_sha
                and binding.get('domain_sha256') == manifest['domain']['sha256']
                and binding.get('problem_sha256') == entry['sha256']
                and re.fullmatch('[0-9a-f]{64}', binding.get('request_sha256', '')), 'Planning task binding')
    norm = result.get('normalization')
    if norm is not None:
        # Oversized/non-list originals are intentionally unavailable in the saved record.
        if norm.get('original') is not None:
            require(norm == normalize_plan(norm['original']), 'Normalization reconstruction mismatch')
        else:
            require(norm.get('status') == 'unknown' and norm.get('normalized') is None
                    and norm.get('token_preserved') is None, 'Unavailable normalization changed')
    counts = {k: 0 for k in COUNT_KEYS}
    counts['new_candidate_executions'] = counts['sandbox_calls'] = int(binding is not None)
    replays = 0
    for name in ('raw', 'normalized'):
        obs = result.get(name)
        if obs is not None:
            counts['host_validations'] += 1
            if type(obs.get('validation')) is dict:
                counts['val_calls'] += int('validator' in obs['validation'])
                replays += 1
            if result['status'] == 'completed':
                require(norm is not None, 'Missing original plan')
                check_validation(obs, norm['original' if name == 'raw' else 'normalized'])
    saved = result['executions']
    require(all(saved.get(k, 0) == v for k, v in counts.items())
            and saved.get('diagnostic_replays') == replays, 'Planning execution counts')
    if result['status'] == 'completed':
        require(binding is not None and norm is not None and saved['val_count_complete'] is True
                and result.get('transport', {}).get('status') == 'completed', 'Completed planning lacks evidence')
        expected = planning_verdict(result['raw'], result['normalized'], norm['normalized'] is not None)
        require((result['verdict'], result['reason']) == expected, 'Planning verdict changed')
    else:
        require(result['status'] in ('unavailable', 'infrastructure_error')
                and result['verdict'] == 'unknown', 'Failed probe asserts a conclusion')
    return counts


def check_symbolic(result, case, config, run_dir, manifest, manifest_sha, seen):
    from rsi_eval.symbolic_probe import build_term_removal
    args = {k: case[k] for k in ('n_params', 'remove_param_index', 'source_sha256',
                               'parent_source', 'parent_n_params', 'parent_sha256')}
    transform = build_term_removal(case['source'], **args)
    require(result.get('version') == 'matched-term-removal-v0.1' and result.get('case_id') == case['id']
            and result.get('transformation') == transform and result.get('epsilon') == config['epsilon']
            and result.get('tolerance') == config['numeric_tolerance']
            and result.get('model_calls') == result.get('sealed_tasks_executed') == 0,
            'Symbolic probe identity/transformation')
    require(result.get('next_edit_scope') == expected_scope('symbolic', result), 'Symbolic next scope')
    entry = next(x for x in manifest['symbolic']['files'] if x['relative_path'] == 'oscillator1/train.csv')
    identity = {'task': 'oscillator1', 'split': 'train', 'rows': entry['rows'],
                'input_names': ['x', 'v'], 'manifest_sha256': manifest_sha, 'data_sha256': entry['sha256']}
    if result.get('dataset_identity') is not None:
        require(result['dataset_identity'] == identity, 'Symbolic dataset binding')
    variants = result['variants']
    expected_sources = [('original', case['source'], case['n_params']),
        ('canonical_full', transform['canonical_source'], case['n_params']),
        ('removed', transform['removed_source'], case['parent_n_params'])]
    require(len(variants) == (3 if transform['status'] == 'ready' else 0), 'Variant count')
    counts = {k: 0 for k in COUNT_KEYS}
    scores, variance, ended = [], None, False
    for variant, (name, source, n_params) in zip(variants, expected_sources):
        require(variant.get('name') == name and variant.get('source') == source
                and variant.get('source_sha256') == sha(source.encode('utf-8'))
                and variant.get('n_params') == n_params, 'Symbolic variant changed')
        relative = 'symbolic/' + case['id'] + '/' + name + '.py'
        require(path_inside(run_dir, relative).read_bytes() == source.encode('utf-8'), 'Saved variant differs')
        record = variant.get('result')
        dispatched = record is not None or 'controller_error_type' in variant
        if dispatched:
            require(not ended, 'Non-prefix symbolic execution')
            counts['new_candidate_executions'] += 1
        else:
            ended = True
        if record is None:
            continue
        phases = record_identity(record, 'symbolic', 'oscillator1', case['id'] + '-' + name,
                                  variant['source_sha256'], case['source_sha256'],
                                  'matched-term-removal-v0.1', seen)
        counts['sandbox_calls'] += len(phases)
        for phase in phases:
            require(phase.get('phase') in ('fit', 'predict'), 'Unexpected symbolic phase')
            counts[phase['phase'] + '_calls'] += 1
        if record['status'] != 'success':
            ended = True
            continue
        fit, diag = record.get('fitting', {}), record.get('diagnostics', {})
        require(record.get('metric_split') == 'train' and fit.get('split') == 'train'
                and fit.get('n_params') == n_params and fit.get('max_nfev') == 100
                and fit.get('converged') is True and integer(fit.get('nfev'), 1) and fit['nfev'] <= 100
                and integer(fit.get('candidate_calls'), 1) and fit['candidate_calls'] <= 100000
                and type(fit.get('params')) is list and len(fit['params']) == n_params
                and all(finite(x) for x in fit['params'])
                and [x.get('phase') for x in phases] == ['fit', 'predict']
                and all(x.get('status') == 'completed' for x in phases)
                and diag.get('version') == 'diagnostics-v0.1'
                and diag.get('candidate_sha256') == variant['source_sha256']
                and diag.get('scope') == 'train' and diag.get('task_id') == 'oscillator1',
                'Fit or diagnostic evidence inconsistent')
        mse, nmse = metric_pair(record.get('metrics'))
        if nmse > 0:
            current = mse / nmse
            require(variance is None or math.isclose(current, variance, rel_tol=1e-12, abs_tol=0),
                    'Metric normalization drift')
            variance = current
        scores.append(nmse)
    require(result.get('candidate_evaluations') == counts['new_candidate_executions']
            and result.get('sandbox_executions') == counts['sandbox_calls']
            and all(result['executions'].get(k, 0) == v for k, v in counts.items()), 'Symbolic counts')
    sham = scores[1] - scores[0] if len(scores) >= 2 else None
    require(result.get('sham_delta_nmse') == sham, 'Sham delta changed')
    if result['status'] == 'completed':
        require(len(scores) == 3 and result.get('dataset_identity') == identity
                and result.get('execution_accounting_complete') is True
                and result.get('infrastructure_stopped') is False
                and abs(sham) <= config['numeric_tolerance'], 'Completed symbolic lacks valid evidence')
        delta = scores[2] - scores[1]
        require(result['delta_nmse'] == delta and (result['verdict'], result['reason']) ==
                symbolic_verdict(delta, config['epsilon'], config['numeric_tolerance']), 'Symbolic verdict changed')
    else:
        require(result['verdict'] == 'unknown' and result['delta_nmse'] is None, 'Unavailable symbolic conclusion')
        if sham is not None and abs(sham) > config['numeric_tolerance']:
            require(len(scores) == 2 and result['reason'] == 'canonical_sham_drift', 'Sham stopping rule')
    return counts


def audit(root, run_dir):
    """Raise ValueError on inconsistency; return explicitly bounded audit evidence."""
    root, run_dir = Path(root).resolve(), Path(run_dir).resolve()
    config, freeze = read(run_dir, 'config.json'), read(run_dir, 'freeze.json')
    require(config == EXPECTED and all(type(config[k]) is type(v) for k, v in EXPECTED.items()), 'Protocol changed')
    commit = freeze_check(root, freeze)
    from rsi_eval.probe_cases import load_cases
    from rsi_eval.planning_probe import build_format_patch
    from rsi_eval.symbolic_probe import build_term_removal
    bundle = load_cases(root)
    require(read(run_dir, 'cases.json') == bundle and read(root, CONFIG_PATH) == config, 'Case/config pin changed')
    summary = read(run_dir, 'summary.json')
    require(summary.get('version') == config['version'] and summary.get('model_calls') == 0
            and summary.get('sealed_tasks_executed') == 0, 'Summary scope')
    complete = summary.get('status') == 'completed'
    require(summary.get('status') in ('completed', 'stopped', 'prepared', 'running'), 'Unknown run status')
    if complete:
        require(freeze.get('checkout_clean') is True and summary.get('counts_complete') is True
                and summary.get('errors') == [], 'Completed run has incomplete/infrastructure evidence')
    counts, reserved, seen = {k: 0 for k in COUNT_KEYS}, 0, set()
    def add(values):
        for key in COUNT_KEYS:
            require(integer(values.get(key, 0)), 'Invalid count')
            counts[key] += values.get(key, 0)
    manifest_path = 'configs/tasks/planning-spanner-v0.1.json'
    manifest = read(root, manifest_path)
    manifest_sha = sha(path_inside(root, manifest_path).read_bytes())
    planning = summary['planning']
    require(len(planning) <= 3 and (not complete or len(planning) == 3), 'Planning case count')
    for i, (row, case) in enumerate(zip(planning, bundle['planning'])):
        require(row['id'] == case['id'] and len(row['results']) <= 2, 'Planning order')
        require(len(row['results']) == 2 or (not complete and i == len(planning) - 1), 'Non-prefix public probes')
        for j, (result, task) in enumerate(zip(row['results'], bundle['public_tasks'])):
            require(read(run_dir, 'planning/' + case['id'] + '/public-' + str(j) + '.json') == result,
                    'Planning summary/sidecar mismatch')
            add(check_planning(result, case, task, manifest, manifest_sha)); reserved += 1
    patch = summary['format_patch']
    trigger = len(planning) > 0 and len(planning[0]['results']) == 2 and all(
        x['status'] == 'completed' and x['verdict'] == 'supported' for x in planning[0]['results'])
    if patch['status'] in ('running', 'completed'):
        require(trigger and len(planning) == 3 and all(len(x['results']) == 2 for x in planning), 'Premature format patch')
        expected = build_format_patch(bundle['planning'][0]['source'])
        require(patch['source_case'] == bundle['planning'][0]['id'] and patch['patch'] == expected
                and read(run_dir, 'format-patch/contract.json') == expected
                and expected['status'] == 'accepted', 'Format patch reconstruction')
        require(path_inside(run_dir, 'format-patch/candidate.py').read_bytes() == expected['source'].encode('utf-8'),
                'Format patch source mismatch')
        require(len(patch['results']) <= 10 and (patch['status'] != 'completed' or len(patch['results']) == 10), 'Patch task count')
        for i, (record, task) in enumerate(zip(patch['results'], bundle['development_tasks'])):
            require(read(run_dir, 'format-patch/evaluation-' + format(i, '02d') + '.json') == record, 'Patch sidecar mismatch')
            phases = record_identity(record, 'planning', task, 'researcher-format-intervention',
                expected['source_sha256'], patch['source_case'], config['version'], seen)
            require(len(phases) <= 1 and all(x.get('phase') == 'plan' for x in phases), 'Patch execution phases')
            validated = ('plan_length' in record or record.get('error_kind') in
                         ('diagnostic_validator_disagreement', 'plan_validation_failed'))
            values = dict(sandbox_calls=len(phases), new_candidate_executions=1,
                          host_validations=int(validated), val_calls=int('validator' in record))
            add(values); reserved += 1
            if record['status'] in ('success', 'task_failure'):
                require(record.get('validator', {}).get('status') ==
                        ('valid' if record['status'] == 'success' else 'invalid'), 'Patch VAL disagreement')
                require(len(phases) == 1 and phases[0]['status'] == 'completed', 'Patch success before execution')
            if task in bundle['public_tasks'] and validated and record['status'] != 'infrastructure_error':
                diag = record.get('diagnostics', {})
                require(diag.get('candidate_sha256') == expected['source_sha256'] and diag.get('task_id') == task
                        and diag.get('scope') == 'public_prompt', 'Patch diagnostic identity')
                # Full plans are not stored here; length/replay/status checks remain available.
                n = record.get('plan_length')
                check_validation({'validation': record, 'replay': diag.get('plan_replay')},
                                 [None] * n if integer(n) else None)
            if complete:
                require(record['status'] != 'infrastructure_error' and record.get('error_kind') not in
                        ('validator_io', 'plan_validation_failed', 'diagnostic_validator_disagreement'), 'Patch infrastructure')
    elif patch['status'] == 'not_triggered':
        require(not trigger and patch == {'status': 'not_triggered', 'reason': 'public_probe_not_all_supported'}, 'Patch trigger changed')
    else:
        require(not complete and patch == {'status': 'not_started'}, 'Missing patch stage')
    if complete:
        require(patch['status'] == ('completed' if trigger else 'not_triggered'), 'Incomplete patch stage')
    data_path = 'configs/tasks/downloads-v0.1.json'
    data_manifest = read(root, data_path)
    data_sha = sha(path_inside(root, data_path).read_bytes())
    symbolic = summary['symbolic']
    require(len(symbolic) <= 2 and (not complete or len(symbolic) == 2), 'Symbolic case count')
    for row, case in zip(symbolic, bundle['symbolic']):
        require(row['id'] == case['id'] and read(run_dir, 'symbolic/' + case['id'] + '/probe.json') == row['result'],
                'Symbolic order/sidecar mismatch')
        add(check_symbolic(row['result'], case, config, run_dir, data_manifest, data_sha, seen)); reserved += 6
    fixture = summary['unsupported_fixture']
    if fixture is not None:
        source = 'def equation(x, v, params):\n    return params[0]*params[1]*x + params[2]*v\n'
        parent = 'def equation(x, v, params):\n    return params[0]*x + params[1]*v\n'
        expected = {'origin': 'researcher_synthetic_not_benchmark', 'source': source, 'parent_source': parent,
            'sandbox_calls': 0, 'result': build_term_removal(source, n_params=3, remove_param_index=2,
                source_sha256=sha(source.encode()), parent_source=parent, parent_n_params=2, parent_sha256=sha(parent.encode()))}
        require(fixture == expected == read(run_dir, 'unsupported-fixture.json')
                and fixture['result']['status'] == 'unknown', 'Synthetic rejection fixture changed')
    require(not complete or fixture is not None, 'Missing rejection calibration')
    require(summary['counts'] == counts and all(integer(x) for x in summary['counts'].values()), 'Summary counts differ')
    if complete or summary['status'] == 'prepared':
        check_budget(summary['budget'], counts, reserved, config['max_sandbox_calls'])
    else:
        # A stopped run may have reserved the next block before a record existed.
        require(reserved <= summary['budget']['reserved'] <= config['max_sandbox_calls'], 'Stopped reservation mismatch')
        check_budget(summary['budget'], counts, summary['budget']['reserved'], config['max_sandbox_calls'])
    return {'version': 'intervention-record-audit-v0.1', 'status': 'verified_complete' if complete else 'partial_not_complete',
            'run_status': summary['status'], 'runtime_commit': commit, 'counts': counts,
            'counts_complete': summary.get('counts_complete') is True, 'budget': summary['budget'],
            'model_calls': 0, 'candidate_executions_by_auditor': 0, 'sealed_data_reads': 0,
            'limitations': list(LIMITATIONS)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run_dir', type=Path)
    parser.add_argument('--root', type=Path, default=ROOT)
    args = parser.parse_args()
    print(json.dumps(audit(args.root, args.run_dir), ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
