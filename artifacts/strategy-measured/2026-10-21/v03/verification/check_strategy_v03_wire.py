from pathlib import Path
import hashlib,json,sys
root=Path.cwd();run_id=sys.argv[1];assert run_id in ('sdk-preflight-v03','measured-v03')
sys.path.insert(0,str(root))
from rsi_eval.strategy_pair_preparation import canonical
# Read the explicit new SYSTEM assignments without importing optional SDK locally.
import ast
module=ast.parse((root/'rsi_eval/strategy_pair_agent.py').read_text())
systems={}
for node in module.body:
 if isinstance(node,ast.Assign):
  for target in node.targets:
   if isinstance(target,ast.Name) and target.id in ('UPDATE_SYSTEM','ACTOR_SYSTEM'):systems[target.id]=ast.literal_eval(node.value)
run=root/'runs/strategy-pair'/run_id;ledger=json.loads((run/'budget-ledger.json').read_bytes())
rows=[]
for row in ledger['requests']:
 slot=row['session_id'];path=run/'experiment/sessions'/slot/'requests'/(row['request_id']+'.request.json')
 raw=path.read_bytes();request=json.loads(raw);tool='submit_policy' if '-update-' in slot else 'submit_candidate'
 assert [t['function']['name'] for t in request['tools']]==[tool]
 assert request['tools'][0]['type']=='function' and request.get('tool_choice') is None
 system=[m['content'] for m in request['messages'] if m['role']=='system'];assert len(system)==1
 content=system[0]
 if isinstance(content,list):
  assert len(content)==1 and content[0]['type']=='text';content=content[0]['text']
 assert content==systems['UPDATE_SYSTEM' if tool=='submit_policy' else 'ACTOR_SYSTEM']
 assert len(canonical(request))==row['input_bytes'] and row['input_bytes']<=98304
 rows.append(dict(slot_id=slot,tool=tool,request_sha256=hashlib.sha256(raw).hexdigest(),system_exact=True,input_bytes=row['input_bytes']))
report=dict(status='passed',run_id=run_id,actual_requests_checked=len(rows),maximum_input_bytes=max((r['input_bytes'] for r in rows),default=0),system_and_single_tool_verified=True,requests=rows,research_activity=dict(model_requests=0,task_executions=0))
(root/('tmp/strategy-'+run_id+'-wire.json')).write_bytes(canonical(report)+b'\n')
print(json.dumps({k:v for k,v in report.items() if k!='requests'}))
