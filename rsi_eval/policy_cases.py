"""Immutable, separately projected experience and cross-state development inputs.

Loading never evaluates a candidate. Update callers receive two bounded cards,
not source programs, evidence identities, evaluation states, or later answers.
Full provenance remains host-side in the pinned specifications and inventory.
"""
import copy
import hashlib
import json
import math
from pathlib import Path

from .evidence_checks import check_claim, register_prediction, check_prediction
from .evidence_ids import EvidenceRegistry
from .repair_states import _json, _one, _read_verified, _validate_record


CONFIG_PATH = 'configs/pilots/policy-transfer-v0.1.json'
VERSION = 'policy-update-cases-v0.1'


def _case(case_id, role, family, session, candidate, hashes):
    if role == 'update':
        base = 'artifacts/paired-repair/2026-10-20/v01/' + session
        names = {'parent_source': 'candidates/'+family+'-000.py',
                 'source': 'candidates/'+candidate+'.py', 'trajectory': 'trajectory.json',
                 'diagnostics': 'diagnostics.json', 'evidence': 'evidence.json', 'audits': 'audits.json'}
        run, commit = '20261020-paired-repair-v01', '5bb61dba33033e9dbd215efeca28b232ec844f8c'
    else:
        base = 'artifacts/diagnostic-comparison/2026-10-20/' + session
        names = {'source': candidate+'.py', 'trajectory': 'trajectory.json', 'diagnostics': 'diagnostics.json'}
        run, commit = '20261020-diagnostic-comparison-v01', 'c36af55d4b20cb624f1cdb49cb5010990ce1d599'
    return {'case_id': case_id, 'role': role, 'family': family, 'archive_session': session,
            'archived_candidate_id': candidate, 'archive_run': run, 'archive_runtime_commit': commit,
            'files': {kind: {'path': base+'/'+name, 'sha256': hashes[kind]}
                      for kind, name in names.items()}}


# Config cannot independently repin these archive bytes. The distinct source
# hashes are an exclusion check, not a claim of independent tasks or lineages.
PINNED_CASES = [
    _case('U-P', 'update', 'planning', 'P1-r1-checked', 'planning-001', {
        'parent_source': 'afb7a5c0597d38b903bee13b10dc106b4ffddc776443769e4a975a997449512c',
        'source': 'fedb9ca63857eb42d30dc6fe9b963abe58cb70dc8136331b36eafef03c645429',
        'trajectory': '8c713770ed871409e9bc707d0aae7d4db099ff700ce451dfa68fcfe19b3d2725',
        'diagnostics': '9e43fc87ea1a168c8fe567067d5ee7c19b906e1550f6a784c78001e4aedb0f2a',
        'evidence': '85c655a2b5c542147bacc5d2698cebd8ff21fe9be8ec4aae5352dbd12e6ee86d',
        'audits': '26d4c0dc6c7492c2460de759e9c24c8459f2b90b2d1577041a01cad6eab18cee'}),
    _case('U-S', 'update', 'symbolic', 'S1-r1-checked', 'symbolic-001', {
        'parent_source': '38d8b88b02d6e3d7577308ad36e74872f39216414544bd45fd8337198c843e4d',
        'source': 'c73538e1966a3c452c44920fc5d8dd3cca71d345a868b2e48f7356a52532b3a0',
        'trajectory': 'f75242bb7ff961072b93cebe578b694ef1377411c7ed534ab032843a03be8507',
        'diagnostics': '4219c22a721d6077df49a0cc0ab85e3fc066fc5d0127ede6e98f50e21c8697a3',
        'evidence': 'c86b53a035398e97ddd1f3ad4da0df181b5dbc60796ed0a6a0664f9649ffbe6e',
        'audits': 'e54ec1be6b4411ffc4146a5cae4befafa2769d0afb6ca11deb0c4e188294e9cf'}),
    _case('E-P', 'evaluation', 'planning', 'planning_B', 'planning-003', {
        'source': '2f98dbb2b63144134a73cf1f9068f32df92b28779168b5859d9af537b2b0c897',
        'trajectory': '9332bab3dde3e2877be410caa2511de3111a80508921a9ef646d86dba3234586',
        'diagnostics': 'ba61d5f1e8f80ebd7dace31a6a45090d79c70a282f8e05202ec78afa2732a3d4'}),
    _case('E-S', 'evaluation', 'symbolic', 'symbolic_C', 'symbolic-002', {
        'source': 'eea9556fadca83705ce5d6551090fb34b5c7b5316e042998db4cfc723571ce47',
        'trajectory': 'c4456ca7ee96b47a21b608fd5eb5966f56208cb0cabebeed4d1138ffe6d99655',
        'diagnostics': 'ed13f0508d597e73383cf204b4c084554b675310bb0d94bdd1a705758a71af58'}),
]

PLAN_FIELDS = ('error_kind', 'executed_actions', 'first_failed_action', 'missing_preconditions',
               'missing_preconditions_truncated', 'plan_length', 'status', 'unsatisfied_goals',
               'unsatisfied_goals_truncated')
RESIDUAL_FIELDS = ('bias', 'binning_method', 'inputs', 'n', 'residual_definition', 'rmse', 'scope',
                   'standardized_bias', 'standardized_bias_definition', 'standardized_bias_reason', 'status')
BIN_FIELDS = {'count', 'lower', 'mean_residual', 'rmse', 'upper', 'upper_inclusive'}
RESULT_FIELDS = ('status', 'reason', 'op', 'actual', 'before', 'after', 'tolerance',
                 'direction', 'min_delta', 'expected')


def _catalog(root, role):
    root = Path(root).resolve()
    config = _json((root/CONFIG_PATH).read_text(encoding='utf-8'))
    if config.get('cases') != PINNED_CASES or config.get('states') != ['E-P', 'E-S']:
        raise ValueError('Policy cases differ from independently pinned cases')
    update_sources = {case['files'][kind]['sha256'] for case in PINNED_CASES
                      if case['role'] == 'update' for kind in ('parent_source', 'source')}
    evaluation_sources = {case['files']['source']['sha256'] for case in PINNED_CASES
                          if case['role'] == 'evaluation'}
    if update_sources & evaluation_sources:
        raise ValueError('Update/evaluation source overlap')
    return root, [case for case in PINNED_CASES if case['role'] == role]


def _documents(root, spec):
    content = {kind: _read_verified(root, entry) for kind, entry in spec['files'].items()}
    return {kind: value if kind in ('source', 'parent_source') else _json(value)
            for kind, value in content.items()}


def _source_matches(source, record):
    if (type(source) is not str or not source.strip() or len(source.encode('utf-8')) > 16384
            or hashlib.sha256(source.encode('utf-8')).hexdigest() != record['source_sha256']):
        raise ValueError('Archived source hash/size mismatch')


def _diagnostics(record, archived, family):
    task_ids = (['spannerlearning/seed0/problem0', 'spannerlearning/seed0/problem1']
                if family == 'planning' else ['oscillator1'])
    scope = 'public_prompt' if family == 'planning' else 'train'
    if type(archived) is not list or [item.get('task_id') for item in archived] != task_ids:
        raise ValueError('Archived diagnostic task scope mismatch')
    for index, diagnostic in enumerate(archived):
        result = record['results'][index]
        if (diagnostic.get('version') != 'diagnostics-v0.1' or diagnostic.get('scope') != scope
                or diagnostic.get('candidate_sha256') != record['source_sha256']
                or ('diagnostics' in result and result['diagnostics'] != diagnostic)):
            raise ValueError('Archived diagnostic source/binding mismatch')
        if family == 'planning':
            replay = diagnostic.get('plan_replay', {})
            if (set(replay) != set(PLAN_FIELDS) or replay['plan_length'] != result.get('plan_length')
                    or type(replay['plan_length']) is not int or replay['plan_length'] < 0
                    or type(replay['executed_actions']) is not int
                    or not 0 <= replay['executed_actions'] <= replay['plan_length']
                    or type(replay['first_failed_action']) not in (dict, type(None))):
                raise ValueError('Archived planning diagnostic disagrees with result')
        else:
            residuals = diagnostic.get('residuals', {})
            if (set(residuals) != set(RESIDUAL_FIELDS) or residuals['scope'] != 'train'
                    or residuals['status'] != 'ok' or residuals['n'] != 10000
                    or not math.isclose(residuals['rmse']**2, record['metrics']['mse'],
                                        rel_tol=1e-12, abs_tol=1e-15)):
                raise ValueError('Archived symbolic diagnostic disagrees with result')
            inputs = residuals['inputs']
            if type(inputs) is not list or [item.get('name') for item in inputs] != ['x', 'v']:
                raise ValueError('Archived residual diagnostic inputs mismatch')
            for item in inputs:
                if (set(item) != {'name', 'boundaries', 'bins'} or len(item['boundaries']) != 5
                        or len(item['bins']) != 4
                        or any(set(bin_) != BIN_FIELDS for bin_ in item['bins'])
                        or sum(bin_['count'] for bin_ in item['bins']) != residuals['n']):
                    raise ValueError('Archived residual diagnostic bins mismatch')
    return archived


def _evidence(record, snapshots, family, session):
    tasks = (['planning_batch', 'spannerlearning/seed0/problem0', 'spannerlearning/seed0/problem1']
             if family == 'planning' else ['oscillator1'])
    scopes = ['development_summary', 'public_prompt', 'public_prompt'] if family == 'planning' else ['train']
    if type(snapshots) is not list or len(snapshots) != len(tasks):
        raise ValueError('Archived evidence is incomplete')
    for item, task, scope in zip(snapshots, tasks, scopes):
        expected = {'session_id': session, 'candidate_id': record['candidate_id'],
                    'candidate_sha256': record['source_sha256'], 'task_id': task,
                    'version': 'evidence-v0.1', 'scope': scope}
        if item.get('binding') != expected:
            raise ValueError('Archived evidence binding mismatch')
    if any(snapshots[0].get('scalars', {}).get(key) != value for key, value in record['metrics'].items()):
        raise ValueError('Archived evidence metric mismatch')


def _observations(diagnostics, family):
    key = 'plan_replay' if family == 'planning' else 'residuals'
    return [{'task_id': item['task_id'], 'scope': item['scope'], key: copy.deepcopy(item[key])}
            for item in diagnostics]


def _safe_result(result):
    view = {key: copy.deepcopy(result[key]) for key in RESULT_FIELDS if key in result}
    # Retain which statistic was checked, without candidate/source/path bindings.
    view['metric_key'] = result['reference']['key']
    return view


def load_update_bundle(root):
    """Read only update archives and return two code-free, identity-free cards."""
    root, specs = _catalog(root, 'update')
    cards = []
    for spec in specs:
        data = _documents(root, spec)
        child = _one(data['trajectory'], spec['archived_candidate_id'], 'child trajectory')
        parent = _one(data['trajectory'], child.get('parent_id'), 'parent trajectory')
        family = spec['family']
        for record, source_key in ((parent, 'parent_source'), (child, 'source')):
            _validate_record(record, family)
            _source_matches(data[source_key], record)
        before = _diagnostics(parent, data['diagnostics'].get(parent['candidate_id']), family)
        after = _diagnostics(child, data['diagnostics'].get(child['candidate_id']), family)
        rationale = child.get('rationale')
        if type(rationale) is not str or len(rationale) > 2000:
            raise ValueError('Archived rationale exceeds the frozen card contract')
        parent_evidence = data['evidence'].get(parent['candidate_id'])
        child_evidence = data['evidence'].get(child['candidate_id'])
        # The paired round used the pair namespace, not the condition suffix.
        session = spec['archive_run']+':'+spec['archive_session'].removesuffix('-checked')
        _evidence(parent, parent_evidence, family, session)
        _evidence(child, child_evidence, family, session)
        audit = _one(data['audits'], child['candidate_id'], 'audit')
        registry = EvidenceRegistry(parent_evidence, session_id=session)
        declaration = audit['compact_declaration']
        claim_expansion = registry.expand_claim({'evidence_id': declaration['claim_id'],
            'op': declaration['claim_op'], 'value': _json(declaration['claim_value_json'])})
        prediction_expansion = registry.expand_prediction({'evidence_id': declaration['prediction_id'],
            'direction': declaration['prediction_direction'], 'min_delta': declaration['prediction_min_delta']})
        manifest_text = json.dumps(registry.export_manifest(), ensure_ascii=False, allow_nan=False,
                                   sort_keys=True, separators=(',', ':'))
        manifest_hash = hashlib.sha256(manifest_text.encode('utf-8')).hexdigest()
        if (claim_expansion != audit['claim_expansion'] or prediction_expansion != audit['prediction_expansion']
                or audit['registry'] != {'file': 'evidence-registry-000.json', 'sha256': manifest_hash}):
            raise ValueError('Archived audit expansion disagrees with original compact declaration')
        if claim_expansion.get('status') != 'resolved' or prediction_expansion.get('status') != 'resolved':
            raise ValueError('Archived audit did not resolve the original declaration')
        claims = [check_claim(claim_expansion['value'], parent_evidence)]
        registered = register_prediction(prediction_expansion['value'], parent_evidence)
        predicted = check_prediction(registered, child_evidence)
        if (claims != audit['claim_results'] or registered != audit['registration']
                or predicted != audit['prediction_result'] or predicted['status'] != 'contradicted'):
            raise ValueError('Archived audit disagrees with original evidence')
        cards.append({'case_id': spec['case_id'], 'family': family,
                      'parent_metrics': copy.deepcopy(parent['metrics']),
                      'child_metrics': copy.deepcopy(child['metrics']), 'rationale': rationale,
                      'observations_before': _observations(before, family),
                      'observations_after': _observations(after, family),
                      'claim_results': [_safe_result(result) for result in claims],
                      'prediction_result': _safe_result(predicted)})
    return {'version': VERSION, 'cases': cards}


def load_evaluation_states(root):
    """Copy two distinct archived development states; do not expose their futures."""
    root, specs = _catalog(root, 'evaluation')
    states = []
    for spec in specs:
        data = _documents(root, spec)
        record = _one(data['trajectory'], spec['archived_candidate_id'], 'evaluation trajectory')
        _validate_record(record, spec['family'])
        _source_matches(data['source'], record)
        diagnostics = _diagnostics(record, data['diagnostics'].get(record['candidate_id']), spec['family'])
        provenance = {'archive_run': spec['archive_run'], 'archive_session': spec['archive_session'],
                      'archived_candidate_id': spec['archived_candidate_id'],
                      'archive_runtime_commit': spec['archive_runtime_commit'],
                      'source_files': copy.deepcopy(list(spec['files'].values())),
                      'candidate_executions_during_load': 0,
                      'seed_policy': 'Forced archived child; no historical trajectory or later answer is exposed.',
                      'source_role': 'Researcher-seen development state; withheld from policy updater, not held-out data.'}
        states.append({'state_id': spec['case_id'], 'family': spec['family'], 'source': data['source'],
                       'n_params': record['n_params'], 'record': copy.deepcopy(record),
                       'diagnostics': copy.deepcopy(diagnostics), 'historical_common': {},
                       'historical_checks': {}, 'provenance': provenance})
    return states
