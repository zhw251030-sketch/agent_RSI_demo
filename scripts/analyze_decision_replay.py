#!/usr/bin/env python3
"""Read-only decision replay audit; no model calls or candidate execution."""
import argparse
import hashlib
from pathlib import Path
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from scripts.run_decision_replay import (CASE_ORDER, COUNTS, actor_order, canonical,
    read, write, sha, validate_config, verify_inputs, PROTOCOL, checked_execution_counts)
from scripts.analyze_two_stage import require, packet_from_request
from scripts.run_intervention_probes import evaluator_counts
from rsi_eval.two_stage_core import common_request, classify_edit, check_forecast
from rsi_eval.two_stage_audit import audit_request, audit_budget


def validate_candidate(case,candidate,directory):
    from rsi_eval.decision_core import summarize_scores, STRATEGY
    require(type(candidate) is dict and candidate.get('status')=='evaluated','Evaluated candidate required')
    raw=(directory/'candidate.py').read_bytes();source=raw.decode('utf-8')
    digest=hashlib.sha256(raw).hexdigest()
    require(candidate['source_sha256']==digest and candidate['source_file']=='candidate.py','Candidate source digest/path')
    require(candidate['parent_id']==case['source_sha256'],'Candidate parent binding')
    results=candidate['results']
    require(len(results)==len(candidate['evaluation_files'])==len(case['task_ids']),'Evaluation cardinality')
    require([r['task_id'] for r in results]==case['task_ids'],'Evaluation task scope')
    for index,(record,path) in enumerate(zip(results,candidate['evaluation_files'])):
        require(path==f'evaluations/evaluation-{index:02d}.json','Evaluation path')
        require(read(directory/path)==record,'Evaluation record differs')
        require(record.get('candidate_hash')==digest and record.get('family')==case['family']
            and record.get('parent_id')==case['source_sha256']
            and record.get('candidate_id')==candidate['candidate_id']
            and record.get('strategy_version')==STRATEGY
            and type(record.get('sealed_tasks_executed')) is int and record['sealed_tasks_executed']==0
            and type(record.get('model_calls')) is int and record['model_calls']==0,'Evaluation binding')
    require(canonical(candidate['score'])==canonical(summarize_scores(case,results,candidate['n_params'])),'Recomputed score')
    require(candidate['edit']==classify_edit(case,source,candidate['n_params']),'Recomputed edit class')
    require(candidate['forecast']==check_forecast(case,candidate['auxiliary'].get('forecast'),candidate['score']),'Recomputed forecast')
    return source


def validate_execution(execution,summary,counts,expected_events):
    require(type(execution.get('max_sandbox_calls')) is int and execution['max_sandbox_calls']==96,'Execution cap')
    reserved=execution.get('reserved_sandbox_calls')
    require(type(reserved) is int and 0<=reserved<=96,'Execution reservation total')
    events=execution['events']
    require([(e.get('label'),e.get('reserved')) for e in events]==[(e[0],e[1]) for e in expected_events],'Execution labels/reservations')
    require(all(canonical(event.get('counts'))==canonical(expected[2])
                for event,expected in zip(events,expected_events)),'Execution per-event counts')
    for event in events:
        require(type(event['reserved']) is int and event['reserved']>0,'Event reservation')
        require(event.get('complete') is True and type(event.get('counts')) is dict,'Incomplete execution')
        require(set(event['counts'])==set(COUNTS) and all(type(v) is int and v>=0 for v in event['counts'].values()),'Execution count types')
        require(event['counts']['sandbox_calls']<=event['reserved'],'Execution exceeds reservation')
    require(sum(e['reserved'] for e in events)==reserved,'Reservation sum')
    actual={k:sum(e['counts'][k] for e in events) for k in COUNTS}
    require(canonical(actual)==canonical(counts)==canonical(summary['actual']),'Recomputed execution counts')
    require(type(summary['reserved_sandbox_calls']) is int and summary['reserved_sandbox_calls']==reserved
            and summary['accounting_complete'] is True,'Execution summary')


def audit(root,run):
    from rsi_eval.decision_cases import load_cases
    from rsi_eval.decision_core import DecisionController
    root=Path(root).resolve();run=Path(run).resolve()
    config=validate_config(read(run/'config.json'));summary=read(run/'summary.json')
    require(summary.get('status')=='attempts_completed','Only complete allocated-slot audit supported')
    cases={c['id']:c for c in load_cases(root)}
    require(list(cases)==CASE_ORDER,'Case order')
    verify_inputs(run,summary['inputs_freeze_sha256'])
    require(canonical(read(run/'inputs/cases.json'))==canonical(cases),'Pinned historical cases/feedback')
    require(read(run/'inputs-freeze.json')['new_probe_executions']==0,'Replay only')
    freeze=read(run/'runtime-freeze.json');commit=freeze['runtime_commit']
    require(freeze.get('checkout_clean') is True and summary['runtime_commit']==commit,'Clean runtime anchor')
    require(freeze['runtime_files_sha256']==summary['runtime_files_sha256'],'Frozen runtime summary')
    require(PROTOCOL in freeze['runtime_files_sha256'],'New protocol frozen')
    for path,digest in freeze['runtime_files_sha256'].items():
        pure=Path(path)
        require(not pure.is_absolute() and '..' not in pure.parts,'Runtime path scope')
        blob=subprocess.check_output(['git','-C',str(root),'show',commit+':'+path])
        require(hashlib.sha256(blob).hexdigest()==digest,'Runtime Git file '+path)
        require(sha(root/path)==digest,'Audit uses unchanged runtime '+path)
    expected_order=actor_order()
    require([{k:r.get(k) for k in ('case_id','repeat','condition','session_id')} for r in summary['revisions']]==expected_order,'Fixed actor order')
    ledger=read(run/'budget-ledger.json');requests=ledger['requests']
    expected_config=dict(config['budgets'],session_ids=[r['session_id'] for r in expected_order])
    audit_budget(ledger,summary['budget'],expected_config)
    require(len(requests)==16 and len({r['session_id'] for r in requests})==16,'One request in each allocated slot')
    require([r['session_id'] for r in requests]==[r['session_id'] for r in expected_order],'Request order')
    require(len(list((run/'sessions').rglob('*.request.json')))==16,'Request file cardinality')
    require({p.name for p in (run/'sessions').iterdir()}=={r['session_id'] for r in expected_order},'Session directory scope')
    by_session={r['session_id']:r for r in requests}
    common={};results={c:{'family':cases[c]['family'],'probe':cases[c]['archive_feedback'],'repeats':{}} for c in cases}
    counts={k:0 for k in COUNTS};events=[];candidates=0
    for slot in summary['revisions']:
        case=cases[slot['case_id']];directory=run/'sessions'/slot['session_id']
        req=by_session[slot['session_id']]
        require(slot.get('request_id')==req['request_id'],'Request link')
        require(slot.get('disposition') in ('available','missing'),'Slot disposition')
        controller=object.__new__(DecisionController);controller.case=case
        controller.feedback=case['archive_feedback'] if slot['condition']=='checked' else None
        packet=controller.task_packet()
        payload=read(directory/'requests'/(req['request_id']+'.request.json'))
        require(canonical(read(directory/'task-packet.json'))==canonical(packet)
                ==canonical(packet_from_request(payload)),'Actual task packet projection')
        shared=canonical(common_request(payload));common.setdefault(case['id'],[]).append(shared)
        candidate=slot.get('candidate')
        audit_request(directory,req,stage='revision',session_id=slot['session_id'],candidate=candidate)
        if candidate is None:
            require(slot['disposition']=='missing' and not (directory/'candidate.json').exists(),'Missing candidate bookkeeping')
        else:
            candidates+=1
            require(slot['disposition']=='available' and canonical(read(directory/'candidate.json'))==canonical(candidate),'Candidate summary')
            validate_candidate(case,candidate,directory)
            for record in candidate['results']:
                record_counts=checked_execution_counts(record)
                for k,v in record_counts.items():
                    if k in counts:counts[k]+=v
                events.append((slot['session_id']+':'+record['task_id'],1 if case['family']=='planning' else 2,
                               {k:record_counts.get(k,0) for k in COUNTS}))
        results[case['id']]['repeats'].setdefault(str(slot['repeat']),{})[slot['condition']]=(
            None if candidate is None else {k:candidate[k] for k in
                ('source_sha256','score','edit','forecast','rationale','auxiliary')})
    for case_id,values in common.items():
        require(len(values)==4 and all(v==values[0] for v in values),'Four complete common requests match')
        require(hashlib.sha256(values[0]).hexdigest()==summary['common_request_sha256'][case_id],'Common request proof')
    validate_execution(read(run/'execution-ledger.json'),summary['execution_budget'],counts,events)
    for field in ('sealed_tasks_executed','new_probe_executions'):
        require(type(summary.get(field)) is int and summary[field]==0,'Zero-scope '+field)
    for field in ('strategy_updated','model_weights_updated','resumed'):
        require(summary.get(field) is False,'Fixed scope '+field)
    return {'status':'passed','runtime_commit':commit,'model_requests':16,'candidate_submissions':candidates,
        'missing_submissions':16-candidates,'known_tokens':sum(r['usage']['total_tokens'] for r in requests),
        'known_estimated_cost_cny':round(sum((r['usage']['prompt_tokens']*2.1+r['usage']['completion_tokens']*8.4)/1e6 for r in requests),10),
        'reserved_cost_cny':round(sum(r['reserved_cost_cny'] for r in requests),10),
        'executions':counts,'matched_request_pairs':8,'matched_four_request_groups':4,'cases':results,
        'limitations':['record_and_source_consistency_only','no_candidate_or_VAL_rerun',
            'no_independent_raw_prediction_metric_recomputation','researcher_seen_development_states',
            'two_generation_repeats_are_not_independent_tasks','historical_source_comments_visible_in_both_arms']}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--run-dir',required=True);parser.add_argument('--output')
    args=parser.parse_args();result=audit(ROOT,Path(args.run_dir))
    if args.output:write(Path(args.output),result)
    import json
    print(json.dumps({k:v for k,v in result.items() if k!='cases'},indent=2))


if __name__=='__main__':main()
