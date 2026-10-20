#!/usr/bin/env python3
"""Read-only record and source-binding audit; never runs candidate Python."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from scripts.run_two_stage import (CASE_ORDER,COUNTS,canonical,read,sha,write,validate_config,
    verify_files,actor_order)
from rsi_eval.two_stage_cases import load_cases
from rsi_eval.two_stage_core import (ProbeController,RevisionController,feedback_projection,
    common_request,summarize_scores,classify_edit,check_forecast,check_probe_forecast)
from scripts.run_intervention_probes import evaluator_counts
from rsi_eval.two_stage_audit import audit_request,audit_budget


def require(value,message):
    if not value:raise ValueError(message)


def packet_from_request(payload):
    messages=payload.get('messages',[])
    users=[m for m in messages if m.get('role')=='user']
    require(len(users)==1 and type(users[0].get('content')) is str,'Unique request packet')
    return json.loads(users[0]['content'])


def validate_candidate(case,candidate,directory):
    require(candidate is not None,'Missing candidate')
    source=(directory/'candidate.py').read_text(encoding='utf-8')
    digest=hashlib.sha256(source.encode()).hexdigest()
    require(candidate['source_sha256']==digest,'Candidate source digest')
    results=candidate['results']
    require(len(results)==len(candidate['evaluation_files']),'Evaluation cardinality')
    for index,(record,path) in enumerate(zip(results,candidate['evaluation_files'])):
        require(path==f'evaluations/evaluation-{index:02d}.json','Evaluation path')
        require(read(directory/path)==record,'Evaluation byte record')
        require(record.get('candidate_hash')==digest and record.get('family')==case['family']
                and record.get('parent_id')==case['source_sha256']
                and record.get('candidate_id')==candidate['candidate_id']
                and record.get('sealed_tasks_executed')==0 and record.get('model_calls')==0,'Evaluation binding')
    require(candidate['score']==summarize_scores(case,results,candidate['n_params']),'Recomputed score')
    require(candidate['edit']==classify_edit(case,source,candidate['n_params']),'Recomputed edit class')
    require(candidate['forecast']==check_forecast(case,candidate['auxiliary'].get('forecast'),candidate['score']),'Recomputed forecast')
    return source


def audit(root,run):
    root=Path(root).resolve();run=Path(run).resolve()
    config=validate_config(read(run/'config.json'));summary=read(run/'summary.json')
    require(summary['status']=='attempts_completed','Only completed allocated-slot audits supported')
    cases={c['id']:c for c in load_cases(root)}
    require(read(run/'cases.json')==cases,'Pinned historical states')
    freeze=read(run/'runtime-freeze.json');commit=freeze['runtime_commit']
    require(freeze['checkout_clean'] and summary['runtime_commit']==commit,'Clean runtime anchor')
    for path,digest in freeze['runtime_files_sha256'].items():
        blob=subprocess.check_output(['git','-C',str(root),'show',commit+':'+path])
        require(hashlib.sha256(blob).hexdigest()==digest,'Runtime Git file '+path)
        require(sha(root/path)==digest,'Auditor uses unchanged runtime '+path)
    registration=read(run/'registration-freeze.json');phase=read(run/'phase-freeze.json')
    require(sha(run/'registration-freeze.json')==summary['registration_freeze_sha256']
            ==phase['registration_freeze_sha256'],'Registration freeze anchor')
    require(sha(run/'phase-freeze.json')==summary['phase_freeze_sha256'],'Phase freeze anchor')
    verify_files(run/'stage1',registration['stage1_files'])
    require(phase['stage1_files']==registration['stage1_files'],'Stage one freeze continuity')
    verify_files(run/'probes',phase['probe_files'])
    require(registration['registrations']==phase['registrations'],'Shared registrations')
    require(summary['registrations']==registration['slots'],'Registered slot records')
    require([r['case_id'] for r in summary['registrations']]==CASE_ORDER,'Registration order')
    require([{k:r[k] for k in ('case_id','condition','session_id')} for r in summary['revisions']]==actor_order(),'Actor order')
    ledger=read(run/'budget-ledger.json');requests=ledger['requests']
    expected_config=dict(config['budgets'],session_ids=[c+'-probe' for c in CASE_ORDER]+[r['session_id'] for r in actor_order()])
    require(ledger['config']==expected_config and not ledger['halted'],'Budget configuration')
    audit_budget(ledger,summary['budget'],expected_config)
    require(len(requests)<=12 and all(r['usage_state']=='known' and r['status'] in ('settled','failed') for r in requests),'Known bounded requests')
    require(len({r['session_id'] for r in requests})==len(requests),'One request per session')
    files=list((run/'stage1').rglob('*.request.json'))+list((run/'stage2').rglob('*.request.json'))
    require(len(files)==len(requests),'Request file cardinality')
    by_id={r['request_id']:r for r in requests};by_session={r['session_id']:r for r in requests}
    for file in files:
        rid=file.name.removesuffix('.request.json');payload=read(file);row=by_id[rid]
        require(hashlib.sha256(canonical(payload)).hexdigest()==row['payload_sha256'],'Request payload digest')
        require(len(canonical(payload))==row['input_bytes'] and row['input_token_reservation']==row['input_bytes']+8192,'Input reservation')
        require(row['output_token_reservation']==4096,'Output reservation')
    results={};all_counts={k:0 for k in COUNTS};projection_proofs={};pair_requests={}
    for case_id in CASE_ORDER:
        case=cases[case_id];slot=next(r for r in summary['registrations'] if r['case_id']==case_id)
        directory=run/'stage1'/case_id
        req=by_session[slot['session_id']]
        require(slot['disposition'] in ('available','missing'),'Registration disposition')
        require(req['request_id']==slot['request_id'],'Registration request link')
        packet=read(directory/'task-packet.json')
        # Build view without calling constructor or writing files.
        controller=object.__new__(ProbeController);controller.case=case
        require(packet==controller.task_packet(),'Registration packet projection')
        require(packet_from_request(read(directory/'requests'/(req['request_id']+'.request.json')))==packet,'Actual registration packet')
        audit_request(directory,req,stage='probe',session_id=slot['session_id'],
                      registration=phase['registrations'].get(case_id))
        if slot['disposition']!='available':
            require(case_id not in phase['registrations'],'Missing registration cannot acquire result')
            require(not (directory/'registration.json').exists(),'Missing registration file')
            continue
        require(req['status']=='settled','Accepted registration needs successful transport')
        require(read(directory/'registration.json')==phase['registrations'][case_id],'Accepted registration frozen')
        full=read(run/'probes'/case_id/'probe.json')
        visible=feedback_projection(case,full)
        require(visible==phase['feedback'][case_id]==read(run/'probes'/case_id/'feedback.json'),'Probe projection')
        projection_proofs[case_id]=hashlib.sha256(canonical(visible)).hexdigest()
        rows=full['results'] if case['family']=='planning' else [full]
        for r in rows:
            for k in COUNTS:all_counts[k]+=r['executions'].get(k,0)
        results[case_id]={'family':case['family'],'probe':visible,'registration':phase['registrations'][case_id],
                         'probe_forecast':check_probe_forecast(case,phase['registrations'][case_id]['auxiliary'],visible),'arms':{}}
    for slot in summary['revisions']:
        case_id=slot['case_id'];case=cases[case_id];condition=slot['condition'];directory=run/'stage2'/slot['session_id']
        require(slot['disposition'] in ('available','missing','skipped_dependency'),'Revision disposition')
        if slot['disposition']=='skipped_dependency':
            require(case_id not in phase['registrations'] and slot['session_id'] not in by_session,'Dependency skip')
            continue
        req=by_session[slot['session_id']];require(req['request_id']==slot['request_id'],'Revision request link')
        packet=read(directory/'task-packet.json')
        c=object.__new__(RevisionController);c.case=case;c.registration=phase['registrations'][case_id]
        c.feedback=phase['feedback'][case_id] if condition=='checked' else None
        require(packet==c.task_packet(),'Revision packet projection')
        payload=read(directory/'requests'/(req['request_id']+'.request.json'))
        require(packet_from_request(payload)==packet,'Actual revision packet')
        pair_requests.setdefault(case_id,[]).append(canonical(common_request(payload)))
        candidate=slot.get('candidate')
        audit_request(directory,req,stage='revision',session_id=slot['session_id'],candidate=candidate)
        if candidate is not None:
            require(slot['disposition']=='available','Candidate disposition')
            require(read(directory/'candidate.json')==candidate,'Candidate summary consistency')
            validate_candidate(case,candidate,directory)
            for record in candidate['results']:
                for k,v in evaluator_counts(record).items():
                    if k in all_counts:all_counts[k]+=v
        else:
            require(slot['disposition']=='missing','Missing candidate disposition')
            require(not (directory/'candidate.json').exists(),'Missing candidate file')
        results[case_id]['arms'][condition]=None if candidate is None else {
            'source_sha256':candidate['source_sha256'],'score':candidate['score'],
            'edit':candidate['edit'],'forecast':candidate['forecast'],'rationale':candidate['rationale']}
    for case_id,payloads in pair_requests.items():
        require(len(payloads)==2 and payloads[0]==payloads[1],'Full shared request equality')
        require(hashlib.sha256(payloads[0]).hexdigest()==summary['common_request_sha256'][case_id],'Request pair proof')
    execution=read(run/'execution-ledger.json');events=execution['events']
    for event in events:
        require(type(event['reserved']) is int and event['reserved']>0,'Positive integer reservation')
        require(type(event['counts']) is dict and set(event['counts'])==set(COUNTS),'Count keys')
        require(all(type(v) is int and v>=0 for v in event['counts'].values()),'Nonnegative integer counts')
    require(execution['max_sandbox_calls']==64 and execution['reserved_sandbox_calls']<=64,'Execution cap')
    require(sum(e['reserved'] for e in events)==execution['reserved_sandbox_calls'],'Execution reservations')
    require(all(e['counts'] is not None and e['complete'] and e['counts']['sandbox_calls']<=e['reserved'] for e in events),'Complete execution accounting')
    event_counts={k:sum(e['counts'][k] for e in events) for k in COUNTS}
    require(event_counts==all_counts==summary['execution_budget']['actual'],'Recomputed execution totals')
    require(summary['execution_budget']['reserved_sandbox_calls']==execution['reserved_sandbox_calls']
            and summary['execution_budget']['accounting_complete'] is True,'Execution summary consistency')
    require(summary['sealed_tasks_executed']==0 and not summary['strategy_updated'] and not summary['model_weights_updated'],'Scope')
    tokens=sum(r['usage']['total_tokens'] for r in requests)
    estimate=sum((r['usage']['prompt_tokens']*2.1+r['usage']['completion_tokens']*8.4)/1e6 for r in requests)
    return {'status':'passed','runtime_commit':commit,'model_requests':len(requests),'known_tokens':tokens,
            'known_estimated_cost_cny':round(estimate,10),'reserved_cost_cny':sum(r['reserved_cost_cny'] for r in requests),
            'executions':all_counts,'matched_full_request_pairs':len(pair_requests),
            'feedback_projection_sha256':projection_proofs,'cases':results,
            'limitations':['record_and_source_consistency_only','no_candidate_or_VAL_rerun',
                          'no_independent_raw_prediction_metric_recomputation','researcher_seen_development_states']}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--run-dir',required=True);parser.add_argument('--output')
    args=parser.parse_args();result=audit(ROOT,Path(args.run_dir))
    if args.output:write(Path(args.output),result)
    print(json.dumps({k:v for k,v in result.items() if k!='cases'},indent=2))
if __name__=='__main__':main()
