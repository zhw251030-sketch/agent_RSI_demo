#!/usr/bin/env python3
"""Prepare, simulate, or run the frozen36 experiment with mandatory SDK audits."""
import argparse
import contextlib
import copy
import importlib.metadata
import io
import json
import logging
import os
from pathlib import Path
import re
import sys
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))
os.environ['OPENHANDS_SUPPRESS_BANNER']='1'
os.environ['LITELLM_LOCAL_MODEL_COST_MAP']='True'
os.environ['DO_NOT_TRACK']='1'

from rsi_eval import strategy_binding as binding
from rsi_eval.revision_policy import S0
from rsi_eval.strategy_learning import render_actor_packet
from rsi_eval import strategy_pair_preparation as prep
from rsi_eval.strategy_pair_budget import StrategyPairBudgetLedger
from rsi_eval.strategy_partition import safe_path


def template_context(root):
    """Only serializer setup, never a measured baseline or a model request."""
    states,_=binding._fixed_metadata(root,{})
    state=states['P-select-1'];candidate=state['candidate']
    source=safe_path(root,str(Path(binding.SOURCE_FREEZE).parent/'sessions/P-select-1/source.py').replace('\\','/')).read_bytes()
    if prep.sha(source)!=candidate['source_sha256']:
        raise ValueError('Template source differs')
    return dict(state_id='P-select-1',family='planning',source=source.decode(),
        source_sha256=candidate['source_sha256'],n_params=0,baseline_feedback=[],
        **binding.task_contract(root,'P-select-1'))


def _file_hashes(directory):
    result={}
    for path in sorted(directory.rglob('*')):
        if path.is_symlink():
            raise ValueError('Symlink in run')
        if path.is_file() and path.name not in ('run-manifest.json','readiness.json'):
            result[path.relative_to(directory).as_posix()]=prep.sha(path.read_bytes())
    return result


def dispatch_counts(output, mock_provider_calls=None):
    """Separate persisted SDK boundary attempts from reservations and mock calls."""
    attempts=sum(path.is_file() for path in
                 (Path(output)/'experiment/sessions').glob('*/sdk-dispatch.json'))
    return dict(sdk_dispatch_attempts=attempts,mock_provider_calls=mock_provider_calls)


def verify_certificate(root, path):
    """A certificate binds one complete same-runtime synthetic run, not science."""
    from rsi_eval.strategy_pair_audit import audit_run
    path=Path(path).resolve();root=Path(root).resolve()
    if not path.is_relative_to(root):
        raise ValueError('Preflight certificate must be inside project')
    safe_path(root,path.relative_to(root).as_posix())
    certificate=prep.read(path)
    if (certificate.get('version')!='strategy-pair-readiness-v0.1'
            or certificate.get('execution_ready') is not True
            or certificate.get('research_activity')!=dict(model_requests=0,task_evaluations=0,strategy_updates=0)):
        raise ValueError('Invalid preflight certificate')
    run=path.parent
    if prep.sha((run/'run-manifest.json').read_bytes())!=certificate['manifest_sha256']:
        raise ValueError('Preflight manifest changed')
    manifest=prep.read(run/'run-manifest.json')
    if manifest['files']!=_file_hashes(run):
        raise ValueError('Preflight evidence files changed')
    if prep.read(run/'preparation/runtime-freeze.json').get('checkout_clean') is not True:
        raise ValueError('Preflight requires a clean frozen implementation')
    check=prep.verify(root,run/'preparation')
    if check['runtime_sha256']!=certificate['runtime_sha256']:
        raise ValueError('Preflight runtime differs')
    result=prep.read(run/'result.json')
    summary=prep.read(run/'experiment/summary.json')
    audit=audit_run(root,run/'experiment',ledger_path=run/'budget-ledger.json')
    if (result['mode']!='simulate' or summary['evidence_kind']!='synthetic'
            or summary['status']!='complete' or summary['accepted_request_count']!=36
            or summary['measurement_record_count']!=716 or audit['status']!='passed_complete'
            or audit!=prep.read(run/'audit.json')):
        raise ValueError('Preflight requires complete audited synthetic36')
    return certificate


def execute(root, run_id, *, mode, allow_dirty=False, certificate=None):
    root=Path(root).resolve()
    if mode not in ('prepare','simulate','run') or not re.fullmatch('[A-Za-z0-9][A-Za-z0-9_-]{0,63}',run_id):
        raise ValueError('Invalid run identifier or mode')
    if mode=='run' and not certificate:
        raise ValueError('A complete same-runtime preflight certificate is required')
    if mode=='run' and allow_dirty:
        raise ValueError('Real execution requires clean frozen implementation')
    if mode=='run':
        verify_certificate(root,certificate)
    output=safe_path(root,'runs/strategy-pair/'+run_id)
    output.mkdir(parents=True,exist_ok=False)
    verification=prep.prepare(root,output/'preparation',allow_dirty=allow_dirty)
    if mode=='prepare':
        prep.write(output/'result.json',dict(mode=mode,preparation=verification,status='prepared'))
        return dict(status='prepared',output=output.relative_to(root).as_posix(),preparation=verification)
    if importlib.metadata.version('openhands-sdk')!='1.55.1':
        raise RuntimeError('Requires OpenHands SDK1.55.1')
    from rsi_eval.strategy_pair_controller import StrategyPairController, write_once
    from rsi_eval.strategy_pair_agent import make_llm,prepare_request_template,run_session
    from rsi_eval.strategy_pair_run import run_strategy_pair
    from rsi_eval.strategy_pair_audit import verify_session,audit_run
    from rsi_eval.strategy_pair_transport import observed_strategy_transport
    from rsi_eval.role_executor import RoleExecutor
    from rsi_eval.strategy_pair_simulation import SyntheticExecutorFactory,SyntheticProvider

    allocation=prep.read(output/'preparation/future-allocation.json')
    slots=allocation['slots']
    ledger=StrategyPairBudgetLedger(output/'budget-ledger.json',[s['id'] for s in slots])
    frozen=prep.read(output/'preparation/runtime-freeze.json')['files']
    frozen_preparation_hash=verification['manifest_sha256']
    public_settings=prep.read(output/'preparation/settings.json')['effective']
    settings=dict(public_settings,api_key='offline-placeholder')
    # Real credentials are loaded only after all previous guards. They are never
    # written to public settings, templates, exceptions or run artifacts.
    if mode=='run':
        from scripts.configure_minimax import auth_path,read_key
        settings['api_key']=read_key(auth_path(None))
    templates={}
    packets={'update':prep.read(output/'preparation/update-packet.json'),
             'actor':render_actor_packet(root,template_context(root),S0)}
    for phase,slot in [('update',slots[0]),('actor',slots[4])]:
        directory=output/'templates'/phase;directory.mkdir(parents=True)
        controller=StrategyPairController(root,packets[phase],slot['id'],directory)
        llm=make_llm(settings,controller,ledger)
        templates[phase]=prepare_request_template(controller,llm,slot['id'],directory)
        write_once(output/(phase+'-template.json'),templates[phase])
    if ledger.summary()['request_count']!=0:
        raise RuntimeError('Template capture must not reserve or send a request')
    template_hashes={name:prep.sha((output/(name+'-template.json')).read_bytes()) for name in templates}
    verified_sessions={}

    def guard(action=None,**fields):
        prep.assert_runtime(root,frozen)
        if prep.sha((output/'preparation/manifest.json').read_bytes())!=frozen_preparation_hash:
            raise ValueError('Preparation manifest changed')
        for name,digest in template_hashes.items():
            if prep.sha((output/(name+'-template.json')).read_bytes())!=digest:
                raise ValueError('Request template changed')
        if action=='accepted_session':
            if verified_sessions.get(fields['slot_id'])!=binding.digest(fields['result']):
                raise ValueError('Session was not audited before task execution')

    def session_runner(slot,packet,directory):
        phase='update' if slot['phase']=='update' else 'actor'
        controller=StrategyPairController(root,packet,slot['id'],directory)
        llm=make_llm(settings,controller,ledger)
        def request_guard(payload):
            guard('dispatch')
            actual,normalized=binding._request_packet(payload)
            if actual!=packet or normalized!=templates[phase]:
                raise ValueError('Actual SDK request differs from frozen template/packet')
        with observed_strategy_transport(directory,public_settings):
            result=run_session(controller,llm,slot['id'],directory,pre_request_guard=request_guard)
        if result['status']=='accepted':
            verify_session(root,slot,packet,result,output/'budget-ledger.json')
            verified_sessions[slot['id']]=binding.digest(result)
        return result

    experiment=(output/'experiment').relative_to(root).as_posix()
    provider=SyntheticProvider(slots) if mode=='simulate' else None
    factory=SyntheticExecutorFactory(experiment) if mode=='simulate' else RoleExecutor
    with contextlib.ExitStack() as stack:
        if mode=='simulate':
            stack.enter_context(patch('openhands.sdk.llm.llm.litellm_completion',provider))
            stack.enter_context(patch('socket.socket.connect',side_effect=RuntimeError('Simulation network prohibited')))
            stack.enter_context(patch('socket.create_connection',side_effect=RuntimeError('Simulation network prohibited')))
        summary=run_strategy_pair(root,experiment,session_runner=session_runner,
            request_template=templates['actor'],budget=ledger.config,executor_factory=factory,
            evidence_kind='synthetic' if mode=='simulate' else 'observed',pre_action_guard=guard)
    audit=audit_run(root,output/'experiment',ledger_path=output/'budget-ledger.json')
    prep.write(output/'audit.json',audit)
    result=dict(version='strategy-pair-launch-v0.1',mode=mode,status=summary['status'],
        preparation=verification,budget=ledger.summary(),audit=audit,
        **dispatch_counts(output,provider.calls if provider else None),
        dispatch_boundary='SDK-to-LiteLLM attempt; not HTTP/provider-confirmed delivery.',
        research_activity=dict(model_requests=0,task_evaluations=0,strategy_updates=0) if mode=='simulate' else None,
        boundary='Synthetic usage/observations are fixtures, excluded from research usage and results.' if mode=='simulate'
                 else 'Observed host records; evaluate outcomes and uncertainty in a separate analysis.')
    prep.write(output/'result.json',result)
    ready=(mode=='simulate' and summary['status']=='complete' and summary['accepted_request_count']==36
           and summary['measurement_record_count']==716 and provider.calls==36 and audit['status']=='passed_complete'
           and prep.read(output/'preparation/runtime-freeze.json')['checkout_clean'] is True)
    if ready:
        manifest=dict(version='strategy-pair-run-manifest-v0.1',files=_file_hashes(output))
        manifest_hash=prep.write(output/'run-manifest.json',manifest)
        prep.write(output/'readiness.json',dict(version='strategy-pair-readiness-v0.1',execution_ready=True,
            runtime_sha256=verification['runtime_sha256'],manifest_sha256=manifest_hash,
            research_activity=dict(model_requests=0,task_evaluations=0,strategy_updates=0)))
    return dict(status=summary['status'],output=output.relative_to(root).as_posix(),mode=mode,
        accepted_requests=summary['accepted_request_count'],measurement_records=summary['measurement_record_count'],
        audit_status=audit['status'],execution_ready=ready,
        sdk_dispatch_attempts=result['sdk_dispatch_attempts'],mock_provider_calls=result['mock_provider_calls'],
        research_activity=result['research_activity'],failure=summary['failure'])


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-id',required=True)
    mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--prepare-only',action='store_true');mode.add_argument('--simulate',action='store_true');mode.add_argument('--run',action='store_true')
    parser.add_argument('--certificate',type=Path)
    parser.add_argument('--allow-dirty',action='store_true',help='Development-only preparation/simulation; never a real run.')
    args=parser.parse_args(argv)
    previous=logging.root.manager.disable;logging.disable(logging.CRITICAL)
    try:
        with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
            result=execute(ROOT,args.run_id,mode='prepare' if args.prepare_only else ('simulate' if args.simulate else 'run'),
                allow_dirty=args.allow_dirty,certificate=args.certificate)
    except Exception as error:
        result=dict(status='error',error_type=type(error).__name__)
        if re.fullmatch('[A-Za-z0-9][A-Za-z0-9_-]{0,63}',args.run_id):
            directory=ROOT/'runs/strategy-pair'/args.run_id
            if directory.is_dir() and not (directory/'launcher-error.json').exists():
                prep.write(directory/'launcher-error.json',result)
    finally:
        logging.disable(previous)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0 if result['status'] in ('complete','prepared') else 1


if __name__=='__main__':
    raise SystemExit(main())
