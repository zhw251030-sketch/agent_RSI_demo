"""Grounded audit preserves allowed contrasts, missingness and denominators."""
import copy
import importlib
import importlib.util
import json
import hashlib
from pathlib import Path
import subprocess
import shutil
import tempfile
import unittest


class GroundedAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('scripts.analyze_grounded_policy'))
        self.audit = importlib.import_module('scripts.analyze_grounded_policy')

    def request(self, field, value):
        packet = {'task_text': 'same', 'evidence': ['same'], field: value}
        return {'model': 'same', 'messages': [{'role': 'system', 'content': 'same'},
                {'role': 'user', 'content': json.dumps(packet)}], 'tools': ['same']}

    def test_review_and_actor_contrasts_remove_only_one_authorized_field(self):
        for field in ('premise_feedback', 'repair_policy'):
            a, b = self.request(field, None), self.request(field, {'changed': True})
            self.assertEqual(self.audit.common_request(a, field), self.audit.common_request(b, field))
            b['tools'] = ['different']
            self.assertNotEqual(self.audit.common_request(a, field), self.audit.common_request(b, field))
            b = self.request(field, {'changed': True})
            packet = json.loads(b['messages'][1]['content']); packet['experience_memory'] = ['leak']
            b['messages'][1]['content'] = json.dumps(packet)
            self.assertNotEqual(self.audit.common_request(a, field), self.audit.common_request(b, field))

    def test_missing_pair_is_explicit_and_unequal_common_request_is_rejected(self):
        order = [r for r in self.audit.expected_updates() if r['condition'] != 'proposal']
        requests = {r['session_id']: self.request('premise_feedback', r['condition']) for r in order}
        proofs = self.audit.verify_pairs(requests, order, 'premise_feedback')
        self.assertEqual(len(proofs), 2)
        self.assertTrue(all(p['both_requested'] for p in proofs))
        del requests[order[0]['session_id']]
        proofs = self.audit.verify_pairs(requests, order, 'premise_feedback')
        self.assertFalse(proofs[0]['both_requested'])
        requests[order[0]['session_id']] = self.request('premise_feedback', None)
        requests[order[0]['session_id']]['model'] = 'different'
        with self.assertRaises(ValueError): self.audit.verify_pairs(requests, order, 'premise_feedback')

    def test_fourteen_dispatches_are_fixed_and_partial_must_be_prefix(self):
        names = [r['session_id'] for r in self.audit.expected_updates()+self.audit.expected_actors()]
        rows = [{'request_id': 'request-'+str(i).zfill(4), 'session_id': name}
                for i, name in enumerate(names, 1)]
        self.audit.verify_dispatch({'status': 'attempts_completed'}, rows, names)
        self.audit.verify_dispatch({'status': 'update_not_frozen'}, rows[:2], names)
        for bad in (rows[:-1], rows[:2]+rows[3:]):
            with self.assertRaises(ValueError):
                self.audit.verify_dispatch({'status': 'attempts_completed'}, bad, names)

    def test_costs_separate_shared_proposals_reviews_and_actors(self):
        names = ['p1-proposal', 'p1-self', 'p1-checked', 'p1-P-A002-self']
        rows = [{'session_id': name, 'usage_state': 'known', 'input_bytes': 100,
                 'input_token_reservation': 8292, 'output_token_reservation': 4096,
                 'reserved_cost_cny': .0518196, 'usage': {'prompt_tokens': 1000,
                 'completion_tokens': 100, 'total_tokens': 1100}, 'actual_estimated_cost_cny': .00294}
                for name in names]
        ledger = {'config': {'input_cny_per_million': 2.1, 'output_cny_per_million': 8.4}, 'requests': rows}
        costs = self.audit.cost_breakdown(ledger)
        self.assertEqual(costs['all']['known_total_tokens'], 4400)
        self.assertEqual(costs['update_proposal']['requests'], 1)
        self.assertEqual(costs['actor_self']['requests'], 1)
        rows[-1].update(usage_state='unknown', usage=None)
        self.assertIsNone(self.audit.cost_breakdown(ledger)['all']['actual_total_tokens'])
        rows[0]['actual_estimated_cost_cny'] = 0
        with self.assertRaises(ValueError): self.audit.cost_breakdown(ledger)

    def test_policy_call_ignores_only_sdk_metadata(self):
        args = {'rule_1': 'R01', 'summary': 'sdk', 'security_risk': 'LOW'}
        response = {'choices': [{'message': {'tool_calls': [{'function': {
            'name': 'submit_policy', 'arguments': json.dumps(args)}}]}}]}
        self.assertEqual(self.audit.policy_arguments(response), {'rule_1': 'R01'})
        args['unexpected'] = 'keep and reject downstream'
        response['choices'][0]['message']['tool_calls'][0]['function']['arguments'] = json.dumps(args)
        self.assertIn('unexpected', self.audit.policy_arguments(response))

    def test_update_packet_checks_exact_fact_projection_and_only_declared_feedback(self):
        from rsi_eval.policy_cases import load_update_bundle
        bundle = load_update_bundle(self.audit.ROOT)
        packet = self.audit.expected_update_packet(bundle, 'p1', None, None)
        self.assertEqual(len(packet['factual_catalogue']), 48)
        self.assertIsNone(packet['premise_feedback'])
        self.assertEqual(packet['experience_cases'], bundle['cases'])
        self.assertNotIn('incumbent', packet)

    def test_missing_child_retains_null_endpoint(self):
        baseline = {'status': 'evaluated', 'metrics': {'mse': .2, 'nmse': .1},
                    'results': [{'task_id': 'oscillator1', 'status': 'success',
                                 'metrics': {'mse': .2, 'nmse': .1}}]}
        endpoint = self.audit.compute_endpoint([baseline], 'symbolic')
        self.assertIsNone(endpoint['child_score'])
        self.assertEqual(endpoint['new_task_result_records'], 0)

    def test_output_cannot_overwrite_or_live_inside_run(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); run = root/'run'; run.mkdir()
            existing = root/'audit.json'; existing.write_text('original')
            for output in (existing, run/'audit.json'):
                with self.assertRaises(ValueError): self.audit.analyze(run, output)
            self.assertEqual(existing.read_text(), 'original')

    def update_fixture(self, root):
        from rsi_eval.policy_cases import load_update_bundle
        from rsi_eval.grounded_policy import GroundedPolicyController, freeze_policy, factual_catalogue
        from rsi_eval.revision_policy import S0, RULES
        bundle = load_update_bundle(self.audit.ROOT)
        directory = root/'p1-proposal'
        controller = GroundedPolicyController(bundle, S0, directory, pair_id='p1')
        submission = {}
        for i, rule in enumerate(S0['rule_ids'], 1):
            submission.update({f'rule_{i}':rule, f'parent_{i}':True, f'quote_{i}':RULES[rule],
                f'support_{i}':'both', f'hypothesis_{i}':'Fixture hypothesis', f'edit_{i}':'Fixture edit'})
        facts = factual_catalogue(bundle)
        for i, family in enumerate(('planning', 'symbolic'), 1):
            fact = next(f for f in facts if f['family'] == family)
            submission.update({f'fact_{i}_id':fact['fact_id'], f'fact_{i}_value':json.dumps(fact['value']),
                               f'fact_{i}_scope':fact['scope']})
        controller.submit_policy(**submission)
        freeze_policy(directory, bundle, S0, 'request-0001', pair_id='p1')
        blob = (self.audit.ROOT/'rsi_eval/pilot_agent.py').read_bytes()
        system = self.audit._literal_assignment(blob, 'POLICY_UPDATE_SYSTEM_PROMPT')
        packet = controller.state_packet()
        request = {'model':'fixture-model', 'messages':[{'role':'system', 'content':system},
            {'role':'user', 'content':json.dumps(packet)}], 'max_output_tokens':4096,
            'tools':[{'function':{'name':name}} for name in ('submit_policy','finish')]}
        usage = {'prompt_tokens':1000,'completion_tokens':100,'total_tokens':1100}
        response = {'response_id':'fixture-response','usage':usage,'choices':[{'message':{'tool_calls':[{'id':'fixture-call','function':{
            'name':'submit_policy','arguments':json.dumps(dict(submission,summary='SDK',security_risk='LOW'))}}]}}]}
        raw = self.audit.canonical(request)
        reservation = {'request_id':'request-0001','session_id':'p1-proposal','status':'settled',
            'usage_state':'known','usage':usage,'usage_sha256':self.audit.digest(self.audit.canonical(usage)),
            'payload_sha256':self.audit.digest(raw),'input_bytes':len(raw),'output_token_reservation':4096}
        requests = directory/'requests'; requests.mkdir()
        def write(path, value): path.write_bytes(self.audit.canonical(value))
        write(directory/'task-packet.json', packet)
        write(requests/'request-0001.request.json', request)
        write(requests/'request-0001.response.json', response)
        write(requests/'packet-0001.json', packet)
        write(requests/'input-audit-0001.json', {'request_id':'request-0001','request_reserved':True,
            'network_dispatch_attempted':True,'transport_called':True,'payload_sha256':self.audit.digest(raw),
            'actual_input_bytes':len(raw)})
        (directory/'events.jsonl').write_text('\n'.join(json.dumps({'type':kind,'tool_name':'submit_policy',
            'tool_call_id':'fixture-call', **({'llm_response_id':'fixture-response'} if kind=='ActionEvent' else {})})
            for kind in ('ActionEvent','ObservationEvent')), encoding='utf-8')
        phase = {'freezes':{'p1-proposal':self.audit.digest((directory/'freeze.json').read_bytes())}}
        args = (directory,self.audit.expected_updates()[0],{'selected_policy':S0},reservation,bundle,None,None,
            {'rsi_eval/pilot_agent.py':blob},{'config':{'max_input_bytes':98304,'max_output_tokens':4096}},
            {'effective_model_config':{'model':'fixture-model'}},phase)
        return args

    def test_frozen_update_recomputes_checks_and_matches_exact_sdk_business_arguments(self):
        with tempfile.TemporaryDirectory() as temp:
            args = self.update_fixture(Path(temp))
            entry, request, policy = self.audit.verify_update(*args)
            self.assertTrue(entry['frozen']); self.assertTrue(entry['checks']['all_checked_pass'])
            response_path = args[0]/'requests/request-0001.response.json'
            response = json.loads(response_path.read_bytes())
            call = response['choices'][0]['message']['tool_calls'][0]['function']
            arguments = json.loads(call['arguments']); arguments['edit_1'] = 'Changed actual model edit'
            call['arguments'] = json.dumps(arguments); response_path.write_text(json.dumps(response))
            with self.assertRaisesRegex(ValueError, 'exact model call'):
                self.audit.verify_update(*args)

    def test_phase_anchor_and_factual_check_tampering_are_rejected(self):
        for target in ('phase', 'checks'):
            with self.subTest(target=target), tempfile.TemporaryDirectory() as temp:
                args = self.update_fixture(Path(temp))
                if target == 'phase': args[-1]['freezes']['p1-proposal'] = '0'*64
                else:
                    path = args[0]/'checks.json'; checks = json.loads(path.read_bytes())
                    checks['all_checked_pass'] = False; path.write_text(json.dumps(checks))
                with self.assertRaises(ValueError): self.audit.verify_update(*args)

    def test_source_provenance_pins_new_protocol_and_reads_commit_not_worktree(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); prompt = root/'prompts/fixed.md'; prompt.parent.mkdir()
            prompt.write_bytes(b'fixed\n')
            protocol = root/self.audit.PROTOCOL; protocol.parent.mkdir(parents=True)
            protocol.write_bytes(b'new frozen protocol\n')
            def git(*args): return subprocess.check_output(['git',*args],cwd=root,stderr=subprocess.DEVNULL)
            git('init','-q'); git('add','.')
            git('-c','user.name=Audit Test','-c','user.email=audit@example.invalid','commit','-qm','fixture')
            commit = git('rev-parse','HEAD').decode().strip()
            sources = {p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in (prompt,protocol)}
            summary = {'code_commit':commit,'source_sha256':sources}
            prompt.write_bytes(b'changed later\n')
            self.assertEqual(self.audit.verify_sources(summary,root)['prompts/fixed.md'],b'fixed\n')
            summary['source_sha256'].pop(self.audit.PROTOCOL)
            with self.assertRaises(ValueError): self.audit.verify_sources(summary,root)

    def archived_run(self):
        for name in ('artifacts/grounded-policy/2026-10-20/v01-stopped', 'tmp/grounded-policy-v01-evidence'):
            root = self.audit.ROOT/name
            if (root/'summary.json').exists(): return root
        self.skipTest('Actual stopped grounded-policy archive is not available in this checkout')

    def test_actual_stopped_round_is_partial_and_preserves_unaccepted_model_text(self):
        source = self.archived_run()
        with tempfile.TemporaryDirectory() as temp:
            report = self.audit.analyze(source, Path(temp)/'audit.json')
        self.assertEqual(report['status'], 'verified_partial')
        self.assertEqual(report['counts']['requests'], 2)
        self.assertEqual(report['counts']['frozen_updates'], 1)
        self.assertEqual(report['counts']['generated_candidate_records'], 0)
        self.assertFalse(report['verification']['actor_pair_equality_observed'])
        self.assertFalse(report['verification']['review_pair_equality_observed'])
        second = report['updates'][1]
        self.assertFalse(second['accepted']); self.assertFalse(second['frozen'])
        self.assertEqual(len(second['literal_submission']['hypothesis_3']), 280)
        self.assertEqual(second['schema_length_issues'], [{'field':'hypothesis_3',
            'actual_characters':280,'maximum_characters':240,'source':'exact_dispatched_tool_schema',
            'status':'exceeds_maxLength'}])
        self.assertEqual(second['event_counts'], {'actions':1,'observations':0,'agent_errors':1})
        self.assertFalse(second['controller_attempt_record_exists'])
        self.assertEqual(report['costs']['all']['known_total_tokens'],20550)
        self.assertTrue(report['run_files_unchanged'])

    def test_actual_negative_copies_reject_request_usage_checks_freeze_response_and_event_edits(self):
        source = self.archived_run()
        def change_call(response):
            call = response['choices'][0]['message']['tool_calls'][0]['function']
            arguments = json.loads(call['arguments']); arguments['edit_1'] = 'tampered'
            call['arguments'] = json.dumps(arguments)
        variants = [
            ('request_model', 'p1-proposal/requests/request-0001.request.json', lambda d:d.update(model='changed')),
            ('request_tool', 'p1-self/requests/request-0002.request.json', lambda d:d['tools'].pop()),
            ('response_usage', 'p1-self/requests/request-0002.response.json', lambda d:d['usage'].update(completion_tokens=1)),
            ('fact_checks', 'p1-proposal/checks.json', lambda d:d.update(all_checked_pass=False)),
            ('freeze_request', 'p1-proposal/freeze.json', lambda d:d.update(request_id='request-0002')),
            ('literal_response', 'p1-proposal/requests/request-0001.response.json', change_call),
            ('dispatch_order', 'budget-ledger.json', lambda d:d['requests'][1].update(session_id='p1-checked')),
            ('complete_overclaim', 'summary.json', lambda d:d.update(status='attempts_completed')),
            ('known_cost', 'budget-ledger.json', lambda d:d['requests'][0].update(actual_estimated_cost_cny=0)),
        ]
        for label, relative, mutate in variants:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temp:
                root = Path(temp); run = root/'copy'; shutil.copytree(source,run)
                path = run/relative; value = json.loads(path.read_bytes()); mutate(value)
                path.write_text(json.dumps(value),encoding='utf-8')
                report = self.audit.analyze(run,root/'audit.json')
                self.assertEqual(report['status'],'error')
                self.assertTrue(report['run_files_unchanged'])
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); run = root/'copy'; shutil.copytree(source,run)
            path = run/'p1-proposal/events.jsonl'
            events = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]
            next(e for e in events if e['type']=='ActionEvent')['tool_call_id'] = 'wrong-call'
            path.write_text('\n'.join(json.dumps(e) for e in events),encoding='utf-8')
            report = self.audit.analyze(run,root/'audit.json')
            self.assertEqual(report['status'],'error')
            self.assertIn('bind exact saved',report['verification_failure'])


if __name__ == '__main__': unittest.main()
