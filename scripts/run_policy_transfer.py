#!/usr/bin/env python3
"""Two explicit processes: choose/freeze S1, then twelve development repairs."""
import argparse
import contextlib
import copy
import hashlib
import importlib.metadata
import io
import json
import logging
import math
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['OPENHANDS_SUPPRESS_BANNER'] = '1'
os.environ['LITELLM_LOCAL_MODEL_COST_MAP'] = 'True'
os.environ['DO_NOT_TRACK'] = '1'
CONFIG_PATH = 'configs/pilots/policy-transfer-v0.1.json'
PROTOCOL = 'docs/protocols/2026-10-20-policy-transfer-v0.1.md'
ACTOR_PROMPT = 'prompts/policy-transfer/actor.md'
UPDATE_PROMPT = 'prompts/policy-transfer/update.md'

from rsi_eval.policy_transfer import canonical, verify_triplets
from scripts.run_paired_repair import summarize_endpoint, write_json


def exclusive_json(path, value):
    with Path(path).open('xb') as stream:
        stream.write(canonical(value)+b'\n')
        stream.flush()
        os.fsync(stream.fileno())


def budget_blocked(summary):
    return bool(summary['halted'] or summary['usage_unknown_count'] or summary['reserved_count'])


def update_request_id(state):
    requests = state.get('requests', [])
    if (len(requests) != 1 or requests[0].get('session_id') != 'policy_update'
            or requests[0].get('status') != 'settled'
            or requests[0].get('usage_state') != 'known'
            or type(requests[0].get('usage')) is not dict):
        raise ValueError('One known, settled policy request is required before evaluation')
    return requests[0]['request_id']


def expected_order():
    result = []
    sequence = [('E-P','fixed'),('E-S','memory'),('E-P','updated'),
                ('E-S','fixed'),('E-P','memory'),('E-S','updated')]
    for repeat in (1,2):
        for state,condition in sequence if repeat == 1 else reversed(sequence):
            pair = state.replace('-','')+'-r'+str(repeat)
            result.append(dict(state_id=state, family='planning' if state=='E-P' else 'symbolic',
                condition=condition, repeat=repeat, pair_id=pair, session_id=pair+'-'+condition))
    return result


def validate_config(config):
    from rsi_eval.policy_cases import PINNED_CASES
    identities = {'schema_version':'0.1', 'base_config':'configs/pilots/development-v0.1.json',
        'policy_file':ACTOR_PROMPT, 'update_prompt':UPDATE_PROMPT, 'protocol':PROTOCOL,
        'states':['E-P','E-S'], 'cases':PINNED_CASES, 'order':expected_order()}
    if type(config) is not dict or any(config.get(k) != v for k,v in identities.items()):
        raise ValueError('Frozen policy comparison identity changed')
    for key,value in [('max_iterations',1),('max_generated_candidates',1),('source_limit_bytes',16384),
                      ('policy_update_requests',1),('evaluation_requests',12)]:
        if type(config.get(key)) is not int or config[key] != value:
            raise ValueError('Policy comparison request shape changed')
    for key in ('automatic_recovery','baseline_reexecution','checks_gate_execution','checks_change_selection'):
        if config.get(key) is not False:
            raise ValueError('Recovery, baseline execution, or selection change is prohibited')
    if config.get('missing_candidate_score') is not None:
        raise ValueError('Missing score must remain null')
    caps = {'max_requests':13,'max_requests_per_session':1,'max_output_tokens':4096,
            'max_input_bytes':98304,'max_reserved_tokens':1800000}
    prices = {'max_cost_cny','input_cny_per_million','output_cny_per_million'}
    budgets = config.get('budgets')
    if type(budgets) is not dict or set(budgets) != set(caps)|prices:
        raise ValueError('Unexpected budgets')
    for key,cap in caps.items():
        if type(budgets[key]) is not int or not 0 < budgets[key] <= cap:
            raise ValueError('Budget outside authorized bound')
    for key in prices:
        if type(budgets[key]) not in (int,float) or not math.isfinite(budgets[key]) or budgets[key]<=0:
            raise ValueError('Invalid cost configuration')
    if budgets['max_cost_cny']>5 or budgets['input_cny_per_million']<2.1 or budgets['output_cny_per_million']<8.4:
        raise ValueError('Cost cap or conservative prices changed')
    return copy.deepcopy(config['order']), copy.deepcopy(budgets)


def asset(relative, prefix):
    path = (ROOT/relative).resolve()
    if not path.is_relative_to(ROOT.resolve()/prefix) or not path.is_file():
        raise ValueError('Trusted asset outside project')
    return path


def source_provenance():
    paths = [p for part in ('rsi_eval','scripts','configs','prompts','fixtures')
             for p in (ROOT/part).rglob('*') if p.is_file() and p.suffix in ('.py','.json','.md')]
    paths.append(ROOT/PROTOCOL)
    return {'code_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
            'sdk_version':importlib.metadata.version('openhands-sdk'),
            'source_sha256':{p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
                             for p in sorted(paths)}}


def prepare_evaluation(output, report, config, base_sessions, states, bundle, policy, guard=None):
    from rsi_eval.policy_transfer import PolicyTransferController
    from rsi_eval.revision_policy import S0
    prepared = []
    prompt = asset(ACTOR_PROMPT,'prompts').read_text(encoding='utf-8')
    for entry in report['sessions']:
        directory = output/entry['session_id']
        c = PolicyTransferController(ROOT, base_sessions[entry['family']], directory,
            session_id=report['run_id']+':'+entry['pair_id'], policy_text=prompt,
            repair_state=states[entry['state_id']],
            policy=policy if entry['condition']=='updated' else S0,
            experience_memory=bundle['cases'] if entry['condition']=='memory' else [], policy_guard=guard)
        baseline = c.baseline()
        packet = c.state_packet()
        (directory/'task-prompt.txt').write_bytes(canonical(packet))
        entry.update(status='prepared', baseline_source_sha256=baseline['source_sha256'],
            baseline_n_params=baseline['n_params'], task_prompt_sha256=hashlib.sha256(canonical(packet)).hexdigest())
        prepared.append((c,directory,entry))
    report['triplet_input_proofs'] = verify_triplets(prepared)
    return prepared


def run_evaluation(prepared, report, ledger, settings):
    from rsi_eval.compact_agent import CompactStatePacketLLM, compact_candidate_tool, run_session
    report['triplet_input_proofs'] = verify_triplets(prepared)
    stop = None
    for controller,directory,entry in prepared:
        if budget_blocked(ledger.summary()):
            stop = 'budget_or_unknown_usage'
        if stop:
            entry.update(status='not_started_after_stop',stop_reason=stop,endpoint=summarize_endpoint(controller))
            write_json(directory/'session-summary.json',entry)
            continue
        try:
            llm = CompactStatePacketLLM(**settings).bind_controller(controller).bind_pilot(
                ledger,entry['session_id'],directory/'requests')
            raw = run_session(controller,llm,entry['session_id'],directory,
                              tool_factory=compact_candidate_tool,max_iterations=1)
            entry.update(raw)
            endpoint = summarize_endpoint(controller)
            entry['endpoint'] = endpoint
            entry['step_status'] = ('candidate_evaluated' if endpoint['child_metrics'] is not None else
                'candidate_without_score' if endpoint['generated_candidates_executed'] else 'no_candidate')
            known_contract = bool({'IncompleteToolResponseError','PilotResponseContractError'} &
                                  {raw.get('cause_type'),raw.get('model_error_type')})
            if controller.halted:
                stop = 'controller_infrastructure_error'
            elif (raw.get('status')=='error' or raw.get('model_error_type')) and not known_contract:
                stop = 'session_error'
        except Exception as error:
            entry.update(status='error',model_error_type=type(error).__name__,endpoint=summarize_endpoint(controller))
            stop = 'session_error'
        write_json(directory/'session-summary.json',entry)
        report['budget'] = ledger.summary()
        if budget_blocked(report['budget']):
            stop = 'budget_or_unknown_usage'
        write_json(directory.parent/'summary.json',report)
    if stop:
        report['stop_reason'] = stop
    report['status'] = 'stopped' if stop else 'attempts_completed'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-id',required=True)
    parser.add_argument('--config',type=Path,default=ROOT/CONFIG_PATH)
    phases = parser.add_mutually_exclusive_group(required=True)
    phases.add_argument('--prepare-only',action='store_true')
    phases.add_argument('--update',action='store_true')
    phases.add_argument('--evaluate',action='store_true')
    parser.add_argument('--auth-file')
    args = parser.parse_args(argv)
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}',args.run_id):
        parser.error('run-id must be a short safe identifier')
    mode = 'evaluate' if args.evaluate else 'update' if args.update else 'prepare_only'
    report = {'run_id':args.run_id,'mode':mode,'status':'error','sessions':[],
              'sealed_test_evaluations':0,'baseline_reexecutions':0,'automatic_recovery_enabled':False}
    output = ledger = None
    old_disable = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
            from rsi_eval.policy_cases import load_update_bundle,load_evaluation_states
            from rsi_eval.revision_policy import S0,PolicyUpdateController,freeze_policy,load_frozen_policy
            from rsi_eval.pilot_budget import BudgetLedger
            from scripts.run_checked_feedback import _base_sessions,_model_configuration
            from scripts.configure_minimax import CONFIG,auth_path,read_key
            parent = ROOT/'runs/policy-transfer'
            if (ROOT/'runs').is_symlink() or parent.is_symlink() or not parent.resolve().is_relative_to(ROOT.resolve()):
                raise ValueError('Output must remain inside project')
            candidate_output = parent/args.run_id
            raw = args.config.read_bytes()
            config = json.loads(raw)
            order,budgets = validate_config(config)
            bundle = load_update_bundle(ROOT)
            states = {s['state_id']:s for s in load_evaluation_states(ROOT)}
            base = json.loads(asset(config['base_config'],'configs').read_bytes())
            sessions = _base_sessions(base)
            model_path = asset(base['model_configuration'],'configs')
            if Path(CONFIG).resolve() != model_path:
                raise ValueError('Ambient model override is not authorized')
            model_hash,public,effective = _model_configuration(model_path,budgets)
            provenance = source_provenance()
            if provenance['sdk_version'] != '1.55.1':
                raise RuntimeError('Policy comparison requires OpenHands SDK 1.55.1')
            identity = dict(config_sha256=hashlib.sha256(raw).hexdigest(),model_config_sha256=model_hash,
                model_config=public,effective_model_config=effective,**provenance)
            if args.evaluate:
                if candidate_output.is_symlink() or not candidate_output.is_dir():
                    raise ValueError('Evaluation requires a completed policy update run')
                previous = json.loads((candidate_output/'summary.json').read_bytes())
                if previous.get('status') != 'policy_frozen' or previous.get('mode') != 'update':
                    raise ValueError('Evaluation cannot restart or follow an incomplete update')
                if any(previous.get(k)!=v for k,v in identity.items()):
                    raise ValueError('Code, model, or config changed between phases')
                if json.loads((candidate_output/'update-bundle.json').read_bytes()) != bundle:
                    raise ValueError('Update evidence changed between phases')
                if json.loads((candidate_output/'policy-S0.json').read_bytes()) != S0:
                    raise ValueError('Parent policy changed between phases')
                selected = load_frozen_policy(candidate_output/'policy_update',bundle,S0)
                request_id = update_request_id(json.loads((candidate_output/'budget-ledger.json').read_bytes()))
                freeze = json.loads((candidate_output/'policy_update/freeze.json').read_bytes())
                if (freeze['request_id'] != request_id or previous.get('freeze') != freeze
                        or previous.get('selected_policy') != selected
                        or previous.get('freeze_file_sha256') != hashlib.sha256(
                            (candidate_output/'policy_update/freeze.json').read_bytes()).hexdigest()):
                    raise ValueError('Frozen policy request identity differs from ledger')
                exclusive_json(candidate_output/'evaluation-started.json',{'mode':mode,'freeze_sha256':
                    hashlib.sha256((candidate_output/'policy_update/freeze.json').read_bytes()).hexdigest()})
                output = candidate_output  # Never rewrite prior summary if phase gate failed.
                report = dict(previous,mode=mode,status='evaluating')
            else:
                candidate_output.mkdir(parents=True,exist_ok=False)
                output = candidate_output
                report.update(identity)
                report['sessions'] = [dict(e,status='not_started') for e in order]
                write_json(output/'config.json',config)
                write_json(output/'base-config.json',base)
                write_json(output/'policy-S0.json',S0)
                write_json(output/'update-bundle.json',bundle)
            ledger = BudgetLedger(output/'budget-ledger.json',
                session_ids=['policy_update']+[e['session_id'] for e in order],**budgets)
            if budget_blocked(ledger.summary()):
                raise ValueError('Unsettled budget prohibits another phase')
            if args.prepare_only:
                updater = PolicyUpdateController(bundle,S0,output/'policy_update')
                write_json(output/'policy_update/task-packet.json',updater.state_packet())
                fixture = {'version':'revision-policy-v0.1','rule_ids':['R01','R02','R05','R07']}
                report['synthetic_policy_fixture'] = fixture
                prepare_evaluation(output,report,config,sessions,states,bundle,fixture)
                report['status'] = 'prepared'
            elif args.update:
                from rsi_eval.policy_agent import PolicyStatePacketLLM,run_policy_session
                updater = PolicyUpdateController(bundle,S0,output/'policy_update')
                write_json(output/'policy_update/task-packet.json',updater.state_packet())
                # Structural checks and case hashes have passed before credential access.
                settings = dict(effective,api_key=read_key(auth_path(args.auth_file)))
                llm = PolicyStatePacketLLM(**settings).bind_controller(updater).bind_pilot(
                    ledger,'policy_update',output/'policy_update/requests')
                raw_update = run_policy_session(updater,llm,'policy_update',output/'policy_update')
                report['policy_update'] = raw_update
                if (updater.halted or updater.policy is None or budget_blocked(ledger.summary())
                        or raw_update.get('status') == 'error' or raw_update.get('model_error_type')):
                    report['status'] = 'update_not_frozen'
                else:
                    request_id = update_request_id(json.loads((output/'budget-ledger.json').read_bytes()))
                    report['freeze'] = freeze_policy(output/'policy_update',bundle,S0,request_id)
                    report['freeze_file_sha256'] = hashlib.sha256((output/'policy_update/freeze.json').read_bytes()).hexdigest()
                    report['selected_policy'] = updater.policy
                    report['strategy_changed'] = updater.policy != S0
                    report['status'] = 'policy_frozen'
            else:
                frozen_bytes = (output/'policy_update/freeze.json').read_bytes()
                def guard():
                    if ((output/'policy_update/freeze.json').read_bytes()!=frozen_bytes
                            or load_frozen_policy(output/'policy_update',bundle,S0)!=selected):
                        raise ValueError('Frozen policy changed during evaluation')
                prepared = prepare_evaluation(output,report,config,sessions,states,bundle,selected,guard)
                settings = dict(effective,api_key=read_key(auth_path(args.auth_file)))
                run_evaluation(prepared,report,ledger,settings)
    except Exception as error:
        report.update(status='error',error_type=type(error).__name__)
    finally:
        logging.disable(old_disable)
    if ledger is not None:
        report['budget'] = ledger.summary()
    if output is not None:
        write_json(output/'summary.json',report)
    print(json.dumps({k:report.get(k) for k in ('run_id','mode','status','error_type','strategy_changed','budget')},indent=2))
    return 0 if report['status'] in ('prepared','policy_frozen','attempts_completed') else 1


if __name__ == '__main__':
    raise SystemExit(main())
