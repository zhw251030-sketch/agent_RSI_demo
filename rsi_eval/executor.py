"""Trusted development controller. Candidate code is executed only by sandbox."""
import hashlib
import json
import math
from pathlib import Path
import time
import uuid

from . import planning, symbolic
from .sandbox import run_candidate

ROOT = Path(__file__).resolve().parents[1]
LIMITS = dict(timeout_seconds=20, memory_mb=2048, cpu_seconds=10,
              max_output_bytes=2_000_000)


def evaluate_candidate(family, task_id, source, *, root=ROOT, n_params=3,
                       candidate_id=None, parent_id=None, strategy_version='unversioned'):
    """Return and journal one development evaluation; never read official tests.

    The root and source file access belong to the trusted caller. A future Agent
    tool should expose source text/task identity only, not root or shell access.
    """
    root = Path(root).resolve()
    started = time.monotonic()
    run_id = uuid.uuid4().hex
    if not isinstance(source, str) or len(source.encode('utf-8')) > 65536:
        return {'status': 'invalid_request', 'error_kind': 'source_size_or_type'}
    digest = hashlib.sha256(source.encode('utf-8')).hexdigest()
    result = dict(schema_version='0.1', run_id=run_id, family=family,
                  task_id=task_id, candidate_id=candidate_id or digest,
                  candidate_hash=digest, parent_id=parent_id,
                  strategy_version=strategy_version,
                  feedback_role='development_only', limits=dict(LIMITS),
                  model_calls=0, sealed_tasks_executed=0, executions=[])

    def finish(values):
        result.update(values)
        result['elapsed_seconds'] = round(time.monotonic() - started, 6)
        directory = root / 'runs/executor_feedback'
        directory.mkdir(parents=True, exist_ok=True)
        candidates = root / 'runs/candidates'
        candidates.mkdir(parents=True, exist_ok=True)
        (candidates / (digest + '.py')).write_text(source, encoding='utf-8')
        (directory / (run_id + '.json')).write_text(
            json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
        return result

    if family not in ('planning', 'symbolic') or not isinstance(task_id, str):
        return finish({'status': 'invalid_request', 'error_kind': 'unsupported_task_family'})
    if family == 'symbolic' and (type(n_params) is not int or not 0 <= n_params <= 16):
        return finish({'status': 'invalid_request', 'error_kind': 'parameter_count'})
    try:
        task = (planning if family == 'planning' else symbolic).prepare_task(task_id, root)
    except (PermissionError, ValueError, KeyError, TypeError) as exc:
        return finish({'status': 'invalid_request', 'error_kind': 'task_contract_rejected',
                       'public_diagnostic': type(exc).__name__})
    except OSError:
        return finish({'status': 'infrastructure_error', 'error_kind': 'task_data_unavailable'})

    def execute(request):
        response = run_candidate(source, request, deps_dir=root / '.task-runtime/python', **LIMITS)
        result['executions'].append({
            'phase': request.get('phase', 'plan'),
            **{k: v for k, v in response.items() if k not in ('result', 'stderr', 'stdout')},
        })
        if response.get('status') != 'completed':
            return None, {'status': response.get('status', 'infrastructure_error'),
                          'error_kind': response.get('error_kind', response.get('reason', 'sandbox_execution_failed'))}
        payload = response.get('result')
        if not isinstance(payload, dict) or payload.get('status') not in ('success', 'ok'):
            payload = payload if isinstance(payload, dict) else {}
            error = {'status': 'candidate_error', 'error_kind': 'invalid_worker_result'}
            for name, value in [('error_kind', payload.get('error', payload.get('error_kind'))),
                                ('exception_type', payload.get('exception_type'))]:
                if isinstance(value, str) and len(value) <= 128:
                    error[name] = value
            line = payload.get('candidate_line')
            if type(line) is int and 1 <= line <= 100000:
                error['candidate_line'] = line
            return None, error
        return payload, None

    if family == 'planning':
        payload, error = execute(task)
        if error:
            return finish(error)
        try:
            return finish(planning.validate_plan(task_id, payload.get('plan'), root))
        except (OSError, ValueError, KeyError, TypeError):
            return finish({'status': 'infrastructure_error', 'error_kind': 'plan_validation_failed'})

    payload, error = execute({**task, 'phase': 'fit', 'n_params': n_params})
    if error:
        return finish(error)
    params = payload.get('params')
    if (not isinstance(params, list) or len(params) != n_params
            or any(type(v) not in (float, int) for v in params)):
        return finish({'status': 'candidate_error', 'error_kind': 'invalid_fitted_parameters'})
    try:
        params = [float(v) for v in params]
    except (OverflowError, ValueError, TypeError):
        return finish({'status': 'candidate_error', 'error_kind': 'invalid_fitted_parameters'})
    if not all(math.isfinite(v) for v in params):
        return finish({'status': 'candidate_error', 'error_kind': 'invalid_fitted_parameters'})
    if (payload.get('converged') is not True or type(payload.get('nfev')) is not int
            or not 1 <= payload['nfev'] <= 100
            or type(payload.get('candidate_calls')) is not int
            or not 1 <= payload['candidate_calls'] <= 100000):
        return finish({'status': 'candidate_error', 'error_kind': 'invalid_fit_metadata'})
    result['fitting'] = {'params': params, 'n_params': n_params,
                         'nfev': payload.get('nfev'), 'converged': payload.get('converged'),
                         'candidate_calls': payload.get('candidate_calls'),
                         'split': 'train', 'max_nfev': 100}
    # This is a fresh process. In particular, no labels or optimizer state cross.
    prediction_request = {k: v for k, v in task.items() if k != 'y'}
    payload, error = execute({**prediction_request, 'phase': 'predict', 'params': params})
    if error:
        return finish(error)
    score = symbolic.score_predictions(task['y'], payload.get('predictions'))
    if 'error' in score:
        score['error_kind'] = score.pop('error')
    score['metric_split'] = 'train'
    score['metric_scope'] = 'Training fit only; not a held-out or generalization result.'
    return finish(score)
