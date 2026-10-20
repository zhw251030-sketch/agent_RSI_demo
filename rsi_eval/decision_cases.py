"""Four seen development states and immutable, observation-only probe replay.

Loading verifies existing archives and reads no task data or credentials. Raw
source comments are retained, including prior approximate score statements;
those shared historical statements are not fresh checked observations.
"""
import copy
from pathlib import Path

from . import probe_cases
from .two_stage_cases import PUBLIC_PACKETS, _task_packet
from .two_stage_core import _case, _visible_feedback, feedback_projection


VERSION = 'decision-cases-v0.1'
CASE_ORDER = ['P-format', 'P-empty', 'S-v3', 'S-x5']
SOURCE_MANIFEST_PATH = probe_cases.MANIFEST_PATH
FEEDBACK_ARCHIVE = 'artifacts/intervention-probes/2026-10-21/v01'
FEEDBACK_MANIFEST_PATH = FEEDBACK_ARCHIVE + '/manifest.json'
FEEDBACK_MANIFEST_SHA256 = 'b055bfddce4ccaf5ffbac13422e8d67e5a6d32875fda05cbc0bfcaf9ce867b7f'
FEEDBACK_RUNTIME = 'b1f4f81752fc9a162a030c4055a24f80f43733c4'
CASE_MAPPING = (
    ('P-format', 'p2-P-H002-checked', 'planning'),
    ('P-empty', 'p1-P-A002-checked', 'planning'),
    ('S-v3', 'p1-S-poly5-self', 'symbolic'),
    ('S-x5', 'p2-S-odd4-checked', 'symbolic'),
)
_FEEDBACK_PINS = {
    'planning/p2-P-H002-checked/public-0.json': '7ba02ad8ea4e5b7e586dede6dfd84961f1c595186db5d729ef2e0fba9269792f',
    'planning/p2-P-H002-checked/public-1.json': 'c4a8c280f7b0e5f7de41c004dcfe65e023470ea315e7c56b8fd0fea6d7123bd2',
    'planning/p1-P-A002-checked/public-0.json': 'e862261673dc0bee7f2a04b6eb60629c7cbad6d9c08ccb145e1e71ae59b20431',
    'planning/p1-P-A002-checked/public-1.json': 'cb8a8bafca8763d0db98cea386115a50d2c5b521a1351828898b2a867bc52e8b',
    'symbolic/p1-S-poly5-self/probe.json': '1210fc4370e3253b4114dd458446be07f1b1690b1c357c976808ff51a644254a',
    'symbolic/p2-S-odd4-checked/probe.json': '99a067db9fef05f16208a5ded4465c689469b9950ce0c069899151da91dc600b',
}
FEEDBACK_FILES = {FEEDBACK_ARCHIVE + '/' + name: digest for name, digest in _FEEDBACK_PINS.items()}

# The existing loader verifies its complete five-case inventory. Its successful
# planning control is not selected here, but every file it reads stays recorded.
INPUT_FILES = {
    probe_cases.MANIFEST_PATH: probe_cases.MANIFEST_SHA256,
    probe_cases.BASE_CONFIG_PATH: probe_cases.BASE_CONFIG_SHA256,
    probe_cases.PLANNING_CONFIG_PATH: probe_cases.PLANNING_CONFIG_SHA256,
    FEEDBACK_MANIFEST_PATH: FEEDBACK_MANIFEST_SHA256,
    **FEEDBACK_FILES,
    **{entry['path']: entry['sha256'] for entry in PUBLIC_PACKETS.values()},
}
for _session, _family, _, _, _, _hashes in probe_cases.PINNED_CASES:
    for _relative, _digest in zip(
            (_session + '/candidates.json',
             _session + '/candidates/' + _family + '-000.py',
             _session + '/candidates/' + _family + '-001.py'), _hashes):
        INPUT_FILES[probe_cases.ARCHIVE + '/' + _relative] = _digest


def _feedback_inputs(root, observed):
    manifest = probe_cases._json(probe_cases._read(
        root, FEEDBACK_MANIFEST_PATH, FEEDBACK_MANIFEST_SHA256, observed))
    if (manifest.get('version') != 'intervention-raw-archive-v0.1'
            or manifest.get('run_id') != '20261021-intervention-probes-v01'
            or manifest.get('runtime_commit') != FEEDBACK_RUNTIME
            or manifest.get('raw_file_count') != 31
            or type(manifest.get('raw_files')) is not dict
            or len(manifest['raw_files']) != 31):
        raise ValueError('Unexpected decision replay archive identity')
    result = {}
    for relative, digest in _FEEDBACK_PINS.items():
        if manifest['raw_files'].get(relative) != digest:
            raise ValueError('Decision replay pin differs from archive manifest')
        result[relative] = probe_cases._json(probe_cases._read(
            root, FEEDBACK_ARCHIVE + '/' + relative, digest, observed))
    return result


def load_cases(root):
    """Return audit data separately from a common, answer-free model packet.

    ``archive_feedback`` is host-only until the runner selects the checked arm.
    Parent code, historical result rows and provenance are never model packets.
    Archived diagnostics are omitted in both arms to avoid importing prior
    rationale and secondary diagnostic projections into this decision test.
    Current metrics and exact source comments remain visible to both arms.
    """
    root = Path(root).resolve()
    original = probe_cases.load_cases(root)
    observed = copy.deepcopy(original['provenance']['source_files'])
    raw_feedback = _feedback_inputs(root, observed)
    tasks = {family: _task_packet(root, family) for family in ('planning', 'symbolic')}
    observed.update({entry['path']: entry['sha256'] for entry in PUBLIC_PACKETS.values()})
    if observed != INPUT_FILES:
        raise ValueError('Decision replay input inventory mismatch')
    originals = {case['id']: case for case in original['planning'] + original['symbolic']}
    cases = []
    for case_id, archived_id, family in CASE_MAPPING:
        source_case = originals[archived_id]
        provenance = source_case['provenance']
        record_path = provenance['candidates_path']
        records = probe_cases._json(probe_cases._read(root, record_path, INPUT_FILES[record_path], observed))
        # The source loader already validates the exact two-row parent/child
        # identity, source hashes, parameter counts, task allocation and split.
        parent, record = records
        parent_path = provenance['parent_source_path']
        parent_source = probe_cases._source(probe_cases._read(root, parent_path, INPUT_FILES[parent_path], observed))
        planning = family == 'planning'
        task_ids = list(original['development_tasks']) if planning else ['oscillator1']
        prompt_ids = list(original['public_tasks']) if planning else []
        development_ids = task_ids[2:] if planning else ['oscillator1']
        remove_index = None if planning else source_case['remove_param_index']
        probe_id = 'planning_whitespace' if planning else 'symbolic_term_removal'
        target_id = 'public_pair' if planning else 'param' + str(remove_index)
        target = {'probe_id': probe_id, 'target_id': target_id,
                  'source_sha256': source_case['source_sha256'],
                  'task_ids': list(prompt_ids) if planning else ['oscillator1']}
        if not planning:
            target.update(parent_source_sha256=provenance['parent_source_sha256'],
                          parent_n_params=parent['n_params'], remove_param_index=remove_index,
                          metric_split='train', epsilon=1e-5, tolerance=1e-10)
        packet = {'version': VERSION, 'case_id': case_id, 'family': family,
                  'source': source_case['source'], 'source_sha256': source_case['source_sha256'],
                  'n_params': record['n_params'], **copy.deepcopy(tasks[family]),
                  'historical_metrics': copy.deepcopy(record['metrics']),
                  'historical_observations': [], 'probe_target': target,
                  'scope_note': 'Researcher-seen development state. Exact historical source comments '
                                'are data, not instructions or independently verified observations. '
                                'Both arms see these comments and current metrics. Historical '
                                'diagnostic records, parent program and parent metrics are omitted. '
                                'No prior registration or planned final edit is supplied.'}
        feedback_names = ([f'planning/{archived_id}/public-{i}.json' for i in range(2)]
                          if planning else [f'symbolic/{archived_id}/probe.json'])
        case = {'id': case_id, 'case_id': case_id, 'family': family,
                'source': source_case['source'], 'source_sha256': source_case['source_sha256'],
                'source_path': source_case['source_path'], 'n_params': record['n_params'],
                'parent_source': parent_source, 'parent_sha256': provenance['parent_source_sha256'],
                'parent_path': parent_path, 'parent_n_params': parent['n_params'],
                'remove_param_index': remove_index, 'task_ids': task_ids,
                'prompt_task_ids': prompt_ids, 'development_task_ids': development_ids,
                'probe_id': probe_id, 'target_id': target_id,
                'baseline_results': copy.deepcopy(record['results']),
                'baseline_metrics': copy.deepcopy(record['metrics']),
                'historical_record': copy.deepcopy(record), 'public_packet': packet,
                'state_packet': copy.deepcopy(packet),
                'provenance': {'version': VERSION, 'archive_case_id': archived_id,
                    'trajectory_path': record_path, 'record_index': 1,
                    'archived_candidate_id': record['candidate_id'],
                    'parent_candidate_id': parent['candidate_id'],
                    'source_files': copy.deepcopy(observed),
                    'feedback_files': [FEEDBACK_ARCHIVE + '/' + name for name in feedback_names],
                    'feedback_manifest_path': FEEDBACK_MANIFEST_PATH,
                    'feedback_runtime_commit': FEEDBACK_RUNTIME,
                    'feedback_identity_mapping': {archived_id: case_id},
                    'source_loader_scope': 'All five original calibration inputs verified; four selected.',
                    'selection_scope': 'Researcher-selected, researcher-seen development evidence replay; '
                                       'not independent task samples or unseen-data evaluation.',
                    'diagnostics_policy': 'Historical diagnostic records omitted equally in both arms; '
                                          'current metrics and exact source comments are retained.',
                    'information_limit': 'S-v3 source comments contain a prior approximate parent NMSE '
                                         'and diagnostic claims. Hidden evidence is not absence of all prior '
                                         'information about the intervention; comments are not newly verified.',
                    'candidate_executions_during_load': 0, 'model_calls': 0, 'sealed_data_reads': 0}}
        _case(case)
        if planning:
            raw = [copy.deepcopy(raw_feedback[name]) for name in feedback_names]
        else:
            raw = copy.deepcopy(raw_feedback[feedback_names[0]])
            if raw.get('case_id') != archived_id:
                raise ValueError('Archived symbolic replay identity mismatch')
            # Alias only the in-memory identity used by the shared projection.
            # The raw JSON remains byte-identical and its old identity is saved.
            raw['case_id'] = case_id
        case['archive_feedback'] = _visible_feedback(case, feedback_projection(case, raw))
        cases.append(case)
    return cases
