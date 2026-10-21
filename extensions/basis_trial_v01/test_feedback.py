import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from extensions.symbolic_basis_v01.contract import make_spec
from extensions.symbolic_basis_v01.executor import canonical, sha
from extensions.basis_trial_v01.feedback import evaluate, load_task


SPEC = make_spec(2, 4)
PAYLOAD = {'feature_ids': ['m_1_1', 'm_0_0', 'm_1_0', 'm_0_1'],
           'explanation': 'Synthetic test fixture only.'}


def prepared():
    return {'request': {'family': 'symbolic', 'task_id': 'oscillator1',
                       'input_names': ['x', 'v'],
                       'X': [[-2., 0.], [-1., 1.], [1., 0.], [2., 1.]],
                       'y': [1., 2., 3., 4.]},
            'provenance': {'partition_sha256': 'a'*64, 'data_sha256': 'b'*64,
                           'domain_sha256': None, 'metric_scope': 'train'}}


def fake_runner(predictions=None, failure=False):
    def run(source, request):
        if request['phase'] == 'fit':
            if failure:
                return {'status': 'completed', 'result': {'status': 'candidate_error'}}
            return {'status': 'completed', 'result': {'status': 'success',
                    'params': [1., 2., 3., 4.], 'converged': True,
                    'nfev': 2, 'candidate_calls': 7,
                    'diagnostics': {'optimizer_invocations': 1}}}
        if 'y' in request:
            raise AssertionError('Prediction received targets')
        return {'status': 'completed', 'result': {'status': 'success',
                'predictions': predictions if predictions is not None else [2., 3., 4., 5.]}}
    return run


class FeedbackTests(unittest.TestCase):
    def test_uses_existing_learning_role_and_fixed_task(self):
        with patch('extensions.basis_trial_v01.feedback.RoleExecutor') as cls:
            cls.return_value.prepare_task.return_value = prepared()
            task = load_task(Path('repo'))
        cls.assert_called_once_with(Path('repo'), role='learning')
        cls.return_value.prepare_task.assert_called_once_with('symbolic', 'oscillator1')
        self.assertEqual(task, prepared())

    def test_feedback_binds_coefficients_and_exact_bounded_diagnostics(self):
        data = prepared()
        unchanged = copy.deepcopy(data)
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)/'one'
            result = evaluate(Path(tmp), output, PAYLOAD, SPEC,
                              prepared=data, runner=fake_runner())
            feedback = json.loads((output/'feedback.json').read_bytes())
            receipt = json.loads((output/'receipt.json').read_bytes())
            self.assertEqual(feedback, result['feedback'])
            self.assertEqual(receipt, result)
            self.assertEqual(result['feedback_sha256'], sha((output/'feedback.json').read_bytes()))
            self.assertEqual(feedback['bindings']['result_sha256'], sha((output/'result.json').read_bytes()))
            self.assertEqual(feedback['bindings']['prediction_sha256'], sha((output/'predict.json').read_bytes()))
        self.assertEqual(data, unchanged)
        self.assertEqual(feedback['nmse'], .8)
        self.assertEqual(feedback['residuals']['bias'], 1.)
        self.assertEqual(feedback['residuals']['rmse'], 1.)
        self.assertAlmostEqual(feedback['residuals']['standardized_bias'], 1/(1.25**.5))
        self.assertEqual([entry['feature_id'] for entry in feedback['coefficients']],
                         ['m_0_0', 'm_0_1', 'm_1_0', 'm_1_1'])
        self.assertEqual([entry['value'] for entry in feedback['coefficients']], [1., 2., 3., 4.])
        self.assertEqual(feedback['provenance'], data['provenance'])
        self.assertLess(len(canonical(feedback)), 10000)
        def inspect(value):
            if isinstance(value, dict):
                self.assertFalse({'X', 'y', 'predictions', 'individual_residuals'} & set(value))
                for item in value.values(): inspect(item)
            elif isinstance(value, list):
                for item in value: inspect(item)
        inspect(feedback)

    def test_prepared_data_reused_without_another_load(self):
        with tempfile.TemporaryDirectory() as tmp, patch('extensions.basis_trial_v01.feedback.load_task') as loader:
            evaluate(Path(tmp), Path(tmp)/'one', PAYLOAD, SPEC,
                     prepared=prepared(), runner=fake_runner())
        loader.assert_not_called()

    def test_invalid_payload_before_data_read_or_output(self):
        with tempfile.TemporaryDirectory() as tmp, patch('extensions.basis_trial_v01.feedback.load_task') as loader:
            output=Path(tmp)/'one'
            with self.assertRaises(ValueError):
                evaluate(Path(tmp), output, dict(PAYLOAD, feature_ids=['bad']), SPEC)
            self.assertFalse(output.exists())
        loader.assert_not_called()

    def test_wrong_task_or_hash_rejected_before_execution(self):
        changes = [('task', 'oscillator2'), ('scope', 'test'), ('data_hash', 'bad')]
        for field, value in changes:
            task=prepared()
            if field=='task': task['request']['task_id']=value
            elif field=='scope': task['provenance']['metric_scope']=value
            else: task['provenance']['data_sha256']=value
            with self.subTest(field=field), tempfile.TemporaryDirectory() as tmp:
                output=Path(tmp)/'one'
                with self.assertRaises(ValueError):
                    evaluate(Path(tmp), output, PAYLOAD, SPEC, prepared=task,
                             runner=lambda *args: self.fail('runner called'))
                self.assertFalse(output.exists())

    def test_trial_restricts_k_and_dimensions(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                evaluate(Path(tmp),Path(tmp)/'one',PAYLOAD,make_spec(2,3),prepared=prepared())

    def test_parent_swap_binding(self):
        child=dict(PAYLOAD, feature_ids=['m_0_0','m_0_1','m_1_0','m_2_0'])
        with tempfile.TemporaryDirectory() as tmp:
            result=evaluate(Path(tmp),Path(tmp)/'one',child,SPEC,
                            parent={'payload': PAYLOAD,'spec': SPEC},
                            prepared=prepared(),runner=fake_runner())
        self.assertEqual(result['transition']['observed_change'],'swap_one')
        self.assertEqual(result['feedback']['transition'],result['transition'])

    def test_multiple_swap_before_read_or_output(self):
        child=dict(PAYLOAD, feature_ids=['m_0_0','m_0_1','m_2_0','m_0_2'])
        with tempfile.TemporaryDirectory() as tmp, patch('extensions.basis_trial_v01.feedback.load_task') as loader:
            output=Path(tmp)/'one'
            with self.assertRaises(ValueError):
                evaluate(Path(tmp),output,child,SPEC,parent={'payload':PAYLOAD,'spec':SPEC})
            self.assertFalse(output.exists())
        loader.assert_not_called()

    def test_fit_failure_has_no_residuals_or_coefficients(self):
        with tempfile.TemporaryDirectory() as tmp:
            result=evaluate(Path(tmp),Path(tmp)/'one',PAYLOAD,SPEC,
                            prepared=prepared(),runner=fake_runner(failure=True))
        self.assertEqual(result['status'],'fit_failed')
        self.assertEqual(result['sandbox_calls'],1)
        self.assertIsNone(result['feedback']['residuals'])
        self.assertIsNone(result['feedback']['nmse'])
        self.assertEqual(result['feedback']['coefficients'],[])
        self.assertIsNone(result['feedback']['bindings']['prediction_sha256'])

    def test_constant_target_preserves_unavailable_metric(self):
        task=prepared(); task['request']['y']=[2.,2.,2.,2.]
        with tempfile.TemporaryDirectory() as tmp:
            result=evaluate(Path(tmp),Path(tmp)/'one',PAYLOAD,SPEC,
                            prepared=task,runner=fake_runner([2.,2.,2.,2.]))
        self.assertEqual(result['status'],'metric_unavailable')
        self.assertIsNone(result['feedback']['nmse'])
        self.assertEqual(result['feedback']['residuals']['standardized_bias_reason'],'zero_target_variance')

    def test_output_once_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            output=Path(tmp)/'one'
            evaluate(Path(tmp),output,PAYLOAD,SPEC,prepared=prepared(),runner=fake_runner())
            with self.assertRaises(FileExistsError):
                evaluate(Path(tmp),output,PAYLOAD,SPEC,prepared=prepared(),
                         runner=lambda *args:self.fail('runner called twice'))


if __name__ == '__main__': unittest.main()
