#!/usr/bin/env python3
"""One-request paired development repairs; immutable archived starting states."""
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
DEFAULT_CONFIG = ROOT/'configs/pilots/paired-repair-v0.1.json'
PROTOCOL = 'docs/protocols/2026-10-20-paired-repair-v0.1.md'
POLICY = 'prompts/paired/policy.md'
CHECK_FIELDS = ('checks_visible', 'audits', 'frozen_history_checks')


def canonical(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True,
                      separators=(',', ':')).encode('utf-8')


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2)+'\n',
                          encoding='utf-8')


def expected_order():
    order = []
    for repeat in (1, 2):
        sequence = [('P1', 'hidden'), ('S1', 'checked'), ('P1', 'checked'), ('S1', 'hidden')]
        if repeat == 2:
            sequence.reverse()
        for state, condition in sequence:
            pair = state+'-r'+str(repeat)
            order.append(dict(state_id=state, family='planning' if state == 'P1' else 'symbolic',
                              condition=condition, repeat=repeat, pair_id=pair,
                              session_id=pair+'-'+condition))
    return order


def validate_config(config):
    from rsi_eval.repair_states import PINNED_STATES
    if (type(config) is not dict or config.get('schema_version') != '0.1'
            or config.get('base_config') != 'configs/pilots/development-v0.1.json'
            or config.get('policy_file') != POLICY or config.get('protocol') != PROTOCOL
            or config.get('states') != PINNED_STATES or config.get('order') != expected_order()):
        raise ValueError('Paired protocol identity or archived states changed')
    for key, value in [('max_iterations', 1), ('max_generated_candidates', 1), ('source_limit_bytes', 16384)]:
        if type(config.get(key)) is not int or config[key] != value:
            raise ValueError('Paired protocol requires one request and one candidate')
    for key in ('strategy_updated', 'checks_gate_execution', 'checks_change_selection', 'automatic_recovery',
                'baseline_reexecution'):
        if config.get(key) is not False:
            raise ValueError('Paired protocol must keep strategy, scoring and recovery fixed')
    if config.get('missing_candidate_score') is not None:
        raise ValueError('Missing candidates cannot be assigned a score')
    caps = dict(max_requests=8, max_requests_per_session=1, max_output_tokens=4096,
                max_input_bytes=98304, max_reserved_tokens=1500000)
    budgets = config.get('budgets')
    prices = {'max_cost_cny', 'input_cny_per_million', 'output_cny_per_million'}
    if type(budgets) is not dict or set(budgets) != set(caps)|prices:
        raise ValueError('Unexpected paired budgets')
    for key, cap in caps.items():
        if type(budgets[key]) is not int or not 0 < budgets[key] <= cap:
            raise ValueError('Paired budget outside authorized bound')
    for key in prices:
        if type(budgets[key]) not in (int, float) or not math.isfinite(budgets[key]) or budgets[key] <= 0:
            raise ValueError('Invalid cost bound')
    if budgets['max_cost_cny'] > 5 or budgets['input_cny_per_million'] < 2.1 or budgets['output_cny_per_million'] < 8.4:
        raise ValueError('Cost cap or configured conservative prices changed')
    return copy.deepcopy(config['order']), copy.deepcopy(budgets)


def common_packet(packet):
    value = copy.deepcopy(packet)
    for key in CHECK_FIELDS:
        value.pop(key, None)
    return value


def verify_pairs(prepared):
    groups = {}
    for controller, _, entry in prepared:
        groups.setdefault(entry['pair_id'], []).append((controller, entry))
    proofs = {}
    for pair, group in groups.items():
        if len(group) != 2 or {e['condition'] for _, e in group} != {'hidden', 'checked'}:
            raise ValueError('Every pair requires both distinct conditions')
        packets = [canonical(common_packet(c.state_packet())) for c, _ in group]
        if packets[0] != packets[1]:
            raise ValueError('Paired common inputs differ')
        starts = [c.records[0] for c, _ in group]
        if len({(r['source_sha256'], r['n_params']) for r in starts}) != 1:
            raise ValueError('Paired baseline source or parameter count differs')
        proofs[pair] = dict(common_sha256=hashlib.sha256(packets[0]).hexdigest(),
                            common_bytes=len(packets[0]), source_sha256=starts[0]['source_sha256'],
                            n_params=starts[0]['n_params'])
    if not proofs:
        raise ValueError('No paired initial states')
    return proofs


def summarize_endpoint(controller):
    records = controller.records
    children = records[1:]
    if len(children) > 1:
        raise ValueError('Single-step session generated multiple candidates')
    result = dict(generated_candidates_executed=len(children),
                  actual_task_executions=sum(len(r.get('results', [])) for r in children),
                  archived_task_records=len(records[0].get('results', [])),
                  baseline_metrics=copy.deepcopy(records[0]['metrics']),
                  child_metrics=None, improvement=None, submitted_and_improved=False)
    if not children or children[0].get('status') != 'evaluated':
        return result
    child = children[0]
    if (not child.get('results')
            or len(child['results']) != len(records[0].get('results', []))):
        return result
    key = 'total_successes' if controller.family == 'planning' else 'nmse'
    before, after = records[0]['metrics'].get(key), child.get('metrics', {}).get(key)
    if (type(before) not in (int, float) or type(after) not in (int, float)
            or not math.isfinite(before) or not math.isfinite(after)):
        return result
    # A failed symbolic prediction cannot acquire a score from an incidental metric.
    if controller.family == 'symbolic' and any(r.get('status') != 'success' for r in child.get('results', [])):
        return result
    delta = after-before if controller.family == 'planning' else before-after
    result.update(child_metrics=copy.deepcopy(child['metrics']), improvement=delta,
                  submitted_and_improved=delta > 1e-12)
    return result


def _run_prepared(controllers, report, ledger, model_config, auth_file):
    from rsi_eval.compact_agent import CompactStatePacketLLM, compact_candidate_tool, run_session
    from scripts.configure_minimax import auth_path, read_key
    # Defense in depth: caller cannot skip the equality gate before credential access.
    report['pair_input_proofs'] = verify_pairs(controllers)
    settings = dict(model_config, api_key=read_key(auth_path(auth_file)))
    stop = None
    for controller, directory, entry in controllers:
        budget = ledger.summary()
        if budget['halted'] or budget['usage_unknown_count'] or budget['reserved_count']:
            stop = 'budget_or_unknown_usage'
        if stop:
            entry.update(status='not_started_after_stop', stop_reason=stop,
                         endpoint=summarize_endpoint(controller))
            write_json(directory/'session-summary.json', entry)
            continue
        try:
            llm = CompactStatePacketLLM(**settings).bind_controller(controller).bind_pilot(
                ledger, entry['session_id'], directory/'requests')
            raw = run_session(controller, llm, entry['session_id'], directory,
                              tool_factory=compact_candidate_tool, max_iterations=1)
            entry.update(raw)
            endpoint = summarize_endpoint(controller)
            entry['endpoint'] = endpoint
            entry['step_status'] = ('candidate_evaluated' if endpoint['child_metrics'] is not None
                                     else 'candidate_without_score' if endpoint['generated_candidates_executed']
                                     else 'no_candidate')
            known_contract = 'IncompleteToolResponseError' in (raw.get('cause_type'), raw.get('model_error_type'))
            if controller.halted:
                stop = 'controller_infrastructure_error'
            elif (raw.get('status') == 'error' or raw.get('model_error_type')) and not known_contract:
                stop = 'session_error'
        except Exception as error:
            entry.update(status='error', model_error_type=type(error).__name__,
                         endpoint=summarize_endpoint(controller))
            stop = 'session_error'
        write_json(directory/'session-summary.json', entry)
        report['budget'] = ledger.summary()
        if (report['budget']['halted'] or report['budget']['usage_unknown_count']
                or report['budget']['reserved_count']):
            stop = 'budget_or_unknown_usage'
        write_json(directory.parent/'summary.json', report)
    if stop:
        report['stop_reason'] = stop
    report['status'] = 'stopped' if stop else 'attempts_completed'


def asset(relative, prefix):
    path = (ROOT/relative).resolve()
    if not path.is_relative_to(ROOT.resolve()/prefix) or not path.is_file():
        raise ValueError('Trusted asset outside allowed project directory')
    return path


def source_provenance():
    paths = [p for part in ('rsi_eval', 'scripts', 'configs', 'prompts', 'fixtures')
             for p in (ROOT/part).rglob('*') if p.is_file() and p.suffix in ('.py', '.json', '.md')]
    paths.append(ROOT/PROTOCOL)
    return dict(code_commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
                sdk_version=importlib.metadata.version('openhands-sdk'),
                source_sha256={p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                               for p in sorted(paths)})


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=DEFAULT_CONFIG)
    parser.add_argument('--run-id', required=True)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--prepare-only', action='store_true')
    group.add_argument('--execute', action='store_true')
    parser.add_argument('--auth-file')
    args = parser.parse_args(argv)
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}', args.run_id):
        parser.error('run-id must be a short safe identifier')
    report = dict(run_id=args.run_id, mode='execute' if args.execute else 'prepare_only',
                  status='error', sessions=[], sealed_test_evaluations=0, strategy_updated=False,
                  baseline_reexecutions=0, automatic_recovery_enabled=False)
    output = ledger = None
    old_disable = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            parent = ROOT/'runs/paired-repair'
            if (ROOT/'runs').is_symlink() or parent.is_symlink() or not parent.resolve().is_relative_to(ROOT.resolve()):
                raise ValueError('Output must remain inside project')
            candidate_output = parent/args.run_id
            candidate_output.mkdir(parents=True, exist_ok=False)
            output = candidate_output
            raw = args.config.read_bytes()
            config = json.loads(raw)
            order, budgets = validate_config(config)
            report['sessions'] = [dict(item, status='not_started') for item in order]
            from rsi_eval.repair_states import load_repair_states
            from rsi_eval.compact_controller import CompactController
            from rsi_eval.pilot_budget import BudgetLedger
            from scripts.run_checked_feedback import _base_sessions, _model_configuration
            from scripts.configure_minimax import CONFIG
            states = {s['state_id']: s for s in load_repair_states(ROOT)}
            base = json.loads(asset(config['base_config'], 'configs').read_bytes())
            sessions = _base_sessions(base)
            model_path = asset(base['model_configuration'], 'configs')
            if Path(CONFIG).resolve() != model_path:
                raise ValueError('Ambient model override is not authorized')
            model_hash, public, effective = _model_configuration(model_path, budgets)
            report.update(config_sha256=hashlib.sha256(raw).hexdigest(), model_config_sha256=model_hash,
                          model_config=public, effective_model_config=effective, **source_provenance())
            if report['sdk_version'] != '1.55.1':
                raise RuntimeError('Paired repair requires SDK 1.55.1')
            write_json(output/'config.json', config)
            write_json(output/'base-config.json', base)
            ledger = BudgetLedger(output/'budget-ledger.json',
                                  session_ids=[x['session_id'] for x in order], **budgets)
            prepared = []
            policy = asset(POLICY, 'prompts/paired').read_text(encoding='utf-8')
            for entry in report['sessions']:
                directory = output/entry['session_id']
                controller = CompactController(ROOT, sessions[entry['family']], directory,
                    condition=entry['condition'], session_id=args.run_id+':'+entry['pair_id'],
                    policy_text=policy, repair_state=states[entry['state_id']])
                baseline = controller.baseline()
                packet = controller.state_packet()
                (directory/'task-prompt.txt').write_bytes(canonical(packet))
                entry.update(status='prepared', baseline_source_sha256=baseline['source_sha256'],
                             baseline_n_params=baseline['n_params'],
                             task_prompt_sha256=hashlib.sha256(canonical(packet)).hexdigest())
                prepared.append((controller, directory, entry))
            report['pair_input_proofs'] = verify_pairs(prepared)
            if args.execute:
                _run_prepared(prepared, report, ledger, effective, args.auth_file)
            else:
                report['status'] = 'prepared'
    except Exception as error:
        report.update(status='error', error_type=type(error).__name__)
    finally:
        logging.disable(old_disable)
    if ledger is not None:
        report['budget'] = ledger.summary()
    if output is not None:
        write_json(output/'summary.json', report)
    print(json.dumps({k: report.get(k) for k in ('run_id', 'status', 'mode', 'error_type', 'budget')}, indent=2))
    return 0 if report['status'] in ('prepared', 'attempts_completed') else 1


if __name__ == '__main__':
    raise SystemExit(main())
