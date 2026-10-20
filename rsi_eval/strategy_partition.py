"""Frozen future task roles, independent of all existing evaluator permissions.

Metadata verification reads only two pinned source inventories. Optional data
verification hashes official training files and normalizes training PDDL names;
it never opens official tests or decodes symbolic CSV values.
"""
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re

VERSION = 'strategy-partition-v0.1'
SOURCE_HASHES = {
    'configs/tasks/planning-spanner-v0.1.json':
        '4ff1d95f4c0350564115e42d3dbf342bf7e7c65842bcdd088d2d415942200010',
    'configs/tasks/downloads-v0.1.json':
        '6f538df7320ecb74732bf7ed9b88cabde77e7223f45cb24faec1e80ee1249ba8',
}


def _root(root):
    root = Path(root).absolute()
    for path in (root, *root.parents):
        if path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction()):
            raise ValueError('symlink or junction root is refused')
    return root.resolve()


def safe_path(root, relative):
    """Reject traversal and symlinks before opening any path component."""
    root = _root(root)
    relative = Path(relative)
    if relative.is_absolute():
        try:
            relative = relative.relative_to(root)
        except ValueError as exc:
            raise ValueError('path outside project root') from exc
    if not relative.parts or '..' in relative.parts:
        raise ValueError('path traversal or empty path')
    target = root
    for part in relative.parts:
        if ':' in part or '\\' in part:
            raise ValueError('invalid path component')
        target = target / part
        if target.is_symlink() or (hasattr(target, 'is_junction') and target.is_junction()):
            raise ValueError('symlink or junction path is refused')
    target.resolve().relative_to(root)
    return target


def _strict_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON key')
        result[key] = value
    return result


def read_json(root, relative):
    raw = safe_path(root, relative).read_bytes()
    return json.loads(raw.decode('utf-8'), object_pairs_hook=_strict_object,
                      parse_constant=lambda value: (_ for _ in ()).throw(
                          ValueError('nonfinite JSON constant')))


def _sources(root):
    documents = []
    for relative, digest in SOURCE_HASHES.items():
        raw = safe_path(root, relative).read_bytes()
        if hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError('pinned source inventory hash mismatch: ' + relative)
        documents.append(json.loads(raw.decode('utf-8'), object_pairs_hook=_strict_object))
    return documents


def _task_order(task_id):
    match = re.fullmatch(r'(spannerlearning(?:_test)?)/seed([0-9])/problem([0-9]+)', task_id)
    if match is None:
        raise ValueError('unexpected planning identity')
    return (match[1] != 'spannerlearning', int(match[2]), int(match[3]))


def build_manifest(root):
    """Build the deterministic non-executable role inventory from pinned inputs."""
    planning, downloads = _sources(root)
    groups = planning['static_audit']['all_seed_train_duplicate_groups']
    representatives = {}
    group_hashes = {}
    for group in groups:
        representative = min(group['task_ids'], key=_task_order)
        for task_id in group['task_ids']:
            representatives[task_id] = representative
            group_hashes[task_id] = group['problem_name_normalized_sha256']
    tasks = []
    for item in sorted(planning['tasks'], key=lambda item: _task_order(item['id'])):
        task_id = item['id']
        if item['official_subset'] == 'official_test':
            role = 'sealed'
        elif representatives.get(task_id, task_id) != task_id:
            role = 'duplicate_excluded'
        else:
            role = ('learning' if item['seed'] == 0 else
                    'selection' if item['seed'] in (1, 2) else 'evaluation')
        relative = item['upstream_path'].removeprefix('llm_genplan/envs/assets/pddl/pg3/')
        representative = representatives.get(task_id)
        tasks.append({
            'task_id': task_id, 'official_subset': item['official_subset'],
            'original_pilot_role': item['pilot_role'], 'role': role,
            'sha256': item['sha256'], 'data_path': 'data/planning/spanner/' + relative,
            'duplicate_of': representative if representative != task_id else None,
            'normalized_duplicate_sha256': group_hashes.get(task_id),
            'exposure': ('model_and_manual_development' if item['seed'] == 0
                         and item['official_subset'] == 'official_train'
                         else 'inventory_integrity_only'),
        })
    roles = {'oscillator1': 'learning', 'oscillator2': 'selection',
             'bactgrow': 'evaluation', 'stressstrain': 'evaluation'}
    exposures = {'oscillator1': 'model_and_manual_development',
                 'oscillator2': 'manual_installation_scored',
                 'bactgrow': 'integrity_only_no_candidate_execution_found',
                 'stressstrain': 'integrity_only_no_candidate_execution_found'}
    files = []
    for item in sorted(downloads['symbolic']['files'], key=lambda item: item['relative_path']):
        task_id, filename = item['relative_path'].split('/')
        split = filename.removesuffix('.csv')
        files.append({'task_id': task_id, 'split': split,
                      'role': roles[task_id] if split == 'train' else 'sealed',
                      'sha256': item['sha256'], 'bytes': item['size'], 'rows': item['rows'],
                      'columns': item['columns'],
                      'data_path': 'data/symbolic/llm-sr/' + item['relative_path']})
    return {
        'schema_version': '0.1', 'version': VERSION,
        'status': 'frozen_role_preparation_not_execution_protocol',
        'execution_authorized': False,
        'sources': [{'path': path, 'sha256': digest} for path, digest in SOURCE_HASHES.items()],
        'planning': {'source': planning['upstream'], 'domain_sha256': planning['domain']['sha256'],
                     'role_rule': 'Numeric seed/problem order; keep first normalized-text duplicate. '
                                  'Seed0 learning, seeds1-2 selection, seeds3-9 evaluation; all official_test sealed.',
                     'normalized_duplicate_groups': groups, 'tasks': tasks},
        'symbolic': {'source': {'name': 'LLM-SR', 'commit': next(
            item['commit'] for item in downloads['sources'] if item['name'] == 'LLM-SR')},
            'equations': [{'task_id': task_id, 'role': role, 'exposure': exposures[task_id],
                           'model_candidate_evaluation_found': task_id == 'oscillator1'}
                          for task_id, role in roles.items()], 'files': files},
        'boundaries': {
            'existing_evaluator_permissions_changed': False,
            'new_program_states_generated': False,
            'semantic_or_graph_isomorphism_deduplication': False,
            'independent_domains': 1, 'symbolic_equation_tasks': 4,
            'row_level_independence_claimed': False,
            'new_state_generation_and_execution_protocol': 'not_frozen',
            'evaluation_train_nmse': 'Within-task fitting; not held-out prediction generalization.',
            'exposure_evidence_date': '2026-10-21',
            'exposure_evidence_scope': 'Archived research records and executor_feedback task identities; '
                                       'absence of discovered candidate execution is not universal proof of non-exposure.',
        },
    }


def _verified_data(root, relative, expected):
    raw = safe_path(root, relative).read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError('training data hash mismatch: ' + relative)
    return raw


def _check_normalized_groups(training_bytes, expected_groups):
    buckets = defaultdict(list)
    for task_id, raw in training_bytes.items():
        text = raw.decode('utf-8')
        normalized, replaced = re.subn(r'\(problem\s+[^\s()]+\)', '(problem NAME)', text,
                                       count=1, flags=re.IGNORECASE)
        if replaced != 1:
            raise ValueError('training problem header missing')
        buckets[hashlib.sha256(normalized.encode('utf-8')).hexdigest()].append(task_id)
    actual = {digest: sorted(ids) for digest, ids in buckets.items() if len(ids) > 1}
    expected = {group['problem_name_normalized_sha256']: sorted(group['task_ids'])
                for group in expected_groups}
    if actual != expected:
        raise ValueError('normalized training duplicate groups mismatch')
    return len(actual)


def validate_manifest(root, document, verify_data=False):
    """Verify exact frozen roles; optionally hash only official training files."""
    if type(verify_data) is not bool:
        raise ValueError('verify_data must be boolean')
    expected = build_manifest(root)
    # Canonical JSON preserves type differences such as true versus 1. Exact
    # comparison also prevents unknown fields from weakening the fixed policy.
    try:
        serialized = json.dumps(document, sort_keys=True, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError('manifest is not finite JSON') from exc
    if serialized != json.dumps(expected, sort_keys=True, ensure_ascii=False, allow_nan=False):
        raise ValueError('manifest differs from frozen roles, source hashes, schema or coverage')
    counts = dict(Counter(item['role'] for item in document['planning']['tasks']))
    report = {
        'status': 'passed', 'version': VERSION,
        'mode': 'training_file_integrity' if verify_data else 'metadata_only',
        'execution_authorized': False,
        'manifest_sha256': hashlib.sha256(serialized.encode('utf-8')).hexdigest(),
        'sources': document['sources'], 'planning_counts': counts,
        'symbolic_equation_counts': dict(Counter(
            item['role'] for item in document['symbolic']['equations'])),
        'sealed_symbolic_files': sum(item['role'] == 'sealed' for item in document['symbolic']['files']),
        'data_verification': {'planning_train_files': 0, 'symbolic_train_files': 0,
                              'normalized_duplicate_groups': None, 'sealed_files_opened': 0,
                              'symbolic_values_decoded': False},
        'model_requests': 0, 'candidate_executions': 0, 'strategy_updates': 0,
        'sealed_tasks_executed': 0, 'limitations': document['boundaries'],
    }
    if verify_data:
        train_bytes = {}
        for item in document['planning']['tasks']:
            if item['official_subset'] != 'official_train':
                continue
            train_bytes[item['task_id']] = _verified_data(root, item['data_path'], item['sha256'])
        groups = _check_normalized_groups(train_bytes, document['planning']['normalized_duplicate_groups'])
        symbolic_count = 0
        for item in document['symbolic']['files']:
            if item['split'] != 'train':
                continue
            raw = _verified_data(root, item['data_path'], item['sha256'])
            if len(raw) != item['bytes']:
                raise ValueError('symbolic training byte count mismatch')
            symbolic_count += 1
        report['data_verification'].update(planning_train_files=len(train_bytes),
                                            symbolic_train_files=symbolic_count,
                                            normalized_duplicate_groups=groups)
    return report


def write_json(root, path, document):
    """Create exact JSON once; identical repeat is harmless, replacement refused."""
    path = safe_path(root, path)
    data = (json.dumps(document, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8')
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError('refusing to overwrite different output')
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation avoids replacing a file created concurrently.
    with path.open('xb') as stream:
        stream.write(data)
