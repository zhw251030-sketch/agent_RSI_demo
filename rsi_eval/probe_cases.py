"""Load five pinned probe inputs without evaluating candidates or reading data.

Historical scores are deliberately omitted. Source strings decode exact UTF-8
bytes: no newline normalization or automatic repair occurs in this loader.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath


VERSION = 'probe-cases-v0.1'
ARCHIVE = 'artifacts/inference-policy/2026-10-20/v01'
MANIFEST_PATH = ARCHIVE + '/manifest.json'
MANIFEST_SHA256 = 'acdc6cee32c7379ec84592267cd052a12855d56f315fcdc953b3ded8edd897d2'
RUNTIME_COMMIT = '568f833eebffb4505e87903029ace9eb5f9e0b78'
BASE_CONFIG_PATH = ARCHIVE + '/base-config.json'
BASE_CONFIG_SHA256 = '8e2576f6a297f6d26180d6c438c40431fafa740739d04126145a0e979aeac2f3'
PLANNING_CONFIG_PATH = 'configs/tasks/planning-spanner-v0.1.json'
PLANNING_CONFIG_SHA256 = '4ff1d95f4c0350564115e42d3dbf342bf7e7c65842bcdd088d2d415942200010'

# The hashes below were checked against the separately pinned archive manifest
# before being introduced. Each tuple is records, parent source, child source.
PINNED_CASES = (
    ('p2-P-H002-checked', 'planning', 0, 0, None, (
        'e60f723bd8f4a63b535ee68f91a8382331931510857ac7ee675c4b7d388ab07d',
        'deb8420baf4bacc6de52068de9844363bb60edf7e9bc6cf5d4753d14c853aca3',
        '954089736b47434d9f2a334a34856c6f4dc5e3b887d98fb48eb8dee2754897fc')),
    ('p1-P-A002-checked', 'planning', 3, 3, None, (
        'd50d8bf494c609ca9b2cee55522ccb76d1d583a934d443a804e61e93ddeb4262',
        '67372060d92e060efd36035c230fcea51d20ac484ee585ee52fda416127132f4',
        '67c3d2fd9ae6a55fb885f5e1518d8e22e5ac90294555e99f9cd1067227874d41')),
    ('p2-P-H002-self', 'planning', 0, 0, None, (
        'd3d5af2c4489104adec31d6a4364ef3f519e9a6efd14b215c687f90c73effa29',
        'deb8420baf4bacc6de52068de9844363bb60edf7e9bc6cf5d4753d14c853aca3',
        '22be60362fe59ac66a11403b97bd9cf0a93b0c9e7c3b2bbeb9b306aafc71948e')),
    ('p1-S-poly5-self', 'symbolic', 5, 6, 5, (
        'eef5454ff0a2ff32e65397ccfde7d3008fa36d2d44759c4a33ad77d76a2cd792',
        'a4eca8e167987cb3dece02024c8d281eafb2bef179da7f82e55dfb9fa4900dd0',
        'd6019099a4c1f3680336f7d6eb0f25941b9c1e906c3a15ad884f2dafdcf57881')),
    ('p2-S-odd4-checked', 'symbolic', 4, 5, 4, (
        'a58cd416b649db6962e919a9d41f7df8917a436370bb04976957e4cd80c8b43c',
        'f3c893f0989dc6a72029687090cd1e3c444eca24e8643740a0a62dddd21d801e',
        '6f51ad2198bedb7b8079921f77c8feb81e1c677febff6fa3654671ea80f1235e')),
)


def _json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('Duplicate JSON key in probe input')
            result[key] = value
        return result

    def invalid_constant(value):
        raise ValueError('Nonfinite JSON in probe input')

    try:
        return json.loads(raw.decode('utf-8'), object_pairs_hook=pairs,
                          parse_constant=invalid_constant)
    except (UnicodeError, TypeError, RecursionError) as exc:
        raise ValueError('Invalid probe JSON input') from exc


def _read(root, relative, expected_sha256, observed):
    pure = PurePosixPath(relative)
    if pure.is_absolute() or '..' in pure.parts or str(pure) != relative:
        raise ValueError('Invalid pinned probe path')
    path = root
    for part in pure.parts:
        path = path / part
        if path.is_symlink():
            raise ValueError('Symlink in pinned probe input')
    try:
        if not path.is_file() or not 0 < path.stat().st_size <= 2_000_000:
            raise ValueError('Missing or oversized pinned probe input')
        raw = path.read_bytes()
    except OSError as exc:
        raise ValueError('Unreadable pinned probe input') from exc
    actual = hashlib.sha256(raw).hexdigest()
    if actual != expected_sha256:
        raise ValueError('Pinned probe input hash mismatch: ' + relative)
    observed[relative] = actual
    return raw


def _source(raw):
    if len(raw) > 65536:
        raise ValueError('Pinned probe source exceeds candidate limit')
    try:
        source = raw.decode('utf-8')
    except UnicodeError as exc:
        raise ValueError('Pinned probe source is not UTF-8') from exc
    if source.encode('utf-8') != raw:
        raise ValueError('Probe source byte preservation failed')
    return source


def _scope(base, planning_config):
    sessions = base.get('sessions')
    if type(sessions) is not list or len(sessions) != 2:
        raise ValueError('Unexpected archived task sessions')
    p, s = sessions
    public = [f'spannerlearning/seed0/problem{i}' for i in range(2)]
    development = [f'spannerlearning/seed0/problem{i}' for i in range(2, 10)]
    all_tasks = public + development
    if (p.get('family') != 'planning' or p.get('source_manifest') != PLANNING_CONFIG_PATH
            or p.get('prompt_task_ids') != public or p.get('development_task_ids') != development
            or p.get('task_ids') != all_tasks or s.get('family') != 'symbolic'
            or s.get('metric_split') != 'train' or s.get('task_ids') != ['oscillator1']):
        raise ValueError('Probe task scope differs from original development allocation')
    tasks = planning_config.get('tasks')
    if type(tasks) is not list or any(type(task) is not dict for task in tasks):
        raise ValueError('Invalid pinned planning task manifest')
    selected = [task for task in tasks if task.get('pilot_role') in ('prompt', 'development_feedback')]
    if [task.get('id') for task in selected] != all_tasks:
        raise ValueError('Planning manifest has a different allowed task set')
    for task in selected:
        expected_role = 'prompt' if task['id'] in public else 'development_feedback'
        if (task.get('pilot_role') != expected_role or task.get('seed') != 0
                or task.get('official_subset') != 'official_train'):
            raise ValueError('Planning manifest scope is not the development subset')
    return public, all_tasks


def load_cases(root):
    """Return pinned source-only inputs, not historical or newly measured scores.

    ``development_tasks`` is the complete original 10-task allocation, including
    the two prompt tasks. No PDDL, CSV, sealed task, credential or runtime is read.
    """
    root = Path(root).resolve()
    observed = {}
    manifest = _json(_read(root, MANIFEST_PATH, MANIFEST_SHA256, observed))
    if (type(manifest) is not dict or manifest.get('version') != 'inference-policy-archive-v0.1'
            or manifest.get('runtime_commit') != RUNTIME_COMMIT
            or manifest.get('source_run') != 'runs/inference-policy/20261020-inference-policy-v01'
            or manifest.get('name_mapping') is not None
            or manifest.get('raw_file_count') != 230 or type(manifest.get('raw_files')) is not dict
            or len(manifest['raw_files']) != 230):
        raise ValueError('Unexpected pinned probe archive identity')

    def archived(relative, expected):
        if manifest['raw_files'].get(relative) != expected:
            raise ValueError('Probe pin differs from archive manifest')
        return _read(root, ARCHIVE + '/' + relative, expected, observed)

    base = _json(archived('base-config.json', BASE_CONFIG_SHA256))
    planning_config = _json(_read(root, PLANNING_CONFIG_PATH, PLANNING_CONFIG_SHA256, observed))
    public, all_tasks = _scope(base, planning_config)
    output = {'version': VERSION, 'planning': [], 'symbolic': [],
              'public_tasks': public, 'development_tasks': all_tasks}
    for session, family, parent_params, child_params, remove_index, hashes in PINNED_CASES:
        relative_records = session + '/candidates.json'
        relative_parent = session + '/candidates/' + family + '-000.py'
        relative_source = session + '/candidates/' + family + '-001.py'
        records = _json(archived(relative_records, hashes[0]))
        parent_source = _source(archived(relative_parent, hashes[1]))
        source = _source(archived(relative_source, hashes[2]))
        if type(records) is not list or len(records) != 2:
            raise ValueError('Probe archive requires exactly one parent-child transition')
        task_ids = all_tasks if family == 'planning' else ['oscillator1']
        for index, (record, expected_params, source_hash) in enumerate(
                zip(records, (parent_params, child_params), hashes[1:])):
            expected_id = family + '-00' + str(index)
            parent_id = None if index == 0 else family + '-000'
            origin = 'archived_model_proposed_initial' if index == 0 else 'model_proposed'
            # This original pilot record predates feedback_role. Its pinned
            # trajectory still binds oscillator1/train; do not rewrite history.
            feedback_role = (None if session == 'p2-S-odd4-checked' and index == 0
                             else 'development_only')
            if (type(record) is not dict or record.get('candidate_id') != expected_id
                    or record.get('parent_id') != parent_id or record.get('origin') != origin
                    or record.get('source_sha256') != source_hash
                    or type(record.get('n_params')) is not int or record['n_params'] != expected_params
                    or record.get('feedback_role') != feedback_role
                    or record.get('status') != 'evaluated'
                    or type(record.get('results')) is not list
                    or [row.get('task_id') for row in record['results']] != task_ids):
                raise ValueError('Probe candidate identity, parameters, or data scope differs')
            if family == 'symbolic' and record.get('metric_split') != 'train':
                raise ValueError('Probe symbolic record is not training scope')
        case = {'id': session, 'family': family, 'source': source,
                'source_sha256': hashes[2], 'source_path': ARCHIVE + '/' + relative_source,
                'provenance': {'archive_session': session, 'runtime_commit': RUNTIME_COMMIT,
                    'candidate_id': family + '-001', 'parent_candidate_id': family + '-000',
                    'candidates_path': ARCHIVE + '/' + relative_records,
                    'candidates_sha256': hashes[0],
                    'parent_source_path': ARCHIVE + '/' + relative_parent,
                    'parent_source_sha256': hashes[1],
                    'selection_scope': 'Researcher-seen development calibration; historical scores omitted.'}}
        if family == 'planning':
            case['task_ids'] = list(public)
        else:
            if remove_index != child_params - 1 or parent_params != child_params - 1:
                raise ValueError('Probe symbolic removal identity is inconsistent')
            case.update(parent_source=parent_source, parent_sha256=hashes[1],
                        parent_path=ARCHIVE + '/' + relative_parent, n_params=child_params,
                        parent_n_params=parent_params, remove_param_index=remove_index,
                        task_id='oscillator1', scope='train')
        output[family].append(case)
    output['provenance'] = {'archive_manifest_path': MANIFEST_PATH,
        'archive_manifest_sha256': MANIFEST_SHA256, 'runtime_commit': RUNTIME_COMMIT,
        'planning_config_path': PLANNING_CONFIG_PATH, 'planning_config_sha256': PLANNING_CONFIG_SHA256,
        'base_config_path': BASE_CONFIG_PATH, 'base_config_sha256': BASE_CONFIG_SHA256,
        'source_files': observed, 'candidate_executions': 0, 'model_calls': 0,
        'sealed_data_reads': 0}
    return output
