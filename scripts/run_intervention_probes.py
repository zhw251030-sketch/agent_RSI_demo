#!/usr/bin/env python3
"""Frozen, zero-LLM development calibration. Candidate Python runs only in sandbox."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CONFIG_PATH = 'configs/pilots/intervention-probes-v0.1.json'
EXPECTED = {
    'version':'intervention-probes-v0.1',
    'protocol':'docs/protocols/2026-10-21-intervention-probes-v0.1.md',
    'epsilon':1e-5, 'numeric_tolerance':1e-10, 'max_sandbox_calls':40,
    'model_calls':0, 'sealed_tasks_executed':0,
    'case_order':['planning','format_patch','symbolic','unsupported_fixture'],
    'format_patch_requires_all_public_supported':True, 'resume':False,
}
COUNT_KEYS = ('sandbox_calls','new_candidate_executions','host_validations',
              'val_calls','fit_calls','predict_calls')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n').encode('utf-8'))


def validate_config(config):
    if (type(config) is not dict or set(config) != set(EXPECTED)
            or any(type(config[k]) is not type(v) or config[k] != v for k,v in EXPECTED.items())):
        raise ValueError('Frozen protocol changed')
    return config


def load_config(root):
    return validate_config(json.loads((root/CONFIG_PATH).read_bytes()))


class ExecutionBudget:
    def __init__(self, maximum):
        self.maximum=maximum; self.reserved=0; self.actual=0

    def reserve(self, count):
        if type(count) is not int or count < 0 or self.reserved+count > self.maximum:
            raise ValueError('Sandbox budget exhausted before dispatch')
        self.reserved += count

    def settle(self, reserved, actual):
        if type(actual) is not int or not 0 <= actual <= reserved:
            raise ValueError('Unexpected sandbox count')
        self.actual += actual


def patch_allowed(results):
    return len(results)==2 and all(r.get('status')=='completed' and r.get('verdict')=='supported' for r in results)


def scoped_edit(family, result):
    actions={
        'planning':{'supported':'consider_format_patch_under_AST_contract',
                    'contradicted':'formatting_not_sufficient_check_semantics',
                    'unknown':'no_repair_inference'},
        'symbolic':{'supported':'retain_selected_term_under_fixed_train_protocol',
                    'contradicted':'consider_evaluated_term_removal',
                    'unknown':'no_term_value_decision'}}
    return {'action':actions[family][result['verdict']],
            'scope':result['task_id'] if family=='planning' else 'oscillator1/train',
            'excludes':['physical_necessity','held_out_generalization',
                        'optimal_rule_selection','agent_autonomous_improvement']}


def new_output(root, output):
    root=root.resolve(); output=Path(output)
    scope=root/'runs/intervention-probes'
    try:
        relative=output.resolve().relative_to(scope)
    except ValueError as exc:
        raise ValueError('Output outside new calibration scope') from exc
    if len(relative.parts)!=1:
        raise ValueError('Output must be one new run directory')
    current=root
    for part in output.relative_to(root).parts:
        current=current/part
        if current.is_symlink():
            raise ValueError('Symlinked output')
    output.mkdir(parents=True, exist_ok=False)
    return output


def runtime_freeze(root, config, *, allow_dirty=False):
    def git(*args):
        return subprocess.check_output(['git','-C',str(root),*args], text=True).strip()
    dirty=git('status','--porcelain')
    if dirty and not allow_dirty:
        raise ValueError('Runtime checkout must be clean before execution')
    paths=[]
    for directory in ('rsi_eval','scripts'):
        paths.extend((root/directory).glob('*.py'))
    paths += [root/CONFIG_PATH, root/config['protocol']]
    paths += list((root/'configs/tasks').glob('*.json'))
    hashes={p.relative_to(root).as_posix():sha(p.read_bytes()) for p in sorted(paths)}
    return {'version':'intervention-runtime-freeze-v0.1', 'runtime_commit':git('rev-parse','HEAD'),
            'checkout_clean':not bool(dirty), 'runtime_files_sha256':hashes,
            'recorded_at_utc':datetime.now(timezone.utc).isoformat()}


def assert_frozen(root, freeze):
    for relative,digest in freeze['runtime_files_sha256'].items():
        if sha((root/relative).read_bytes())!=digest:
            raise ValueError('Runtime file changed: '+relative)


def evaluator_counts(record):
    phases=[r.get('phase') for r in record.get('executions',[])]
    # A plan-phase sandbox failure returns before host validation starts.
    validated=('plan_length' in record or record.get('error_kind') in (
        'diagnostic_validator_disagreement','plan_validation_failed'))
    counts={'sandbox_calls':len(phases), 'new_candidate_executions':1,
            'host_validations':int(validated), 'val_calls':int('validator' in record),
            'fit_calls':phases.count('fit'), 'predict_calls':phases.count('predict')}
    if record.get('error_kind') in ('validator_io','plan_validation_failed','diagnostic_validator_disagreement'):
        counts['val_count_complete']=False
    return counts


def run(root, output, *, prepare_only=False):
    from rsi_eval.probe_cases import load_cases
    from rsi_eval.planning_probe import probe_plan, build_format_patch
    from rsi_eval.symbolic_probe import probe_symbolic, build_term_removal
    from rsi_eval.executor import evaluate_candidate
    config=load_config(root)
    bundle=load_cases(root)
    freeze=runtime_freeze(root,config,allow_dirty=prepare_only)
    output=new_output(root,output)
    write_json(output/'config.json',config)
    write_json(output/'cases.json',bundle)
    write_json(output/'freeze.json',freeze)
    budget=ExecutionBudget(config['max_sandbox_calls'])
    report={'version':config['version'],'status':'prepared' if prepare_only else 'running',
            'model_calls':0,'sealed_tasks_executed':0,'planning':[],'symbolic':[],
            'format_patch':{'status':'not_started'},'unsupported_fixture':None,
            'counts':{key:0 for key in COUNT_KEYS}, 'counts_complete':True, 'errors':[]}

    def save():
        report['budget']={'maximum':budget.maximum,'reserved':budget.reserved,'actual':budget.actual}
        write_json(output/'summary.json',report)

    def account(result, reserved):
        counts=result['executions']
        if (counts.get('val_count_complete',True) is not True
                or result.get('execution_accounting_complete',True) is not True):
            report['counts_complete']=False
        budget.settle(reserved,counts['sandbox_calls'])
        for key in COUNT_KEYS:
            value=counts.get(key,0)
            if type(value) is not int or value<0:
                raise ValueError('Invalid execution accounting')
            report['counts'][key]+=value

    def check_infrastructure(result):
        if result.get('status')=='infrastructure_error' or result.get('infrastructure_stopped'):
            raise RuntimeError('Infrastructure stopped calibration')

    save()
    if prepare_only:
        return report
    try:
        for case in bundle['planning']:
            row={'id':case['id'],'results':[]}; report['planning'].append(row)
            for index,task in enumerate(bundle['public_tasks']):
                assert_frozen(root,freeze); budget.reserve(1); save()
                result=probe_plan(case['source'],task,root=root,source_sha256=case['source_sha256'])
                result['next_edit_scope']=scoped_edit('planning',result)
                row['results'].append(result)
                write_json(output/'planning'/case['id']/f'public-{index}.json',result)
                account(result,1); save(); check_infrastructure(result)

        first=bundle['planning'][0]
        if patch_allowed(report['planning'][0]['results']):
            patch=build_format_patch(first['source'])
            report['format_patch']={'status':'running','source_case':first['id'],
                                    'patch':patch,'results':[]}
            write_json(output/'format-patch/contract.json',patch)
            if patch['status']!='accepted':
                raise ValueError('Frozen format patch contract did not match')
            (output/'format-patch/candidate.py').write_bytes(patch['source'].encode('utf-8'))
            for index,task in enumerate(bundle['development_tasks']):
                assert_frozen(root,freeze); budget.reserve(1); save()
                result=evaluate_candidate('planning',task,patch['source'],root=root,
                    candidate_id='researcher-format-intervention',parent_id=first['id'],
                    strategy_version=config['version'],diagnostics=True)
                report['format_patch']['results'].append(result)
                write_json(output/'format-patch'/f'evaluation-{index:02d}.json',result)
                account({'executions':evaluator_counts(result)},1)
                save(); check_infrastructure(result)
            report['format_patch']['status']='completed'
        else:
            report['format_patch']={'status':'not_triggered','reason':'public_probe_not_all_supported'}
        save()

        for case in bundle['symbolic']:
            assert_frozen(root,freeze); budget.reserve(6); save()
            arguments={key:case[key] for key in ('n_params','remove_param_index','source_sha256',
                                                'parent_source','parent_n_params','parent_sha256')}
            result=probe_symbolic(case['source'],root=root,case_id=case['id'],
                epsilon=config['epsilon'],tolerance=config['numeric_tolerance'],**arguments)
            result['next_edit_scope']=scoped_edit('symbolic',result)
            report['symbolic'].append({'id':case['id'],'result':result})
            write_json(output/'symbolic'/case['id']/'probe.json',result)
            for variant in result.get('variants',[]):
                path=output/'symbolic'/case['id']/(variant['name']+'.py')
                path.write_bytes(variant['source'].encode('utf-8'))
            account(result,6); save(); check_infrastructure(result)

        source='def equation(x, v, params):\n    return params[0]*params[1]*x + params[2]*v\n'
        parent='def equation(x, v, params):\n    return params[0]*x + params[1]*v\n'
        fixture=build_term_removal(source,n_params=3,remove_param_index=2,
            source_sha256=sha(source.encode()),parent_source=parent,parent_n_params=2,
            parent_sha256=sha(parent.encode()))
        report['unsupported_fixture']={'origin':'researcher_synthetic_not_benchmark',
             'source':source,'parent_source':parent,'result':fixture,'sandbox_calls':0}
        write_json(output/'unsupported-fixture.json',report['unsupported_fixture'])
        if fixture.get('status')!='unknown':
            raise ValueError('Unsupported coupled parameter was accepted')
        assert_frozen(root,freeze)
        # Recheck archive provenance after all new execution; no historical rewrites.
        if load_cases(root)!=bundle:
            raise ValueError('Historical source provenance changed')
        report['status']='completed'
    except Exception as exc:
        report['status']='stopped'
        # An exception can occur after dispatch but before a complete record.
        # The settled counter is then a confirmed lower bound, not an exact zero.
        report['counts_complete']=False
        report['errors'].append({'type':type(exc).__name__})
        save()
        raise
    finally:
        save()
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--prepare-only',action='store_true')
    args=parser.parse_args()
    result=run(ROOT,args.output.resolve(),prepare_only=args.prepare_only)
    print(json.dumps({'status':result['status'],'counts':result['counts'],'budget':result['budget']},indent=2))
    return 0 if result['status'] in ('prepared','completed') else 1


if __name__=='__main__':
    raise SystemExit(main())
