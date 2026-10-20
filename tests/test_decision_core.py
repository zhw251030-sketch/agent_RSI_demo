"""Decision boundaries without candidate execution, datasets or model calls."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from tests.test_two_stage_core import case, plan_probe, sha
from rsi_eval import decision_core as core
from rsi_eval.two_stage_core import feedback_projection


class DecisionCoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def controller(self, c=None, feedback=None, evaluator=None, name='run'):
        return core.DecisionController(c or case(), feedback, self.root,
                                       self.root/name, evaluator=evaluator)

    def test_packets_need_no_registration_and_only_feedback_differs(self):
        c = case(); c['archive_feedback'] = {'private': 'NOT_VISIBLE'}
        a = self.controller(c, name='a').task_packet()
        b = self.controller(c, feedback_projection(c, plan_probe(c)), name='b').task_packet()
        self.assertNotIn('registration', a)
        self.assertNotIn('planned_edit', json.dumps(a))
        self.assertNotIn('NOT_VISIBLE', json.dumps(a))
        self.assertIn('Keeping the starting artifact unchanged is legal', a['decision_contract'])
        a.pop('probe_feedback'); b.pop('probe_feedback'); self.assertEqual(a, b)

    def test_parent_solution_and_old_edit_hints_are_not_replayed(self):
        c = case('symbolic')
        c['public_packet']['probe_target'] = {'parent_source': 'REMOVE_THIS_SOLUTION',
            'parent_source_sha256': c['parent_sha256'], 'remove_param_index': 2}
        packet = self.controller(c).task_packet()
        self.assertNotIn('REMOVE_THIS_SOLUTION', json.dumps(packet))
        self.assertEqual(packet['probe_target']['remove_param_index'], 2)
        self.assertIn('does not support adding', packet['decision_contract'])

    def test_state_packet_and_task_prompt_are_current_packet(self):
        c = self.controller()
        self.assertEqual(c.state_packet(), c.task_packet())
        self.assertEqual(json.loads(c.task_prompt()), c.task_packet())
        self.assertEqual(c.task_packet()['auxiliary_contract']['forecast_example'],
                         {'development_successes': 0})

    def test_retain_is_accepted_without_counting_as_improvement(self):
        c = case('symbolic'); calls = []
        def evaluator(family, task_id, source, **kwargs):
            calls.append(kwargs)
            return {'task_id': task_id, 'status': 'success', 'candidate_hash': sha(source),
                    'metrics': {'nmse': .1}, 'executions': [{'phase': 'fit'}, {'phase': 'predict'}]}
        controller = self.controller(c, evaluator=evaluator)
        result = controller.submit('s', c['source'], 3, 'Retain.', {'forecast': {'nmse': .1}})
        self.assertEqual(result['status'], 'evaluated')
        self.assertEqual(result['edit']['kind'], 'unchanged')
        self.assertIs(result['score']['meaningful_improvement'], False)
        self.assertIs(result['score']['acceptable_simplification'], False)
        self.assertIs(result['score']['degraded'], False)
        self.assertEqual(calls[0]['strategy_version'], 'decision-replay-v0.1')
        self.assertEqual(result['forecast']['absolute_error'], 0)
        self.assertEqual(controller.submit('s', c['source'], 3)['status'], 'budget_exhausted')

    def test_planning_executes_exact_scope_and_counts_public_separately(self):
        c = case(); calls = []
        def evaluator(family, task_id, source, **kwargs):
            calls.append(task_id)
            return {'task_id': task_id, 'status': 'success' if task_id.endswith('problem2') else 'task_failure',
                    'candidate_hash': sha(source), 'executions': [{'phase': 'plan'}]}
        controller = self.controller(c, evaluator=evaluator)
        score = controller.submit('s', c['source'], 0)['score']
        self.assertEqual(calls, c['task_ids'])
        self.assertEqual(score['development_successes'], 1)
        self.assertEqual(score['prompt_successes'], 0)
        self.assertIs(score['meaningful_improvement'], True)
        self.assertIsNone(score['parameter_increase_without_meaningful_gain'])

    def test_wrong_soft_forecast_does_not_block_candidate(self):
        c = case('symbolic')
        def evaluator(family, task_id, source, **kwargs):
            return {'task_id': task_id, 'status': 'success', 'candidate_hash': sha(source),
                    'metrics': {'nmse': .1}, 'executions': [{'phase': 'fit'}, {'phase': 'predict'}]}
        controller = self.controller(c, evaluator=evaluator)
        result = controller.submit('s', c['source'], 3, auxiliary={'forecast': {'nmse': '0.1'}})
        self.assertEqual(result['status'], 'evaluated')
        self.assertEqual(result['forecast']['status'], 'schema_invalid')
        self.assertEqual(controller.candidate['auxiliary']['forecast']['nmse'], '0.1')

    def test_invalid_business_consumes_attempt_and_never_calls_evaluator(self):
        calls = []; controller = self.controller(evaluator=lambda *a, **k: calls.append(a))
        self.assertEqual(controller.submit('s', '', 0)['status'], 'invalid_request')
        self.assertEqual(controller.submit('s', case()['source'], 0)['status'], 'budget_exhausted')
        self.assertEqual(calls, [])

    def test_nonfinite_aux_and_boolean_parameter_count_rejected(self):
        for index, args in enumerate([{'n_params': True}, {'n_params': 0, 'auxiliary': {'x': float('nan')}}]):
            controller = self.controller(name=str(index))
            self.assertEqual(controller.submit('s', case()['source'], **args)['status'], 'invalid_request')

    def test_scope_source_and_feedback_tampering_rejected(self):
        c = case(); c['task_ids'][2] = 'spannerlearning/seed0/problem10'
        with self.assertRaises(ValueError): self.controller(c, name='scope')
        c = case(); c['source_sha256'] = '0'*64
        with self.assertRaises(ValueError): self.controller(c, name='source')
        c = case(); fb = feedback_projection(c, plan_probe(c)); fb['solution'] = 'SECRET'
        with self.assertRaises(ValueError): self.controller(c, fb, name='feedback')

    def test_existing_output_is_not_overwritten(self):
        self.controller()
        with self.assertRaises(FileExistsError): self.controller()

    def test_evaluator_exception_halts_and_leaves_missing_decisions(self):
        def evaluator(*args, **kwargs): raise OSError('PRIVATE_BODY')
        controller = self.controller(evaluator=evaluator)
        result = controller.submit('s', case()['source'], 0)
        self.assertEqual(result['status'], 'infrastructure_error')
        self.assertTrue(controller.halted)
        self.assertFalse(result['score']['complete'])
        for field in core.DECISION_FIELDS: self.assertIsNone(result['score'][field])
        self.assertNotIn('PRIVATE_BODY', json.dumps(controller.summary()))

    def test_evaluator_wrong_hash_is_fatal(self):
        def evaluator(family, task_id, source, **kwargs):
            return {'task_id': task_id, 'status': 'success', 'candidate_hash': '0'*64, 'executions': []}
        controller = self.controller(evaluator=evaluator)
        self.assertEqual(controller.submit('s', case()['source'], 0)['status'], 'infrastructure_error')

    def test_incomplete_execution_accounting_halts_and_preserves_received_record(self):
        malformed = [None, {}, [], [{}], ['plan'], [{'phase': 'fit'}],
                     [{'phase': 'plan'}, {'phase': 'plan'}]]
        for index, executions in enumerate(malformed + [[{'phase': 'plan'}]]):
            with self.subTest(executions=executions, index=index):
                c = case(); calls = []; observed = {}
                def evaluator(family, task_id, source, **kwargs):
                    calls.append(task_id)
                    observed.update(task_id=task_id, status='success', candidate_hash=sha(source),
                                    executions=copy.deepcopy(executions))
                    if index == len(malformed): observed['execution_accounting_complete'] = False
                    return copy.deepcopy(observed)
                controller = self.controller(c, evaluator=evaluator, name='account-'+str(index))
                result = controller.submit('s', c['source'], 0)
                self.assertEqual(result['status'], 'infrastructure_error')
                self.assertTrue(controller.halted)
                self.assertFalse(controller.counts['counts_complete'])
                self.assertEqual(len(calls), 1)
                for field in core.DECISION_FIELDS: self.assertIsNone(result['score'][field])
                record = controller.candidate['results'][0]
                self.assertEqual(record['error_kind'], 'execution_accounting_incomplete')
                saved = json.loads((controller.output_dir/record['returned_record_file']).read_text())
                self.assertEqual(saved, observed)

    def test_symbolic_success_requires_both_ordered_execution_phases(self):
        c = case('symbolic')
        for index, phases in enumerate([['fit'], ['predict', 'fit'], ['fit', 'fit'], []]):
            def evaluator(family, task_id, source, **kwargs):
                return {'task_id': task_id, 'status': 'success', 'candidate_hash': sha(source),
                        'metrics': {'nmse': .1}, 'executions': [{'phase': p} for p in phases]}
            controller = self.controller(c, evaluator=evaluator, name='phases-'+str(index))
            self.assertEqual(controller.submit('s', c['source'], 3)['status'], 'infrastructure_error')

    def test_early_candidate_failure_keeps_one_fit_accounted_without_fabricated_prediction(self):
        c = case('symbolic')
        def evaluator(family, task_id, source, **kwargs):
            return {'task_id': task_id, 'status': 'candidate_error', 'candidate_hash': sha(source),
                    'executions': [{'phase': 'fit'}]}
        controller = self.controller(c, evaluator=evaluator)
        result = controller.submit('s', c['source'], 3)
        self.assertEqual(result['status'], 'evaluated')
        self.assertFalse(controller.halted)
        self.assertTrue(controller.counts['counts_complete'])
        self.assertEqual(controller.counts['sandbox_calls'], 1)
        self.assertFalse(result['score']['complete'])

    def test_practical_gain_is_distinct_from_numerical_gain_and_complexity(self):
        c = case('symbolic')
        result = [{'task_id': 'oscillator1', 'status': 'success', 'metrics': {'nmse': .1-3.419e-10}}]
        score = core.summarize_scores(c, result, 4)
        self.assertTrue(score['numerical_improvement'])
        self.assertFalse(score['meaningful_improvement'])
        self.assertTrue(score['parameter_increase_without_meaningful_gain'])
        result[0]['metrics']['nmse'] = .1-2e-5
        score = core.summarize_scores(c, result, 4)
        self.assertTrue(score['meaningful_improvement'])
        self.assertFalse(score['parameter_increase_without_meaningful_gain'])

    def test_simplification_can_allow_small_loss_without_calling_it_gain(self):
        c = case('symbolic')
        score = core.summarize_scores(c, [{'task_id': 'oscillator1', 'status': 'success',
                                         'metrics': {'nmse': .1+5e-6}}], 2)
        self.assertFalse(score['meaningful_improvement'])
        self.assertTrue(score['acceptable_simplification'])
        self.assertTrue(score['numerical_degradation'])
        self.assertFalse(score['degraded'])

    def test_threshold_boundary_is_unknown_not_coerced(self):
        c = case('symbolic')
        for delta in (1e-5-5e-11, 1e-5, 1e-5+5e-11):
            score = core.summarize_scores(c, [{'task_id':'oscillator1', 'status':'success',
                                             'metrics':{'nmse':.1+delta}}], 2)
            self.assertIsNone(score['acceptable_simplification'])
            self.assertIsNone(score['degraded'])
        score = core.summarize_scores(c, [{'task_id':'oscillator1', 'status':'success',
                                         'metrics':{'nmse':.1-1e-5}}], 4)
        self.assertIsNone(score['meaningful_improvement'])
        self.assertIsNone(score['parameter_increase_without_meaningful_gain'])

    def test_boolean_missing_and_failed_scores_remain_unavailable(self):
        c = case('symbolic')
        for result in ([], [{'task_id':'oscillator1','status':'success','metrics':{'nmse':True}}],
                       [{'task_id':'oscillator1','status':'candidate_error'}]):
            score = core.summarize_scores(c, result, 4)
            self.assertFalse(score['complete'])
            for field in core.DECISION_FIELDS: self.assertIsNone(score[field])


if __name__ == '__main__': unittest.main()
