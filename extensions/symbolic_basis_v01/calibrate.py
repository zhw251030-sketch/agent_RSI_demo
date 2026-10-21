"""Frozen synthetic calibration only: no benchmark loader or model provider."""
import argparse
import itertools
import json
import math
from pathlib import Path
import subprocess
import sys

from .contract import make_spec, compile_submission
from .executor import BASE, ROOT, canonical, sha, write, check_runtime, sandbox_call, evaluate_submission, validate_transition

PROTOCOL='docs/experiments/2026-10-22-basis-contract-freeze.json'
RUN='runs/symbolic-basis/calibration-v01'


def fixture(identifier,n,features,truth,*,X=None,parent_features=None,mode='initial',expected='exact'):
    points=X if X is not None else [list(map(float,p)) for p in itertools.product((-2,-1,0,1,2),repeat=n)]
    return dict(id=identifier,spec=make_spec(n,len(features)),payload=dict(feature_ids=features,explanation='Researcher synthetic calibration'),
                request=dict(family='symbolic',X=points,y=[float(truth(*p)) for p in points],task_id='synthetic/'+identifier,input_names=[f'x{i}' for i in range(n)]),
                parent_spec=make_spec(n,len(parent_features)) if parent_features else None,
                parent_payload=dict(feature_ids=parent_features,explanation='Synthetic parent structure') if parent_features else None,
                mode=mode,expected=expected)


def fixtures():
    parent=['m_0_0','m_1_0','m_0_1']
    target=lambda a,b:1+2*a*a-3*b
    # Independent closed-form target; all 15 quadratic terms plus x0^3.
    full16=['m_0_0_0_0','m_1_0_0_0','m_0_1_0_0','m_0_0_1_0','m_0_0_0_1',
            'm_2_0_0_0','m_0_2_0_0','m_0_0_2_0','m_0_0_0_2',
            'm_1_1_0_0','m_1_0_1_0','m_1_0_0_1','m_0_1_1_0','m_0_1_0_1','m_0_0_1_1','m_3_0_0_0']
    target16=lambda *x:1+sum((i+1)*x[i]+(0.5+i)*x[i]**2 for i in range(4))+sum(0.1*(i+j+1)*x[i]*x[j] for i in range(4) for j in range(i+1,4))+0.25*x[0]**3
    return [
      fixture('affine-1d',1,['m_0','m_1'],lambda x:1+2*x),
      fixture('mixed-2d',2,['m_0_0','m_2_0','m_1_1','m_0_1'],lambda a,b:1+2*a*a-3*a*b+0.5*b),
      fixture('triple-3d',3,['m_0_0_0','m_1_1_1'],lambda a,b,c:2-0.75*a*b*c),
      fixture('mixed-4d',4,['m_0_0_0_0','m_0_0_1_0','m_1_0_0_1','m_0_2_0_0'],lambda a,b,c,d:-1+0.3*c+2*a*d-0.5*b*b),
      fixture('missing-square',2,parent,target,expected='underfit'),
      fixture('swap-one',2,['m_0_0','m_2_0','m_0_1'],target,parent_features=parent,mode='swap_one'),
      fixture('add-one',2,parent+['m_2_0'],target,parent_features=parent,mode='add_one'),
      fixture('constant-target',1,['m_0'],lambda x:4,expected='zero_variance'),
      fixture('collinear-inputs',2,parent,lambda a,b:1+3*a,X=[[float(x),float(2*x)] for x in range(-3,4)],expected='nonidentifiable_exact'),
      fixture('max-k-4d',4,full16,target16),
    ]


def environment():
    code=('import sys,json,inspect;sys.path.insert(0,sys.argv[1]);import numpy,scipy;'
          'from scipy.optimize import least_squares;print(json.dumps(dict(python=sys.version,'
          'numpy=numpy.__version__,scipy=scipy.__version__,solver_signature=str(inspect.signature(least_squares)))))')
    return json.loads(subprocess.check_output(['/usr/bin/python3','-I','-S','-B','-c',code,str(ROOT/'.task-runtime/python')]))


def check_files(files):
    for ref in files:
        path=ROOT/ref['path']
        if not path.resolve().is_relative_to(ROOT) or path.is_symlink() or sha(path.read_bytes())!=ref['sha256']: raise ValueError('frozen source changed: '+ref['path'])


def prepare():
    check_runtime()
    refs=[{'path':p.relative_to(ROOT).as_posix(),'sha256':sha(p.read_bytes())} for p in sorted(BASE.rglob('*'))
          if p.is_file() and p.suffix in ('.py','.json','.md') and '__pycache__' not in p.parts]
    protocol=dict(version='symbolic-basis-calibration-v01',run_directory=RUN,files=refs,fixtures=fixtures(),
                  environment=environment(),max_nfev=100,initialization='ones',input_transform='identity',
                  guard='nan_to_num(nan=0,posinf=1e6,neginf=-1e6)',
                  thresholds=dict(exact_max_abs_error=1e-6,exact_nmse=1e-12,underfit_nmse_min=0.01),
                  guard_cases=[dict(id='overflow-signs',params=[0.,1.],expected=[1e6,-1e6,0.]),
                               dict(id='zero-times-overflow',params=[0.,0.],expected=[0.,0.,0.])],
                  benchmark_fits=0,model_requests=0,retries=0,resume=False,
                  git_head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip())
    write(ROOT/PROTOCOL,protocol)
    print(json.dumps(dict(status='frozen',sha256=sha((ROOT/PROTOCOL).read_bytes()),files=len(refs),fit_conditions=10,predict_guard_conditions=2)))


def assess(case,result,predictions,thresholds):
    kind=case['expected']
    if kind=='zero_variance':
        return result['status']=='metric_unavailable' and result.get('score',{}).get('error')=='zero_target_variance' and max(abs(v-4.) for v in predictions)<thresholds['exact_max_abs_error']
    if result['status']!='success': return False
    if kind=='underfit': return result['metrics']['nmse']>thresholds['underfit_nmse_min']
    return (result['metrics']['nmse']<thresholds['exact_nmse'] and
            max(abs(y-p) for y,p in zip(case['request']['y'],predictions))<thresholds['exact_max_abs_error'])


def run(expected_hash):
    raw=(ROOT/PROTOCOL).read_bytes()
    if sha(raw)!=expected_hash: raise ValueError('protocol hash mismatch')
    protocol=json.loads(raw)
    check_files(protocol['files']); check_runtime()
    if protocol['fixtures']!=fixtures() or protocol['environment']!=environment(): raise ValueError('fixture/environment mismatch')
    output=ROOT/RUN
    output.mkdir(parents=True,exist_ok=False)
    write(output/'protocol.json',protocol)
    rows=[]
    try:
        for case in protocol['fixtures']:
            position=output/case['id']
            result=evaluate_submission(case['payload'],case['spec'],request=case['request'],
                provenance=dict(kind='synthetic',metric_scope='synthetic',fixture_id=case['id']),output=position,
                parent_payload=case['parent_payload'],parent_spec=case['parent_spec'],mode=case['mode'])
            predictions=json.loads((position/'predict.json').read_bytes())['result']['predictions'] if (position/'predict.json').exists() else []
            passed=bool(predictions) and assess(case,result,predictions,protocol['thresholds'])
            row=dict(id=case['id'],expected=case['expected'],passed=passed,result=result)
            rows.append(row)
            print(json.dumps(dict(id=case['id'],passed=passed,status=result['status'],metrics=result['metrics'])),flush=True)
            if not passed: raise RuntimeError('synthetic calibration mismatch: '+case['id'])
        for case in protocol['guard_cases']:
            payload=dict(feature_ids=['m_0','m_3'],explanation='Synthetic finite input overflow guard')
            compiled=compile_submission(payload,make_spec(1,2))
            request=dict(family='symbolic',phase='predict',X=[[1e200],[-1e200],[0.]],params=case['params'])
            position=output/case['id']; position.mkdir()
            write(position/'compiled.json',compiled); write(position/'request.json',request)
            prediction=sandbox_call(compiled['source'],request)
            write(position/'predict.json',prediction)
            passed=prediction.get('status')=='completed' and prediction.get('result',{}).get('predictions')==case['expected']
            rows.append(dict(id=case['id'],passed=passed))
            if not passed: raise RuntimeError('guard mismatch')
        write(output/'summary.json',dict(status='passed',rows=rows,synthetic_fit_attempts=10,synthetic_fits_converged=10,
            synthetic_predict_calls=12,sandbox_calls=22,internal_synthetic_warmups=22,benchmark_fits=0,
            benchmark_data_reads=0,model_requests=0,policy_updates=0,sealed_accesses=0))
    except BaseException as exc:
        write(output/'aborted.json',dict(status='aborted_no_resume',error_type=type(exc).__name__,message=str(exc),rows=rows))
        raise
    finally:
        files=[dict(path=p.relative_to(output).as_posix(),sha256=sha(p.read_bytes())) for p in sorted(output.rglob('*')) if p.is_file()]
        write(output/'manifest.json',dict(files=files))


def verify(directory):
    """Replay scores from saved synthetic inputs and predictions; no execution."""
    from rsi_eval.symbolic import score_predictions
    directory=Path(directory)
    manifest=json.loads((directory/'manifest.json').read_bytes())
    actual={p.relative_to(directory).as_posix() for p in directory.rglob('*') if p.is_file()}
    if actual!={r['path'] for r in manifest['files']}|{'manifest.json'}: raise ValueError('file coverage')
    for ref in manifest['files']:
        path=directory/ref['path']
        if not path.resolve().is_relative_to(directory.resolve()) or path.is_symlink() or sha(path.read_bytes())!=ref['sha256']: raise ValueError('raw file integrity')
    protocol=json.loads((directory/'protocol.json').read_bytes())
    if (directory/'protocol.json').read_bytes()!=(ROOT/PROTOCOL).read_bytes(): raise ValueError('external protocol anchor')
    check_files(protocol['files']); check_runtime()
    if protocol['fixtures']!=fixtures(): raise ValueError('fixture definition mismatch')
    summary=json.loads((directory/'summary.json').read_bytes())
    if summary['status']!='passed' or len(summary['rows'])!=12: raise ValueError('incomplete calibration')
    for case,row in zip(protocol['fixtures'],summary['rows'][:10]):
        if row['id']!=case['id'] or row['expected']!=case['expected'] or row['passed'] is not True: raise ValueError('case mismatch')
        position=directory/case['id']
        read=lambda name:json.loads((position/name).read_bytes())
        compiled=compile_submission(case['payload'],case['spec'])
        if compiled!=read('compiled.json') or case['payload']!=read('submission.json') or (position/'source.py').read_bytes()!=compiled['source'].encode('utf-8'): raise ValueError('source/structure mismatch')
        result=read('result.json'); fit=read('fit.json'); predict=read('predict.json')
        if row['result']!=result or result['optimizer_diagnostics']!=fit['result'].get('diagnostics') or result['params']!=fit['result']['params']: raise ValueError('fit record mismatch')
        fitted=fit['result']; predicted=predict['result']
        params=fitted['params']
        if type(params) is not list or len(params)!=compiled['n_params'] or any(type(p) not in (int,float) or not math.isfinite(p) for p in params): raise ValueError('invalid fitted coefficients')
        if fit['status']!='completed' or fitted['status']!='success' or fitted['converged'] is not True or type(fitted['nfev']) is not int or not 1<=fitted['nfev']<=100 or type(fitted['candidate_calls']) is not int or fitted['candidate_calls']<1: raise ValueError('invalid fit success metadata')
        if predict['status']!='completed' or predicted['status']!='success': raise ValueError('invalid prediction status')
        if (result['source_sha256'],result['structural_sha256'],result['n_params'])!=(compiled['source_sha256'],compiled['structural_sha256'],compiled['n_params']): raise ValueError('result source binding')
        if (result['sandbox_calls'],result['fit_attempts'],result['prediction_calls'],result['model_calls'],result['metric_scope'],result['fit_transport_status'])!=(2,1,1,0,'synthetic','completed'): raise ValueError('per-case activity')
        transition=validate_transition(case['payload'],case['spec'],case['parent_payload'],case['parent_spec'],case['mode'])
        if result['transition']!=transition or read('transition.json')!=transition: raise ValueError('transition mismatch')
        reservation=read('reservation.json')
        request=dict(case['request'],phase='fit',n_params=compiled['n_params'])
        expected_reservation=dict(provenance=dict(kind='synthetic',metric_scope='synthetic',fixture_id=case['id']),source_sha256=compiled['source_sha256'],structural_sha256=compiled['structural_sha256'],request_sha256=sha(canonical(request)),n_params=compiled['n_params'],rows=len(case['request']['y']),initial_params=[1.0]*compiled['n_params'],attempt=1)
        if reservation!=expected_reservation: raise ValueError('request binding')
        diag=result['optimizer_diagnostics']
        if diag['initial_params']!=reservation['initial_params'] or diag['final_params']!=result['params'] or diag['optimizer_invocations']!=1 or diag['optimizer_success'] is not True or diag['nfev']!=fitted['nfev'] or diag['candidate_calls']!=fitted['candidate_calls'] or diag['postfit_confirmation_calls']!=1 or diag['optimizer_candidate_calls']+1!=diag['candidate_calls']: raise ValueError('optimizer details mismatch')
        prediction_request={k:v for k,v in case['request'].items() if k!='y'}
        prediction_request.update(phase='predict',params=result['params'])
        if read('prediction-request.json')!=dict(request_sha256=sha(canonical(prediction_request)),target_present=False): raise ValueError('prediction request binding')
        predictions=predict['result']['predictions']
        score=score_predictions(case['request']['y'],predictions)
        if result['score']!=score or not assess(case,result,predictions,protocol['thresholds']): raise ValueError('synthetic score replay')
        if score['status']!='success' and (result['metrics'] is not None or result['sse'] is not None): raise ValueError('unavailable metric has numeric score')
        if score['status']=='success' and (score['metrics']!=result['metrics'] or math.fsum((y-p)**2 for y,p in zip(case['request']['y'],predictions))!=result['sse']): raise ValueError('metric replay')
    for case,row in zip(protocol['guard_cases'],summary['rows'][10:]):
        if row!={'id':case['id'],'passed':True}: raise ValueError('guard row mismatch')
        position=directory/case['id']
        compiled=compile_submission(dict(feature_ids=['m_0','m_3'],explanation='Synthetic finite input overflow guard'),make_spec(1,2))
        request=dict(family='symbolic',phase='predict',X=[[1e200],[-1e200],[0.]],params=case['params'])
        if json.loads((position/'compiled.json').read_bytes())!=compiled or json.loads((position/'request.json').read_bytes())!=request: raise ValueError('guard source/request mismatch')
        predicted=json.loads((directory/case['id']/'predict.json').read_bytes())
        if predicted['status']!='completed' or predicted['result']['status']!='success' or predicted['result']['predictions']!=case['expected']: raise ValueError('guard replay')
    if len(list(directory.glob('*/fit.json')))!=10 or len(list(directory.glob('*/predict.json')))!=12 or summary['sandbox_calls']!=22: raise ValueError('activity counts')
    expected_counts=dict(synthetic_fit_attempts=10,synthetic_fits_converged=10,synthetic_predict_calls=12,sandbox_calls=22,internal_synthetic_warmups=22,benchmark_fits=0,benchmark_data_reads=0,model_requests=0,policy_updates=0,sealed_accesses=0)
    if any(summary.get(k)!=v for k,v in expected_counts.items()): raise ValueError('summary activity mismatch')
    return dict(status='passed',raw_files=len(manifest['files']),synthetic_fit_cases=10,guard_predict_cases=2,
                score_replays=10,new_fits=0,new_candidate_executions=0,benchmark_data_reads=0,
                protocol_sha256=sha((ROOT/PROTOCOL).read_bytes()),manifest_sha256=sha((directory/'manifest.json').read_bytes()))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['prepare','run','verify'])
    parser.add_argument('--sha256'); parser.add_argument('--directory'); parser.add_argument('--output')
    args=parser.parse_args()
    if args.command=='prepare': prepare()
    elif args.command=='run': run(args.sha256)
    else:
        result=verify(ROOT/args.directory)
        if args.output: write(ROOT/args.output,result)
        print(json.dumps(result))


if __name__=='__main__': main()
