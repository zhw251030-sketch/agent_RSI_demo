from pathlib import Path
import hashlib,json,sys
root=Path.cwd();sys.path.insert(0,str(root))
from rsi_eval.strategy_pair_preparation import canonical
from rsi_eval.strategy_pair_audit import audit_run
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
reports={}
for run_id in ['sdk-preflight-v01','measured-v01','sdk-preflight-v02','measured-v02']:
 run=root/'runs/strategy-pair'/run_id
 before={p.relative_to(run).as_posix():sha(p) for p in run.rglob('*') if p.is_file()}
 actual=audit_run(root,run/'experiment',ledger_path=run/'budget-ledger.json',expected_agent_version='strategy-pair-agent-v0.1')
 stored=(run/'audit.json').read_bytes()
 assert actual==json.loads(stored),run_id
 assert canonical(actual)+b'\n'==stored,run_id
 after={p.relative_to(run).as_posix():sha(p) for p in run.rglob('*') if p.is_file()};assert before==after,run_id
 reports[run_id]=dict(audit=actual,audit_json_byte_equal=True,original_run_files_unchanged=len(before),audit_sha256=hashlib.sha256(stored).hexdigest())
report=dict(status='passed',expected_agent_version='strategy-pair-agent-v0.1',historical_replays=reports,research_activity=dict(model_requests=0,task_executions=0))
(root/'tmp/strategy-v03-historical-audits.json').write_bytes(canonical(report)+b'\n')
print(json.dumps({k:dict(status=v['audit']['status'],original_run_files_unchanged=v['original_run_files_unchanged']) for k,v in reports.items()}))
