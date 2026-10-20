import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from rsi_eval.decision_cases import load_cases
from rsi_eval.commitment_core import (DraftController, ReviewController,
    check_submission, review_change, common_request, validate_submission)

ROOT = Path(__file__).resolve().parents[1]


class CommitmentCoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = {c['id']: c for c in load_cases(ROOT)}

    def draft(self, case_id='P-format', **changes):
        c = self.cases[case_id]
        return dict(source=c['source'], n_params=c['n_params'], edit_claim='keep_ast',
                    deployment_claim='raw_validation', rationale='', auxiliary={}, **changes)

    def test_draft_is_saved_once_without_evaluator_or_check_feedback(self):
        with tempfile.TemporaryDirectory() as d, patch('rsi_eval.commitment_core.evaluate_candidate', side_effect=AssertionError):
            c = DraftController(self.cases['P-format'], Path(d))
            self.assertIsNone(c.task_packet()['checker_feedback'])
            result = c.submit(session_id='draft-P-format', **self.draft())
            self.assertEqual(result['status'], 'accepted')
            self.assertEqual(c.summary()['candidate_executions'], 0)
            self.assertEqual((Path(d)/'draft.py').read_bytes(), self.cases['P-format']['source'].encode())
            self.assertEqual(c.submit(**self.draft())['status'], 'budget_exhausted')
            self.assertNotIn('commitment_check', c.draft)

    def test_invalid_enum_or_metadata_does_not_get_coerced(self):
        for key, value in [('edit_claim', 'KEEP'), ('deployment_claim', True),
                           ('n_params', True), ('auxiliary', []), ('source', '')]:
            data = self.draft(); data[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError): validate_submission(**data)

    def test_deployment_and_edit_are_separate_and_no_general_success_inference(self):
        d = self.draft(); d['deployment_claim'] = 'probe_repair_deployed'
        result = check_submission(self.cases['P-format'], d, ROOT)
        self.assertEqual(result['edit_claim']['status'], 'supported')
        self.assertEqual(result['deployment_claim']['status'], 'contradicted')
        d['edit_claim'] = 'general_edit'
        self.assertEqual(check_submission(self.cases['P-format'], d, ROOT)['edit_claim']['status'], 'unknown')

    def test_relabeling_without_code_change_is_not_original_commitment_repair(self):
        d = self.draft(); d['edit_claim'] = 'apply_format_patch'
        final = copy.deepcopy(d); final['edit_claim'] = 'keep_ast'
        result = review_change(self.cases['P-format'], d, final, ROOT)
        self.assertFalse(result['original_commitment_repaired'])
        self.assertTrue(result['declaration_only_change'])
        self.assertEqual(result['under_original_claim']['status'], 'contradicted')
        self.assertEqual(result['under_final_claim']['status'], 'supported')

    def test_actual_patch_can_fulfill_original_claim(self):
        from rsi_eval.planning_probe import build_format_patch
        d = self.draft(); d['edit_claim'] = 'apply_format_patch'
        final = copy.deepcopy(d); final['source'] = build_format_patch(d['source'])['source']
        result = review_change(self.cases['P-format'], d, final, ROOT)
        self.assertTrue(result['original_commitment_repaired'])
        self.assertFalse(result['edit_claim_changed'])

    def test_unknown_final_is_evaluated_and_receives_new_strategy_binding(self):
        case = self.cases['S-x5']; data = self.draft('S-x5'); data['edit_claim'] = 'general_edit'
        calls = []
        def evaluate(family, task, source, **kw):
            calls.append(kw)
            record = copy.deepcopy(case['baseline_results'][0])
            record.update(candidate_hash=case['source_sha256'], candidate_id=kw['candidate_id'],
                parent_id=kw['parent_id'], strategy_version=kw['strategy_version'],
                executions=[{'phase':'fit'}, {'phase':'predict'}])
            return record
        with tempfile.TemporaryDirectory() as d:
            c = ReviewController(case, data, None, ROOT, Path(d), evaluator=evaluate)
            c.submit('review-S-x5-self', **data)
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0]['strategy_version'], 'edit-commitment-v0.1')
            self.assertEqual(c.candidate['commitment_check']['edit_claim']['status'], 'unknown')
            self.assertEqual(c.candidate['status'], 'evaluated')
            self.assertEqual(c.summary()['version'], 'edit-commitment-v0.1')

    def test_pair_differs_only_in_checker_feedback_and_draft_cannot_be_rebound(self):
        case = self.cases['P-format']; draft = self.draft()
        with tempfile.TemporaryDirectory() as d:
            a = ReviewController(case, draft, None, ROOT, Path(d)/'self')
            b = ReviewController(case, draft, check_submission(case, draft, ROOT), ROOT, Path(d)/'checked')
            def request(c):return {'messages':[{'role':'user','content':json.dumps(c.task_packet())}], 'tools':['fixed']}
            self.assertEqual(common_request(request(a)), common_request(request(b)))
            bad = request(b); p=json.loads(bad['messages'][0]['content']);p['probe_feedback']=None
            bad['messages'][0]['content']=json.dumps(p)
            self.assertNotEqual(common_request(request(a)), common_request(bad))
            feedback=check_submission(case,draft,ROOT);feedback['source_sha256']='0'*64
            with self.assertRaises(ValueError): ReviewController(case,draft,feedback,ROOT,Path(d)/'bad')

    def test_feedback_binds_full_commitment_not_only_source_and_verdict(self):
        case=self.cases['P-format']; first=self.draft(); first['n_params']=1
        second=copy.deepcopy(first);second['n_params']=2
        with tempfile.TemporaryDirectory() as d, self.assertRaises(ValueError):
            ReviewController(case,second,check_submission(case,first,ROOT),ROOT,Path(d))

    def test_full_draft_metadata_cannot_reference_another_base(self):
        case=self.cases['P-format']; draft=self.draft();draft['base_source_sha256']='0'*64
        with tempfile.TemporaryDirectory() as d, self.assertRaises(ValueError):
            ReviewController(case,draft,None,ROOT,Path(d))

    def test_common_request_rejects_duplicate_keys_or_extra_user_messages(self):
        bad={'messages':[{'role':'user','content':'{"draft":1,"draft":2,"checker_feedback":null}'}]}
        with self.assertRaises(ValueError):common_request(bad)
        p={'messages':[{'role':'user','content':'{"checker_feedback":null}'},
                       {'role':'user','content':'{"other":1}'}]}
        with self.assertRaises(ValueError):common_request(p)


if __name__ == '__main__': unittest.main()
