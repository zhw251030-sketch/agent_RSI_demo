"""Real sandbox/VAL calibration on tiny synthetic tasks, never benchmark data.

Set RSI_ROLE_CALIBRATION_DIR to a new directory to retain all four journals.
The only patched production boundary is the pinned metadata loader, because a
synthetic fixture intentionally has different hashes from the benchmark.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

from rsi_eval import role_executor
from tests.test_planning import DOMAIN, PROBLEM


ROOT = Path(__file__).resolve().parents[1]
P_TASK = 'spannerlearning/seed1/problem0'


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def run_calibration(output_root, runtime_root=ROOT):
    """Create four manual calibration records; real isolation, fit and VAL."""
    output_root = Path(output_root).absolute()
    runtime_root = Path(runtime_root).absolute()
    output_root.mkdir(parents=True, exist_ok=False)
    domain_path = output_root / 'data/planning/spanner/spannerlearning.pddl'
    domain_path.parent.mkdir(parents=True)
    domain_path.write_bytes(DOMAIN.encode())
    problem = PROBLEM.replace('(and (tightened nut1))', '(and (at bob gate))').encode()
    problem_relative = 'data/planning/spanner/' + P_TASK + '.pddl'
    problem_path = output_root / problem_relative
    problem_path.parent.mkdir(parents=True)
    problem_path.write_bytes(problem)
    csv_raw = b't,x,v,a\n0,0,0,1\n1,0,0,3\n2,0,0,5\n3,0,0,7\n'
    csv_relative = 'data/symbolic/llm-sr/oscillator2/train.csv'
    csv_path = output_root / csv_relative
    csv_path.parent.mkdir(parents=True)
    csv_path.write_bytes(csv_raw)
    manifest = dict(planning=dict(domain_sha256=_sha(DOMAIN.encode()), tasks=[
        dict(task_id=P_TASK, role='selection', data_path=problem_relative, sha256=_sha(problem))]),
        symbolic=dict(files=[dict(task_id='oscillator2', role='selection', split='train',
            columns=['t', 'x', 'v', 'a'], bytes=len(csv_raw), rows=4,
            data_path=csv_relative, sha256=_sha(csv_raw))]))
    manifest_raw = (json.dumps(manifest, ensure_ascii=False, indent=2) + '\n').encode()
    (output_root / 'synthetic-manifest.json').write_bytes(manifest_raw)
    val_relative = 'vendor/llm-genplan/' + role_executor.planning.VAL_DIRECTORY
    val_dir = output_root / val_relative
    val_dir.mkdir(parents=True)
    for name, expected in role_executor.planning.VAL_HASHES.items():
        source = runtime_root / val_relative / name
        if _sha(source.read_bytes()) != expected:
            raise ValueError('Calibration requires the existing pinned VAL runtime')
        shutil.copy2(source, val_dir / name)
    # This is only a test runtime mount. Candidate input/data paths remain
    # ordinary nonsymlink files; sandbox resolves and mounts deps read-only.
    dependencies = runtime_root / '.task-runtime/python'
    if not dependencies.is_dir():
        raise ValueError('Calibration requires existing isolated task dependencies')
    (output_root / '.task-runtime').mkdir()
    (output_root / '.task-runtime/python').symlink_to(dependencies, target_is_directory=True)
    sources = {
        'planning_valid': 'def get_plan(objects, init, goal):\n    return ["(walk shed gate bob)"]\n',
        'planning_invalid': 'def get_plan(objects, init, goal):\n    return []\n',
        'symbolic_linear': 'def equation(t, x, v, params):\n    return params[0] * t + params[1]\n',
        'symbolic_constant': 'def equation(t, x, v, params):\n    return params[0] + 0 * t\n',
    }
    records = {}
    with patch.object(role_executor, '_load_partition', return_value=(manifest, _sha(manifest_raw))):
        executor = role_executor.RoleExecutor(output_root, role='selection')
        for name, source in sources.items():
            planning_task = name.startswith('planning')
            records[name] = executor.evaluate('planning' if planning_task else 'symbolic',
                P_TASK if planning_task else 'oscillator2', source,
                n_params=0 if planning_task else (2 if name.endswith('linear') else 1),
                candidate_id=name, strategy_version='manual-calibration')
    if records['planning_valid']['status'] != 'success':
        raise AssertionError(records['planning_valid'])
    if records['planning_invalid']['status'] != 'task_failure':
        raise AssertionError(records['planning_invalid'])
    for name in ('symbolic_linear', 'symbolic_constant'):
        if records[name]['status'] != 'success':
            raise AssertionError(records[name])
    if records['symbolic_linear']['metrics']['nmse'] > 1e-12:
        raise AssertionError('Synthetic linear model did not recover y = 2t + 1')
    if abs(records['symbolic_constant']['metrics']['nmse'] - 1.0) > 1e-12:
        raise AssertionError('Synthetic constant did not obtain NMSE = 1')
    report = dict(version='role-executor-calibration-v0.1', status='passed',
                  evidence_kind='synthetic', model_calls=0, benchmark_candidate_executions=0,
                  sealed_tasks_executed=0, manual_candidate_evaluations=4,
                  sandbox_executions=sum(len(r['executions']) for r in records.values()),
                  val_calls=sum('validator' in r for r in records.values()),
                  records={name: dict(path=r['journal_path'],
                      sha256=_sha((output_root / r['journal_path']).read_bytes()),
                      status=r['status'], metrics=r.get('metrics')) for name, r in records.items()})
    (output_root / 'calibration-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return report


@unittest.skipUnless(sys.platform == 'linux' and shutil.which('bwrap') and
                     (ROOT / '.task-runtime/python').is_dir(),
                     'Real calibration needs the existing Linux sandbox and isolated task runtime')
class RoleExecutorIntegrationTests(unittest.TestCase):
    def test_manual_synthetic_planning_and_symbolic_measurements(self):
        destination = os.environ.get('RSI_ROLE_CALIBRATION_DIR')
        if destination:
            report = run_calibration(destination)
        else:
            with tempfile.TemporaryDirectory() as temporary:
                report = run_calibration(Path(temporary) / 'calibration')
        self.assertEqual(report['sandbox_executions'], 6)
        self.assertEqual(report['val_calls'], 2)
        self.assertEqual(report['benchmark_candidate_executions'], 0)


if __name__ == '__main__':
    unittest.main()
