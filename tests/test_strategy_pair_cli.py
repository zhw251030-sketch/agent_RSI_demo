import importlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

try:
    cli=importlib.import_module('scripts.run_strategy_pair')
except ModuleNotFoundError as error:
    if error.name!='scripts.run_strategy_pair':
        raise
    cli=None
ROOT=Path(__file__).resolve().parents[1]


class StrategyCliTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(cli,'Bounded strategy CLI missing')

    def test_real_run_requires_certificate_before_credentials_or_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError,'certificate'):
                cli.execute(Path(directory),'blocked',mode='run')
            self.assertEqual(list(Path(directory).iterdir()),[])

    def test_invalid_run_id_or_mode_rejected_before_creation(self):
        with tempfile.TemporaryDirectory() as directory:
            for name,mode in [('../escape','simulate'),('good','unknown')]:
                with self.assertRaises(ValueError):
                    cli.execute(Path(directory),name,mode=mode)
            self.assertEqual(list(Path(directory).iterdir()),[])

    def test_template_context_is_frozen_selection_source_with_no_measurements(self):
        context=cli.template_context(ROOT)
        self.assertEqual(context['state_id'],'P-select-1')
        self.assertEqual(context['baseline_feedback'],[])
        self.assertTrue(context['source'])
        self.assertEqual(context['n_params'],0)

    def test_dispatch_counts_exclude_reserved_but_never_dispatched_slots(self):
        with tempfile.TemporaryDirectory() as directory:
            output=Path(directory)
            pending=output/'experiment/sessions/r1-update'
            pending.mkdir(parents=True)
            (output/'budget-ledger.json').write_text(json.dumps({'requests':[{'status':'reserved'}]}))
            self.assertEqual(cli.dispatch_counts(output),dict(sdk_dispatch_attempts=0,mock_provider_calls=None))
            (pending/'sdk-dispatch.json').write_text('{}')
            self.assertEqual(cli.dispatch_counts(output),dict(sdk_dispatch_attempts=1,mock_provider_calls=None))
            # The mock callable may not have been entered even though its
            # preceding SDK boundary observation was persisted.
            self.assertEqual(cli.dispatch_counts(output,0),dict(sdk_dispatch_attempts=1,mock_provider_calls=0))

    def test_dirty_preflight_cannot_be_promoted_by_adding_readiness_flag(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);run=root/'run';preparation=run/'preparation'
            preparation.mkdir(parents=True)
            cli.prep.write(preparation/'runtime-freeze.json',{'checkout_clean':False})
            manifest_hash=cli.prep.write(run/'run-manifest.json',{'files':cli._file_hashes(run)})
            cli.prep.write(run/'readiness.json',dict(version='strategy-pair-readiness-v0.1',
                execution_ready=True,manifest_sha256=manifest_hash,runtime_sha256='test',
                research_activity=dict(model_requests=0,task_evaluations=0,strategy_updates=0)))
            with patch.object(cli.prep,'verify',return_value={'runtime_sha256':'test'}), \
                    patch('rsi_eval.strategy_pair_audit.audit_run',side_effect=AssertionError('Must reject before audit')):
                with self.assertRaisesRegex(ValueError,'clean'):
                    cli.verify_certificate(root,run/'readiness.json')


if __name__=='__main__':
    unittest.main()
