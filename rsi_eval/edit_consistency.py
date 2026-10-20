"""Bounded, static relations between an artifact and a proposed replacement.

This module parses source but never imports, evaluates or executes it. AST
identity ignores locations/comments and empty Python 3.12 type-parameter fields;
type comments and docstrings remain visible. Identity is a syntactic relation,
not a proof of arbitrary Python semantics, solver success, physical necessity,
or equivalence of floating-point evaluation orders.

The legacy symbolic term helper intentionally ignores optional NumPy imports,
docstrings and coefficient aliases, and flattens some arithmetic syntax. Its
signature comparison alone is therefore insufficient to prove an edit's scope.
Here it only validates the bound original-to-parent relation. Support additionally
requires unchanged module/function scaffolding and the candidate's entire AST
to equal the bound parent's AST. Other equivalent-looking rewrites are unknown.
"""
import ast
import copy
import hashlib
import re

from .planning_probe import _ast_dump, build_format_patch
from .symbolic_probe import _terms, _signature, build_term_removal


VERSION = 'edit-consistency-v0.1'
MAX_SOURCE_BYTES = 16384
MAX_AST_NODES = 10000
CLAIM_KINDS = ('keep_bytes', 'keep_ast', 'apply_format_patch', 'remove_selected_term')
_DIGEST = re.compile(r'[0-9a-f]{64}')
_PARSE_ERRORS = (SyntaxError, ValueError, TypeError, RecursionError, OverflowError,
                 UnicodeError)


def _sha(source):
    return hashlib.sha256(source.encode('utf-8')).hexdigest()


def _verdict(status, reason):
    return {'status': status, 'reason': reason}


def _dump(tree):
    projected = copy.deepcopy(tree)
    for node in ast.walk(projected):
        # Unlike ordinary node locations, TypeIgnore.lineno is an AST field,
        # so include_attributes=False alone would preserve accidental shifts.
        if isinstance(node, ast.TypeIgnore):
            node.lineno = 0
    return _ast_dump(projected)


def _bounded_parse(source):
    if type(source) is not str:
        raise ValueError('source_type')
    if not source.strip() or not 0 < len(source.encode('utf-8')) <= MAX_SOURCE_BYTES:
        raise ValueError('source_byte_limit_or_empty')
    tree = ast.parse(source, type_comments=True)
    for index, _ in enumerate(ast.walk(tree), 1):
        if index > MAX_AST_NODES:
            raise ValueError('ast_node_limit')
    return tree, _dump(tree)


def _bound_source(case, source_key, hash_key):
    source, digest = case.get(source_key), case.get(hash_key)
    try:
        valid = (type(source) is str and type(digest) is str
                 and _DIGEST.fullmatch(digest) is not None and _sha(source) == digest)
    except UnicodeError:
        valid = False
    if not valid:
        raise ValueError('Case source binding mismatch: '+source_key)


def _validate_case(case):
    if type(case) is not dict or case.get('family') not in ('planning', 'symbolic'):
        raise ValueError('Invalid case family')
    _bound_source(case, 'source', 'source_sha256')
    if type(case.get('n_params')) is not int or not 0 <= case['n_params'] <= 16:
        raise ValueError('Invalid case parameter count')
    if case['family'] == 'symbolic':
        _bound_source(case, 'parent_source', 'parent_sha256')
        if (type(case.get('parent_n_params')) is not int
                or case['parent_n_params'] != case['n_params']-1
                or not 2 <= case['n_params'] <= 16
                or type(case.get('remove_param_index')) is not int
                or not 0 <= case['remove_param_index'] < case['n_params']):
            raise ValueError('Invalid bound symbolic parameter metadata')


def _is_docstring(node):
    return (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
            and type(node.value.value) is str)


def _scaffold(tree):
    """Mask only the restricted equation's aliases and return, retaining docs.

Callers first validate the legacy one-function language. This extra projection
keeps imports, module docs, equation docs, signature and type comments outside
the permitted alias/return edit. It is not a general dependency analysis.
"""
    projected = copy.deepcopy(tree)
    functions = [node for node in projected.body if isinstance(node, ast.FunctionDef)]
    if len(functions) != 1 or functions[0].name != 'equation':
        raise ValueError('unsupported_equation_module')
    function = functions[0]
    statements = function.body
    docs = statements[:1] if statements and _is_docstring(statements[0]) else []
    # The old parser uses ast.parse without type_comments=True. Do not allow
    # type-comment changes to disappear inside the newly masked statements.
    if any(getattr(node, 'type_comment', None) is not None for node in statements):
        raise ValueError('symbolic_statement_type_comment_unsupported')
    function.body = docs+[ast.Pass()]
    return _dump(projected)


def _format_relation(case, source_ast, parameter_count_same):
    transform = build_format_patch(case['source'])
    if transform['status'] != 'accepted':
        return _verdict('unknown', 'original_formatter_outside_exact_contract')
    try:
        _, expected = _bounded_parse(transform['source'])
    except _PARSE_ERRORS:
        return _verdict('unknown', 'expected_formatter_patch_parse_unavailable')
    if source_ast != expected:
        return _verdict('contradicted', 'candidate_ast_differs_from_exact_formatter_patch')
    if not parameter_count_same:
        return _verdict('contradicted', 'parameter_metadata_changed')
    return _verdict('supported', 'whole_ast_equals_exact_formatter_patch')


def _removal_relation(case, source, n_params, original_tree, original_ast,
                      candidate_tree, candidate_ast):
    try:
        parent_tree, parent_ast = _bounded_parse(case['parent_source'])
        transform = build_term_removal(case['source'], n_params=case['n_params'],
            remove_param_index=case['remove_param_index'],
            source_sha256=case['source_sha256'], parent_source=case['parent_source'],
            parent_n_params=case['parent_n_params'], parent_sha256=case['parent_sha256'])
        if transform['status'] != 'ready':
            return _verdict('unknown', 'original_parent_outside_selected_removal_contract')
        if _scaffold(original_tree) != _scaffold(parent_tree):
            return _verdict('unknown', 'original_parent_scaffolding_differs')
        if candidate_ast == original_ast and n_params == case['n_params']:
            return _verdict('contradicted', 'original_formula_and_parameter_count_retained')
        if candidate_ast == parent_ast:
            if n_params != case['parent_n_params']:
                return _verdict('contradicted', 'removed_formula_parameter_count_mismatch')
            return _verdict('supported', 'restricted_signature_and_bound_parent_ast')
        # Restrictive parsing excludes extra functions, calls, imports and
        # arbitrary side effects before drawing any conclusion about terms.
        actual_terms = _terms(source, n_params)
        if _scaffold(candidate_tree) != _scaffold(parent_tree):
            return _verdict('unknown', 'candidate_scaffolding_differs')
        if n_params != case['parent_n_params']:
            return _verdict('contradicted', 'restricted_formula_parameter_count_mismatch')
        expected_terms = _terms(case['parent_source'], case['parent_n_params'])
        if [_signature(term) for term in actual_terms] != [_signature(term) for term in expected_terms]:
            return _verdict('contradicted', 'restricted_retained_term_signatures_differ')
        return _verdict('unknown', 'matching_signatures_but_bound_parent_ast_differs')
    except _PARSE_ERRORS:
        return _verdict('unknown', 'symbolic_source_outside_restricted_contract')


def inspect_edit(case, source, n_params):
    """Inspect four explicitly bounded claims without candidate execution.

Trusted case binding failures raise ValueError. Unsupported or malformed
candidate syntax is unknown, rather than a proof of a false semantic claim.
"""
    _validate_case(case)
    parameter_valid = type(n_params) is int and 0 <= n_params <= 16
    result = {'version': VERSION, 'family': case['family'],
              'before_sha256': case['source_sha256'], 'after_sha256': None,
              'before_n_params': case['n_params'],
              'after_n_params': n_params if parameter_valid else None,
              'parameter_count_same': n_params == case['n_params'] if parameter_valid else None,
              'relation': 'unsupported_or_general_change',
              'relations': {kind: _verdict('unknown', 'not_inspected') for kind in CLAIM_KINDS},
              'semantic_equivalence_proven': False, 'candidate_executions': 0,
              'ast_scope': 'Locations/comments and empty type_params ignored; type comments and docstrings retained.'}
    try:
        if type(source) is str:
            result['after_sha256'] = _sha(source)
        if not parameter_valid:
            raise ValueError('candidate_parameter_count')
        original_tree, original_ast = _bounded_parse(case['source'])
        candidate_tree, candidate_ast = _bounded_parse(source)
    except _PARSE_ERRORS as error:
        reason = str(error) if type(error) is ValueError else type(error).__name__
        result['relations'] = {kind: _verdict('unknown', 'parse_or_input_unavailable:'+reason)
                               for kind in CLAIM_KINDS}
        return result
    same_parameters = result['parameter_count_same']
    same_bytes = source == case['source']
    same_ast = candidate_ast == original_ast
    relations = result['relations']
    relations['keep_bytes'] = _verdict(
        'supported' if same_bytes and same_parameters else 'contradicted',
        'source_bytes_and_parameter_metadata_identical' if same_bytes and same_parameters else
        'parameter_metadata_changed' if same_bytes else 'source_bytes_changed')
    relations['keep_ast'] = _verdict(
        'supported' if same_ast and same_parameters else 'contradicted',
        'whole_ast_and_parameter_metadata_identical' if same_ast and same_parameters else
        'parameter_metadata_changed' if same_ast else 'whole_ast_changed')
    if case['family'] == 'planning':
        relations['apply_format_patch'] = _format_relation(case, candidate_ast, same_parameters)
        relations['remove_selected_term'] = _verdict('unknown', 'claim_not_applicable_to_family')
    else:
        relations['apply_format_patch'] = _verdict('unknown', 'claim_not_applicable_to_family')
        relations['remove_selected_term'] = _removal_relation(case, source, n_params,
            original_tree, original_ast, candidate_tree, candidate_ast)
    for claim, label in [('keep_bytes', 'byte_identical'), ('keep_ast', 'ast_same'),
                         ('apply_format_patch', 'exact_format_patch_up_to_ast'),
                         ('remove_selected_term', 'remove_selected_term')]:
        if relations[claim]['status'] == 'supported':
            result['relation'] = label
            break
    return result


def assess_claim(inspection, claim_kind):
    """Return only a named narrow relation; no free-text claim interpretation."""
    if type(claim_kind) is not str or claim_kind not in CLAIM_KINDS:
        return _verdict('unknown', 'unsupported_claim')
    if type(inspection) is not dict or type(inspection.get('relations')) is not dict:
        return _verdict('unknown', 'inspection_unavailable')
    verdict = inspection['relations'].get(claim_kind)
    if (type(verdict) is not dict or verdict.get('status') not in
            ('supported', 'contradicted', 'unknown') or type(verdict.get('reason')) is not str):
        return _verdict('unknown', 'inspection_unavailable')
    return copy.deepcopy(verdict)
