#!/usr/bin/env python3
"""Offline, retrospective edit-claim audit. Never run candidates or call a model."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path, PurePosixPath
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from rsi_eval.decision_cases import load_cases
from rsi_eval.edit_consistency import inspect_edit, assess_claim
from scripts.analyze_decision_replay import audit as audit_replay

ARCHIVE = 'artifacts/decision-replay/2026-10-21/v01'
CONFIG = 'configs/analysis/edit-consistency-v0.1.json'
PROTOCOL = 'docs/protocols/2026-10-21-edit-consistency-v0.1.md'
MANIFEST_SHA256 = '0b32ada07fbc53761ba85a11dd521595a80d4befeebb138cad2d434eb35dc705'
CONFIG_SHA256 = 'ddcd36f7e9ce15f0ea720419a19e045de51dd9de538227b8bf87b73f8e74f422'
TREE_SHA256 = '065029305dd3434661889d3f508f56b94af3c89f7d790c1630cc489ff1166dd5'
SOURCE_FILES = [CONFIG, PROTOCOL, 'rsi_eval/edit_consistency.py',
                'scripts/analyze_edit_consistency.py', 'tests/test_edit_consistency.py',
                'tests/test_edit_consistency_audit.py']


def require(ok, message):
    if not ok:
        raise ValueError(message)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def read_json(path):
    return json.loads(path.read_bytes().decode('utf-8'))


def checked_path(root, relative):
    require(type(relative) is str and '\\' not in relative, 'Invalid evidence path')
    pure = PurePosixPath(relative)
    require(not pure.is_absolute() and '..' not in pure.parts and ':' not in relative,
            'Path outside audit root')
    root = Path(root).resolve()
    result = root.joinpath(*pure.parts)
    require(result.resolve().is_relative_to(root), 'Symlink outside audit root')
    return result


def verify_archive(root):
    archive = checked_path(root, ARCHIVE)
    manifest_raw = (archive / 'manifest.json').read_bytes()
    require(digest(manifest_raw) == MANIFEST_SHA256, 'Archive manifest hash mismatch')
    manifest = json.loads(manifest_raw)
    files = manifest['raw_files']
    require(len(files) == manifest['raw_file_count'] == 303, 'Archive cardinality')
    tree = digest(json.dumps(files, sort_keys=True, separators=(',', ':')).encode())
    require(tree == manifest['raw_tree_sha256'] == TREE_SHA256, 'Archive tree mismatch')
    for name, expected in files.items():
        require(digest(checked_path(archive, name).read_bytes()) == expected,
                'Archive raw file mismatch: ' + name)
    actual = {p.relative_to(archive).as_posix() for p in archive.rglob('*') if p.is_file()}
    require(actual == set(files) | {'manifest.json', 'README.md'}, 'Unexpected archive files')
    return manifest


def check_evidence(root, evidence, session_id):
    relative = ARCHIVE + '/sessions/' + session_id + '/candidate.json'
    require(evidence.get('file') == relative, 'Evidence file/session mismatch')
    raw = checked_path(root, relative).read_bytes()
    require(digest(raw) == evidence.get('file_sha256'), 'Evidence file hash mismatch')
    pointer = evidence.get('json_pointer')
    require(pointer in {'/rationale', '/auxiliary/forecast_basis', '/auxiliary/notes',
                        '/auxiliary/probe_hypothesis'}, 'Unregistered annotation field')
    text = json.loads(raw)
    for part in pointer.split('/')[1:]:
        require(type(text) is dict and part in text, 'Annotation field absent')
        text = text[part]
    require(type(text) is str, 'Annotation field must be original text')
    start, end, quote = (evidence.get(k) for k in
                         ('start_character', 'end_character_exclusive', 'quote'))
    require(type(start) is int and type(end) is int and type(quote) is str
            and 0 <= start < end <= len(text) and text[start:end] == quote
            and text.count(quote) == 1, 'Evidence quote/character span mismatch')
    return quote


def check_annotation(root, row, case, candidate):
    require(row.get('annotation_origin') == 'manual_retrospective_review', 'Annotation origin')
    require(type(row.get('explicit_bytes_claim')) is bool, 'Byte claim marker')
    require(type(row.get('n_params_claimed_at_submission')) is int
            and row['n_params_claimed_at_submission'] == candidate['n_params'], 'Parameter annotation')
    check_evidence(root, row['main_claim']['evidence'], row['session_id'])
    for item in row['separate_unvalidated_statements']:
        check_evidence(root, item['evidence'], row['session_id'])
    kind = row['main_claim']['kind']
    require(kind in {'keep_ast', 'apply_format_patch', 'remove_selected_term',
                     'not_stated', 'outside_supported_contract'}, 'Unregistered annotation kind')
    if kind == 'remove_selected_term':
        target = row['main_claim']['target']
        require(case['family'] == 'symbolic' and target == {
            'parameter_index': case['remove_param_index'],
            'basis': {'S-x5': 'x**5', 'S-v3': 'v**3'}[case['id']],
            'original_n_params': case['n_params'],
            'result_n_params': case['parent_n_params']}, 'Removal annotation target mismatch')
    if kind == 'apply_format_patch':
        require(case['family'] == 'planning' and row['main_claim']['target'] == {
            'function': '_fmt', 'allowed_transform': 'ascii_inner_edge_whitespace_only',
            'outside_target_ast_unchanged': True}, 'Format annotation target mismatch')


def deployment_verdict(root, kind, pins):
    """Apply a human-audited fact about a pinned runtime, not program synthesis."""
    freeze = read_json(Path(root) / ARCHIVE / 'runtime-freeze.json')['runtime_files_sha256']
    expected = {p: freeze[p] for p in
                ('rsi_eval/executor.py', 'rsi_eval/planning.py', 'rsi_eval/planning_probe.py')}
    require(pins == expected, 'Deployment contract pins differ from historical runtime')
    for path, sha in pins.items():
        require(digest(checked_path(root, path).read_bytes()) == sha, 'Deployment runtime changed')
    if kind != 'final_host_normalization':
        return {'status': 'unknown', 'reason': 'no_registered_deployment_contract'}
    return {'status': 'contradicted',
            'reason': 'final_syntax_gate_precedes_token_normalization;probe_copy_repair_not_deployed',
            'basis': 'manually_audited_hash_pinned_runtime_contract',
            'scope': 'This runtime only; not a general proof about execution hosts.'}


def analyze(root=ROOT):
    root = Path(root).resolve()
    manifest = verify_archive(root)
    raw = (root / CONFIG).read_bytes()
    require(digest(raw) == CONFIG_SHA256, 'Annotation config hash mismatch')
    config = json.loads(raw)
    # Reuse the previous source/request/evaluation binding audit, never an evaluator.
    previous = audit_replay(root, root / ARCHIVE)
    cases = {c['id']: c for c in load_cases(root)}
    summary = read_json(root / ARCHIVE / 'summary.json')
    annotations = config['rows']
    require([r['session_id'] for r in annotations] == [s['session_id'] for s in summary['revisions']],
            'All sixteen annotations must follow the frozen run order')
    rows = []
    for annotation, slot in zip(annotations, summary['revisions']):
        case = cases[slot['case_id']]
        directory = root / ARCHIVE / 'sessions' / slot['session_id']
        candidate = read_json(directory / 'candidate.json')
        check_annotation(root, annotation, case, candidate)
        source = (directory / 'candidate.py').read_bytes().decode('utf-8')
        inspection = inspect_edit(case, source, candidate['n_params'])
        main = annotation['main_claim']
        separate = annotation['separate_unvalidated_statements']
        assumptions = [{'evidence': s['evidence'], 'verdict': deployment_verdict(
            root, s['kind'], config['deployment_contract']['runtime_files_sha256'])}
            for s in separate if s['kind'] == 'final_host_normalization']
        rows.append({
            'session_id': slot['session_id'], 'case_id': slot['case_id'],
            'condition': slot['condition'], 'repeat': slot['repeat'],
            'annotation_origin': 'manual_retrospective_review', 'inspection': inspection,
            'main_claim': {**main, 'verdict': assess_claim(inspection, main['kind'])},
            'explicit_bytes_claim': assess_claim(inspection, 'keep_bytes')
                if annotation['explicit_bytes_claim'] else None,
            'deployment_assumptions': assumptions,
            'unvalidated_statements': [s for s in separate if s['kind'] != 'final_host_normalization'],
            'archived_outcome': {'source_sha256': candidate['source_sha256'],
                'score': candidate['score'], 'old_edit_label_unchanged': candidate['edit'],
                'record_file': f'{ARCHIVE}/sessions/{slot["session_id"]}/candidate.json',
                'error_kinds': dict(Counter(r.get('error_kind') for r in candidate['results']
                                          if r.get('error_kind'))),
                'provenance': 'copied_from_hash_pinned_records;bindings_reaudited;not_reexecuted'}})
    return {
        'version': 'edit-consistency-offline-v0.1', 'status': 'completed',
        'annotation_origin': 'manual_retrospective_review',
        'source_files_sha256': {p: digest((root / p).read_bytes()) for p in SOURCE_FILES},
        'historical_archive': {'path': ARCHIVE, 'manifest_sha256': MANIFEST_SHA256,
            'raw_file_count': manifest['raw_file_count'], 'raw_tree_sha256': TREE_SHA256,
            'runtime_commit': manifest['runtime_commit'], 'binding_audit_status': previous['status']},
        'new_activity': dict(model_calls=0, candidate_executions=0, task_evaluations=0,
                             probe_executions=0, strategy_updates=0, model_weight_updates=0),
        'main_claim_counts': dict(Counter(r['main_claim']['verdict']['status'] for r in rows)),
        'explicit_bytes_claim_counts': dict(Counter(r['explicit_bytes_claim']['status'] for r in rows
                                                   if r['explicit_bytes_claim'] is not None)),
        'rows': rows,
        'limitations': ['retrospective_annotations_not_model_structured_claims',
            'hand_selected_development_cases_not_independent_evaluation',
            'supported_narrow_edit_does_not_certify_full_rationale_or_utility',
            'AST_identity_not_general_semantic_equivalence',
            'no_new_candidate_execution_or_raw_prediction_metric_recomputation',
            'no_learned_policy_update_or_generalization_claim']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    report = analyze()
    output = Path(args.output).resolve()
    archive = (ROOT / 'artifacts').resolve()
    require(not output.is_relative_to(archive), 'Do not write inside historical archives')
    encoded = (json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode()
    if output.exists():
        require(output.read_bytes() == encoded, 'Refusing to replace differing report')
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(encoded)
    print(json.dumps({k: report[k] for k in
        ('status', 'main_claim_counts', 'explicit_bytes_claim_counts', 'new_activity')}, indent=2))


if __name__ == '__main__':
    main()
