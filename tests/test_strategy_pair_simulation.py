import importlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

try:
    sim=importlib.import_module('rsi_eval.strategy_pair_simulation')
except ModuleNotFoundError as error:
    if error.name!='rsi_eval.strategy_pair_simulation':
        raise
    sim=None
ROOT=Path(__file__).resolve().parents[1]


class SimulationTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(sim,'Explicit no-execution simulation fixture missing')

    def test_factory_never_calls_candidate_or_reads_data_files(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'tmp') as directory:
            factory=sim.SyntheticExecutorFactory(Path(directory).relative_to(ROOT).as_posix())
            with patch('rsi_eval.role_executor.run_candidate',side_effect=AssertionError('real execution')), \
                 patch('rsi_eval.role_executor.RoleExecutor.prepare_task',side_effect=AssertionError('real task read')):
                value=factory(ROOT,role='learning').evaluate('planning','spannerlearning/seed0/problem0','def get_plan(a,b,c): return []\n')
            self.assertEqual(value['evidence_kind'],'synthetic')
            self.assertEqual(value['synthetic_observation_only'],True)
            self.assertEqual(factory.calls,1)
            self.assertEqual(json.loads((ROOT/value['journal_path']).read_bytes()),value)

    def test_role_and_production_gate_are_rejected_before_record_creation(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'tmp') as directory:
            factory=sim.SyntheticExecutorFactory(Path(directory).relative_to(ROOT).as_posix())
            with self.assertRaises(ValueError):
                factory(ROOT,role='evaluation',evaluation_gate=object())
            with self.assertRaises(ValueError):
                factory(ROOT,role='selection').evaluate('planning','spannerlearning/seed0/problem0','x')
            self.assertEqual(factory.calls,0)


if __name__=='__main__':
    unittest.main()
