#!/usr/bin/env python3
"""Freeze offline strategy inputs; never execute candidates or call a provider.

The output explicitly remains non-runnable until a separate bounded SDK
orchestrator is implemented and tested against these interfaces.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rsi_eval.strategy_learning import build_learning_package, render_update_packet
from rsi_eval.strategy_partition import read_json, safe_path, validate_manifest
from scripts.analyze_state_generation_v02 import audit as audit_sources

VERSION = 'strategy-interface-preparation-v0.1'
GENERATION = 'artifacts/state-generation/2026-10-21/v02'
GENERATION_FREEZE = 'f37695fa966f2e44027cc1b93d66a05f04d406e2b0b2f6808d73517c90d5004c'
ALLOCATION = 'configs/pilots/strategy-pair-allocation-v0.1.json'
PARTITION = 'configs/tasks/strategy-partition-v0.1.json'
PROTOCOL = 'docs/protocols/2026-10-21-strategy-interface-v0.1.md'


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
                      separators=(',', ':')).encode('utf-8')


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _runtime(root):
    names = subprocess.check_output(['git', '-C', str(root), 'ls-files', '-z',
        '--cached', '--others', '--exclude-standard', '--',
        'rsi_eval', 'scripts', 'configs', 'prompts', 'fixtures', 'tests', 'docs/protocols'])
    paths = sorted({x for x in names.decode('utf-8').split('\0') if x
                    and Path(x).suffix in ('.py', '.json', '.md', '.txt')})
    required = {'rsi_eval/role_executor.py', 'rsi_eval/strategy_binding.py',
                'rsi_eval/strategy_learning.py', 'scripts/prepare_strategy_pair.py', PROTOCOL}
    if not required <= set(paths):
        raise ValueError('Strategy interface runtime incomplete')
    return {name: sha(safe_path(root, name).read_bytes()) for name in paths}


def build_preparation(root):
    root = Path(root).resolve()
    if platform.python_version() != '3.12.14':
        raise ValueError('Frozen AST audit requires Python 3.12.14')
    source_audit = audit_sources(root, safe_path(root, GENERATION))
    if source_audit['status'] != 'passed' or source_audit['accepted_sources'] != 8:
        raise ValueError('All eight frozen sources must remain available')
    freeze_raw = safe_path(root, GENERATION+'/source-freeze.json').read_bytes()
    if sha(freeze_raw) != GENERATION_FREEZE:
        raise ValueError('Unexpected source batch')
    allocation = read_json(root, ALLOCATION)
    partition = read_json(root, PARTITION)
    roles = validate_manifest(root, partition, verify_data=False)
    if (allocation['execution_ready'] is not False or allocation['future_request_cap'] != 36
            or allocation['task_partition_sha256'] != sha(safe_path(root, PARTITION).read_bytes())):
        raise ValueError('Frozen future allocation changed')
    slots = allocation['slots']
    counts = dict(Counter(x['phase'] for x in slots))
    if len(slots) != 36 or counts != dict(update=4, selection=16, evaluation=16):
        raise ValueError('Future allocation incomplete')
    initial_states = []
    for slot in json.loads(freeze_raw)['slots']:
        if slot['disposition'] != 'available' or slot['candidate']['status'] != 'stored_unexecuted':
            raise ValueError('Source not stored')
        path = GENERATION+'/sessions/'+slot['id']+'/source.py'
        source = safe_path(root, path).read_bytes()
        candidate = slot['candidate']
        if sha(source) != candidate['source_sha256']:
            raise ValueError('Frozen source differs')
        initial_states.append(dict(state_id=slot['id'], family=slot['family'], role=slot['role'],
            task_ids=slot['task_ids'], source_path=path, source_sha256=sha(source),
            n_params=candidate['n_params']))
    package = build_learning_package(root)
    packet = render_update_packet(root, package)
    runtime = _runtime(root)
    report = dict(version=VERSION, execution_ready=False,
        source_batch_sha256=GENERATION_FREEZE, initial_states=initial_states,
        future_allocation_sha256=sha(safe_path(root, ALLOCATION).read_bytes()),
        future_slot_counts=counts, future_request_cap=36, future_reserved_cost_cap_cny=12,
        learning_package_sha256=sha(canonical(package)), update_packet_sha256=sha(canonical(packet)),
        update_packet_bytes=len(canonical(packet)), renderer_packet_limit_bytes=81920,
        runtime_files_sha256=runtime, runtime_sha256=sha(canonical(runtime)),
        phase_order=allocation['freeze_order'],
        completed_interfaces=['role-scoped task execution', 'pinned historical learning package',
            'update and actor packet rendering', 'raw-record binding to paired selection',
            'both-replicate decision replay and evaluation gate'],
        remaining_before_live_run=['bounded SDK controller for the new learning package and actor packets',
            'actual SDK dispatch/response and submission audit',
            'phase scheduler binding baseline feedback, per-session budgets and stop conditions',
            'full 36-slot fake-provider integration and clean pre-request runtime freeze'],
        activity=dict(model_requests=0, candidate_executions=0, task_evaluations=0,
                      strategy_updates=0, sealed_tasks_executed=0),
        evidence_boundary='Offline preparation only. No fabricated baseline, selected strategy or task score.')
    return {'preparation.json': report, 'learning-package.json': package,
            'update-packet.json': packet, 'future-allocation.json': allocation,
            'source-audit.json': source_audit, 'role-metadata-audit.json': roles}


def write_preparation(output, documents):
    output = Path(output).absolute()
    for path in (output, *output.parents):
        if path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction()):
            raise ValueError('Symlinked output refused')
    output.mkdir(parents=True, exist_ok=False)
    files = {}
    for name, value in documents.items():
        path = safe_path(output, name)
        raw = canonical(value)+b'\n'
        with path.open('xb') as stream:
            stream.write(raw)
        files[name] = sha(raw)
    manifest = dict(version=VERSION, files=files, activity=documents['preparation.json']['activity'])
    with (output/'manifest.json').open('xb') as stream:
        stream.write(canonical(manifest)+b'\n')


def verify_preparation(root, output):
    output = Path(output)
    manifest = read_json(output, 'manifest.json')
    expected = build_preparation(root)
    if (manifest['version'] != VERSION or set(manifest['files']) != set(expected)
            or {p.name for p in output.iterdir()} != set(expected)|{'manifest.json'}):
        raise ValueError('Preparation file set differs')
    for name, document in expected.items():
        raw = safe_path(output, name).read_bytes()
        if sha(raw) != manifest['files'][name] or raw != canonical(document)+b'\n':
            raise ValueError('Preparation content changed: '+name)
    if manifest['activity'] != expected['preparation.json']['activity']:
        raise ValueError('Preparation activity changed')
    return dict(status='passed', version=VERSION, execution_ready=False,
                manifest_sha256=sha(safe_path(output, 'manifest.json').read_bytes()),
                files_verified=len(expected), update_packet_bytes=expected['preparation.json']['update_packet_bytes'],
                runtime_files=len(expected['preparation.json']['runtime_files_sha256']),
                activity=manifest['activity'])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    parser.add_argument('--verify', action='store_true')
    args = parser.parse_args(argv)
    output = safe_path(ROOT, args.output)
    if not args.verify:
        dirty = subprocess.check_output(['git', '-C', str(ROOT), 'status', '--porcelain'])
        if dirty.strip():
            raise ValueError('Commit verified interfaces before creating a preparation freeze')
        write_preparation(output, build_preparation(ROOT))
    result = verify_preparation(ROOT, output)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
