"""Narrow, trusted AST intervention and matched training-only refit probe.

Parsing and emitting the restricted formula language never executes candidate
Python in the host. Evaluation remains exclusively in the existing sandbox.
The verdict concerns this fixed optimizer/protocol, not physical necessity.
"""
import ast
import copy
import hashlib
import math
from pathlib import Path
import re

from . import symbolic
from .executor import LIMITS, evaluate_candidate

CONTRACT = 'single-independent-additive-coefficient-v0.1'
STRATEGY = 'matched-term-removal-v0.1'
CLAIM = ('Removing the selected additive term and refitting under the fixed '
         'protocol increases oscillator1 train NMSE by more than epsilon.')


def _sha(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def _reject(reason):
    raise ValueError(reason)


def _is_docstring(node):
    return (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
            and type(node.value.value) is str)


def _parameter(node, aliases, count):
    if isinstance(node, ast.Name) and node.id in aliases:
        return aliases[node.id]
    if (isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name)
            and node.value.id == 'params' and isinstance(node.slice, ast.Constant)
            and type(node.slice.value) is int and 0 <= node.slice.value < count):
        return node.slice.value
    return None


def _basis(node):
    """Validate coefficient-free polynomial/absolute-value syntax only."""
    if isinstance(node, ast.Name) and node.id in ('x', 'v'):
        return
    if isinstance(node, ast.Constant) and type(node.value) in (float, int):
        if abs(node.value) <= 1e6 and math.isfinite(node.value):
            return
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        _basis(node.operand)
        return
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult)):
        _basis(node.left)
        _basis(node.right)
        return
    if (isinstance(node, ast.BinOp) and isinstance(node.op, ast.Pow)
            and isinstance(node.right, ast.Constant) and type(node.right.value) is int
            and 0 <= node.right.value <= 8):
        _basis(node.left)
        return
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name) and node.func.value.id == 'np'
            and node.func.attr == 'abs' and len(node.args) == 1 and not node.keywords):
        _basis(node.args[0])
        return
    _reject('unsupported_or_parameter_dependent_basis')


def _terms(source, count):
    tree = ast.parse(source)
    nodes = list(ast.walk(tree))
    if len(nodes) > 1000:
        _reject('ast_size_limit')
    body = list(tree.body)
    if body and _is_docstring(body[0]):
        body.pop(0)
    if body and isinstance(body[0], ast.Import):
        names = body.pop(0).names
        if len(names) != 1 or names[0].name != 'numpy' or names[0].asname != 'np':
            _reject('unsupported_import')
    if len(body) != 1 or not isinstance(body[0], ast.FunctionDef):
        _reject('unsupported_module')
    function = body[0]
    arguments = function.args
    if (function.name != 'equation' or function.decorator_list or function.returns
            or function.type_comment or getattr(function, 'type_params', [])
            or arguments.posonlyargs or arguments.vararg or arguments.kwarg
            or arguments.kwonlyargs or arguments.defaults or arguments.kw_defaults
            or [arg.arg for arg in arguments.args] != ['x', 'v', 'params']
            or any(arg.annotation for arg in arguments.args)):
        _reject('unsupported_equation_signature')
    statements = list(function.body)
    if statements and _is_docstring(statements[0]):
        statements.pop(0)
    if not statements or not isinstance(statements[-1], ast.Return):
        _reject('missing_final_return')
    aliases = {}
    for statement in statements[:-1]:
        if (not isinstance(statement, ast.Assign) or len(statement.targets) != 1
                or not isinstance(statement.targets[0], ast.Name) or statement.type_comment):
            _reject('unsupported_statement')
        name = statement.targets[0].id
        index = _parameter(statement.value, {}, count)
        if name in ('x', 'v', 'params', 'np') or name in aliases or index is None:
            _reject('invalid_parameter_alias')
        aliases[name] = index

    additive = []
    def expand(node, sign=1):
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub)):
            expand(node.left, sign)
            expand(node.right, sign if isinstance(node.op, ast.Add) else -sign)
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            expand(node.operand, sign if isinstance(node.op, ast.UAdd) else -sign)
        else:
            additive.append((sign, node))
    expand(statements[-1].value)
    terms = []
    for sign, expression in additive:
        factors = []
        def multiply(node):
            nonlocal sign
            if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult):
                multiply(node.left)
                multiply(node.right)
            elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
                if isinstance(node.op, ast.USub):
                    sign *= -1
                multiply(node.operand)
            else:
                factors.append(node)
        multiply(expression)
        coefficient = [_parameter(node, aliases, count) for node in factors]
        indices = [index for index in coefficient if index is not None]
        if len(indices) != 1:
            _reject('term_requires_one_independent_coefficient')
        bases = [node for node, index in zip(factors, coefficient) if index is None]
        if not bases:
            _reject('constant_only_coefficient_term_not_supported')
        for node in bases:
            _basis(node)
        basis = copy.deepcopy(bases[0])
        for node in bases[1:]:
            basis = ast.BinOp(left=basis, op=ast.Mult(), right=copy.deepcopy(node))
        terms.append({'index': indices[0], 'sign': sign, 'basis': basis})
    if sorted(term['index'] for term in terms) != list(range(count)):
        _reject('each_parameter_must_occur_in_exactly_one_term')
    return terms


def _signature(term, index=None):
    return (term['index'] if index is None else index, term['sign'],
            ast.dump(term['basis'], include_attributes=False))


def _expression(term, index=None):
    value = ast.BinOp(
        left=ast.Subscript(value=ast.Name(id='params', ctx=ast.Load()),
                           slice=ast.Constant(term['index'] if index is None else index),
                           ctx=ast.Load()),
        op=ast.Mult(), right=copy.deepcopy(term['basis']))
    return value if term['sign'] == 1 else ast.UnaryOp(op=ast.USub(), operand=value)


def _source(terms, mapping=None):
    expressions = [_expression(term, None if mapping is None else mapping[str(term['index'])])
                   for term in terms]
    expression = expressions[0]
    for term in expressions[1:]:
        expression = ast.BinOp(left=expression, op=ast.Add(), right=term)
    return ('import numpy as np\n\ndef equation(x, v, params):\n    return '
            + ast.unparse(ast.fix_missing_locations(expression)) + '\n')


def build_term_removal(source, *, n_params, remove_param_index, source_sha256,
                       parent_source, parent_n_params, parent_sha256):
    """Prove one independent additive term was appended, then emit two variants.

The retained basis ASTs must equal the parent's in their original order after
alias expansion and parameter reindexing. This deliberately accepts a narrow
language, not arbitrary mathematical equivalence or arbitrary Python.
"""
    result = {'contract': CONTRACT, 'status': 'unknown', 'verdict': 'unknown',
              'reason': None, 'source_sha256': source_sha256, 'parent_sha256': parent_sha256,
              'n_params_before': n_params, 'n_params_after': None,
              'remove_param_index': remove_param_index, 'mapping': None,
              'canonical_source': None, 'removed_source': None,
              'canonical_sha256': None, 'removed_sha256': None, 'term_ast_sha256': None}
    try:
        for text, digest in ((source, source_sha256), (parent_source, parent_sha256)):
            if type(text) is not str or not 0 < len(text.encode('utf-8')) <= 16384:
                _reject('source_size_or_type')
            if type(digest) is not str or not re.fullmatch('[0-9a-f]{64}', digest) or _sha(text) != digest:
                _reject('source_hash_mismatch')
        if (type(n_params) is not int or not 2 <= n_params <= 16
                or type(parent_n_params) is not int or parent_n_params != n_params - 1
                or type(remove_param_index) is not int or not 0 <= remove_param_index < n_params):
            _reject('parameter_dimension_contract')
        terms = _terms(source, n_params)
        parent_terms = _terms(parent_source, parent_n_params)
        mapping = {str(index): (None if index == remove_param_index else
                               index if index < remove_param_index else index - 1)
                   for index in range(n_params)}
        retained = [term for term in terms if term['index'] != remove_param_index]
        if ([_signature(term, mapping[str(term['index'])]) for term in retained]
                != [_signature(term) for term in parent_terms]):
            _reject('retained_terms_differ_from_parent')
        selected = next(term for term in terms if term['index'] == remove_param_index)
        canonical = _source(terms)
        removed = _source(retained, mapping)
        result.update(status='ready', reason=None, mapping=mapping,
                      n_params_after=parent_n_params, canonical_source=canonical,
                      removed_source=removed, canonical_sha256=_sha(canonical),
                      removed_sha256=_sha(removed),
                      term_ast_sha256=_sha(ast.dump(_expression(selected), include_attributes=False)))
    except (SyntaxError, ValueError, TypeError, RecursionError, OverflowError) as exc:
        result['reason'] = str(exc) if type(exc) is ValueError else type(exc).__name__
    return result


def _dataset_identity(root):
    """Read and verify only the pinned oscillator1 training manifest/table."""
    root = Path(root).resolve()
    manifest = symbolic._inside(root, 'configs/tasks/downloads-v0.1.json')
    data = symbolic._inside(root, 'data/symbolic/llm-sr/oscillator1/train.csv')
    before = (manifest.read_bytes(), data.read_bytes())
    task = symbolic.prepare_task('oscillator1', root)
    if before != (manifest.read_bytes(), data.read_bytes()):
        raise ValueError('dataset_changed_during_verification')
    return {'task': 'oscillator1', 'split': 'train', 'rows': len(task['y']),
            'input_names': task['input_names'],
            'manifest_sha256': hashlib.sha256(before[0]).hexdigest(),
            'data_sha256': hashlib.sha256(before[1]).hexdigest()}


def _finite(value):
    return type(value) in (float, int) and math.isfinite(value)


def _valid_record(record, variant, candidate_id, run_ids, parent_id):
    if not isinstance(record, dict):
        return False
    fit = record.get('fitting', {})
    metrics = record.get('metrics', {})
    executions = record.get('executions')
    diagnostics = record.get('diagnostics')
    if (not isinstance(fit, dict) or not isinstance(metrics, dict)
            or not isinstance(executions, list) or not isinstance(diagnostics, dict)):
        return False
    params = fit.get('params')
    run_id = record.get('run_id')
    return (record.get('status') == 'success' and record.get('family') == 'symbolic'
            and record.get('task_id') == 'oscillator1' and record.get('candidate_id') == candidate_id
            and record.get('candidate_hash') == variant['source_sha256']
            and record.get('parent_id') == parent_id and record.get('strategy_version') == STRATEGY
            and diagnostics.get('version') == 'diagnostics-v0.1'
            and diagnostics.get('candidate_sha256') == variant['source_sha256']
            and diagnostics.get('scope') == 'train' and diagnostics.get('task_id') == 'oscillator1'
            and type(run_id) is str and bool(run_id) and run_id not in run_ids
            and record.get('limits') == LIMITS and record.get('model_calls') == 0
            and record.get('sealed_tasks_executed') == 0 and record.get('metric_split') == 'train'
            and fit.get('split') == 'train' and type(fit.get('max_nfev')) is int and fit['max_nfev'] == 100
            and type(fit.get('n_params')) is int and fit['n_params'] == variant['n_params']
            and fit.get('converged') is True
            and type(fit.get('nfev')) is int and 1 <= fit['nfev'] <= 100
            and type(fit.get('candidate_calls')) is int and 1 <= fit['candidate_calls'] <= 100000
            and isinstance(params, list) and len(params) == variant['n_params']
            and all(_finite(value) for value in params)
            and len(executions) == 2
            and all(isinstance(item, dict) and item.get('phase') == phase
                    and item.get('status') == 'completed'
                    for item, phase in zip(executions, ('fit', 'predict')))
            and set(metrics) == {'mse', 'nmse'}
            and all(_finite(value) and value >= 0 for value in metrics.values())
            and ((metrics['mse'] == 0) == (metrics['nmse'] == 0)))


def probe_symbolic(source, *, root, case_id, n_params, remove_param_index,
                   source_sha256, parent_source, parent_n_params, parent_sha256,
                   epsilon=1e-5, tolerance=1e-10):
    """Run original/full/removed matched refits, stopping on missing evidence.

Returned sources and complete executor records are intended to be archived by
the caller. The executor additionally journals every evaluation itself. Epsilon
is an engineering threshold selected after historical observations, never a
statistical significance threshold or a claim of independent confirmation.
"""
    transformation = build_term_removal(
        source, n_params=n_params, remove_param_index=remove_param_index,
        source_sha256=source_sha256, parent_source=parent_source,
        parent_n_params=parent_n_params, parent_sha256=parent_sha256)
    result = {'version': STRATEGY, 'case_id': case_id, 'status': 'unavailable',
              'verdict': 'unknown', 'reason': transformation['reason'], 'claim': CLAIM,
              'epsilon': epsilon, 'tolerance': tolerance, 'transformation': transformation,
              'variants': [], 'dataset_identity': None, 'delta_nmse': None,
              'sham_delta_nmse': None, 'candidate_evaluations': 0, 'sandbox_executions': 0,
              'executions': {'sandbox_calls': 0, 'new_candidate_executions': 0,
                             'fit_calls': 0, 'predict_calls': 0},
              'execution_accounting_complete': True,
              'model_calls': 0, 'sealed_tasks_executed': 0, 'infrastructure_stopped': False}
    def stop(reason, infrastructure=False):
        result['reason'] = reason
        if infrastructure:
            result['status'] = 'infrastructure_error'
            result['infrastructure_stopped'] = True
        return result

    if transformation['status'] != 'ready':
        return result
    if (type(case_id) is not str or not re.fullmatch('[A-Za-z0-9][A-Za-z0-9_-]{0,63}', case_id)
            or not _finite(epsilon) or not _finite(tolerance) or not 0 < tolerance < epsilon):
        return stop('invalid_probe_contract')
    # All transformations precede any dataset read or candidate execution.
    result['variants'] = [
        {'name': name, 'source': text, 'source_sha256': _sha(text), 'n_params': count, 'result': None}
        for name, text, count in [('original', source, n_params),
                                 ('canonical_full', transformation['canonical_source'], n_params),
                                 ('removed', transformation['removed_source'], parent_n_params)]]
    try:
        identity = _dataset_identity(root)
        result['dataset_identity'] = identity
    except (OSError, ValueError, KeyError, TypeError):
        return stop('dataset_verification_failed', True)
    run_ids = set()
    variance = None
    for variant in result['variants']:
        dispatched, counted = False, False
        try:
            if _dataset_identity(root) != identity:
                return stop('dataset_identity_changed', True)
            candidate_id = case_id + '-' + variant['name']
            result['candidate_evaluations'] += 1
            result['executions']['new_candidate_executions'] += 1
            dispatched = True
            record = evaluate_candidate(
                'symbolic', 'oscillator1', variant['source'], root=root,
                n_params=variant['n_params'], candidate_id=candidate_id,
                parent_id=source_sha256, strategy_version=STRATEGY, diagnostics=True)
            variant['result'] = copy.deepcopy(record)
            if isinstance(record, dict) and isinstance(record.get('executions'), list):
                result['sandbox_executions'] += len(record['executions'])
                result['executions']['sandbox_calls'] += len(record['executions'])
                for item in record['executions']:
                    if isinstance(item, dict) and item.get('phase') in ('fit', 'predict'):
                        result['executions'][item['phase'] + '_calls'] += 1
                counted = True
            else:
                result['execution_accounting_complete'] = False
            if _dataset_identity(root) != identity:
                return stop('dataset_identity_changed', True)
        except Exception as exc:
            # Only trusted controller failures are caught here, never executed
            # candidate Python. The raw exception text may contain local paths.
            variant['controller_error_type'] = type(exc).__name__
            if dispatched and not counted:
                # The call may already have entered a sandbox before failing
                # to journal/return. Counts then are confirmed lower bounds.
                result['execution_accounting_complete'] = False
            return stop('controller_or_executor_error', True)
        if not isinstance(record, dict):
            return stop('invalid_executor_record', True)
        if record.get('status') == 'infrastructure_error':
            return stop('executor_infrastructure_error', True)
        if record.get('status') != 'success':
            return stop('candidate_evaluation_unavailable')
        if not _valid_record(record, variant, candidate_id, run_ids, source_sha256):
            return stop('executor_record_contract_mismatch', True)
        run_ids.add(record['run_id'])
        metrics = record['metrics']
        if metrics['nmse'] > 0:
            current_variance = metrics['mse'] / metrics['nmse']
            if variance is not None and not math.isclose(current_variance, variance, rel_tol=1e-12, abs_tol=0):
                return stop('metric_normalization_mismatch', True)
            variance = current_variance
        if variant['name'] == 'canonical_full':
            result['sham_delta_nmse'] = metrics['nmse'] - result['variants'][0]['result']['metrics']['nmse']
            if abs(result['sham_delta_nmse']) > tolerance:
                return stop('canonical_sham_drift')
    result['status'] = 'completed'
    delta = (result['variants'][2]['result']['metrics']['nmse']
             - result['variants'][1]['result']['metrics']['nmse'])
    result['delta_nmse'] = delta
    if delta < -tolerance:
        result['reason'] = 'nested_fit_inconsistent'
    elif delta > epsilon + tolerance:
        result.update(verdict='supported', reason='removal_loss_exceeds_threshold')
    elif delta < epsilon - tolerance:
        result.update(verdict='contradicted', reason='removal_loss_below_threshold')
    else:
        result['reason'] = 'threshold_boundary'
    return result
