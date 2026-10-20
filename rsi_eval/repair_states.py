"""Load two immutable development repair states without executing candidates.

The selected child is the NEW repair starting point even when the original
search rejected it. Historical declarations and checks retain their original
bindings and are never repaired, reinterpreted, or counted as new submissions.
"""
import copy
import hashlib
import json
import math
from pathlib import Path

from .evidence_checks import check_claim, register_prediction, check_prediction


CONFIG_PATH = 'configs/pilots/paired-repair-v0.1.json'
ARCHIVE_ROOT = 'artifacts/checked-feedback/2026-10-20/v02'
ARCHIVE_RUN = '20261020-checked-feedback-v02'
ARCHIVE_COMMIT = 'e298713f575ea04d99984a32fc4c1f6dfbc6a5ce'


def _spec(state_id, family, session, candidate, hashes):
    names = {'source': 'candidates/'+candidate+'.py', 'trajectory': 'trajectory.json',
             'diagnostics': 'diagnostics.json', 'evidence': 'evidence.json', 'audits': 'audits.json'}
    return {'state_id': state_id, 'family': family, 'archive_session': session,
            'archived_candidate_id': candidate,
            'files': {kind: {'path': ARCHIVE_ROOT+'/'+session+'/'+name, 'sha256': hashes[kind]}
                      for kind, name in names.items()}}


# Independently pinned here as well as in the protocol config. Altering config
# hashes alone cannot silently replace a seed after the protocol was frozen.
PINNED_STATES = [
    _spec('P1', 'planning', 'planning_hidden', 'planning-001', {
        'source': 'afb7a5c0597d38b903bee13b10dc106b4ffddc776443769e4a975a997449512c',
        'trajectory': '0d33f5e216020d374d43c1d597329c3bd700400c4fd62fe4e598621d74648be6',
        'diagnostics': '106651b2873a6e437f97e2e000b9d6a5e9226b2ae4158f397d9346c010a03152',
        'evidence': '5c3385dab136ef705af4da24b86dda01c10a8d63a8127f29481b23cdc0979dcc',
        'audits': '37ddc683563613c5a0a07021d22152d6dde52c982270a4fa159d8754622d55e2'}),
    _spec('S1', 'symbolic', 'symbolic_checked', 'symbolic-002', {
        'source': '38d8b88b02d6e3d7577308ad36e74872f39216414544bd45fd8337198c843e4d',
        'trajectory': '479d46bf17e0708172c4f1fb88dcd6c52d792f71e3315d91a07e5373d509fcd5',
        'diagnostics': '597b13476e5b5b1d4d3bb10fe4f9645ca1da3334b0147174f5ef948527ae0e7e',
        'evidence': 'a9d7e7aa1d2d7e489ebabf463cbe224ec97045a78751dc2197f3fa7bf1995819',
        'audits': '6df0ac3afa2f5128fd2d265ea24ca52ff07559d1083ed8868603ad425c4c2628'}),
]


def _json(content):
    def reject(value):
        raise ValueError('Nonfinite archived JSON constant: '+value)
    return json.loads(content, parse_constant=reject)


def _read_verified(root, entry):
    path = (root/entry['path']).resolve()
    if not path.is_relative_to(root):
        raise ValueError('Archived path escapes project')
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != entry['sha256']:
        raise ValueError('Archived file hash mismatch: '+entry['path'])
    return raw.decode('utf-8')


def _one(items, identifier, label):
    if type(items) is not list or any(type(item) is not dict for item in items):
        raise ValueError(label+': expected list of records')
    matches = [item for item in items if item.get('candidate_id') == identifier]
    if len(matches) != 1:
        raise ValueError(label+': candidate missing or ambiguous')
    return matches[0]


def _finite_number(value):
    return type(value) in (int, float) and math.isfinite(value)


def _validate_record(record, family):
    task_ids = (['spannerlearning/seed0/problem'+str(i) for i in range(10)]
                if family == 'planning' else ['oscillator1'])
    results = record.get('results')
    if (record.get('status') != 'evaluated' or type(results) is not list
            or len(results) != len(task_ids)):
        raise ValueError('Archived record is not complete')
    if [item.get('task_id') for item in results] != task_ids:
        raise ValueError('Archived task order differs from frozen development scope')
    if any(item.get('candidate_hash') != record.get('source_sha256') for item in results):
        raise ValueError('Archived execution source hash mismatch')
    if any(item.get('status') in (None, 'infrastructure_error', 'invalid_request') for item in results):
        raise ValueError('Archived record is not complete')
    if type(record.get('n_params')) is not int or not 0 <= record['n_params'] <= 16:
        raise ValueError('Invalid archived parameter count')
    metrics = record.get('metrics')
    if type(metrics) is not dict or any(not _finite_number(value) for value in metrics.values()):
        raise ValueError('Invalid archived metrics')
    if family == 'planning':
        prompt = sum(item['status'] == 'success' for item in results[:2])
        development = sum(item['status'] == 'success' for item in results[2:])
        expected = dict(prompt_successes=prompt, prompt_total=2,
                        development_successes=development, development_total=8,
                        total_successes=prompt+development, total_tasks=10)
        if metrics != expected:
            raise ValueError('Archived planning metrics disagree with execution results')
    elif (results[0].get('status') != 'success' or metrics != results[0].get('metrics')
          or set(metrics) != {'mse', 'nmse'} or any(value < 0 for value in metrics.values())
          or record.get('metric_split') != 'train'):
        raise ValueError('Archived symbolic metrics disagree with train result')


def _validate_diagnostics(record, diagnostics, family):
    expected = (['spannerlearning/seed0/problem0', 'spannerlearning/seed0/problem1']
                if family == 'planning' else ['oscillator1'])
    scope = 'public_prompt' if family == 'planning' else 'train'
    if type(diagnostics) is not list or [x.get('task_id') for x in diagnostics] != expected:
        raise ValueError('Archived diagnostic task scope mismatch')
    for index, diagnostic in enumerate(diagnostics):
        if (diagnostic.get('version') != 'diagnostics-v0.1' or diagnostic.get('scope') != scope
                or diagnostic.get('candidate_sha256') != record['source_sha256']
                or diagnostic != record['results'][index].get('diagnostics')):
            raise ValueError('Archived diagnostic source/binding mismatch')


def _validate_evidence(record, evidence, family, session):
    tasks = (['planning_batch', 'spannerlearning/seed0/problem0', 'spannerlearning/seed0/problem1']
             if family == 'planning' else ['oscillator1'])
    scopes = ['development_summary', 'public_prompt', 'public_prompt'] if family == 'planning' else ['train']
    if type(evidence) is not list or len(evidence) != len(tasks):
        raise ValueError('Archived evidence is incomplete')
    for item, task, scope in zip(evidence, tasks, scopes):
        expected = {'session_id': ARCHIVE_RUN+':'+session, 'candidate_id': record['candidate_id'],
                    'candidate_sha256': record['source_sha256'], 'task_id': task,
                    'version': 'evidence-v0.1', 'scope': scope}
        if item.get('binding') != expected:
            raise ValueError('Archived evidence binding mismatch')
    scalars = evidence[0].get('scalars', {})
    if any(scalars.get(key) != value for key, value in record['metrics'].items()):
        raise ValueError('Archived evidence metric mismatch')


def _candidate_summary(record, *, rationale=False):
    names = ['candidate_id', 'source_sha256', 'n_params', 'metrics']
    if rationale:
        names.append('rationale')
    return {key: record[key] for key in names}


def load_repair_states(root):
    """Return fresh copies after byte and cross-record verification.

    This reads only the fixed config and ten pinned archive files. It does not
    import an executor, access task data, load credentials, or call a model.
    Pure predicate recomputation checks archived audit integrity; it does not
    reevaluate the archived programs/formulas or modify their original results.
    """
    root = Path(root).resolve()
    config = _json((root/CONFIG_PATH).read_text(encoding='utf-8'))
    if config.get('states') != PINNED_STATES:
        raise ValueError('Repair states differ from independently pinned seeds')
    states = []
    for spec in PINNED_STATES:
        contents = {kind: _read_verified(root, entry) for kind, entry in spec['files'].items()}
        source = contents.pop('source')
        data = {kind: _json(value) for kind, value in contents.items()}
        record = _one(data['trajectory'], spec['archived_candidate_id'], 'trajectory')
        previous = _one(data['trajectory'], record.get('parent_id'), 'previous trajectory')
        family = spec['family']
        for selected in (record, previous):
            _validate_record(selected, family)
        if (hashlib.sha256(source.encode('utf-8')).hexdigest() != record['source_sha256']
                or len(source.encode('utf-8')) > 16384 or not source.strip()):
            raise ValueError('Selected archived source hash/size mismatch')
        diagnostics = data['diagnostics'].get(record['candidate_id'])
        _validate_diagnostics(record, diagnostics, family)
        current_evidence = data['evidence'].get(record['candidate_id'])
        parent_evidence = data['evidence'].get(previous['candidate_id'])
        _validate_evidence(record, current_evidence, family, spec['archive_session'])
        _validate_evidence(previous, parent_evidence, family, spec['archive_session'])
        audit = _one(data['audits'], record['candidate_id'], 'audit')
        claim_results = [check_claim(claim, parent_evidence) for claim in audit['claims']]
        registration = register_prediction(audit['prediction'], parent_evidence)
        prediction_result = check_prediction(registration, current_evidence)
        if (claim_results != audit.get('claim_results') or registration != audit.get('registration')
                or prediction_result != audit.get('prediction_result')
                or prediction_result.get('status') != 'contradicted'):
            raise ValueError('Archived audit differs from its exact immutable evidence')
        common = {'origin': 'archived_model_submission',
                  'previous_candidate': _candidate_summary(previous),
                  'current_candidate': _candidate_summary(record, rationale=True),
                  'claims': audit['claims'], 'prediction': audit['prediction'],
                  'referenced_parent_evidence': parent_evidence}
        checks = {key: audit[key] for key in ('claim_results', 'registration', 'prediction_result')}
        provenance = {'archive_run': ARCHIVE_RUN, 'archive_session': spec['archive_session'],
                      'archived_candidate_id': spec['archived_candidate_id'],
                      'archive_runtime_commit': ARCHIVE_COMMIT,
                      'source_files': list(spec['files'].values()),
                      'seed_policy': 'Forced repair of archived child; historical selection is not resumed.',
                      'candidate_executions_during_load': 0,
                      'source_role': 'Existing model-proposed development artifact; not a new or held-out task.'}
        states.append({'state_id': spec['state_id'], 'family': family, 'source': source,
                       'n_params': record['n_params'], 'record': copy.deepcopy(record),
                       'diagnostics': copy.deepcopy(diagnostics),
                       'historical_common': copy.deepcopy(common),
                       'historical_checks': copy.deepcopy(checks),
                       'provenance': copy.deepcopy(provenance)})
    return states
