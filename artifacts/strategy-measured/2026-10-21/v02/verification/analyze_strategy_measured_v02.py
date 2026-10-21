from pathlib import Path
from collections import Counter
from decimal import Decimal
import ast,hashlib,json,sys
root=Path.cwd();sys.path.insert(0,str(root))
from rsi_eval import strategy_binding as binding
from rsi_eval.strategy_learning import common_actor_packet
from rsi_eval.strategy_pair_preparation import canonical,model_settings
from rsi_eval.strategy_pair_transport import verify_dispatch_record
read=lambda p:json.loads(p.read_bytes())
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
run=root/'runs/strategy-pair/measured-v02';summary=read(run/'experiment/summary.json')
export=read(root/'tmp/strategy-measured-v02-export.json')
assert all(sha(root/p)==h for p,h in export['files'].items())
ledger=read(run/'budget-ledger.json');budget=read(run/'result.json')['budget']
assert summary['slot_counts']==dict(completed=6,failed=1,not_started=29)
failed=run/'experiment/sessions/r1-selection-S-select-1-updated'
request_path=failed/'requests/request-0007.request.json';request=read(request_path)
response_path=failed/'requests/request-0007.response.json';response=read(response_path)
calls=response['choices'][0]['message']['tool_calls'];names=[c['function']['name'] for c in calls]
assert len(response['choices'])==1 and names==['submit_candidate','finish']
assert response['error_type']=='PilotResponseContractError'
assert {t['function']['name'] for t in request['tools']}==set(names)
assert all(not (failed/name).exists() for name in ('sdk-submission.json','submission.json','acceptance-attempt.json','source.py'))
row=ledger['requests'][-1]
assert row['status']=='failed' and row['usage_state']=='known' and row['usage']==response['usage']
assert row['usage_sha256']==hashlib.sha256(canonical(response['usage'])).hexdigest()
dispatch=verify_dispatch_record(failed,model_settings(root)['effective'])
transport=read(failed/'transport-result.json')
assert transport['status']=='returned' and transport['error_type'] is None
assert transport['request_receipt_sha256']==sha(failed/'transport-request.json')
assert dispatch['request_sha256']==sha(request_path)
baselines={}
for event in summary['events']:
    if event['kind']!='baseline_frozen':continue
    context=read(root/event['context']['path']);records=[read(root/r['path']) for r in event['measurements']]
    baselines[event['state_id']]=dict(task_role=records[0]['task_role'],n_params=context['n_params'],
        task_count=len(records),statuses=dict(Counter(r['status'] for r in records)),
        errors=dict(Counter(r.get('error_kind','none') for r in records)),
        metrics=[r['metrics'] for r in records if 'metrics' in r])
pairs={};packets=[];templates=[]
for arm in ('fixed','updated'):
    name='r1-selection-P-select-1-'+arm
    bound=read(run/('experiment/bound-sessions/'+name+'.json'))
    records=[read(root/ref['path']) for ref in bound['evaluations']]
    source=(root/bound['source']['path']).read_text(encoding='utf-8')
    try:ast.parse(source);syntax=dict(valid=True)
    except SyntaxError as e:syntax=dict(valid=False,line=e.lineno,message=e.msg)
    pairs[arm]=dict(task_count=len(records),successes=sum(r['status']=='success' for r in records),
                   statuses=dict(Counter(r['status'] for r in records)),
                   errors=dict(Counter(r.get('error_kind','none') for r in records)),
                   exceptions=dict(Counter(r.get('exception_type','none') for r in records)),
                   source=bound['source'],syntax=syntax)
    packet,template=binding._request_packet(read(root/bound['request']['path']))
    packets.append(common_actor_packet(packet));templates.append(template)
assert packets[0]==packets[1] and templates[0]==templates[1]
updates=summary['slots'][:4]
request_hashes=[slot['session']['request']['sha256'] for slot in updates]
assert len(set(request_hashes))==1
proposals={slot['slot']['id']:slot['session']['policy']['rule_ids'] for slot in updates}
assert not summary['decisions'] and summary['production_evaluation_gate'] is None
report=dict(status='passed',run_id='measured-v02',raw_files_unchanged=len(export['files']),
    failure=dict(slot_id=row['session_id'],layer='raw response total tool-call count',
        error_type='PilotResponseContractError',finish_reason=response['choices'][0]['finish_reason'],
        tool_names=names,tool_choice=request['tool_choice'],both_tools_advertised=True,
        transport_returned=True,elapsed_seconds=transport['elapsed_seconds'],usage_known=True,
        failed_usage=response['usage'],accepted=False,candidate_executed=False),
    baselines=baselines,planning_pair=pairs,actual_common_requests_equal=True,
    proposals=proposals,distinct_proposals=len({tuple(v) for v in proposals.values()}),
    update_requests_identical=True,selected_strategies=0,evaluation_states_executed=0,
    cumulative_research=dict(requests=127+budget['request_count'],known_tokens=952489+budget['known_total_tokens'],
        known_estimated_cost_cny=float(Decimal('2.9705907')+Decimal(str(budget['known_estimated_cost_cny']))),
        reserved_cost_cny=float(Decimal('13.2746796')+Decimal(str(budget['reserved_cost_cny']))),
        unknown_usage_requests=2,actual_total_cost_cny=None))
assert all(sha(root/p)==h for p,h in export['files'].items())
(root/'tmp/strategy-measured-v02-analysis.json').write_bytes(canonical(report)+b'\n')
print(json.dumps(report,ensure_ascii=False,indent=2))
