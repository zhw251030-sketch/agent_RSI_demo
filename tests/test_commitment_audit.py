"""Offline receipt, commitment and phase-boundary audit regression tests."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from rsi_eval.pilot_budget import BudgetLedger
from scripts.analyze_edit_commitment import (
    audit, audit_request, audit_budget, validate_draft, validate_candidate, validate_execution,
    validate_phase_freezes,
)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False).encode('utf-8')


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical(value))


class CommitmentAuditTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)

    def fixture(self, stage='draft', raw=None):
        tool = 'submit_draft' if stage == 'draft' else 'submit_candidate'
        business = dict(source='def get_plan(objects, init, goal):\n    return []\n',
                        n_params=0, rationale='keep the original', auxiliary={},
                        edit_claim='keep_ast', deployment_claim='raw_validation')
        directory = self.root / stage
        directory.mkdir()
        session = 'P-format-' + stage
        ledger = BudgetLedger(directory/'ledger.json', session_ids=[session],
                              max_requests=1, max_requests_per_session=1)
        payload = dict(model='anthropic/MiniMax-M3', max_output_tokens=4096,
                       messages=[{'role': 'user', 'content': '{}'}],
                       tools=[{'type': 'function', 'function': {'name': tool}}])
        rid = ledger.reserve(session, payload, 4096)
        usage = dict(prompt_tokens=100, completion_tokens=20, total_tokens=120)
        ledger.settle(rid, usage)
        row = json.loads((directory/'ledger.json').read_bytes())['requests'][0]
        response = dict(usage=usage, choices=[dict(message=dict(tool_calls=[dict(
            id='call-1', type='function', function=dict(name=tool,
            arguments=json.dumps(business if raw is None else raw))) ]),
            finish_reason='tool_calls')])
        write(directory/'requests'/f'{rid}.request.json', payload)
        write(directory/'requests'/f'{rid}.response.json', response)
        write(directory/'sdk-submission.json', dict(stage=stage, tool=tool,
              session_id=session, business=business))
        source_file = 'draft.py' if stage == 'draft' else 'candidate.py'
        (directory/source_file).write_bytes(business['source'].encode())
        artifact = dict(business, source_sha256=hashlib.sha256(business['source'].encode()).hexdigest(),
                        source_file=source_file, status='accepted' if stage == 'draft' else 'evaluated')
        if stage == 'draft':
            artifact.update(case_id='P-format', base_source_sha256='b'*64)
        return directory, row, ledger, response, artifact

    def call(self, fixture, stage='draft', artifact=True):
        directory, row, _, _, saved = fixture
        return audit_request(directory, row, stage=stage,
                             session_id='P-format-'+stage,
                             artifact=saved if artifact is True else artifact)

    def test_draft_binds_source_and_both_pre_feedback_claims(self):
        data = self.fixture()
        self.assertTrue(self.call(data)['submitted'])
        for key, value in [('edit_claim', 'general_edit'),
                           ('deployment_claim', 'probe_repair_deployed'),
                           ('n_params', 1), ('rationale', 'different'),
                           ('auxiliary', {'different': True})]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.call(data, artifact=dict(data[-1], **{key: value}))

    def test_review_binds_same_six_fields_to_final_candidate(self):
        data = self.fixture('review')
        self.assertTrue(self.call(data, 'review')['submitted'])
        with self.assertRaises(ValueError):
            self.call(data, 'review', artifact=dict(data[-1], edit_claim='general_edit'))

    def test_documented_sdk_defaults_and_top_level_metadata_only(self):
        raw = dict(source='def get_plan(objects, init, goal):\n    return []\n',
                   n_params=0, edit_claim='keep_ast', deployment_claim='raw_validation',
                   rationale='keep the original', auxiliary=None, summary='extra', security_risk=None)
        data = self.fixture(raw=raw)
        self.assertTrue(self.call(data)['submitted'])

    def test_rationale_default_matches_sdk_and_core(self):
        data = self.fixture()
        d, _, _, response, artifact = data
        raw = json.loads(response['choices'][0]['message']['tool_calls'][0]['function']['arguments'])
        del raw['rationale']
        response['choices'][0]['message']['tool_calls'][0]['function']['arguments'] = json.dumps(raw)
        write(d/'requests/request-0001.response.json', response)
        saved = json.loads((d/'sdk-submission.json').read_bytes())
        saved['business']['rationale'] = ''
        artifact['rationale'] = ''
        write(d/'sdk-submission.json', saved)
        self.assertTrue(self.call(data)['submitted'])

    def test_claims_are_required_and_never_inferred_from_rationale(self):
        data = self.fixture()
        d, _, _, response, _ = data
        for field in ('edit_claim', 'deployment_claim'):
            modified = copy.deepcopy(response)
            raw = json.loads(modified['choices'][0]['message']['tool_calls'][0]['function']['arguments'])
            del raw[field]
            modified['choices'][0]['message']['tool_calls'][0]['function']['arguments'] = json.dumps(raw)
            write(d/'requests/request-0001.response.json', modified)
            with self.subTest(field=field), self.assertRaises(ValueError): self.call(data)

    def test_wrong_enum_boolean_parameter_extra_field_and_deep_aux_reject(self):
        data = self.fixture()
        d, _, _, response, _ = data
        deep = {}
        for _ in range(25): deep = {'nested': deep}
        for key, value in [('edit_claim', 'remove_any_term'), ('deployment_claim', 'yes'),
                           ('n_params', False), ('extra', 1), ('auxiliary', deep)]:
            modified = copy.deepcopy(response)
            raw = json.loads(modified['choices'][0]['message']['tool_calls'][0]['function']['arguments'])
            raw[key] = value
            modified['choices'][0]['message']['tool_calls'][0]['function']['arguments'] = json.dumps(raw)
            write(d/'requests/request-0001.response.json', modified)
            with self.subTest(key=key), self.assertRaises(ValueError): self.call(data)

    def test_source_and_source_file_binding_are_strict(self):
        data = self.fixture()
        with self.assertRaises(ValueError): self.call(data, artifact=dict(data[-1], source_file='candidate.py'))
        (data[0]/'draft.py').write_bytes(b'changed')
        with self.assertRaises(ValueError): self.call(data)

    def test_sdk_session_and_normalized_business_cannot_change(self):
        data = self.fixture()
        saved = json.loads((data[0]/'sdk-submission.json').read_bytes())
        saved['session_id'] = 'other'
        write(data[0]/'sdk-submission.json', saved)
        with self.assertRaises(ValueError): self.call(data)

    def test_received_usage_and_request_envelope_are_bound(self):
        data = self.fixture()
        d, _, _, response, _ = data
        response['usage']['prompt_tokens'] = 101
        write(d/'requests/request-0001.response.json', response)
        with self.assertRaises(ValueError): self.call(data)
        response['usage']['prompt_tokens'] = 100
        write(d/'requests/request-0001.response.json', response)
        payload = json.loads((d/'requests/request-0001.request.json').read_bytes())
        payload['model'] = 'different'
        write(d/'requests/request-0001.request.json', payload)
        with self.assertRaises(ValueError): self.call(data)

    def test_finish_can_be_missing_but_cannot_create_artifact(self):
        data = self.fixture()
        d, _, _, response, _ = data
        response['choices'][0]['message']['tool_calls'][0]['function'] = dict(name='finish', arguments='{}')
        write(d/'requests/request-0001.response.json', response)
        (d/'sdk-submission.json').unlink()
        with self.assertRaises(ValueError): self.call(data)
        (d/'draft.py').unlink()
        self.assertFalse(self.call(data, artifact=None)['submitted'])

    def test_core_rejection_needs_matching_attempt_and_no_source_artifact(self):
        data = self.fixture()
        (data[0]/'draft.py').unlink()
        with self.assertRaises(ValueError): self.call(data, artifact=None)
        write(data[0]/'attempts.json', [dict(session_id='P-format-draft', status='invalid_request')])
        self.assertTrue(self.call(data, artifact=None)['submitted'])

    def test_invalid_business_can_be_missing_without_dispatch(self):
        data = self.fixture()
        d, _, _, response, _ = data
        response['choices'][0]['message']['tool_calls'][0]['function']['arguments'] = '{}'
        write(d/'requests/request-0001.response.json', response)
        (d/'sdk-submission.json').unlink(); (d/'draft.py').unlink()
        self.assertFalse(self.call(data, artifact=None)['submitted'])

    def test_valid_business_cannot_lose_sdk_submission(self):
        data = self.fixture()
        (data[0]/'sdk-submission.json').unlink(); (data[0]/'draft.py').unlink()
        with self.assertRaises(ValueError): self.call(data, artifact=None)

    def test_known_response_contract_failure_is_missing_not_repaired(self):
        data = self.fixture()
        d, row, _, response, _ = data
        response['choices'][0]['message']['tool_calls'] *= 2
        response['error_type'] = 'PilotResponseContractError'
        row.update(error_type='PilotResponseContractError', status='failed')
        write(d/'requests/request-0001.response.json', response)
        (d/'sdk-submission.json').unlink(); (d/'draft.py').unlink()
        self.assertFalse(self.call(data, artifact=None)['submitted'])

    def test_unknown_usage_and_other_transport_failure_never_complete(self):
        data = self.fixture()
        data[1]['usage_state'] = 'unknown'
        with self.assertRaises(ValueError): self.call(data)

    def test_draft_record_does_not_invent_evaluation(self):
        data = self.fixture(); d, _, _, _, draft = data
        case = dict(id='P-format', source_sha256='b'*64, n_params=0)
        validate_draft(case, draft, d)
        bad = dict(draft, results=[{'status': 'success'}])
        with self.assertRaises(ValueError): validate_draft(case, bad, d)
        for key, value in [('case_id', 'S-x5'), ('base_source_sha256', 'a'*64)]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_draft(case, dict(draft, **{key:value}), d)

    def test_final_commitment_record_and_original_claim_comparison_are_bound(self):
        from rsi_eval.commitment_core import check_submission, review_change
        from rsi_eval.decision_cases import load_cases
        from rsi_eval.decision_core import summarize_scores
        from rsi_eval.two_stage_core import classify_edit, check_forecast
        root = Path(__file__).resolve().parents[1]
        case = next(c for c in load_cases(root) if c['id'] == 'S-x5')
        source_dir = root/'artifacts/decision-replay/2026-10-21/v01/sessions/S-x5-r1-hidden'
        old = json.loads((source_dir/'candidate.json').read_bytes())
        business = dict(source=case['source'], n_params=case['n_params'], rationale='keep',
                        auxiliary={}, edit_claim='keep_ast', deployment_claim='unspecified')
        directory = self.root/'candidate'; directory.mkdir()
        (directory/'candidate.py').write_bytes(business['source'].encode())
        results = copy.deepcopy(old['results'])
        for index, record in enumerate(results):
            record['strategy_version'] = 'edit-commitment-v0.1'
            write(directory/f'evaluations/evaluation-{index:02d}.json', record)
        candidate = dict(old, results=results, rationale=business['rationale'], auxiliary={},
                         edit_claim=business['edit_claim'], deployment_claim=business['deployment_claim'])
        candidate['score'] = summarize_scores(case, results, case['n_params'])
        candidate['edit'] = classify_edit(case, case['source'], case['n_params'])
        candidate['forecast'] = check_forecast(case, None, candidate['score'])
        candidate['commitment_check'] = check_submission(case, business, root)
        candidate['review_change'] = review_change(case, business, business, root)
        final = dict(business, source_sha256=candidate['source_sha256'],
                     commitment_check=candidate['commitment_check'], review_change=candidate['review_change'])
        write(directory/'final-commitment.json', final)
        validate_candidate(root, case, business, candidate, directory)
        bad = copy.deepcopy(candidate)
        bad['review_change']['original_commitment_repaired'] = True
        with self.assertRaises(ValueError): validate_candidate(root, case, business, bad, directory)
        final['edit_claim'] = 'general_edit'
        write(directory/'final-commitment.json', final)
        with self.assertRaises(ValueError): validate_candidate(root, case, business, candidate, directory)

    def test_native_budget_summary_and_tampering(self):
        d, _, ledger, _, _ = self.fixture()
        stored = json.loads((d/'ledger.json').read_bytes())
        audit_budget(stored, ledger.summary(), stored['config'])
        for key in ('request_count', 'known_total_tokens', 'reserved_cost_cny'):
            summary = copy.deepcopy(ledger.summary()); summary[key] += 1
            with self.subTest(key=key), self.assertRaises(ValueError):
                audit_budget(stored, summary, stored['config'])

    def test_execution_requires_frozen_cap_and_exact_per_event_counts(self):
        counts = dict(sandbox_calls=1, new_candidate_executions=1, host_validations=1,
                      val_calls=1, fit_calls=0, predict_calls=0)
        event = dict(label='P-format-self:task', reserved=1, complete=True, counts=counts)
        execution = dict(max_sandbox_calls=48, reserved_sandbox_calls=1, events=[event])
        summary = dict(reserved_sandbox_calls=1, actual=counts, accounting_complete=True)
        expected = [('P-format-self:task', 1, counts)]
        validate_execution(execution, summary, counts, expected)
        for change in ('cap', 'label', 'count', 'incomplete'):
            bad = copy.deepcopy(execution)
            if change == 'cap': bad['max_sandbox_calls'] = 96
            if change == 'label': bad['events'][0]['label'] = 'different'
            if change == 'count': bad['events'][0]['counts']['fit_calls'] = 1
            if change == 'incomplete': bad['events'][0]['complete'] = False
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_execution(bad, summary, counts, expected)

    def test_phase_freeze_links_and_every_draft_file_are_bound(self):
        run = self.root/'run'; (run/'drafts'/'P-format').mkdir(parents=True)
        (run/'drafts'/'P-format'/'draft.py').write_bytes(b'original')
        files = {'P-format/draft.py': hashlib.sha256(b'original').hexdigest()}
        drafts = {'P-format': {'source': 'original'}}
        write(run/'draft-freeze.json', dict(drafts=drafts, files=files))
        draft_hash = hashlib.sha256((run/'draft-freeze.json').read_bytes()).hexdigest()
        feedback = {'P-format': {'status': 'unknown'}}
        write(run/'feedback-freeze.json', dict(feedback=feedback, draft_freeze_sha256=draft_hash))
        report = dict(draft_freeze_sha256=draft_hash,
                      feedback_freeze_sha256=hashlib.sha256((run/'feedback-freeze.json').read_bytes()).hexdigest())
        validate_phase_freezes(run, report, drafts, feedback)
        (run/'drafts'/'P-format'/'draft.py').write_bytes(b'changed')
        with self.assertRaises(ValueError): validate_phase_freezes(run, report, drafts, feedback)

    def integration_fixture(self, missing=()):
        """Synthetic transport and copied old result records; zero candidate execution."""
        from rsi_eval.decision_cases import load_cases
        from scripts.run_edit_commitment import (
            ROOT, CONFIG_PATH, PROTOCOL, CASE_ORDER, draft_order, review_order,
            freeze_inputs, execute, ExecutionLedger,
        )
        root = ROOT; run = self.root/'full-run'; run.mkdir()
        available = {c['id']:c for c in load_cases(root)}
        cases = {key:available[key] for key in CASE_ORDER}
        config = json.loads((root/CONFIG_PATH).read_bytes())
        frozen = dict(runtime_commit='a'*40, checkout_clean=True,
                      runtime_files_sha256={PROTOCOL:hashlib.sha256((root/PROTOCOL).read_bytes()).hexdigest()})
        report = dict(run_id='synthetic-audit-fixture', status='running',
                      sealed_tasks_executed=0, new_probe_executions=0, draft_executions=0,
                      strategy_updated=False, model_weights_updated=False, resumed=False,
                      drafts=draft_order(), reviews=review_order(), **frozen)
        write(run/'config.json', config); write(run/'runtime-freeze.json', frozen)
        report['inputs_freeze_sha256'] = freeze_inputs(run, cases)
        ledger = BudgetLedger(run/'budget-ledger.json',
            session_ids=[r['session_id'] for r in report['drafts']+report['reviews']], **config['budgets'])
        executions = ExecutionLedger(run/'execution-ledger.json', 48)
        def session(controller, slot, directory):
            stage = slot['stage']; tool = 'submit_draft' if stage == 'draft' else 'submit_candidate'
            payload = dict(model='synthetic-no-provider', max_output_tokens=4096,
                messages=[dict(role='user', content=canonical(controller.task_packet()).decode())],
                tools=[dict(type='function', function=dict(name=tool))])
            rid = ledger.reserve(slot['session_id'], payload, 4096)
            usage = dict(prompt_tokens=20, completion_tokens=10, total_tokens=30)
            ledger.settle(rid, usage)
            write(directory/'requests'/f'{rid}.request.json', payload)
            business = dict(source=controller.case['source'], n_params=controller.case['n_params'],
                rationale='', auxiliary={}, edit_claim='keep_ast', deployment_claim='unspecified')
            is_missing = stage == 'draft' and slot['case_id'] in missing
            function = dict(name='finish', arguments='{}') if is_missing else dict(name=tool, arguments=json.dumps(business))
            response = dict(usage=usage, choices=[dict(message=dict(tool_calls=[dict(id='offline',type='function',function=function)]),finish_reason='tool_calls')])
            write(directory/'requests'/f'{rid}.response.json', response)
            if not is_missing:
                write(directory/'sdk-submission.json',dict(stage=stage,tool=tool,
                    session_id=slot['session_id'],business=business))
                controller.submit(session_id=slot['session_id'], **business)
            return dict(status='completed')
        def copied_record(family, task_id, source, **kwargs):
            case = next(c for c in cases.values() if c['source_sha256'] == kwargs['parent_id'])
            record = copy.deepcopy(next(r for r in case['baseline_results'] if r['task_id'] == task_id))
            phases = [{'phase':'plan'}] if family == 'planning' else [{'phase':'fit'},{'phase':'predict'}]
            record.update(family=family, executions=phases,
                          candidate_hash=hashlib.sha256(source.encode()).hexdigest(),
                          candidate_id=kwargs['candidate_id'], parent_id=kwargs['parent_id'],
                          strategy_version=kwargs['strategy_version'], sealed_tasks_executed=0, model_calls=0)
            return record
        execute(root, run, report, cases, ledger, executions, session, copied_record)
        return root, run, report

    def integration_audit(self, root, run):
        def git_blob(command):
            self.assertEqual(command[:3], ['git', '-C', str(root)])
            self.assertEqual(command[3], 'show')
            commit, path = command[4].split(':', 1)
            self.assertEqual(commit, 'a'*40)
            return (root/path).read_bytes()
        # Only the synthetic Git anchor is mocked. Receipt/phase/candidate/budget
        # bindings use real audit code and synthetic files produced by the runner.
        with patch('scripts.analyze_edit_commitment.subprocess.check_output', side_effect=git_blob), \
             patch('rsi_eval.executor.evaluate_candidate', side_effect=AssertionError('execution')), \
             patch('socket.socket.connect', side_effect=AssertionError('network')):
            return audit(root, run)

    def test_complete_synthetic_runner_output_passes_all_bindings(self):
        root, run, _ = self.integration_fixture()
        result = self.integration_audit(root, run)
        self.assertEqual((result['model_requests'],result['accepted_drafts'],
                          result['candidate_submissions'],result['matched_request_pairs']), (12,4,8,4))
        self.assertEqual(result['executions']['new_candidate_executions'],44)

    def test_missing_shared_draft_skips_exactly_two_reviews_in_full_audit(self):
        root, run, _ = self.integration_fixture(missing=('P-format',))
        result = self.integration_audit(root, run)
        self.assertEqual((result['model_requests'],result['accepted_drafts'],
                          result['skipped_reviews'],result['matched_request_pairs']), (10,3,2,3))

    def test_all_drafts_missing_is_a_valid_empty_review_allocation(self):
        root, run, _ = self.integration_fixture(missing=('P-format','S-v3','P-empty','S-x5'))
        result = self.integration_audit(root, run)
        self.assertEqual((result['model_requests'],result['candidate_submissions'],
                          result['skipped_reviews'],result['matched_request_pairs']), (4,0,8,0))

    def test_full_audit_rejects_relabelled_frozen_feedback_or_draft_identity(self):
        root, run, report = self.integration_fixture()
        original = (run/'feedback-freeze.json').read_bytes()
        changed = json.loads(original)
        changed['feedback']['P-format']['edit_claim']['status'] = 'contradicted'
        write(run/'feedback-freeze.json', changed)
        report['feedback_freeze_sha256'] = hashlib.sha256((run/'feedback-freeze.json').read_bytes()).hexdigest()
        write(run/'summary.json', report)
        with self.assertRaisesRegex(ValueError,'feedback differs'):
            self.integration_audit(root, run)


if __name__ == '__main__': unittest.main()
