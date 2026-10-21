from pathlib import Path
import collections,hashlib,json,sys
root=Path.cwd();sys.path.insert(0,str(root));run_id=sys.argv[1]
assert run_id in ('sdk-preflight-v02','measured-v02')
from rsi_eval.strategy_pair_preparation import canonical,verify
from rsi_eval.strategy_pair_audit import audit_run
from scripts.run_strategy_pair import verify_certificate
run=root/'runs/strategy-pair'/run_id
read=lambda path:json.loads(path.read_bytes())
before={p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
        for p in run.rglob('*') if p.is_file()}
audit=audit_run(root,run/'experiment',ledger_path=run/'budget-ledger.json')
assert audit==read(run/'audit.json')
preparation=verify(root,run/'preparation')
certificate=verify_certificate(root,run/'readiness.json') if run_id.startswith('sdk-') else None
summary=read(run/'experiment/summary.json');ledger=read(run/'budget-ledger.json');result=read(run/'result.json')
metadata=collections.Counter();measured=[];requests=[]
for slot in summary['slots']:
    session=slot.get('session')
    if session and session.get('response'):
        response=read(root/session['response']['path'])
        calls=response.get('choices',[{}])[0].get('message',{}).get('tool_calls') or []
        for call in calls:
            try:args=json.loads(call['function']['arguments'])
            except (ValueError,TypeError):continue
            if isinstance(args,dict):
                fields='+'.join(sorted(set(args)&{'summary','security_risk'})) or 'omitted'
                metadata[fields]+=1
for event in summary['events']:
    if event['kind']=='measurement_recorded':measured.append(read(root/event['receipt']['path']))
for row in ledger['requests']:
    base=run/'experiment/sessions'/row['session_id']/'requests'
    request=read(base/(row['request_id']+'.request.json'))
    assert hashlib.sha256(canonical(request)).hexdigest()==row['payload_sha256']
    assert len(canonical(request))==row['input_bytes']<=98304
    response_path=base/(row['request_id']+'.response.json')
    if row['status']=='settled' and row['usage_state']=='known':
        assert read(response_path)['usage']==row['usage']
        assert hashlib.sha256(canonical(row['usage'])).hexdigest()==row['usage_sha256']
    requests.append(dict(slot_id=row['session_id'],request_id=row['request_id'],status=row['status'],
                         usage_state=row['usage_state'],input_bytes=row['input_bytes']))
assert before=={p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in run.rglob('*') if p.is_file()}
observed=summary['evidence_kind']=='observed'
report=dict(status='passed',run_id=run_id,preparation=preparation,certificate=certificate,audit=audit,
            original_run_files=len(before),original_run_files_unchanged=True,
            metadata_variants=dict(metadata),request_chain= requests,
            measurement_families=dict(collections.Counter(row['family'] for row in measured)),
            measurement_statuses=dict(collections.Counter(row['status'] for row in measured)),
            sandbox_executions=sum(len(row['executions']) for row in measured) if observed else 0,
            val_calls=sum('validator' in row for row in measured) if observed else 0,
            symbolic_fit_attempts=sum(any(e['phase']=='fit' for e in row['executions']) for row in measured) if observed else 0,
            sealed_task_executions=sum(row['sealed_tasks_executed'] for row in measured),
            proposals={k:read(root/v['path']) for k,v in summary['proposals'].items()},
            decisions={k:read(root/v['path'])['replay']['decision'] for k,v in summary['decisions'].items()},
            budget=result['budget'])
target=root/('tmp/strategy-'+run_id+'-replay.json');target.write_bytes(canonical(report)+b'\n')
print(json.dumps({k:v for k,v in report.items() if k not in ('request_chain','budget','proposals','decisions')},ensure_ascii=False,indent=2))
