#!/usr/bin/env python3
"""Matched policy premise review, then separate-process four-state repairs."""
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

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
os.environ['OPENHANDS_SUPPRESS_BANNER']='1'
os.environ['LITELLM_LOCAL_MODEL_COST_MAP']='True'
os.environ['DO_NOT_TRACK']='1'
CONFIG_PATH='configs/pilots/grounded-policy-v0.1.json'
PROTOCOL='docs/protocols/2026-10-20-grounded-policy-v0.1.md'
ACTOR_PROMPT='prompts/policy-transfer/actor.md'
from rsi_eval.policy_transfer import canonical
from scripts.run_paired_repair import summarize_endpoint,write_json
from scripts.run_policy_transfer import exclusive_json,budget_blocked


def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def read(path): return json.loads(Path(path).read_bytes())


def update_order():
    return [dict(pair_id=pair,condition=condition,session_id=pair+'-'+condition)
            for pair, conditions in [('p1',('proposal','self','checked')),
                                     ('p2',('proposal','checked','self'))]
            for condition in conditions]


def evaluation_order():
    values=[('p1','P-A002','self'),('p1','S-poly5','checked'),('p1','P-A002','checked'),
            ('p1','S-poly5','self'),('p2','S-odd4','self'),('p2','P-B002','checked'),
            ('p2','S-odd4','checked'),('p2','P-B002','self')]
    return [dict(policy_pair=pair,pair_id=pair+'-'+state,state_id=state,condition=arm,
                 family='planning' if state.startswith('P-') else 'symbolic',
                 session_id=pair+'-'+state+'-'+arm) for pair,state,arm in values]


def validate_config(config):
    expected={'schema_version':'0.1','base_config':'configs/pilots/development-v0.1.json',
        'protocol':PROTOCOL,'policy_file':ACTOR_PROMPT,'update_order':update_order(),
        'evaluation_order':evaluation_order(),'max_iterations':1,'max_generated_candidates':1,
        'automatic_recovery':False,'baseline_reexecution':False,'checks_gate_execution':False,
        'checks_change_selection':False,'missing_candidate_score':None}
    if any(type(config.get(k)) is not type(v) or config.get(k)!=v for k,v in expected.items()):
        raise ValueError('Frozen protocol identity changed')
    limits={'max_requests':14,'max_requests_per_session':1,'max_output_tokens':4096,
        'max_input_bytes':98304,'max_reserved_tokens':1900000}
    budgets=config.get('budgets',{})
    prices={'max_cost_cny','input_cny_per_million','output_cny_per_million'}
    if set(budgets)!=set(limits)|prices: raise ValueError('Unexpected budget keys')
    for k,cap in limits.items():
        if type(budgets[k]) is not int or not 0<budgets[k]<=cap: raise ValueError('Budget bound changed')
    for k in prices:
        if type(budgets[k]) not in (float,int) or not math.isfinite(budgets[k]) or budgets[k]<=0:
            raise ValueError('Invalid price or cost cap')
    if budgets['max_cost_cny']>5 or budgets['input_cny_per_million']<2.1 or budgets['output_cny_per_million']<8.4:
        raise ValueError('Cost cap/price changed')
    return copy.deepcopy(budgets)


def settled_request(state,session):
    if state.get('halted') or any(r.get('status')!='settled' or r.get('usage_state')!='known'
                                for r in state.get('requests',[])):
        raise ValueError('Unknown or unsettled usage blocks another phase')
    rows=[r for r in state.get('requests',[]) if r['session_id']==session]
    if len(rows)!=1 or type(rows[0].get('usage')) is not dict:
        raise ValueError('Exactly one known request is required per session')
    return rows[0]['request_id']


def review_common(packet):
    result=copy.deepcopy(packet); result.pop('premise_feedback',None)
    return result


def verify_pairs(prepared):
    groups={}
    for c,_,row in prepared: groups.setdefault(row['pair_id'],[]).append((c,row))
    proofs={}
    for pair,group in groups.items():
        if len(group)!=2 or {r['condition'] for _,r in group}!={'self','checked'}:
            raise ValueError('Expected two matched arms')
        packets=[]
        for c,_ in group:
            packet=copy.deepcopy(c.state_packet()); packet.pop('repair_policy')
            packets.append(canonical(packet))
        starts=[c.records[0] for c,_ in group]
        if len(set(packets))!=1 or len({(r['source_sha256'],r['n_params']) for r in starts})!=1:
            raise ValueError('Common actor input or baseline differs')
        proofs[pair]={'common_sha256':hashlib.sha256(packets[0]).hexdigest(),
            'common_bytes':len(packets[0]),'source_sha256':starts[0]['source_sha256']}
    return proofs


def provenance():
    paths=[p for part in ('rsi_eval','scripts','configs','prompts','fixtures')
           for p in (ROOT/part).rglob('*') if p.is_file() and p.suffix in ('.py','.json','.md')]
    paths.append(ROOT/PROTOCOL)
    return {'code_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        'sdk_version':importlib.metadata.version('openhands-sdk'),
        'source_sha256':{p.relative_to(ROOT).as_posix():sha(p) for p in sorted(paths)}}


def fixture_submission(bundle):
    from rsi_eval.grounded_policy import factual_catalogue
    from rsi_eval.revision_policy import RULES,S0
    facts=factual_catalogue(bundle)
    selected=[next(f for f in facts if f['family']==family) for family in ('planning','symbolic')]
    result={}
    for i,rule in enumerate(S0['rule_ids'],1):
        result.update({f'rule_{i}':rule,f'parent_{i}':True,f'quote_{i}':RULES[rule],
            f'support_{i}':'both',f'hypothesis_{i}':'Synthetic offline fixture, not a model result.',
            f'edit_{i}':'Synthetic offline fixture.'})
    for i,fact in enumerate(selected,1):
        result.update({f'fact_{i}_id':fact['fact_id'],f'fact_{i}_value':json.dumps(fact['value']),
                       f'fact_{i}_scope':fact['scope']})
    return result


def prepare_actors(output,report,base_sessions,states,policies,guard=None):
    from rsi_eval.policy_transfer import PolicyTransferController
    prepared=[]
    for row in report['sessions']:
        directory=output/row['session_id']
        policy=policies[row['policy_pair']+'-'+row['condition']]
        c=PolicyTransferController(ROOT,base_sessions[row['family']],directory,
            session_id=report['run_id']+':'+row['pair_id'],
            policy_text=(ROOT/ACTOR_PROMPT).read_text(encoding='utf-8'),
            repair_state=states[row['state_id']],policy=policy,experience_memory=[],policy_guard=guard)
        baseline=c.baseline()
        packet=c.state_packet(); write_json(directory/'task-prompt.json',packet)
        row.update(status='prepared',baseline_source_sha256=baseline['source_sha256'],
                   baseline_n_params=baseline['n_params'],selected_policy=policy)
        prepared.append((c,directory,row))
    report['pair_input_proofs']=verify_pairs(prepared)
    return prepared


def load_phase(output,bundle,summary):
    from rsi_eval.grounded_policy import load_frozen_policy
    from rsi_eval.revision_policy import S0
    manifest=read(output/'update-phase-freeze.json')
    if summary.get('phase_freeze_sha256')!=sha(output/'update-phase-freeze.json'):
        raise ValueError('Phase anchor changed')
    if set(manifest.get('freezes',{}))!={r['session_id'] for r in update_order()}:
        raise ValueError('Incomplete frozen update phase')
    policies={}
    ledger=read(output/'budget-ledger.json')
    for row in update_order():
        session=row['session_id']; directory=output/session
        initial=output/(row['pair_id']+'-proposal')
        proposal=None if row['condition']=='proposal' else read(initial/'submission.json')
        feedback=read(initial/'checks.json') if row['condition']=='checked' else None
        policy=load_frozen_policy(directory,bundle,S0,proposal=proposal,feedback=feedback,
            condition=row['condition'],pair_id=row['pair_id'],
            expected_freeze_sha256=manifest['freezes'][session])
        if read(directory/'freeze.json')['request_id']!=settled_request(ledger,session):
            raise ValueError('Frozen request differs from ledger')
        if row['condition']!='proposal': policies[session]=policy
    return policies


def updates(output,report,bundle,ledger,settings):
    from rsi_eval.grounded_policy import GroundedPolicyController,freeze_policy,load_frozen_policy
    from rsi_eval.grounded_policy_agent import GroundedPolicyStatePacketLLM,run_grounded_policy_session
    from rsi_eval.revision_policy import S0
    freezes={}; common={}
    for row in report['updates']:
        directory=output/row['session_id']; initial=output/(row['pair_id']+'-proposal')
        if row['condition']!='proposal':
            load_frozen_policy(initial,bundle,S0,condition='proposal',pair_id=row['pair_id'],
                expected_freeze_sha256=freezes[row['pair_id']+'-proposal'])
        proposal=None if row['condition']=='proposal' else read(initial/'submission.json')
        feedback=read(initial/'checks.json') if row['condition']=='checked' else None
        c=GroundedPolicyController(bundle,S0,directory,proposal=proposal,feedback=feedback,pair_id=row['pair_id'])
        packet=c.state_packet(); write_json(directory/'task-packet.json',packet)
        if proposal is not None:
            value=canonical(review_common(packet))
            if row['pair_id'] in common and common[row['pair_id']]!=value:
                raise ValueError('Review branch common packet differs')
            common[row['pair_id']]=value
        llm=GroundedPolicyStatePacketLLM(**settings).bind_controller(c).bind_pilot(
            ledger,row['session_id'],directory/'requests')
        raw=run_grounded_policy_session(c,llm,row['session_id'],directory)
        row.update(raw)
        if c.halted or c.policy is None or budget_blocked(ledger.summary()) or raw.get('status')=='error' or raw.get('model_error_type'):
            row['policy_available']=False
            report.update(status='update_not_frozen',stop_reason='update_missing_or_error')
            write_json(directory/'session-summary.json',row)
            return
        request=settled_request(read(output/'budget-ledger.json'),row['session_id'])
        freeze_policy(directory,bundle,S0,request,proposal=proposal,feedback=feedback,
                      condition=row['condition'],pair_id=row['pair_id'])
        freezes[row['session_id']]=sha(directory/'freeze.json')
        row.update(policy_available=True,selected_policy=c.policy,
                   all_checked_pass=read(directory/'checks.json')['all_checked_pass'])
        write_json(directory/'session-summary.json',row)
        write_json(output/'summary.json',dict(report,budget=ledger.summary()))
    exclusive_json(output/'update-phase-freeze.json',{'version':'grounded-policy-phase-v0.1','freezes':freezes})
    report.update(status='policies_frozen',phase_freeze_sha256=sha(output/'update-phase-freeze.json'),
        review_input_proofs={k:hashlib.sha256(v).hexdigest() for k,v in common.items()})


def evaluate(prepared,report,ledger,settings):
    from rsi_eval.compact_agent import CompactStatePacketLLM,compact_candidate_tool,run_session
    stop=None
    for c,directory,row in prepared:
        if budget_blocked(ledger.summary()): stop='budget_or_unknown_usage'
        if stop:
            row.update(status='not_started_after_stop',stop_reason=stop,endpoint=summarize_endpoint(c)); continue
        try:
            llm=CompactStatePacketLLM(**settings).bind_controller(c).bind_pilot(ledger,row['session_id'],directory/'requests')
            raw=run_session(c,llm,row['session_id'],directory,tool_factory=compact_candidate_tool,max_iterations=1)
            row.update(raw,endpoint=summarize_endpoint(c))
            known=bool({'IncompleteToolResponseError','PilotResponseContractError'} &
                {raw.get('cause_type'),raw.get('model_error_type')})
            if c.halted: stop='controller_infrastructure_error'
            elif (raw.get('status')=='error' or raw.get('model_error_type')) and not known: stop='session_error'
        except Exception as error:
            row.update(status='error',model_error_type=type(error).__name__,endpoint=summarize_endpoint(c))
            stop='session_error'
        row['step_status']='candidate_evaluated' if row['endpoint']['child_metrics'] is not None else 'no_candidate'
        write_json(directory/'session-summary.json',row)
        write_json(directory.parent/'summary.json',dict(report,budget=ledger.summary()))
    report['status']='stopped' if stop or budget_blocked(ledger.summary()) else 'attempts_completed'
    if stop: report['stop_reason']=stop


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-id',required=True)
    group=parser.add_mutually_exclusive_group(required=True)
    for name in ('prepare-only','update','evaluate'): group.add_argument('--'+name,action='store_true')
    args=parser.parse_args(argv)
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}',args.run_id): parser.error('Invalid run ID')
    mode='evaluate' if args.evaluate else 'update' if args.update else 'prepare_only'
    report={'run_id':args.run_id,'mode':mode,'status':'error','sealed_test_evaluations':0,
        'baseline_reexecutions':0,'automatic_recovery_enabled':False}
    output=ledger=None
    old_disable=logging.root.manager.disable; logging.disable(logging.CRITICAL)
    try:
        with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
            from rsi_eval.policy_cases import load_update_bundle
            from rsi_eval.grounded_states import load_grounded_states
            from rsi_eval.pilot_budget import BudgetLedger
            from scripts.run_checked_feedback import _base_sessions,_model_configuration
            from scripts.configure_minimax import CONFIG,auth_path,read_key
            config=read(ROOT/CONFIG_PATH); budgets=validate_config(config)
            bundle=load_update_bundle(ROOT); states={s['state_id']:s for s in load_grounded_states(ROOT)}
            base=read(ROOT/config['base_config']); base_sessions=_base_sessions(base)
            model_path=(ROOT/base['model_configuration']).resolve()
            if model_path!=Path(CONFIG).resolve(): raise ValueError('Ambient model configuration override')
            model_hash,public,effective=_model_configuration(model_path,budgets)
            identity=dict(config_sha256=sha(ROOT/CONFIG_PATH),model_config_sha256=model_hash,
                model_config=public,effective_model_config=effective,**provenance())
            if identity['sdk_version']!='1.55.1': raise ValueError('Wrong SDK version')
            parent=ROOT/'runs/grounded-policy'; target=parent/args.run_id
            if (ROOT/'runs').is_symlink() or parent.is_symlink() or not parent.resolve().is_relative_to(ROOT.resolve()):
                raise ValueError('Output path escapes project')
            if args.evaluate:
                if target.is_symlink() or not target.is_dir(): raise ValueError('Missing update phase')
                previous=read(target/'summary.json')
                if previous.get('status')!='policies_frozen' or previous.get('mode')!='update':
                    raise ValueError('Evaluation cannot repeat or follow incomplete updates')
                if any(previous.get(k)!=v for k,v in identity.items()) or read(target/'update-bundle.json')!=bundle:
                    raise ValueError('Code/model/config/evidence changed between phases')
                policies=load_phase(target,bundle,previous)
                exclusive_json(target/'evaluation-started.json',{'phase_freeze_sha256':previous['phase_freeze_sha256']})
                output=target; report=dict(previous,mode=mode,status='evaluating')
            else:
                target.mkdir(parents=True,exist_ok=False); output=target
                report.update(identity,updates=[dict(r,status='not_started') for r in update_order()],
                    sessions=[dict(r,status='not_started') for r in evaluation_order()])
                write_json(output/'config.json',config); write_json(output/'base-config.json',base)
                write_json(output/'update-bundle.json',bundle)
                write_json(output/'state-provenance.json',{k:v['provenance'] for k,v in states.items()})
            ledger=BudgetLedger(output/'budget-ledger.json',
                session_ids=[r['session_id'] for r in update_order()+evaluation_order()],**budgets)
            if budget_blocked(ledger.summary()): raise ValueError('Unsettled budget')
            if args.prepare_only:
                from rsi_eval.grounded_policy import GroundedPolicyController
                from rsi_eval.revision_policy import S0
                c=GroundedPolicyController(bundle,S0,output/'fixture',pair_id='offline')
                c.submit_policy(**fixture_submission(bundle))
                report['synthetic_policy_fixture']=c.policy
                prepare_actors(output,report,base_sessions,states,{r['session_id']:S0 for r in update_order()})
                report['status']='prepared'
            elif args.update:
                settings=dict(effective,api_key=read_key(auth_path(None)))
                updates(output,report,bundle,ledger,settings)
            else:
                def guard():
                    if load_phase(output,bundle,report)!=policies: raise ValueError('Frozen policies changed')
                prepared=prepare_actors(output,report,base_sessions,states,policies,guard)
                settings=dict(effective,api_key=read_key(auth_path(None)))
                evaluate(prepared,report,ledger,settings)
    except Exception as error:
        report.update(status='error',error_type=type(error).__name__)
    finally: logging.disable(old_disable)
    if ledger is not None: report['budget']=ledger.summary()
    if output is not None: write_json(output/'summary.json',report)
    print(json.dumps({k:report.get(k) for k in ('run_id','mode','status','error_type','budget')},indent=2))
    return 0 if report['status'] in ('prepared','policies_frozen','attempts_completed') else 1


if __name__=='__main__': raise SystemExit(main())
