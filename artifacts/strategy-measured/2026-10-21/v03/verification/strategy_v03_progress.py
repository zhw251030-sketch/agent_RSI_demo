from pathlib import Path
import json,sys
root=Path.cwd();run=root/'runs/strategy-pair'/sys.argv[1]
read=lambda p:json.loads(p.read_bytes())
ledger=read(run/'budget-ledger.json') if (run/'budget-ledger.json').exists() else {'requests':[]}
events=[read(p) for p in sorted((run/'experiment/events').glob('*.json'))]
last=events[-1] if events else {}
out=dict(requests=len(ledger['requests']),settled=sum(r['status']=='settled' for r in ledger['requests']),failed=sum(r['status']=='failed' for r in ledger['requests']),last_event={k:v for k,v in last.items() if k in ('kind','slot_id','state_id','role','replicate')},measurements=sum(e['kind']=='measurement_recorded' for e in events),decisions_frozen=sum(e['kind']=='decision_frozen' for e in events),evaluation_gate=(run/'experiment/evaluation-gate.json').exists())
if (run/'result.json').exists():
 r=read(run/'result.json');out.update(status=r['status'],audit_status=r.get('audit',{}).get('status'),known_tokens=r['budget']['known_total_tokens'],known_estimated_cost_cny=r['budget']['known_estimated_cost_cny'],reserved_cost_cny=r['budget']['reserved_cost_cny'],usage_unknown_count=r['budget']['usage_unknown_count'])
print(json.dumps(out,ensure_ascii=False))
