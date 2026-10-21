"""Artificial task/provider preflight support, never research measurements.

The fake runner ignores source bytes entirely. Its counters are fabricated
protocol fixtures, not evidence of a fit, optimizer invocation or sandbox run.
"""
from extensions.symbolic_basis_v01.executor import canonical, sha


def synthetic_task():
    """Fresh arrays only; do not load any task file or benchmark value."""
    request = {
        'family': 'symbolic', 'task_id': 'oscillator1', 'input_names': ['x', 'v'],
        'X': [[-2., 0.], [-1., 1.], [1., 0.], [2., 1.]], 'y': [1., 2., 3., 4.],
    }
    return {
        'request': request,
        'provenance': {
            'partition_sha256': sha(b'basis-trial-v01 synthetic SDK preflight partition; no benchmark'),
            'data_sha256': sha(canonical(request)), 'domain_sha256': None,
            'metric_scope': 'train', 'data_kind': 'synthetic_sdk_preflight',
        },
    }


def synthetic_runner(source, request):
    """Return fake receipts without evaluating, importing or executing source."""
    if request.get('phase') == 'fit':
        n_params = request.get('n_params')
        if type(n_params) is not int or not 1 <= n_params <= 16:
            raise ValueError('invalid fake parameter count')
        return {'status': 'completed', 'result': {
            'status': 'success', 'params': [1.0] * n_params,
            'converged': True, 'nfev': 1, 'candidate_calls': 1,
            'diagnostics': {'data_kind': 'synthetic_sdk_preflight', 'actual_formula_calls': 0},
        }}
    if request.get('phase') == 'predict':
        if 'y' in request:
            raise ValueError('fake prediction must not receive targets')
        X = request.get('X')
        if type(X) is not list or not X:
            raise ValueError('invalid fake prediction inputs')
        return {'status': 'completed', 'result': {
            'status': 'success', 'predictions': [0.0] * len(X),
        }}
    raise ValueError('unknown fake phase')
