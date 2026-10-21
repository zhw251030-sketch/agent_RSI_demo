#!/usr/bin/env python3
"""Audit a genuine v02 source batch and its observed transport parameters.

The v01 auditor and archived records remain unchanged. Shared request, budget,
source and history checks operate on the original v02 files, never rewritten
records or a fabricated compatibility workspace. This does not call a model,
import an SDK, execute candidate source, or read task CSVs.
"""
import argparse
import math
from pathlib import Path
import re
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from scripts import analyze_state_generation as base
from scripts.run_state_generation_v02 import BATCH_CONFIG, PROTOCOL, batch_snapshot, model_configuration
from rsi_eval.state_generation import build_inputs, validate_config, SLOT_ORDER, PUBLIC_IDS

require=base.require
read=base.read
canonical=base.canonical
digest=base.digest


def audit_transport(directory, row, *, expected_timeout=180, allow_incomplete=False):
    """Check trusted SDK-to-provider receipts, including explicit missing evidence."""
    directory=Path(directory);rid=row.get('request_id')
    require(type(rid) is str and re.fullmatch(r'request-\d{4}',rid),'Transport request identifier')
    request_path=directory/'transport-request.json';result_path=directory/'transport-result.json'
    if not request_path.exists():
        require(allow_incomplete and not result_path.exists(),'Missing transport request receipt')
        return dict(observed=False,incomplete=True,status='unobserved',timeout_seconds=None,elapsed_seconds=None)
    request=read(base._path(directory,'transport-request.json'))
    fields={'version','expected_timeout_seconds','timeout_seconds','max_retries','stream_present','stream',
            'num_retries_present','num_retries','request_file','request_sha256'}
    require(set(request)==fields and request['version']=='state-generation-transport-v0.1','Transport request schema')
    require(type(expected_timeout) is int and type(request['expected_timeout_seconds']) is int
            and request['expected_timeout_seconds']==expected_timeout
            and type(request['timeout_seconds']) in (int,float) and math.isfinite(request['timeout_seconds'])
            and request['timeout_seconds']==expected_timeout,'Observed transport timeout differs')
    require(type(request['max_retries']) is int and request['max_retries']==0,'Transport retries enabled')
    require(type(request['stream_present']) is bool and request['stream'] is False,'Transport streaming/presence')
    require(type(request['num_retries_present']) is bool and
            ((request['num_retries_present'] and type(request['num_retries']) is int and request['num_retries']==0)
             or (not request['num_retries_present'] and request['num_retries'] is None)), 'Transport retry presence/value')
    expected_file=f'requests/{rid}.request.json'
    require(request['request_file']==expected_file
            and request['request_sha256']==digest(base._path(directory,expected_file).read_bytes()),
            'Transport actual request file differs')
    require(len(list((directory/'requests').glob('*.request.json')))==1,'Multiple requests in one transport context')
    if not result_path.exists():
        require(allow_incomplete,'Missing transport result receipt')
        return dict(observed=True,incomplete=True,status='result_missing',timeout_seconds=expected_timeout,elapsed_seconds=None)
    result=read(base._path(directory,'transport-result.json'))
    require(set(result)=={'version','request_receipt_sha256','elapsed_seconds','status','error_type'}
            and result['version']=='state-generation-transport-v0.1','Transport result schema')
    require(result['request_receipt_sha256']==digest(request_path.read_bytes()),'Transport receipt hash differs')
    elapsed=result['elapsed_seconds']
    require(type(elapsed) in (int,float) and math.isfinite(elapsed) and elapsed>=0,'Transport elapsed time')
    status=result['status'];error=result['error_type']
    require(status in ('returned','raised'),'Transport result status')
    if status=='returned': require(error is None,'Returned transport has an error')
    else:
        require(type(error) is str and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,127}',error)
                and row.get('error_type')==error and allow_incomplete,'Raised transport error binding')
    return dict(observed=True,incomplete=False,status=status,timeout_seconds=expected_timeout,elapsed_seconds=elapsed)


def _runtime(root, freeze, report):
    commit=freeze.get('runtime_commit')
    require(type(commit) is str and re.fullmatch('[0-9a-f]{40}',commit)
            and report.get('runtime_commit')==commit and freeze.get('checkout_clean') is True,'Clean runtime anchor')
    mapping=freeze.get('runtime_files_sha256')
    required={PROTOCOL,BATCH_CONFIG,'scripts/run_state_generation_v02.py','scripts/analyze_state_generation_v02.py',
              'rsi_eval/state_generation_transport.py','tests/test_state_generation_v02_audit.py',
              'scripts/analyze_state_generation.py','scripts/run_state_generation.py'}
    require(type(mapping) is dict and required<=set(mapping),'V02 runtime inventory incomplete')
    names=subprocess.check_output(['git','-C',str(root),'ls-tree','-r','-z','--name-only',commit,
        '--','rsi_eval','scripts','configs','prompts','fixtures','tests']).decode('utf-8').split('\0')
    expected={name for name in names if name and (name.split('/',1)[0] in ('rsi_eval','scripts','configs','prompts','fixtures')
        and Path(name).suffix in ('.py','.json','.md','.txt')
        or name.startswith('tests/test_state_generation') and name.endswith('.py'))}
    expected.update({base.PROTOCOL,PROTOCOL,'docs/protocols/2026-10-21-two-stage-v0.1.md'})
    require(set(mapping)==expected,'Complete v02 runtime inventory differs from Git')
    for name,expected_hash in mapping.items():
        raw=base._path(root,name).read_bytes()
        blob=subprocess.check_output(['git','-C',str(root),'show',commit+':'+name])
        require(digest(blob)==expected_hash==digest(raw),'Frozen runtime differs: '+name)
    return commit


def _batch(root, run, report):
    path=base._path(run,'batch-freeze.json');value=read(path)
    require(digest(path.read_bytes())==report.get('batch_freeze_sha256'),'Batch freeze hash differs')
    require(canonical(value)==canonical(batch_snapshot(root)),'Frozen batch configuration/environment differs')
    return value


def audit(root, run):
    root=Path(root).resolve();run=Path(run)
    require(not any(p.is_symlink() or (hasattr(p,'is_junction') and p.is_junction())
                    for p in (run,*run.parents)),'Symlinked run')
    run=run.resolve();report=read(base._path(run,'summary.json'))
    status=report.get('status')
    require(report.get('version')=='state-generation-run-v0.2'
            and status in ('prepared','attempts_completed','stopped'),'Unsupported v02 run status')
    incomplete=status=='stopped';prepared=status=='prepared'
    config=validate_config(read(base._path(run,'config.json')))
    commit=_runtime(root,read(base._path(run,'runtime-freeze.json')),report)
    batch=_batch(root,run,report)
    inputs=read(base._path(run,'input-freeze.json'))
    require(digest((run/'input-freeze.json').read_bytes())==report.get('inputs_freeze_sha256'),'Input freeze hash')
    examples=[dict(family='planning',task_id=task,**example) for task,example in
              zip(PUBLIC_IDS,inputs['slots'][0]['packet']['examples'])]
    require(canonical(inputs)==canonical(build_inputs(root,examples)) and inputs['config']==config,'Frozen source inputs')
    history=read(base._path(run,'history-index.json'))
    require(digest((run/'history-index.json').read_bytes())==report.get('history_index_sha256'),'History index hash')
    base._history(root,history,commit)
    model_digest,public,effective=model_configuration(root,config['budgets'])
    require(report.get('model_config_sha256')==model_digest and report.get('model_config')==public
            and report.get('effective_model_config')==effective,'Model configuration binding')
    require(read(base._path(run,'generation-settings.json'))==
            dict(model_config_sha256=model_digest,public=public,effective=effective),'Saved generation settings')
    rows=report.get('slots');slots=inputs['slots'];identity=('id','family','role','task_ids','input_dimension')
    require(type(rows) is list and all(type(row) is dict for row in rows)
            and [{k:r.get(k) for k in identity} for r in rows]==[{k:s[k] for k in identity} for s in slots],
            'Full frozen slot allocation')
    ledger=read(base._path(run,'budget-ledger.json'))
    budget=base.audit_budget_state(ledger,report.get('budget'),dict(config['budgets'],session_ids=SLOT_ORDER),
                                  allow_incomplete=incomplete)
    requests=ledger['requests'];by={r['session_id']:r for r in requests}
    require([r['session_id'] for r in requests]==SLOT_ORDER[:len(requests)],'Request order/prefix')
    for key in ('candidate_executions','task_evaluations','probe_executions','sealed_tasks_executed',
                'strategy_updates','model_weight_updates','symbolic_csv_reads'):
        require(type(report.get(key)) is int and report[key]==0,'Zero-scope '+key)
    require(report.get('resumed') is False,'No resume')
    if prepared:
        require(not requests and all(r.get('disposition')=='not_started' and r.get('candidate') is None
                                    and r.get('request_id') is None and r.get('session_summary') is None for r in rows),
                'Prepared run has attempts')
        require(not (run/'sessions').exists() or not any((run/'sessions').iterdir()),'Prepared run has sessions')
        return dict(status='prepared_checked',run_status=status,allocation_completed=False,runtime_commit=commit,
            batch_freeze_sha256=report['batch_freeze_sha256'],python_version=batch['python_version'],
            effective_timeout_seconds=effective['timeout'],observed_transport_calls=0,
            model_requests=0,accepted_sources=0,known_tokens=0,known_estimated_cost_cny=0)
    frozen=read(base._path(run,'source-freeze.json'))
    require(digest((run/'source-freeze.json').read_bytes())==report.get('source_freeze_sha256'),'Source phase hash')
    require(frozen==dict(version='source-freeze-v0.1',inputs_freeze_sha256=report['inputs_freeze_sha256'],
        history_index_sha256=report['history_index_sha256'],runtime_commit=commit,slots=rows,
        session_files=base._tree(base._path(run,'sessions',directory=True))),'Frozen source inventory/slot binding')
    proofs={};receipts=[];available=0;started=set();blocked=False
    for row,slot in zip(rows,slots):
        name=slot['id'];directory=run/'sessions'/name;request=by.get(name)
        if request is None:
            require(row.get('request_id') is None and row.get('candidate') is None,'Missing request has accepted artifact')
            require(incomplete,'Completed allocation has missing request')
            if directory.exists():
                require(not blocked and row.get('disposition')=='blocked','Unexpected unrequested session')
                require(not any((directory/file).exists() for file in
                        ('source.py','candidate.json','sdk-submission.json','transport-request.json','transport-result.json')),
                        'Unrequested session has source/dispatch')
                session=read(base._path(directory,'session-summary.json'))
                require(row.get('session_summary')==session and session.get('session_id')==name
                        and session.get('stage')=='generation' and session.get('status')=='error'
                        and session.get('model_error_type') is not None,'Unrequested slot lacks host-error evidence')
                started.add(name);blocked=True
            else:require(row.get('disposition')=='not_started' and row.get('session_summary') is None,'Unstarted slot status')
            continue
        require(not blocked and row.get('request_id')==request['request_id'],'Request after blocked slot or wrong ID')
        started.add(name)
        receipt=base.audit_request(directory,request,slot,artifact=row.get('candidate'),allow_incomplete=incomplete)
        payload=base._actual_contract(root,directory,request,slot,effective['model'],allow_incomplete=incomplete)
        transport=audit_transport(directory,request,expected_timeout=effective['timeout'],allow_incomplete=incomplete)
        require(row.get('session_summary')==read(base._path(directory,'session-summary.json')),'Session summary binding')
        session=row['session_summary']
        require(session.get('session_id')==name and session.get('stage')=='generation'
                and session.get('adapter_version')=='state-generation-agent-v0.1'
                and session.get('sdk_version')==batch['sdk_version'] and set(session.get('tools',[]))=={'submit_candidate','finish'},
                'Session adapter/tools binding')
        controller=session.get('controller')
        require(type(controller) is dict and controller.get('candidate')==row.get('candidate')
                and controller.get('slot_id')==name,'Session controller binding')
        for field in ('candidate_executions','task_scores','sealed_tasks_executed','strategy_updates','model_calls_owned'):
            require(type(controller.get(field)) is int and controller[field]==0,'Controller zero scope')
        disposition=row.get('disposition')
        if disposition=='blocked':require(incomplete,'Completed slot cannot be blocked');blocked=True
        else:require(disposition==('available' if row.get('candidate') is not None else 'missing')
                     and not receipt['incomplete'] and not transport['incomplete'],'Slot disposition contradicts evidence')
        dispatched=read(base._path(directory,'requests/input-audit-0001.json'))['network_dispatch_attempted']
        require(not transport['observed'] or dispatched,'Observed provider call without dispatch audit')
        available+=row.get('candidate') is not None
        receipts.append(dict(slot_id=name,network_dispatch_attempted=dispatched,transport=transport,**receipt))
        group='planning' if slot['family']=='planning' else 'symbolic-'+str(slot['input_dimension'])
        proofs.setdefault(group,[]).append(digest(canonical(payload)))
    require({p.name for p in (run/'sessions').iterdir()}==started,'Unexpected source session directory')
    require(len(list((run/'sessions').rglob('*.request.json')))==len(requests),'Raw request file cardinality')
    if not incomplete:require(len(requests)==8 and not blocked,'Complete allocation needs eight attempts')
    else:require(blocked or budget['usage_unknown_count'] or budget['reserved_count'],'Stopped run lacks stop evidence')
    require(all(len(set(values))==1 for values in proofs.values()),'Equal-information actual requests differ')
    from scripts.run_state_generation import analyze_frozen_sources
    analysis=read(base._path(run,'static-analysis.json'))
    require(digest((run/'static-analysis.json').read_bytes())==report.get('analysis_sha256')
            and canonical(analysis)==canonical(analyze_frozen_sources(run)),'Recomputed static analysis differs')
    require(report.get('source_counts')=={k:analysis[k] for k in
            ('source_slots','available_sources','distinct_source_count','distinct_ast_count')},'Static summary counts')
    return dict(status='record_consistent_incomplete' if incomplete else 'passed',run_status=status,
        allocation_completed=not incomplete,runtime_commit=commit,batch_freeze_sha256=report['batch_freeze_sha256'],
        python_version=batch['python_version'],effective_timeout_seconds=effective['timeout'],
        observed_transport_calls=sum(r['transport']['observed'] for r in receipts),
        model_requests=len(requests),accepted_sources=available,request_reservations=len(requests),
        transport_dispatch_attempts=sum(r['network_dispatch_attempted'] for r in receipts),
        missing_or_unattempted_sources=8-available,known_tokens=budget['known_total_tokens'],
        known_estimated_cost_cny=budget['known_estimated_cost_cny'],actual_estimated_cost_cny=budget['actual_estimated_cost_cny'],
        reserved_cost_cny=budget['reserved_cost_cny'],unknown_usage_requests=budget['usage_unknown_count'],
        history_source_files=len(history['files']),frozen_session_files=len(frozen['session_files']),
        source_freeze_sha256=report['source_freeze_sha256'],analysis_sha256=report['analysis_sha256'],
        common_request_sha256={k:v[0] for k,v in sorted(proofs.items())},receipts=receipts,static_analysis=analysis,
        candidate_executions=0,task_evaluations=0,probe_executions=0,sealed_tasks_executed=0,strategy_updates=0,
        limitations=['Trusted client records, not provider authenticity or independent timestamp attestation.',
            'Elapsed time is local client observation, not service compute time or a strict full-session time bound.',
            'Strict JSON plus SDK metadata removal only; no other SDK argument repair is replayed.',
            'No source execution, task performance, strategy improvement, or independent-state guarantee.',
            'Stopped evidence remains incomplete; missing or unknown usage is not counted as zero.'])


def main():
    import json
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir',required=True);parser.add_argument('--output',required=True)
    args=parser.parse_args();result=audit(ROOT,Path(args.run_dir));base.write_output(ROOT,args.output,result)
    print(json.dumps({k:v for k,v in result.items() if k not in ('receipts','static_analysis')},indent=2))


if __name__=='__main__':main()
