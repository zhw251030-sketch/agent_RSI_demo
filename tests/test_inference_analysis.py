"""Audit-only regressions; no SDK, network or candidate execution."""
import copy
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
AUDITOR = (ROOT/'scripts/analyze_inference_policy.py' if (ROOT/'scripts/analyze_inference_policy.py').is_file()
           else ROOT/'tmp/analyze_inference_policy.py')
spec = importlib.util.spec_from_file_location('inference_auditor_under_test', AUDITOR)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class InferenceAuditorTests(unittest.TestCase):
    def assignment(self, missing_proposal=False, missing_review=False):
        updates = [dict(r, disposition='available', policy_available=True) for r in m.expected_updates()]
        actors = [dict(r, policy_available=True) for r in m.expected_actors()]
        if missing_proposal:
            for row in updates:
                if row['pair_id'] == 'p1':
                    row['disposition'] = 'missing' if row['condition'] == 'proposal' else 'skipped_dependency'
                    row['policy_available'] = False
            for row in actors:
                if row['policy_pair'] == 'p1': row['policy_available'] = False
        if missing_review:
            row = next(r for r in updates if r['session_id'] == 'p1-self')
            row.update(disposition='missing', policy_available=False)
            for row in actors:
                if row['policy_pair'] == 'p1' and row['condition'] == 'self': row['policy_available'] = False
        summary = {'status': 'attempts_completed', 'updates': updates, 'sessions': actors}
        actual = [r['session_id'] for r in updates if r['disposition'] != 'skipped_dependency']
        actual += [r['session_id'] for r in actors if r['policy_available']]
        rows = [{'session_id': name, 'request_id': f'request-{i:04d}'} for i, name in enumerate(actual, 1)]
        names = [r['session_id'] for r in m.expected_updates()+m.expected_actors()]
        return summary, rows, names

    def test_complete_assignment_and_known_missing_review_are_distinguished(self):
        for kwargs, count in [({}, 14), ({'missing_review': True}, 12), ({'missing_proposal': True}, 8)]:
            summary, rows, names = self.assignment(**kwargs)
            self.assertEqual(len(rows), count)
            m.verify_dispatch(summary, rows, names)

    def test_dispatch_cannot_hide_unrequested_available_slot(self):
        summary, rows, names = self.assignment()
        with self.assertRaises(ValueError): m.verify_dispatch(summary, rows[:-1], names)

    def test_dispatch_rejects_duplicate_reordered_or_unknown_session(self):
        summary, rows, names = self.assignment()
        for change in ('duplicate', 'reorder', 'unknown'):
            altered = copy.deepcopy(rows)
            if change == 'duplicate': altered[2]['session_id'] = altered[1]['session_id']
            elif change == 'reorder': altered[1]['session_id'], altered[2]['session_id'] = altered[2]['session_id'], altered[1]['session_id']
            else: altered[2]['session_id'] = 'not-assigned'
            with self.subTest(change=change), self.assertRaises(ValueError):
                m.verify_dispatch(summary, altered, names)

    def test_completed_run_cannot_call_skipped_dependency(self):
        summary, rows, names = self.assignment(missing_proposal=True)
        rows.insert(1, {'session_id': 'p1-self', 'request_id': ''})
        for i, row in enumerate(rows, 1): row['request_id'] = f'request-{i:04d}'
        with self.assertRaises(ValueError): m.verify_dispatch(summary, rows, names)

    def test_auxiliary_sdk_normalization_preserves_strings_and_nested_null(self):
        raw = {'rule_1': 'R01', 'rule_2': 'R02', 'rule_3': 'R03', 'rule_4': 'R04',
               'notes': '\u6c49'*3000, 'evidence_1': None, 'verdict_2': {'nested': None}}
        original = copy.deepcopy(raw)
        normalized = m.sdk_business_arguments(raw)
        self.assertEqual(raw, original)
        self.assertEqual(normalized['evidence_1'], '')
        self.assertEqual(normalized['verdict_2'], {'nested': None})
        self.assertEqual(normalized['notes'], original['notes'])
        self.assertEqual(set(normalized), set(original)|m.AUXILIARY_FIELDS)

    @staticmethod
    def request(feedback=None):
        return {'model': 'fixed-model', 'messages': [{'role': 'system', 'content': 'fixed'},
            {'role': 'user', 'content': json.dumps({'proposal': {'rule_1': 'R01'},
                'inference_feedback': feedback, 'shared_evidence': [1, 2]})}],
            'tools': [{'name': 'submit_policy'}]}

    def test_matched_review_removes_exactly_feedback(self):
        requests = {'p1-self': self.request(), 'p1-checked': self.request({'status': 'unknown'})}
        order = [r for r in m.expected_updates() if r['condition'] != 'proposal']
        results = m.verify_pairs(requests, order, 'inference_feedback')
        self.assertTrue(results[0]['both_requested'])
        self.assertFalse(results[1]['both_requested'])
        changed = copy.deepcopy(requests)
        changed['p1-checked']['tools'].append({'name': 'extra'})
        with self.assertRaises(ValueError): m.verify_pairs(changed, order, 'inference_feedback')

    def test_comparison_cannot_remove_proposal_or_other_evidence(self):
        for field in ('proposal', 'shared_evidence', 'premise_feedback'):
            with self.assertRaises(ValueError): m.common_request(self.request(), field)

    def test_config_and_assignment_bind_new_planning_state(self):
        config = json.loads((ROOT/m.CONFIG).read_bytes())
        summary, _, _ = self.assignment()
        m.validate_layout(config, summary)
        self.assertIn('P-H002', {r['state_id'] for r in m.expected_actors()})
        self.assertNotIn('P-B002', {r['state_id'] for r in m.expected_actors()})
        summary['sessions'][5]['state_id'] = 'P-B002'
        with self.assertRaises(ValueError): m.validate_layout(config, summary)

    def test_costs_count_actual_requests_without_imputing_missing_policy(self):
        from rsi_eval.pilot_budget import BudgetLedger
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'ledger.json'
            ledger = BudgetLedger(path, session_ids=['p1-proposal'], max_requests=1, max_requests_per_session=1)
            request = ledger.reserve('p1-proposal', {'model': 'offline'}, 128)
            ledger.settle(request, {'prompt_tokens': 100, 'completion_tokens': 20, 'total_tokens': 120})
            raw = json.loads(path.read_bytes())
            costs = m.cost_breakdown(raw)
            self.assertEqual(costs['all']['requests'], 1)
            self.assertEqual(costs['actor_checked']['requests'], 0)
            self.assertEqual(costs['all']['known_total_tokens'], 120)
            raw['requests'][0]['actual_estimated_cost_cny'] += 1
            with self.assertRaises(ValueError): m.cost_breakdown(raw)

    def test_output_must_be_new_and_outside_immutable_run(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)/'run'; run.mkdir()
            with self.assertRaises(ValueError): m.analyze(run, run/'audit.json', project_root=ROOT)
            output = Path(directory)/'exists.json'; output.write_text('{}')
            with self.assertRaises(ValueError): m.analyze(run, output, project_root=ROOT)

    def test_archived_run_recomputes_calls_checks_costs_and_development_results(self):
        archive = ROOT/'artifacts/inference-policy/2026-10-20/v01'
        self.assertTrue((archive/'summary.json').is_file(), 'Frozen run archive is required')
        with tempfile.TemporaryDirectory() as directory:
            report = m.analyze(archive, Path(directory)/'audit.json', project_root=ROOT)
        self.assertEqual(report['status'], 'verified', report.get('verification_failure'))
        self.assertEqual(report['counts']['requests'], 14)
        self.assertEqual(report['counts']['frozen_updates'], 6)
        self.assertEqual(report['counts']['generated_candidate_records'], 8)
        self.assertEqual(report['counts']['new_task_result_records'], 44)
        self.assertEqual(report['counts']['unique_new_evaluator_run_ids'], 44)
        self.assertEqual(len(report['inference_assessments']), 6)
        self.assertTrue(all(p['exact_common_request_equality'] for p in report['review_pairs']+report['actor_pairs']))
        self.assertTrue(report['run_files_unchanged'])
        self.assertEqual(report['new_model_calls'], 0)
        self.assertEqual(report['new_candidate_executions'], 0)

    def test_resealed_inference_check_tamper_is_rejected_semantically(self):
        archive = ROOT/'artifacts/inference-policy/2026-10-20/v01'
        def read(path): return json.loads(path.read_bytes())
        def write(path, value):
            path.write_bytes(json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2).encode('utf-8')+b'\n')
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)/'run'; shutil.copytree(archive, target)
            update = target/'p1-self'
            checks = read(update/'checks.json')
            checks['assessments'][1]['expected_verdict'] = 'supported'
            write(update/'checks.json', checks)
            frozen = read(update/'freeze.json')
            frozen['files']['checks.json'] = m.digest((update/'checks.json').read_bytes())
            frozen.pop('freeze_sha256'); frozen['freeze_sha256'] = m.digest(m.canonical(frozen))
            write(update/'freeze.json', frozen)
            phase = read(target/'update-phase-freeze.json')
            phase['slots']['p1-self']['files'] = m.tree_hashes(update)
            phase['slots']['p1-self']['freeze_sha256'] = m.digest((update/'freeze.json').read_bytes())
            write(target/'update-phase-freeze.json', phase)
            phase_hash = m.digest((target/'update-phase-freeze.json').read_bytes())
            for name in ('summary.json', 'evaluation-started.json'):
                value = read(target/name); value['phase_freeze_sha256'] = phase_hash; write(target/name, value)
            report = m.analyze(target, Path(directory)/'audit.json', project_root=ROOT)
        self.assertEqual(report['status'], 'error')
        self.assertEqual(report['verification_failure'], 'Saved policy or checks disagree with the submission')
        self.assertTrue(report['run_files_unchanged'])


if __name__ == '__main__': unittest.main()
