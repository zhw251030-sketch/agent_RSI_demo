"""Bounded, non-resumable orchestration of the already allocated 36 slots.

The host owns the provider, budget ledger and pre-action runtime guard. This
module owns ordering, shared contexts, raw measurement binding and stopping.
Synthetic runs use explicitly synthetic executors; they never create or pass
a production EvaluationGate. Neither a successful simulation nor an accepted
policy proposal is evidence of scientific improvement.
"""
import copy
import hashlib
import math
from pathlib import Path
import time

from . import goal_alignment
from . import strategy_binding as binding
from . import strategy_learning as learning
from .revision_policy import S0, validate_policy
from .role_executor import RoleExecutor, LIMITS, runtime_inventory
from .strategy_partition import safe_path

VERSION = 'strategy-pair-run-v0.1'


class _SchedulerError(ValueError):
    """Only fixed host-authored error messages may enter the public summary."""


def _require(condition, message):
    if not condition:
        raise _SchedulerError(message)


def _read(root, ref):
    _require(binding.file_ref(root, ref['path']) == ref, 'Frozen dependency changed')
    return binding._json(safe_path(root, ref['path']).read_bytes())


def _raw(root, ref):
    _require(binding.file_ref(root, ref['path']) == ref, 'Frozen source changed')
    return safe_path(root, ref['path']).read_bytes()


def _write(root, relative, value):
    path = safe_path(root, relative)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        stream.write(binding.canonical(value) + b'\n')
    return binding.file_ref(root, relative)


def project_evaluation(root, state_id, refs, *, source, n_params, policy_sha256,
                       role, evidence_kind, evaluation_gate=None):
    """Validate evaluation-state receipts, including learning-task feedback.

    The old selection binder intentionally has no evaluation entrypoint. This
    successor verifies the added gate field without editing historic modules.
    Synthetic input remains explicitly labelled and cannot authorize task data.
    """
    _require(state_id in binding.EVALUATION_STATES, 'Evaluation state required')
    _require(evidence_kind in ('observed', 'synthetic'), 'Evidence kind')
    if evidence_kind == 'observed':
        gate_hash = binding.authorize_state_phase(root, state_id, evaluation_gate=evaluation_gate)
    else:
        _require(evaluation_gate is None, 'Synthetic projection cannot carry a production gate')
        gate_hash = None
    slots, partition = binding._fixed_metadata(root, {})
    slot = slots[state_id]
    family = slot['family']
    _require(role in ('learning', 'evaluation') and (role != 'learning' or family == 'planning'),
             'Invalid evaluation-state feedback role')
    tasks = ([x['task_id'] for x in partition['planning']['tasks'] if x['role'] == 'learning']
             if role == 'learning' else slot['task_ids'])
    entries = binding._data_entries(partition, family, tasks, role)
    _require(len(refs) == len(entries) and len({r['path'] for r in refs}) == len(refs),
             'Incomplete evaluation-state observations')
    files, runtime = runtime_inventory()
    for item in files:
        _raw(root, item)
    source_hash = hashlib.sha256(source.encode('utf-8')).hexdigest()
    rows = []
    for ref, entry in zip(refs, entries):
        value = _read(root, ref)
        folder = str(Path(ref['path']).parent).replace('\\', '/')
        request_ref = binding.file_ref(root, folder + '/request.json')
        request = _read(root, request_ref)
        expected = dict(version='role-executor-v0.1', role=role, family=family,
            task_id=entry['task_id'], candidate_sha256=source_hash, n_params=n_params,
            strategy_version=policy_sha256, partition_sha256=binding.PARTITION_SHA256,
            data_sha256=entry['data_sha256'], domain_sha256=entry['domain_sha256'],
            evaluator_sha256=runtime, metric_scope=role if family == 'planning' else 'train', limits=LIMITS)
        if role == 'evaluation' and evidence_kind == 'observed':
            expected['evaluation_gate_sha256'] = gate_hash
        _require(request == expected and value.get('request_sha256') == request_ref['sha256'],
                 'Evaluation request or gate provenance mismatch')
        _require(_raw(root, binding.file_ref(root, folder + '/source.py')) == source.encode(),
                 'Evaluation source mismatch')
        renamed = {'role': 'task_role', 'candidate_sha256': 'candidate_hash'}
        _require(all(value.get(renamed.get(k, k)) == v for k, v in expected.items()),
                 'Evaluation result provenance mismatch')
        _require(value.get('journal_path') == ref['path'] and value.get('runtime_files') == files
                 and value.get('record_kind') == 'executor_observation'
                 and value.get('model_calls') == 0 and value.get('sealed_tasks_executed') == 0,
                 'Evaluation journal identity/runtime/activity mismatch')
        if evidence_kind == 'synthetic':
            _require(value.get('evidence_kind') == 'synthetic', 'Synthetic receipt label missing')
        else:
            _require(value.get('evidence_kind') != 'synthetic', 'Synthetic receipt in observed run')
        status = value.get('status')
        _require(status in binding._MEASURED | {'infrastructure_error'}, 'Invalid task status')
        executions = value.get('executions')
        _require(type(executions) is list, 'Missing execution observations')
        if status in binding._MEASURED:
            expected_last = status if status in ('timeout', 'resource_limit', 'output_limit', 'candidate_process_error') else 'completed'
            _require(executions and executions[-1].get('status') == expected_last,
                     'Task status contradicts execution')
        if 'validator' in value:
            _require(type(value['validator']) is dict and status in ('success', 'task_failure', 'infrastructure_error'),
                     'Unexpected validator on pre-validation result')
            if value['validator'].get('status') in ('valid', 'invalid'):
                _require(status == ('success' if value['validator']['status'] == 'valid' else 'task_failure'),
                         'Task status contradicts VAL')
        row = dict(task_id=entry['task_id'], status=status, candidate_hash=source_hash,
            data_sha256=binding.digest(entries), evaluator_sha256=runtime,
            metric_scope=expected['metric_scope'])
        for key in ('error_kind', 'exception_type', 'candidate_line', 'first_invalid_action', 'plan_length'):
            if value.get(key) is not None:
                if key in ('error_kind', 'exception_type'):
                    _require(type(value[key]) is str and 0 < len(value[key]) <= 128,
                             'Invalid observed diagnostic string')
                else:
                    _require(type(value[key]) is int and (1 if key == 'candidate_line' else 0) <= value[key] <= 1000000,
                             'Invalid observed diagnostic location')
                row[key] = value[key]
        if family == 'planning' and status in ('success', 'task_failure'):
            _require(value.get('validator', {}).get('status') == ('valid' if status == 'success' else 'invalid')
                     and executions == [dict(executions[0], phase='plan', status='completed')],
                     'Planning verdict lacks completed plan observation')
        if family == 'symbolic' and status == 'success':
            fit, metrics = value.get('fitting', {}), value.get('metrics', {})
            nmse = metrics.get('nmse')
            _require(type(nmse) in (int, float) and math.isfinite(nmse) and nmse >= 0,
                     'Invalid symbolic measurement')
            _require(fit.get('n_params') == n_params and fit.get('split') == 'train'
                     and fit.get('converged') is True and fit.get('max_nfev') == 100
                     and type(fit.get('params')) is list and len(fit['params']) == n_params
                     and all(type(x) in (int, float) and math.isfinite(x) for x in fit['params'])
                     and type(fit.get('nfev')) is int and 1 <= fit['nfev'] <= 100
                     and type(fit.get('candidate_calls')) is int and 1 <= fit['candidate_calls'] <= 100000
                     and [x.get('phase') for x in executions] == ['fit', 'predict']
                     and all(x.get('status') == 'completed' for x in executions),
                     'Missing symbolic fit and predict evidence')
            row['metrics'] = copy.deepcopy(metrics)
        rows.append(row)
    return rows


class _Run:
    def __init__(self, root, output, session_runner, executor_factory, request_template,
                 budget, evidence_kind, pre_action_guard):
        self.root, self.output = Path(root), output
        self.session_runner, self.executor_factory = session_runner, executor_factory
        self.kind, self.guard = evidence_kind, pre_action_guard
        self.template, self.budget = copy.deepcopy(request_template), copy.deepcopy(budget)
        self.states, self.partition = binding._fixed_metadata(root, {})
        allocation = _read(root, dict(path=binding.FUTURE_ALLOCATION, sha256=binding.FUTURE_ALLOCATION_SHA256))
        self.slots = allocation['slots']
        _require(len(self.slots) == 36 and [s['phase'] for s in self.slots] ==
                 ['update'] * 4 + ['selection'] * 16 + ['evaluation'] * 16, 'Frozen slot allocation')
        self.rows = [dict(slot=copy.deepcopy(s), status='not_started') for s in self.slots]
        self.events, self.request_ids, self.measurement_paths = [], set(), set()
        self.proposals, self.decisions, self.contexts, self.baselines, self.sessions = {}, {}, {}, {}, []
        self.context_refs, self.allocations = {}, {}
        self.gate, self.synthetic_phase, self.failure, self.active = None, None, None, None
        self.selected, self.evaluation_results = {}, {}

    def write(self, name, value):
        return _write(self.root, self.output + '/' + name, value)

    def event(self, kind, **fields):
        value = dict(ordinal=len(self.events) + 1, kind=kind, monotonic_ns=time.monotonic_ns(),
            previous_sha256=binding.digest(self.events[-1]) if self.events else None, **fields)
        self.write('events/' + str(value['ordinal']).zfill(5) + '.json', value)
        self.events.append(value)

    def check(self, action, **fields):
        if self.guard is not None:
            self.guard(action, **fields)

    def authorize(self, state_id):
        if state_id in binding.EVALUATION_STATES and self.kind == 'synthetic':
            _require(self.synthetic_phase is not None and set(self.decisions) == {'r1', 'r2'},
                     'Both synthetic decisions must precede evaluation simulation')
            _require(_read(self.root, self.synthetic_phase)['decisions'] == self.decisions,
                     'Synthetic phase receipt changed')
            for ref in self.decisions.values():
                value = _read(self.root, ref)
                _require(value['replay']['evidence_kind'] == 'synthetic', 'Synthetic decision label')
            return
        binding.authorize_state_phase(self.root, state_id, evaluation_gate=self.gate)

    def execute(self, state_id, role, task_ids, source, n_params, policy_hash, candidate_id):
        self.authorize(state_id)
        self.check('executor_construction', state_id=state_id, role=role)
        executor = self.executor_factory(self.root, role=role,
            evaluation_gate=self.gate if role == 'evaluation' else None)
        if self.kind == 'synthetic':
            _require(not isinstance(executor, RoleExecutor) and getattr(executor, 'synthetic_only', False) is True,
                     'Synthetic run requires a synthetic executor instance')
        refs = []
        for task_id in task_ids:
            self.authorize(state_id)
            self.check('execution', state_id=state_id, role=role, task_id=task_id)
            result = executor.evaluate(self.states[state_id]['family'], task_id, source,
                n_params=n_params, candidate_id=candidate_id, parent_id=state_id, strategy_version=policy_hash)
            _require(type(result) is dict and type(result.get('journal_path')) is str, 'Missing executor journal')
            if self.kind == 'synthetic':
                _require(result.get('evidence_kind') == 'synthetic', 'Synthetic executor lost evidence label')
            else:
                _require(result.get('evidence_kind') != 'synthetic', 'Synthetic executor in observed run')
            ref = binding.file_ref(self.root, result['journal_path'])
            _require(_read(self.root, ref) == result and ref['path'] not in self.measurement_paths,
                     'Executor result changed or reused')
            self.measurement_paths.add(ref['path'])
            refs.append(ref)
            self.event('measurement_recorded', state_id=state_id, role=role, receipt=ref,
                       evidence_kind=self.kind, status=result.get('status'))
            if result.get('status') == 'infrastructure_error':
                raise _SchedulerError('Infrastructure failure; remaining slots stay unstarted')
        return refs

    def baseline(self, state_id):
        self.authorize(state_id)
        self.event('baseline_started', state_id=state_id)
        slot = self.states[state_id]
        source_ref = dict(path=str(Path(binding.SOURCE_FREEZE).parent / 'sessions' / state_id / 'source.py').replace('\\', '/'),
                          sha256=slot['candidate']['source_sha256'])
        source = _raw(self.root, source_ref).decode('utf-8')
        planning = slot['family'] == 'planning'
        role = 'learning' if planning else slot['role']
        tasks = ([x['task_id'] for x in self.partition['planning']['tasks'] if x['role'] == 'learning']
                 if planning else slot['task_ids'])
        refs = self.execute(state_id, role, tasks, source, slot['candidate']['n_params'], 'baseline', state_id + '-baseline')
        if state_id in binding.SELECTION_STATES:
            rows = binding.project_baseline(self.root, state_id, refs)
        else:
            rows = project_evaluation(self.root, state_id, refs, source=source,
                n_params=slot['candidate']['n_params'], policy_sha256='baseline', role=role,
                evidence_kind=self.kind, evaluation_gate=self.gate)
        context = dict(state_id=state_id, family=slot['family'], source=source,
            source_sha256=source_ref['sha256'], n_params=slot['candidate']['n_params'],
            baseline_feedback=rows, **binding.task_contract(self.root, state_id))
        learning.render_actor_packet(self.root, context, S0)
        self.contexts[state_id], self.baselines[state_id] = context, refs
        self.context_refs[state_id] = self.write('contexts/' + state_id + '.json', context)
        self.event('baseline_frozen', state_id=state_id, context=self.context_refs[state_id], measurements=refs)

    def session(self, slot, packet):
        self.check('network', slot_id=slot['id'], phase=slot['phase'])
        self.event('session_started', slot_id=slot['id'], phase=slot['phase'], packet_sha256=binding.digest(packet))
        directory = safe_path(self.root, self.output + '/sessions/' + slot['id'])
        directory.mkdir(parents=True, exist_ok=False)
        result = self.session_runner(copy.deepcopy(slot), copy.deepcopy(packet), directory)
        _require(type(result) is dict, 'Invalid session result')
        self.active['session'] = copy.deepcopy(result)
        self.write('session-results/' + slot['id'] + '.json', result)
        if result.get('status') != 'accepted':
            raise _SchedulerError('Session did not accept exactly one valid submission')
        if self.kind == 'observed':
            for key in ('sdk_submission', 'input_audit', 'response'):
                _require(type(result.get(key)) is dict, 'Observed session requires SDK acceptance and transport receipts')
                _read(self.root, result[key])
            self.check('accepted_session', slot_id=slot['id'], result=copy.deepcopy(result))
        request_id = result.get('request_id')
        _require(type(request_id) is str and request_id and request_id not in self.request_ids,
                 'Missing or reused global request ID')
        self.request_ids.add(request_id)
        actual = _read(self.root, result['request'])
        actual_packet, normalized = binding._request_packet(actual)
        _require(actual_packet == packet, 'Actual request differs from frozen packet')
        if slot['phase'] != 'update':
            _require(normalized == self.template, 'Actual actor request differs from frozen request template')
        self.event('session_accepted', slot_id=slot['id'], request_id=request_id, request=result['request'])
        return result

    def update(self, slot, packet):
        result = self.session(slot, packet)
        policy = validate_policy(result.get('policy'))
        snapshot = binding.policy_snapshot(self.root, policy)
        ref = self.write('proposals/' + slot['id'] + '.json', snapshot)
        self.proposals[slot['id']] = ref

    def actor(self, slot):
        state_id, rep, arm, phase = slot['state_id'], slot['replicate'], slot['arm'], slot['phase']
        self.authorize(state_id)
        policy = self.parent if arm == 'fixed' else (
            _read(self.root, self.proposals[rep + '-update-updated']) if phase == 'selection' else self.selected[rep])
        packet = learning.render_actor_packet(self.root, self.contexts[state_id], policy['content'])
        result = self.session(slot, packet)
        submission = _read(self.root, result['submission'])
        expected = dict(version='strategy-submission-v0.1', slot_id=slot['id'], request_id=result['request_id'],
            request_sha256=result['request']['sha256'], status='accepted',
            source_sha256=result['source']['sha256'], n_params=submission.get('n_params'))
        _require(submission == expected, 'Actor submission is not bound to accepted request/source')
        n_params = submission['n_params']
        _require(type(n_params) is int and 0 <= n_params <= 16 and
                 (self.states[state_id]['family'] != 'planning' or n_params == 0), 'Invalid actor parameter count')
        source = _raw(self.root, result['source']).decode('utf-8')
        refs = self.execute(state_id, phase, self.states[state_id]['task_ids'], source, n_params,
                            policy['sha256'], slot['id'])
        item = dict(slot_id=slot['id'], state_id=state_id, arm=arm, request_id=result['request_id'],
            request=result['request'], submission=result['submission'], source=result['source'], evaluations=refs)
        self.sessions.append(item)
        self.write('bound-sessions/' + slot['id'] + '.json', item)
        if phase == 'evaluation':
            rows = project_evaluation(self.root, state_id, refs, source=source, n_params=n_params,
                policy_sha256=policy['sha256'], role='evaluation', evidence_kind=self.kind, evaluation_gate=self.gate)
            self.evaluation_results[slot['id']] = dict(results=rows, n_params=n_params,
                policy_sha256=policy['sha256'], source_sha256=result['source']['sha256'])

    def decisions_and_gate(self):
        self.check('selection_freeze')
        for rep in ('r1', 'r2'):
            manifest = dict(version=binding.VERSION, evidence_kind=self.kind, replicate_id=rep,
                allocation=self.allocations[rep], parent_policy=self.parent_ref,
                candidate_policy=self.proposals[rep + '-update-updated'],
                contexts={s: self.context_refs[s] for s in binding.SELECTION_STATES},
                baseline_evaluations={s: self.baselines[s] for s in binding.SELECTION_STATES},
                request_template=self.template_ref, budget=self.budget_ref,
                sessions=[s for s in self.sessions if s['slot_id'].startswith(rep + '-selection-')])
            ref = self.write('selection/' + rep + '-manifest.json', manifest)
            decision = binding.freeze_selection(self.root, ref['path'], ref['sha256'],
                self.output + '/selection/' + rep + '-decision.json')
            self.decisions[rep] = decision
            self.selected[rep] = _read(self.root, decision)['selected_policy']
            self.event('decision_frozen', replicate=rep, decision=decision)
        self.check('evaluation_gate')
        if self.kind == 'observed':
            self.gate = binding.freeze_evaluation_gate(self.root, self.decisions, self.output + '/evaluation-gate.json')
        else:
            self.synthetic_phase = self.write('synthetic-phase.json', dict(
                version='synthetic-phase-only-v0.1', evidence_kind='synthetic',
                decisions=self.decisions, grants_task_data_access=False))
        self.event('both_decisions_frozen', decisions=self.decisions, evidence_kind=self.kind)

    def evaluate_pairs(self):
        pairs = []
        for rep in ('r1', 'r2'):
            for state in binding.EVALUATION_STATES:
                old = self.evaluation_results[f'{rep}-evaluation-{state}-fixed']
                new = self.evaluation_results[f'{rep}-evaluation-{state}-updated']
                if self.states[state]['family'] == 'planning':
                    result = goal_alignment.assess_planning(old['results'], new['results'],
                        development_ids=self.states[state]['task_ids'], public_ids=[])
                elif all(item['results'][0]['status'] == 'success' for item in (old, new)):
                    result = goal_alignment.assess_symbolic(*[dict(nmse=item['results'][0]['metrics']['nmse'],
                        n_params=item['n_params']) for item in (old, new)])
                else:
                    result = dict(decision='unknown', reason_codes=['symbolic_final_without_complete_numeric_score'])
                pairs.append(dict(replicate=rep, state_id=state, assessment=result,
                    attribution='no_policy_change' if old['policy_sha256'] == new['policy_sha256'] else 'paired_policy_comparison',
                    parent=old, candidate=new))
        return pairs

    def run(self):
        self.template_ref = self.write('actor-request-template.json', self.template)
        self.budget_ref = self.write('budget.json', self.budget)
        self.parent = binding.policy_snapshot(self.root, S0)
        self.parent_ref = self.write('parent-policy.json', self.parent)
        self.write('allocation.json', dict(version=VERSION, evidence_kind=self.kind, slots=self.slots))
        status, pairs = 'stopped', []
        try:
            package = learning.build_learning_package(self.root)
            packet = learning.render_update_packet(self.root, package)
            self.write('learning-package.json', package)
            packet_ref = self.write('update-packet.json', packet)
            self.event('learning_frozen', packet=packet_ref)
            for index, slot in enumerate(self.slots):
                if index == 4:
                    self.active = None
                    self.check('proposal_freeze')
                    proposal_ref = self.write('proposal-freeze.json', dict(proposals=self.proposals, evidence_kind=self.kind))
                    self.event('proposals_frozen', proposals=proposal_ref)
                    for state in binding.SELECTION_STATES:
                        self.baseline(state)
                    for rep in ('r1', 'r2'):
                        allocation = binding.build_selection_allocation(self.root, self.contexts,
                            self.template_ref, self.budget_ref, rep)
                        self.allocations[rep] = self.write('selection/' + rep + '-allocation.json', allocation)
                    self.event('selection_allocations_frozen', allocations=self.allocations)
                if index == 20:
                    self.active = None
                    self.decisions_and_gate()
                    for state in binding.EVALUATION_STATES:
                        self.baseline(state)
                    self.event('evaluation_contexts_frozen', contexts={s: self.context_refs[s] for s in binding.EVALUATION_STATES})
                self.active = self.rows[index]
                self.active['status'] = 'started'
                if slot['phase'] == 'update':
                    self.update(slot, packet)
                else:
                    self.actor(slot)
                self.active['status'] = 'completed'
                self.event('slot_completed', slot_id=slot['id'])
            self.active = None
            pairs = self.evaluate_pairs()
            status = 'complete'
        except Exception as error:
            if self.active is not None:
                self.active['status'] = 'failed'
            self.failure = dict(error_type=type(error).__name__, message=(str(error) if isinstance(error, _SchedulerError)
                else 'Host callback or dependency validation failed; no further action was attempted'),
                slot_id=self.active['slot']['id'] if self.active else None,
                session=self.active.get('session') if self.active else None)
            self.event('run_stopped', failure=self.failure)
        report = dict(version=VERSION, evidence_kind=self.kind, status=status, failure=self.failure,
            slots=self.rows, slot_counts={key: sum(row['status'] == key for row in self.rows)
                for key in ('completed', 'failed', 'not_started')},
            decisions=self.decisions, proposals=self.proposals,
            production_evaluation_gate=dict(path=self.gate.path, sha256=self.gate.sha256) if self.gate else None,
            synthetic_phase=self.synthetic_phase, events=self.events, evaluation_pairs=pairs,
            accepted_request_count=len(self.request_ids), measurement_record_count=len(self.measurement_paths),
            boundary='Synthetic receipts are not task scores; observed requests require SDK and provider audit. No resumption or replacement slots.')
        self.write('summary.json', report)
        return report


def run_strategy_pair(root, output, *, session_runner, request_template, budget,
                      executor_factory=RoleExecutor, evidence_kind='observed', pre_action_guard=None):
    """Run once in a fresh directory; failures preserve all completed evidence.

    session_runner(slot, packet, directory) returns status, globally unique
    request_id, actual request file ref, and either policy or source/submission
    refs. It must use a shared bounded ledger and audit genuine SDK acceptance.
    pre_action_guard(action, **fields) is called before network/executor/gates.
    It must reject changed runtime/configuration before any external activity.
    """
    _require(evidence_kind in ('observed', 'synthetic'), 'Evidence kind')
    _require(type(request_template) is dict and type(budget) is dict, 'Frozen template and budget required')
    if evidence_kind == 'synthetic':
        _require(getattr(executor_factory, 'synthetic_only', False) is True
                 and not (isinstance(executor_factory, type) and issubclass(executor_factory, RoleExecutor)),
                 'A synthetic run requires a synthetic-only executor factory')
    else:
        _require(executor_factory is RoleExecutor and callable(pre_action_guard),
                 'Observed execution requires the production executor and a pre-action guard')
    directory = safe_path(root, output)
    directory.mkdir(parents=True, exist_ok=False)
    run = _Run(root, output, session_runner, executor_factory, request_template, budget,
               evidence_kind, pre_action_guard)
    return run.run()
