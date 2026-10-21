import copy,json,tempfile,unittest
from pathlib import Path
try:
    from scripts import run_state_generation_v02 as mod
except ImportError:
    mod=None

ROOT=Path(__file__).resolve().parents[1]

class GenerationV02Tests(unittest.TestCase):
    def test_v02_runner_exists(self):self.assertIsNotNone(mod)

    @unittest.skipIf(mod is None,'v02 runner not implemented')
    def test_timeout_is_only_effective_model_difference(self):
        from scripts.run_checked_feedback import _model_configuration
        budgets=json.loads((ROOT/'configs/pilots/state-generation-v0.1.json').read_text())['budgets']
        before=_model_configuration(ROOT/'configs/models/minimax-m3.json',budgets)
        after=mod.model_configuration(ROOT,budgets)
        self.assertEqual(before[:2],after[:2])
        self.assertEqual({k for k in before[2] if before[2][k]!=after[2][k]},{'timeout'})
        self.assertEqual(after[2]['timeout'],180);self.assertEqual(after[2]['num_retries'],0)

    @unittest.skipIf(mod is None,'v02 runner not implemented')
    def test_batch_rejects_changed_timeout_and_resume(self):
        c=json.loads((ROOT/mod.BATCH_CONFIG).read_text())
        self.assertEqual(mod.validate_batch(c),c)
        for field,value in [('effective_timeout_seconds',181),('resume',True),('whole_new_batch',False),('automatic_retries',1)]:
            bad=copy.deepcopy(c);bad[field]=value
            with self.assertRaises(ValueError):mod.validate_batch(bad)

    @unittest.skipIf(mod is None,'v02 runner not implemented')
    def test_prepare_freezes_complete_new_batch_without_credentials(self):
        from unittest.mock import patch
        from rsi_eval.state_generation import build_inputs
        examples=json.loads((ROOT/'artifacts/state-generation/2026-10-21/v01/input-freeze.json').read_text())['slots'][0]['packet']['examples']
        examples=[dict(family='planning',task_id=f'spannerlearning/seed0/problem{i}',**p) for i,p in enumerate(examples)]
        with tempfile.TemporaryDirectory() as d:
            out=Path(d)/'fresh'
            with patch.object(mod,'new_output',return_value=out),patch.object(mod,'load_public_examples',return_value=examples),patch.object(mod,'runtime_freeze',return_value={'runtime_commit':'a'*40,'checkout_clean':True,'runtime_files_sha256':{}}):
                output,report,inputs,ledger=mod.prepare(ROOT,'fixture',allow_dirty=True)
            self.assertEqual(report['version'],'state-generation-run-v0.2')
            self.assertEqual(ledger.summary()['request_count'],0)
            self.assertEqual(len(report['slots']),8)
            self.assertEqual(inputs,build_inputs(ROOT,examples))
            self.assertEqual(report['effective_model_config']['timeout'],180)
            self.assertTrue((out/'batch-freeze.json').exists())
            self.assertFalse((out/'sessions').exists())

if __name__=='__main__':unittest.main()
