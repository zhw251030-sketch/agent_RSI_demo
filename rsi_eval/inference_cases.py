"""Pinned experience with explicit evidence availability, loaded without execution.

The complete line diff establishes observable source changes, not fulfillment
of a historical intended edit or its causal effect. Historical explanations
remain untrusted. No matched intervention or formal edit contract is invented.
"""
import ast
import copy
import difflib
import hashlib
import json
import math
from pathlib import Path
import re

from .evidence_checks import check_claim, check_prediction, register_prediction
from .evidence_ids import EvidenceRegistry
from .grounded_states import (PINNED_STATES as GROUNDED_STATES, _identity,
                             _ordinary, _pilot_record, _read_documents)
from .policy_cases import (_diagnostics, _documents, _evidence, _observations,
                           _source_matches)
from .repair_states import _json, _one, _validate_record

VERSION = 'inference-cases-v0.1'
STATE_ORDER = ('P-A002', 'P-H002', 'S-poly5', 'S-odd4')
CASE_KEYS = {'case_id', 'family', 'source_sha256', 'source_diff', 'ast_equal',
    'parent_n_params', 'child_n_params', 'parent_metrics', 'child_metrics',
    'historical_rationale', 'forecast', 'diagnostics_before', 'diagnostics_after',
    'provenance', 'available_evidence', 'edit_contract', 'matched_interventions'}
FORECAST_KEYS = {'metric_key', 'scope', 'status', 'direction', 'min_delta',
                 'before', 'after', 'actual_delta'}
SELECTION_RULE = ('Most recent complete archived round: policy-transfer-v01; '
    'fixed arm with neither experience injection nor policy update; smallest '
    'repeat index; first complete parent-child transition in each task family. '
    'Chosen now from researcher-seen development archives, not preregistered '
    'before those outcomes and not an outcome-filtered independent sample.')


def _case(case_id, family, session, hashes):
    base = 'artifacts/policy-transfer/2026-10-20/v01/'+session
    names = {'parent_source': 'candidates/'+family+'-000.py',
             'source': 'candidates/'+family+'-001.py', 'trajectory': 'trajectory.json',
             'diagnostics': 'diagnostics.json', 'evidence': 'evidence.json',
             'audits': 'audits.json', 'state_provenance': 'repair-state-provenance.json'}
    return {'case_id': case_id, 'family': family, 'archive_session': session,
            'archive_run': '20261020-policy-transfer-v01',
            'archive_runtime_commit': '154bc39aa64d680ade8b3ddfedbecd296f0b4e81',
            'files': {kind: {'path': base+'/'+name, 'sha256': hashes[kind]}
                      for kind, name in names.items()}}


PINNED_CASES = [
    _case('D-P', 'planning', 'EP-r1-fixed', {
        'parent_source': '2f98dbb2b63144134a73cf1f9068f32df92b28779168b5859d9af537b2b0c897',
        'source': 'b47b7183020a42d814f64258886df6add8834e199299cf81bcc9c9d63acb5dfa',
        'trajectory': '04943c3e27f7fced9a842e6db61789200e651a1b6cf956e16f5304fce10e004d',
        'diagnostics': '511a923b28f53078a70fd625ee7f3264d12006181ec8daa88c1b79adc03ba6e3',
        'evidence': '70303551929d3f8e26057c5991651ef1eaa1b8f38dad6c14c5d4d7ac38ce44ce',
        'audits': 'cb00f3bab8322a4c913b3f0e8075d3d6e95f7b1a6a7cb3521fb3746b59ac4a6d',
        'state_provenance': '61f50c991c37fe382670a44c8aa79b073d6de4ac76ebe8837314ad2f9ca53914'}),
    _case('D-S', 'symbolic', 'ES-r1-fixed', {
        'parent_source': 'eea9556fadca83705ce5d6551090fb34b5c7b5316e042998db4cfc723571ce47',
        'source': '7cc7bbf448e5bd9e3d1edad2dbf4a8942577eb8ccc146192208dbf98196b7a19',
        'trajectory': '3aa0b0d83b291500deb4daf0b127a631eb249a2e572c2a4a5768a9ab3b09d9db',
        'diagnostics': '54b94d987aa3183cfb7f4d6fb6735e5e7fd836fcda540993422bd86a3d5c7a9c',
        'evidence': '5da063709b44f09e703871fa767edb71f41c391303f029300e478500f549180a',
        'audits': '4d97c00c3a91ffdbd714220dfabf399229e460a8b06af7d9af4fd9b89e9fd926',
        'state_provenance': '51246ed1be4ea93fa8b86b4b9f7ae22eb8e3607fe726c954a873964c8387e2a3'})]

PINNED_STATES = {name: copy.deepcopy(GROUNDED_STATES[name])
                 for name in ('P-A002', 'S-poly5', 'S-odd4')}
PINNED_STATES['P-H002'] = _ordinary('P-H002', 'planning',
    'artifacts/checked-feedback/2026-10-20/v01-stopped/planning_hidden',
    'planning-002', 2, 0,
    dict(prompt_successes=0, prompt_total=2, development_successes=0,
         development_total=8, total_successes=0, total_tasks=10),
    'candidates/planning-002.py', (
        'deb8420baf4bacc6de52068de9844363bb60edf7e9bc6cf5d4753d14c853aca3',
        'b1468be8a1ea03666409e588ca8feb6e8cd108b7c207b78c5d8f8324d1f02a67',
        '3276bcde9c2c39a4fda3fac59963b9960d02d9e46ede8b903de723a970167556'),
    '20261020-checked-feedback-v01', 'c4d4f60f852208494e214bd226882e532172c799',
    'Separate v01 hidden history from D-P/B003 and D-S/C002. Its declared parent '
    'is the empty program; the rejected earlier H001 and feedback also informed '
    'H002. Same Spanner development instances, not an independent task.')


def ast_equal(parent_source, child_source):
    """Ignore locations/formatting, not docstrings, constants or program meaning."""
    try:
        return ast.dump(ast.parse(parent_source), include_attributes=False) == ast.dump(
            ast.parse(child_source), include_attributes=False)
    except (SyntaxError, ValueError, TypeError) as exc:
        raise ValueError('Archived source cannot be parsed for AST comparison') from exc


def _no_overlap():
    if ([s['case_id'] for s in PINNED_CASES] != ['D-P', 'D-S']
            or set(PINNED_STATES) != set(STATE_ORDER)):
        raise ValueError('Inference case/state catalog mismatch')
    update = {s['files'][k]['sha256'] for s in PINNED_CASES for k in ('source', 'parent_source')}
    evaluation = {s['files']['source']['sha256'] for s in PINNED_STATES.values()}
    if len(update) != 4 or len(evaluation) != 4 or update & evaluation:
        raise ValueError('Inference update/evaluation source overlap')


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def _metrics(metrics, family):
    if type(metrics) is not dict or any(not _finite(v) or v < 0 for v in metrics.values()):
        raise ValueError('Invalid inference metrics')
    if family == 'symbolic':
        if set(metrics) != {'mse', 'nmse'}:
            raise ValueError('Invalid symbolic metric dimensions')
    else:
        names = {'prompt_successes', 'prompt_total', 'development_successes',
                 'development_total', 'total_successes', 'total_tasks'}
        if (set(metrics) != names or any(type(v) is not int for v in metrics.values())
                or (metrics['prompt_total'], metrics['development_total'], metrics['total_tasks']) != (2, 8, 10)
                or metrics['prompt_successes'] > 2 or metrics['development_successes'] > 8
                or metrics['total_successes'] != metrics['prompt_successes']+metrics['development_successes']):
            raise ValueError('Invalid planning metric dimensions')


def validate_bundle(bundle):
    """Validate a projected packet without claiming arbitrary prose is true.

    Archive authenticity is separately enforced by load_inference_bundle.
    This validator checks representation, metric dimensions and arithmetic.
    """
    if (type(bundle) is not dict or set(bundle) != {'version', 'cases'}
            or bundle['version'] != VERSION or type(bundle['cases']) is not list
            or len(bundle['cases']) != 2):
        raise ValueError('Invalid inference bundle envelope')
    for case, identifier, family in zip(bundle['cases'], ('D-P', 'D-S'), ('planning', 'symbolic')):
        if (type(case) is not dict or set(case) != CASE_KEYS
                or case['case_id'] != identifier or case['family'] != family):
            raise ValueError('Invalid inference case identity or fields')
        hashes = case['source_sha256']
        if (type(hashes) is not dict or set(hashes) != {'parent', 'child'}
                or any(type(v) is not str or re.fullmatch('[0-9a-f]{64}', v) is None for v in hashes.values())
                or type(case['ast_equal']) is not bool):
            raise ValueError('Invalid inference source identity')
        if (type(case['source_diff']) is not str or len(case['source_diff'].encode('utf-8')) > 16384
                or (case['source_diff'] and not case['source_diff'].startswith('--- parent.py\n+++ child.py\n'))):
            raise ValueError('Invalid or oversized inference source diff')
        if hashes['parent'] == hashes['child'] and (case['source_diff'] or not case['ast_equal']):
            raise ValueError('Source identity disagrees with diff/AST')
        for key in ('parent_n_params', 'child_n_params'):
            if type(case[key]) is not int or not 0 <= case[key] <= 16:
                raise ValueError('Invalid inference parameter count')
        for key in ('parent_metrics', 'child_metrics'):
            _metrics(case[key], family)
        rationale = case['historical_rationale']
        if type(rationale) is not str or len(rationale) > 2000:
            raise ValueError('Invalid historical rationale')
        forecast = case['forecast']
        metric_keys = {'mse', 'nmse'} if family == 'symbolic' else {
            'prompt_successes', 'development_successes', 'total_successes'}
        scope = 'train' if family == 'symbolic' else 'development_summary'
        if (type(forecast) is not dict or set(forecast) != FORECAST_KEYS
                or forecast['metric_key'] not in metric_keys or forecast['scope'] != scope
                or forecast['direction'] not in ('increase', 'decrease')
                or forecast['status'] not in ('supported', 'contradicted')
                or any(not _finite(forecast[key]) for key in ('min_delta', 'before', 'after', 'actual_delta'))
                or forecast['min_delta'] < 0
                or forecast['before'] != case['parent_metrics'][forecast['metric_key']]
                or forecast['after'] != case['child_metrics'][forecast['metric_key']]):
            raise ValueError('Invalid inference forecast or metric dimension')
        delta = forecast['after']-forecast['before']
        if forecast['direction'] == 'decrease':
            delta = -delta
        tolerance = 1e-10+1e-8*max(abs(delta), abs(forecast['min_delta']))
        status = 'supported' if delta+tolerance >= forecast['min_delta'] else 'contradicted'
        if forecast['actual_delta'] != delta or forecast['status'] != status:
            raise ValueError('Inference forecast arithmetic/status mismatch')
        expected_ids = [identifier+':'+kind for kind in ('source-diff', 'metrics', 'forecast', 'diagnostics')]
        if case['available_evidence'] != expected_ids or case['edit_contract'] is not None or case['matched_interventions'] != []:
            raise ValueError('Inference evidence availability differs from frozen contract')
        tasks = ['oscillator1'] if family == 'symbolic' else [
            'spannerlearning/seed0/problem0', 'spannerlearning/seed0/problem1']
        diagnostic_key = 'residuals' if family == 'symbolic' else 'plan_replay'
        diagnostic_scope = 'train' if family == 'symbolic' else 'public_prompt'
        for key in ('diagnostics_before', 'diagnostics_after'):
            rows = case[key]
            if (type(rows) is not list or len(rows) != len(tasks)
                    or any(type(row) is not dict or set(row) != {'task_id', 'scope', diagnostic_key}
                           or row['task_id'] != task or row['scope'] != diagnostic_scope
                           for row, task in zip(rows, tasks))):
                raise ValueError('Invalid inference diagnostic scope')
        if type(case['provenance']) is not dict:
            raise ValueError('Invalid inference provenance')
    try:
        encoded = json.dumps(bundle, ensure_ascii=False, allow_nan=False).encode('utf-8')
    except (ValueError, TypeError) as exc:
        raise ValueError('Inference bundle must be finite JSON') from exc
    if len(encoded) > 49152:
        raise ValueError('Inference bundle exceeds 48 KiB')
    return copy.deepcopy(bundle)


def _audit(data, spec, parent, child):
    session = spec['archive_run']+':'+spec['archive_session'].removesuffix('-fixed')
    parent_evidence = data['evidence'].get(parent['candidate_id'])
    child_evidence = data['evidence'].get(child['candidate_id'])
    _evidence(parent, parent_evidence, spec['family'], session)
    _evidence(child, child_evidence, spec['family'], session)
    audit = _one(data['audits'], child['candidate_id'], 'inference audit')
    registry = EvidenceRegistry(parent_evidence, session_id=session)
    declaration = audit['compact_declaration']
    claim = registry.expand_claim({'evidence_id': declaration['claim_id'],
        'op': declaration['claim_op'], 'value': _json(declaration['claim_value_json'])})
    prediction = registry.expand_prediction({'evidence_id': declaration['prediction_id'],
        'direction': declaration['prediction_direction'], 'min_delta': declaration['prediction_min_delta']})
    manifest = json.dumps(registry.export_manifest(), ensure_ascii=False, allow_nan=False,
                          sort_keys=True, separators=(',', ':'))
    digest = hashlib.sha256(manifest.encode('utf-8')).hexdigest()
    if (claim != audit['claim_expansion'] or prediction != audit['prediction_expansion']
            or audit['registry'] != {'file': 'evidence-registry-000.json', 'sha256': digest}
            or prediction.get('status') != 'resolved'):
        raise ValueError('Inference audit expansion differs from original declaration')
    claims = [check_claim(claim['value'], parent_evidence)] if claim.get('status') == 'resolved' else [claim]
    registered = register_prediction(prediction['value'], parent_evidence)
    result = check_prediction(registered, child_evidence)
    if (claims != audit['claim_results'] or registered != audit['registration']
            or result != audit['prediction_result']):
        raise ValueError('Inference audit differs from immutable evidence')
    forecast = {'metric_key': result['reference']['key'], 'scope': result['reference']['scope'],
                'status': result['status'], 'direction': result['direction'],
                'min_delta': declaration['prediction_min_delta'], 'before': result['before'],
                'after': result['after'], 'actual_delta': result['actual']}
    return forecast, claims


def load_inference_bundle(root):
    """Read only selected transition archives; no task data, credentials or execution."""
    root = Path(root).resolve()
    _no_overlap()
    cards = []
    for spec in PINNED_CASES:
        data = _documents(root, spec)
        family = spec['family']
        if len(data['trajectory']) != 2:
            raise ValueError('Inference transition must contain exactly its parent and child')
        parent, child = data['trajectory']
        if (parent.get('candidate_id') != family+'-000' or child.get('candidate_id') != family+'-001'
                or child.get('parent_id') != parent['candidate_id']
                or parent.get('origin') != 'archived_model_proposed_initial'
                or child.get('origin') != 'model_proposed'):
            raise ValueError('Inference transition identity mismatch')
        for record, key in ((parent, 'parent_source'), (child, 'source')):
            _validate_record(record, family)
            _source_matches(data[key], record)
        before = _diagnostics(parent, data['diagnostics'].get(parent['candidate_id']), family)
        after = _diagnostics(child, data['diagnostics'].get(child['candidate_id']), family)
        forecast, claims = _audit(data, spec, parent, child)
        source_diff = '\n'.join(difflib.unified_diff(data['parent_source'].splitlines(),
            data['source'].splitlines(), fromfile='parent.py', tofile='child.py', lineterm=''))+'\n'
        provenance = {key: spec[key] for key in ('archive_run', 'archive_session', 'archive_runtime_commit')}
        provenance.update(source_files=copy.deepcopy(list(spec['files'].values())),
            parent_candidate_id=parent['candidate_id'], child_candidate_id=child['candidate_id'],
            parent_archive=copy.deepcopy(data['state_provenance']), selection_rule=SELECTION_RULE,
            historical_claim_statuses=[item['status'] for item in claims],
            candidate_executions_during_load=0,
            evidence_limits='Source diff/AST establish changes, not specific repair fulfillment. '
                'Historical rationale is untrusted. No formal edit contract or matched intervention exists. '
                'All evidence is researcher-seen development data; no independent-task inference.')
        cards.append({'case_id': spec['case_id'], 'family': family,
            'source_sha256': {'parent': parent['source_sha256'], 'child': child['source_sha256']},
            'source_diff': source_diff, 'ast_equal': ast_equal(data['parent_source'], data['source']),
            'parent_n_params': parent['n_params'], 'child_n_params': child['n_params'],
            'parent_metrics': copy.deepcopy(parent['metrics']), 'child_metrics': copy.deepcopy(child['metrics']),
            'historical_rationale': child['rationale'], 'forecast': forecast,
            'diagnostics_before': _observations(before, family), 'diagnostics_after': _observations(after, family),
            'provenance': provenance,
            'available_evidence': [spec['case_id']+':'+kind for kind in ('source-diff', 'metrics', 'forecast', 'diagnostics')],
            'edit_contract': None, 'matched_interventions': []})
    return validate_bundle({'version': VERSION, 'cases': cards})


def load_inference_states(root):
    """Four pinned repair states; B002 is replaced to avoid D-P's known history."""
    root = Path(root).resolve()
    _no_overlap()
    states = []
    for state_id in STATE_ORDER:
        spec = PINNED_STATES[state_id]
        data = _read_documents(root, spec)
        if state_id == 'S-odd4':
            record, diagnostics, detail = _pilot_record(data, spec)
        else:
            rows = data['trajectory']
            record = _one(rows, spec['archived_candidate_id'], 'inference state')
            if len(rows) <= spec['record_index'] or rows[spec['record_index']] != record:
                raise ValueError('Inference state record position mismatch')
            diagnostics = data['diagnostics'].get(record['candidate_id'])
            detail = {'record_index': spec['record_index'], 'record_assembly': 'Original record and own diagnostics.'}
        _identity(record, spec)
        _validate_record(record, spec['family'])
        _source_matches(data['source'], record)
        diagnostics = _diagnostics(record, diagnostics, spec['family'])
        provenance = {key: copy.deepcopy(spec[key]) for key in ('archive_run', 'archive_session',
            'archived_candidate_id', 'archive_runtime_commit', 'lineage')}
        provenance.update(source_files=copy.deepcopy(list(spec['files'].values())),
            candidate_executions_during_load=0, **detail,
            seed_policy='Forced archived state; no later answers or complete history supplied.',
            source_role='Researcher-seen development state, not an independent or held-out task.',
            inference_round_scope='No exact source overlap with D-P/D-S. B002 was removed because '
                'D-P parent B003 had observed its history; shared task data and common ancestors remain.')
        states.append({'state_id': state_id, 'family': spec['family'], 'source': data['source'],
            'n_params': record['n_params'], 'record': copy.deepcopy(record),
            'diagnostics': copy.deepcopy(diagnostics), 'historical_common': {},
            'historical_checks': {}, 'provenance': provenance})
    return states
