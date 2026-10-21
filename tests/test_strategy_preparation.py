"""Readiness must freeze real inputs without executing new research candidates."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.prepare_strategy_pair import build_preparation, write_preparation, verify_preparation

ROOT = Path(__file__).resolve().parents[1]


class PreparationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.prepared = build_preparation(ROOT)

    def test_complete_sources_and_all_future_slots_are_retained_without_scores(self):
        doc = self.prepared['preparation.json']
        self.assertEqual(len(doc['initial_states']), 8)
        self.assertEqual(doc['future_slot_counts'], {'update': 4, 'selection': 16, 'evaluation': 16})
        self.assertFalse(doc['execution_ready'])
        self.assertEqual(doc['activity'], {'model_requests': 0, 'candidate_executions': 0,
                         'task_evaluations': 0, 'strategy_updates': 0, 'sealed_tasks_executed': 0})
        self.assertEqual({st['role'] for st in doc['initial_states']}, {'selection', 'evaluation'})
        self.assertTrue(all('score' not in st and 'baseline_feedback' not in st for st in doc['initial_states']))

    def test_preparation_is_deterministic_without_network_or_candidate_execution(self):
        with patch('socket.socket', side_effect=AssertionError('network forbidden')), \
             patch('rsi_eval.executor.evaluate_candidate', side_effect=AssertionError('execution forbidden')), \
             patch('rsi_eval.sandbox.run_candidate', side_effect=AssertionError('sandbox forbidden')):
            again = build_preparation(ROOT)
        self.assertEqual(again, self.prepared)

    def test_write_is_exclusive_and_tampering_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)/'prepared'
            write_preparation(output, self.prepared)
            report = verify_preparation(ROOT, output)
            self.assertEqual(report['status'], 'passed')
            with self.assertRaises(FileExistsError):
                write_preparation(output, self.prepared)
            target = output/'update-packet.json'
            packet = json.loads(target.read_text(encoding='utf-8'))
            packet['unregistered_hint'] = 'read evaluation notes'
            target.write_text(json.dumps(packet), encoding='utf-8')
            with self.assertRaises(ValueError):
                verify_preparation(ROOT, output)

    def test_unknown_extra_output_is_not_silently_excluded_from_freeze(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)/'prepared'
            write_preparation(output, self.prepared)
            (output/'extra.json').write_text('{}', encoding='utf-8')
            with self.assertRaises(ValueError):
                verify_preparation(ROOT, output)


if __name__ == '__main__':
    unittest.main()
