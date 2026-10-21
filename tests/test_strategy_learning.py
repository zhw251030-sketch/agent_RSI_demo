"""Learning preparation must retain the whole old cohort and exclude new states."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from rsi_eval import strategy_learning as sl
from rsi_eval.revision_policy import S0

ROOT = Path(__file__).resolve().parents[1]


class LearningPackageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.package = sl.build_learning_package(ROOT)

    def test_full_old_cohorts_and_roles(self):
        visible = self.package['model_visible']
        self.assertEqual(len(visible['transitions']), 24)
        self.assertEqual({x['case_id'] for x in visible['states']},
                         {'P-format', 'P-empty', 'S-v3', 'S-x5'})
        self.assertEqual({x['task_id'] for s in visible['states']
                          for x in visible['outcome_tables'][s['baseline_table']]},
                         {'oscillator1'} | {f'spannerlearning/seed0/problem{i}' for i in range(10)})
        self.assertEqual(sum(x['goal_rule']['decision'] == 'promote'
                             for x in visible['transitions']), 4)
        self.assertEqual(self.package['activity'], {
            'model_requests': 0, 'candidate_executions': 0, 'task_data_reads': 0,
            'probe_executions': 0, 'strategy_updates': 0})

    def test_all_sources_are_exact_hash_bound(self):
        visible = self.package['model_visible']
        sources = visible['sources']
        for digest, text in sources.items():
            self.assertEqual(hashlib.sha256(text.encode()).hexdigest(), digest)
        for case in visible['states']:
            self.assertIn(case['source_sha256'], sources)
        for row in visible['transitions']:
            self.assertIn(row['source_sha256'], sources)
            base = next(s for s in visible['states'] if s['case_id'] == row['case_id'])
            self.assertIn(base['source_sha256'], sources)

    def test_new_archive_and_data_files_not_opened(self):
        original = Path.open
        def guarded(path, *args, **kwargs):
            relative = path.as_posix()
            forbidden = ('/data/', '/state-generation/', 'source-notes', 'auth.json')
            self.assertFalse(any(term in relative for term in forbidden), relative)
            return original(path, *args, **kwargs)
        with patch.object(Path, 'open', guarded):
            self.assertEqual(sl.build_learning_package(ROOT), self.package)

    def test_update_has_no_arm_identity_or_host_provenance(self):
        packet = sl.render_update_packet(ROOT, self.package)
        self.assertEqual(packet['parent_policy']['rule_ids'], S0['rule_ids'])
        self.assertEqual(len(packet['catalog']), 8)
        self.assertNotIn('provenance', packet)
        self.assertNotIn('arm', packet)
        self.assertNotIn('replicate', packet)
        self.assertLessEqual(len(sl.canonical(packet)), 81920)
        self.assertEqual(packet, sl.render_update_packet(ROOT, self.package))

    def test_tampered_package_rejected(self):
        bad = copy.deepcopy(self.package)
        bad['model_visible']['transitions'].pop()
        with self.assertRaises(ValueError):
            sl.render_update_packet(ROOT, bad)

    def test_changing_hash_bound_archive_rejected(self):
        original = Path.read_bytes
        def changed(path):
            raw = original(path)
            return raw + b' ' if path.name == 'candidate.py' else raw
        with patch.object(Path, 'read_bytes', changed), self.assertRaises(ValueError):
            sl.build_learning_package(ROOT)

    def test_result_projection_keeps_task_status_and_public_diagnostics(self):
        states = {s['case_id']: s for s in self.package['model_visible']['states']}
        tables = self.package['model_visible']['outcome_tables']
        rows = tables[states['P-format']['baseline_table']]
        self.assertEqual(len(rows), 10)
        self.assertIn('plan_replay', rows[0]['diagnostics'])
        self.assertNotIn('trace', rows[0]['diagnostics'])
        self.assertNotIn('diagnostics', rows[2])
        symbolic = tables[states['S-v3']['baseline_table']]
        self.assertEqual(symbolic[0]['metric_split'], 'train')
        self.assertIn('residuals', symbolic[0]['diagnostics'])


class ActorPacketTests(unittest.TestCase):
    def setUp(self):
        source = 'def get_plan(objects, init, goal):\n    return []\n'
        self.context = dict(state_id='P-select-1', family='planning', source=source,
            source_sha256=hashlib.sha256(source.encode()).hexdigest(), n_params=0,
            task_text='Only the supplied task contract.', public_examples=[],
            baseline_feedback=[], objective='Improve task success.')

    def test_only_selected_rule_text_changes(self):
        other = dict(version=S0['version'], rule_ids=['R01', 'R02', 'R05', 'R08'])
        first = sl.render_actor_packet(ROOT, self.context, S0)
        second = sl.render_actor_packet(ROOT, self.context, other)
        self.assertEqual(sl.common_actor_packet(first), sl.common_actor_packet(second))
        self.assertNotEqual(first['repair_policy'], second['repair_policy'])
        self.assertNotIn('available_revision_rules', first)
        self.assertNotIn('experience_memory', first)

    def test_source_hash_is_required(self):
        self.context['source'] += '# modified'
        with self.assertRaises(ValueError):
            sl.render_actor_packet(ROOT, self.context, S0)

    def test_extra_context_is_rejected(self):
        self.context['evaluation_notes'] = 'leaked future information'
        with self.assertRaises(ValueError):
            sl.render_actor_packet(ROOT, self.context, S0)

    def test_invalid_policy_and_nonfinite_feedback_rejected(self):
        with self.assertRaises(ValueError):
            sl.render_actor_packet(ROOT, self.context, {'rule_ids': ['R01']})
        self.context['baseline_feedback'] = [float('nan')]
        with self.assertRaises(ValueError):
            sl.render_actor_packet(ROOT, self.context, S0)

    def test_request_bound_rejects_instead_of_truncates(self):
        self.context['baseline_feedback'] = ['x' * 90000]
        with self.assertRaises(ValueError):
            sl.render_actor_packet(ROOT, self.context, S0)

    def test_unrecognized_state_and_wrong_parameters_rejected(self):
        self.context['state_id'] = 'P-eval-unregistered'
        with self.assertRaises(ValueError):
            sl.render_actor_packet(ROOT, self.context, S0)
        self.context['state_id'] = 'P-select-1'
        self.context['n_params'] = True
        with self.assertRaises(ValueError):
            sl.render_actor_packet(ROOT, self.context, S0)


if __name__ == '__main__':
    unittest.main()
