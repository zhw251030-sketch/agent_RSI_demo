"""One free edit with replayed diagnostic evidence and explicit keep permission.

No probe is registered or executed here. Historical evidence and candidate
evaluation stay separate. Parameter count is a complexity proxy, not a proof
that an explanation or added mathematical term is justified.
"""
import copy
from pathlib import Path

from .executor import evaluate_candidate
from .two_stage_core import (
    _binding, _case, _copy_json, _identifier, _sha, _visible_feedback, _write,
    _STATUSES, MAX_SOURCE_BYTES, canonical, probe_contract, common_request,
    classify_edit, check_forecast, summarize_scores as _legacy_scores,
)

VERSION = 'decision-core-v0.1'
STRATEGY = 'decision-replay-v0.1'
MIN_MEANINGFUL_GAIN = 1e-5
MAX_SIMPLIFICATION_LOSS = 1e-5
NUMERIC_TOLERANCE = 1e-10
DECISION_FIELDS = ('meaningful_improvement', 'acceptable_simplification',
                   'degraded', 'parameter_increase_without_meaningful_gain')


class ExecutionAccountingError(ValueError):
    """An evaluator result cannot substantiate the execution phases it used."""


def _execution_accounting_valid(family, record):
    if record.get('execution_accounting_complete', True) is not True:
        return False
    executions = record.get('executions')
    if type(executions) is not list or any(type(row) is not dict for row in executions):
        return False
    phases = [row.get('phase') for row in executions]
    if not phases:
        # Task preparation can fail before any sandbox dispatch. These records
        # remain fatal at the controller boundary, but zero calls is accounted.
        return record['status'] in ('infrastructure_error', 'invalid_request')
    if family == 'planning':
        return phases == ['plan']
    if record['status'] == 'success':
        return phases == ['fit', 'predict']
    # A candidate can legitimately fail during fitting and never predict.
    return phases in (['fit'], ['fit', 'predict'])


def _above(value, threshold):
    if abs(value-threshold) <= NUMERIC_TOLERANCE:
        return None
    return value > threshold


def summarize_scores(case, results, n_params):
    """Report numerical change, practical change and simplification separately.

``degraded`` means a loss larger than the practical threshold. Tiny numerical
loss is retained separately in ``numerical_degradation``. Boundary values are
unknown. A valid unchanged submission is not an improvement.
"""
    score = _legacy_scores(case, results, n_params)
    numeric_improvement = score.pop('strict_improvement')
    score.update({field: None for field in DECISION_FIELDS})
    score.update(numerical_improvement=None, numerical_degradation=None,
                 achieved_improvement=False)
    if not score['complete']:
        return score
    if case['family'] == 'planning':
        delta = score['development_delta']
        score.update(meaningful_improvement=delta > 0, degraded=delta < 0,
                     numerical_improvement=delta > 0, numerical_degradation=delta < 0,
                     achieved_improvement=delta > 0)
        return score
    delta = score['delta_nmse']
    meaningful = _above(-delta, MIN_MEANINGFUL_GAIN)
    degraded = _above(delta, MAX_SIMPLIFICATION_LOSS)
    simplified = False
    if n_params < case['n_params']:
        above_loss = _above(delta, MAX_SIMPLIFICATION_LOSS)
        simplified = None if above_loss is None else not above_loss
    extra_without_gain = False
    if n_params > case['n_params']:
        extra_without_gain = None if meaningful is None else not meaningful
    score.update(meaningful_improvement=meaningful, acceptable_simplification=simplified,
        degraded=degraded, parameter_increase_without_meaningful_gain=extra_without_gain,
        numerical_improvement=numeric_improvement,
        numerical_degradation=delta > NUMERIC_TOLERANCE,
        achieved_improvement=meaningful is True or simplified is True,
        minimum_meaningful_gain=MIN_MEANINGFUL_GAIN,
        maximum_simplification_loss=MAX_SIMPLIFICATION_LOSS,
        degradation_threshold=MAX_SIMPLIFICATION_LOSS,
        complexity_proxy='independent_parameter_count_only')
    return score


class DecisionController:
    def __init__(self, case, feedback, root, outputdir, evaluator=None):
        self.case = _case(case)
        self.feedback = _visible_feedback(self.case, feedback)
        self.root = Path(root).resolve()
        self.output_dir = Path(outputdir)
        if any(p.is_symlink() for p in (self.output_dir, *self.output_dir.parents)):
            raise ValueError('Symlinked decision output')
        self.output_dir.mkdir(parents=True, exist_ok=True)
        with (self.output_dir/'controller-binding.json').open('x', encoding='utf-8') as stream:
            stream.write(canonical(dict(version=VERSION, kind='decision', **_binding(self.case))).decode('utf-8')+'\n')
        (self.output_dir/'evaluations').mkdir(exist_ok=True)
        self.evaluator = evaluator or evaluate_candidate
        self.candidate = None
        self.attempts = []
        self.halted = False
        self.infrastructure_error_type = None
        self.counts = {'candidate_evaluations': 0, 'sandbox_calls': 0, 'counts_complete': True}

    def task_packet(self):
        packet = copy.deepcopy(self.case['public_packet'])
        packet.pop('registration', None)
        packet.pop('planned_edit', None)
        if type(packet.get('probe_target')) is dict:
            packet['probe_target'].pop('parent_source', None)
        planning = self.case['family'] == 'planning'
        packet.update(stage='decide_once', max_submissions=1,
            probe_feedback=copy.deepcopy(self.feedback), probe_contract=probe_contract(self.case),
            evidence_mode='Researcher-fixed archived diagnostic evidence; no new registration or probe is requested.',
            decision_contract=(
                'The diagnostic intervention is temporary and is not a required final edit. '
                'Keeping the starting artifact unchanged is legal; submit its complete original source and parameter count if you choose that. '
                'You may also submit one revised complete artifact. No prior planned edit is binding. '
                'Evidence against deleting a term does not support adding a new term or extra parameters. '
                'An unavailable or unknown diagnostic result is not evidence of success. '
                'Choose from the available information and explain uncertainty. Do not claim that a new candidate succeeds before its evaluation.'),
            objective=('Maximize successes on the eight development instances; report the two public instances separately. '
                       'Keeping the same artifact is a legal decision and does not itself count as improvement.' if planning else
                       'Meaningful improvement requires a train NMSE decrease greater than 1e-5. '
                       'Simplification is a separate outcome: fewer independent parameters with train NMSE increase below 1e-5. '
                       'Within 1e-10 of either threshold the decision is uncertain. '
                       'Tiny numerical gains do not satisfy the meaningful gain criterion. '
                       'Report parameter count as a complexity proxy; extra parameters without meaningful gain are recorded separately.'),
            auxiliary_contract={
                'decision': 'Optional keep or revise declaration; unverified and not an execution gate.',
                'forecast': {'development_successes': 'integer 0..8'} if planning else {'nmse': 'finite nonnegative number'},
                'forecast_example': {'development_successes': 0} if planning else {'nmse': 0.123},
                'example_scope': 'The example demonstrates JSON types only and is not an expected result. Put it inside auxiliary.forecast.',
                'scope': 'No held-out, physical necessity, optimality or generalization conclusion follows from this development evidence.'})
        return _copy_json(packet)

    def state_packet(self):
        return self.task_packet()

    def task_prompt(self):
        return canonical(self.task_packet()).decode('utf-8')

    def submit(self, session_id=None, source='', n_params=0, rationale='', auxiliary=None):
        if self.halted:
            return {'status': 'infrastructure_error', 'error_kind': 'controller_halted'}
        if self.attempts:
            return {'status': 'budget_exhausted', 'error_kind': 'one_candidate_attempt'}
        attempt = {'session_id': session_id, 'status': 'invalid_request'}
        self.attempts.append(attempt)
        try:
            _identifier(session_id, optional=True)
            if (type(source) is not str or not source.strip() or len(source.encode('utf-8')) > MAX_SOURCE_BYTES
                    or type(n_params) is not int or not 0 <= n_params <= 16
                    or type(rationale) is not str or len(rationale) > 4000):
                raise ValueError('Candidate contract')
            auxiliary = _copy_json({} if auxiliary is None else auxiliary)
            if type(auxiliary) is not dict:
                raise ValueError('Auxiliary must be a JSON object')
            _copy_json({'source': source, 'n_params': n_params, 'rationale': rationale, 'auxiliary': auxiliary})
        except (ValueError, TypeError, UnicodeError, OverflowError, RecursionError):
            attempt['error_kind'] = 'candidate_contract'
            _write(self.output_dir/'attempts.json', self.attempts)
            return copy.deepcopy(attempt)
        identifier = self.case['family']+'-001'
        digest = _sha(source)
        self.candidate = dict(candidate_id=identifier, parent_id=self.case['source_sha256'],
            source_sha256=digest, n_params=n_params, rationale=rationale, auxiliary=auxiliary,
            source_file='candidate.py', results=[], evaluation_files=[], status='evaluating',
            edit=classify_edit(self.case, source, n_params), score=summarize_scores(self.case, [], n_params))
        (self.output_dir/'candidate.py').write_bytes(source.encode('utf-8'))
        attempt.update(status='accepted', source_sha256=digest)
        _write(self.output_dir/'attempts.json', self.attempts)
        _write(self.output_dir/'candidate.json', self.candidate)
        for index, task_id in enumerate(self.case['task_ids']):
            self.counts['candidate_evaluations'] += 1
            returned_record_file = None
            try:
                record = self.evaluator(self.case['family'], task_id, source, root=self.root,
                    n_params=n_params, candidate_id=identifier, parent_id=self.case['source_sha256'],
                    strategy_version=STRATEGY, diagnostics=True)
                if (type(record) is not dict or record.get('task_id') != task_id
                        or record.get('candidate_hash') != digest or record.get('status') not in _STATUSES):
                    raise ValueError('Executor binding mismatch')
                record = _copy_json(record, maximum=4*1024*1024)
                if not _execution_accounting_valid(self.case['family'], record):
                    returned_record_file = f'evaluations/evaluation-{index:02d}.returned.json'
                    _write(self.output_dir/returned_record_file, record)
                    raise ExecutionAccountingError('Incomplete evaluator execution accounting')
                self.counts['sandbox_calls'] += len(record['executions'])
            except Exception as error:
                self.infrastructure_error_type = type(error).__name__
                self.counts['counts_complete'] = False
                record = dict(task_id=task_id, candidate_hash=digest, status='infrastructure_error',
                    error_kind='controller_or_executor_exception', exception_type=self.infrastructure_error_type)
                if isinstance(error, ExecutionAccountingError):
                    record.update(error_kind='execution_accounting_incomplete',
                                  returned_record_file=returned_record_file)
            relative = f'evaluations/evaluation-{index:02d}.json'
            _write(self.output_dir/relative, record)
            self.candidate['results'].append(record)
            self.candidate['evaluation_files'].append(relative)
            _write(self.output_dir/'candidate.json', self.candidate)
            if record['status'] in ('infrastructure_error', 'invalid_request'):
                self.halted = True
                break
        self.candidate['status'] = 'infrastructure_error' if self.halted else 'evaluated'
        self.candidate['score'] = summarize_scores(self.case, self.candidate['results'], n_params)
        self.candidate['forecast'] = check_forecast(self.case, auxiliary.get('forecast'), self.candidate['score'])
        _write(self.output_dir/'candidate.json', self.candidate)
        _write(self.output_dir/'controller-summary.json', self.summary())
        return {key: copy.deepcopy(self.candidate[key]) for key in
                ('candidate_id', 'source_sha256', 'status', 'score', 'edit', 'forecast')}

    def summary(self):
        return dict(version=VERSION, **_binding(self.case), attempts=len(self.attempts),
            candidate=copy.deepcopy(self.candidate), halted=self.halted,
            infrastructure_error_type=self.infrastructure_error_type, counts=copy.deepcopy(self.counts),
            generated_candidates=int(self.candidate is not None), model_calls_owned=0, sealed_tasks_executed=0)
