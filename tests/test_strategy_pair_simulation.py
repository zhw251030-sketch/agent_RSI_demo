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

    @unittest.skipUnless(importlib.util.find_spec('litellm'), 'SDK provider dependency unavailable')
    def test_provider_covers_advertised_optional_metadata_in_both_phases(self):
        slots=json.loads((ROOT/'configs/pilots/strategy-pair-allocation-v0.1.json').read_bytes())['slots']
        provider=sim.SyntheticProvider(slots)
        seen={'update':set(),'actor':set()}
        for index,slot in enumerate(slots):
            packet={'current_state':{'source':'def get_plan(a,b,c): return []\n','n_params':0}}
            response=provider(messages=[dict(role='user',content=json.dumps(packet))])
            args=json.loads(response.choices[0].message.tool_calls[0].function.arguments)
            expected=({'summary','security_risk'},{'summary'},{'security_risk'},set())[index%4]
            actual=set(args)&{'summary','security_risk'}
            self.assertEqual(actual,expected)
            if 'security_risk' in args:
                self.assertEqual(args['security_risk'],'UNKNOWN')
            if 'summary' in args:
                if index%4==1:
                    self.assertIsNone(args['summary'])
                else:
                    self.assertIsInstance(args['summary'],str)
            seen['update' if slot['phase']=='update' else 'actor'].add(tuple(sorted(actual)))
        self.assertEqual(provider.calls,36)
        self.assertEqual(len(seen['update']),4)
        self.assertEqual(len(seen['actor']),4)


if __name__=='__main__':
    unittest.main()
