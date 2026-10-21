"""Bounded successor scheduling, business/prose separation and frozen history."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from extensions.basis_trial_v01 import run as previous
from extensions.symbolic_basis_v01.executor import canonical, sha, write
from . import run


class TrialTests(unittest.TestCase):
    def setUp(self): self.tmp = tempfile.TemporaryDirectory()
    def tearDown(self): self.tmp.cleanup()

    def test_same_research_allocation_and_order(self):
        old, new = previous.design(), run.design()
        self.assertNotEqual(old.pop('version'), new.pop('version'))
        self.assertEqual(old, new)
        self.assertEqual(len(new['slots']), 13)
        self.assertEqual(len({s['id'] for s in new['slots']}), 13)

    def test_actor_context_differs_only_by_policy_and_requests_ids(self):
        common = {'parent': run.design()['parents']['A'], 'feedback': {'nmse': .3}}
        a = run.actor_packet(common, run.S0)
        b = run.actor_packet(common, {'version': run.S0['version'], 'rule_ids': ['R01','R02','R05','R08']})
        self.assertEqual(run.common_packet(a), run.common_packet(b))
        self.assertNotEqual(a['repair_policy'], b['repair_policy'])
        self.assertIn('feature_ids only', a['task_text'])
        self.assertNotIn('Explain', a['task_text'])
        a['current_state']['feedback']['nmse'] = 99
        self.assertEqual(common['feedback']['nmse'], .3)

    def exercise(self, fail=None, proposal=None, actor_mutation=None):
        directory = Path(self.tmp.name)/('run'+str(len(list(Path(self.tmp.name).iterdir()))))
        calls, packets, children = [], [], []
        def session(slot, packet):
            calls.append(('request', slot['id']))
            packets.append(copy.deepcopy(packet))
            if slot['id'] == fail: raise RuntimeError('injected')
            if slot['stage'] == 'update':
                return {'status': 'accepted', 'business': proposal if proposal is not None else {'rule_ids': run.S0['rule_ids']},
                        'assistant_text': 'UNTRUSTED_PROPOSAL_TEXT_'*1000}
            self.assertTrue((directory/'policy-freeze.json').exists())
            ids = copy.deepcopy(packet['current_state']['parent']['payload']['feature_ids'])
            result = {'status': 'accepted', 'business': {'feature_ids': ids},
                      'execution_payload': {'feature_ids': ids, 'explanation': run.HOST_EXPLANATION},
                      'assistant_text': 'UNTRUSTED_ACTOR_TEXT_'*1000}
            if actor_mutation: actor_mutation(result)
            return result
        def measure(parent, child, out):
            self.assertTrue((directory/'policy-freeze.json').exists())
            calls.append(('measure', out.name)); children.append(copy.deepcopy(child))
            return {'status': 'success', 'metrics': {'nmse': .25}, 'feedback': {'nmse': .25},
                    'n_params': 4, 'sandbox_calls': 2, 'fit_attempts': 1, 'prediction_calls': 1}
        result = run.orchestrate(directory, run.design(), {'old_history': True}, session, measure)
        return directory, result, calls, packets, children

    def test_freeze_before_data_and_no_prose_or_child_feedback_enters_actor(self):
        directory, result, calls, packets, children = self.exercise()
        self.assertEqual(result['status'], 'complete')
        self.assertTrue(result['policy_no_change'])
        self.assertEqual(sum(c[0]=='request' for c in calls), 13)
        self.assertEqual(sum(c[0]=='measure' for c in calls), 14)
        self.assertEqual(calls[0], ('request', 'update'))
        for packet in packets[1:]:
            self.assertNotIn('UNTRUSTED_', json.dumps(packet))
            self.assertEqual(packet['current_state']['feedback'], {'nmse': .25})
        for child in children[2:]:
            self.assertEqual(set(child), {'feature_ids','explanation'})
            self.assertEqual(child['explanation'], run.HOST_EXPLANATION)
        with self.assertRaises(FileExistsError): run.orchestrate(directory, run.design(), {}, None, None)

    def test_update_failure_prevents_all_data_access(self):
        _, result, calls, _, _ = self.exercise(fail='update')
        self.assertEqual(result['status'], 'stopped')
        self.assertEqual(calls, [('request','update')])

    def test_policy_extra_business_field_stops_before_data(self):
        _, result, calls, _, _ = self.exercise(proposal={'rule_ids': run.S0['rule_ids'], 'explanation': 'must not be business'})
        self.assertEqual(result['status'], 'stopped')
        self.assertEqual(len(calls), 1)

    def test_invalid_policy_stops_before_data(self):
        _, result, calls, _, _ = self.exercise(proposal={'rule_ids': ['R01']*4})
        self.assertEqual(result['status'], 'stopped')
        self.assertEqual(len(calls), 1)

    def test_actor_failure_stops_without_recovery(self):
        _, result, calls, _, _ = self.exercise(fail='A-r1-S1')
        self.assertEqual(result['status'], 'stopped')
        self.assertEqual(sum(c[0]=='request' for c in calls), 3)
        self.assertEqual(sum(c[0]=='measure' for c in calls), 3)

    def test_actor_execution_payload_cannot_change_ids(self):
        def mutate(row): row['execution_payload']['feature_ids'] = ['m_0_0','m_0_1','m_1_0','m_2_0']
        _, result, calls, _, _ = self.exercise(actor_mutation=mutate)
        self.assertEqual(result['status'], 'stopped')
        self.assertEqual(sum(c[0]=='measure' for c in calls), 2)

    def test_actor_execution_payload_cannot_include_model_explanation(self):
        def mutate(row): row['execution_payload']['explanation'] = 'model text'
        _, result, calls, _, _ = self.exercise(actor_mutation=mutate)
        self.assertEqual(result['status'], 'stopped')
        self.assertEqual(sum(c[0]=='measure' for c in calls), 2)

    def test_actor_business_cannot_include_explanation(self):
        def mutate(row): row['business']['explanation'] = 'model text'
        _, result, calls, _, _ = self.exercise(actor_mutation=mutate)
        self.assertEqual(result['status'], 'stopped')
        self.assertEqual(sum(c[0]=='measure' for c in calls), 2)

    def test_thresholds_and_no_best_sample_selection(self):
        self.assertEqual(run.change_label(.2,.1), 'improved')
        self.assertEqual(run.change_label(.2,.3), 'degraded')
        self.assertEqual(run.change_label(.2,.2000001), 'unchanged')
        with self.assertRaises(ValueError): run.change_label(.2, float('nan'))

    def test_context_tampering_stops_before_candidate_fit(self):
        directory = Path(self.tmp.name)/'tamper'; measurements=[]
        def session(slot, packet):
            if slot['stage']=='update': return {'status':'accepted','business':{'rule_ids':run.S0['rule_ids']}}
            (directory/'context-A.json').write_text('{}')
            return {'status':'accepted','business':{'feature_ids':[]},'execution_payload':{}}
        def measure(parent, child, output):
            measurements.append(output.name)
            return {'status':'success','metrics':{'nmse':.2},'feedback':{'nmse':.2}}
        result = run.orchestrate(directory, run.design(), {}, session, measure)
        self.assertEqual(result['status'],'stopped')
        self.assertEqual(measurements,['baseline-A','baseline-B'])

    def test_ledger_rejects_out_of_order_and_recovery(self):
        ledger=run.TrialLedger(Path(self.tmp.name)/'ledger.json')
        with self.assertRaises(run.BudgetExceeded): ledger.reserve('A-r1-S0',{},8192)
        request=ledger.reserve('update',{},8192)
        ledger.settle(request,None,error_type='Timeout')
        with self.assertRaises(run.BudgetExceeded): ledger.reserve('A-r1-S0',{},8192)
        with self.assertRaises(run.BudgetExceeded): ledger.resume_after_transport_failure()

    def test_runtime_union_retains_every_original_dependency(self):
        old=previous.runtime_files(run.ROOT); new=run.runtime_files(run.ROOT)
        self.assertTrue(old)
        self.assertEqual({p:new[p] for p in old},old)
        extra=set(new)-set(old)
        self.assertTrue(extra)
        self.assertTrue(all(p.startswith('extensions/basis_trial_v02/') for p in extra))

    def test_prepare_keeps_complete_history_replaces_stale_instructions_and_guards(self):
        from rsi_eval.strategy_learning import build_learning_package, render_update_packet
        package=build_learning_package(run.ROOT)
        old=render_update_packet(run.ROOT,package)
        output=Path(self.tmp.name)/'prepared'
        result=run.prepare(run.ROOT,output)
        packet=json.loads((output/'update-packet.json').read_bytes())
        self.assertEqual(packet['learning_material'],old['learning_material'])
        self.assertEqual(len(packet['learning_material']['transitions']),24)
        self.assertEqual(packet['catalog'],old['catalog'])
        self.assertEqual(packet['parent_policy'],old['parent_policy'])
        self.assertIn('rule_ids only',packet['task_text'])
        self.assertNotIn('shadow',packet['task_text'])
        self.assertNotIn('separate selection stage',packet['task_text'])
        self.assertNotIn('explanation is required',packet['task_text'])
        self.assertEqual(run.guard_preparation(run.ROOT,output)['version'],run.VERSION)
        packet['learning_material']['transitions'].pop()
        (output/'update-packet.json').write_bytes(canonical(packet))
        with self.assertRaises(ValueError):run.guard_preparation(run.ROOT,output)


if __name__=='__main__': unittest.main()
