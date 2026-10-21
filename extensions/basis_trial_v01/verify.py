"""Offline binding audit. No provider, candidate execution or fit."""
import copy
import json
import math
from pathlib import Path
from extensions.symbolic_basis_v01.executor import canonical,sha,validate_transition
from extensions.symbolic_basis_v01.contract import compile_submission
from extensions.symbolic_basis_v01.sdk_adapter import parse_tool_response,_decode_json
from rsi_eval.strategy_pair_transport import verify_dispatch_record
from rsi_eval.strategy_pair_controller import strict_json
from .sdk_controller import normalize_envelope,parse_policy_response,public_settings
from .run import ROOT,design,actor_packet,change_label,TrialLedger,guard_preparation,S0


def require(value,message):
    if not value:raise ValueError(message)


def read(path):return strict_json(Path(path).read_bytes())


def request_packet(request):
    messages=request.get('messages')
    require(type(messages) is list and len(messages)>=2,'Missing messages')
    require(messages[-1].get('role')=='user' and all(x.get('role') in ('system','developer') for x in messages[:-1]),'Extra conversational context')
    return strict_json(messages[-1]['content'])


def common_request(request):
    result=copy.deepcopy(request);packet=request_packet(result)
    require('repair_policy' in packet,'Missing policy field')
    packet.pop('repair_policy')
    result['messages'][-1]['content']=canonical(packet).decode()
    return result


def verify_measurement(folder,parent,child,mode,prepared=None):
    folder=Path(folder);payload=read(folder/'submission.json')
    require(payload==(child if child is not None else parent['payload']),'Executed wrong submission')
    compiled=compile_submission(payload,parent['spec'])
    require(read(folder/'compiled.json')==compiled and (folder/'source.py').read_bytes()==compiled['source'].encode(),'Compiled source mismatch')
    transition=validate_transition(payload,parent['spec'],parent['payload'] if child else None,parent['spec'] if child else None,'swap_one' if child else 'initial')
    require(read(folder/'transition.json')==transition,'Transition mismatch')
    result=read(folder/'result.json');receipt=read(folder/'receipt.json');feedback=read(folder/'feedback.json')
    require(receipt==dict(result,feedback=feedback,feedback_sha256=sha((folder/'feedback.json').read_bytes())),'Receipt mismatch')
    reservation=read(folder/'reservation.json');fit=read(folder/'fit.json');prediction=read(folder/'predict.json')
    require(result['status']=='success' and result['n_params']==4 and result['transition']==transition,'Unsuccessful or wrong-K measurement')
    require(result['source_sha256']==compiled['source_sha256'] and result['structural_sha256']==compiled['structural_sha256'],'Result source mismatch')
    require(reservation['source_sha256']==compiled['source_sha256'] and reservation['structural_sha256']==compiled['structural_sha256'] and reservation['initial_params']==[1.0]*4 and reservation['attempt']==1,'Reservation mismatch')
    require(fit['status']=='completed' and fit['result']['status']=='success' and fit['result']['converged'] is True,'Fit not successful')
    require(result['params']==fit['result']['params'] and len(result['params'])==4 and all(type(x) in (int,float) and math.isfinite(x) for x in result['params']),'Coefficient mismatch')
    require(result['optimizer_diagnostics']==fit['result']['diagnostics'],'Optimizer diagnostics mismatch')
    require(prediction['status']=='completed' and prediction['result']['status']=='success','Prediction failed')
    require(result['fit_attempts']==1 and result['prediction_calls']==1 and result['sandbox_calls']==2,'Activity mismatch')
    require(read(folder/'prediction-request.json')['target_present'] is False,'Prediction targets exposed')
    for key,name in [('result_sha256','result.json'),('fit_sha256','fit.json'),('prediction_sha256','predict.json')]:
        require(feedback['bindings'][key]==sha((folder/name).read_bytes()),'Feedback raw binding mismatch')
    require(feedback['bindings']['source_sha256']==compiled['source_sha256'] and feedback['bindings']['structural_sha256']==compiled['structural_sha256'],'Feedback source mismatch')
    require(feedback['coefficients']==[dict(feature_id=f,value=v) for f,v in zip(compiled['feature_ids'],result['params'])],'Feedback coefficient order mismatch')
    require(feedback['nmse']==result['metrics']['nmse'] and feedback['transition']==transition,'Feedback metric or transition mismatch')
    require(feedback['provenance']==reservation['provenance'] and feedback['bindings']['provenance_sha256']==sha(canonical(feedback['provenance'])),'Provenance mismatch')
    require(feedback['fit']=={k:fit['result'][k] for k in ('converged','nfev','candidate_calls')},'Fit count mismatch')
    require((feedback['provenance'].get('data_kind')=='synthetic_sdk_preflight')==(mode=='simulate'),'Synthetic/observed mismatch')
    if mode=='run':
        require(feedback['provenance']['data_sha256']==design()['data_sha256'],'Real data identity mismatch')
    if prepared is not None:
        from rsi_eval.symbolic import score_predictions
        from rsi_eval.symbolic_diagnostics import summarize_residuals
        request=prepared['request'];pred=prediction['result']['predictions']
        require(prepared['provenance']==feedback['provenance'],'Score replay provenance mismatch')
        require(sha(canonical(request))==feedback['bindings']['prepared_request_sha256'],'Prepared request mismatch')
        require(reservation['request_sha256']==sha(canonical(dict(request,phase='fit',n_params=4))),'Fit request mismatch')
        predict_request={k:v for k,v in request.items() if k!='y'};predict_request.update(phase='predict',params=result['params'])
        require(read(folder/'prediction-request.json')['request_sha256']==sha(canonical(predict_request)),'Prediction request mismatch')
        require(result['score']==score_predictions(request['y'],pred),'Score replay mismatch')
        require(result['metrics']==result['score']['metrics'],'Metrics mismatch')
        require(result['sse']==math.fsum((y-p)**2 for y,p in zip(request['y'],pred)),'SSE mismatch')
        require(feedback['residuals']==summarize_residuals(request['X'],request['y'],pred,request['input_names']),'Residual replay mismatch')
    return receipt


def verify_run(output,preparation,score_replay=False):
    output=Path(output);preparation=Path(preparation)
    frozen=guard_preparation(ROOT,preparation)
    invocation=read(output/'invocation.json');mode=invocation['mode']
    require(mode in ('simulate','run'),'Mode mismatch')
    freeze_hash=sha((preparation/'freeze.json').read_bytes())
    require(invocation['freeze_sha256']==freeze_hash,'External freeze mismatch')
    protocol=design();experiment=output/'experiment';summary=read(experiment/'summary.json')
    require(read(experiment/'design.json')==protocol,'Experiment protocol mismatch')
    ledger=read(output/'budget-ledger.json');budget=TrialLedger(output/'budget-ledger.json').summary()
    final=read(output/'result.json')
    require(final==dict(mode=mode,status=summary['status'],budget=budget,freeze_sha256=freeze_hash,research_calls=0 if mode=='simulate' else budget['request_count']),'Terminal ledger mismatch')
    requests=ledger['requests'];slots=protocol['slots']
    require([r['session_id'] for r in requests]==[s['id'] for s in slots[:len(requests)]],'Out-of-order request')
    require(len(requests)<=13 and budget['reserved_cost_cny']<=4 and not budget['recovery'],'Budget violation')
    freeze_path=experiment/'policy-freeze.json';policy=None
    if freeze_path.exists():
        freeze=read(freeze_path);policy=freeze['S1']
        require(freeze['S0']==S0 and freeze['no_change']==(policy==S0),'Policy freeze mismatch')
        require(freeze['update_packet_sha256']==sha(canonical(read(preparation/'update-packet.json'))),'Learning packet mismatch')
        require(summary['policy']==policy and summary['policy_no_change']==(policy==S0),'Summary policy differs from freeze')
    else:require(summary['policy'] is None and summary['policy_no_change'] is None,'Policy without freeze')
    measurement_dirs=sorted([p for p in experiment.iterdir() if p.is_dir() and p.name.startswith(('baseline-','candidate-'))])
    prepared=None
    if mode=='simulate':
        from .simulation import synthetic_task
        prepared=synthetic_task()
    elif score_replay and measurement_dirs:
        from .feedback import load_task
        prepared=load_task(ROOT)
    measurements=0;common={};accepted=0;max_bytes=0
    for name,result in summary['baselines'].items():
        require(policy is not None,'Baseline before policy')
        actual=verify_measurement(experiment/('baseline-'+name),protocol['parents'][name],None,mode,prepared)
        require(result==actual,'Baseline summary mismatch');measurements+=1
        context=read(experiment/f'context-{name}.json')
        require(context==dict(parent=protocol['parents'][name],task=dict(id='oscillator1',role='learning',split='train',input_names=['x','v'],target='a'),feedback=actual['feedback'],catalog_spec=protocol['parents'][name]['spec'],operation='swap_one'),'Common context mismatch')
    measured_rows={row['slot']['id']:row for row in summary['rows'][1:]}
    for i,(row,slot) in enumerate(zip(requests,slots)):
        directory=output/'sessions'/slot['id'];session=read(directory/'session-summary.json')
        request=read(directory/'requests'/f"{row['request_id']}.request.json")
        require(row['request_id']==f'request-{i+1:04d}' and row['payload_sha256']==sha(canonical(request)) and row['input_bytes']==len(canonical(request)),'Request budget binding mismatch')
        require(row['input_token_reservation']==row['input_bytes']+8192 and row['output_token_reservation']==8192,'Reservation size mismatch')
        max_bytes=max(max_bytes,row['input_bytes'])
        verify_dispatch_record(directory,public_settings())
        packet=request_packet(request)
        expected=read(preparation/'update-packet.json') if slot['stage']=='update' else actor_packet(read(experiment/f"context-{slot['parent']}.json"),S0 if slot['arm']=='S0' else policy)
        require(packet==expected and read(directory/'packet.json')==expected,'Model-visible context mismatch')
        if slot['stage']=='actor':
            context=common_request(request);name=slot['parent']
            if name in common:require(common[name]==context,'Non-policy difference between arms or repeats')
            else:common[name]=context
        response=read(directory/'requests'/f"{row['request_id']}.response.json")
        if session['status']!='accepted':
            require(summary['status']=='stopped' and i==len(requests)-1,'Failed request followed by continuation')
            continue
        require(row['status']=='settled' and row['usage_state']=='known' and row['usage']==response['usage'],'Accepted without known usage')
        business=parse_policy_response(response) if slot['stage']=='update' else parse_tool_response(normalize_envelope(response,'submit_basis'))
        require(session['business']==business,'Accepted business differs from raw response')
        submission=read(directory/'submission.json');sdk=read(directory/'sdk-submission.json');attempt=read(directory/'acceptance-attempt.json')
        require(submission['business']==business and sdk['business']==business and attempt['business_sha256']==sha(canonical(business)),'SDK business binding mismatch')
        require(sdk['response_id']==response['response_id'] and sdk['tool_call_id']==response['choices'][0]['message']['tool_calls'][0]['id'],'SDK response identity mismatch')
        for key,suffix in [('request','request'),('response','response')]:
            ref=session[key];path=directory/'requests'/f"{row['request_id']}.{suffix}.json"
            require(ref==sdk[key]==attempt[key] and ref['path']==path.relative_to(ROOT).as_posix() and ref['sha256']==sha(path.read_bytes()),'Raw SDK references mismatch')
        events=[json.loads(line) for line in (directory/'events.jsonl').read_text().splitlines()]
        actions=[e for e in events if e['type']=='ActionEvent']
        require(len(actions)==1 and actions[0]['tool_call_id']==sdk['tool_call_id'] and actions[0]['llm_response_id']==sdk['response_id'],'SDK action event mismatch')
        accepted+=1
        if slot['stage']=='update':
            require(freeze['proposal']==session and policy==session['policy'] and policy['rule_ids']==business['rule_ids'],'Policy submission freeze mismatch')
        elif slot['id'] in measured_rows:
            stored=measured_rows[slot['id']];parent=protocol['parents'][slot['parent']]
            actual=verify_measurement(experiment/('candidate-'+slot['id']),parent,business,mode,prepared);measurements+=1
            base=summary['baselines'][slot['parent']]['metrics']['nmse'];nmse=actual['metrics']['nmse']
            require(stored==dict(slot=slot,status='accepted',nmse=nmse,parent_nmse=base,delta_nmse=base-nmse,
                outcome=change_label(base,nmse),transition=actual['transition'],structural_sha256=actual['structural_sha256'],submission=business,result=actual),'Candidate row mismatch')
            require(read(experiment/f"row-{slot['id']}.json")==stored,'Row file mismatch')
            require(read(directory/'compiled.json')==compile_submission(business,parent['spec']),'SDK compiled identity mismatch')
    events=[read(p) for p in sorted((experiment/'events').glob('*.json'))]
    require([e['index'] for e in events]==list(range(len(events))),'Event sequence mismatch')
    frozen_indices=[e['index'] for e in events if e['kind']=='policy_frozen']
    require(not measurements or len(frozen_indices)==1 and all(e['index']>frozen_indices[0] for e in events if e['kind'] in ('baseline_complete','candidate_complete')),'Phase order mismatch')
    if summary['status']=='complete':
        require(len(requests)==accepted==13 and len(summary['rows'])==13 and measurements==14 and summary['failure'] is None,'Incomplete complete record')
    else:require(summary['status']=='stopped' and summary['failure'] is not None,'Invalid terminal status')
    fit_attempts=predictions=sandbox_calls=0
    allowed_dirs={'baseline-'+name for name in protocol['parents']}|{'candidate-'+slot['id'] for slot in slots[1:]}
    failed_measurements=[]
    for directory in measurement_dirs:
        require(directory.name in allowed_dirs,'Unexpected measurement directory')
        if (directory/'result.json').exists():
            item=read(directory/'result.json')
            fit_attempts+=item['fit_attempts'];predictions+=item['prediction_calls'];sandbox_calls+=item['sandbox_calls']
            if item['status']!='success':failed_measurements.append(directory.name)
        elif (directory/'aborted.json').exists():
            item=read(directory/'aborted.json');fit_attempts+=item['fit_attempts'];sandbox_calls+=item['sandbox_calls']
            predictions+=item['sandbox_calls']-item['fit_attempts'];failed_measurements.append(directory.name)
        else:
            require(summary['status']=='stopped','Partial measurement in complete run')
            failed_measurements.append(directory.name)
    require(fit_attempts<=14 and predictions<=14 and sandbox_calls<=28,'Task execution cap exceeded')
    if failed_measurements:
        require(summary['status']=='stopped' and len(failed_measurements)==1,'Measurement failure followed by continuation')
        failure=summary['failure']['slot'];expected=failure if failure.startswith('baseline-') else 'candidate-'+failure
        require(failed_measurements==[expected],'Failed measurement not bound to stop slot')
    elif summary['status']=='complete':require(len(measurement_dirs)==measurements,'Unaccounted measurements')
    return dict(status='passed' if summary['status']=='complete' else 'record_consistent_incomplete',mode=mode,
        requests=len(requests),accepted=accepted,measurements=measurements,shared_context_groups=len(common),max_input_bytes=max_bytes,
        freeze_sha256=freeze_hash,score_replays=measurements if prepared else 0,
        recorded_fit_attempts=fit_attempts,recorded_predict_calls=predictions,recorded_sandbox_calls=sandbox_calls,
        failed_measurement_directories=failed_measurements,counters_are_simulated=mode=='simulate',
        new_fits=0,new_model_requests=0,sealed_access=0)
