import json
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from rsi_eval.pilot_controller import PilotController


class PilotControllerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / 'fixtures').mkdir()
        (self.root / 'fixtures/initial.py').write_text('initial', encoding='utf-8')
        (self.root / 'prompts').mkdir()
        (self.root / 'prompts/task.md').write_text('Public task.', encoding='utf-8')
        self.config = dict(session_id='symbolic', family='symbolic', prompt_file='prompts/task.md',
            initial_candidate='fixtures/initial.py', initial_n_params=1, task_ids=['oscillator1'],
            prompt_task_ids=[], strategy_version='fixed-revision-v0.1', max_generated_candidates=3)
        self.config['initial_candidate_sha256'] = hashlib.sha256(b'initial').hexdigest()

    def controller(self):
        return PilotController(self.root, self.config, self.root / 'out')

    @staticmethod
    def scored(nmse):
        return dict(status='success', metrics={'mse': nmse * 2, 'nmse': nmse},
                    metric_split='train', run_id='a' * 32, candidate_hash='b' * 64)

    def test_baseline_last_and_best_are_distinct_and_parent_is_previous(self):
        with patch('rsi_eval.pilot_controller.evaluate_candidate', side_effect=[self.scored(1), self.scored(.2), self.scored(.4)]) as run:
            c = self.controller(); c.baseline()
            first = c.submit('candidate_one', 2, 'Add structure')
            last = c.submit('candidate_two', 3, 'Try another term')
        s = c.summary()
        self.assertEqual(s['baseline']['metrics']['nmse'], 1)
        self.assertEqual(s['first']['candidate_id'], first['candidate_id'])
        self.assertEqual(s['last']['candidate_id'], last['candidate_id'])
        self.assertEqual(s['best']['candidate_id'], first['candidate_id'])
        self.assertEqual(run.call_args_list[2].kwargs['parent_id'], first['candidate_id'])
        self.assertFalse(s['strategy_updated'])
        self.assertEqual(s['sealed_tasks_executed'], 0)

    def test_candidate_limit_is_checked_before_execution(self):
        with patch('rsi_eval.pilot_controller.evaluate_candidate', return_value=self.scored(1)) as run:
            c = self.controller(); c.baseline()
            for i in range(3): c.submit(str(i), 1, 'bounded')
            result = c.submit('fourth', 1, 'must not run')
        self.assertEqual(result['status'], 'budget_exhausted')
        self.assertEqual(run.call_count, 4)
        self.assertEqual(c.summary()['generated_candidates'], 3)

    def test_equal_metric_keeps_earlier_candidate(self):
        with patch('rsi_eval.pilot_controller.evaluate_candidate', return_value=self.scored(1)):
            c = self.controller(); initial = c.baseline(); c.submit('one', 1)
        self.assertEqual(c.summary()['best']['candidate_id'], initial['candidate_id'])

    def test_regression_returns_incumbent_and_next_revision_uses_it(self):
        with patch('rsi_eval.pilot_controller.evaluate_candidate', side_effect=[self.scored(1),self.scored(.2),self.scored(.4),self.scored(.1)]) as run:
            c=self.controller();c.baseline();best=c.submit('best',1)
            worse=c.submit('worse',1);c.submit('third',1)
        self.assertEqual(worse['selection']['incumbent_id'],best['candidate_id'])
        self.assertFalse(worse['selection']['accepted'])
        self.assertEqual(worse['selection']['incumbent_source'],'best')
        self.assertEqual(run.call_args_list[3].kwargs['parent_id'],best['candidate_id'])

    def test_no_generated_candidate_is_reported_as_null(self):
        with patch('rsi_eval.pilot_controller.evaluate_candidate',return_value=self.scored(1)):
            c=self.controller();c.baseline()
        self.assertIsNone(c.summary()['first'])
        self.assertIsNone(c.summary()['last'])

    def test_modified_initial_fixture_is_rejected_before_execution(self):
        self.config['initial_candidate_sha256']='0'*64
        with patch('rsi_eval.pilot_controller.evaluate_candidate') as run:
            with self.assertRaises(ValueError):self.controller()
        run.assert_not_called()

    def test_failures_and_sources_are_recorded_without_raw_private_fields(self):
        with patch('rsi_eval.pilot_controller.evaluate_candidate', side_effect=[self.scored(1), {'status':'candidate_error','error_kind':'python_exception','stderr':'SECRET','path':'/home/private','candidate_line':5}]):
            c = self.controller(); c.baseline(); result = c.submit('broken', 1)
        self.assertNotIn('SECRET', json.dumps(result))
        self.assertNotIn('/home/private', json.dumps(result))
        self.assertEqual(result['results'][0]['candidate_line'], 5)
        self.assertEqual((self.root / 'out/candidates/symbolic-001.py').read_text(), 'broken')
        self.assertEqual(len(json.loads((self.root / 'out/candidates.json').read_text())), 2)

    def test_task_scope_cannot_be_changed_to_official_tests(self):
        self.config['task_ids'] = ['oscillator1/test_id']
        with self.assertRaises(ValueError): self.controller()

    def test_invalid_parameters_and_source_are_rejected_without_evaluation(self):
        with patch('rsi_eval.pilot_controller.evaluate_candidate', return_value=self.scored(1)) as run:
            c = self.controller(); c.baseline()
            for source, params in [('x',True),('x',17),('',1),('x'*65537,1)]:
                self.assertEqual(c.submit(source,params)['status'], 'invalid_request')
        self.assertEqual(run.call_count, 1)

    def test_infrastructure_failure_halts_further_candidates(self):
        with patch('rsi_eval.pilot_controller.evaluate_candidate', return_value={'status':'infrastructure_error','error_kind':'missing_validator'}) as run:
            c = self.controller(); c.baseline(); result=c.submit('one',1)
        self.assertEqual(result['status'], 'infrastructure_error')
        self.assertEqual(run.call_count, 1)
        self.assertTrue(c.summary()['halted'])

    def test_planning_evaluates_fixed_batch_and_selects_development_first(self):
        tasks = [f'spannerlearning/seed0/problem{i}' for i in range(10)]
        self.config.update(session_id='planning', family='planning', task_ids=tasks,
            prompt_task_ids=tasks[:2], initial_n_params=0)
        def fake(family, task, source, **kwargs):
            i=int(task.rsplit('problem',1)[1])
            good = (source=='initial' and i<2) or (source=='one' and i==2)
            return {'status':'success' if good else 'task_failure'}
        with patch('rsi_eval.pilot_controller.evaluate_candidate', side_effect=fake) as run:
            c=self.controller(); c.baseline(); candidate=c.submit('one',0)
        self.assertEqual(run.call_count,20)
        self.assertEqual(candidate['metrics'], {'prompt_successes':0,'prompt_total':2,'development_successes':1,'development_total':8,'total_successes':1,'total_tasks':10})
        self.assertEqual(c.summary()['best']['candidate_id'],candidate['candidate_id'])

    def test_prompt_uses_only_two_authorized_examples(self):
        tasks=[f'spannerlearning/seed0/problem{i}' for i in range(10)]
        self.config.update(session_id='planning',family='planning',task_ids=tasks,prompt_task_ids=tasks[:2],initial_n_params=0)
        with patch('rsi_eval.pilot_controller.evaluate_candidate',return_value={'status':'task_failure'}), patch('rsi_eval.pilot_controller.planning.prepare_task',side_effect=lambda task,root:{'task_id':task,'objects':[],'init':[],'goal':[]}) as load:
            c=self.controller();c.baseline();text=c.task_prompt()
        self.assertEqual(load.call_count,2)
        self.assertNotIn('SECRET',text)
        self.assertIn('initial',text)


if __name__ == '__main__':
    unittest.main()
