"""Partition boundaries: no execution authorization and no sealed-data reads."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
AVAILABLE = importlib.util.find_spec('rsi_eval.strategy_partition') is not None
if AVAILABLE:
    from rsi_eval.strategy_partition import build_manifest, validate_manifest, write_json


class Availability(unittest.TestCase):
    def test_partition_implementation_exists(self):
        self.assertTrue(AVAILABLE, 'A separate strategy partition implementation is required')


@unittest.skipUnless(AVAILABLE, 'implementation is not present yet')
class PartitionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for relative in ('configs/tasks/planning-spanner-v0.1.json',
                         'configs/tasks/downloads-v0.1.json'):
            destination = self.root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / relative, destination)
        self.document = build_manifest(self.root)

    def test_counts_and_sealed_roles(self):
        report = validate_manifest(self.root, self.document)
        self.assertEqual(report['planning_counts'], {
            'learning': 10, 'selection': 19, 'evaluation': 63,
            'duplicate_excluded': 8, 'sealed': 300})
        self.assertEqual(report['symbolic_equation_counts'],
                         {'learning': 1, 'selection': 1, 'evaluation': 2})
        self.assertEqual(report['sealed_symbolic_files'], 8)
        self.assertFalse(self.document['execution_authorized'])
        self.assertEqual(report['candidate_executions'], 0)

    def test_oscillator2_exposure_is_not_unseen(self):
        item = next(x for x in self.document['symbolic']['equations']
                    if x['task_id'] == 'oscillator2')
        self.assertEqual(item['role'], 'selection')
        self.assertEqual(item['exposure'], 'manual_installation_scored')
        self.assertFalse(item['model_candidate_evaluation_found'])

    def test_known_duplicates_all_excluded(self):
        items = {x['task_id']: x for x in self.document['planning']['tasks']}
        self.assertEqual(items['spannerlearning/seed1/problem4']['duplicate_of'],
                         'spannerlearning/seed0/problem0')
        self.assertEqual(items['spannerlearning/seed3/problem1']['duplicate_of'],
                         'spannerlearning/seed1/problem8')
        self.assertEqual(items['spannerlearning/seed6/problem5']['role'], 'duplicate_excluded')

    def test_manifest_is_deterministic_and_checked_in_exactly(self):
        self.assertEqual(self.document, build_manifest(self.root))
        saved = json.loads((ROOT / 'configs/tasks/strategy-partition-v0.1.json').read_text())
        self.assertEqual(saved, self.document)

    def test_rejects_role_rewrite_omissions_duplicates_sealed_assignment(self):
        mutations = []
        for name, index, value in [('role', 0, 'evaluation'),
                                   ('sealed', 100, 'selection')]:
            d = copy.deepcopy(self.document)
            d['planning']['tasks'][index]['role'] = value
            mutations.append((name, d))
        d = copy.deepcopy(self.document); d['planning']['tasks'].pop()
        mutations.append(('missing', d))
        d = copy.deepcopy(self.document); d['planning']['tasks'].append(d['planning']['tasks'][0])
        mutations.append(('duplicate', d))
        d = copy.deepcopy(self.document)
        next(x for x in d['planning']['tasks'] if x['role'] == 'duplicate_excluded')['role'] = 'evaluation'
        mutations.append(('cross_role_duplicate', d))
        d = copy.deepcopy(self.document); d['execution_authorized'] = True
        mutations.append(('authorization', d))
        d = copy.deepcopy(self.document); d['schema_version'] = '2'
        mutations.append(('schema', d))
        d = copy.deepcopy(self.document); d['symbolic']['equations'][0]['role'] = 'evaluation'
        mutations.append(('equation_role', d))
        for name, document in mutations:
            with self.subTest(name=name), self.assertRaises(ValueError):
                validate_manifest(self.root, document)

    def test_rejects_source_hash_or_path_rewrite(self):
        for field, value in [('sha256', '0' * 64), ('path', '../outside.json')]:
            d = copy.deepcopy(self.document); d['sources'][0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_manifest(self.root, d)

    def test_changed_source_rejected_even_with_rebound_document_hash(self):
        source = self.root / 'configs/tasks/downloads-v0.1.json'
        source.write_bytes(source.read_bytes() + b'\n')
        d = copy.deepcopy(self.document)
        d['sources'][1]['sha256'] = hashlib.sha256(source.read_bytes()).hexdigest()
        with self.assertRaisesRegex(ValueError, 'source'):
            validate_manifest(self.root, d)

    def test_metadata_mode_never_opens_data(self):
        original = Path.read_bytes
        def guarded(path):
            self.assertNotIn('data', path.relative_to(self.root).parts)
            return original(path)
        with patch.object(Path, 'read_bytes', guarded):
            self.assertEqual(validate_manifest(self.root, self.document)['status'], 'passed')

    def test_data_mode_fails_closed_on_missing_training_file(self):
        with self.assertRaises((ValueError, FileNotFoundError)):
            validate_manifest(self.root, self.document, verify_data=True)

    def test_data_mode_never_opens_sealed_or_decodes_symbolic(self):
        # Mock byte acquisition and digest only: exercise exactly which paths the
        # production verifier requests, without real task data or candidate code.
        import rsi_eval.strategy_partition as module
        files = {}
        for x in self.document['planning']['tasks']:
            if x['official_subset'] == 'official_train':
                files[x['data_path']] = x['sha256']
        for x in self.document['symbolic']['files']:
            if x['split'] == 'train':
                files[x['data_path']] = x['sha256']
        symbolic_sizes = {x['data_path']: x['bytes'] for x in self.document['symbolic']['files']}
        observed = []
        def verify(root, relative, expected):
            self.assertIn(relative, files)
            self.assertEqual(expected, files[relative])
            observed.append(relative)
            return (b'\xff' * symbolic_sizes[relative] if relative.endswith('.csv')
                    else b'(define (problem x))')
        expected_groups = self.document['planning']['normalized_duplicate_groups']
        with patch.object(module, '_verified_data', side_effect=verify), \
             patch.object(module, '_check_normalized_groups', return_value=len(expected_groups)):
            report = validate_manifest(self.root, self.document, verify_data=True)
        self.assertEqual(len(observed), 104)
        self.assertEqual(report['data_verification']['planning_train_files'], 100)
        self.assertEqual(report['data_verification']['symbolic_train_files'], 4)
        self.assertEqual(report['data_verification']['sealed_files_opened'], 0)

    def test_normalization_rejects_unlisted_duplicate_or_wrong_group_hash(self):
        from rsi_eval.strategy_partition import _check_normalized_groups
        raw = {'a': b'(define (problem a))', 'b': b'(define (problem b))'}
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            _check_normalized_groups(raw, [])

    def test_normalization_matches_only_problem_header_changes(self):
        from rsi_eval.strategy_partition import _check_normalized_groups
        raw = {'a': b'(define (problem a))', 'b': b'(define (problem b))'}
        digest = hashlib.sha256(b'(define (problem NAME))').hexdigest()
        expected = [{'problem_name_normalized_sha256': digest, 'task_ids': ['a', 'b']}]
        self.assertEqual(_check_normalized_groups(raw, expected), 1)
        raw['b'] = b'(define (problem b) (:init (extra)))'
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            _check_normalized_groups(raw, expected)

    def test_data_digest_and_data_path_are_checked_before_use(self):
        from rsi_eval.strategy_partition import _verified_data
        path = self.root / 'data/train.csv'
        path.parent.mkdir(); path.write_bytes(b'abc')
        with self.assertRaisesRegex(ValueError, 'hash'):
            _verified_data(self.root, 'data/train.csv', '0' * 64)
        with self.assertRaisesRegex(ValueError, 'traversal'):
            _verified_data(self.root, '../outside.csv', '0' * 64)

    def test_json_duplicate_keys_rejected(self):
        from rsi_eval.strategy_partition import read_json
        (self.root / 'bad.json').write_text('{"role":"sealed","role":"learning"}')
        with self.assertRaisesRegex(ValueError, 'duplicate JSON'):
            read_json(self.root, 'bad.json')

    def test_symlink_source_refused(self):
        source = self.root / 'configs/tasks/downloads-v0.1.json'
        target = self.root / 'source.json'; source.rename(target)
        try:
            source.symlink_to(target)
        except OSError:
            # Windows may lack symlink privilege; still exercise detection.
            original = Path.is_symlink
            with patch.object(Path, 'is_symlink', lambda p: p == source or original(p)):
                with self.assertRaisesRegex(ValueError, 'symlink'):
                    build_manifest(self.root)
        else:
            with self.assertRaisesRegex(ValueError, 'symlink'):
                build_manifest(self.root)

    def test_safe_output_idempotent_but_refuses_replacement(self):
        output = self.root / 'out/report.json'
        write_json(self.root, output, {'a': 1})
        original = output.read_bytes()
        write_json(self.root, output, {'a': 1})
        self.assertEqual(output.read_bytes(), original)
        with self.assertRaisesRegex(ValueError, 'different'):
            write_json(self.root, output, {'a': 2})
        self.assertEqual(output.read_bytes(), original)

    def test_safe_output_refuses_traversal(self):
        with self.assertRaises(ValueError):
            write_json(self.root, '../bad.json', {})

    def test_safe_output_refuses_symlink_parent(self):
        original = Path.is_symlink
        linked = self.root / 'linked'
        with patch.object(Path, 'is_symlink', lambda p: p == linked or original(p)):
            with self.assertRaisesRegex(ValueError, 'symlink'):
                write_json(self.root, 'linked/report.json', {})

    def test_cli_metadata_report(self):
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/check_strategy_partition.py'),
                                 '--root', str(ROOT), '--output', str(ROOT / 'tmp/partition-cli-test.json')],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['status'], 'passed')


if __name__ == '__main__':
    unittest.main()
