"""Read-only replay of the stopped first request; never accepts or executes it."""
from pathlib import Path
from decimal import Decimal
import hashlib,json,sys
root=Path.cwd();sys.path.insert(0,str(root))
from rsi_eval.strategy_pair_preparation import canonical,verify,verify_prior_inputs,assert_runtime
from rsi_eval.strategy_pair_audit import audit_run
from rsi_eval.strategy_pair_transport import verify_dispatch_record
from rsi_eval.strategy_pair_controller import StrategyPairController,strict_json
from rsi_eval.revision_policy import validate_policy
from rsi_eval.strategy_pair_budget import StrategyPairBudgetLedger

run=root/'runs/strategy-pair/measured-v01';session=run/'experiment/sessions/r1-update-updated'
sha=lambda raw:hashlib.sha256(raw).hexdigest()
read=lambda path:json.loads(Path(path).read_bytes())
original={p.relative_to(run).as_posix():sha(p.read_bytes()) for p in sorted(run.rglob('*')) if p.is_file()}
checks={}
def check(name,condition):
    if not condition:raise AssertionError(name)
    checks[name]=True

check('exact_33_original_files',len(original)==33)
preparation=verify(root,run/'preparation')
check('frozen_254_runtime_files',preparation['runtime_files']==254)
old=verify_prior_inputs(root)
audit=audit_run(root,run/'experiment',ledger_path=run/'budget-ledger.json')
check('saved_audit_replays',audit==read(run/'audit.json'))
summary=read(run/'experiment/summary.json');result=read(run/'result.json')
check('stopped_first_slot',summary['status']=='stopped' and summary['slot_counts']==dict(completed=0,failed=1,not_started=35))
check('no_accepted_policy_or_measurement',summary['accepted_request_count']==0 and summary['measurement_record_count']==0
      and not summary['proposals'] and not summary['decisions'] and not summary['evaluation_pairs'])
check('no_production_gate',summary['production_evaluation_gate'] is None)
check('no_acceptance_or_candidate_files',not any((session/name).exists() for name in
      ('acceptance-attempt.json','sdk-submission.json','submission.json','policy.json','source.py')))
ledger=read(run/'budget-ledger.json');rows=ledger['requests']
check('exactly_one_settled_request',len(rows)==1 and rows[0]['status']=='settled' and rows[0]['usage_state']=='known')
row=rows[0];request=read(session/'requests/request-0001.request.json');response=read(session/'requests/request-0001.response.json')
check('request_ledger_binding',row['payload_sha256']==sha(canonical(request)) and row['input_bytes']==len(canonical(request))==90616)
check('usage_response_ledger_binding',row['usage']==response['usage'] and row['usage_sha256']==sha(canonical(response['usage'])))
slot_ids=[s['id'] for s in read(run/'preparation/future-allocation.json')['slots']]
check('summary_recomputed',StrategyPairBudgetLedger(run/'budget-ledger.json',slot_ids).summary()==result['budget'])
dispatch=verify_dispatch_record(session,read(run/'preparation/settings.json')['effective'])
check('dispatch_request_binding',dispatch['request_sha256']==sha((session/'requests/request-0001.request.json').read_bytes()))
tr=read(session/'transport-request.json');returned=read(session/'transport-result.json')
check('transport_returned',returned['status']=='returned' and returned['error_type'] is None
      and returned['request_receipt_sha256']==sha((session/'transport-request.json').read_bytes()))
check('response_finish_one_tool',len(response['choices'])==1 and response['choices'][0]['finish_reason']=='tool_calls'
      and len(response['choices'][0]['message']['tool_calls'])==1)
call=response['choices'][0]['message']['tool_calls'][0]
check('one_submit_policy_call',call['function']['name']=='submit_policy')
args=strict_json(call['function']['arguments'])
tool=next(t['function'] for t in request['tools'] if t['function']['name']=='submit_policy')
schema=tool['parameters'];extras=sorted(set(args)-{'rule_1','rule_2','rule_3','rule_4','explanation'})
check('only_advertised_sdk_fields_are_extra',extras==['security_risk','summary'] and set(args)<=set(schema['properties']))
check('sdk_fields_optional_in_schema',all(k not in schema['required'] for k in extras))
packet=read(run/'preparation/update-packet.json')
controller=StrategyPairController(root,packet,'r1-update-updated',root/'tmp/never-created-measured-controller')
try:controller.validate_arguments(call['function']['arguments'])
except ValueError as error: rejection=str(error)
else:raise AssertionError('Raw response unexpectedly accepted')
check('exact_frozen_contract_rejection',rejection=='Submission fields differ from contract')
# Diagnostic projection only. Do not call accept, save policy, or execute source.
projected={k:v for k,v in args.items() if k not in extras}
business=controller.validate_arguments(projected)
rules=[business[f'rule_{i}'] for i in range(1,5)]
check('business_fields_alone_valid',validate_policy(dict(version='revision-policy-v0.1',rule_ids=rules)) is not None)
check('originals_unchanged_after_replay',original=={p.relative_to(run).as_posix():sha(p.read_bytes()) for p in sorted(run.rglob('*')) if p.is_file()})
oldsim=root/'artifacts/strategy-pair/2026-10-21/v02'
m=read(oldsim/'manifest.json')
check('previous_3653_simulation_archive_files_unchanged',all(sha((oldsim/name).read_bytes())==digest for name,digest in m['files'].items()))
known=Decimal('2.9139117')+Decimal(str(result['budget']['known_estimated_cost_cny']))
reserve=Decimal('12.9983700')+Decimal(str(result['budget']['reserved_cost_cny']))
report=dict(version='strategy-measured-v01-verification-v0.1',status='passed',checks=checks,
    run_id='measured-v01',original_files=original,implementation_commit='15144dc0fad8aee0ceae77535563fb6fc1b22144',
    execution_commit=read(run/'preparation/runtime-freeze.json')['commit'],preparation=preparation,previous_inputs=old,audit=audit,
    stopped_cause=dict(layer='pre-SDK strict business validation',message=rejection,
        returned_rule_ids=rules,policy_accepted=False,extra_fields=extras,
        all_returned_keys_declared_by_sent_schema=True,optional_sdk_fields=True,
        explanation_bytes=len(args['explanation'].encode('utf-8')),
        original_response_sha256=sha((session/'requests/request-0001.response.json').read_bytes()),
        original_request_sha256=sha((session/'requests/request-0001.request.json').read_bytes())),
    transport=dict(elapsed_seconds=returned['elapsed_seconds'],returned=True,sdk_dispatch_attempts=1,
        boundary='SDK-to-LiteLLM observation and saved response; not provider-signed HTTP evidence.'),
    budget=result['budget'],research_activity=dict(model_requests=1,accepted_policies=0,candidate_executions=0,
        task_evaluations=0,symbolic_fits=0,sandbox_executions=0,val_calls=0,sealed_evaluations=0,strategy_updates=0,weight_updates=0),
    cumulative_research=dict(requests=127,known_tokens=952489,known_estimated_cost_cny=float(known),
        reserved_cost_cny=float(reserve),unknown_usage_requests=2,actual_total_cost_cny=None),
    continuation=dict(current_round='stopped_do_not_resume',current_runtime_recommended_for_new_real_run=False,
        historical_readiness='Preserved; previous mock replies omitted both optional SDK fields and did not certify this case.',
        next='Fix and fully validate a successor SDK envelope/business contract before any independent new run.'))
Path('tmp/strategy-measured-v01-verification.json').write_bytes(canonical(report)+b'\n')
print(json.dumps({k:v for k,v in report.items() if k not in ('original_files','budget','checks','preparation','previous_inputs')},ensure_ascii=False,indent=2))
