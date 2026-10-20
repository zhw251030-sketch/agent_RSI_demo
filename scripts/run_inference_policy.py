#!/usr/bin/env python3
"""Evidence-requirement review with explicit missing slots and frozen policies."""
import argparse
import contextlib
import copy
import hashlib
import importlib.metadata
import io
import json
import logging
import math
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
os.environ['OPENHANDS_SUPPRESS_BANNER']='1'
os.environ['LITELLM_LOCAL_MODEL_COST_MAP']='True'
os.environ['DO_NOT_TRACK']='1'
CONFIG_PATH='configs/pilots/inference-policy-v0.1.json'
PROTOCOL='docs/protocols/2026-10-20-inference-policy-v0.1.md'
ACTOR_PROMPT='prompts/policy-transfer/actor.md'
from rsi_eval.policy_transfer import canonical
from scripts.run_paired_repair import write_json
from scripts.run_policy_transfer import exclusive_json,budget_blocked
from scripts.run_grounded_policy import sha,read,update_order,settled_request,evaluate


def evaluation_order():
    values=[('p1','P-A002','self'),('p1','S-poly5','checked'),('p1','P-A002','checked'),
        ('p1','S-poly5','self'),('p2','S-odd4','self'),('p2','P-H002','checked'),
        ('p2','S-odd4','checked'),('p2','P-H002','self')]
    return [dict(policy_pair=p,pair_id=p+'-'+s,state_id=s,condition=a,
        family='planning' if s.startswith('P-') else 'symbolic',session_id=p+'-'+s+'-'+a)
        for p,s,a in values]


def validate_config(config):
    expected={'schema_version':'0.1','base_config':'configs/pilots/development-v0.1.json',
        'protocol':PROTOCOL,'policy_file':ACTOR_PROMPT,'update_order':update_order(),
        'evaluation_order':evaluation_order(),'max_iterations':1,'max_generated_candidates':1,
        'automatic_recovery':False,'baseline_reexecution':False,'checks_gate_execution':False,
        'checks_change_selection':False,'missing_candidate_score':None,'missing_policy_fallback':None,
        'continue_independent_known_failures':True}
    if any(type(config.get(k)) is not type(v) or config.get(k)!=v for k,v in expected.items()):
        raise ValueError('Frozen protocol identity changed')
    limits={'max_requests':14,'max_requests_per_session':1,'max_output_tokens':4096,
        'max_input_bytes':98304,'max_reserved_tokens':1900000}
    prices={'max_cost_cny','input_cny_per_million','output_cny_per_million'}
    budgets=config.get('budgets',{})
    if set(budgets)!=set(limits)|prices:raise ValueError('Unexpected budgets')
    for key,cap in limits.items():
        if type(budgets[key]) is not int or not 0<budgets[key]<=cap:raise ValueError('Budget outside bound')
    for key in prices:
        if type(budgets[key]) not in (int,float) or not math.isfinite(budgets[key]) or budgets[key]<=0:
            raise ValueError('Invalid cost')
    if budgets['max_cost_cny']>5 or budgets['input_cny_per_million']<2.1 or budgets['output_cny_per_million']<8.4:
        raise ValueError('Cost cap or prices changed')
    return copy.deepcopy(budgets)


def dependency_missing(row,completed):
    return row['condition']!='proposal' and completed.get(row['pair_id']+'-proposal',{}).get('disposition')!='available'


def classify_update(raw,controller,budget):
    if budget_blocked(budget) or controller.halted:return 'blocked'
    known=bool({'IncompleteToolResponseError','PilotResponseContractError'} &
        {raw.get('model_error_type'),raw.get('cause_type')})
    if (raw.get('status')=='error' or raw.get('model_error_type')) and not known:return 'blocked'
    if known:return 'missing'
    return 'available' if controller.policy is not None else 'missing'


def directory_hashes(directory):
    directory=Path(directory)
    if directory.is_symlink():raise ValueError('Symlinked update directory')
    result={}
    for path in sorted(directory.rglob('*')):
        if path.is_symlink():raise ValueError('Symlink in frozen update')
        if path.is_file():result[path.relative_to(directory).as_posix()]=sha(path)
    return result


def request_for(state,session):
    if state.get('halted') or any(r.get('usage_state')!='known' or r.get('status') not in ('settled','failed') for r in state['requests']):
        raise ValueError('Unsafe ledger phase state')
    rows=[r for r in state['requests'] if r['session_id']==session]
    if len(rows)!=1 or type(rows[0].get('usage')) is not dict:raise ValueError('Expected exactly one known request')
    return rows[0]['request_id']


def execute_updates(output,report,bundle,ledger,session_runner):
    from rsi_eval.inference_policy import InferencePolicyController,freeze_policy,load_frozen_policy
    from rsi_eval.revision_policy import S0
    completed={};proofs={};slots={}
    for row in report['updates']:
        session=row['session_id'];directory=output/session;pair=row['pair_id']
        if budget_blocked(ledger.summary()):
            report.update(status='stopped',stop_reason='budget_or_unknown_usage');return
        if dependency_missing(row,completed):
            row.update(disposition='skipped_dependency',status='not_started_missing_proposal',policy_available=False)
            completed[session]=row
            slots[session]={'disposition':'skipped_dependency','request_id':None,'freeze_sha256':None,'files':{}}
            continue
        initial=output/(pair+'-proposal')
        if row['condition']!='proposal':
            load_frozen_policy(initial,bundle,S0,condition='proposal',pair_id=pair,
                expected_freeze_sha256=slots[pair+'-proposal']['freeze_sha256'])
        proposal=None if row['condition']=='proposal' else read(initial/'submission.json')
        feedback=read(initial/'checks.json') if row['condition']=='checked' else None
        c=InferencePolicyController(bundle,S0,directory,proposal=proposal,feedback=feedback,pair_id=pair)
        packet=c.state_packet();write_json(directory/'task-packet.json',packet)
        if proposal is not None:
            common=copy.deepcopy(packet);common.pop('inference_feedback');value=canonical(common)
            if pair in proofs and proofs[pair]!=value:raise ValueError('Review common packet mismatch')
            proofs[pair]=value
        raw=session_runner(c,row,directory);row.update(raw)
        disposition=classify_update(raw,c,ledger.summary());row['disposition']=disposition
        row['policy_available']=disposition=='available'
        if disposition=='blocked':
            report.update(status='stopped',stop_reason='update_infrastructure_or_unknown_failure')
            write_json(directory/'session-summary.json',row);return
        request=request_for(read(output/'budget-ledger.json'),session)
        if disposition=='available':
            settled_request(read(output/'budget-ledger.json'),session)
            freeze_policy(directory,bundle,S0,request,proposal=proposal,feedback=feedback,
                condition=row['condition'],pair_id=pair)
            row['selected_policy']=c.policy
        row['request_id']=request
        write_json(directory/'session-summary.json',row)
        slots[session]={'disposition':disposition,'request_id':request,
            'freeze_sha256':sha(directory/'freeze.json') if disposition=='available' else None,
            'files':directory_hashes(directory)}
        completed[session]=row
        write_json(output/'summary.json',dict(report,budget=ledger.summary()))
    exclusive_json(output/'update-phase-freeze.json',{'version':'inference-phase-v0.1','slots':slots})
    report.update(status='updates_frozen',phase_freeze_sha256=sha(output/'update-phase-freeze.json'),
        review_input_proofs={key:hashlib.sha256(value).hexdigest() for key,value in proofs.items()})


def load_phase(output,bundle,summary):
    from rsi_eval.inference_policy import load_frozen_policy
    from rsi_eval.revision_policy import S0
    if summary.get('phase_freeze_sha256')!=sha(output/'update-phase-freeze.json'):raise ValueError('Phase anchor changed')
    manifest=read(output/'update-phase-freeze.json');slots=manifest.get('slots',{})
    if manifest.get('version')!='inference-phase-v0.1' or set(slots)!={r['session_id'] for r in update_order()}:
        raise ValueError('Incomplete update slots')
    policies={};ledger=read(output/'budget-ledger.json')
    for row in update_order():
        session=row['session_id'];slot=slots[session];directory=output/session
        if set(slot)!={'disposition','request_id','freeze_sha256','files'}:raise ValueError('Unknown slot fields')
        if directory_hashes(directory)!=slot['files']:raise ValueError('Frozen update files changed')
        disposition=slot['disposition'];missing_parent=dependency_missing(row,slots)
        if disposition=='skipped_dependency':
            if not missing_parent or slot['files'] or slot['request_id'] is not None or slot['freeze_sha256'] is not None:
                raise ValueError('Invalid missing dependency')
            if any(r['session_id']==session for r in ledger['requests']):raise ValueError('Skipped slot has request')
            continue
        if missing_parent or disposition not in ('available','missing'):raise ValueError('Invalid terminal slot')
        if request_for(ledger,session)!=slot['request_id']:raise ValueError('Slot request mismatch')
        if disposition=='missing':
            if slot['freeze_sha256'] is not None or (directory/'policy.json').exists():raise ValueError('Missing slot acquired policy')
            continue
        initial=output/(row['pair_id']+'-proposal')
        proposal=None if row['condition']=='proposal' else read(initial/'submission.json')
        feedback=read(initial/'checks.json') if row['condition']=='checked' else None
        policy=load_frozen_policy(directory,bundle,S0,proposal=proposal,feedback=feedback,
            condition=row['condition'],pair_id=row['pair_id'],expected_freeze_sha256=slot['freeze_sha256'])
        if read(directory/'freeze.json')['request_id']!=settled_request(ledger,session):raise ValueError('Freeze request mismatch')
        if row['condition']!='proposal':policies[session]=policy
    return policies


def verify_pairs(prepared):
    groups={};proofs={}
    for c,_,row in prepared:groups.setdefault(row['pair_id'],[]).append((c,row))
    for pair,group in groups.items():
        conditions=[r['condition'] for _,r in group]
        if len(group)>2 or len(set(conditions))!=len(group) or not set(conditions)<={'self','checked'}:
            raise ValueError('Invalid actor group')
        packets=[]
        for c,_ in group:
            packet=copy.deepcopy(c.state_packet());packet.pop('repair_policy');packets.append(canonical(packet))
        if len(set(packets))!=1 or len({(c.records[0]['source_sha256'],c.records[0]['n_params']) for c,_ in group})!=1:
            raise ValueError('Actor common inputs mismatch')
        proofs[pair]={'both_available':len(group)==2,'conditions':conditions,
            'common_sha256':hashlib.sha256(packets[0]).hexdigest(),'common_bytes':len(packets[0])}
    return proofs


def prepare_actors(output,report,base_sessions,states,policies,guard=None):
    from rsi_eval.policy_transfer import PolicyTransferController
    prepared=[]
    for row in report['sessions']:
        key=row['policy_pair']+'-'+row['condition']
        if key not in policies:
            row.update(status='not_started_policy_unavailable',policy_available=False,endpoint=None);continue
        directory=output/row['session_id']
        c=PolicyTransferController(ROOT,base_sessions[row['family']],directory,
            session_id=report['run_id']+':'+row['pair_id'],policy_text=(ROOT/ACTOR_PROMPT).read_text(encoding='utf-8'),
            repair_state=states[row['state_id']],policy=policies[key],experience_memory=[],policy_guard=guard)
        baseline=c.baseline();write_json(directory/'task-prompt.json',c.state_packet())
        row.update(status='prepared',policy_available=True,selected_policy=policies[key],
            baseline_source_sha256=baseline['source_sha256'],baseline_n_params=baseline['n_params'])
        prepared.append((c,directory,row))
    report['pair_input_proofs']=verify_pairs(prepared)
    return prepared


def provenance():
    paths=[p for part in ('rsi_eval','scripts','configs','prompts','fixtures') for p in (ROOT/part).rglob('*')
        if p.is_file() and p.suffix in ('.py','.json','.md')]+[ROOT/PROTOCOL]
    return {'code_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        'sdk_version':importlib.metadata.version('openhands-sdk'),
        'source_sha256':{p.relative_to(ROOT).as_posix():sha(p) for p in sorted(paths)}}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--run-id',required=True)
    group=parser.add_mutually_exclusive_group(required=True)
    for name in ('prepare-only','update','evaluate'):group.add_argument('--'+name,action='store_true')
    args=parser.parse_args(argv)
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}',args.run_id):parser.error('Invalid run ID')
    mode='evaluate' if args.evaluate else 'update' if args.update else 'prepare_only'
    report={'run_id':args.run_id,'mode':mode,'status':'error','sealed_test_evaluations':0,
        'baseline_reexecutions':0,'automatic_recovery_enabled':False}
    output=ledger=None;previous_disable=logging.root.manager.disable;logging.disable(logging.CRITICAL)
    try:
        with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
            from rsi_eval.inference_cases import load_inference_bundle,load_inference_states
            from rsi_eval.inference_policy import InferencePolicyController,fixture_submission
            from rsi_eval.revision_policy import S0
            from rsi_eval.pilot_budget import BudgetLedger
            from scripts.run_checked_feedback import _base_sessions,_model_configuration
            from scripts.configure_minimax import CONFIG,auth_path,read_key
            config=read(ROOT/CONFIG_PATH);budgets=validate_config(config)
            bundle=load_inference_bundle(ROOT);states={s['state_id']:s for s in load_inference_states(ROOT)}
            base=read(ROOT/config['base_config']);base_sessions=_base_sessions(base)
            model_path=(ROOT/base['model_configuration']).resolve()
            if model_path!=Path(CONFIG).resolve():raise ValueError('Ambient model override')
            model_hash,public,effective=_model_configuration(model_path,budgets)
            identity=dict(config_sha256=sha(ROOT/CONFIG_PATH),model_config_sha256=model_hash,
                model_config=public,effective_model_config=effective,**provenance())
            if identity['sdk_version']!='1.55.1':raise ValueError('Wrong SDK version')
            parent=ROOT/'runs/inference-policy';target=parent/args.run_id
            if (ROOT/'runs').is_symlink() or parent.is_symlink() or not parent.resolve().is_relative_to(ROOT.resolve()):raise ValueError('Output escape')
            if args.evaluate:
                if target.is_symlink() or not target.is_dir():raise ValueError('Missing update phase')
                previous=read(target/'summary.json')
                if previous.get('status')!='updates_frozen' or previous.get('mode')!='update':raise ValueError('Invalid or repeated phase')
                if any(previous.get(k)!=v for k,v in identity.items()) or read(target/'update-bundle.json')!=bundle:raise ValueError('Phase identity changed')
                policies=load_phase(target,bundle,previous)
                exclusive_json(target/'evaluation-started.json',{'phase_freeze_sha256':previous['phase_freeze_sha256']})
                output=target;report=dict(previous,mode=mode,status='evaluating')
            else:
                target.mkdir(parents=True,exist_ok=False);output=target
                report.update(identity,updates=[dict(r,status='not_started') for r in update_order()],
                    sessions=[dict(r,status='not_started') for r in evaluation_order()])
                write_json(output/'config.json',config);write_json(output/'base-config.json',base)
                write_json(output/'update-bundle.json',bundle)
                write_json(output/'state-provenance.json',{k:v['provenance'] for k,v in states.items()})
            ledger=BudgetLedger(output/'budget-ledger.json',session_ids=[r['session_id'] for r in update_order()+evaluation_order()],**budgets)
            if budget_blocked(ledger.summary()):raise ValueError('Unsafe budget')
            if args.prepare_only:
                c=InferencePolicyController(bundle,S0,output/'fixture',pair_id='offline')
                c.submit_policy(**fixture_submission(bundle));report['synthetic_policy_fixture']=c.policy
                prepare_actors(output,report,base_sessions,states,{r['session_id']:S0 for r in update_order()})
                report['status']='prepared'
            elif args.update:
                from rsi_eval.inference_policy_agent import InferencePolicyStatePacketLLM,run_inference_policy_session
                settings=dict(effective,api_key=read_key(auth_path(None)))
                def run(c,row,directory):
                    llm=InferencePolicyStatePacketLLM(**settings).bind_controller(c).bind_pilot(ledger,row['session_id'],directory/'requests')
                    return run_inference_policy_session(c,llm,row['session_id'],directory)
                execute_updates(output,report,bundle,ledger,run)
            else:
                def guard():
                    if load_phase(output,bundle,report)!=policies:raise ValueError('Frozen phase changed')
                prepared=prepare_actors(output,report,base_sessions,states,policies,guard)
                settings=dict(effective,api_key=read_key(auth_path(None)))
                evaluate(prepared,report,ledger,settings)
    except Exception as error:report.update(status='error',error_type=type(error).__name__)
    finally:logging.disable(previous_disable)
    if ledger is not None:report['budget']=ledger.summary()
    if output is not None:write_json(output/'summary.json',report)
    print(json.dumps({k:report.get(k) for k in ('run_id','mode','status','error_type','budget')},indent=2))
    return 0 if report['status'] in ('prepared','updates_frozen','attempts_completed') else 1


if __name__=='__main__':raise SystemExit(main())
