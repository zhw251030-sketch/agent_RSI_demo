"""Read-only checks of actual SDK dispatch and persisted experiment records.

This verifies a trusted-client chain. It is not provider attestation, independent
execution proof, an authenticated timestamp, or evidence of scientific benefit.
No credentials, benchmark CSV/PDDL, candidate execution or provider calls occur.
"""
import hashlib
import math
from pathlib import Path

from . import strategy_binding as binding
from .strategy_pair_controller import StrategyPairController, strict_json
from .strategy_partition import safe_path

VERSION = 'strategy-pair-audit-v0.1'
BOUNDARY = 'Persisted trusted-client consistency only; not provider attestation or independent execution/time proof.'


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _read(root, ref):
    _require(binding.file_ref(root, ref['path']) == ref, 'Bound evidence bytes changed')
    return strict_json(safe_path(root, ref['path']).read_bytes())


def _named(root, relative):
    return _read(root, binding.file_ref(root, relative))


def _output_name(root, output):
    path=Path(output)
    if path.is_absolute():
        path=path.relative_to(Path(root).resolve())
    relative=path.as_posix()
    safe_path(root,relative)
    return relative


def _ledger(root, path):
    path = Path(path)
    if path.is_absolute():
        path = path.relative_to(Path(root).resolve())
    ledger = _named(root, path.as_posix())
    allocation = _read(root, dict(path=binding.FUTURE_ALLOCATION, sha256=binding.FUTURE_ALLOCATION_SHA256))
    ids = [s['id'] for s in allocation['slots']]
    expected = dict(max_requests=36,max_requests_per_session=1,max_output_tokens=8192,
        max_input_bytes=98304,max_reserved_tokens=4128768,max_cost_cny=12.0,
        input_cny_per_million=2.1,output_cny_per_million=8.4,session_ids=ids)
    _require(ledger.get('version') == 1 and ledger.get('config') == expected, 'Global budget configuration mismatch')
    rows = ledger.get('requests')
    _require(type(rows) is list and len(rows) <= 36 and
        [r.get('session_id') for r in rows] == ids[:len(rows)] and
        [r.get('request_id') for r in rows] == [f'request-{i:04d}' for i in range(1,len(rows)+1)],
        'Global request order or IDs changed')
    return ledger, allocation


def _transport(root, directory, request_ref, request_id):
    from .strategy_pair_preparation import model_settings
    from .strategy_pair_transport import verify_dispatch_record
    binding.file_ref(root,directory+'/sdk-dispatch.json')
    verify_dispatch_record(safe_path(root,directory),model_settings(root)['effective'])
    settings = _named(root, directory+'/transport-settings.json')
    _require(settings == dict(version='strategy-pair-agent-v0.1',timeout=180,num_retries=0,
        provider_max_retries=0,stream=False,max_output_tokens=8192), 'Transport settings changed')
    ref = binding.file_ref(root,directory+'/transport-request.json')
    sent = _read(root,ref)
    expected_keys = {'version','expected_timeout_seconds','timeout_seconds','max_retries','stream_present',
        'stream','num_retries_present','num_retries','request_file','request_sha256'}
    _require(set(sent) == expected_keys and sent['version'] == 'state-generation-transport-v0.1'
        and sent['expected_timeout_seconds'] == 180 and sent['timeout_seconds'] == 180
        and type(sent['max_retries']) is int and sent['max_retries'] == 0
        and type(sent['stream_present']) is bool and sent['stream'] is False
        and type(sent['num_retries_present']) is bool
        and ((sent['num_retries_present'] and type(sent['num_retries']) is int and sent['num_retries']==0)
             or (not sent['num_retries_present'] and sent['num_retries'] is None))
        and sent['request_file'] == 'requests/'+request_id+'.request.json'
        and sent['request_sha256'] == request_ref['sha256'], 'Actual SDK dispatch flags or request differ')
    result = _named(root,directory+'/transport-result.json')
    _require(set(result) == {'version','request_receipt_sha256','elapsed_seconds','status','error_type'}
        and result['version'] == sent['version'] and result['request_receipt_sha256'] == ref['sha256']
        and result['status'] == 'returned' and result['error_type'] is None
        and type(result['elapsed_seconds']) in (int,float) and math.isfinite(result['elapsed_seconds'])
        and result['elapsed_seconds'] >= 0, 'Transport did not return one bound response')


def verify_session(root, slot, packet, result, ledger_path):
    """Certify accepted client records before their source may be measured.

    The caller owns phase/runtime guards. Rechecking an earlier accepted slot
    remains possible after a later slot fails, but every earlier reservation
    must be known and settled. This never relabels synthetic provider responses.
    """
    root = Path(root).resolve()
    ledger, allocation = _ledger(root,ledger_path)
    _require(slot in allocation['slots'], 'Session slot differs from frozen allocation')
    ordinal = allocation['slots'].index(slot)
    request_id = f'request-{ordinal+1:04d}'
    _require(len(ledger['requests']) > ordinal, 'No budget reservation for session')
    prior = ledger['requests'][:ordinal+1]
    _require(all(r.get('status')=='settled' and r.get('usage_state')=='known' and r.get('error_type') is None for r in prior),
             'Acceptance requires known settled preceding requests')
    row = prior[-1]
    _require(type(result) is dict and result.get('version')=='strategy-pair-agent-v0.1'
        and result.get('status')=='accepted' and result.get('slot_id')==slot['id']
        and result.get('request_id')==request_id and result.get('error_type') is None,
        'Accepted SDK result identity mismatch')
    stage = 'update' if slot['phase']=='update' else 'actor'
    tool = 'submit_policy' if stage=='update' else 'submit_candidate'
    _require(result.get('stage')==stage, 'SDK stage mismatch')
    request = _read(root,result['request'])
    sent_packet,_ = binding._request_packet(request)
    payload = binding.canonical(request)
    _require(sent_packet==packet and row.get('payload_sha256')==hashlib.sha256(payload).hexdigest()
        and row.get('input_bytes')==len(payload) and len(payload)<=98304
        and row.get('input_token_reservation')==len(payload)+8192
        and row.get('output_token_reservation')==8192 and request.get('max_output_tokens')==8192,
        'Actual request differs from packet or reserved bytes')
    tools = request.get('tools')
    _require(type(tools) is list and len(tools)==2
        and {t.get('function',{}).get('name') for t in tools}=={tool,'finish'}, 'Unexpected SDK tool set')
    response = _read(root,result['response'])
    choices = response.get('choices')
    _require(type(choices) is list and len(choices)==1 and response.get('error_type') is None,
             'Accepted response must contain exactly one choice')
    calls = choices[0].get('message',{}).get('tool_calls')
    _require(type(calls) is list and len(calls)==1 and calls[0].get('function',{}).get('name')==tool,
             'Accepted response must call one business tool')
    response_id,call_id = response.get('response_id'),calls[0].get('id')
    _require(all(type(x) is str and x for x in (response_id,call_id)), 'Missing response or call identity')
    usage = response.get('usage')
    fields = ('prompt_tokens','completion_tokens','total_tokens')
    _require(type(usage) is dict and all(type(usage.get(k)) is int and 0<=usage[k]<=10**12 for k in fields)
        and usage['total_tokens']==usage['prompt_tokens']+usage['completion_tokens']
        and usage==row.get('usage') and usage['prompt_tokens']<=row['input_token_reservation']
        and usage['completion_tokens']<=8192, 'Raw response usage differs from settled budget')
    expected_usage_hash = hashlib.sha256(binding.canonical(usage)).hexdigest()
    _require(row.get('usage_sha256')==expected_usage_hash, 'Settled usage digest differs')
    sdk = _read(root,result['sdk_submission'])
    directory = str(Path(result['sdk_submission']['path']).parent).replace('\\','/')
    _require(result['request']['path']==directory+'/requests/'+request_id+'.request.json'
        and result['response']['path']==directory+'/requests/'+request_id+'.response.json'
        and result['submission']['path']==directory+'/submission.json'
        and result['input_audit']['path']==directory+'/requests/input-audit.json', 'Session files cross directories')
    controller = StrategyPairController(root,packet,slot['id'],safe_path(root,directory))
    business = controller.validate_arguments(calls[0]['function']['arguments'])
    expected_sdk = dict(version='strategy-sdk-submission-v0.1',stage=stage,slot_id=slot['id'],tool=tool,
        request_id=request_id,request=result['request'],response=result['response'],response_id=response_id,
        tool_call_id=call_id,business=business)
    _require(sdk==expected_sdk, 'SDK dispatched business differs from raw response')
    audit = _read(root,result['input_audit'])
    _require(audit==dict(version='strategy-pair-input-audit-v0.1',request_id=request_id,slot_id=slot['id'],
        actual_input_bytes=len(payload),max_input_bytes=98304,payload_sha256=binding.digest(request),
        request_reserved=True,transport_called=True,status='completed',error_type=None), 'SDK input audit differs')
    events_raw = safe_path(root,directory+'/events.jsonl').read_bytes().splitlines()
    events = [strict_json(line) for line in events_raw]
    actions = [e for e in events if e.get('type')=='ActionEvent']
    observations = [e for e in events if e.get('type')=='ObservationEvent']
    _require(len(actions)==1 and len(observations)==1 and actions[0].get('tool_name')==tool
        and actions[0].get('tool_call_id')==call_id and actions[0].get('llm_response_id')==response_id
        and observations[0].get('tool_name')==tool and observations[0].get('tool_call_id')==call_id
        and events.index(actions[0])<events.index(observations[0]), 'SDK action/observation chain differs')
    errors = [e.get('code') for e in events if e.get('type')=='ConversationErrorEvent']
    _require(all(code=='MaxIterationsReached' for code in errors) and result.get('sdk_error_codes')==errors,
             'Unexpected SDK error event')
    common = dict(slot_id=slot['id'],request_id=request_id,request_sha256=result['request']['sha256'],status='accepted')
    attempt = _named(root,directory+'/acceptance-attempt.json')
    _require(attempt==dict(version='strategy-pair-controller-v0.1',**common,sdk_submission=result['sdk_submission'],
        business_sha256=binding.digest(business)), 'Controller acceptance attempt differs')
    sub = _read(root,result['submission'])
    if stage=='update':
        policy = dict(version='revision-policy-v0.1',rule_ids=[business[f'rule_{i}'] for i in range(1,5)])
        _require(result.get('policy')==policy and result.get('source') is None
            and _named(root,directory+'/policy.json')==policy, 'Accepted policy differs from dispatched rules')
        expected_sub = dict(version='strategy-policy-submission-v0.1',**common,policy_sha256=binding.digest(policy))
    else:
        ref = result['source']
        _require(ref['path']==directory+'/source.py' and binding.file_ref(root,ref['path'])==ref
            and safe_path(root,ref['path']).read_bytes()==business['source'].encode('utf-8')
            and result.get('policy') is None, 'Accepted source differs from dispatched business')
        expected_sub = dict(version='strategy-submission-v0.1',**common,source_sha256=ref['sha256'],n_params=business['n_params'])
    _require(sub==expected_sub, 'Host submission receipt differs')
    explanation = _named(root,directory+'/explanation.json')
    _require(explanation.get('explanation')==business['explanation'], 'Archived explanation differs')
    status = result.get('controller',{})
    _require(status.get('status')=='accepted' and status.get('halted') is False
        and all(status.get(k)==0 for k in ('candidate_executions','task_evaluations','model_weight_updates'))
        and status.get('policy')==result.get('policy') and status.get('source')==result.get('source')
        and status.get('submission')==result['submission'], 'Controller summary differs from accepted receipt')
    _require(_named(root,directory+'/session-summary.json')==result, 'Stored session summary differs')
    _transport(root,directory,result['request'],request_id)
    return dict(version=VERSION,status='passed',slot_id=slot['id'],request_id=request_id,tool=tool,
        actual_input_bytes=len(payload),usage=usage,evidence_boundary=BOUNDARY)


def audit_protocol(root, output):
    """Replay phase, source, measurement and selection records without SDK claims."""
    from . import goal_alignment
    from .revision_policy import S0
    from .strategy_learning import build_learning_package, render_update_packet, render_actor_packet
    from .strategy_pair_run import project_evaluation
    root = Path(root).resolve()
    output = _output_name(root,output)
    report = _named(root,output+'/summary.json')
    allocation = _read(root,dict(path=binding.FUTURE_ALLOCATION,sha256=binding.FUTURE_ALLOCATION_SHA256))
    states, _ = binding._fixed_metadata(root,{})
    rows, slots = report.get('slots'), allocation['slots']
    kind = report.get('evidence_kind')
    _require(report.get('version')=='strategy-pair-run-v0.1' and kind in ('synthetic','observed')
        and report.get('status') in ('complete','stopped') and type(rows) is list
        and [r.get('slot') for r in rows]==slots, 'Run identity or slot allocation differs')
    statuses = [r.get('status') for r in rows]
    _require(all(s in ('completed','failed','not_started') for s in statuses)
        and statuses.count('failed')<=1
        and statuses==sorted(statuses,key={'completed':0,'failed':1,'not_started':2}.get)
        and report.get('slot_counts')=={s:statuses.count(s) for s in ('completed','failed','not_started')},
        'Run completion prefix differs')
    complete = report['status']=='complete'
    _require((complete and statuses==['completed']*36 and report.get('failure') is None)
        or (not complete and report.get('failure') is not None), 'Complete/stopped outcome differs')
    events = report.get('events')
    _require(type(events) is list and events and events[0].get('kind')=='learning_frozen', 'Learning freeze missing')
    actual_files = {p.name for p in safe_path(root,output+'/events').iterdir()}
    _require(actual_files=={f'{i:05d}.json' for i in range(1,len(events)+1)}, 'Event file set differs')
    previous, clock = None, -1
    starts, accepts, completed = [], {}, []
    baseline_events, measurement_refs = {}, []
    proposed, gated, selection_allocated, eval_contexts = False, False, False, False
    decision_events = {}
    allowed = {'learning_frozen','session_started','session_accepted','slot_completed','proposals_frozen',
        'baseline_started','measurement_recorded','baseline_frozen','selection_allocations_frozen',
        'decision_frozen','both_decisions_frozen','evaluation_contexts_frozen','run_stopped'}
    for number, event in enumerate(events,1):
        _require(_named(root,output+f'/events/{number:05d}.json')==event
            and event.get('ordinal')==number and event.get('previous_sha256')==previous
            and type(event.get('monotonic_ns')) is int and event['monotonic_ns']>=clock
            and event.get('kind') in allowed, 'Event ordering or persisted bytes differ')
        previous, clock = binding.digest(event), event['monotonic_ns']
        name = event['kind']
        if name=='session_started':
            index = len(starts)
            _require(index<36 and event.get('slot_id')==slots[index]['id']
                and event.get('phase')==slots[index]['phase'], 'Session order differs')
            if slots[index]['phase']=='selection':
                _require(proposed and selection_allocated, 'Selection precedes frozen proposals or allocation')
            if slots[index]['phase']=='evaluation':
                _require(gated and eval_contexts, 'Evaluation request precedes both S* or shared contexts')
            starts.append(event['slot_id'])
        elif name=='session_accepted':
            identifier=event.get('slot_id')
            _require(identifier in starts and identifier not in accepts, 'Acceptance has no unique request start')
            accepts[identifier]=event
        elif name=='slot_completed':
            identifier=event.get('slot_id')
            _require(identifier in accepts and identifier not in completed, 'Completed slot lacks acceptance')
            completed.append(identifier)
        elif name=='proposals_frozen':
            _require(not proposed and completed==[s['id'] for s in slots[:4]], 'Proposals frozen before all four updates')
            proposed=True
            value=_read(root,event['proposals'])
            _require(value==dict(proposals=report['proposals'],evidence_kind=kind), 'Proposal freeze differs')
        elif name=='baseline_started':
            state=event.get('state_id')
            _require(proposed and state in states, 'Baseline precedes proposals')
            _require(state not in binding.EVALUATION_STATES or gated, 'Evaluation baseline precedes both decisions')
        elif name=='baseline_frozen':
            state=event.get('state_id')
            _require(state not in baseline_events, 'Duplicate baseline context')
            baseline_events[state]=event
        elif name=='measurement_recorded':
            state=event.get('state_id')
            _require(proposed and state in states and (state not in binding.EVALUATION_STATES or gated),
                     'Task measurement precedes its frozen phase')
            value=_read(root,event['receipt'])
            _require(value.get('status')==event.get('status') and value.get('task_role')==event.get('role')
                and value.get('model_calls')==0 and value.get('sealed_tasks_executed')==0
                and (value.get('evidence_kind')=='synthetic')==(kind=='synthetic'), 'Measurement event differs from raw record')
            measurement_refs.append(event['receipt'])
        elif name=='selection_allocations_frozen':
            _require(set(baseline_events)==set(binding.SELECTION_STATES), 'Selection starts before common baselines')
            selection_allocated=True
        elif name=='decision_frozen':
            rep=event.get('replicate')
            _require(completed==[s['id'] for s in slots[:20]] and rep in ('r1','r2') and rep not in decision_events,
                     'S* precedes all selection finals')
            decision_events[rep]=event['decision']
        elif name=='both_decisions_frozen':
            _require(not gated and set(decision_events)=={'r1','r2'}
                and event.get('decisions')==decision_events, 'Both S* were not frozen')
            gated=True
        elif name=='evaluation_contexts_frozen':
            _require(gated and set(baseline_events)==set(states), 'Evaluation contexts precede shared baseline freeze')
            eval_contexts=True
        elif name=='run_stopped':
            _require(not complete and number==len(events) and event.get('failure')==report['failure'], 'Stop event differs')
    _require(completed==[s['id'] for s,r in zip(slots,rows) if r['status']=='completed']
        and len(accepts)==report.get('accepted_request_count')
        and len(measurement_refs)==report.get('measurement_record_count')
        and len({r['path'] for r in measurement_refs})==len(measurement_refs), 'Activity counts or record uniqueness differ')
    _require(complete or events[-1]['kind']=='run_stopped', 'Stopped run lacks terminal stop event')
    packet=_named(root,output+'/update-packet.json')
    _require(packet==render_update_packet(root,build_learning_package(root)), 'Learning packet changed')
    template=_named(root,output+'/actor-request-template.json')
    parent=binding.policy_snapshot(root,S0)
    selected, decisions = {}, {}
    _require(report.get('decisions')==decision_events, 'Decision event inventory differs')
    for rep,ref in decision_events.items():
        frozen=_read(root,ref)
        old=frozen['replay']
        replay=binding.bind_selection(root,old['manifest']['path'],old['manifest']['sha256'])
        _require(replay==old and replay['replicate_id']==rep and replay['evidence_kind']==kind, 'Selection replay changed')
        manifest=_read(root,old['manifest'])
        _require(manifest['candidate_policy']==report['proposals'][rep+'-update-updated']
            and replay['parent_policy']==parent, 'Selection does not use its own updated proposal')
        chosen=replay['candidate_policy'] if replay['decision']['decision']=='promote' else parent
        _require(frozen['selected_policy']==chosen, 'Frozen S* differs from acceptance rule')
        selected[rep],decisions[rep]=chosen,frozen
    if gated:
        binding._verify_decision_pair(decisions)
    gate=None
    if kind=='synthetic':
        _require(report.get('production_evaluation_gate') is None, 'Synthetic run created a production gate')
        if gated:
            _require(_read(root,report['synthetic_phase'])==dict(version='synthetic-phase-only-v0.1',
                evidence_kind='synthetic',decisions=decision_events,grants_task_data_access=False), 'Synthetic phase label changed')
    elif gated:
        gate=binding.EvaluationGate(**report['production_evaluation_gate'])
        binding.verify_evaluation_gate(root,gate)
    contexts={}
    consumed=set()
    for state,event in baseline_events.items():
        context=_read(root,event['context'])
        source_path=str(Path(binding.SOURCE_FREEZE).parent/'sessions'/state/'source.py').replace('\\','/')
        source=safe_path(root,source_path).read_text(encoding='utf-8')
        count=states[state]['candidate']['n_params']
        refs=event['measurements']
        if state in binding.SELECTION_STATES:
            feedback=binding.project_baseline(root,state,refs)
        else:
            role='learning' if states[state]['family']=='planning' else 'evaluation'
            feedback=project_evaluation(root,state,refs,source=source,n_params=count,policy_sha256='baseline',
                role=role,evidence_kind=kind,evaluation_gate=gate)
        expected=dict(state_id=state,family=states[state]['family'],source=source,
            source_sha256=hashlib.sha256(source.encode()).hexdigest(),n_params=count,
            baseline_feedback=feedback,**binding.task_contract(root,state))
        _require(context==expected, 'Frozen context differs from source, contract or raw baseline')
        contexts[state]=context
        consumed.update(r['path'] for r in refs)
    evaluation={}
    update_template=None
    for slot,row in zip(slots,rows):
        result=row.get('session')
        if result is None:
            continue
        _require(_named(root,output+'/session-results/'+slot['id']+'.json')==result, 'Session-result copy differs')
        if slot['id'] not in accepts:
            continue
        _require(result.get('status')=='accepted' and result.get('request_id')==accepts[slot['id']]['request_id']
            and result.get('request')==accepts[slot['id']]['request'], 'Accepted event differs from session')
        sent,normalized=binding._request_packet(_read(root,result['request']))
        if slot['phase']=='update':
            _require(sent==packet, 'Updated and shadow learning requests differ')
            if update_template is None: update_template=normalized
            _require(normalized==update_template, 'Update request settings differ')
            _require(_read(root,report['proposals'][slot['id']])==binding.policy_snapshot(root,result['policy']),
                     'Frozen proposal differs from accepted policy')
            continue
        state,rep,arm=slot['state_id'],slot['replicate'],slot['arm']
        policy=parent if arm=='fixed' else (_read(root,report['proposals'][rep+'-update-updated'])
            if slot['phase']=='selection' else selected[rep])
        _require(normalized==template and sent==render_actor_packet(root,contexts[state],policy['content']),
                 'Actor received changed common context, shadow output or wrong policy')
        if row['status']!='completed':
            continue
        bound=_named(root,output+'/bound-sessions/'+slot['id']+'.json')
        _require(all(bound[k]==result[k] for k in ('request_id','request','submission','source'))
            and bound['state_id']==state and bound['arm']==arm and bound['slot_id']==slot['id'], 'Bound final differs from accepted source')
        refs=bound['evaluations']
        _require(not consumed.intersection(r['path'] for r in refs), 'Measurement reused across baseline/finals')
        consumed.update(r['path'] for r in refs)
        if slot['phase']=='evaluation':
            sub=_read(root,result['submission'])
            source=safe_path(root,result['source']['path']).read_text(encoding='utf-8')
            count=sub['n_params']
            values=project_evaluation(root,state,refs,source=source,n_params=count,policy_sha256=policy['sha256'],
                role='evaluation',evidence_kind=kind,evaluation_gate=gate)
            evaluation[slot['id']]=dict(results=values,n_params=count,policy_sha256=policy['sha256'],source_sha256=result['source']['sha256'])
    pairs=[]
    if complete:
        _require(len(measurement_refs)==716 and consumed=={r['path'] for r in measurement_refs}
            and len(accepts)==36 and set(contexts)==set(states) and gated, 'Complete activity allocation differs')
        for rep in ('r1','r2'):
            for state in binding.EVALUATION_STATES:
                old=evaluation[f'{rep}-evaluation-{state}-fixed']
                new=evaluation[f'{rep}-evaluation-{state}-updated']
                if states[state]['family']=='planning':
                    assessment=goal_alignment.assess_planning(old['results'],new['results'],development_ids=states[state]['task_ids'],public_ids=[])
                elif all(x['results'][0]['status']=='success' for x in (old,new)):
                    assessment=goal_alignment.assess_symbolic(*[dict(nmse=x['results'][0]['metrics']['nmse'],n_params=x['n_params']) for x in (old,new)])
                else:
                    assessment=dict(decision='unknown',reason_codes=['symbolic_final_without_complete_numeric_score'])
                pairs.append(dict(replicate=rep,state_id=state,assessment=assessment,
                    attribution='no_policy_change' if old['policy_sha256']==new['policy_sha256'] else 'paired_policy_comparison',parent=old,candidate=new))
    _require(report.get('evaluation_pairs')==pairs, 'Final paired assessments or attribution differ')
    return dict(version=VERSION,status='passed_complete' if complete else 'record_consistent_incomplete',
        evidence_kind=kind,slots_completed=statuses.count('completed'),slots_failed=statuses.count('failed'),
        slots_not_started=statuses.count('not_started'),accepted_sessions=len(accepts),sdk_sessions_verified=0,
        decisions_replayed=len(decisions),measurement_records_verified=len(measurement_refs),
        synthetic_measurements=len(measurement_refs) if kind=='synthetic' else 0,
        observed_measurements=len(measurement_refs) if kind=='observed' else 0,
        evidence_boundary=BOUNDARY)


def audit_run(root, output, *, ledger_path=None):
    """Full replay plus real SDK evidence for every accepted session."""
    output=_output_name(root,output)
    report=audit_protocol(root,output)
    summary=_named(root,output+'/summary.json')
    path=ledger_path if ledger_path is not None else output+'/budget-ledger.json'
    ledger,_=_ledger(root,path)
    started=[e['slot_id'] for e in summary['events'] if e['kind']=='session_started']
    _require(len(ledger['requests'])<=len(started)
        and [r['session_id'] for r in ledger['requests']]==started[:len(ledger['requests'])],
        'Reserved request has no matching started slot')
    verified=[]
    for row in summary['slots']:
        result=row.get('session')
        if result is None or result.get('status')!='accepted':
            continue
        packet,_=binding._request_packet(_read(root,result['request']))
        verified.append(verify_session(root,row['slot'],packet,result,path))
    _require(len(verified)==report['accepted_sessions'], 'SDK accepted session count differs')
    if summary['status']=='complete':
        _require(len(ledger['requests'])==36 and ledger.get('halted') is False, 'Complete run budget differs')
    report.update(sdk_sessions_verified=len(verified),actual_reserved_requests=len(ledger['requests']),
        usage_unknown_count=sum(r.get('usage_state')!='known' for r in ledger['requests']),
        request_input_bytes=[r['actual_input_bytes'] for r in verified],
        attempt_audit_scope='Complete request/response/dispatch/acceptance chains are verified for accepted sessions. '
            'Unaccepted attempts are counted from the ordered ledger; their full failure payload chain is not certified here.')
    return report
