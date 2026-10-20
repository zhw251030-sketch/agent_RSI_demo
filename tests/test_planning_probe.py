"""Offline formatting calibration: sandbox and VAL calls are always mocked."""
import ast
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from rsi_eval import planning, planning_probe
from tests.test_planning import DOMAIN, PROBLEM, TASK_ID


SOURCE = 'def get_plan(objects, init, goal):\n    raise RuntimeError("NEVER_EXECUTE_ON_HOST")\n'
OLD_FORMAT = 'def _fmt(name, params):\n    return "(" + " " + " ".join([name] + list(params)) + ")"\n'


class NormalizePlanTests(unittest.TestCase):
    def test_only_ascii_edges_change_and_internal_bytes_case_order_stay(self):
        original = [' \t( \nWALK  shed\tgate bob \r)\n', '(pickup_spanner shed s1 bob)']
        saved = copy.deepcopy(original)
        result = planning_probe.normalize_plan(original)
        self.assertEqual(result['status'], 'normalized')
        self.assertEqual(result['original'], saved)
        self.assertEqual(result['normalized'], ['(WALK  shed\tgate bob)', original[1]])
        self.assertEqual(result['changed_indices'], [0])
        self.assertIs(result['token_preserved'], True)
        self.assertEqual(original, saved)

    def test_canonical_and_empty_plans_are_unchanged(self):
        for value in ([], ['(walk shed gate bob)']):
            result = planning_probe.normalize_plan(value)
            self.assertEqual(result['status'], 'unchanged')
            self.assertEqual(result['original'], value)
            self.assertEqual(result['normalized'], value)
            self.assertEqual(result['changed_indices'], [])

    def test_nested_multiple_or_malformed_forms_are_not_repaired(self):
        cases = ['((walk shed gate bob))', '(walk shed gate bob)(walk gate shed bob)',
                 '(walk shed gate bob', 'walk shed gate bob)', '()', '(   )',
                 '(walk shed gate bob);comment', '(walk shed gate b_ob!)']
        for value in cases:
            with self.subTest(value=value):
                result = planning_probe.normalize_plan([value])
                self.assertEqual(result['status'], 'unknown')
                self.assertIsNone(result['normalized'])
                self.assertIsNone(result['token_preserved'])
                self.assertEqual(result['original'], [value])

    def test_non_ascii_space_is_neither_trimmed_nor_reinterpreted(self):
        for value in ('\u00a0(walk shed gate bob)', '(\u2003walk shed gate bob)',
                      '(walk shed\u00a0gate bob)', '(walk shed gate bob\u00a0)'):
            result = planning_probe.normalize_plan([value])
            self.assertEqual(result['status'], 'unknown')
            self.assertEqual(result['original'], [value])

    def test_non_list_nonstring_oversize_and_invalid_utf8_are_unknown(self):
        for value in (None, '(walk shed gate bob)', ('(walk shed gate bob)',), [None],
                      [object()], ['(walk shed gate bob)']*1001, ['x'*4097], ['\ud800']):
            with self.subTest(type=type(value).__name__):
                result = planning_probe.normalize_plan(value)
                self.assertEqual(result['status'], 'unknown')
                self.assertIsNone(result['normalized'])


class PlanningProbeTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.manifest_path = self.root/'configs/tasks/planning-spanner-v0.1.json'
        self.manifest_path.parent.mkdir(parents=True)
        data = self.root/'data/planning/spanner'
        (data/'spannerlearning/seed0').mkdir(parents=True)
        (data/'spannerlearning.pddl').write_bytes(DOMAIN.encode())
        self.problem = PROBLEM.replace('(and (tightened nut1))', '(and (at bob gate))')
        self.problem_path = data/'spannerlearning/seed0/problem0.pddl'
        self.problem_path.write_bytes(self.problem.encode())
        self.manifest = {'domain': {'upstream_path': planning.PDDL_PREFIX+'spannerlearning.pddl',
            'sha256': hashlib.sha256(DOMAIN.encode()).hexdigest()},
            'tasks': [{'id': TASK_ID, 'upstream_path': planning.PDDL_PREFIX+TASK_ID+'.pddl',
                'sha256': hashlib.sha256(self.problem.encode()).hexdigest(), 'pilot_role': 'prompt'}]}
        self.save_manifest()
        self.source_sha = hashlib.sha256(SOURCE.encode()).hexdigest()

    def save_manifest(self):
        self.manifest_path.write_text(json.dumps(self.manifest), encoding='utf-8')

    def execute(self, plan, val_status='valid', transport=None):
        payload = {'status': 'completed', 'elapsed_seconds': 0.01, 'stdout_bytes': 45,
            'stderr_bytes': 0, 'result': {'status': 'ok', 'plan': copy.deepcopy(plan)}}
        if transport is not None: payload = transport
        with patch('rsi_eval.planning_probe.run_candidate', return_value=payload) as candidate, \
             patch.dict(planning.VAL_HASHES, {}, clear=True), \
             patch.object(planning, 'run_val', return_value={'status': val_status, 'reason': 'offline_fixture'}) as validator:
            result = planning_probe.probe_plan(SOURCE, TASK_ID, root=self.root, source_sha256=self.source_sha)
        return result, candidate, validator

    def test_same_generated_plan_is_used_for_both_sides_and_one_format_probe_succeeds(self):
        result, candidate, validator = self.execute(['( walk shed gate bob )'])
        self.assertEqual(result['version'], 'planning-format-probe-v0.1')
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(result['verdict'], 'supported')
        self.assertEqual(result['raw']['validation']['error_kind'], 'operator_syntax')
        self.assertEqual(result['normalized']['validation']['status'], 'success')
        self.assertEqual(result['normalized']['replay']['status'], 'valid')
        self.assertEqual(result['normalization']['original'], ['( walk shed gate bob )'])
        self.assertEqual(result['normalization']['normalized'], ['(walk shed gate bob)'])
        candidate.assert_called_once()
        self.assertEqual(candidate.call_args.args[0], SOURCE)
        self.assertEqual(candidate.call_args.args[1], planning.prepare_task(TASK_ID, self.root))
        self.assertEqual(candidate.call_args.kwargs, {
            'deps_dir': self.root/'.task-runtime/python', **planning_probe.LIMITS})
        self.assertEqual(validator.call_count, 1)
        self.assertEqual(validator.call_args.args[3], ['(walk shed gate bob)'])
        self.assertEqual(result['executions'], {'new_candidate_executions': 1, 'sandbox_calls': 1,
            'host_validations': 2, 'diagnostic_replays': 2, 'val_calls': 1, 'val_count_complete': True})
        self.assertFalse(result['changes_historical_scores'])
        self.assertEqual(result['model_calls'], 0)

    def test_missing_precondition_after_normalization_contradicts_sufficiency(self):
        result, _, validator = self.execute(['( walk gate shed bob )'], val_status='invalid')
        self.assertEqual(result['verdict'], 'contradicted')
        self.assertEqual(result['normalized']['validation']['status'], 'task_failure')
        self.assertEqual(result['normalized']['replay']['status'], 'precondition_failure')
        self.assertEqual(validator.call_count, 1)

    def test_empty_plan_has_unsatisfied_goal_and_does_not_gain_actions(self):
        result, _, validator = self.execute([], val_status='invalid')
        self.assertEqual(result['verdict'], 'contradicted')
        self.assertEqual(result['normalization']['normalized'], [])
        self.assertEqual(result['raw']['replay']['executed_actions'], 0)
        self.assertEqual(result['normalized']['replay']['status'], 'goal_unsatisfied')
        self.assertEqual(validator.call_count, 2)

    def test_successful_original_is_not_a_successful_repair_claim(self):
        result, _, validator = self.execute(['  (walk shed gate bob)\t'])
        self.assertEqual(result['verdict'], 'unknown')
        self.assertEqual(result['reason'], 'original_already_valid_not_applicable')
        self.assertEqual(validator.call_count, 2)

    def test_malformed_plan_is_unknown_without_invented_normalized_actions(self):
        result, _, validator = self.execute(['((walk shed gate bob))'])
        self.assertEqual(result['verdict'], 'unknown')
        self.assertIsNone(result['normalized'])
        self.assertEqual(result['executions']['host_validations'], 1)
        self.assertEqual(result['executions']['diagnostic_replays'], 1)
        validator.assert_not_called()

    def test_validator_replay_disagreement_is_infrastructure_not_candidate_failure(self):
        result, _, _ = self.execute(['( walk gate shed bob )'], val_status='valid')
        self.assertEqual(result['status'], 'infrastructure_error')
        self.assertEqual(result['verdict'], 'unknown')
        self.assertIn('disagreement', result['reason'])

    def test_validator_infrastructure_failure_is_separate_and_counted(self):
        result, _, validator = self.execute(['( walk shed gate bob )'], val_status='infrastructure_error')
        self.assertEqual(result['status'], 'infrastructure_error')
        self.assertEqual(result['verdict'], 'unknown')
        self.assertEqual(result['executions']['val_calls'], 1)
        self.assertEqual(validator.call_count, 1)

    def test_task_and_source_bindings_are_explicit_and_public(self):
        result, _, _ = self.execute(['( walk shed gate bob )'])
        self.assertEqual(result['source_sha256'], self.source_sha)
        self.assertEqual(result['task_id'], TASK_ID)
        self.assertEqual(result['task_binding']['domain_sha256'], self.manifest['domain']['sha256'])
        self.assertEqual(result['task_binding']['problem_sha256'], self.manifest['tasks'][0]['sha256'])
        self.assertEqual(result['task_binding']['manifest_sha256'], hashlib.sha256(self.manifest_path.read_bytes()).hexdigest())
        self.assertEqual(result['task_binding']['pilot_role'], 'prompt')

    def test_nonpublic_and_wrong_hash_reject_before_execution_or_task_read(self):
        with patch('rsi_eval.planning_probe.run_candidate') as candidate:
            with self.assertRaises(ValueError):
                planning_probe.probe_plan(SOURCE, TASK_ID, root=self.root, source_sha256='0'*64)
            self.manifest['tasks'][0]['pilot_role'] = 'development_feedback'; self.save_manifest()
            self.problem_path.unlink()
            with self.assertRaises(PermissionError):
                planning_probe.probe_plan(SOURCE, TASK_ID, root=self.root, source_sha256=self.source_sha)
        candidate.assert_not_called()

    def test_data_integrity_error_never_executes_candidate(self):
        self.problem_path.write_text(self.problem+'\n; tampered', encoding='utf-8')
        with patch('rsi_eval.planning_probe.run_candidate') as candidate:
            result = planning_probe.probe_plan(SOURCE, TASK_ID, root=self.root, source_sha256=self.source_sha)
        self.assertEqual(result['status'], 'infrastructure_error')
        self.assertEqual(result['executions']['sandbox_calls'], 0)
        candidate.assert_not_called()

    def test_sandbox_failures_preserve_unknown_and_never_publish_stderr(self):
        for status in ('timeout', 'candidate_process_error', 'infrastructure_error'):
            result, _, validator = self.execute(None, transport={'status': status, 'stderr': 'PRIVATE_ERROR',
                'error': 'PRIVATE_ERROR', 'stdout': 'PRIVATE_ERROR', 'returncode': 70})
            self.assertEqual(result['verdict'], 'unknown')
            self.assertEqual(result['status'], 'infrastructure_error' if status == 'infrastructure_error' else 'unavailable')
            self.assertNotIn('PRIVATE_ERROR', json.dumps(result))
            validator.assert_not_called()

    def test_candidate_python_error_is_unavailable_and_not_task_failure(self):
        result, _, validator = self.execute(None, transport={'status': 'completed',
            'result': {'status': 'candidate_error', 'error_kind': 'python_exception',
                       'exception_type': 'TypeError', 'candidate_line': 3, 'message': 'PRIVATE_ERROR'}})
        self.assertEqual(result['status'], 'unavailable')
        self.assertEqual(result['verdict'], 'unknown')
        self.assertNotIn('PRIVATE_ERROR', json.dumps(result))
        self.assertEqual(result['executions']['host_validations'], 0)
        validator.assert_not_called()

    def test_malformed_transport_is_infrastructure_error_not_arbitrary_output(self):
        result, _, validator = self.execute(None, transport={'status': ['PRIVATE_ERROR']})
        self.assertEqual(result['status'], 'infrastructure_error')
        self.assertEqual(result['verdict'], 'unknown')
        self.assertNotIn('PRIVATE_ERROR', json.dumps(result))
        validator.assert_not_called()

    def test_unobservable_validator_exception_marks_val_count_incomplete(self):
        with patch.object(planning, 'validate_plan', side_effect=ValueError('PRIVATE_ERROR')):
            result, _, _ = self.execute(['(walk shed gate bob)'])
        self.assertEqual(result['status'], 'infrastructure_error')
        self.assertEqual(result['verdict'], 'unknown')
        self.assertFalse(result['executions']['val_count_complete'])
        self.assertEqual(result['executions']['host_validations'], 1)
        self.assertNotIn('PRIVATE_ERROR', json.dumps(result))


class FormatPatchTests(unittest.TestCase):
    def test_ast_projection_ignores_only_empty_python312_type_params(self):
        old_tree = ast.parse(OLD_FORMAT)
        old_function = old_tree.body[0]
        old_function._fields = tuple(field for field in old_function._fields if field != 'type_params')
        new_tree = copy.deepcopy(old_tree)
        new_function = new_tree.body[0]
        new_function._fields += ('type_params',)
        new_function.type_params = []
        before = ast.dump(new_tree, include_attributes=False)
        self.assertNotEqual(ast.dump(old_tree, include_attributes=False), before)
        self.assertEqual(planning_probe._ast_dump(old_tree), planning_probe._ast_dump(new_tree))
        self.assertEqual(ast.dump(new_tree, include_attributes=False), before)
        new_function.type_params = [ast.Name(id='T', ctx=ast.Load())]
        self.assertNotEqual(planning_probe._ast_dump(old_tree), planning_probe._ast_dump(new_tree))
        self.assertIn('type_params=', planning_probe._ast_dump(new_tree))

    def test_exact_format_expression_patch_keeps_every_other_ast_node(self):
        source = '# preserved comment\n'+OLD_FORMAT+'\n'+SOURCE
        result = planning_probe.build_format_patch(source)
        self.assertEqual(result['status'], 'accepted')
        expected = source.replace('"(" + " " + " ".join', '"(" + " ".join')
        self.assertEqual(result['source'], expected)
        self.assertEqual(result['source_sha256'], hashlib.sha256(expected.encode()).hexdigest())
        self.assertEqual(result['original_sha256'], hashlib.sha256(source.encode()).hexdigest())
        self.assertTrue(result['contract']['other_ast_unchanged'])
        self.assertEqual(result['contract']['function'], '_fmt')
        self.assertEqual(result['contract']['ast_projection_version'], 'python310-empty-type-params-v0.1')

    def test_nonmatching_function_contracts_are_rejected_without_source(self):
        cases = [SOURCE, OLD_FORMAT+OLD_FORMAT, '@decorator\n'+OLD_FORMAT,
            OLD_FORMAT.replace('(name, params)', '(name, params=())'),
            OLD_FORMAT.replace('(name, params)', '(name: str, params)'),
            OLD_FORMAT.replace('"(" + " " + ', '"(" + '),
            OLD_FORMAT.replace('return ', 'print("side effect")\n    return '),
            OLD_FORMAT.replace('list(params)', 'sorted(params)'),
            'async '+OLD_FORMAT, 'def _fmt(:\n']
        for source in cases:
            with self.subTest(source=source[:50]):
                result = planning_probe.build_format_patch(source)
                self.assertEqual(result['status'], 'rejected')
                self.assertIsNone(result['source'])

    def test_multiline_return_and_utf8_prefix_preserve_other_source_bytes(self):
        source = '# 汉字说明\n'+OLD_FORMAT.replace('return "(" + " " + ', 'return ("(" + " " + ').replace(' + ")"\n', ' +\n            ")")\n')+SOURCE
        result = planning_probe.build_format_patch(source)
        self.assertEqual(result['status'], 'accepted')
        self.assertTrue(result['source'].startswith('# 汉字说明\n'))
        self.assertTrue(result['source'].endswith(SOURCE))
        self.assertTrue(result['contract']['other_ast_unchanged'])

    def test_nested_formatter_remains_in_place_and_other_ast_stays_equal(self):
        source = 'def get_plan(objects, init, goal):\n'+''.join('    '+line for line in OLD_FORMAT.splitlines(keepends=True))+'    return [_fmt("walk", ["shed", "gate", "bob"])]\n'
        result = planning_probe.build_format_patch(source)
        self.assertEqual(result['status'], 'accepted')
        expected = source.replace('"(" + " " + " ".join', '"(" + " ".join')
        self.assertEqual(result['source'], expected)
        self.assertTrue(result['contract']['other_ast_unchanged'])


if __name__ == '__main__': unittest.main()
