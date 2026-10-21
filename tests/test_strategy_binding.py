"""Synthetic record fixtures; these tests never execute or score a candidate."""
import copy
import hashlib
import importlib
import json
from pathlib import Path
import tempfile
import unittest
import shutil

try:
    binding = importlib.import_module('rsi_eval.strategy_binding')
except ModuleNotFoundError as error:
    if error.name != 'rsi_eval.strategy_binding':
        raise
    binding = None

ROOT = Path(__file__).resolve().parents[1]


class Fixture:
    """Fabricated observations only, with production-format dependency files."""
    def __init__(self, root, replicate='r1', kind='synthetic'):
        from rsi_eval.role_executor import runtime_inventory, LIMITS
        from rsi_eval.revision_policy import S0
        from rsi_eval.strategy_learning import render_actor_packet
        self.root, self.rep = root, replicate
        files, runtime = runtime_inventory()
        names = [x['path'] for x in files] + ['rsi_eval/revision_policy.py',
            'rsi_eval/strategy_binding.py','rsi_eval/goal_alignment.py','rsi_eval/strategy_learning.py',
            'prompts/strategy-pair/actor.md', binding.SOURCE_FREEZE, binding.PARTITION,
            binding.INPUT_FREEZE,binding.FUTURE_ALLOCATION]
        names += [str(Path(binding.SOURCE_FREEZE).parent / 'sessions' / st / 'source.py').replace('\\', '/')
                  for st in binding.SELECTION_STATES]
        for name in names:
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, target)
        self.partition = json.loads((root / binding.PARTITION).read_text())
        sourcefreeze = json.loads((root / binding.SOURCE_FREEZE).read_text())
        slots = {s['id']: s for s in sourcefreeze['slots']}
        self.parent = binding.policy_snapshot(root, S0)
        self.candidate = binding.policy_snapshot(root, {'version': 'revision-policy-v0.1', 'rule_ids': ['R01','R04','R06','R08']})
        self.runtime_files, self.runtime, self.limits = files, runtime, LIMITS
        self.contexts, baseline_refs = {}, {}
        for st in binding.SELECTION_STATES:
            slot = slots[st]
            cand = slot['candidate']
            source = (root / Path(binding.SOURCE_FREEZE).parent / 'sessions' / st / 'source.py').read_text(encoding='utf-8')
            family = slot['family']
            self.contexts[st] = dict(state_id=st, family=family, source=source,
                source_sha256=cand['source_sha256'], n_params=cand['n_params'], task_text='Frozen contract',
                public_examples=[], baseline_feedback=[], objective='Improve measured task outcomes')
            self.contexts[st].update(binding.task_contract(root,st))
            if family == 'planning':
                entries = [x for x in self.partition['planning']['tasks'] if x['role'] == 'learning']
                role = 'learning'
            else:
                entries = [x for x in self.partition['symbolic']['files'] if x['task_id'] == 'oscillator2' and x['split'] == 'train']
                role = 'selection'
            baseline_refs[st] = [self.receipt('baseline-' + st + '-' + str(i), family, role, entry,
                source, cand['n_params'], 'baseline', success=False) for i, entry in enumerate(entries)]
            self.contexts[st]['baseline_feedback'] = binding.project_baseline(root, st, baseline_refs[st])
        template = {'model': 'anthropic/MiniMax-M3', 'temperature': 1.0, 'max_tokens': 8192,
                    'messages': [{'role': 'system', 'content': 'Synthetic controller fixture'}, {'role': 'user', 'content': None}]}
        template_ref = self.write(replicate + '/template.json', template)
        budget_ref = self.write(replicate + '/budget.json', {'max_requests': 1, 'num_retries': 0})
        allocation = binding.build_selection_allocation(root, self.contexts, template_ref, budget_ref, replicate)
        self.manifest = dict(version=binding.VERSION, evidence_kind=kind, replicate_id=replicate,
            allocation=self.write(replicate + '/allocation.json', allocation),
            parent_policy=self.write(replicate + '/parent.json', self.parent),
            candidate_policy=self.write(replicate + '/candidate.json', self.candidate),
            contexts={k: self.write(replicate + '/context-' + k + '.json', v) for k, v in self.contexts.items()},
            baseline_evaluations=baseline_refs, request_template=template_ref, budget=budget_ref, sessions=[])
        for state in allocation['states']:
            st = state['id']
            for arm in ('fixed', 'updated'):
                slot = f'{replicate}-selection-{st}-{arm}'
                policy = self.parent if arm == 'fixed' else self.candidate
                request = copy.deepcopy(template)
                request['messages'][1]['content'] = binding.canonical(render_actor_packet(root, self.contexts[st], policy['content'])).decode()
                request_ref = self.write(slot + '/request.json', request)
                source = self.contexts[st]['source']
                src_ref = self.write(slot + '/source.py', source.encode(), raw=True)
                sub = dict(version='strategy-submission-v0.1',slot_id=slot,request_id=slot,
                    request_sha256=request_ref['sha256'],status='accepted',source_sha256=src_ref['sha256'],n_params=state['base_n_params'])
                if state['family'] == 'planning':
                    entries = [x for x in self.partition['planning']['tasks'] if x['role'] == 'selection']
                else:
                    entries = [x for x in self.partition['symbolic']['files'] if x['task_id'] == 'oscillator2' and x['split'] == 'train']
                evaluations = [self.receipt(slot + '-' + str(i),state['family'],'selection',entry,source,
                    state['base_n_params'],policy['sha256'],success=arm=='updated') for i,entry in enumerate(entries)]
                self.manifest['sessions'].append(dict(slot_id=slot,state_id=st,arm=arm,request_id=slot,
                    request=request_ref,submission=self.write(slot+'/submission.json',sub),source=src_ref,evaluations=evaluations))
        order=[s['id'] for s in json.loads((root/binding.FUTURE_ALLOCATION).read_text())['slots']
               if s['phase']=='selection' and s['replicate']==replicate]
        self.manifest['sessions'].sort(key=lambda s:order.index(s['slot_id']))
        self.ref = self.save()

    def write(self, path, value, raw=False):
        target = self.root / path
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(value if raw else binding.canonical(value)+b'\n')
        return binding.file_ref(self.root,path)

    def receipt(self, label, family, role, entry, source, params, policy, success):
        folder = self.rep + '/raw/' + label
        source_ref = self.write(folder+'/source.py',source.encode(),raw=True)
        request = dict(version='role-executor-v0.1',role=role,family=family,task_id=entry['task_id'],
            candidate_sha256=source_ref['sha256'],n_params=params,strategy_version=policy,
            partition_sha256=binding.PARTITION_SHA256,data_sha256=entry['sha256'],
            domain_sha256=self.partition['planning']['domain_sha256'] if family=='planning' else None,
            evaluator_sha256=self.runtime,metric_scope=role if family=='planning' else 'train',limits=self.limits)
        request_ref = self.write(folder+'/request.json',request)
        row = {k:v for k,v in request.items() if k not in ('role','candidate_sha256')}
        row.update(record_kind='executor_observation',task_role=role,candidate_hash=source_ref['sha256'],
            runtime_files=self.runtime_files,model_calls=0,sealed_tasks_executed=0,
            executions=[{'phase':'plan' if family=='planning' else 'fit','status':'completed'}],
            request_sha256=request_ref['sha256'],journal_path=folder+'/result.json',
            status='success' if success or family=='symbolic' else 'candidate_error')
        if family=='symbolic':
            row.update(metrics={'nmse':0.1,'mse':0.2},fitting={'n_params':params,'split':'train','converged':True,
                'params':[0.0]*params,'nfev':1,'candidate_calls':1,'max_nfev':100},
                executions=[{'phase':p,'status':'completed'} for p in ('fit','predict')])
        elif success:
            row['validator']={'status':'valid'}
        return self.write(folder+'/result.json',row)

    def save(self):
        self.ref = self.write(self.rep+'/manifest.json',self.manifest)
        return self.ref

    def replay(self):
        return binding.bind_selection(self.root,self.ref['path'],self.ref['sha256'])

    def change(self,ref,change):
        value=json.loads((self.root/ref['path']).read_text())
        change(value)
        ref.update(self.write(ref['path'],value))


class BindingTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(binding, 'Raw measured selection binding is not implemented')

    def test_evaluation_rejects_boolean_or_claimed_complete_flag(self):
        for flag in (True, {'complete': True}, None, 'frozen'):
            with self.subTest(flag=flag), self.assertRaises((ValueError, PermissionError)):
                binding.verify_evaluation_gate(Path('.'), flag)

    def test_synthetic_manifest_cannot_unlock_evaluation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises((ValueError, PermissionError)):
                binding.freeze_evaluation_gate(root, {}, 'gate.json')

    def fixture(self):
        temporary=tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        return Fixture(Path(temporary.name))

    def test_complete_raw_records_project_and_promote_without_running_source(self):
        fixture=self.fixture()
        result=fixture.replay()
        self.assertEqual(result['decision']['decision'],'promote')
        self.assertEqual(len(result['paired_results']),4)
        self.assertEqual(result['evidence_kind'],'synthetic')

    def test_changed_source_is_rejected_even_after_rehashing_final_reference(self):
        fixture=self.fixture()
        session=fixture.manifest['sessions'][0]
        session['source']=fixture.write(session['source']['path'],b'# changed\n',raw=True)
        fixture.change(session['submission'],lambda v:v.update(source_sha256=session['source']['sha256']))
        fixture.save()
        with self.assertRaisesRegex(ValueError,'source|context'):
            fixture.replay()

    def test_rehashed_model_packet_policy_mismatch_is_rejected(self):
        fixture=self.fixture();session=fixture.manifest['sessions'][0]
        def change(v):
            packet=json.loads(v['messages'][1]['content']);packet['repair_policy']['rule_ids'].reverse()
            v['messages'][1]['content']=binding.canonical(packet).decode()
        fixture.change(session['request'],change)
        fixture.change(session['submission'],lambda v:v.update(request_sha256=session['request']['sha256']))
        fixture.save()
        with self.assertRaisesRegex(ValueError,'Actual request'):
            fixture.replay()

    def test_rehashed_sampling_change_is_rejected(self):
        fixture=self.fixture();session=fixture.manifest['sessions'][0]
        fixture.change(session['request'],lambda v:v.update(temperature=0.0));fixture.save()
        with self.assertRaisesRegex(ValueError,'Actual request'):
            fixture.replay()

    def test_missing_final_stays_unknown_without_imputed_zero(self):
        fixture=self.fixture();session=fixture.manifest['sessions'][0]
        fixture.change(session['submission'],lambda v:v.update(status='missing',source_sha256=None,n_params=None))
        session.update(source=None,evaluations=[]);fixture.save()
        result=fixture.replay()
        self.assertEqual(result['decision']['decision'],'unknown')
        self.assertIsNone(result['paired_results'][0]['parent']['results'])

    def test_infrastructure_error_remains_unknown(self):
        fixture=self.fixture();session=fixture.manifest['sessions'][0]
        fixture.change(session['evaluations'][0],lambda v:v.update(status='infrastructure_error',executions=[]));fixture.save()
        result=fixture.replay()
        self.assertEqual(result['decision']['decision'],'unknown')

    def test_incomplete_measurements_are_rejected_not_counted_as_failure(self):
        fixture=self.fixture();fixture.manifest['sessions'][0]['evaluations'].pop();fixture.save()
        with self.assertRaisesRegex(ValueError,'Incomplete'):
            fixture.replay()

    def test_cross_role_score_rejected_even_with_new_result_hash(self):
        fixture=self.fixture();ref=fixture.manifest['sessions'][0]['evaluations'][0]
        fixture.change(ref,lambda v:v.update(task_role='evaluation'));fixture.save()
        with self.assertRaisesRegex(ValueError,'context mismatch'):
            fixture.replay()

    def test_baseline_feedback_cannot_be_replaced_by_posthoc_notes(self):
        fixture=self.fixture();ref=fixture.manifest['contexts']['P-select-1']
        fixture.change(ref,lambda v:v.update(baseline_feedback={'diagnosis':'hand selected future finding'}));fixture.save()
        with self.assertRaisesRegex(ValueError,'baseline|Allocation'):
            fixture.replay()

    def test_eval_state_seed0_feedback_requires_same_gate(self):
        with self.assertRaises((ValueError,PermissionError)):
            binding.authorize_state_phase(ROOT,'P-eval-1')
        self.assertIsNone(binding.authorize_state_phase(ROOT,'P-select-1'))

    def test_synthetic_frozen_decisions_cannot_unlock_real_evaluation(self):
        fixture=self.fixture()
        ref=binding.freeze_selection(fixture.root,fixture.ref['path'],fixture.ref['sha256'],'decision-r1.json')
        with self.assertRaisesRegex(ValueError,'Synthetic'):
            binding.freeze_evaluation_gate(fixture.root,{'r1':ref,'r2':ref},'gate.json')

    def test_gate_needs_both_replicates_and_replays_dependencies(self):
        fixture=self.fixture()
        with self.assertRaisesRegex(ValueError,'Both'):
            binding.freeze_evaluation_gate(fixture.root,{'r1':{}},'gate.json')

    def test_path_traversal_reference_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises((ValueError,PermissionError)):
                binding.file_ref(Path(directory),'../outside.json')

    def test_path_alias_cannot_disguise_reused_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'a').mkdir();(root/'a'/'x.json').write_text('{}')
            for name in ('a//x.json','a/./x.json','a\\x.json'):
                with self.subTest(name=name),self.assertRaises(ValueError):
                    binding.file_ref(root,name)

    def test_task_contract_cannot_include_rehashed_evaluation_hints(self):
        fixture=self.fixture();contexts=copy.deepcopy(fixture.contexts)
        contexts['P-select-1']['task_text']='Evaluation source has known defect: change its call arity.'
        with self.assertRaisesRegex(ValueError,'contract'):
            binding.build_selection_allocation(fixture.root,contexts,
                fixture.manifest['request_template'],fixture.manifest['budget'],'r1')

    def test_success_cannot_contradict_raw_validator_verdict(self):
        fixture=self.fixture();ref=fixture.manifest['sessions'][1]['evaluations'][0]
        fixture.change(ref,lambda v:v.update(validator={'status':'invalid'}));fixture.save()
        with self.assertRaisesRegex(ValueError,'validator'):
            fixture.replay()

    def test_failure_cannot_hide_valid_validator_verdict(self):
        fixture=self.fixture();ref=fixture.manifest['sessions'][0]['evaluations'][0]
        fixture.change(ref,lambda v:v.update(validator={'status':'valid'}));fixture.save()
        with self.assertRaisesRegex(ValueError,'validator'):
            fixture.replay()

    def test_baseline_retains_only_bounded_observed_error_location(self):
        fixture=self.fixture();refs=fixture.manifest['baseline_evaluations']['P-select-1']
        fixture.change(refs[0],lambda v:v.update(error_kind='invalid_worker_result',exception_type='TypeError',candidate_line=17))
        rows=binding.project_baseline(fixture.root,'P-select-1',refs)
        self.assertEqual(rows[0]['exception_type'],'TypeError')
        self.assertEqual(rows[0]['candidate_line'],17)
        fixture.change(refs[0],lambda v:v.update(candidate_line=True))
        with self.assertRaisesRegex(ValueError,'diagnostic'):
            binding.project_baseline(fixture.root,'P-select-1',refs)

    def test_task_contract_has_no_cold_start_workflow_instruction(self):
        for st in binding.SELECTION_STATES:
            text=binding.task_contract(ROOT,st)['task_text']
            self.assertNotIn('no starting program',text)
            self.assertNotIn('cold-start workflow',text)
            self.assertNotIn('without running or fitting',text)

    def test_symbolic_success_needs_independent_predict_receipt(self):
        fixture=self.fixture();ref=fixture.manifest['sessions'][2]['evaluations'][0]
        fixture.change(ref,lambda v:v.update(executions=[{'phase':'fit','status':'completed'}]));fixture.save()
        with self.assertRaisesRegex(ValueError,'fit|predict'):
            fixture.replay()

    def test_gate_positive_contract_fixture_and_changed_dependency_closes_it(self):
        # 'observed' here exercises the production branch on fabricated files;
        # it is a contract fixture, not evidence of any real model/executor run.
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        root=Path(temporary.name)
        first=Fixture(root,'r1',kind='observed');second=Fixture(root,'r2',kind='observed')
        refs={r:binding.freeze_selection(root,f.ref['path'],f.ref['sha256'],r+'/decision.json')
              for r,f in [('r1',first),('r2',second)]}
        gate=binding.freeze_evaluation_gate(root,refs,'gate.json')
        self.assertEqual(binding.verify_evaluation_gate(root,gate),gate.sha256)
        (root / first.manifest['sessions'][0]['source']['path']).write_bytes(b'# later change\n')
        with self.assertRaisesRegex(ValueError,'changed'):
            binding.verify_evaluation_gate(root,gate)

    def test_cross_repetition_request_or_context_reuse_is_rejected(self):
        fixture=self.fixture();one=fixture.replay();two=copy.deepcopy(one)
        two['replicate_id']='r2';two['manifest']['path']='r2/manifest.json'
        for state in two['allocation']['states']:
            state['replicate_ids']=['r2']
        for pair in two['paired_results']:
            pair['replicate_id']='r2'
            for arm in ('parent','candidate'):
                pair[arm]['request_id']='r2-'+pair[arm]['request_id']
        decisions={'r1':{'replay':one},'r2':{'replay':two}}
        with self.assertRaisesRegex(ValueError,'reused'):
            binding._verify_decision_pair(decisions)
        two['request_files']=['r2/'+x for x in two['request_files']]
        two['evaluation_files']=['r2/'+x for x in two['evaluation_files']]
        two['common_context_sha256']['P-select-1']='0'*64
        with self.assertRaisesRegex(ValueError,'context'):
            binding._verify_decision_pair(decisions)


if __name__ == '__main__':
    unittest.main()
