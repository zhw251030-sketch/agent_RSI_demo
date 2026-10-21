#!/usr/bin/env python3
"""Run one new eight-slot batch with a frozen 180-second transport setting."""
import argparse,contextlib,copy,importlib.metadata,io,json,logging,platform,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from scripts.run_state_generation import (read,sha,create_json,update_summary,new_output,
    build_inputs,load_public_examples,history_index,execute)
from scripts.run_state_generation import runtime_freeze as base_runtime_freeze
from scripts.run_checked_feedback import _model_configuration
from rsi_eval.pilot_budget import BudgetLedger

BATCH_CONFIG='configs/pilots/state-generation-v0.2.json'
PROTOCOL='docs/protocols/2026-10-21-state-generation-v0.2.md'

def validate_batch(config):
    expected=dict(version='state-generation-batch-v0.2',protocol=PROTOCOL,
        base_config='configs/pilots/state-generation-v0.1.json',
        previous_archive='artifacts/state-generation/2026-10-21/v01',
        previous_archive_manifest_sha256='c8b249c5c8bbbcff497e86536309e5f6cfbf7ca8b4eac59871101d778466086c',
        effective_timeout_seconds=180,python_version='3.12.14',sdk_version='1.55.1',whole_new_batch=True,
        automatic_retries=0,resume=False,candidate_executions=0,strategy_updates=0)
    from rsi_eval.state_generation import canonical
    if canonical(config)!=canonical(expected):raise ValueError('Frozen batch configuration changed')
    return copy.deepcopy(config)

def load_batch_config(root):return validate_batch(read(Path(root)/BATCH_CONFIG))

def model_configuration(root,budgets):
    root=Path(root);batch=load_batch_config(root)
    digest,public,effective=_model_configuration(root/'configs/models/minimax-m3.json',budgets)
    effective['timeout']=batch['effective_timeout_seconds']
    return digest,public,effective

def batch_snapshot(root):
    root=Path(root);config=load_batch_config(root)
    if platform.python_implementation()!='CPython' or platform.python_version()!=config['python_version']:
        raise ValueError('Source AST freeze requires CPython 3.12.14')
    previous=root/config['previous_archive']/'manifest.json'
    if sha(previous)!=config['previous_archive_manifest_sha256']:
        raise ValueError('Previous archive manifest changed')
    return dict(version='state-generation-batch-freeze-v0.2',config_path=BATCH_CONFIG,
        config_sha256=sha(root/BATCH_CONFIG),config=config,protocol_sha256=sha(root/PROTOCOL),
        python_version=platform.python_version(),python_implementation=platform.python_implementation(),
        sdk_version=config['sdk_version'],previous_archive_manifest_sha256=sha(previous))

def runtime_freeze(root,*,allow_dirty=False):
    result=base_runtime_freeze(root,allow_dirty=allow_dirty)
    result['runtime_files_sha256'][PROTOCOL]=sha(Path(root)/PROTOCOL)
    return result

def prepare(root,run_id,*,allow_dirty=False):
    root=Path(root);batch=batch_snapshot(root)
    inputs=build_inputs(root,load_public_examples(root));config=inputs['config']
    freeze=runtime_freeze(root,allow_dirty=allow_dirty)
    output=new_output(root,run_id)
    for name,value in [('runtime-freeze.json',freeze),('input-freeze.json',inputs),
        ('history-index.json',history_index(root)),('config.json',config),('batch-freeze.json',batch)]:
        create_json(output/name,value)
    report=dict(version='state-generation-run-v0.2',run_id=run_id,status='prepared',
        runtime_commit=freeze['runtime_commit'],batch_freeze_sha256=sha(output/'batch-freeze.json'),
        inputs_freeze_sha256=sha(output/'input-freeze.json'),history_index_sha256=sha(output/'history-index.json'),
        candidate_executions=0,task_evaluations=0,probe_executions=0,sealed_tasks_executed=0,
        strategy_updates=0,model_weight_updates=0,symbolic_csv_reads=0,resumed=False,
        slots=[{**{k:s[k] for k in ('id','family','role','task_ids','input_dimension')},
            'status':'not_started','disposition':'not_started','request_id':None,'candidate':None,
            'session_summary':None} for s in inputs['slots']])
    ledger=BudgetLedger(output/'budget-ledger.json',session_ids=[s['id'] for s in inputs['slots']],**config['budgets'])
    digest,public,effective=model_configuration(root,config['budgets'])
    report.update(model_config=public,effective_model_config=effective,model_config_sha256=digest)
    create_json(output/'generation-settings.json',dict(model_config_sha256=digest,public=public,effective=effective))
    report['budget']=ledger.summary();update_summary(output/'summary.json',report)
    return output,report,inputs,ledger

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run-id',required=True)
    mode=p.add_mutually_exclusive_group(required=True);mode.add_argument('--prepare-only',action='store_true');mode.add_argument('--run',action='store_true')
    args=p.parse_args(argv);output=None;ledger=None
    report={'version':'state-generation-run-v0.2','run_id':args.run_id,'status':'preparing'}
    previous=logging.root.manager.disable;logging.disable(logging.CRITICAL)
    try:
        with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
            if args.run and importlib.metadata.version('openhands-sdk')!='1.55.1':raise ValueError('SDK version differs')
            output,report,inputs,ledger=prepare(ROOT,args.run_id,allow_dirty=args.prepare_only)
            if args.run:
                from rsi_eval.state_generation_agent import GenerationStatePacketLLM,run_generation_session
                from rsi_eval.state_generation_transport import observed_transport
                from scripts.configure_minimax import auth_path,read_key
                settings=dict(report['effective_model_config'],api_key=read_key(auth_path(None)))
                report['status']='running'
                def session(c,row,directory):
                    if sha(output/'batch-freeze.json')!=report['batch_freeze_sha256']:
                        raise ValueError('Batch freeze changed')
                    llm=GenerationStatePacketLLM(**settings).bind_controller(c).bind_pilot(ledger,row['id'],directory/'requests')
                    with observed_transport(directory,expected_timeout=180):
                        return run_generation_session(c,llm,row['id'],directory)
                execute(ROOT,output,report,inputs,ledger,session)
    except Exception as error:report.update(status='error',error_type=type(error).__name__)
    finally:logging.disable(previous)
    if ledger is not None:report['budget']=ledger.summary()
    if output is not None:update_summary(output/'summary.json',report)
    print(json.dumps({k:v for k,v in report.items() if k not in ('slots','model_config','effective_model_config')},indent=2))
    return 0 if report['status'] in ('prepared','attempts_completed') else 1

if __name__=='__main__':raise SystemExit(main())
