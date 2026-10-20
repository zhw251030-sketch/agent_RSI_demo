"""Expanded repair states preserve original evidence and exclude future history."""
import copy
import hashlib
import importlib
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch


PROJECT = Path(__file__).resolve().parents[1]


class GroundedStateTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('rsi_eval.grounded_states'))
        self.loader = importlib.import_module('rsi_eval.grounded_states')

    def copy_inputs(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        for spec in self.loader.PINNED_STATES.values():
            for entry in spec['files'].values():
                target = root / entry['path']
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(PROJECT / entry['path'], target)
        return root

    def changed(self, state_id, kind, mutate):
        root = self.copy_inputs()
        specs = copy.deepcopy(self.loader.PINNED_STATES)
        entry = specs[state_id]['files'][kind]
        path = root / entry['path']
        value = json.loads(path.read_text(encoding='utf-8'))
        mutate(value)
        path.write_text(json.dumps(value), encoding='utf-8')
        entry['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
        return root, specs

    def reject_changed(self, state_id, kind, mutate):
        root, specs = self.changed(state_id, kind, mutate)
        with patch.object(self.loader, 'PINNED_STATES', specs), self.assertRaises(ValueError):
            self.loader.load_grounded_states(root)

    def test_four_states_load_without_execution_network_or_history(self):
        with (patch('subprocess.run', side_effect=AssertionError('No execution')),
              patch('socket.socket', side_effect=AssertionError('No network'))):
            states = self.loader.load_grounded_states(PROJECT)
        self.assertEqual([s['state_id'] for s in states], ['P-A002', 'P-B002', 'S-poly5', 'S-odd4'])
        self.assertEqual([s['n_params'] for s in states], [3, 3, 5, 4])
        self.assertEqual(states[0]['diagnostics'][0]['plan_replay']['executed_actions'], 0)
        self.assertEqual(states[1]['diagnostics'][0]['plan_replay']['executed_actions'], 7)
        self.assertEqual(states[2]['record']['metrics']['nmse'], 0.09376229967010528)
        self.assertEqual(states[3]['record']['metrics']['nmse'], 0.09180470524756017)
        for state in states:
            self.assertEqual(set(state), {'state_id', 'family', 'source', 'n_params', 'record',
                'diagnostics', 'historical_common', 'historical_checks', 'provenance'})
            self.assertEqual(state['historical_common'], {})
            self.assertEqual(state['historical_checks'], {})
            self.assertEqual(state['provenance']['candidate_executions_during_load'], 0)
            self.assertEqual(hashlib.sha256(state['source'].encode()).hexdigest(),
                             state['record']['source_sha256'])
            self.assertNotIn('later_records', json.dumps(state))

    def test_pilot_diagnostic_is_identified_as_later_replay_not_original_run(self):
        state = self.loader.load_grounded_states(PROJECT)[3]
        replay = state['record']['results'][0]
        self.assertEqual(replay['run_id'], 'd6c079a6fc3341b6ae87b1d59b61c754')
        self.assertEqual(state['provenance']['original_evaluator_run_ids'],
                         ['a8019bf73a40470f9d61dd196b2e0821'])
        self.assertEqual(replay['fitting']['n_params'], 4)
        self.assertEqual(state['diagnostics'], [replay['diagnostics']])
        self.assertIn('replay', state['provenance']['record_assembly'])

    def test_outputs_are_independent_copies(self):
        baseline = self.loader.load_grounded_states(PROJECT)
        altered = self.loader.load_grounded_states(PROJECT)
        altered[0]['record']['metrics']['total_successes'] = 10
        altered[3]['diagnostics'][0]['residuals']['bias'] = 123
        altered[1]['provenance']['source_files'][0]['sha256'] = '0' * 64
        self.assertEqual(self.loader.load_grounded_states(PROJECT), baseline)

    def test_every_pinned_file_rejects_byte_tampering(self):
        paths = {entry['path'] for spec in self.loader.PINNED_STATES.values()
                 for entry in spec['files'].values()}
        for name in paths:
            with self.subTest(path=name):
                root = self.copy_inputs()
                with (root / name).open('ab') as stream:
                    stream.write(b' ')
                with self.assertRaisesRegex(ValueError, 'hash'):
                    self.loader.load_grounded_states(root)

    def test_missing_duplicate_wrong_candidate_and_reordered_tasks_rejected(self):
        mutations = [lambda rows: rows.pop(2),
                     lambda rows: rows.append(copy.deepcopy(rows[2])),
                     lambda rows: rows[2].update(candidate_id='planning-999'),
                     lambda rows: rows[2]['results'].reverse(),
                     lambda rows: rows[2]['results'].pop()]
        for mutate in mutations:
            self.reject_changed('P-A002', 'trajectory', mutate)

    def test_record_parameter_count_and_pinned_metrics_verified(self):
        for mutate in [lambda rows: rows[3].update(n_params=4),
                       lambda rows: rows[3]['metrics'].update(nmse=0.5),
                       lambda rows: rows[3]['results'][0]['metrics'].update(mse=0.5)]:
            self.reject_changed('S-poly5', 'trajectory', mutate)

    def test_diagnostic_binding_scope_and_plan_length_verified(self):
        for mutate in [lambda d: d['planning-002'][0].update(candidate_sha256='0'*64),
                       lambda d: d['planning-002'][0].update(scope='sealed'),
                       lambda d: d['planning-002'][0].update(task_id='spannerlearning/seed0/problem9'),
                       lambda d: d['planning-002'][0]['plan_replay'].update(plan_length=8),
                       lambda d: d['planning-002'].reverse()]:
            self.reject_changed('P-B002', 'diagnostics', mutate)

    def test_pilot_curated_record_cannot_silently_select_another_candidate(self):
        for mutate in [lambda d: d['session_outcomes'][1]['trajectory'][3].update(candidate_id='symbolic-002'),
                       lambda d: d['session_outcomes'][1]['trajectory'][3].update(n_params=3),
                       lambda d: d['session_outcomes'][1]['trajectory'][3]['metrics'].update(nmse=0.1)]:
            self.reject_changed('S-odd4', 'record', mutate)

    def test_pilot_replay_must_match_original_identity_fit_score_and_scope(self):
        for mutate in [lambda d: d.update(candidate_hash='0'*64),
                       lambda d: d.update(candidate_id='symbolic-002'),
                       lambda d: d.update(metric_split='test'),
                       lambda d: d.update(status='task_failure'),
                       lambda d: d['fitting'].update(n_params=3),
                       lambda d: d['fitting'].update(split='test'),
                       lambda d: d['fitting']['params'].__setitem__(0, float('inf')),
                       lambda d: d.update(parent_id='symbolic-002'),
                       lambda d: d['metrics'].update(nmse=0.1),
                       lambda d: d['diagnostics']['residuals'].update(rmse=0.1)]:
            self.reject_changed('S-odd4', 'feedback', mutate)

    def test_pilot_replay_diagnostic_cannot_change_scope_or_candidate(self):
        for mutate in [lambda d: d['diagnostics'].update(candidate_sha256='0'*64),
                       lambda d: d['diagnostics'].update(scope='test'),
                       lambda d: d['diagnostics']['residuals'].update(n=9999)]:
            self.reject_changed('S-odd4', 'feedback', mutate)

    def test_source_must_still_match_record_when_file_digest_is_repinned(self):
        root = self.copy_inputs()
        specs = copy.deepcopy(self.loader.PINNED_STATES)
        entry = specs['P-A002']['files']['source']
        path = root / entry['path']
        path.write_bytes(path.read_bytes() + b'\n# changed\n')
        entry['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
        with patch.object(self.loader, 'PINNED_STATES', specs), self.assertRaises(ValueError):
            self.loader.load_grounded_states(root)

    def test_paths_cannot_escape_root_even_with_correct_external_hash(self):
        root = self.copy_inputs()
        outside = root.parent / (root.name + '-outside.py')
        outside.write_text('pass\n', encoding='utf-8')
        self.addCleanup(outside.unlink)
        for name in [str(outside), '../' + outside.name]:
            specs = copy.deepcopy(self.loader.PINNED_STATES)
            specs['P-A002']['files']['source'] = {
                'path': name, 'sha256': hashlib.sha256(outside.read_bytes()).hexdigest()}
            with patch.object(self.loader, 'PINNED_STATES', specs), self.assertRaises(ValueError):
                self.loader.load_grounded_states(root)

    def test_nonfinite_archive_json_is_rejected(self):
        self.reject_changed('S-poly5', 'trajectory',
                            lambda rows: rows[3]['metrics'].update(mse=float('nan')))

    def test_reads_only_pinned_inputs_and_never_reaches_task_data(self):
        read_bytes = Path.read_bytes
        allowed = {(PROJECT / entry['path']).resolve() for spec in self.loader.PINNED_STATES.values()
                   for entry in spec['files'].values()}
        seen = set()

        def checked(path):
            self.assertIn(path.resolve(), allowed)
            seen.add(path.resolve())
            return read_bytes(path)

        with patch.object(Path, 'read_bytes', checked):
            self.loader.load_grounded_states(PROJECT)
        self.assertEqual(seen, allowed)


if __name__ == '__main__':
    unittest.main()
