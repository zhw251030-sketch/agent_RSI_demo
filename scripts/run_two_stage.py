#!/usr/bin/env python3
"""One new, non-resumable shared-probe experiment; no ambient agent tools."""
import argparse
import contextlib
import copy
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import io
import json
import logging
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
os.environ['OPENHANDS_SUPPRESS_BANNER']='1'
os.environ['LITELLM_LOCAL_MODEL_COST_MAP']='True'
os.environ['DO_NOT_TRACK']='1'
CONFIG_PATH='configs/pilots/two-stage-v0.1.json'
PROTOCOL='docs/protocols/2026-10-21-two-stage-v0.1.md'
CASE_ORDER=['P-format-missing','P-prefix','S-cubic','S-square']
COUNTS=('sandbox_calls','new_candidate_executions','host_validations','val_calls','fit_calls','predict_calls')


def canonical(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode('utf-8')
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def read(path):return json.loads(Path(path).read_bytes())
def write(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_bytes((json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode('utf-8'))


def validate_config(config):
    expected={'version':'two-stage-v0.1','protocol':PROTOCOL,'case_order':CASE_ORDER,
        'epsilon':1e-5,'numeric_tolerance':1e-10,'max_sandbox_calls':64,'resume':False,
        'sealed_tasks_executed':0,'budgets':{'max_requests':12,'max_requests_per_session':1,
        'max_output_tokens':4096,'max_input_bytes':98304,'max_reserved_tokens':1600000,
        'max_cost_cny':5,'input_cny_per_million':2.1,'output_cny_per_million':8.4}}
    if canonical(config)!=canonical(expected):raise ValueError('Frozen configuration changed')
    return copy.deepcopy(config)


def actor_order():
    pairs=[('P-format-missing','self'),('S-cubic','checked'),('P-format-missing','checked'),
           ('S-cubic','self'),('P-prefix','checked'),('S-square','self'),('P-prefix','self'),('S-square','checked')]
    return [dict(case_id=c,condition=a,session_id=c+'-'+a) for c,a in pairs]


def directory_hashes(directory):
    directory=Path(directory)
    if directory.is_symlink():raise ValueError('Symlinked frozen directory')
    files={}
    for p in sorted(directory.rglob('*')):
        if p.is_symlink():raise ValueError('Symlinked frozen file')
        if p.is_file():files[p.relative_to(directory).as_posix()]=sha(p)
    return files


def verify_files(directory,pins):
    if directory_hashes(directory)!=pins:raise ValueError('Frozen phase files changed')


def runtime_freeze(root,*,allow_dirty=False):
    def git(*args):return subprocess.check_output(['git','-C',str(root),*args],text=True).strip()
    dirty=git('status','--porcelain')
    if dirty and not allow_dirty:raise ValueError('Runtime checkout is dirty')
    paths=[p for d in ('rsi_eval','scripts','configs','prompts','fixtures') for p in (root/d).rglob('*')
           if p.is_file() and p.suffix in ('.py','.json','.md','.txt')]+[root/PROTOCOL]
    return {'runtime_commit':git('rev-parse','HEAD'),'checkout_clean':not bool(dirty),
            'runtime_files_sha256':{p.relative_to(root).as_posix():sha(p) for p in sorted(paths)},
            'recorded_at_utc':datetime.now(timezone.utc).isoformat()}


def assert_runtime(root,freeze):
    for p,digest in freeze['runtime_files_sha256'].items():
        if sha(root/p)!=digest:raise ValueError('Frozen runtime changed')


class ExecutionLedger:
    def __init__(self,path,maximum):
        self.path=Path(path)
        if self.path.exists():raise FileExistsError('No execution ledger resume')
        self.state={'max_sandbox_calls':maximum,'reserved_sandbox_calls':0,'events':[]}
        self._save()

    def _save(self):
        # Same-directory atomic replace; reserve is durable before dispatch.
        temporary=self.path.with_suffix('.pending')
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with temporary.open('w',encoding='utf-8') as stream:
            json.dump(self.state,stream,ensure_ascii=False,allow_nan=False,indent=2)
            stream.flush();os.fsync(stream.fileno())
        os.replace(temporary,self.path)

    def reserve(self,label,count):
        if type(count) is not int or count<1 or self.state['reserved_sandbox_calls']+count>self.state['max_sandbox_calls']:
            raise ValueError('Execution budget exceeded')
        token=len(self.state['events'])
        self.state['events'].append({'label':label,'reserved':count,'counts':None})
        self.state['reserved_sandbox_calls']+=count;self._save();return token

    def settle(self,token,counts):
        event=self.state['events'][token]
        if event['counts'] is not None:raise ValueError('Execution already settled')
        values={k:counts.get(k,0) for k in COUNTS}
        if any(type(v) is not int or v<0 for v in values.values()) or values['sandbox_calls']>event['reserved']:
            raise ValueError('Invalid execution accounting')
        event['counts']=values
        event['complete']=counts.get('val_count_complete',True) and counts.get('execution_accounting_complete',True)
        self._save()

    def summary(self):
        return {'reserved_sandbox_calls':self.state['reserved_sandbox_calls'],
                'actual':{k:sum((e['counts'] or {}).get(k,0) for e in self.state['events']) for k in COUNTS},
                'accounting_complete':all(e['counts'] is not None and e.get('complete') for e in self.state['events'])}


def classify_session(raw,controller,budget,available):
    from scripts.run_policy_transfer import budget_blocked
    if budget_blocked(budget) or controller.halted:return 'blocked'
    known=bool({'IncompleteToolResponseError','PilotResponseContractError'} &
               {raw.get('model_error_type'),raw.get('cause_type')})
    if (raw.get('status')=='error' or raw.get('model_error_type')) and not known:return 'blocked'
    if known:return 'missing'
    return 'available' if available else 'missing'


def request_id(output,session):
    from scripts.run_inference_policy import request_for
    return request_for(read(output/'budget-ledger.json'),session)


def check_probe(result):
    if (result.get('status')=='infrastructure_error' or result.get('infrastructure_stopped')
            or result.get('execution_accounting_complete') is False
            or result.get('executions',{}).get('val_count_complete') is False):
        raise RuntimeError('Probe infrastructure or accounting failure')


def execute(root,output,report,cases,ledger,executions,session_runner,probe_runner,eval_runner):
    from rsi_eval.two_stage_core import ProbeController,RevisionController,feedback_projection,common_request
    from scripts.run_intervention_probes import evaluator_counts
    registrations={};feedback={}
    freeze=read(output/'runtime-freeze.json')
    def save():
        report['budget']=ledger.summary();report['execution_budget']=executions.summary();write(output/'summary.json',report)
    def guard():assert_runtime(root,freeze)
    for row in report['registrations']:
        guard();case=cases[row['case_id']];directory=output/'stage1'/row['case_id']
        c=ProbeController(case,directory);write(directory/'task-packet.json',c.task_packet())
        raw=session_runner(c,row,directory,'probe');row.update(raw)
        disposition=classify_session(raw,c,ledger.summary(),c.registration is not None)
        row['disposition']=disposition
        if disposition=='blocked':
            report.update(status='stopped',stop_reason='registration_infrastructure_or_usage');save();return
        row['request_id']=request_id(output,row['session_id'])
        if disposition=='available':
            request=next(r for r in read(output/'budget-ledger.json')['requests'] if r['request_id']==row['request_id'])
            if request['status']!='settled':raise ValueError('Available registration requires settled transport')
            registrations[row['case_id']]=copy.deepcopy(c.registration)
        save()
    # No model sees an observation until all first-stage slots have ended.
    registration_freeze={'slots':copy.deepcopy(report['registrations']),
                         'registrations':registrations,'stage1_files':directory_hashes(output/'stage1')}
    write(output/'registration-freeze.json',registration_freeze)
    registration_sha=sha(output/'registration-freeze.json')
    report['registration_freeze_sha256']=registration_sha;save()
    def registration_guard():
        guard()
        if sha(output/'registration-freeze.json')!=registration_sha:raise ValueError('Registration anchor changed')
        verify_files(output/'stage1',registration_freeze['stage1_files'])
    for case_id in CASE_ORDER:
        if case_id not in registrations:continue
        registration_guard();case=cases[case_id];directory=output/'probes'/case_id
        full=probe_runner(case,executions,directory)
        feedback[case_id]=feedback_projection(case,full)
        write(directory/'feedback.json',feedback[case_id]);save()
    registration_guard()
    phase={'registrations':registrations,'feedback':feedback,'registration_freeze_sha256':registration_sha,
           'stage1_files':directory_hashes(output/'stage1'),'probe_files':directory_hashes(output/'probes')}
    write(output/'phase-freeze.json',phase);phase_sha=sha(output/'phase-freeze.json')
    report['phase_freeze_sha256']=phase_sha;save()
    def phase_guard():
        registration_guard()
        if sha(output/'phase-freeze.json')!=phase_sha:raise ValueError('Phase anchor changed')
        verify_files(output/'stage1',phase['stage1_files']);verify_files(output/'probes',phase['probe_files'])
    request_proofs={}
    for row in report['revisions']:
        case_id=row['case_id'];case=cases[case_id]
        if case_id not in registrations:
            row.update(disposition='skipped_dependency',candidate=None);save();continue
        phase_guard();directory=output/'stage2'/row['session_id']
        def evaluate(*args,**kwargs):
            phase_guard();family=args[0] if args else kwargs['family']
            token=executions.reserve(row['session_id']+':'+str(args[1] if len(args)>1 else kwargs.get('task_id')),1 if family=='planning' else 2)
            result=eval_runner(*args,**kwargs);counts=evaluator_counts(result)
            executions.settle(token,counts);save()
            if result.get('status')=='infrastructure_error' or counts.get('val_count_complete') is False:
                raise RuntimeError('Candidate infrastructure failure')
            return result
        c=RevisionController(case,registrations[case_id],feedback[case_id] if row['condition']=='checked' else None,
                             root,directory,evaluator=evaluate)
        write(directory/'task-packet.json',c.task_packet())
        raw=session_runner(c,row,directory,'revision');row.update(raw)
        disposition=classify_session(raw,c,ledger.summary(),c.summary().get('candidate') is not None)
        row['disposition']=disposition;row['candidate']=c.summary().get('candidate')
        if disposition=='blocked':
            report.update(status='stopped',stop_reason='revision_infrastructure_or_usage');save();return
        row['request_id']=request_id(output,row['session_id'])
        requests=list((directory/'requests').glob('*.request.json'))
        if len(requests)!=1:raise ValueError('One real request required')
        shared=common_request(read(requests[0]))
        shared_bytes=shared if isinstance(shared,bytes) else canonical(shared)
        digest=hashlib.sha256(shared_bytes).hexdigest()
        if case_id in request_proofs and request_proofs[case_id]!=digest:raise ValueError('Actual common request differs')
        request_proofs[case_id]=digest;report['common_request_sha256']=dict(request_proofs);save()
    phase_guard();report['status']='attempts_completed';save()


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--run-id',required=True)
    modes=parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--prepare-only',action='store_true');modes.add_argument('--run',action='store_true')
    args=parser.parse_args(argv)
    if not re.fullmatch('[A-Za-z0-9][A-Za-z0-9_-]{0,63}',args.run_id):parser.error('Invalid run ID')
    report={'run_id':args.run_id,'status':'error','sealed_tasks_executed':0,'strategy_updated':False,
            'resumed':False,'model_weights_updated':False}
    output=None;ledger=None;executions=None;previous=logging.root.manager.disable;logging.disable(logging.CRITICAL)
    try:
        with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
            from rsi_eval.two_stage_cases import load_cases
            from rsi_eval.pilot_budget import BudgetLedger
            from scripts.run_checked_feedback import _model_configuration
            config=validate_config(read(ROOT/CONFIG_PATH));cases={c['id']:c for c in load_cases(ROOT)}
            if list(cases)!=CASE_ORDER:raise ValueError('Case order changed')
            freeze=runtime_freeze(ROOT,allow_dirty=args.prepare_only)
            parent=ROOT/'runs/two-stage';target=parent/args.run_id
            if (ROOT/'runs').is_symlink() or parent.is_symlink() or target.is_symlink():raise ValueError('Output symlink')
            target.mkdir(parents=True,exist_ok=False);output=target
            write(output/'runtime-freeze.json',freeze);write(output/'config.json',config);write(output/'cases.json',cases)
            registrations=[dict(case_id=c,session_id=c+'-probe',status='not_started') for c in CASE_ORDER]
            revisions=[dict(r,status='not_started') for r in actor_order()]
            ledger=BudgetLedger(output/'budget-ledger.json',session_ids=[r['session_id'] for r in registrations+revisions],**config['budgets'])
            executions=ExecutionLedger(output/'execution-ledger.json',config['max_sandbox_calls'])
            digest,public,effective=_model_configuration(ROOT/'configs/models/minimax-m3.json',config['budgets'])
            report.update(registrations=registrations,revisions=revisions,model_config=public,
                          effective_model_config=effective,model_config_sha256=digest,**freeze)
            if args.prepare_only:
                from rsi_eval.two_stage_core import ProbeController
                for c in cases.values():
                    controller=ProbeController(c,output/'preview'/c['id'])
                    write(output/'preview'/c['id']/'task-packet.json',controller.task_packet())
                report['status']='prepared'
            else:
                from rsi_eval.two_stage_agent import ProbeStatePacketLLM,RevisionStatePacketLLM,run_two_stage_session
                from rsi_eval.planning_probe import probe_plan
                from rsi_eval.symbolic_probe import probe_symbolic
                from rsi_eval.executor import evaluate_candidate
                from scripts.configure_minimax import auth_path,read_key
                if importlib.metadata.version('openhands-sdk')!='1.55.1':raise ValueError('Wrong SDK version')
                report['sdk_version']=importlib.metadata.version('openhands-sdk')
                settings=dict(effective,api_key=read_key(auth_path(None)))
                def session(c,row,directory,stage):
                    cls=ProbeStatePacketLLM if stage=='probe' else RevisionStatePacketLLM
                    llm=cls(**settings).bind_controller(c).bind_pilot(ledger,row['session_id'],directory/'requests')
                    return run_two_stage_session(c,llm,row['session_id'],directory,stage=stage)
                def probe(case,budget,directory):
                    if case['family']=='planning':
                        values=[]
                        for task_id in case['prompt_task_ids']:
                            token=budget.reserve(case['id']+':'+task_id,1)
                            result=probe_plan(case['source'],task_id,root=ROOT,source_sha256=case['source_sha256'])
                            values.append(result);write(directory/'probe.json',{'results':values})
                            budget.settle(token,result['executions']);check_probe(result)
                        return {'results':values}
                    token=budget.reserve(case['id'],6)
                    kwargs={k:case[k] for k in ('n_params','remove_param_index','source_sha256','parent_source','parent_n_params','parent_sha256')}
                    result=probe_symbolic(case['source'],root=ROOT,case_id=case['id'],epsilon=config['epsilon'],tolerance=config['numeric_tolerance'],**kwargs)
                    write(directory/'probe.json',result)
                    budget.settle(token,dict(result['executions'],execution_accounting_complete=result['execution_accounting_complete']))
                    check_probe(result);return result
                execute(ROOT,output,report,cases,ledger,executions,session,probe,evaluate_candidate)
    except Exception as error:
        report.update(status='error',error_type=type(error).__name__)
    finally:logging.disable(previous)
    if ledger is not None:report['budget']=ledger.summary()
    if executions is not None:report['execution_budget']=executions.summary()
    if output is not None and output.exists():write(output/'summary.json',report)
    print(json.dumps({k:report.get(k) for k in ('run_id','status','error_type','stop_reason','budget','execution_budget')},indent=2))
    return 0 if report['status'] in ('prepared','attempts_completed') else 1


if __name__=='__main__':raise SystemExit(main())
