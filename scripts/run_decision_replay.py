#!/usr/bin/env python3
"""New non-resumable decision experiment over pinned existing probe evidence."""
import argparse
import contextlib
import copy
import hashlib
import importlib.metadata
import io
import json
import logging
import os
from pathlib import Path
import re
import sys

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
os.environ['OPENHANDS_SUPPRESS_BANNER']='1'
os.environ['LITELLM_LOCAL_MODEL_COST_MAP']='True'
os.environ['DO_NOT_TRACK']='1'
from scripts.run_two_stage import (COUNTS, ExecutionLedger, canonical, read, write, sha,
    directory_hashes, verify_files, runtime_freeze as legacy_runtime_freeze,
    assert_runtime, classify_session, request_id)

CONFIG_PATH='configs/pilots/decision-replay-v0.1.json'
PROTOCOL='docs/protocols/2026-10-21-decision-replay-v0.1.md'
CASE_ORDER=['P-format','P-empty','S-v3','S-x5']


def validate_config(config):
    expected={'version':'decision-replay-v0.1','protocol':PROTOCOL,
        'case_order':CASE_ORDER,'repeats':2,'minimum_gain_nmse':1e-5,
        'simplification_loss_nmse':1e-5,'numeric_tolerance':1e-10,
        'max_sandbox_calls':96,'resume':False,'new_probe_executions':0,
        'sealed_tasks_executed':0,'budgets':{'max_requests':16,'max_requests_per_session':1,
        'max_output_tokens':4096,'max_input_bytes':98304,'max_reserved_tokens':2000000,
        'max_cost_cny':5,'input_cny_per_million':2.1,'output_cny_per_million':8.4}}
    if canonical(config)!=canonical(expected):raise ValueError('Frozen configuration changed')
    return copy.deepcopy(config)


def actor_order():
    first=[('P-format',['hidden','checked']),('S-v3',['checked','hidden']),
           ('P-empty',['checked','hidden']),('S-x5',['hidden','checked'])]
    return [dict(case_id=case,repeat=repeat,condition=arm,
                 session_id=f'{case}-r{repeat}-{arm}')
            for repeat in (1,2) for case,arms in first
            for arm in (arms if repeat==1 else arms[::-1])]


def runtime_freeze(root,*,allow_dirty=False):
    freeze=legacy_runtime_freeze(root,allow_dirty=allow_dirty)
    freeze['runtime_files_sha256'][PROTOCOL]=sha(root/PROTOCOL)
    return freeze


def freeze_inputs(output,cases):
    if (output/'inputs').exists() or (output/'inputs-freeze.json').exists():
        raise FileExistsError('Refusing to replace frozen inputs')
    write(output/'inputs/cases.json',cases)
    write(output/'inputs-freeze.json',{'version':'decision-inputs-v0.1',
        'files':directory_hashes(output/'inputs'),'new_probe_executions':0})
    return sha(output/'inputs-freeze.json')


def verify_inputs(output,digest):
    if sha(output/'inputs-freeze.json')!=digest:raise ValueError('Frozen input anchor changed')
    verify_files(output/'inputs',read(output/'inputs-freeze.json')['files'])


def checked_execution_counts(record):
    from scripts.run_intervention_probes import evaluator_counts
    phases=record.get('executions')
    if (type(phases) is not list or any(type(p) is not dict or p.get('phase') not in
            ('plan','fit','predict') for p in phases)
            or record.get('execution_accounting_complete',True) is not True
            or record.get('status') in ('infrastructure_error','invalid_request')):
        raise ValueError('Incomplete or failed candidate execution accounting')
    names=[p['phase'] for p in phases];family=record.get('family')
    allowed=([],['plan']) if family=='planning' else ([],['fit'],['fit','predict']) if family=='symbolic' else ()
    required=['plan'] if family=='planning' else ['fit','predict']
    if names not in allowed or record.get('status')=='success' and names!=required:
        raise ValueError('Execution phases do not support the reported family/outcome')
    counts=evaluator_counts(record)
    if counts.get('val_count_complete') is False:
        raise ValueError('Incomplete validator accounting')
    return counts


def execute(root,output,report,cases,ledger,executions,session_runner,eval_runner):
    from rsi_eval.decision_core import DecisionController
    from rsi_eval.two_stage_core import common_request
    from scripts.run_policy_transfer import budget_blocked
    freeze=read(output/'runtime-freeze.json')
    def save():
        report['budget']=ledger.summary();report['execution_budget']=executions.summary()
        write(output/'summary.json',report)
    def guard():
        assert_runtime(root,freeze)
        verify_inputs(output,report['inputs_freeze_sha256'])
    proofs={}
    for row in report['revisions']:
        guard();case=cases[row['case_id']];directory=output/'sessions'/row['session_id']
        def evaluate(*args,**kwargs):
            guard()
            if budget_blocked(ledger.summary()):
                raise RuntimeError('Candidate execution refused after unsettled or unknown model usage')
            family=args[0] if args else kwargs['family']
            task=args[1] if len(args)>1 else kwargs['task_id']
            token=executions.reserve(row['session_id']+':'+task,1 if family=='planning' else 2)
            result=eval_runner(*args,**kwargs)
            counts=checked_execution_counts(result);executions.settle(token,counts);save()
            return result
        feedback=case['archive_feedback'] if row['condition']=='checked' else None
        controller=DecisionController(case,feedback,root,directory,evaluator=evaluate)
        write(directory/'task-packet.json',controller.task_packet())
        raw=session_runner(controller,row,directory);row.update(raw)
        if (controller.summary().get('counts',{}).get('counts_complete') is False
                or not executions.summary()['accounting_complete']):
            controller.halted=True
        candidate=controller.summary().get('candidate')
        row['candidate']=candidate
        row['disposition']=classify_session(raw,controller,ledger.summary(),candidate is not None)
        if row['disposition']=='blocked':
            report.update(status='stopped',stop_reason='decision_infrastructure_or_usage');save();return
        row['request_id']=request_id(output,row['session_id'])
        requests=list((directory/'requests').glob('*.request.json'))
        if len(requests)!=1:raise ValueError('Exactly one real request required')
        digest=hashlib.sha256(canonical(common_request(read(requests[0])))).hexdigest()
        if row['case_id'] in proofs and proofs[row['case_id']]!=digest:
            raise ValueError('Actual common request differs')
        proofs[row['case_id']]=digest
        report['common_request_sha256']=dict(proofs);save()
    guard();report['status']='attempts_completed';save()


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--run-id',required=True)
    modes=parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--prepare-only',action='store_true');modes.add_argument('--run',action='store_true')
    args=parser.parse_args(argv)
    if not re.fullmatch('[A-Za-z0-9][A-Za-z0-9_-]{0,63}',args.run_id):parser.error('Invalid run ID')
    report={'run_id':args.run_id,'status':'error','sealed_tasks_executed':0,
            'new_probe_executions':0,'strategy_updated':False,'resumed':False,'model_weights_updated':False}
    output=None;ledger=None;executions=None
    previous=logging.root.manager.disable;logging.disable(logging.CRITICAL)
    try:
        with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
            from rsi_eval.decision_cases import load_cases
            from rsi_eval.decision_core import DecisionController
            from rsi_eval.pilot_budget import BudgetLedger
            from scripts.run_checked_feedback import _model_configuration
            config=validate_config(read(ROOT/CONFIG_PATH));cases={c['id']:c for c in load_cases(ROOT)}
            if list(cases)!=CASE_ORDER:raise ValueError('Case order changed')
            freeze=runtime_freeze(ROOT,allow_dirty=args.prepare_only)
            parent=ROOT/'runs/decision-replay';target=parent/args.run_id
            if any(p.is_symlink() for p in (ROOT/'runs',parent,target)):raise ValueError('Output symlink')
            target.mkdir(parents=True,exist_ok=False);output=target
            write(output/'runtime-freeze.json',freeze);write(output/'config.json',config)
            report['inputs_freeze_sha256']=freeze_inputs(output,cases)
            revisions=[dict(row,status='not_started') for row in actor_order()]
            ledger=BudgetLedger(output/'budget-ledger.json',
                session_ids=[r['session_id'] for r in revisions],**config['budgets'])
            executions=ExecutionLedger(output/'execution-ledger.json',config['max_sandbox_calls'])
            digest,public,effective=_model_configuration(ROOT/'configs/models/minimax-m3.json',config['budgets'])
            report.update(revisions=revisions,model_config=public,effective_model_config=effective,
                          model_config_sha256=digest,**freeze)
            if args.prepare_only:
                for case in cases.values():
                    for arm in ('hidden','checked'):
                        directory=output/'preview'/case['id']/arm
                        c=DecisionController(case,case['archive_feedback'] if arm=='checked' else None,ROOT,directory)
                        write(directory/'task-packet.json',c.task_packet())
                report['status']='prepared'
            else:
                from rsi_eval.decision_agent import run_decision_session,RevisionStatePacketLLM
                from rsi_eval.executor import evaluate_candidate
                from scripts.configure_minimax import auth_path,read_key
                if importlib.metadata.version('openhands-sdk')!='1.55.1':raise ValueError('Wrong SDK version')
                report['sdk_version']=importlib.metadata.version('openhands-sdk')
                settings=dict(effective,api_key=read_key(auth_path(None)))
                def session(c,row,directory):
                    llm=RevisionStatePacketLLM(**settings).bind_controller(c).bind_pilot(
                        ledger,row['session_id'],directory/'requests')
                    return run_decision_session(c,llm,row['session_id'],directory)
                execute(ROOT,output,report,cases,ledger,executions,session,evaluate_candidate)
    except Exception as error:
        report.update(status='error',error_type=type(error).__name__)
    finally:logging.disable(previous)
    if ledger is not None:report['budget']=ledger.summary()
    if executions is not None:report['execution_budget']=executions.summary()
    if output is not None:write(output/'summary.json',report)
    print(json.dumps({k:report.get(k) for k in ('run_id','status','error_type','stop_reason','budget','execution_budget')},indent=2))
    return 0 if report['status'] in ('prepared','attempts_completed') else 1


if __name__=='__main__':raise SystemExit(main())
