#!/usr/bin/env python3
"""Generate and freeze cold-start source submissions without executing them."""
import argparse
import ast
import contextlib
import copy
import hashlib
import io
import json
import logging
import os
from pathlib import Path
import re
import sys

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
os.environ['OPENHANDS_SUPPRESS_BANNER']='1'
os.environ['LITELLM_LOCAL_MODEL_COST_MAP']='True'
os.environ['DO_NOT_TRACK']='1'
from rsi_eval.state_generation import GenerationController,build_inputs,validate_config,CONFIG_PATH
from rsi_eval.two_stage_audit import _read as read
from scripts.run_two_stage import directory_hashes,verify_files,assert_runtime
from scripts.run_two_stage import runtime_freeze as previous_runtime_freeze

PROTOCOL='docs/protocols/2026-10-21-state-generation-v0.1.md'


def canonical(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode('utf-8')


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def create_json(path,value):
    path=Path(path)
    if path.is_symlink():raise ValueError('Symlinked output')
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('xb') as stream:
        stream.write((json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode('utf-8'))
        stream.flush();os.fsync(stream.fileno())


def update_summary(path,value):
    path=Path(path);pending=path.with_suffix('.pending')
    create_json(pending,value);os.replace(pending,path)


def ast_digest(source):
    try:
        tree=ast.parse(source)
        return hashlib.sha256(ast.dump(tree,include_attributes=False).encode()).hexdigest()
    except (SyntaxError,ValueError,UnicodeError,RecursionError):return None


def history_index(root):
    root=Path(root);files={}
    for path in sorted((root/'artifacts').rglob('*')):
        if path.is_symlink():raise ValueError('Symlink in historical source index')
        if not path.is_file() or path.suffix!='.py':continue
        raw=path.read_bytes()
        try:normalized=ast_digest(raw.decode('utf-8'))
        except UnicodeError:normalized=None
        files[path.relative_to(root).as_posix()]={'source_sha256':hashlib.sha256(raw).hexdigest(),'ast_sha256':normalized}
    return {'version':'history-source-index-v0.1','files':files}


build_history_index=history_index


def static_source(source,family,input_dimension):
    result=dict(parse_status='syntax_error',ast_sha256=None,entry_signature_matches=False,executed=False)
    try:tree=ast.parse(source)
    except (SyntaxError,ValueError,UnicodeError,RecursionError):return result
    name='get_plan' if family=='planning' else 'equation'
    expected=3 if family=='planning' else input_dimension+1
    functions=[node for node in tree.body if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)) and node.name==name]
    valid=False
    if len(functions)==1 and type(functions[0]) is ast.FunctionDef:
        args=functions[0].args
        valid=(len(args.posonlyargs)+len(args.args)==expected and not args.vararg and not args.kwarg
               and not args.kwonlyargs and not args.defaults)
    result.update(parse_status='parsed',ast_sha256=hashlib.sha256(ast.dump(tree,include_attributes=False).encode()).hexdigest(),
                  entry_signature_matches=valid)
    return result


def freeze_sources(output,report):
    output=Path(output);(output/'sessions').mkdir(exist_ok=True)
    frozen=dict(version='source-freeze-v0.1',inputs_freeze_sha256=report['inputs_freeze_sha256'],
        history_index_sha256=report['history_index_sha256'],runtime_commit=report['runtime_commit'],
        slots=copy.deepcopy(report['slots']),session_files=directory_hashes(output/'sessions'))
    create_json(output/'source-freeze.json',frozen)
    return sha(output/'source-freeze.json')


def analyze_frozen_sources(output):
    output=Path(output);frozen=read(output/'source-freeze.json')
    verify_files(output/'sessions',frozen['session_files'])
    if sha(output/'history-index.json')!=frozen['history_index_sha256']:raise ValueError('History index changed')
    history=read(output/'history-index.json')['files'];rows=[]
    for slot in frozen['slots']:
        candidate=slot['candidate']
        row=dict(id=slot['id'],family=slot['family'],role=slot['role'],disposition=slot['disposition'],source_sha256=None,
            ast_sha256=None,parse_status='no_source',entry_signature_matches=False,executed=False,
            historical_source_matches=[],historical_ast_matches=[])
        if candidate is not None:
            if candidate['source_file']!='source.py':raise ValueError('Unexpected source file')
            raw=(output/'sessions'/slot['id']/'source.py').read_bytes()
            digest=hashlib.sha256(raw).hexdigest()
            if candidate['source_sha256']!=digest:raise ValueError('Candidate source changed')
            row.update(source_sha256=digest,n_params=candidate['n_params'],
                **static_source(raw.decode('utf-8'),slot['family'],slot['input_dimension']))
            row['historical_source_matches']=[p for p,v in history.items() if v['source_sha256']==digest]
            row['historical_ast_matches']=[p for p,v in history.items() if row['ast_sha256'] is not None and v['ast_sha256']==row['ast_sha256']]
        rows.append(row)
    def groups(field):
        by={}
        for row in rows:
            if row[field] is not None:by.setdefault(row[field],[]).append(row)
        return [dict(sha256=h,slots=[r['id'] for r in group],roles=sorted({r['role'] for r in group}))
                for h,group in sorted(by.items()) if len(group)>1]
    source_groups=groups('source_sha256');ast_groups=groups('ast_sha256')
    return dict(version='state-generation-static-v0.1',source_freeze_sha256=sha(output/'source-freeze.json'),
        rows=rows,source_slots=len(rows),available_sources=sum(r['source_sha256'] is not None for r in rows),
        distinct_source_count=len({r['source_sha256'] for r in rows if r['source_sha256'] is not None}),
        distinct_ast_count=len({r['ast_sha256'] for r in rows if r['ast_sha256'] is not None}),
        source_duplicate_groups=source_groups,ast_duplicate_groups=ast_groups,
        cross_role_ast_duplicates=[g for g in ast_groups if len(g['roles'])>1],
        any_historical_source_collision=any(r['historical_source_matches'] for r in rows),
        any_historical_ast_collision=any(r['historical_ast_matches'] for r in rows),
        candidate_executions=0,performance_scores=None,
        limitations=['AST equality ignores comments/locations only; no alpha-renaming or semantic equivalence check.',
                    'A parsed matching entry signature does not prove runtime correctness or task suitability.',
                    'New API requests are not guaranteed new independent program states.'])


def load_public_examples(root):
    from rsi_eval.planning import prepare_task
    return [prepare_task(f'spannerlearning/seed0/problem{i}',root) for i in (0,1)]


def runtime_freeze(root,*,allow_dirty=False):
    result=previous_runtime_freeze(root,allow_dirty=allow_dirty)
    for p in [Path(root)/PROTOCOL,*sorted((Path(root)/'tests').glob('test_state_generation*.py'))]:
        result['runtime_files_sha256'][p.relative_to(root).as_posix()]=sha(p)
    return result


def new_output(root,run_id):
    if not re.fullmatch('[A-Za-z0-9][A-Za-z0-9_-]{0,63}',run_id):raise ValueError('Invalid run ID')
    path=Path(root)/'runs/state-generation'/run_id
    for part in (path,*path.parents):
        if part.is_symlink() or (hasattr(part,'is_junction') and part.is_junction()):
            raise ValueError('Symlinked run directory')
    path.mkdir(parents=True,exist_ok=False)
    return path


def input_guard(root,output,report,inputs):
    assert_runtime(root,read(output/'runtime-freeze.json'))
    if (sha(output/'input-freeze.json')!=report['inputs_freeze_sha256']
            or canonical(read(output/'input-freeze.json'))!=canonical(inputs)
            or sha(output/'history-index.json')!=report['history_index_sha256']):
        raise ValueError('Frozen generation inputs changed')
    for relative,digest in inputs['source_bindings'].items():
        if sha(root/relative)!=digest:raise ValueError('Bound source changed')


def execute(root,output,report,inputs,ledger,session_runner):
    root=Path(root);output=Path(output)
    def save():
        report['budget']=ledger.summary();update_summary(output/'summary.json',report)
    def guard():input_guard(root,output,report,inputs)
    def checked_guard():
        try:guard();return True
        except Exception as error:
            report.update(status='integrity_failed',error_type=type(error).__name__,
                          stop_reason='frozen_input_or_runtime_changed')
            (output/'sessions').mkdir(exist_ok=True)
            create_json(output/'unverified-source-snapshot.json',{
                'version':'unverified-source-snapshot-v0.1','trusted':False,
                'reason':'integrity_guard_failed','slots':copy.deepcopy(report['slots']),
                'session_files':directory_hashes(output/'sessions')})
            save();return False
    guard();save()
    for row,slot in zip(report['slots'],inputs['slots']):
        if not checked_guard():return
        budget=ledger.summary()
        if budget['halted'] or budget['reserved_count'] or budget['usage_unknown_count']:
            report.update(status='stopped',stop_reason='unsettled_or_unknown_usage');break
        directory=output/'sessions'/row['id']
        c=GenerationController(slot,directory);create_json(directory/'task-packet.json',c.task_packet())
        try:raw=session_runner(c,row,directory)
        except Exception as error:
            raw={'status':'error','model_error_type':type(error).__name__,'host_exception':True}
        row['session_summary']=raw;row['status']=raw.get('status','error');row['candidate']=copy.deepcopy(c.candidate)
        requests=[r for r in read(output/'budget-ledger.json')['requests'] if r['session_id']==row['id']]
        if len(requests)>1:raise ValueError('More than one source request')
        row['request_id']=requests[0]['request_id'] if requests else None
        budget=ledger.summary()
        failure=(raw.get('host_exception',False) or c.halted or budget['halted'] or budget['reserved_count'] or budget['usage_unknown_count']
                 or not requests or (raw.get('model_error_type') not in (None,'PilotResponseContractError','IncompleteToolResponseError')))
        row['disposition']='blocked' if failure else 'available' if c.candidate is not None else 'missing'
        save()
        if failure:
            report.update(status='stopped',stop_reason='generation_infrastructure_or_usage');break
    else:report['status']='attempts_completed'
    if not checked_guard():return
    report['source_freeze_sha256']=freeze_sources(output,report)
    analysis=analyze_frozen_sources(output)
    create_json(output/'static-analysis.json',analysis);report['analysis_sha256']=sha(output/'static-analysis.json')
    report['source_counts']={k:analysis[k] for k in ('source_slots','available_sources','distinct_source_count','distinct_ast_count')}
    save()


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--run-id',required=True)
    modes=parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--prepare-only',action='store_true');modes.add_argument('--run',action='store_true')
    args=parser.parse_args(argv)
    if not re.fullmatch('[A-Za-z0-9][A-Za-z0-9_-]{0,63}',args.run_id):parser.error('Invalid run ID')
    report=dict(version='state-generation-run-v0.1',run_id=args.run_id,status='preparing',
        candidate_executions=0,task_evaluations=0,probe_executions=0,sealed_tasks_executed=0,strategy_updates=0,
        model_weight_updates=0,symbolic_csv_reads=0,resumed=False)
    output=None;ledger=None
    previous=logging.root.manager.disable;logging.disable(logging.CRITICAL)
    try:
        with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
            from rsi_eval.pilot_budget import BudgetLedger
            from scripts.run_checked_feedback import _model_configuration
            config=validate_config(read(ROOT/CONFIG_PATH))
            inputs=build_inputs(ROOT,load_public_examples(ROOT));freeze=runtime_freeze(ROOT,allow_dirty=args.prepare_only)
            output=new_output(ROOT,args.run_id)
            create_json(output/'runtime-freeze.json',freeze);create_json(output/'input-freeze.json',inputs)
            create_json(output/'history-index.json',history_index(ROOT));create_json(output/'config.json',config)
            report.update(runtime_commit=freeze['runtime_commit'],inputs_freeze_sha256=sha(output/'input-freeze.json'),
                history_index_sha256=sha(output/'history-index.json'),
                slots=[{**{k:s[k] for k in ('id','family','role','task_ids','input_dimension')},
                        'status':'not_started','disposition':'not_started','request_id':None,'candidate':None,
                        'session_summary':None} for s in inputs['slots']])
            ledger=BudgetLedger(output/'budget-ledger.json',session_ids=[s['id'] for s in inputs['slots']],**config['budgets'])
            digest,public,effective=_model_configuration(ROOT/'configs/models/minimax-m3.json',config['budgets'])
            report.update(model_config=public,effective_model_config=effective,model_config_sha256=digest)
            create_json(output/'generation-settings.json',{'model_config_sha256':digest,'public':public,'effective':effective})
            if args.prepare_only:report['status']='prepared'
            else:
                from rsi_eval.state_generation_agent import GenerationStatePacketLLM,run_generation_session
                from scripts.configure_minimax import auth_path,read_key
                settings=dict(effective,api_key=read_key(auth_path(None)))
                report['status']='running'
                def session(c,row,directory):
                    llm=GenerationStatePacketLLM(**settings).bind_controller(c).bind_pilot(ledger,row['id'],directory/'requests')
                    return run_generation_session(c,llm,row['id'],directory)
                execute(ROOT,output,report,inputs,ledger,session)
    except Exception as error:
        report.update(status='error',error_type=type(error).__name__)
    finally:logging.disable(previous)
    if ledger is not None:report['budget']=ledger.summary()
    if output is not None and output.is_dir():update_summary(output/'summary.json',report)
    print(json.dumps({k:v for k,v in report.items() if k not in ('slots','model_config','effective_model_config')},ensure_ascii=False,indent=2))
    return 0 if report['status'] in ('prepared','attempts_completed') else 1


if __name__=='__main__':raise SystemExit(main())
