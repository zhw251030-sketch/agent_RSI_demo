"""Host-only fixed-task evaluation and bounded shared parent feedback.

Only the caller controls when load_task runs: the trial controller must freeze
S1 first, load once, and reuse that prepared object for both arms. This module
does not learn or choose a strategy, rank basis terms, or expose individual rows.
The original role executor, basis compiler, isolated fitter and residual helper
remain unchanged.
"""
import json
from pathlib import Path
import re

from rsi_eval.role_executor import RoleExecutor
from rsi_eval.symbolic_diagnostics import summarize_residuals
from extensions.symbolic_basis_v01.contract import compile_submission, make_spec
from extensions.symbolic_basis_v01.executor import (
    canonical, evaluate_submission, sha, validate_request, validate_transition, write,
)


VERSION = 'basis-trial-feedback-v0.1'
TASK_ID = 'oscillator1'
ROLE = 'learning'
SPEC = make_spec(2, 4)
MAX_FEEDBACK_BYTES = 10000


def _validate_prepared(prepared, spec, *, allow_synthetic=False):
    if type(prepared) is not dict or set(prepared) != {'request', 'provenance'}:
        raise ValueError('expected a prepared symbolic role request')
    request, provenance = prepared['request'], prepared['provenance']
    validate_request(request, spec)
    if request.get('task_id') != TASK_ID or request.get('input_names') != ['x', 'v']:
        raise ValueError('trial permits oscillator1 x/v training inputs only')
    expected = {'partition_sha256', 'data_sha256', 'domain_sha256', 'metric_scope'}
    if type(provenance) is not dict:
        raise ValueError('expected original role provenance fields')
    if 'data_kind' in provenance:
        if not allow_synthetic or provenance['data_kind'] != 'synthetic_sdk_preflight':
            raise ValueError('synthetic data require an explicit fake runner')
        expected.add('data_kind')
    if set(provenance) != expected:
        raise ValueError('expected original role provenance fields')
    if provenance['metric_scope'] != 'train' or provenance['domain_sha256'] is not None:
        raise ValueError('training symbolic role provenance required')
    for key in ('partition_sha256', 'data_sha256'):
        if type(provenance[key]) is not str or re.fullmatch('[0-9a-f]{64}', provenance[key]) is None:
            raise ValueError('invalid data/partition hash')
    canonical(prepared)


def load_task(root):
    """Read only the fixed learning-role train data and verify its frozen hash.

    No model-facing override exists. Production callers must retain this return
    value and supply it to evaluate after their strategy-freeze gate has opened.
    """
    prepared = RoleExecutor(Path(root), role=ROLE).prepare_task('symbolic', TASK_ID)
    _validate_prepared(prepared, SPEC)
    return prepared


def evaluate(root, output, payload, spec, parent=None, *, prepared=None, runner=None):
    """One isolated fit/predict, one immutable receipt, no retries or model calls.

    ``parent`` is absent for baselines or exactly {payload, spec} for a child.
    A child keeps all four terms or replaces one term. ``prepared`` is the trusted
    return from load_task. ``runner`` exists for synthetic tests; production leaves
    it unset so the pinned sandbox executes the generated formula.
    """
    if type(spec) is not dict or spec != SPEC:
        raise ValueError('trial requires exactly two inputs and four basis terms')
    compiled = compile_submission(payload, spec)
    parent_payload = parent_spec = None
    mode = 'initial'
    if parent is not None:
        if type(parent) is not dict or set(parent) != {'payload', 'spec'} or parent['spec'] != SPEC:
            raise ValueError('fixed-K parent payload and host specification required')
        parent_payload, parent_spec = parent['payload'], parent['spec']
        mode = 'swap_one'
    validate_transition(payload, spec, parent_payload, parent_spec, mode)
    root, output = Path(root).resolve(), Path(output).resolve()
    if not output.is_relative_to(root) or output == root:
        raise ValueError('output must be inside the project root')
    if output.exists():
        raise FileExistsError('evaluation directory already exists; no resume')
    task = load_task(root) if prepared is None else prepared
    _validate_prepared(task, spec, allow_synthetic=runner is not None)
    result = evaluate_submission(
        payload, spec, request=task['request'], provenance=task['provenance'],
        output=output, parent_payload=parent_payload, parent_spec=parent_spec,
        mode=mode, runner=runner,
    )
    request = task['request']
    residuals = None
    prediction_path = output/'predict.json'
    if prediction_path.exists():
        prediction = json.loads(prediction_path.read_bytes())
        predicted = prediction.get('result', {})
        if prediction.get('status') == 'completed' and predicted.get('status') == 'success':
            residuals = summarize_residuals(
                request['X'], request['y'], predicted.get('predictions'), request['input_names'],
            )
    fit = json.loads((output/'fit.json').read_bytes()).get('result', {})
    coefficients = []
    if result['params'] is not None:
        coefficients = [{'feature_id': feature, 'value': value}
                        for feature, value in zip(compiled['feature_ids'], result['params'])]
    feedback = {
        'version': VERSION, 'family': 'symbolic', 'task_id': TASK_ID,
        'task_role': ROLE, 'metric_scope': 'train', 'status': result['status'],
        'feature_ids': compiled['feature_ids'], 'n_params': compiled['n_params'],
        'nmse': result['metrics']['nmse'] if result['metrics'] is not None else None,
        'coefficients': coefficients, 'residuals': residuals,
        'transition': result['transition'], 'provenance': task['provenance'],
        'fit': {key: fit.get(key) for key in ('converged', 'nfev', 'candidate_calls')},
        'bindings': {
            'source_sha256': compiled['source_sha256'],
            'structural_sha256': compiled['structural_sha256'],
            'prepared_request_sha256': sha(canonical(request)),
            'provenance_sha256': sha(canonical(task['provenance'])),
            'result_sha256': sha((output/'result.json').read_bytes()),
            'fit_sha256': sha((output/'fit.json').read_bytes()),
            'prediction_sha256': sha(prediction_path.read_bytes()) if prediction_path.exists() else None,
        },
        'interpretation': (
            'Residual = prediction minus target. Standardized bias divides by the population '
            'target standard deviation, not a standard error. Four quantile bins per original '
            'input depend only on X. Marginal associations neither identify necessary terms '
            'nor establish causation. No target-dependent basis ranking is supplied. '
            'These are already-seen training measurements, not held-out predictive performance.'
        ),
    }
    if len(canonical(feedback)) > MAX_FEEDBACK_BYTES:
        raise ValueError('bounded feedback exceeded host limit')
    write(output/'feedback.json', feedback)
    receipt = dict(result, feedback=feedback,
                   feedback_sha256=sha((output/'feedback.json').read_bytes()))
    write(output/'receipt.json', receipt)
    return receipt
