"""Frozen repair seeds are verified without credentials, data, or execution."""
import copy
import hashlib
import importlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch


PROJECT = Path(__file__).resolve().parents[1]
CONFIG = 'configs/pilots/paired-repair-v0.1.json'


class RepairStateTests(unittest.TestCase):
    def setUp(self):
        self.loader = importlib.import_module('rsi_eval.repair_states')
        self.config = json.loads((PROJECT/CONFIG).read_text(encoding='utf-8'))

    def copy_inputs(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        for name in [CONFIG] + [f['path'] for s in self.config['states'] for f in s['files'].values()]:
            target = root/name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(PROJECT/name, target)
        return root

    def altered_archive(self, state_id, kind, mutate):
        """Repin inside this test only to exercise semantic checks after hashing."""
        root = self.copy_inputs()
        specs = copy.deepcopy(self.loader.PINNED_STATES)
        spec = next(s for s in specs if s['state_id'] == state_id)
        entry = spec['files'][kind]
        path = root/entry['path']
        value = json.loads(path.read_text(encoding='utf-8'))
        mutate(value)
        path.write_text(json.dumps(value), encoding='utf-8')
        entry['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
        config = copy.deepcopy(self.config)
        config['states'] = specs
        (root/CONFIG).write_text(json.dumps(config), encoding='utf-8')
        return root, specs

    def test_loads_two_real_unsolved_states_and_preserves_original_identity(self):
        with patch('socket.socket', side_effect=AssertionError('No network permitted')):
            states = self.loader.load_repair_states(PROJECT)
        self.assertEqual([s['state_id'] for s in states], ['P1', 'S1'])
        p, s = states
        self.assertEqual(p['record']['candidate_id'], 'planning-001')
        self.assertFalse(p['record']['selection']['accepted'])
        self.assertEqual(p['record']['selection']['incumbent_id'], 'planning-000')
        self.assertEqual(p['record']['metrics']['total_successes'], 0)
        self.assertEqual(s['record']['candidate_id'], 'symbolic-002')
        self.assertAlmostEqual(s['record']['metrics']['nmse'], 0.09639217003192727)
        self.assertEqual(s['n_params'], 3)
        for state in states:
            self.assertEqual(hashlib.sha256(state['source'].encode()).hexdigest(),
                             state['record']['source_sha256'])
            self.assertEqual(state['historical_checks']['prediction_result']['status'], 'contradicted')
            self.assertEqual(state['provenance']['candidate_executions_during_load'], 0)

    def test_historical_common_does_not_leak_checker_outcomes_or_repair_bad_claims(self):
        for state in self.loader.load_repair_states(PROJECT):
            common = state['historical_common']
            serialized = json.dumps(common)
            for forbidden in ['claim_results', 'prediction_result', 'schema_invalid', 'contradicted', 'registration']:
                self.assertNotIn(forbidden, serialized)
            self.assertTrue(common['referenced_parent_evidence'])
        symbolic = self.loader.load_repair_states(PROJECT)[1]
        for claim in symbolic['historical_common']['claims']:
            self.assertNotIn('session_id', claim['reference'])
        self.assertEqual(symbolic['historical_checks']['claim_results'][0]['reason'], 'reference_schema_invalid')

    def test_every_load_returns_independent_clones(self):
        states = self.loader.load_repair_states(PROJECT)
        original = copy.deepcopy(states)
        states[0]['record']['metrics']['total_successes'] = 99
        states[0]['diagnostics'][0]['plan_replay']['plan_length'] = 99
        states[1]['historical_common']['claims'][0]['reference']['session_id'] = 'repaired'
        states[1]['historical_checks']['prediction_result']['status'] = 'supported'
        self.assertEqual(self.loader.load_repair_states(PROJECT), original)
        self.assertNotIn('session_id', original[1]['historical_common']['claims'][0]['reference'])

    def test_raw_byte_tampering_in_each_of_ten_inputs_is_rejected(self):
        for state in self.config['states']:
            for kind, entry in state['files'].items():
                with self.subTest(state=state['state_id'], kind=kind):
                    root = self.copy_inputs()
                    with (root/entry['path']).open('ab') as stream:
                        stream.write(b' ')
                    with self.assertRaisesRegex(ValueError, 'hash'):
                        self.loader.load_repair_states(root)

    def test_editing_config_hash_cannot_repin_the_frozen_source(self):
        root = self.copy_inputs()
        config = copy.deepcopy(self.config)
        entry = config['states'][0]['files']['source']
        (root/entry['path']).write_text('def get_plan(*args): return []\n', encoding='utf-8')
        entry['sha256'] = hashlib.sha256((root/entry['path']).read_bytes()).hexdigest()
        (root/CONFIG).write_text(json.dumps(config), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'pinned'):
            self.loader.load_repair_states(root)

    def test_missing_source_is_rejected_without_fallback(self):
        root = self.copy_inputs()
        (root/self.config['states'][1]['files']['source']['path']).unlink()
        with self.assertRaises((ValueError, FileNotFoundError)):
            self.loader.load_repair_states(root)

    def test_incomplete_parent_record_is_rejected_even_with_valid_file_hash(self):
        root, specs = self.altered_archive('P1', 'trajectory', lambda rows: rows[1].update(status='infrastructure_error'))
        with patch.object(self.loader, 'PINNED_STATES', specs), self.assertRaisesRegex(ValueError, 'complete'):
            self.loader.load_repair_states(root)

    def test_task_order_or_metric_mismatch_is_rejected(self):
        for mutation in [lambda rows: rows[1]['results'].reverse(),
                         lambda rows: rows[1]['metrics'].update(total_successes=1)]:
            root, specs = self.altered_archive('P1', 'trajectory', mutation)
            with patch.object(self.loader, 'PINNED_STATES', specs), self.assertRaises(ValueError):
                self.loader.load_repair_states(root)

    def test_symbolic_result_metrics_must_match_record(self):
        root, specs = self.altered_archive('S1', 'trajectory',
            lambda rows: rows[2]['results'][0]['metrics'].update(nmse=0.5))
        with patch.object(self.loader, 'PINNED_STATES', specs), self.assertRaisesRegex(ValueError, 'metric'):
            self.loader.load_repair_states(root)

    def test_diagnostics_cannot_reference_other_source_or_sealed_task(self):
        for mutation in [lambda d: d['planning-001'][0].update(candidate_sha256='0'*64),
                         lambda d: d['planning-001'][0].update(task_id='spannerlearning/seed0/problem99')]:
            root, specs = self.altered_archive('P1', 'diagnostics', mutation)
            with patch.object(self.loader, 'PINNED_STATES', specs), self.assertRaises(ValueError):
                self.loader.load_repair_states(root)

    def test_evidence_requires_exact_binding_and_matching_metric(self):
        for mutation in [lambda e: e['symbolic-002'][0]['binding'].update(candidate_id='symbolic-003'),
                         lambda e: e['symbolic-002'][0]['scalars'].update(nmse=0.5)]:
            root, specs = self.altered_archive('S1', 'evidence', mutation)
            with patch.object(self.loader, 'PINNED_STATES', specs), self.assertRaises(ValueError):
                self.loader.load_repair_states(root)

    def test_recorded_check_outcome_cannot_be_changed_to_success(self):
        root, specs = self.altered_archive('S1', 'audits',
            lambda a: a[1]['prediction_result'].update(status='supported'))
        with patch.object(self.loader, 'PINNED_STATES', specs), self.assertRaisesRegex(ValueError, 'audit'):
            self.loader.load_repair_states(root)

    def test_frozen_order_has_two_balanced_repeats_and_one_request_per_session(self):
        order = self.config['order']
        self.assertEqual(len(order), 8)
        for state in ['P1', 'S1']:
            for repeat in [1, 2]:
                pair = [x for x in order if x['state_id'] == state and x['repeat'] == repeat]
                self.assertEqual({x['condition'] for x in pair}, {'hidden', 'checked'})
                self.assertEqual({x['pair_id'] for x in pair}, {state+'-r'+str(repeat)})
        first = [(x['state_id'], x['condition']) for x in order[:4]]
        second = [(x['state_id'], x['condition']) for x in order[4:]]
        self.assertEqual(second, first[::-1])
        self.assertEqual(self.config['budgets']['max_requests_per_session'], 1)
        self.assertEqual(self.config['budgets']['max_requests'], 8)
        self.assertEqual(self.config['max_generated_candidates'], 1)
        self.assertFalse(self.config['automatic_recovery'])


if __name__ == '__main__':
    unittest.main()
