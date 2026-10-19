"""Run hand-authored installation fixtures on allowed development tasks only."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from rsi_eval.executor import evaluate_candidate


def main():
    report = dict(checked_at_utc=datetime.now(timezone.utc).isoformat(),
                  scope='Hand-authored executor acceptance, not LLM/RSI performance.',
                  model_calls=0, agent_rollouts=0, sealed_tasks_executed=0,
                  planning=[], symbolic=[], failure_fixtures=[])
    solver = (ROOT / 'fixtures/planning/collect_then_tighten.py').read_text()
    for index in range(10):
        result = evaluate_candidate('planning', f'spannerlearning/seed0/problem{index}', solver,
                                    strategy_version='manual-acceptance-v0')
        report['planning'].append(result)
    for task, parameters in [('oscillator1', 3), ('oscillator2', 4)]:
        for filename, count in [('linear.py', parameters), ('constant.py', 1)]:
            result = evaluate_candidate('symbolic', task,
                                        (ROOT / 'fixtures/symbolic' / filename).read_text(),
                                        n_params=count, strategy_version='manual-acceptance-v0')
            result['fixture'] = filename
            report['symbolic'].append(result)
    cases = [
        ('empty_plan', 'planning', 'spannerlearning/seed0/problem0',
         (ROOT / 'fixtures/planning/empty_plan.py').read_text(), 0, 'task_failure', 'plan_semantics'),
        ('invalid_shape', 'symbolic', 'oscillator1',
         (ROOT / 'fixtures/symbolic/invalid_shape.py').read_text(), 1, 'candidate_error', 'invalid_shape'),
        ('nonfinite_output', 'symbolic', 'oscillator1',
         (ROOT / 'fixtures/symbolic/nan.py').read_text(), 1, 'candidate_error', 'nonfinite_output'),
        ('sealed_planning_refused', 'planning', 'spannerlearning_test/seed0/problem0', solver,
         0, 'invalid_request', 'task_contract_rejected'),
        ('symbolic_test_refused', 'symbolic', 'oscillator1/test_id', '',
         0, 'invalid_request', 'task_contract_rejected'),
    ]
    for name, family, task, source, count, status, error in cases:
        result = evaluate_candidate(family, task, source, n_params=count,
                                    strategy_version='manual-negative-fixture-v0')
        report['failure_fixtures'].append(dict(name=name, expected_status=status,
            expected_error=error, passed=result['status'] == status and result.get('error_kind') == error,
            observed=result))
    report['passed'] = (all(r['status'] == 'success' for r in report['planning'] + report['symbolic'])
                        and all(r['passed'] for r in report['failure_fixtures']))
    report['source_sha256'] = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
        for folder in ['rsi_eval', 'fixtures'] for p in sorted((ROOT / folder).rglob('*.py'))}
    report['python'] = sys.version.split()[0]
    report['bubblewrap'] = subprocess.check_output(['bwrap', '--version'], text=True).strip()
    directory = ROOT / 'runs/executor-acceptance'
    directory.mkdir(parents=True, exist_ok=True)
    (directory / 'report.json').write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
    print(json.dumps({'passed': report['passed'],
                      'planning_successes': sum(r['status'] == 'success' for r in report['planning']),
                      'symbolic_successes': sum(r['status'] == 'success' for r in report['symbolic']),
                      'negative_checks_passed': sum(r['passed'] for r in report['failure_fixtures']),
                      'model_calls': 0, 'sealed_tasks_executed': 0}))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
