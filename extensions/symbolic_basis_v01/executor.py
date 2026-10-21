"""Trusted host adapter: validated structure -> isolated fit/predict -> host score.

No candidate is executed or imported in this process. Model-facing APIs must not
expose this module's task/spec/provenance/output arguments.
"""
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re

from rsi_eval.role_executor import RoleExecutor, HEADERS, LIMITS
from rsi_eval.symbolic import score_predictions
from .contract import compile_submission

BASE=Path(__file__).resolve().parent
ROOT=BASE.parents[1]
RUNTIME='analysis/symbolic-diagnostic-v01/runtime/rsi_eval'


def canonical(value):
    return json.dumps(value,sort_keys=True,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode('utf-8')


def sha(raw): return hashlib.sha256(raw).hexdigest()


def write(path,value):
    with path.open('xb') as stream: stream.write(canonical(value)+b'\n')


def validate_transition(payload,spec,parent_payload=None,parent_spec=None,mode='initial'):
    child=compile_submission(payload,spec)
    if mode=='initial':
        if parent_payload is not None or parent_spec is not None: raise ValueError('initial must not have a parent')
        return dict(mode=mode,observed_change='initial',added=child['feature_ids'],removed=[],parent_structural_sha256=None,child_structural_sha256=child['structural_sha256'])
    if mode not in ('swap_one','add_one') or parent_payload is None or parent_spec is None:
        raise ValueError('explicit trusted transition and parent required')
    parent=compile_submission(parent_payload,parent_spec)
    if spec['n_inputs']!=parent_spec['n_inputs']: raise ValueError('input dimension changed')
    old=set(parent['feature_ids']); new=set(child['feature_ids'])
    added=sorted(new-old); removed=sorted(old-new)
    if mode=='swap_one':
        if spec['k']!=parent_spec['k'] or len(added)!=len(removed) or len(added)>1:
            raise ValueError('fixed-K edit must retain or replace exactly one feature')
        observed='swap_one' if added else 'keep'
    else:
        if spec['k']!=parent_spec['k']+1 or removed or len(added)!=1:
            raise ValueError('add-one must preserve every parent feature')
        observed='add_one'
    return dict(mode=mode,observed_change=observed,added=added,removed=removed,
                parent_structural_sha256=parent['structural_sha256'],child_structural_sha256=child['structural_sha256'])


def check_runtime():
    lock=json.loads((BASE/'runtime-lock.json').read_bytes())
    for ref in lock['files']:
        path=ROOT/ref['path']
        if not path.resolve().is_relative_to(ROOT) or path.is_symlink() or sha(path.read_bytes())!=ref['sha256']:
            raise ValueError('trusted runtime integrity mismatch')
    return lock


def sandbox_call(source,request):
    check_runtime()
    spec=importlib.util.spec_from_file_location('basis_locked_sandbox',ROOT/RUNTIME/'sandbox.py')
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.run_candidate(source,request,deps_dir=ROOT/'.task-runtime/python',**LIMITS)


def validate_request(request,spec):
    if type(request) is not dict or request.get('family')!='symbolic': raise ValueError('symbolic request required')
    if set(request)-{'family','X','y','task_id','input_names'}: raise ValueError('unexpected host request fields')
    X=request.get('X'); y=request.get('y')
    if type(X) is not list or not X or type(y) is not list or len(X)!=len(y): raise ValueError('invalid data dimensions')
    if len(X)>20000: raise ValueError('too many rows')
    for row in X:
        if type(row) is not list or len(row)!=spec['n_inputs']: raise ValueError('input dimension mismatch')
        if any(type(x) not in (int,float) or not math.isfinite(x) for x in row): raise ValueError('nonfinite or nonnumeric X')
    if any(type(x) not in (int,float) or not math.isfinite(x) for x in y): raise ValueError('nonfinite or nonnumeric y')
    if 'input_names' in request:
        names=request['input_names']
        if type(names) is not list or len(names)!=spec['n_inputs'] or any(type(n) is not str or re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,63}',n) is None for n in names) or len(set(names))!=len(names): raise ValueError('invalid input names')
    if 'task_id' in request and (type(request['task_id']) is not str or re.fullmatch(r'[A-Za-z0-9_/-]{1,128}',request['task_id']) is None): raise ValueError('invalid task identity')
    canonical(request)


def evaluate_submission(payload,spec,*,request,provenance,output,parent_payload=None,parent_spec=None,mode='initial',runner=None):
    """Host-only prepared-array entry. One call per output path; no resume/retry."""
    compiled=compile_submission(payload,spec)
    transition=validate_transition(payload,spec,parent_payload,parent_spec,mode)
    validate_request(request,spec)
    if type(provenance) is not dict: raise ValueError('trusted provenance must be a dictionary')
    canonical(provenance)
    run=sandbox_call if runner is None else runner
    output=Path(output)
    output.mkdir(parents=True,exist_ok=False)
    write(output/'submission.json',payload)
    write(output/'compiled.json',compiled)
    write(output/'transition.json',transition)
    (output/'source.py').write_bytes(compiled['source'].encode('utf-8'))
    fit_request=dict(request,phase='fit',n_params=compiled['n_params'])
    write(output/'reservation.json',dict(provenance=provenance,source_sha256=compiled['source_sha256'],
          structural_sha256=compiled['structural_sha256'],request_sha256=sha(canonical(fit_request)),
          n_params=compiled['n_params'],rows=len(request['y']),initial_params=[1.0]*compiled['n_params'],attempt=1))
    result=dict(status='fit_failed',metrics=None,sse=None,params=None,n_params=compiled['n_params'],
                structural_sha256=compiled['structural_sha256'],source_sha256=compiled['source_sha256'],
                transition=transition,sandbox_calls=0,fit_attempts=0,prediction_calls=0,optimizer_diagnostics=None,
                model_calls=0,metric_scope=provenance.get('metric_scope','synthetic'))
    try:
        result['sandbox_calls']+=1; result['fit_attempts']+=1
        fit=run(compiled['source'],fit_request)
        write(output/'fit.json',fit)
        result['fit_transport_status']=fit.get('status')
        fitted=fit.get('result',{})
        result['optimizer_diagnostics']=fitted.get('diagnostics')
        params=fitted.get('params')
        success=(fit.get('status')=='completed' and fitted.get('status')=='success' and fitted.get('converged') is True
                 and type(params) is list and len(params)==compiled['n_params']
                 and all(type(v) in (int,float) and math.isfinite(v) for v in params)
                 and type(fitted.get('nfev')) is int and 1<=fitted['nfev']<=100
                 and type(fitted.get('candidate_calls')) is int and fitted['candidate_calls']>=1)
        if success:
            result['params']=params
            predict_request={k:v for k,v in request.items() if k!='y'}
            predict_request.update(phase='predict',params=params)
            write(output/'prediction-request.json',dict(request_sha256=sha(canonical(predict_request)),target_present=False))
            result['sandbox_calls']+=1; result['prediction_calls']+=1
            prediction=run(compiled['source'],predict_request)
            write(output/'predict.json',prediction)
            predicted=prediction.get('result',{})
            result['status']='prediction_failed'
            if prediction.get('status')=='completed' and predicted.get('status')=='success':
                scored=score_predictions(request['y'],predicted.get('predictions'))
                result['score']=scored
                if scored['status']=='success':
                    result.update(status='success',metrics=scored['metrics'],sse=math.fsum((y-p)**2 for y,p in zip(request['y'],predicted['predictions'])))
                else: result['status']='metric_unavailable'
        write(output/'result.json',result)
        return result
    except BaseException as exc:
        write(output/'aborted.json',dict(status='aborted_no_resume',type=type(exc).__name__,message=str(exc),
                                      sandbox_calls=result['sandbox_calls'],fit_attempts=result['fit_attempts']))
        raise


def evaluate_role(payload,spec,*,task_id,role,output,evaluation_gate=None,parent_payload=None,parent_spec=None,mode='initial'):
    """Future host integration; keeps original role permissions and data hashes."""
    compile_submission(payload,spec)
    validate_transition(payload,spec,parent_payload,parent_spec,mode)
    if type(task_id) is not str or task_id not in HEADERS or len(HEADERS[task_id])-1!=spec['n_inputs']:
        raise ValueError('task/input dimension mismatch')
    executor=RoleExecutor(ROOT,role=role,evaluation_gate=evaluation_gate)
    prepared=executor.prepare_task('symbolic',task_id)
    return evaluate_submission(payload,spec,request=prepared['request'],provenance=prepared['provenance'],
                               output=output,parent_payload=parent_payload,parent_spec=parent_spec,mode=mode)
