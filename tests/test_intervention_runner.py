import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('intervention_runner', ROOT/'scripts/run_intervention_probes.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class RunnerTests(unittest.TestCase):
    def test_protocol_rejects_extra_keys_changed_scope_and_nan(self):
        config = runner.load_config(ROOT)
        for key, value in [('model_calls', 1), ('epsilon', float('nan')),
                           ('resume', True), ('max_sandbox_calls', 41), ('extra', 1)]:
            bad = copy.deepcopy(config); bad[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                runner.validate_config(bad)

    def test_reservation_happens_before_dispatch(self):
        budget = runner.ExecutionBudget(2)
        budget.reserve(2)
        with self.assertRaises(ValueError):
            budget.reserve(1)
        budget.settle(2, 1)
        self.assertEqual(budget.actual, 1)
        self.assertEqual(budget.reserved, 2)

    def test_underreserved_execution_is_rejected(self):
        budget = runner.ExecutionBudget(2)
        budget.reserve(1)
        with self.assertRaises(ValueError):
            budget.settle(1, 2)

    def test_patch_gate_requires_two_supported_public_results(self):
        good = [{'status':'completed','verdict':'supported'} for _ in range(2)]
        self.assertTrue(runner.patch_allowed(good))
        for rows in [good[:1], good + good[:1],
                     [good[0], {'status':'completed','verdict':'contradicted'}],
                     [good[0], {'status':'infrastructure_error','verdict':'supported'}]]:
            self.assertFalse(runner.patch_allowed(rows))

    def test_new_output_only_under_run_scope(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root/'runs/intervention-probes/test'
            runner.new_output(root, output)
            with self.assertRaises(FileExistsError):
                runner.new_output(root, output)
            with self.assertRaises(ValueError):
                runner.new_output(root, root/'artifacts/wrong')

    def test_counts_use_actual_executions_and_validator_presence(self):
        record = {'executions':[{'phase':'plan'}], 'validator':{'status':'valid'},'plan_length':4}
        self.assertEqual(runner.evaluator_counts(record),
                         {'sandbox_calls':1, 'new_candidate_executions':1,
                          'host_validations':1, 'val_calls':1, 'fit_calls':0, 'predict_calls':0})
        failed = {'executions':[{'phase':'fit'}], 'status':'candidate_error'}
        counts = runner.evaluator_counts(failed)
        self.assertEqual((counts['sandbox_calls'],counts['fit_calls'],counts['predict_calls']), (1,1,0))
        timeout={'status':'timeout','executions':[{'phase':'plan','status':'timeout'}]}
        self.assertEqual(runner.evaluator_counts(timeout)['host_validations'],0)
        ambiguous={'error_kind':'plan_validation_failed','executions':[{'phase':'plan'}]}
        self.assertIs(runner.evaluator_counts(ambiguous)['val_count_complete'],False)

    def test_json_preserves_exact_source_newlines(self):
        with tempfile.TemporaryDirectory() as directory:
            file=Path(directory)/'a.json'
            runner.write_json(file, {'source':'a\r\nb\n'})
            self.assertEqual(json.loads(file.read_text())['source'], 'a\r\nb\n')

    def test_complete_mock_dispatch_and_infrastructure_stop(self):
        # This exercises sequencing/accounting only; no candidate or model runs.
        from rsi_eval import planning_probe, symbolic_probe, probe_cases, executor
        bundle={'planning':[{'id':f'p{i}','source':'source','source_sha256':'hash'} for i in range(3)],
                'symbolic':[dict(id=f's{i}',source='source',source_sha256='hash',n_params=3,
                    remove_param_index=2,parent_source='parent',parent_n_params=2,
                    parent_sha256='parent-hash') for i in range(2)],
                'public_tasks':['problem0','problem1'],
                'development_tasks':[f'problem{i}' for i in range(10)]}
        plan={'status':'completed','verdict':'supported','task_id':'problem0',
              'executions':{'sandbox_calls':1,'new_candidate_executions':1,'host_validations':2,'val_calls':2}}
        symbol={'status':'completed','verdict':'contradicted','variants':[],
                'executions':{'sandbox_calls':6,'new_candidate_executions':3,'fit_calls':3,'predict_calls':3}}
        evaluation={'status':'success','executions':[{'phase':'plan'}],'validator':{'status':'valid'},'plan_length':4}
        for stop in (False,True):
            with self.subTest(stop=stop), tempfile.TemporaryDirectory() as directory:
                root=Path(directory)
                runner.write_json(root/runner.CONFIG_PATH,runner.EXPECTED)
                output=root/'runs/intervention-probes/run'
                returned=copy.deepcopy(plan)
                if stop:
                    returned['status']='infrastructure_error'
                with patch.object(probe_cases,'load_cases',return_value=bundle), \
                     patch.object(runner,'runtime_freeze',return_value={'runtime_files_sha256':{}}), \
                     patch.object(planning_probe,'probe_plan',return_value=returned) as p, \
                     patch.object(planning_probe,'build_format_patch',return_value={'status':'accepted','source':'patched'}), \
                     patch.object(symbolic_probe,'probe_symbolic',return_value=symbol) as s, \
                     patch.object(symbolic_probe,'build_term_removal',return_value={'status':'unknown'}), \
                     patch.object(executor,'evaluate_candidate',return_value=evaluation) as e:
                    if stop:
                        with self.assertRaises(RuntimeError):
                            runner.run(root,output)
                        self.assertEqual((p.call_count,s.call_count,e.call_count),(1,0,0))
                        self.assertEqual(json.loads((output/'summary.json').read_bytes())['status'],'stopped')
                    else:
                        report=runner.run(root,output)
                        self.assertEqual(report['status'],'completed')
                        self.assertEqual((p.call_count,s.call_count,e.call_count),(6,2,10))
                        self.assertEqual(report['counts']['sandbox_calls'],28)
                        self.assertEqual(report['counts']['new_candidate_executions'],22)
                        self.assertEqual(report['budget'],{'maximum':40,'reserved':28,'actual':28})

    def test_unknown_never_authorizes_a_structural_repair(self):
        for family in ('planning','symbolic'):
            result=runner.scoped_edit(family,{'verdict':'unknown','task_id':'public0'})
            self.assertIn(result['action'],('no_repair_inference','no_term_value_decision'))
            self.assertIn('agent_autonomous_improvement',result['excludes'])


if __name__ == '__main__':
    unittest.main()
