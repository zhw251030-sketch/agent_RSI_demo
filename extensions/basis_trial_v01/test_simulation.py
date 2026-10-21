from pathlib import Path
import tempfile
import unittest

from extensions.basis_trial_v01.feedback import evaluate
from extensions.basis_trial_v01.simulation import synthetic_runner, synthetic_task
from extensions.symbolic_basis_v01.contract import make_spec


class SimulationTests(unittest.TestCase):
    def test_fake_fit_predict_never_executes_source(self):
        result=synthetic_runner('raise AssertionError("must not execute")',
                                {'phase':'fit','n_params':4})
        self.assertEqual(result['result']['params'],[1.,1.,1.,1.])
        prediction=synthetic_runner('not even valid python',{'phase':'predict','X':[[1.,2.],[2.,3.]]})
        self.assertEqual(prediction['result']['predictions'],[0.,0.])
        with self.assertRaises(ValueError): synthetic_runner('',{'phase':'other'})

    def test_marked_fake_task_and_successful_feedback_path(self):
        task=synthetic_task()
        self.assertEqual(task['provenance']['data_kind'],'synthetic_sdk_preflight')
        task['request']['y'][0]=500
        self.assertNotEqual(synthetic_task()['request']['y'][0],500)
        payload={'feature_ids':['m_0_0','m_0_1','m_1_0','m_1_1'],'explanation':'Simulation only.'}
        with tempfile.TemporaryDirectory() as tmp:
            result=evaluate(Path(tmp),Path(tmp)/'run',payload,make_spec(2,4),
                            prepared=synthetic_task(),runner=synthetic_runner)
        self.assertEqual(result['status'],'success')
        self.assertEqual(result['sandbox_calls'],2)
        self.assertEqual(result['feedback']['provenance']['data_kind'],'synthetic_sdk_preflight')

    def test_marked_task_cannot_enter_live_runner(self):
        payload={'feature_ids':['m_0_0','m_0_1','m_1_0','m_1_1'],'explanation':'Simulation only.'}
        with tempfile.TemporaryDirectory() as tmp:
            output=Path(tmp)/'run'
            with self.assertRaises(ValueError):
                evaluate(Path(tmp),output,payload,make_spec(2,4),prepared=synthetic_task())
            self.assertFalse(output.exists())


if __name__=='__main__': unittest.main()
