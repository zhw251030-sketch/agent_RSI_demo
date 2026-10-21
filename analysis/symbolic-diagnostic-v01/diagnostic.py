"""Eight once-only, researcher-specified fits; never an Agent/strategy run.

Commands: calibrate, freeze, run, verify. Old runtime/data permissions are reused;
the diagnostic worker is mounted using byte-identical sandbox/bootstrap copies.
"""
import argparse
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import subprocess
import sys
import time

BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[1]
sys.path.insert(0, str(ROOT))
from rsi_eval.symbolic import score_predictions
from rsi_eval.role_executor import RoleExecutor, LIMITS
from rsi_eval.strategy_binding import EvaluationGate
from rsi_eval.strategy_pair_preparation import assert_runtime

ORDER = ['stress-original-7', 'stress-direct-4', 'bact-triple-14',
         *[f'bact-square-14-drop{i}' for i in range(4)], 'bact-square-15']
GATE = 'runs/strategy-pair/measured-v03/experiment/evaluation-gate.json'
OLD_FREEZE = 'artifacts/strategy-measured/2026-10-21/v03/raw/preparation/runtime-freeze.json'
MANIFEST = 'artifacts/strategy-measured/2026-10-21/v03/manifest.json'
PARTITION = 'configs/tasks/strategy-partition-v0.1.json'
RUN = 'runs/symbolic-diagnostic/v01'
PROTOCOL = 'docs/experiments/2026-10-22-symbolic-diagnostic-freeze.json'


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False,
                      separators=(',', ':')).encode('utf-8')


def sha(raw): return hashlib.sha256(raw).hexdigest()
def read(path): return json.loads(Path(path).read_bytes())


def write(path, value):
    with Path(path).open('xb') as stream: stream.write(canonical(value)+b'\n')


def reference(path):
    return {'path':path.relative_to(ROOT).as_posix(), 'sha256':sha(path.read_bytes())}


def check_files(root, records):
    root = root.resolve()
    for record in records:
        path = root/record['path']
        if not path.resolve().is_relative_to(root) or any(p.is_symlink() for p in [path, *path.parents]):
            raise ValueError('unsafe file path')
        if sha(path.read_bytes()) != record['sha256']: raise ValueError('file changed: '+record['path'])


def allowed_task(task):
    if task not in ('stressstrain', 'bactgrow'): raise ValueError('only two already-seen train tasks allowed')
    return task


def effective(identifier, params):
    if identifier == 'stress-original-7':
        c,q,r,l,m,g,b = params
        return [b,g*c*l*m,g*q*l*l,g*r*m*m]
    return params


def fit_succeeded(receipt):
    result = receipt.get('result', {})
    params = result.get('params')
    return (receipt.get('status') == 'completed' and result.get('status') == 'success'
            and result.get('converged') is True and isinstance(params, list)
            and all(type(p) in (int,float) and math.isfinite(p) for p in params))


def infrastructure_failure(receipt):
    if receipt.get('status')=='completed' and receipt.get('result',{}).get('status')=='invalid_request': return True
    return receipt.get('status') not in ('completed', 'timeout', 'output_limit', 'resource_limit', 'candidate_process_error')


def sandbox(new=True):
    path = BASE/'runtime/rsi_eval/sandbox.py' if new else ROOT/'rsi_eval/sandbox.py'
    spec = importlib.util.spec_from_file_location('isolated_diagnostic_sandbox', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.run_candidate


def runtime_environment():
    code = ('import sys,json,inspect;sys.path.insert(0,sys.argv[1]);'
            'import numpy,scipy;from scipy.optimize import least_squares;'
            'print(json.dumps(dict(python=sys.version,numpy=numpy.__version__,'
            'scipy=scipy.__version__,least_squares_signature=str(inspect.signature(least_squares)))))')
    raw = subprocess.check_output(['/usr/bin/python3','-I','-S','-B','-c',code,str(ROOT/'.task-runtime/python')])
    return json.loads(raw)


def call(source, request, new=True):
    return sandbox(new)(source, request, deps_dir=ROOT/'.task-runtime/python', **LIMITS)


def runtime_check():
    files = read(ROOT/OLD_FREEZE)['files']
    assert_runtime(ROOT, files)
    for name in ('sandbox.py','worker.py','__init__.py'):
        if (BASE/'runtime/rsi_eval'/name).read_bytes() != (ROOT/'rsi_eval'/name).read_bytes():
            raise ValueError('isolation/bootstrap copy changed: '+name)
    return len(files)


def calibrate(output):
    output.mkdir(parents=True, exist_ok=False)
    runtime_check()
    linear='def equation(x, params):\n    return params[0]*x+params[1]\n'
    constant='def equation(x, params):\n    return np.full_like(x, params[0])\n'
    X=[[float(x)] for x in range(-3,4)]
    records=[]
    for name,source,y,nparams in [('linear',linear,[2*x[0]+3 for x in X],2),
                                 ('constant',constant,[4.0]*len(X),1)]:
        req=dict(family='symbolic',phase='fit',X=X,y=y,n_params=nparams)
        pair=[]
        for new in (False,True):
            result=call(source,req,new)
            write(output/f'{name}-{"new" if new else "old"}-fit.json', result)
            if not fit_succeeded(result): raise ValueError('calibration fit failed')
            pair.append(result['result'])
        if len(pair[0]['params']) != len(pair[1]['params']) or any(abs(a-b)>1e-10 for a,b in zip(pair[0]['params'],pair[1]['params'])):
            raise ValueError('instrumentation changed calibration coefficients')
        prediction=call(source,dict(family='symbolic',phase='predict',X=X,params=pair[1]['params']))
        write(output/f'{name}-new-predict.json',prediction)
        values=prediction.get('result',{}).get('predictions',[])
        if len(values)!=len(y) or max(abs(a-b) for a,b in zip(y,values))>1e-8:
            raise ValueError('calibration prediction failed')
        records.append(dict(case=name,params=pair[1]['params'],max_absolute_error=max(abs(a-b) for a,b in zip(y,values))))
    bad=call('def equation(x, params):\n    return 1.0\n',dict(family='symbolic',phase='fit',X=X,y=[1.0]*len(X),n_params=1))
    write(output/'invalid-shape.json',bad)
    if bad.get('result',{}).get('error')!='invalid_shape': raise ValueError('negative calibration not rejected')
    report=dict(status='passed',cases=records,synthetic_fit_attempts=5,synthetic_fit_successes=4,
                sandbox_calls=7,internal_synthetic_warmups=7,benchmark_fits=0,model_requests=0,
                environment=runtime_environment(),runtime_files_unchanged=runtime_check(),
                calibrated_files=[reference(p) for p in sorted((BASE/'runtime/rsi_eval').glob('*.py'))])
    write(output/'summary.json',report)
    print(json.dumps(report))


def freeze(output, calibration):
    runtime_check()
    calibrated=read(calibration/'summary.json')
    if calibrated['status']!='passed' or calibrated['environment']!=runtime_environment():
        raise ValueError('calibration/environment mismatch')
    check_files(ROOT,calibrated['calibrated_files'])
    candidates=read(BASE/'candidates.json')['candidates']
    if [c['id'] for c in candidates]!=ORDER: raise ValueError('candidate order changed')
    for c in candidates:
        allowed_task(c['task'])
        check_files(ROOT,[dict(path=c['source_path'],sha256=c['source_sha256']),*c['parents']])
    files=[reference(p) for p in sorted(BASE.rglob('*')) if p.is_file() and p.suffix in ('.py','.json','.md') and '__pycache__' not in p.parts]
    files += [reference(p) for p in sorted(calibration.glob('*.json'))]
    files += [reference(ROOT/p) for p in (OLD_FREEZE,MANIFEST,PARTITION,GATE)]
    data=[x for x in read(ROOT/PARTITION)['symbolic']['files'] if x['split']=='train' and x['task_id'] in ('bactgrow','stressstrain')]
    if len(data)!=2 or {x['task_id'] for x in data}!={'bactgrow','stressstrain'}: raise ValueError('train metadata scope mismatch')
    # Only hash raw bytes here; numeric parsing is deferred until the once-only run.
    check_files(ROOT,[dict(path=x['data_path'],sha256=x['sha256']) for x in data])
    protocol=dict(version='symbolic-diagnostic-v01',order=ORDER,candidates=candidates,data=data,
                  environment=runtime_environment(),limits=LIMITS,input_transform='identity',
                  optimizer='scipy.optimize.least_squares(residual, np.ones(n_params), max_nfev=100); all other installed defaults',
                  fitting_scope='seen train only; once per condition; researcher numerical diagnostic',
                  gate=reference(ROOT/GATE),run_directory=RUN,files=files,model_requests=0,
                  retries=0,resume=False,failures='candidate/timeout retained; infrastructure exception stops; no replacement',
                  freeze_git_head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip())
    write(output,protocol)
    print(json.dumps({'status':'frozen','sha256':sha(output.read_bytes()),'files':len(files),'conditions':len(candidates)}))


def run(protocol_path, expected_hash):
    if sha(protocol_path.read_bytes())!=expected_hash: raise ValueError('protocol hash mismatch')
    protocol=read(protocol_path)
    if protocol['order']!=ORDER or protocol['run_directory']!=RUN: raise ValueError('wrong run protocol')
    if protocol['candidates']!=read(BASE/'candidates.json')['candidates'] or [c['id'] for c in protocol['candidates']]!=ORDER: raise ValueError('candidate protocol mismatch')
    check_files(ROOT,protocol['files'])
    if runtime_environment()!=protocol['environment']: raise ValueError('numerical environment changed')
    runtime_check()
    output=ROOT/RUN
    output.mkdir(parents=True,exist_ok=False)
    write(output/'protocol.json',protocol)
    write(output/'start.json',dict(protocol_sha256=expected_hash,started_unix=time.time(),git_head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()))
    rows=[]
    sandbox_calls=0
    try:
        executor=RoleExecutor(ROOT,role='evaluation',evaluation_gate=EvaluationGate(**protocol['gate']))
        tasks={name:executor.prepare_task('symbolic',allowed_task(name)) for name in ('stressstrain','bactgrow')}
        for index,candidate in enumerate(protocol['candidates']):
            check_files(ROOT,[dict(path=candidate['source_path'],sha256=candidate['source_sha256'])])
            source=(ROOT/candidate['source_path']).read_bytes().decode('utf-8')
            task=tasks[allowed_task(candidate['task'])]
            request=dict(task['request'],phase='fit',n_params=candidate['n_params'])
            position=output/f'{index+1:02d}-{candidate["id"]}'
            position.mkdir(exist_ok=False)
            target_mean=math.fsum(v/len(request['y']) for v in request['y'])
            variance=math.fsum((v-target_mean)**2/len(request['y']) for v in request['y'])
            write(position/'reserved.json',dict(id=candidate['id'],source_sha256=candidate['source_sha256'],
                  provenance=task['provenance'],request_sha256=sha(canonical(request)),rows=len(request['y']),
                  target_population_variance=variance,target_sha256=sha(canonical(request['y'])),
                  n_params=candidate['n_params'],initial_params=[1.0]*candidate['n_params'],attempt=1))
            sandbox_calls+=1
            fitted=call(source,request)
            write(position/'fit.json',fitted)
            row=dict(id=candidate['id'],task=candidate['task'],n_params=candidate['n_params'],status='fit_failed',
                     metrics=None,sse=None,effective_coefficients=None,fit_status=fitted.get('status'),
                     fit_seconds=fitted.get('elapsed_seconds'),diagnostics=fitted.get('result',{}).get('diagnostics'))
            if infrastructure_failure(fitted): raise RuntimeError('fit infrastructure failed at '+candidate['id'])
            if fit_succeeded(fitted):
                params=fitted['result']['params']
                if len(params)!=candidate['n_params']: raise ValueError('fitted parameter count mismatch')
                predict={k:v for k,v in task['request'].items() if k!='y'}
                predict.update(phase='predict',params=params)
                write(position/'prediction-request.json',dict(request_sha256=sha(canonical(predict)),target_present=False))
                sandbox_calls+=1
                predicted=call(source,predict)
                write(position/'predict.json',predicted)
                if infrastructure_failure(predicted): raise RuntimeError('prediction infrastructure failed')
                values=predicted.get('result',{}).get('predictions')
                scored=score_predictions(request['y'],values)
                row['status']='prediction_failed'
                if predicted.get('status')=='completed' and predicted.get('result',{}).get('status')=='success' and scored['status']=='success':
                    row.update(status='success',metrics=scored['metrics'],sse=math.fsum((y-p)**2 for y,p in zip(request['y'],values)),
                               effective_coefficients=effective(candidate['id'],params))
            write(position/'result.json',row)
            rows.append(row)
            print(json.dumps(row),flush=True)
        runtime_check()
        summary=dict(status='complete',rows=rows,benchmark_fit_attempts=len(rows),sandbox_calls=sandbox_calls,
                     benchmark_prediction_calls=sandbox_calls-len(rows),internal_synthetic_warmups=sandbox_calls,
                     model_requests=0,agent_candidates=0,policy_updates=0,sealed_evaluations=0,old_runtime_files_unchanged=258)
        write(output/'summary.json',summary)
    except BaseException as exc:
        write(output/'aborted.json',dict(status='aborted_no_resume',error_type=type(exc).__name__,error=str(exc),
                                       completed_rows=len(rows),sandbox_calls=sandbox_calls))
        raise
    finally:
        files=[dict(path=p.relative_to(output).as_posix(),sha256=sha(p.read_bytes())) for p in sorted(output.rglob('*')) if p.is_file()]
        write(output/'manifest.json',dict(files=files))


def verify(directory, verify_scores=False):
    manifest=read(directory/'manifest.json')
    check_files(directory,manifest['files'])
    listed={r['path'] for r in manifest['files']}|{'manifest.json'}
    actual={p.relative_to(directory).as_posix() for p in directory.rglob('*') if p.is_file()}
    if listed!=actual: raise ValueError('archive coverage mismatch')
    protocol=read(directory/'protocol.json')
    anchor=ROOT/PROTOCOL
    if (directory/'protocol.json').read_bytes()!=anchor.read_bytes(): raise ValueError('external frozen protocol mismatch')
    if read(directory/'start.json')['protocol_sha256']!=sha(anchor.read_bytes()): raise ValueError('execution protocol binding mismatch')
    if protocol['candidates']!=read(BASE/'candidates.json')['candidates']: raise ValueError('candidate definitions changed')
    check_files(ROOT,[r for r in protocol['files'] if not r['path'].startswith('runs/')])
    tasks={}
    if verify_scores:
        executor=RoleExecutor(ROOT,role='evaluation',evaluation_gate=EvaluationGate(**protocol['gate']))
        tasks={name:executor.prepare_task('symbolic',allowed_task(name)) for name in ('stressstrain','bactgrow')}
    summary=read(directory/'summary.json')
    if summary['status']!='complete' or [r['id'] for r in summary['rows']]!=ORDER: raise ValueError('incomplete run')
    for index,row in enumerate(summary['rows']):
        pos=directory/f'{index+1:02d}-{row["id"]}'
        if read(pos/'result.json')!=row: raise ValueError('summary differs from raw result')
        reserved=read(pos/'reserved.json')
        if reserved['attempt']!=1 or reserved['id']!=row['id']: raise ValueError('position mismatch')
        candidate=protocol['candidates'][index]
        data=next(x for x in protocol['data'] if x['task_id']==candidate['task'])
        if row['task']!=candidate['task'] or row['n_params']!=candidate['n_params']: raise ValueError('candidate identity mismatch')
        if (reserved['source_sha256'],reserved['n_params'],reserved['initial_params'],reserved['rows'])!=(candidate['source_sha256'],candidate['n_params'],[1.0]*candidate['n_params'],data['rows']): raise ValueError('reservation mismatch')
        if reserved['provenance']['data_sha256']!=data['sha256'] or reserved['provenance']['metric_scope']!='train': raise ValueError('data provenance mismatch')
        fitted=read(pos/'fit.json')
        if fitted.get('result',{}).get('diagnostics')!=row['diagnostics']: raise ValueError('optimizer metadata mismatch')
        if row['diagnostics'] and row['diagnostics']['initial_params']!=reserved['initial_params']: raise ValueError('optimizer initialization mismatch')
        if row['status']=='success':
            if not fit_succeeded(fitted): raise ValueError('invalid success')
            prediction=read(pos/'predict.json')
            values=prediction.get('result',{}).get('predictions')
            if prediction['status']!='completed' or prediction['result']['status']!='success' or not isinstance(values,list) or len(values)!=reserved['rows'] or not all(type(v) in (int,float) and math.isfinite(v) for v in values): raise ValueError('invalid archived predictions')
            if read(pos/'prediction-request.json')['target_present'] is not False: raise ValueError('prediction target leak')
            if fitted['result']['params']!=row['diagnostics']['final_params']: raise ValueError('optimizer coefficients mismatch')
            if not math.isclose(row['sse']/reserved['rows'],row['metrics']['mse'],rel_tol=1e-12,abs_tol=1e-15): raise ValueError('SSE/MSE mismatch')
            if not math.isclose(row['metrics']['mse']/reserved['target_population_variance'],row['metrics']['nmse'],rel_tol=1e-12): raise ValueError('NMSE mismatch')
            if row['effective_coefficients']!=effective(row['id'],fitted['result']['params']): raise ValueError('coefficient mismatch')
        elif row['metrics'] is not None or row['sse'] is not None: raise ValueError('failed condition has score')
        if verify_scores:
            task=tasks[candidate['task']]
            request=dict(task['request'],phase='fit',n_params=candidate['n_params'])
            if sha(canonical(request))!=reserved['request_sha256'] or sha(canonical(request['y']))!=reserved['target_sha256']: raise ValueError('archived request does not match pinned data')
            if (pos/'predict.json').exists():
                predict={k:v for k,v in task['request'].items() if k!='y'}
                predict.update(phase='predict',params=fitted['result']['params'])
                if sha(canonical(predict))!=read(pos/'prediction-request.json')['request_sha256']: raise ValueError('prediction request mismatch')
            if row['status']=='success':
                if score_predictions(request['y'],values)['metrics']!=row['metrics']: raise ValueError('numeric score replay mismatch')
                if math.fsum((y-p)**2 for y,p in zip(request['y'],values))!=row['sse']: raise ValueError('numeric SSE replay mismatch')
    fits=len(list(directory.glob('*/fit.json')))
    predicts=len(list(directory.glob('*/predict.json')))
    if (summary['benchmark_fit_attempts'],summary['benchmark_prediction_calls'],summary['sandbox_calls'],summary['internal_synthetic_warmups'])!=(fits,predicts,fits+predicts,fits+predicts): raise ValueError('activity count mismatch')
    return dict(status='passed',files=len(manifest['files']),conditions=len(summary['rows']),
                successful_fits=sum(r['status']=='success' for r in summary['rows']),archive_manifest_sha256=sha((directory/'manifest.json').read_bytes()),
                numerical_score_replay=verify_scores,new_fits=0,new_candidate_executions=0,
                scope='external protocol, raw hashes, source/data/parameter/optimizer/prediction/summary bindings; optional score replay from pinned seen train and saved predictions')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['calibrate','freeze','run','verify'])
    parser.add_argument('--output')
    parser.add_argument('--calibration')
    parser.add_argument('--protocol')
    parser.add_argument('--sha256')
    parser.add_argument('--verify-scores',action='store_true')
    args=parser.parse_args()
    if args.command=='calibrate': calibrate(ROOT/args.output)
    elif args.command=='freeze': freeze(ROOT/args.output,ROOT/args.calibration)
    elif args.command=='run': run(ROOT/args.protocol,args.sha256)
    else: print(json.dumps(verify(ROOT/args.output,args.verify_scores)))


if __name__=='__main__': main()
