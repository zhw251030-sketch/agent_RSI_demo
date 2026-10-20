"""Four pinned development repair states; loading copies evidence, never executes.

The pilot's original curated record has no diagnostic payload. Its fourth state
therefore pairs that original model identity with an independently archived,
unchanged-source diagnostic replay. This assembly is explicit in provenance.
"""
import copy
import math
from pathlib import Path, PurePosixPath

from .policy_cases import _diagnostics, _source_matches
from .repair_states import _json, _one, _read_verified, _validate_record


STATE_ORDER = ('P-A002', 'P-B002', 'S-poly5', 'S-odd4')
_PLAN_METRICS = dict(prompt_successes=0, prompt_total=2, development_successes=0,
                     development_total=8, total_successes=0, total_tasks=10)


def _entry(path, digest):
    return {'path': path, 'sha256': digest}


def _ordinary(state_id, family, base, candidate, index, n_params, metrics,
              source_name, hashes, run, commit, lineage):
    return {'state_id': state_id, 'family': family, 'archive_session': base.rsplit('/', 1)[-1],
            'archived_candidate_id': candidate, 'record_index': index, 'n_params': n_params,
            'metrics': copy.deepcopy(metrics), 'archive_run': run,
            'archive_runtime_commit': commit, 'lineage': lineage,
            'files': {'source': _entry(base+'/'+source_name, hashes[0]),
                      'trajectory': _entry(base+'/trajectory.json', hashes[1]),
                      'diagnostics': _entry(base+'/diagnostics.json', hashes[2])}}


PINNED_STATES = {
    'P-A002': _ordinary('P-A002', 'planning',
        'artifacts/diagnostic-comparison/2026-10-20/planning_A', 'planning-002', 2, 3,
        _PLAN_METRICS, 'planning-002.py', (
            '67372060d92e060efd36035c230fcea51d20ac484ee585ee52fda416127132f4',
            '69af92d6002375c3eaff36bbfebbada71c8b8fdaf9b04e8662b318ce6c098cb3',
            'f87360a0eeac9bf74d6ac203ae50af9456d1cd8229fe9986432553b6170ebe4c'),
        '20261020-diagnostic-comparison-v01', 'c36af55d4b20cb624f1cdb49cb5010990ce1d599',
        'Separate A information history from U-P and old E-P/B003; common empty-plan root. '
        'A001 was already seen; later successful A003 is excluded.'),
    'P-B002': _ordinary('P-B002', 'planning',
        'artifacts/diagnostic-comparison/2026-10-20/planning_B', 'planning-002', 2, 3,
        _PLAN_METRICS, 'planning-002.py', (
            '31556410061483bcdf5593e3e4ee75db650bbfbab324a1b8fa833259e310b0d8',
            '9332bab3dde3e2877be410caa2511de3111a80508921a9ef646d86dba3234586',
            'ba61d5f1e8f80ebd7dace31a6a45090d79c70a282f8e05202ec78afa2732a3d4'),
        '20261020-diagnostic-comparison-v01', 'c36af55d4b20cb624f1cdb49cb5010990ce1d599',
        'Information ancestor of old E-P/B003, despite both selecting the empty-plan parent. '
        'Separate from U-P; B001 already seen, B003 and later answers excluded.'),
    'S-poly5': _ordinary('S-poly5', 'symbolic',
        'artifacts/checked-feedback/2026-10-20/v01-stopped/symbolic_checked',
        'symbolic-003', 3, 5,
        {'mse': 0.0004091082334152086, 'nmse': 0.09376229967010528},
        'candidates/symbolic-003.py', (
            'a4eca8e167987cb3dece02024c8d281eafb2bef179da7f82e55dfb9fa4900dd0',
            'b51c4f03cf38f13cc1213fb45c453605cd7a654751a66c6f8a00fc10df0a545e',
            '8da0748c75ca6bfe08c92e77d76409efd5c4abc10bbea8db951d0eba2c2a10d0'),
        '20261020-checked-feedback-v01', 'c4d4f60f852208494e214bd226882e532172c799',
        'Distinct v01 history from U-S/v02 and old E-S/C002; shared constant root and '
        'mathematically equivalent linear ancestor. Formula: x,v,x^3,v^2,x^5.'),
    'S-odd4': {
        'state_id': 'S-odd4', 'family': 'symbolic', 'archive_session': 'symbolic',
        'archived_candidate_id': 'symbolic-003', 'n_params': 4,
        'metrics': {'mse': 0.00040056676206938317, 'nmse': 0.09180470524756017},
        'archive_run': '20261020-minimax-v01-recovery',
        'archive_runtime_commit': '49b4b9f6d967360b264cd93f52c326a7814bb595',
        'record_pointer': '/session_outcomes/1/trajectory/3',
        'replay_run': '20261020-diagnostic-probe-v01',
        'replay_evaluator_run_id': 'd6c079a6fc3341b6ae87b1d59b61c754',
        'lineage': 'Original pilot history, separate from U-S/v02 and old E-S/C002. '
                   'Shares the constant root and linear/cubic mathematical ancestors with S-poly5; '
                   'not an independent task. Formula: x,v,x^3,v*abs(v).',
        'files': {
            'source': _entry('artifacts/pilot/2026-10-20/symbolic-003.py',
                'f3c893f0989dc6a72029687090cd1e3c444eca24e8643740a0a62dddd21d801e'),
            'record': _entry('docs/environment/2026-10-20-agent-pilot-verification.json',
                'a4df3771754340b7a4872a5e8aaa07bcc45c6d5da777bbf8f0e53b5f012a6453'),
            'feedback': _entry('artifacts/grounded-policy-inputs/2026-10-20/pilot-symbolic-003-feedback.json',
                'ed849fd17ccafa807637be37d3617afe926d26efb1da88471777786260ff4fda')}}}


def _read_documents(root, spec):
    documents = {}
    for kind, entry in spec['files'].items():
        name = entry['path']
        if type(name) is not str:
            raise ValueError('Archived path must be a relative string')
        relative = PurePosixPath(name)
        if (relative.is_absolute() or '..' in relative.parts
                or '\\' in name or ':' in name):
            raise ValueError('Archived path must be relative and stay inside project')
        text = _read_verified(root, entry)
        documents[kind] = text if kind == 'source' else _json(text)
    return documents


def _identity(record, spec):
    if (type(record) is not dict or record.get('candidate_id') != spec['archived_candidate_id']
            or record.get('source_sha256') != spec['files']['source']['sha256']
            or record.get('status') != 'evaluated' or record.get('origin') != 'model_proposed'
            or type(record.get('n_params')) is not int or record['n_params'] != spec['n_params']
            or record.get('metrics') != spec['metrics']):
        raise ValueError('Archived record identity, parameter count or pinned metrics mismatch')


def _pilot_record(documents, spec):
    """Retain source identity, but never relabel the later replay as original evidence."""
    verification = documents['record']
    try:
        rows = verification['session_outcomes'][1]['trajectory']
        original = rows[3]
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError('Pilot verification record pointer is unavailable') from exc
    if _one(rows, spec['archived_candidate_id'], 'pilot trajectory') != original:
        raise ValueError('Pilot verification record order mismatch')
    _identity(original, spec)
    if (verification.get('code_commit') != spec['archive_runtime_commit']
            or verification.get('run_id') != spec['archive_run']
            or original.get('evaluator_run_ids') != ['a8019bf73a40470f9d61dd196b2e0821']):
        raise ValueError('Pilot original run provenance mismatch')
    replay = documents['feedback']
    fitting = replay.get('fitting', {})
    if (replay.get('schema_version') != '0.1' or replay.get('family') != 'symbolic'
            or replay.get('task_id') != 'oscillator1' or replay.get('metric_split') != 'train'
            or replay.get('status') != 'success' or replay.get('metrics') != original['metrics']
            or replay.get('candidate_id') != original['candidate_id']
            or replay.get('candidate_hash') != original['source_sha256']
            or replay.get('run_id') != spec['replay_evaluator_run_id']
            or fitting.get('n_params') != original['n_params'] or fitting.get('split') != 'train'
            or type(fitting.get('params')) is not list or len(fitting['params']) != original['n_params']
            or any(type(value) not in (int, float) or not math.isfinite(value)
                   for value in fitting['params'])
            or replay.get('parent_id') != original['candidate_id']
            or replay.get('model_calls') != 0 or replay.get('sealed_tasks_executed') != 0
            or replay.get('feedback_role') != 'development_only'
            or replay.get('strategy_version') != 'human-diagnostic-probe-v0.1'):
        raise ValueError('Pilot replay identity, fit, metric or scope mismatch')
    names = ('candidate_id', 'parent_id', 'source_sha256', 'origin', 'n_params',
             'rationale', 'strategy_version', 'status', 'metrics')
    record = {name: copy.deepcopy(original[name]) for name in names}
    record.update(results=[copy.deepcopy(replay)], metric_split='train')
    provenance = {'record_pointer': spec['record_pointer'],
                  'original_evaluator_run_ids': copy.deepcopy(original['evaluator_run_ids']),
                  'diagnostic_replay_run': spec['replay_run'],
                  'diagnostic_replay_evaluator_run_id': replay['run_id'],
                  'record_assembly': 'Original model identity and rationale plus later unchanged-source '
                                     'replay results and diagnostics; original and replay scores agree.'}
    return record, [replay.get('diagnostics')], provenance


def load_grounded_states(root):
    """Load exactly four researcher-seen development states, without reevaluation.

Only the selected records and own diagnostics are returned. Whole archive
trajectories, their later answers, the inventory and credentials are excluded.
The caller receives fresh copies; file hashes and semantic bindings are checked.
"""
    root = Path(root).resolve()
    if set(PINNED_STATES) != set(STATE_ORDER):
        raise ValueError('Grounded state catalog differs from frozen state IDs')
    states = []
    for state_id in STATE_ORDER:
        spec = PINNED_STATES[state_id]
        if spec.get('state_id') != state_id or spec.get('family') not in ('planning', 'symbolic'):
            raise ValueError('Grounded state identity mismatch')
        documents = _read_documents(root, spec)
        if state_id == 'S-odd4':
            record, diagnostics, detail = _pilot_record(documents, spec)
        else:
            rows = documents['trajectory']
            record = _one(rows, spec['archived_candidate_id'], 'grounded trajectory')
            if (len(rows) <= spec['record_index'] or rows[spec['record_index']] != record):
                raise ValueError('Archived record position mismatch')
            diagnostics = documents['diagnostics'].get(record['candidate_id'])
            detail = {'record_index': spec['record_index'],
                      'record_assembly': 'Original model record and original own diagnostics.'}
        _identity(record, spec)
        _validate_record(record, spec['family'])
        _source_matches(documents['source'], record)
        diagnostics = _diagnostics(record, diagnostics, spec['family'])
        provenance = {name: copy.deepcopy(spec[name]) for name in
                      ('archive_run', 'archive_session', 'archived_candidate_id',
                       'archive_runtime_commit', 'lineage')}
        provenance.update(source_files=copy.deepcopy(list(spec['files'].values())),
            candidate_executions_during_load=0,
            seed_policy='Forced archived model candidate; no historical or future answers exposed.',
            source_role='Researcher-seen development repair state; not a held-out or independent task.',
            **detail)
        states.append({'state_id': state_id, 'family': spec['family'], 'source': documents['source'],
                       'n_params': record['n_params'], 'record': copy.deepcopy(record),
                       'diagnostics': copy.deepcopy(diagnostics), 'historical_common': {},
                       'historical_checks': {}, 'provenance': provenance})
    return states
