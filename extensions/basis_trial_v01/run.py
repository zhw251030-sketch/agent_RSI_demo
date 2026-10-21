"""One bounded proposal plus twelve independent fixed-K revisions. No resume."""
import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
import subprocess
from unittest.mock import patch

from extensions.symbolic_basis_v01.contract import make_spec, compile_submission
from extensions.symbolic_basis_v01.executor import canonical, sha, write, validate_transition
from rsi_eval.revision_policy import S0, validate_policy, render_policy
from rsi_eval.pilot_budget import BudgetLedger, BudgetExceeded

ROOT=Path(__file__).resolve().parents[2]
VERSION='basis-trial-v0.1'


def design():
    spec=make_spec(2,4)
    parents={name:dict(spec=copy.deepcopy(spec),payload=dict(feature_ids=ids,explanation=reason)) for name,ids,reason in [
        ('A',['m_0_0','m_0_1','m_1_0','m_1_1'],'Researcher-fixed affine backbone plus interaction.'),
        ('B',['m_0_0','m_0_1','m_1_0','m_2_0'],'Researcher-fixed affine backbone plus first-input square.')]}
    slots=[dict(id='update',stage='update')]
    for repeat in range(1,4):
        for name in ['A','B']:
            order=['S0','S1'] if (repeat+(name=='B'))%2 else ['S1','S0']
            slots.extend(dict(id=f'{name}-r{repeat}-{arm}',stage='actor',parent=name,repeat=repeat,arm=arm) for arm in order)
    return dict(version=VERSION,task_id='oscillator1',role='learning',split='train',
        data_sha256='a846b36b931dee4e2335faf9fb4195a7a8d1b4e4430e915266ef45fcd2e07ee7',
        parents=parents,slots=slots,mode='swap_one',s0=copy.deepcopy(S0),threshold=1e-5,
        max_requests=13,max_fits=14,max_sandbox=28,max_reserved_cost_cny=4.0,
        rule='freeze policy before data access; stop on any failure; no recovery or redraw',
        scope='seen oscillator1 train development; no strategy promotion or independent generalization')


def actor_packet(common,policy):
    return dict(version=VERSION,task_text=(
        'Make one revision to the supplied polynomial structure for oscillator1: inputs x (position), v (velocity), output a (acceleration). '
        'Select exactly four distinct catalog IDs including constant. Retain the entire parent set OR replace exactly one nonconstant item. '
        'ID m_i_j means x**i * v**j; m_0_0 means 1. The complete catalog includes all monomials of total degree at most three. '
        'No additions, no two-item replacement. The host fits direct coefficients with fixed ones initialization and scores train NMSE. '
        'All variables map to the frozen input order. Lower NMSE is better; improvement threshold is absolute 1e-5. '
        'Use the parent feedback only as observations, not causal proof. You cannot run tools to try features. '
        'Explain the proposed edit but do not claim unmeasured success. Return one submit_basis call only.'),
        current_state=copy.deepcopy(common),repair_policy=render_policy(validate_policy(policy)))


def common_packet(packet):
    return {k:copy.deepcopy(v) for k,v in packet.items() if k!='repair_policy'}


def change_label(parent,child):
    if any(type(x) not in (int,float) or not math.isfinite(x) or x<0 for x in (parent,child)):
        raise ValueError('Invalid NMSE')
    diff=parent-child
    return 'improved' if diff>1e-5 else ('degraded' if diff< -1e-5 else 'unchanged')


def orchestrate(output,protocol,update_packet,session,measure):
    output=Path(output); output.mkdir(parents=True,exist_ok=False)
    write(output/'design.json',protocol)
    rows=[]; baselines={}; policy=None; active=None
    events=[]; protected={}
    def protect(path): protected[path]=sha(path.read_bytes())
    def check_protected():
        if any(not p.is_file() or sha(p.read_bytes())!=h for p,h in protected.items()):
            raise ValueError('Frozen policy or common context changed')
    def event(kind,**fields):
        record=dict(index=len(events),kind=kind,**fields)
        folder=output/'events';folder.mkdir(exist_ok=True)
        write(folder/f'{len(events):03d}.json',record);events.append(record)
    try:
        if protocol!=design(): raise ValueError('Protocol differs from frozen design')
        active=protocol['slots'][0];event('request_start',slot=active['id'])
        proposal=session(active,update_packet)
        if proposal['status']!='accepted': raise ValueError('Policy request not accepted')
        business=proposal['business']
        policy=validate_policy(dict(version=S0['version'],rule_ids=business['rule_ids']))
        write(output/'policy-freeze.json',dict(S0=S0,S1=policy,proposal=proposal,
            no_change=policy==S0,update_packet_sha256=sha(canonical(update_packet))))
        protect(output/'policy-freeze.json')
        rows.append(dict(slot=active,status='accepted'))
        event('policy_frozen',policy_sha256=sha(canonical(policy)),no_change=policy==S0)
        for name,parent in protocol['parents'].items():
            active=dict(id='baseline-'+name)
            check_protected()
            measured=measure(parent,None,output/('baseline-'+name))
            if measured['status']!='success': raise ValueError('Baseline measurement failed')
            baselines[name]=measured
            common=dict(parent=copy.deepcopy(parent),task=dict(id=protocol['task_id'],role=protocol['role'],split='train',input_names=['x','v'],target='a'),
                        feedback=measured['feedback'],catalog_spec=parent['spec'],operation='swap_one')
            write(output/f'context-{name}.json',common)
            protect(output/f'context-{name}.json')
            event('baseline_complete',parent=name,nmse=measured['metrics']['nmse'])
        for slot in protocol['slots'][1:]:
            active=slot
            check_protected()
            parent=protocol['parents'][slot['parent']]
            common=json.loads((output/f"context-{slot['parent']}.json").read_bytes())
            packet=actor_packet(common,S0 if slot['arm']=='S0' else policy)
            event('request_start',slot=slot['id'])
            accepted=session(slot,packet)
            check_protected()
            if accepted['status']!='accepted': raise ValueError('Actor request not accepted')
            child=accepted['business']
            transition=validate_transition(child,parent['spec'],parent['payload'],parent['spec'],'swap_one')
            measured=measure(parent,child,output/('candidate-'+slot['id']))
            if measured['status']!='success': raise ValueError('Candidate measurement failed')
            nmse=measured['metrics']['nmse']; base=baselines[slot['parent']]['metrics']['nmse']
            row=dict(slot=slot,status='accepted',nmse=nmse,parent_nmse=base,delta_nmse=base-nmse,
                outcome=change_label(base,nmse),transition=transition,
                structural_sha256=compile_submission(child,parent['spec'])['structural_sha256'],
                submission=child,result=measured)
            rows.append(row);write(output/f"row-{slot['id']}.json",row)
            event('candidate_complete',slot=slot['id'],outcome=row['outcome'])
        result=dict(status='complete',rows=rows,baselines=baselines,policy_no_change=policy==S0,policy=policy,failure=None)
    except Exception as error:
        # Exceptions can contain transport secrets; only the type and slot are public.
        event('stopped',slot=active['id'] if active else None,error_type=type(error).__name__)
        result=dict(status='stopped',rows=rows,baselines=baselines,policy_no_change=policy==S0 if policy else None,
                    policy=policy,failure=dict(slot=active['id'] if active else None,error_type=type(error).__name__))
    write(output/'summary.json',result)
    return result


class TrialLedger(BudgetLedger):
    def __init__(self,path):
        ids=[x['id'] for x in design()['slots']]
        super().__init__(path,max_requests=13,max_requests_per_session=1,max_output_tokens=8192,
            max_input_bytes=98304,max_reserved_tokens=1500000,max_cost_cny=4.0,session_ids=ids)

    def reserve(self,session_id,request_payload,output_tokens):
        with self._locked():
            rows=self._read()['requests']
            if len(rows)>=13 or session_id!=self.session_ids[len(rows)]: raise BudgetExceeded('Not next frozen slot')
            if any(r['status']!='settled' or r['usage_state']!='known' for r in rows): raise BudgetExceeded('Previous request not successful with known usage')
        return super().reserve(session_id,request_payload,output_tokens)

    def resume_after_transport_failure(self): raise BudgetExceeded('Trial does not allow recovery')


def runtime_files(root):
    paths=set()
    for base in ['rsi_eval','scripts','configs','prompts','extensions/basis_trial_v01','extensions/symbolic_basis_v01','analysis/symbolic-diagnostic-v01/runtime']:
        for p in (root/base).rglob('*'):
            if p.is_file() and p.suffix in ('.py','.json','.md') and '__pycache__' not in p.parts:
                paths.add(p.relative_to(root).as_posix())
    return {p:sha((root/p).read_bytes()) for p in sorted(paths)}


def guard_preparation(root,preparation):
    saved=json.loads((preparation/'freeze.json').read_bytes())
    if runtime_files(root)!=saved['runtime']: raise ValueError('Frozen runtime changed')
    for name,digest in saved['prepared'].items():
        if sha((preparation/name).read_bytes())!=digest: raise ValueError('Prepared content changed')
    if json.loads((preparation/'design.json').read_bytes())!=design(): raise ValueError('Frozen design changed')
    return saved


def prepare(root,output):
    from rsi_eval.strategy_learning import build_learning_package,render_update_packet
    root=Path(root);output=Path(output);output.mkdir(parents=True,exist_ok=False)
    package=build_learning_package(root)
    packet=render_update_packet(root,package)
    # Preserve all old material; replace only stale scheduling language in the prompt.
    packet['task_text']+='\nThis successor has one policy proposal only, no shadow proposals or automatic promotion. The proposal is measured in a later already-seen development comparison; explanation is required archive-only text.'
    for name,value in [('design.json',design()),('learning-package.json',package),('update-packet.json',packet)]:write(output/name,value)
    frozen=dict(version=VERSION,runtime=runtime_files(root),prepared={p.name:sha(p.read_bytes()) for p in output.iterdir() if p.is_file()})
    write(output/'freeze.json',frozen)
    return dict(status='prepared',freeze_sha256=sha((output/'freeze.json').read_bytes()),runtime_files=len(frozen['runtime']))


def execute(root,preparation,output,mode,certificate=None):
    from . import sdk_controller as sdk
    from . import feedback
    root=Path(root);preparation=Path(preparation);output=Path(output)
    guard_preparation(root,preparation)
    freeze_hash=sha((preparation/'freeze.json').read_bytes())
    if mode not in ('simulate','run'):raise ValueError('Unknown mode')
    if mode=='run':
        if subprocess.check_output(['git','status','--porcelain'],cwd=root):raise ValueError('Real run requires clean worktree')
        cert=json.loads(Path(certificate).read_bytes())
        if cert.get('status')!='passed' or cert.get('freeze_sha256')!=freeze_hash or cert.get('mode')!='simulate':raise ValueError('Matching complete preflight required')
        from .verify import verify_run
        verify_run(Path(certificate).parent,preparation)
    output.mkdir(parents=True,exist_ok=False)
    write(output/'invocation.json',dict(version=VERSION,mode=mode,freeze_sha256=freeze_hash,
        implementation_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip()))
    protocol=json.loads((preparation/'design.json').read_bytes());packet=json.loads((preparation/'update-packet.json').read_bytes())
    ledger=TrialLedger(output/'budget-ledger.json');settings=sdk.public_settings();settings['api_key']='offline-placeholder'
    if mode=='run':
        from scripts.configure_minimax import auth_path,read_key
        settings['api_key']=read_key(auth_path(None))
    def request_guard(payload):guard_preparation(root,preparation)
    def session(slot,packet):
        guard_preparation(root,preparation)
        return sdk.run_session(root,output/'sessions'/slot['id'],slot['id'],packet,ledger,settings,
            stage=slot['stage'],spec=protocol['parents'][slot['parent']]['spec'] if slot['stage']=='actor' else None,
            pre_request_guard=request_guard)
    loaded=None
    def measure(parent,child,directory):
        nonlocal loaded
        guard_preparation(root,preparation)
        if not (output/'experiment/policy-freeze.json').exists():raise ValueError('Policy must freeze before task reads')
        if loaded is None:
            from .simulation import synthetic_task
            loaded=feedback.load_task(root) if mode=='run' else synthetic_task()
        from .simulation import synthetic_runner
        return feedback.evaluate(root,directory,child or parent['payload'],parent['spec'],parent=parent if child else None,
            prepared=loaded,runner=None if mode=='run' else synthetic_runner)
    from contextlib import nullcontext
    responses=[dict(tool='submit_policy',arguments=dict(rule_ids=['R01','R04','R05','R08'],explanation='Synthetic proposal; no research claim.'))]
    responses.extend(dict(tool='submit_basis',arguments=protocol['parents'][s['parent']]['payload']) for s in protocol['slots'][1:])
    responses[1]['arguments']=protocol['parents']['B']['payload']
    responses[3]['arguments']=protocol['parents']['A']['payload']
    provider=sdk.FakeProvider(responses) if mode=='simulate' else None
    context=patch('openhands.sdk.llm.llm.litellm_completion',provider) if mode=='simulate' else nullcontext()
    with context: result=orchestrate(output/'experiment',protocol,packet,session,measure)
    write(output/'result.json',dict(mode=mode,status=result['status'],budget=ledger.summary(),freeze_sha256=freeze_hash,
        research_calls=0 if mode=='simulate' else ledger.summary()['request_count']))
    from .verify import verify_run
    audit=verify_run(output,preparation,score_replay=mode=='run')
    write(output/'audit.json',audit)
    if mode=='simulate' and result['status']=='complete' and audit['status']=='passed':
        write(output/'readiness.json',dict(mode='simulate',status='passed',freeze_sha256=freeze_hash))
    return audit


def main():
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=['prepare','simulate','run','verify'])
    parser.add_argument('--output',required=True);parser.add_argument('--preparation');parser.add_argument('--certificate')
    a=parser.parse_args()
    if a.mode=='prepare':result=prepare(ROOT,ROOT/a.output)
    elif a.mode=='verify':
        from .verify import verify_run
        result=verify_run(ROOT/a.output,ROOT/a.preparation)
    else:result=execute(ROOT,ROOT/a.preparation,ROOT/a.output,a.mode,ROOT/a.certificate if a.certificate else None)
    print(json.dumps(result,ensure_ascii=False,allow_nan=False))

if __name__=='__main__':main()
