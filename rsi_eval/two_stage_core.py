"""Bounded registration and one-revision controllers, independent of the SDK.

The only executable candidate entry is the injected trusted evaluator. Probe
feedback is an allowlisted observation projection, never a solution artifact.
Historical inputs and raw evaluations remain separate from model-visible data.
"""
import copy
import hashlib
import json
import math
from pathlib import Path
import re

from .executor import evaluate_candidate
from .planning_probe import build_format_patch
from .symbolic_probe import build_term_removal, _terms, _signature

VERSION = 'two-stage-core-v0.1'
STRATEGY = 'two-stage-revision-v0.1'
EPSILON = 1e-5
TOLERANCE = 1e-10
MAX_SOURCE_BYTES = 16384
MAX_JSON_BYTES = 65536
_PLANNING_TASKS = [f'spannerlearning/seed0/problem{i}' for i in range(10)]
_STATUSES = {'success', 'task_failure', 'invalid_output', 'candidate_error',
             'candidate_process_error', 'timeout', 'resource_limit', 'output_limit',
             'infrastructure_error', 'invalid_request'}


def canonical(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False,
                      sort_keys=True, separators=(',', ':')).encode('utf-8')


def _copy_json(value, maximum=MAX_JSON_BYTES):
    # Reject non-string mapping keys rather than silently stringifying them.
    def visit(item):
        if item is None or type(item) in (str, bool, int):
            return
        if type(item) is float and math.isfinite(item):
            return
        if type(item) is list:
            for child in item: visit(child)
            return
        if type(item) is dict and all(type(key) is str for key in item):
            for child in item.values(): visit(child)
            return
        raise ValueError('Expected finite JSON')
    visit(value)
    encoded = canonical(value)
    if len(encoded) > maximum:
        raise ValueError('JSON byte bound exceeded')
    return json.loads(encoded)


def _sha(source):
    return hashlib.sha256(source.encode('utf-8')).hexdigest()


def _write(path, value):
    Path(path).write_bytes(json.dumps(value, ensure_ascii=False, allow_nan=False,
                                     indent=2).encode('utf-8') + b'\n')


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def _identifier(value, optional=False):
    if optional and value is None:
        return None
    if type(value) is not str or re.fullmatch(r'[A-Za-z0-9_:-]{1,128}', value) is None:
        raise ValueError('Invalid fixed identifier')
    return value


def _case(case):
    value = copy.deepcopy(case)
    _identifier(value['case_id'])
    family = value['family']
    source = value['source']
    if (type(source) is not str or not source.strip()
            or len(source.encode('utf-8')) > MAX_SOURCE_BYTES
            or _sha(source) != value['source_sha256']):
        raise ValueError('Case source binding mismatch')
    if type(value['n_params']) is not int or not 0 <= value['n_params'] <= 16:
        raise ValueError('Invalid parameter count')
    if family == 'planning':
        expected = (_PLANNING_TASKS, _PLANNING_TASKS[:2], _PLANNING_TASKS[2:],
                    'planning_whitespace', 'public_pair')
    elif family == 'symbolic':
        expected = (['oscillator1'], [], ['oscillator1'], 'symbolic_term_removal',
                    'param' + str(value['remove_param_index']))
        if (_sha(value['parent_source']) != value['parent_sha256']
                or value['parent_n_params'] != value['n_params'] - 1):
            raise ValueError('Symbolic parent binding mismatch')
    else:
        raise ValueError('Unknown family')
    actual = tuple(value[key] for key in ('task_ids', 'prompt_task_ids',
                    'development_task_ids', 'probe_id', 'target_id'))
    if actual != expected:
        raise ValueError('Case is outside fixed development/probe scope')
    packet = value['public_packet']
    if any(packet.get(key) != value[key] for key in
           ('case_id', 'family', 'source', 'source_sha256', 'n_params')):
        raise ValueError('Public packet source binding mismatch')
    _copy_json(packet)
    return value


def _binding(case):
    return {key: case[key] for key in
            ('case_id', 'family', 'source_sha256', 'probe_id', 'target_id')}


def probe_contract(case):
    common={'selection':'One researcher-fixed probe and target per state; registration does not measure autonomous probe selection.',
            'scope':'Only the bound candidate and stated development observations; no held-out, physical-necessity or universal claim.'}
    if case['family']=='planning':
        return {**common,'claim':'For each named public instance, only ASCII edge-whitespace normalization is sufficient to repair this generated failing plan.',
            'operation':'Generate one plan per public instance; trim ASCII whitespace outside parentheses and at inside payload edges only. Preserve operator/argument tokens, case, internal whitespace, order and count. Never add parentheses or actions.',
            'evaluation':'Both versions of the same generated plan use unchanged host syntax checks, VAL when reached, and public STRIPS replay; they are not separately generated plans.',
            'verdicts':{'supported':'Original failed and normalized plan succeeds.',
                'contradicted':'Original failed and safely normalized plan still fails.',
                'unknown':'Original already succeeded, no usable plan, or normalization contract does not apply; unknown is not false.'},
            'planning_n_params':'Parameter-count metadata is ignored by the planning executor.'}
    return {**common,'claim':'Removing the selected independent additive term and refitting increases oscillator1/train NMSE by more than epsilon.',
        'operation':'Delete the selected independent additive coefficient term, reduce parameter dimension by one and reindex. Retained basis terms must match the supplied parent under the narrow static AST contract.',
        'evaluation':'Refit original, canonical full sham and removed formula separately on the same 10000 training rows, all-one initialization, scipy least_squares max_nfev=100; fresh isolated prediction and host NMSE.',
        'quantity':'delta_nmse = NMSE(removed) - NMSE(canonical_full)',
        'epsilon':EPSILON,'tolerance':TOLERANCE,
        'verdicts':{'supported':'delta_nmse > epsilon + tolerance.',
            'contradicted':'-tolerance <= delta_nmse < epsilon - tolerance; this does not mean the term has zero benefit.',
            'unknown':'Unsupported static contract, unusable/nonconverged fit, absolute sham drift > tolerance, delta < -tolerance, or within tolerance of epsilon.'}}


def _registration(case, registration):
    if (type(registration) is not dict or registration.get('status') != 'accepted'
            or any(registration.get(key) != value for key, value in _binding(case).items())):
        raise ValueError('An accepted, source-bound registration is required')
    return _copy_json(registration)


def _start(directory, case, kind):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    with (directory/'controller-binding.json').open('x', encoding='utf-8') as stream:
        json.dump(dict(version=VERSION, kind=kind, **_binding(case)), stream,
                  ensure_ascii=False, allow_nan=False, indent=2)
        stream.write('\n')
    return directory


class ProbeController:
    def __init__(self, case, outputdir):
        self.case = _case(case)
        self.output_dir = _start(outputdir, self.case, 'registration')
        self.registration = None
        self.attempts = []
        self.halted = False
        self.infrastructure_error_type = None

    def task_packet(self):
        packet = copy.deepcopy(self.case['public_packet'])
        packet.update(stage='register_probe', probe_id=self.case['probe_id'],
            target_id=self.case['target_id'], max_submissions=1,
            probe_contract=probe_contract(self.case),
            auxiliary_contract={'pre_verdict': 'planning: {problem0,problem1}: supported/contradicted/unknown; symbolic: one such string',
                'predicted_delta_nmse': 'symbolic optional finite number',
                'planned_edit': 'Describe the intended edit before observations; unverified text',
                'rationale': 'Unverified explanation; auxiliary errors do not block valid probe'})
        return _copy_json(packet)

    state_packet = task_packet

    def task_prompt(self):
        return canonical(self.task_packet()).decode('utf-8')

    def submit_probe(self, session_id=None, probe_id='', target_id='', auxiliary=None):
        if self.halted:
            return {'status': 'infrastructure_error', 'error_kind': 'controller_halted'}
        if self.attempts:
            return {'status': 'budget_exhausted', 'error_kind': 'one_registration_attempt'}
        attempt = {'session_id': session_id, 'status': 'invalid_request'}
        self.attempts.append(attempt)
        try:
            auxiliary = _copy_json({} if auxiliary is None else auxiliary)
            _identifier(session_id, optional=True)
            if (probe_id, target_id) != (self.case['probe_id'], self.case['target_id']):
                raise ValueError('Probe/target binding mismatch')
            self.registration = dict(version=VERSION, status='accepted',
                **_binding(self.case), auxiliary=auxiliary)
            attempt.update(status='accepted', probe_id=probe_id, target_id=target_id)
            _write(self.output_dir/'registration.json', self.registration)
        except (ValueError, TypeError, UnicodeError, OverflowError, RecursionError):
            attempt['error_kind'] = 'registration_contract'
        _write(self.output_dir/'attempts.json', self.attempts)
        return copy.deepcopy(self.registration if self.registration is not None else attempt)

    def summary(self):
        return dict(version=VERSION, **_binding(self.case), attempts=len(self.attempts),
            registration=copy.deepcopy(self.registration), halted=self.halted,
            infrastructure_error_type=self.infrastructure_error_type,
            model_calls_owned=0, candidate_evaluations=0)


def _observation(record):
    if record is None:
        return None
    if type(record) is not dict:
        raise ValueError('Invalid observation')
    result = {}
    for key in ('status', 'error_kind'):
        if key in record:
            result[key] = _identifier(record[key], optional=True)
    for key in ('plan_length', 'executed_actions', 'first_invalid_action'):
        if key in record:
            if type(record[key]) is not int or not 0 <= record[key] <= 100000:
                raise ValueError('Invalid observation count')
            result[key] = record[key]
    return result


def feedback_projection(case, full_probe):
    """Expose narrow observations without copying any arbitrary nested field."""
    case = _case(case)
    projected = dict(version='two-stage-probe-feedback-v0.1', **_binding(case))
    if case['family'] == 'planning':
        rows = full_probe if type(full_probe) is list else full_probe.get('results', full_probe.get('records'))
        if (type(rows) is not list or len(rows) != 2
                or [row.get('task_id') for row in rows] != case['prompt_task_ids']):
            raise ValueError('Planning probe scope mismatch')
        projected.update(scope='two_public_prompt_instances_only', observations=[])
        for row in rows:
            if (row.get('source_sha256') != case['source_sha256']
                    or row.get('task_binding', {}).get('pilot_role') != 'prompt'
                    or row.get('verdict') not in ('supported', 'contradicted', 'unknown')):
                raise ValueError('Planning probe binding mismatch')
            item = {key: row[key] for key in ('task_id', 'status', 'verdict', 'reason')}
            _identifier(item['reason']); _identifier(item['status'])
            item.update(original=_observation((row.get('raw') or {}).get('validation')),
                intervention=_observation((row.get('normalized') or {}).get('validation')))
            projected['observations'].append(item)
    else:
        row = full_probe
        transform = row.get('transformation', {})
        identity = row.get('dataset_identity')
        if (row.get('case_id') != case['case_id']
                or transform.get('source_sha256') != case['source_sha256']
                or transform.get('parent_sha256') != case['parent_sha256']
                or row.get('verdict') not in ('supported', 'contradicted', 'unknown')
                or row.get('epsilon') != EPSILON or row.get('tolerance') != TOLERANCE
                or identity is not None and (identity.get('task'), identity.get('split')) != ('oscillator1', 'train')):
            raise ValueError('Symbolic probe binding/scope mismatch')
        projected.update(scope='oscillator1/train_fixed_refit', observations=[])
        for key in ('status', 'verdict', 'reason'):
            projected[key] = _identifier(row.get(key), optional=(key == 'reason'))
        for key in ('epsilon', 'tolerance', 'delta_nmse', 'sham_delta_nmse'):
            number = row.get(key)
            if number is not None and not _number(number):
                raise ValueError('Nonfinite probe observation')
            projected[key] = number
        variants = row.get('variants', [])
        if type(variants) is not list or [v.get('name') for v in variants] not in (
                [], ['original', 'canonical_full', 'removed']):
            raise ValueError('Unexpected symbolic variant order')
        for variant in variants:
            observed = variant.get('result')
            item = dict(variant=variant['name'], n_params=variant['n_params'], status=None, nmse=None)
            if observed is not None:
                item['status'] = _identifier(observed['status'])
                number = observed.get('metrics', {}).get('nmse')
                if number is not None and (not _number(number) or number < 0):
                    raise ValueError('Invalid symbolic NMSE')
                item['nmse'] = number
            projected['observations'].append(item)
    return _copy_json(projected)


def common_request(payload):
    """Remove exactly probe_feedback from the unique JSON user packet."""
    result = copy.deepcopy(payload)
    if type(result) is not dict or type(result.get('messages')) is not list:
        raise ValueError('Expected complete request envelope')
    users = [message for message in result['messages'] if message.get('role') == 'user']
    if len(users) != 1 or type(users[0].get('content')) is not str:
        raise ValueError('Exactly one JSON user packet is required')
    packet = json.loads(users[0]['content'])
    if type(packet) is not dict or 'probe_feedback' not in packet:
        raise ValueError('Missing sole permitted feedback channel')
    packet.pop('probe_feedback')
    users[0]['content'] = canonical(packet).decode('utf-8')
    return _copy_json(result, maximum=1024*1024)


def _visible_feedback(case, feedback):
    """Recheck a projection at the final model-facing boundary, including extras."""
    if feedback is None:
        return None
    value=_copy_json(feedback)
    common={'version','case_id','family','source_sha256','probe_id','target_id','scope','observations'}
    extra=set() if case['family']=='planning' else {'status','verdict','reason','epsilon','tolerance','delta_nmse','sham_delta_nmse'}
    scope='two_public_prompt_instances_only' if case['family']=='planning' else 'oscillator1/train_fixed_refit'
    if (type(value) is not dict or set(value)!=common|extra
            or value.get('version')!='two-stage-probe-feedback-v0.1'
            or value.get('scope')!=scope
            or any(value.get(key)!=item for key,item in _binding(case).items())
            or type(value.get('observations')) is not list):
        raise ValueError('Feedback projection contract mismatch')
    if case['family']=='planning':
        if [row.get('task_id') for row in value['observations']]!=case['prompt_task_ids']:
            raise ValueError('Feedback prompt scope mismatch')
        for row in value['observations']:
            if set(row)!={'task_id','status','verdict','reason','original','intervention'}:
                raise ValueError('Unexpected planning feedback field')
            if row['verdict'] not in ('supported','contradicted','unknown'):
                raise ValueError('Invalid feedback verdict')
            for key in ('original','intervention'):
                if _observation(row[key])!=row[key]:
                    raise ValueError('Unexpected observation field')
            _identifier(row['status']);_identifier(row['reason'])
    else:
        if (value['epsilon']!=EPSILON or value['tolerance']!=TOLERANCE
                or value['verdict'] not in ('supported','contradicted','unknown')
                or [row.get('variant') for row in value['observations']] not in (
                    [],['original','canonical_full','removed'])):
            raise ValueError('Invalid symbolic feedback scope')
        _identifier(value['status']);_identifier(value['reason'],optional=True)
        for key in ('delta_nmse','sham_delta_nmse'):
            if value[key] is not None and not _number(value[key]):
                raise ValueError('Nonfinite feedback delta')
        for row in value['observations']:
            if (set(row)!={'variant','n_params','status','nmse'}
                    or type(row['n_params']) is not int
                    or row['n_params']!=(case['parent_n_params'] if row['variant']=='removed' else case['n_params'])
                    or row['nmse'] is not None and (not _number(row['nmse']) or row['nmse']<0)):
                raise ValueError('Invalid symbolic feedback observation')
            _identifier(row['status'],optional=True)
    return value


def summarize_scores(case, results, n_params):
    """Development quality, keeping missing outcomes and train simplification distinct."""
    score = {'complete': False, 'family': case['family'], 'strict_improvement': None,
             'acceptable_simplification': None, 'achieved_improvement': False}
    if (type(results) is not list or [r.get('task_id') for r in results] != case['task_ids']
            or any(r.get('status') not in _STATUSES - {'infrastructure_error','invalid_request'} for r in results)):
        return score
    baseline = case['baseline_results']
    if case['family'] == 'planning':
        if [r.get('task_id') for r in baseline] != case['task_ids']:
            raise ValueError('Baseline score scope mismatch')
        good = lambda rows, tasks: sum(r.get('status') == 'success' for r in rows if r['task_id'] in tasks)
        dev = good(results,case['development_task_ids']); prompt=good(results,case['prompt_task_ids'])
        base_dev=good(baseline,case['development_task_ids'])
        base_prompt=good(baseline,case['prompt_task_ids'])
        score.update(complete=True, development_successes=dev, development_total=8,
            prompt_successes=prompt,prompt_total=2,total_successes=dev+prompt,total_tasks=10,
            baseline_development_successes=base_dev,baseline_prompt_successes=base_prompt,
            development_delta=dev-base_dev,prompt_delta=prompt-base_prompt,
            strict_improvement=dev>base_dev,achieved_improvement=dev>base_dev)
    else:
        value=results[0].get('metrics',{}).get('nmse')
        before=baseline[0].get('metrics',{}).get('nmse') if len(baseline)==1 else None
        if (results[0].get('status')!='success' or not _number(value) or value<0
                or not _number(before) or before<0):
            return score
        delta=value-before
        simplified=(None if abs(delta-EPSILON)<=TOLERANCE else
                    n_params<case['n_params'] and delta<EPSILON-TOLERANCE)
        improved=delta < -TOLERANCE
        score.update(complete=True,metric_split='train',nmse=value,baseline_nmse=before,
            delta_nmse=delta,n_params=n_params,baseline_n_params=case['n_params'],
            parameter_delta=n_params-case['n_params'],epsilon=EPSILON,tolerance=TOLERANCE,
            strict_improvement=improved,acceptable_simplification=simplified,
            achieved_improvement=improved or simplified is True)
    return score


def classify_edit(case, source, n_params):
    result={'kind':'other_change','source_changed':source!=case['source'],
            'parameter_delta':n_params-case['n_params'],'semantic_equivalence_proven':False}
    if source==case['source'] and n_params==case['n_params']:
        result['kind']='unchanged';return result
    if case['family']=='planning':
        patch=build_format_patch(case['source'])
        if patch['status']=='accepted' and source==patch['source']:
            result['kind']='exact_format_patch'
    else:
        transform=build_term_removal(case['source'],n_params=case['n_params'],
            remove_param_index=case['remove_param_index'],source_sha256=case['source_sha256'],
            parent_source=case['parent_source'],parent_n_params=case['parent_n_params'],parent_sha256=case['parent_sha256'])
        if transform['status']=='ready' and n_params==case['parent_n_params']:
            try:
                left=[_signature(t) for t in _terms(source,n_params)]
                right=[_signature(t) for t in _terms(transform['removed_source'],n_params)]
                if left==right:result['kind']='exact_term_removal'
            except (SyntaxError,ValueError,TypeError,RecursionError,OverflowError):
                pass
    return result


def check_forecast(case, forecast, score):
    field='development_successes' if case['family']=='planning' else 'nmse'
    result={'status':'schema_invalid','metric':field,'predicted':None,'observed':None,'absolute_error':None}
    value=forecast.get(field) if type(forecast) is dict else None
    valid=(type(value) is int and 0<=value<=8) if field=='development_successes' else (_number(value) and value>=0)
    if not valid:return result
    result['predicted']=value
    if not score.get('complete') or field not in score:
        result['status']='unavailable';return result
    result.update(status='evaluated',observed=score[field],absolute_error=abs(value-score[field]))
    return result


def check_probe_forecast(case, auxiliary, feedback):
    """Score declarations without gating registration, probe or revision."""
    auxiliary=auxiliary if type(auxiliary) is dict else {}
    predicted=auxiliary.get('pre_verdict')
    rows=[]
    observed=([('problem'+str(index),row['verdict']) for index,row in enumerate(feedback['observations'])]
              if case['family']=='planning' else [('selected_term',feedback['verdict'])])
    for target,actual in observed:
        value=predicted.get(target) if case['family']=='planning' and type(predicted) is dict else predicted if case['family']=='symbolic' else None
        valid=type(value) is str and value in ('supported','contradicted','unknown')
        rows.append(dict(target=target,status='evaluated' if valid else 'schema_invalid',
            predicted=copy.deepcopy(value),observed=actual,correct=(value==actual) if valid else None))
    numeric={'status':'not_applicable','absolute_error':None}
    if case['family']=='symbolic':
        value=auxiliary.get('predicted_delta_nmse');actual=feedback.get('delta_nmse')
        numeric=dict(status='schema_invalid',predicted=copy.deepcopy(value),observed=actual,absolute_error=None)
        if _number(value):
            numeric.update(status='evaluated' if _number(actual) else 'unavailable',
                absolute_error=abs(value-actual) if _number(actual) else None)
    return {'verdicts':rows,'numeric':numeric,'gates_execution':False}


class RevisionController:
    def __init__(self, case, registration, feedback, root, outputdir, evaluator=None):
        self.case=_case(case)
        self.registration=_registration(self.case,registration)
        self.feedback=_visible_feedback(self.case,feedback)
        self.root=Path(root).resolve()
        self.output_dir=_start(outputdir,self.case,'revision')
        (self.output_dir/'evaluations').mkdir(exist_ok=True)
        self.evaluator=evaluator or evaluate_candidate
        self.candidate=None;self.attempts=[];self.halted=False
        self.infrastructure_error_type=None
        self.counts={'candidate_evaluations':0,'sandbox_calls':0,'counts_complete':True}

    def task_packet(self):
        packet=copy.deepcopy(self.case['public_packet'])
        packet.update(stage='revise_once',registration=copy.deepcopy(self.registration),
            probe_feedback=copy.deepcopy(self.feedback),max_submissions=1,
            probe_contract=probe_contract(self.case),
            objective=('Maximize successes on the eight development instances; public instances are reported separately.'
                if self.case['family']=='planning' else
                'Improve train NMSE by more than 1e-10, or simplify with fewer parameters and NMSE increase < 1e-5; within 1e-10 of this threshold the simplification verdict is uncertain. Report NMSE and parameter count.'),
            auxiliary_contract={'decision':'retain, modify or abandon the registered intended edit; unverified',
                'forecast':{'development_successes':'integer 0..8'} if self.case['family']=='planning' else {'nmse':'finite nonnegative train NMSE'},
                'scope':'No held-out, physical necessity, optimality or generalization claim follows from the probe.'})
        return _copy_json(packet)

    state_packet=task_packet

    def task_prompt(self):
        return canonical(self.task_packet()).decode('utf-8')

    def submit(self, session_id=None, source='', n_params=0, rationale='', auxiliary=None):
        if self.halted:return {'status':'infrastructure_error','error_kind':'controller_halted'}
        if self.attempts:return {'status':'budget_exhausted','error_kind':'one_candidate_attempt'}
        attempt={'session_id':session_id,'status':'invalid_request'};self.attempts.append(attempt)
        try:
            _identifier(session_id,optional=True)
            if (type(source) is not str or not source.strip() or len(source.encode('utf-8'))>MAX_SOURCE_BYTES
                    or type(n_params) is not int or not 0<=n_params<=16
                    or type(rationale) is not str):raise ValueError('Candidate contract')
            auxiliary=_copy_json({} if auxiliary is None else auxiliary)
            _copy_json({'source':source,'n_params':n_params,'rationale':rationale,'auxiliary':auxiliary})
        except (ValueError,TypeError,UnicodeError,OverflowError,RecursionError):
            attempt['error_kind']='candidate_contract'
            _write(self.output_dir/'attempts.json',self.attempts);return copy.deepcopy(attempt)
        identifier=self.case['family']+'-001';digest=_sha(source)
        self.candidate=dict(candidate_id=identifier,parent_id=self.case['source_sha256'],
            source_sha256=digest,n_params=n_params,rationale=rationale,auxiliary=auxiliary,
            source_file='candidate.py',results=[],evaluation_files=[],status='evaluating',
            edit=classify_edit(self.case,source,n_params),score=summarize_scores(self.case,[],n_params))
        (self.output_dir/'candidate.py').write_bytes(source.encode('utf-8'))
        attempt.update(status='accepted',source_sha256=digest)
        _write(self.output_dir/'attempts.json',self.attempts)
        _write(self.output_dir/'candidate.json',self.candidate)
        for index,task_id in enumerate(self.case['task_ids']):
            self.counts['candidate_evaluations']+=1
            try:
                record=self.evaluator(self.case['family'],task_id,source,root=self.root,
                    n_params=n_params,candidate_id=identifier,parent_id=self.case['source_sha256'],
                    strategy_version=STRATEGY,diagnostics=True)
                if (type(record) is not dict or record.get('task_id')!=task_id
                        or record.get('candidate_hash')!=digest or record.get('status') not in _STATUSES):
                    raise ValueError('Executor binding mismatch')
                # Executor records may contain bounded diagnostic traces larger
                # than a prompt. Preserve them as archive-only JSON.
                record=_copy_json(record,maximum=4*1024*1024)
                if type(record.get('executions')) is list:
                    self.counts['sandbox_calls']+=len(record['executions'])
                else:self.counts['counts_complete']=False
            except Exception as error:
                self.infrastructure_error_type=type(error).__name__
                self.counts['counts_complete']=False
                record=dict(task_id=task_id,candidate_hash=digest,status='infrastructure_error',
                    error_kind='controller_or_executor_exception',exception_type=self.infrastructure_error_type)
            relative=f'evaluations/evaluation-{index:02d}.json'
            _write(self.output_dir/relative,record)
            self.candidate['results'].append(record)
            self.candidate['evaluation_files'].append(relative)
            _write(self.output_dir/'candidate.json',self.candidate)
            if record['status'] in ('infrastructure_error','invalid_request'):
                self.halted=True;break
        self.candidate['status']='infrastructure_error' if self.halted else 'evaluated'
        self.candidate['score']=summarize_scores(self.case,self.candidate['results'],n_params)
        self.candidate['forecast']=check_forecast(self.case,
            auxiliary.get('forecast') if type(auxiliary) is dict else None,self.candidate['score'])
        _write(self.output_dir/'candidate.json',self.candidate)
        _write(self.output_dir/'controller-summary.json',self.summary())
        return {key:copy.deepcopy(self.candidate[key]) for key in
                ('candidate_id','source_sha256','status','score','edit','forecast')}

    def summary(self):
        return dict(version=VERSION,**_binding(self.case),attempts=len(self.attempts),
            candidate=copy.deepcopy(self.candidate),halted=self.halted,
            infrastructure_error_type=self.infrastructure_error_type,counts=copy.deepcopy(self.counts),
            generated_candidates=int(self.candidate is not None),model_calls_owned=0,sealed_tasks_executed=0)
