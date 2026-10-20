"""Read-only policy audit rejects confounded inputs and dishonest denominators."""
import copy
import hashlib
import importlib
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from rsi_eval.revision_policy import S0, catalog, render_policy


class PolicyAnalysisTests(unittest.TestCase):
    def setUp(self):
        if importlib.util.find_spec('scripts.analyze_policy_transfer') is None:
            self.fail('Independent policy-transfer audit is not implemented')
        self.audit=importlib.import_module('scripts.analyze_policy_transfer')
        self.selected={'version':'revision-policy-v0.1','rule_ids':['R01','R02','R05','R07']}
        self.bundle={'version':'policy-update-cases-v0.1','cases':[{'case_id':'U-P'},{'case_id':'U-S'}]}
        self.order=self.audit.expected_order()

    def packet(self, arm):
        return {'version':'fixture','session_id':'shared-pair','task_text':'frozen task',
            'available_revision_rules':catalog(),
            'repair_policy':render_policy(self.selected if arm=='updated' else S0),
            'experience_memory':copy.deepcopy(self.bundle['cases']) if arm=='memory' else [],
            'metadata':{'source':'common'},'audits':[]}

    def request(self, arm):
        return {'model':'fixed-model','messages':[{'role':'system','content':'fixed system'},
            {'role':'user','content':json.dumps(self.packet(arm))}],
            'tools':[{'type':'function','function':{'name':'submit_candidate','parameters':{'type':'object'}}}],
            'tool_choice':'auto','max_output_tokens':4096}

    def test_twelve_sessions_are_exactly_four_three_condition_groups(self):
        self.assertEqual(len(self.order),12)
        config={'order':self.order,'max_iterations':1,'max_generated_candidates':1}
        summary={'sessions':copy.deepcopy(self.order)}
        self.audit.validate_layout(config,summary)
        for bad in [summary['sessions'][:-1],summary['sessions']+[summary['sessions'][0]],
                    [dict(x,condition='hidden') if i==0 else x for i,x in enumerate(summary['sessions'])]]:
            with self.assertRaises(ValueError):self.audit.validate_layout(config,{'sessions':bad})

    def test_correct_policy_and_memory_channels_match_exactly(self):
        for arm in ('fixed','memory','updated'):
            packet=self.packet(arm)
            self.audit.verify_channels(packet,arm,self.selected,self.bundle,'frozen task')
            common=self.audit.request_common(self.request(arm))
            if arm=='fixed':first=common
            else:self.assertEqual(common,first)

    def test_changed_policy_host_rationale_or_extra_memory_is_rejected(self):
        cases=[('updated',lambda p:p['repair_policy'].update(rationale='MODEL_PRIVATE_REASON')),
               ('fixed',lambda p:p.update(repair_policy=render_policy(self.selected))),
               ('updated',lambda p:p.update(experience_memory=self.bundle['cases'])),
               ('memory',lambda p:p['experience_memory'].append({'case_id':'E-P'})),
               ('updated',lambda p:p.update(task_text='frozen task MODEL_PRIVATE_REASON')),
               ('fixed',lambda p:p['available_revision_rules'][0].update(instruction='injected'))]
        for arm,mutate in cases:
            with self.subTest(arm=arm):
                packet=self.packet(arm);mutate(packet)
                with self.assertRaises(ValueError):self.audit.verify_channels(packet,arm,self.selected,self.bundle,'frozen task')

    def test_group_comparison_includes_system_tools_and_other_checks(self):
        requests={row['session_id']:self.request(row['condition']) for row in self.order}
        proofs=self.audit.verify_request_groups(requests,self.order)
        self.assertEqual(len(proofs),4)
        self.assertTrue(all(p['all_three_requested'] and p['exact_common_request_equality'] for p in proofs.values()))
        for target in ('system','tool','other_check'):
            with self.subTest(target=target):
                bad=copy.deepcopy(requests);request=bad[self.order[0]['session_id']]
                if target=='system':request['messages'][0]['content']='different'
                elif target=='tool':request['tools'][0]['function']['parameters']['extra']='changed'
                else:
                    packet=json.loads(request['messages'][1]['content']);packet['audits']=['different']
                    request['messages'][1]['content']=json.dumps(packet)
                with self.assertRaises(ValueError):self.audit.verify_request_groups(bad,self.order)

    def test_missing_request_is_marked_incomplete_not_invented(self):
        requests={row['session_id']:self.request(row['condition']) for row in self.order[1:]}
        proofs=self.audit.verify_request_groups(requests,self.order)
        self.assertFalse(proofs[self.order[0]['pair_id']]['all_three_requested'])
        requests['unexpected']=self.request('fixed')
        with self.assertRaises(ValueError):self.audit.verify_request_groups(requests,self.order)

    def test_missing_child_has_null_score_and_no_new_execution(self):
        baseline={'candidate_id':'symbolic-000','status':'evaluated','metrics':{'mse':0.2,'nmse':0.1},
                  'results':[{'task_id':'oscillator1','status':'success','metrics':{'mse':0.2,'nmse':0.1}}]}
        endpoint=self.audit.compute_endpoint([baseline],'symbolic')
        self.assertIsNone(endpoint['child_score']);self.assertIsNone(endpoint['improvement'])
        self.assertFalse(endpoint['submitted_and_improved'])
        self.assertEqual(endpoint['new_task_result_records'],0)
        self.assertEqual(endpoint['archived_task_result_records'],1)
        child=copy.deepcopy(baseline);child['candidate_id']='symbolic-001';child['metrics']={'mse':0.1,'nmse':0.05};child['results'][0]['metrics']=child['metrics']
        endpoint=self.audit.compute_endpoint([baseline,child],'symbolic')
        self.assertAlmostEqual(endpoint['improvement'],0.05)
        self.assertTrue(endpoint['submitted_and_improved'])
        self.assertEqual(endpoint['new_task_result_records'],1)

    def test_usage_and_cost_are_separated_by_update_and_condition(self):
        prices={'input_cny_per_million':2.1,'output_cny_per_million':8.4}
        rows=[]
        for i,session in enumerate(('policy_update','EP-r1-fixed','EP-r1-memory','EP-r1-updated'),1):
            rows.append({'request_id':f'request-{i:04d}','session_id':session,'usage_state':'known',
                'status':'settled','input_bytes':100,'input_token_reservation':8292,'output_token_reservation':4096,
                'reserved_cost_cny':0.0518196,'usage':{'prompt_tokens':1000,'completion_tokens':100,'total_tokens':1100},
                'actual_estimated_cost_cny':0.00294})
        result=self.audit.cost_breakdown({'config':prices,'requests':rows},self.order)
        self.assertEqual(result['all']['known_total_tokens'],4400)
        self.assertAlmostEqual(result['all']['known_estimated_cost_cny'],0.01176)
        self.assertEqual(result['policy_update']['requests'],1)
        self.assertEqual(result['updated']['requests'],1)
        self.assertAlmostEqual(result['updated_plus_update']['known_estimated_cost_cny'],0.00588)
        rows[-1]['actual_estimated_cost_cny']=0.0
        with self.assertRaises(ValueError):self.audit.cost_breakdown({'config':prices,'requests':rows},self.order)

    def test_unknown_usage_preserves_unknown_totals(self):
        row={'request_id':'request-0001','session_id':'policy_update','usage_state':'unknown','status':'failed',
             'input_bytes':1,'input_token_reservation':8193,'output_token_reservation':4096,
             'reserved_cost_cny':0.0516117,'usage':None}
        result=self.audit.cost_breakdown({'config':{'input_cny_per_million':2.1,'output_cny_per_million':8.4},'requests':[row]},self.order)
        self.assertEqual(result['all']['unknown_usage_requests'],1)
        self.assertIsNone(result['all']['actual_total_tokens'])
        self.assertIsNone(result['all']['actual_estimated_cost_cny'])

    def test_source_provenance_reads_frozen_git_blob_not_modified_worktree(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'prompts').mkdir();path=root/'prompts/fixed.md';path.write_bytes(b'frozen\n')
            second=root/'prompts/other.md';second.write_bytes(b'also frozen\n')
            def git(*args):return subprocess.check_output(['git',*args],cwd=root,stderr=subprocess.DEVNULL)
            git('init','-q');git('add','prompts')
            git('-c','user.name=Audit Test','-c','user.email=audit@example.invalid','commit','-qm','fixture')
            commit=git('rev-parse','HEAD').decode().strip()
            summary={'code_commit':commit,'source_sha256':{'prompts/fixed.md':hashlib.sha256(b'frozen\n').hexdigest(),
                'prompts/other.md':hashlib.sha256(b'also frozen\n').hexdigest()}}
            path.write_bytes(b'later worktree\n')
            blobs=self.audit.verify_sources(summary,root)
            self.assertEqual(blobs['prompts/fixed.md'],b'frozen\n')
            missing=copy.deepcopy(summary);missing['source_sha256'].pop('prompts/other.md')
            with self.assertRaises(ValueError):self.audit.verify_sources(missing,root)
            summary['source_sha256']['prompts/fixed.md']='0'*64
            with self.assertRaises(ValueError):self.audit.verify_sources(summary,root)

    def test_completed_status_requires_all_thirteen_requests_but_not_children(self):
        sessions=['policy_update']+[row['session_id'] for row in self.order]
        rows=[{'request_id':f'request-{i:04d}','session_id':name} for i,name in enumerate(sessions,1)]
        self.audit.verify_dispatch({'status':'attempts_completed'},rows,sessions)
        with self.assertRaises(ValueError):
            self.audit.verify_dispatch({'status':'attempts_completed'},rows[:-1],sessions)
        self.audit.verify_dispatch({'status':'stopped'},rows[:-1],sessions)
        with self.assertRaises(ValueError):
            self.audit.verify_dispatch({'status':'stopped'},rows[:2]+rows[3:],sessions)

    def policy_stage(self, root):
        from rsi_eval.policy_cases import load_update_bundle
        from rsi_eval.revision_policy import PolicyUpdateController,freeze_policy
        bundle=load_update_bundle(self.audit.ROOT)
        controller=PolicyUpdateController(bundle,S0,root/'policy_update')
        packet=controller.state_packet()
        fields={f'rule_{i}':rule for i,rule in enumerate(self.selected['rule_ids'],1)}
        fields.update({f'support_{i}':'both' for i in range(1,5)})
        fields['rationale']='HOST_ONLY_CANARY'
        self.assertEqual(controller.submit_policy(**fields)['status'],'accepted')
        frozen=freeze_policy(root/'policy_update',bundle,S0,'request-0001')
        blobs={p:(self.audit.ROOT/p).read_bytes() for p in
               ('rsi_eval/pilot_agent.py','prompts/policy-transfer/update.md')}
        system=self.audit._literal_assignment(blobs['rsi_eval/pilot_agent.py'],'POLICY_UPDATE_SYSTEM_PROMPT')
        request={'model':'fixture-model','messages':[{'role':'system','content':system},
            {'role':'user','content':json.dumps(packet)}],
            'tools':[{'type':'function','function':{'name':name}} for name in ('submit_policy','finish')],
            'tool_choice':'auto','max_output_tokens':4096}
        usage={'prompt_tokens':1000,'completion_tokens':100,'total_tokens':1100}
        response={'usage':usage,'choices':[{'finish_reason':'tool_calls','message':{'tool_calls':[
            {'type':'function','function':{'name':'submit_policy','arguments':json.dumps(fields)}}]}}]}
        encoded=self.audit.canonical(request)
        row={'request_id':'request-0001','session_id':'policy_update','usage_state':'known',
             'status':'settled','usage':usage,'usage_sha256':self.audit.digest(self.audit.canonical(usage)),
             'payload_sha256':self.audit.digest(encoded),'input_bytes':len(encoded),'output_token_reservation':4096}
        input_audit={'request_id':'request-0001','request_reserved':True,'network_dispatch_attempted':True,
            'transport_called':True,'payload_sha256':row['payload_sha256'],'actual_input_bytes':len(encoded)}
        (root/'policy_update/requests').mkdir()
        def write(path,data):
            (root/path).write_bytes(self.audit.canonical(data))
        write('policy-S0.json',S0)
        write('evaluation-started.json',{'mode':'evaluate','freeze_sha256':self.audit.digest((root/'policy_update/freeze.json').read_bytes())})
        write('policy_update/task-packet.json',packet)
        write('policy_update/requests/packet-0001.json',packet)
        write('policy_update/requests/input-audit-0001.json',input_audit)
        write('policy_update/requests/request-0001.request.json',request)
        write('policy_update/requests/request-0001.response.json',response)
        (root/'policy_update/events.jsonl').write_text('\n'.join(json.dumps({'type':kind,'tool_name':'submit_policy'})
            for kind in ('ActionEvent','ObservationEvent')),encoding='utf-8')
        summary={'selected_policy':self.selected,'freeze':frozen,'strategy_changed':True,
            'freeze_file_sha256':self.audit.digest((root/'policy_update/freeze.json').read_bytes()),
            'effective_model_config':{'model':'fixture-model'}}
        ledger={'config':{'max_input_bytes':98304,'max_output_tokens':4096},'requests':[row]}
        return summary,bundle,blobs,ledger

    def test_frozen_policy_stage_matches_literal_response_and_excludes_host_rationale(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);args=self.policy_stage(root)
            selected,detail=self.audit._verify_policy_stage(root,*args)
            self.assertEqual(selected,self.selected)
            self.assertFalse(detail['host_rationale_rendered'])
            self.assertNotIn('HOST_ONLY_CANARY',json.dumps(detail))
            path=root/'policy_update/requests/request-0001.response.json'
            value=json.loads(path.read_text()); fields=json.loads(value['choices'][0]['message']['tool_calls'][0]['function']['arguments'])
            fields['rule_1']='R08';value['choices'][0]['message']['tool_calls'][0]['function']['arguments']=json.dumps(fields)
            path.write_text(json.dumps(value))
            with self.assertRaises(ValueError):self.audit._verify_policy_stage(root,*args)

    def test_policy_stage_rejects_changed_external_freeze_digest_or_update_model(self):
        for target in ('freeze','model'):
            with self.subTest(target=target),tempfile.TemporaryDirectory() as temp:
                root=Path(temp);args=self.policy_stage(root);summary=args[0]
                if target=='freeze':summary['freeze_file_sha256']='0'*64
                else:summary['effective_model_config']['model']='different-model'
                with self.assertRaises(ValueError):self.audit._verify_policy_stage(root,*args)

    def test_saved_response_requires_settlement_and_matching_error_status(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);_,_,blobs,ledger=self.policy_stage(root)
            row=ledger['requests'][0]
            system=self.audit._literal_assignment(blobs['rsi_eval/pilot_agent.py'],'POLICY_UPDATE_SYSTEM_PROMPT')
            args=(root/'policy_update',row,ledger['config'],system)
            self.audit._request_record(*args)
            for status,error in [('reserved',None),('failed',None),('settled','Timeout')]:
                row.update(status=status,error_type=error)
                with self.subTest(status=status,error=error),self.assertRaises(ValueError):
                    self.audit._request_record(*args)
            response_path=root/'policy_update/requests/request-0001.response.json'
            response=json.loads(response_path.read_text());response['error_type']='PilotResponseContractError'
            response_path.write_text(json.dumps(response))
            row.update(status='settled',error_type=None)
            with self.assertRaises(ValueError):self.audit._request_record(*args)
            row.update(status='failed',error_type='PilotResponseContractError')
            self.audit._request_record(*args)
            row['error_type']='Timeout'
            with self.assertRaises(ValueError):self.audit._request_record(*args)

    def test_budget_summary_cannot_hide_reserved_unknown_or_halted_run(self):
        sessions=['policy_update','EP-r1-fixed']
        ledger={'config':{'session_ids':sessions},'halted':False,'halt_reasons':[],
            'requests':[{'session_id':s,'status':'settled','usage_state':'known'} for s in sessions]}
        summary={'status':'attempts_completed','budget':{'request_count':2,'reserved_count':0,'failed_count':0,
            'usage_unknown_count':0,'session_counts':dict.fromkeys(sessions,1),'halted':False,'halt_reasons':[],
            'recovery':None,'config':ledger['config']}}
        self.audit.verify_budget_state(summary,ledger)
        for field in ('reserved_count','failed_count','usage_unknown_count','request_count','session_counts','halted','halt_reasons'):
            bad=copy.deepcopy(summary)
            bad['budget'][field]= {'session_counts':{},'halted':True,'halt_reasons':['usage_unknown']}.get(field,3)
            with self.subTest(field=field),self.assertRaises(ValueError):self.audit.verify_budget_state(bad,ledger)
        for bad_field in ('reserved','unknown','halted'):
            altered=copy.deepcopy(ledger);bad=copy.deepcopy(summary)
            if bad_field=='reserved':
                altered['requests'][1]['status']='reserved';bad['budget']['reserved_count']=1
            elif bad_field=='unknown':
                altered['requests'][1]['usage_state']='unknown';bad['budget']['usage_unknown_count']=1
            else:
                altered['halted']=bad['budget']['halted']=True
                altered['halt_reasons']=bad['budget']['halt_reasons']=['usage_unknown']
            with self.subTest(field=bad_field),self.assertRaises(ValueError):self.audit.verify_budget_state(bad,altered)


if __name__=='__main__':unittest.main()
