#!/usr/bin/env python3
"""Frozen shared drafts, paired commitment reviews, final-only evaluations."""
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
from scripts.run_two_stage import (COUNTS,ExecutionLedger,canonical,read,write,sha,
    directory_hashes,verify_files,runtime_freeze as legacy_runtime_freeze,
    assert_runtime,classify_session,request_id)
from scripts.run_decision_replay import freeze_inputs,verify_inputs,checked_execution_counts

CONFIG_PATH='configs/pilots/edit-commitment-v0.1.json'
PROTOCOL='docs/protocols/2026-10-21-edit-commitment-v0.1.md'
CASE_ORDER=['P-format','S-v3','P-empty','S-x5']


def validate_config(config):
    expected={'version':'edit-commitment-v0.1','protocol':PROTOCOL,'case_order':CASE_ORDER,
        'max_sandbox_calls':48,'resume':False,'new_probe_executions':0,'draft_executions':0,
        'sealed_tasks_executed':0,'budgets':{'max_requests':12,'max_requests_per_session':1,
        'max_output_tokens':4096,'max_input_bytes':98304,'max_reserved_tokens':1600000,
        'max_cost_cny':5,'input_cny_per_million':2.1,'output_cny_per_million':8.4}}
    if canonical(config)!=canonical(expected):raise ValueError('Frozen configuration changed')
    return copy.deepcopy(config)


def draft_order():
    return [dict(case_id=c,stage='draft',session_id=c+'-draft') for c in CASE_ORDER]


def review_order():
    return [dict(case_id=c,stage='review',condition=arm,session_id=c+'-'+arm)
            for c,arms in zip(CASE_ORDER,[('self','checked'),('checked','self'),
                                         ('checked','self'),('self','checked')]) for arm in arms]


def runtime_freeze(root,*,allow_dirty=False):
    result=legacy_runtime_freeze(root,allow_dirty=allow_dirty)
    result['runtime_files_sha256'][PROTOCOL]=sha(root/PROTOCOL)
    for path in sorted((root/'tests').glob('test_commitment_*.py')):
        result['runtime_files_sha256'][path.relative_to(root).as_posix()]=sha(path)
    return result


def execute(root,output,report,cases,ledger,executions,session_runner,eval_runner):
    from rsi_eval.commitment_core import DraftController,ReviewController,check_submission,common_request
    from scripts.run_policy_transfer import budget_blocked
    freeze=read(output/'runtime-freeze.json')
    def save():
        report['budget']=ledger.summary();report['execution_budget']=executions.summary()
        write(output/'summary.json',report)
    def guard():
        assert_runtime(root,freeze);verify_inputs(output,report['inputs_freeze_sha256'])
    drafts={}
    report['common_request_sha256']={}
    for row in report['drafts']:
        guard();directory=output/'drafts'/row['case_id']
        c=DraftController(cases[row['case_id']],directory)
        write(directory/'task-packet.json',c.task_packet())
        raw=session_runner(c,row,directory);row.update(raw)
        row['draft']=copy.deepcopy(c.draft)
        row['disposition']=classify_session(raw,c,ledger.summary(),c.draft is not None)
        if row['disposition']=='blocked':
            report.update(status='stopped',stop_reason='draft_infrastructure_or_usage');save();return
        row['request_id']=request_id(output,row['session_id'])
        if row['disposition']=='available':drafts[row['case_id']]=copy.deepcopy(c.draft)
        save()
    guard()
    frozen={'drafts':drafts,'files':directory_hashes(output/'drafts')}
    write(output/'draft-freeze.json',frozen)
    report['draft_freeze_sha256']=sha(output/'draft-freeze.json');save()
    def draft_guard():
        guard()
        if sha(output/'draft-freeze.json')!=report['draft_freeze_sha256']:
            raise ValueError('Draft freeze changed')
        verify_files(output/'drafts',frozen['files'])
    draft_guard()
    feedback={key:check_submission(cases[key],draft,root) for key,draft in drafts.items()}
    write(output/'feedback-freeze.json',{'feedback':feedback,'draft_freeze_sha256':report['draft_freeze_sha256']})
    report['feedback_freeze_sha256']=sha(output/'feedback-freeze.json');save()
    def review_guard():
        draft_guard()
        if sha(output/'feedback-freeze.json')!=report['feedback_freeze_sha256']:
            raise ValueError('Feedback freeze changed')
    proofs={}
    (output/'reviews').mkdir(exist_ok=False)
    for row in report['reviews']:
        review_guard();key=row['case_id']
        if key not in drafts:
            row.update(disposition='skipped_missing_draft',candidate=None);save();continue
        case=cases[key];directory=output/'reviews'/row['session_id']
        def evaluate(*args,**kwargs):
            review_guard()
            if budget_blocked(ledger.summary()):
                raise RuntimeError('Evaluation refused after unsettled or unknown usage')
            family=args[0] if args else kwargs['family'];task=args[1] if len(args)>1 else kwargs['task_id']
            token=executions.reserve(row['session_id']+':'+task,1 if family=='planning' else 2)
            result=eval_runner(*args,**kwargs)
            executions.settle(token,checked_execution_counts(result));save();return result
        c=ReviewController(case,drafts[key],feedback[key] if row['condition']=='checked' else None,
                           root,directory,evaluator=evaluate)
        write(directory/'task-packet.json',c.task_packet())
        raw=session_runner(c,row,directory);row.update(raw)
        if c.counts['counts_complete'] is False or not executions.summary()['accounting_complete']:
            c.halted=True
        row['candidate']=copy.deepcopy(c.candidate)
        row['disposition']=classify_session(raw,c,ledger.summary(),c.candidate is not None)
        if row['disposition']=='blocked':
            report.update(status='stopped',stop_reason='review_infrastructure_or_usage');save();return
        row['request_id']=request_id(output,row['session_id'])
        payloads=list((directory/'requests').glob('*.request.json'))
        if len(payloads)!=1:raise ValueError('Exactly one request per review required')
        digest=hashlib.sha256(canonical(common_request(read(payloads[0])))).hexdigest()
        if key in proofs and proofs[key]!=digest:raise ValueError('Actual common request differs')
        proofs[key]=digest;report['common_request_sha256']=dict(proofs);save()
    review_guard();report['status']='attempts_completed';save()


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--run-id',required=True)
    modes=parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--prepare-only',action='store_true');modes.add_argument('--run',action='store_true')
    args=parser.parse_args(argv)
    if not re.fullmatch('[A-Za-z0-9][A-Za-z0-9_-]{0,63}',args.run_id):parser.error('Invalid run ID')
    report=dict(run_id=args.run_id,status='preparing',sealed_tasks_executed=0,draft_executions=0,
        new_probe_executions=0,strategy_updated=False,model_weights_updated=False,resumed=False)
    output=None;ledger=None;executions=None
    previous=logging.root.manager.disable;logging.disable(logging.CRITICAL)
    try:
        with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
            from rsi_eval.decision_cases import load_cases
            from rsi_eval.commitment_core import DraftController,ReviewController,check_submission
            from rsi_eval.pilot_budget import BudgetLedger
            from scripts.run_checked_feedback import _model_configuration
            config=validate_config(read(ROOT/CONFIG_PATH))
            source_cases={c['id']:c for c in load_cases(ROOT)};cases={k:source_cases[k] for k in CASE_ORDER}
            freeze=runtime_freeze(ROOT,allow_dirty=args.prepare_only)
            parent=ROOT/'runs/edit-commitment';target=parent/args.run_id
            if any(p.is_symlink() for p in (ROOT/'runs',parent,target)):raise ValueError('Output symlink')
            target.mkdir(parents=True,exist_ok=False);output=target
            write(output/'runtime-freeze.json',freeze);write(output/'config.json',config)
            report['inputs_freeze_sha256']=freeze_inputs(output,cases)
            report.update(drafts=[dict(r,status='not_started') for r in draft_order()],
                          reviews=[dict(r,status='not_started') for r in review_order()],**freeze)
            ledger=BudgetLedger(output/'budget-ledger.json',session_ids=[r['session_id'] for r in
                report['drafts']+report['reviews']],**config['budgets'])
            executions=ExecutionLedger(output/'execution-ledger.json',48)
            digest,public,effective=_model_configuration(ROOT/'configs/models/minimax-m3.json',config['budgets'])
            report.update(model_config=public,effective_model_config=effective,model_config_sha256=digest)
            if args.prepare_only:
                for case in cases.values():
                    c=DraftController(case,output/'preview'/case['id']/'draft')
                    write(c.output_dir/'task-packet.json',c.task_packet())
                    draft=dict(source=case['source'],n_params=case['n_params'],rationale='',auxiliary={},
                               edit_claim='keep_ast',deployment_claim='unspecified')
                    for arm in ('self','checked'):
                        c=ReviewController(case,draft,check_submission(case,draft,ROOT) if arm=='checked' else None,
                                           ROOT,output/'preview'/case['id']/arm)
                        write(c.output_dir/'task-packet.json',c.task_packet())
                report['status']='prepared'
            else:
                from rsi_eval.commitment_agent import run_commitment_session,DraftStatePacketLLM,ReviewStatePacketLLM
                from rsi_eval.executor import evaluate_candidate
                from scripts.configure_minimax import auth_path,read_key
                if importlib.metadata.version('openhands-sdk')!='1.55.1':raise ValueError('Wrong SDK version')
                report['sdk_version']=importlib.metadata.version('openhands-sdk')
                settings=dict(effective,api_key=read_key(auth_path(None)));report['status']='running'
                def session(c,row,directory):
                    klass=DraftStatePacketLLM if row['stage']=='draft' else ReviewStatePacketLLM
                    llm=klass(**settings).bind_controller(c).bind_pilot(ledger,row['session_id'],directory/'requests')
                    return run_commitment_session(c,llm,row['session_id'],directory,stage=row['stage'])
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
