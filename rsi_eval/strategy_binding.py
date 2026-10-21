"""Bind trusted-client files to the pure strategy selector and phase gate.

This validates concrete request/source/executor files, not only hashes supplied
to select_strategy. It is not provider attestation or a proof of historical
write times. An accepted host submission is not independently an SDK acceptance
receipt. A future controller must freeze these dependencies before dispatch.
No candidate execution, model call, or task-data read occurs in this module.
"""
from dataclasses import dataclass
import copy
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re

from . import goal_alignment
from .revision_policy import S0, validate_policy
from .strategy_learning import render_actor_packet
from .strategy_partition import safe_path

VERSION = 'strategy-binding-v0.1'
SOURCE_FREEZE = 'artifacts/state-generation/2026-10-21/v02/source-freeze.json'
SOURCE_FREEZE_SHA256 = 'f37695fa966f2e44027cc1b93d66a05f04d406e2b0b2f6808d73517c90d5004c'
PARTITION = 'configs/tasks/strategy-partition-v0.1.json'
PARTITION_SHA256 = 'bf49dd855d591863bc938a37d889cc5afc9a2ea2e1bfab87d71a951c39692ed7'
INPUT_FREEZE = 'artifacts/state-generation/2026-10-21/v02/input-freeze.json'
INPUT_FREEZE_SHA256 = '64f1e2b8d1a2c77959af0fb69c77c912d9695a56dedaf29d8c902b8e98149964'
FUTURE_ALLOCATION = 'configs/pilots/strategy-pair-allocation-v0.1.json'
FUTURE_ALLOCATION_SHA256 = 'f75b2ea2d63c28a4b6e273cd594d1ef92ac4d1847407e36d7f2a81e496d9ea02'
SELECTION_STATES = ('P-select-1', 'S-select-1', 'P-select-2', 'S-select-2')
EVALUATION_STATES = ('P-eval-1', 'S-bact-eval-1', 'P-eval-2', 'S-stress-eval-1')
_HASH = re.compile(r'[0-9a-f]{64}\Z')
_MEASURED = frozenset({'success', 'task_failure', 'invalid_output', 'candidate_error',
    'candidate_process_error', 'timeout', 'resource_limit', 'output_limit'})


def canonical(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True,
                      separators=(',', ':')).encode('utf-8')


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _json(raw):
    def pairs(values):
        result = {}
        for key, value in values:
            _require(key not in result, 'Duplicate JSON key')
            result[key] = value
        return result
    def invalid(value):
        raise ValueError('Nonfinite JSON constant')
    value = json.loads(raw.decode('utf-8'), object_pairs_hook=pairs, parse_constant=invalid)
    canonical(value)  # Also reject overflow literals such as 1e999.
    return value


def file_ref(root, relative):
    _require(type(relative) is str and relative and '\\' not in relative
             and not PurePosixPath(relative).is_absolute()
             and PurePosixPath(relative).as_posix() == relative
             and '..' not in PurePosixPath(relative).parts, 'Noncanonical file reference path')
    path = safe_path(root, relative)
    _require(path.is_file() and path.stat().st_size <= 4_000_000, 'File absent or too large')
    return {'path': relative, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def _read(root, ref, inventory, *, json_value=True):
    _require(type(ref) is dict and set(ref) == {'path', 'sha256'}
             and type(ref['sha256']) is str and _HASH.fullmatch(ref['sha256']), 'Invalid file reference')
    actual = file_ref(root, ref['path'])
    _require(actual == ref, 'Bound file bytes changed: ' + ref['path'])
    inventory[ref['path']] = ref['sha256']
    raw = safe_path(root, ref['path']).read_bytes()
    return _json(raw) if json_value else raw


def _fixed_metadata(root, inventory):
    freeze = _read(root, {'path': SOURCE_FREEZE, 'sha256': SOURCE_FREEZE_SHA256}, inventory)
    partition = _read(root, {'path': PARTITION, 'sha256': PARTITION_SHA256}, inventory)
    slots = {slot['id']: slot for slot in freeze['slots']}
    _require(set(slots) == set(SELECTION_STATES + EVALUATION_STATES), 'Frozen source allocation')
    return slots, partition


def task_contract(root, state_id, *, _inventory=None):
    """Derive allowed actor task information from the original frozen inputs."""
    inventory = {} if _inventory is None else _inventory
    _require(state_id in SELECTION_STATES + EVALUATION_STATES, 'Unknown task contract state')
    frozen = _read(root, dict(path=INPUT_FREEZE, sha256=INPUT_FREEZE_SHA256), inventory)
    slots = [slot for slot in frozen['slots'] if slot['id'] == state_id]
    _require(len(slots) == 1, 'Task contract slot')
    slot = slots[0]
    packet = slot['packet']
    _require(digest(packet) == slot['packet_sha256'], 'Task contract packet hash')
    spec = {key: value for key, value in packet.items() if key not in ('version', 'family', 'examples', 'instructions')}
    if slot['family'] == 'planning':
        original = packet['instructions']
        start = original.index('Define `get_plan')
        end = original.index('Use only Python', start)
        spec['instructions'] = original[start:end].strip() + (
            '\nUse only the Python standard library. Do not access files, networks, subprocesses '
            'or other programs. Preserve the exact domain definition and required output format.')
    else:
        spec['instructions'] = (
            'Define equation with the listed input arrays in their exact order followed by params. '
            'Inputs are read-only one-dimensional NumPy arrays of equal length; np is available. '
            'Return finite numeric predictions of shape (len(u0),). Declare 0 through 16 parameters '
            'and use only valid indices. The host fits them from ones by bounded least squares. '
            'Do not access files, networks, subprocesses or extra packages. Do not encode row '
            'indices, sampled labels or lookup tables. Training NMSE is within-task fit only.')
    objective = ('Increase successful task outcomes without losing an earlier success; '
                 'the host uses the frozen goal acceptance rule.' if slot['family'] == 'planning' else
                 'Reduce training NMSE by more than 1e-5, or reduce declared parameters while '
                 'keeping NMSE increase below 1e-5; declared count is only a complexity proxy.')
    return dict(task_text=canonical(dict(task_specification=spec)).decode('utf-8'),
        public_examples=copy.deepcopy(packet.get('examples', [])), objective=objective)


def _data_entries(partition, family, task_ids, role='selection'):
    if family == 'planning':
        mapping = {x['task_id']: x for x in partition['planning']['tasks']}
        entries = [dict(task_id=t, data_sha256=mapping[t]['sha256'],
                        domain_sha256=partition['planning']['domain_sha256']) for t in task_ids]
        _require(all(mapping[t]['role'] == role for t in task_ids), 'Cross-role planning score')
    else:
        mapping = {x['task_id']: x for x in partition['symbolic']['files'] if x['split'] == 'train'}
        entries = [dict(task_id=t, data_sha256=mapping[t]['sha256'], domain_sha256=None) for t in task_ids]
        _require(all(mapping[t]['role'] == role for t in task_ids), 'Cross-role symbolic score')
    return entries


def policy_snapshot(root, policy):
    policy = validate_policy(policy)
    body = dict(content=policy, renderer_sha256=file_ref(root, 'rsi_eval/revision_policy.py')['sha256'])
    return dict(body, sha256=digest(body))


def _policy(root, value):
    _require(type(value) is dict and set(value) == {'content', 'renderer_sha256', 'sha256'}, 'Policy snapshot fields')
    _require(value == policy_snapshot(root, value['content']), 'Policy snapshot/runtime mismatch')
    return value


def build_selection_allocation(root, contexts, request_template_ref, budget_ref, replicate_id):
    """Construct one four-state allocation per proposal, never merge r1/r2."""
    from .role_executor import runtime_inventory
    _require(replicate_id in ('r1', 'r2') and set(contexts) == set(SELECTION_STATES), 'Selection replicate/states')
    inventory = {}
    slots, partition = _fixed_metadata(root, inventory)
    _read(root, request_template_ref, inventory)
    _read(root, budget_ref, inventory)
    _, evaluator_hash = runtime_inventory()
    states = []
    for identifier in SELECTION_STATES:
        slot, context = slots[identifier], contexts[identifier]
        candidate = slot['candidate']
        source_ref = {'path': str(Path(SOURCE_FREEZE).parent / 'sessions' / identifier / 'source.py').replace('\\', '/'),
                      'sha256': candidate['source_sha256']}
        raw = _read(root, source_ref, inventory, json_value=False)
        _require(context['state_id'] == identifier and context['family'] == slot['family']
                 and context['source'].encode('utf-8') == raw
                 and context['source_sha256'] == candidate['source_sha256']
                 and context['n_params'] == candidate['n_params'], 'Context does not use frozen source')
        contract = task_contract(root, identifier, _inventory=inventory)
        _require(all(context[key] == value for key, value in contract.items()), 'Actor task contract differs from frozen inputs')
        render_actor_packet(root, context, S0)
        planning = slot['family'] == 'planning'
        tasks = slot['task_ids']
        states.append(dict(id=identifier, family=slot['family'],
            base_source_sha256=candidate['source_sha256'], base_n_params=candidate['n_params'],
            task_ids=tasks, development_ids=tasks if planning else [], public_ids=[],
            metric_scope='selection' if planning else 'train',
            feedback_sha256=digest(context['baseline_feedback']),
            model_config_sha256=request_template_ref['sha256'], budget_sha256=budget_ref['sha256'],
            evaluator_sha256=evaluator_hash, data_sha256=digest(_data_entries(partition, slot['family'], tasks)),
            replicate_ids=[replicate_id]))
    body = dict(version='goal-selection-allocation-v0.1', role='selection', states=states)
    return dict(body, sha256=digest(body))


def _request_packet(body):
    _require(type(body) is dict and type(body.get('messages')) is list, 'Actual model request missing messages')
    users = [i for i, message in enumerate(body['messages']) if message.get('role') == 'user']
    _require(len(users) == 1, 'Exactly one actor user packet is required')
    index = users[0]
    content = body['messages'][index].get('content')
    if type(content) is list:
        _require(len(content) == 1 and type(content[0]) is dict
                 and set(content[0]) == {'type', 'text'} and content[0]['type'] == 'text', 'Actor content parts')
        content = content[0]['text']
    _require(type(content) is str, 'Actor user packet must be serialized JSON')
    packet = _json(content.encode('utf-8'))
    normalized = copy.deepcopy(body)
    normalized['messages'][index]['content'] = None
    return packet, normalized


def _raw_evaluation(root, ref, source, n_params, policy_hash, state, data, inventory, role='selection'):
    from .role_executor import LIMITS, runtime_inventory
    value = _read(root, ref, inventory)
    _require(value.get('version') == 'role-executor-v0.1'
             and value.get('record_kind') == 'executor_observation'
             and value.get('journal_path') == ref['path'], 'Not a bound role executor journal')
    expected = dict(role=role, family=state['family'], task_id=data['task_id'],
        candidate_sha256=hashlib.sha256(source).hexdigest(), n_params=n_params,
        strategy_version=policy_hash, partition_sha256=PARTITION_SHA256,
        data_sha256=data['data_sha256'], domain_sha256=data['domain_sha256'],
        evaluator_sha256=state['evaluator_sha256'], metric_scope=state['metric_scope'], limits=LIMITS)
    directory = str(Path(ref['path']).parent).replace('\\', '/')
    request_ref = file_ref(root, directory + '/request.json')
    request = _read(root, request_ref, inventory)
    _require(request == dict(version='role-executor-v0.1', **expected), 'Executor request context mismatch')
    stored_source = _read(root, file_ref(root, directory + '/source.py'), inventory, json_value=False)
    _require(stored_source == source and value.get('request_sha256') == request_ref['sha256'], 'Executor source/request mismatch')
    renamed = {'role': 'task_role', 'candidate_sha256': 'candidate_hash'}
    _require(all(value.get(renamed.get(key, key)) == expected[key] for key in expected), 'Executor result context mismatch')
    files, runtime_hash = runtime_inventory()
    _require(value.get('runtime_files') == files and runtime_hash == state['evaluator_sha256'], 'Executor runtime changed')
    for item in files:
        _read(root, item, inventory, json_value=False)
    _require(value.get('model_calls') == 0 and value.get('sealed_tasks_executed') == 0
             and type(value.get('executions')) is list, 'Executor activity bounds')
    status = value.get('status')
    _require(status in _MEASURED | {'infrastructure_error'}, 'Invalid executor status')
    if status in _MEASURED:
        _require(bool(value['executions']), 'Measured result has no sandbox observation')
        last_status = value['executions'][-1].get('status')
        expected_last = status if status in {'timeout', 'resource_limit', 'output_limit', 'candidate_process_error'} else 'completed'
        _require(last_status == expected_last, 'Outer result contradicts sandbox observation')
    if 'validator' in value:
        verdict = value['validator']
        _require(type(verdict) is dict and status in ('success', 'task_failure', 'infrastructure_error'),
                 'Unexpected validator on pre-validation result')
        if verdict.get('status') in ('valid', 'invalid'):
            _require(status == ('success' if verdict['status'] == 'valid' else 'task_failure'),
                     'Outer status contradicts raw validator verdict')
    if state['family'] == 'planning' and status in ('success', 'task_failure'):
        expected_verdict = 'valid' if status == 'success' else 'invalid'
        _require(type(value.get('validator')) is dict and value['validator'].get('status') == expected_verdict,
                 'Planning score contradicts raw validator verdict')
        _require(len(value['executions']) == 1 and value['executions'][0].get('phase') == 'plan'
                 and value['executions'][0].get('status') == 'completed', 'Planning score lacks completed execution')
    row = dict(task_id=data['task_id'], status=status, candidate_hash=expected['candidate_sha256'],
        data_sha256=state['data_sha256'], evaluator_sha256=state['evaluator_sha256'], metric_scope=state['metric_scope'])
    for key in ('error_kind', 'exception_type'):
        if value.get(key) is not None:
            _require(type(value[key]) is str and 0 < len(value[key]) <= 128, 'Invalid observed diagnostic string')
            row[key] = value[key]
    for key in ('candidate_line', 'first_invalid_action', 'plan_length'):
        if value.get(key) is not None:
            lower = 1 if key == 'candidate_line' else 0
            _require(type(value[key]) is int and lower <= value[key] <= 1000000, 'Invalid observed diagnostic location')
            row[key] = value[key]
    if state['family'] == 'symbolic' and status == 'success':
        metrics = value.get('metrics')
        _require(type(metrics) is dict and type(metrics.get('nmse')) in (int, float)
                 and math.isfinite(metrics['nmse']) and metrics['nmse'] >= 0, 'Invalid measured symbolic NMSE')
        fit = value.get('fitting')
        _require(type(fit) is dict and fit.get('n_params') == n_params
                 and fit.get('split') == 'train' and fit.get('converged') is True, 'Missing bound fit metadata')
        _require([x.get('phase') for x in value['executions']] == ['fit', 'predict']
                 and all(x.get('status') == 'completed' for x in value['executions']), 'Missing separate fit/predict observations')
        _require(type(fit.get('params')) is list and len(fit['params']) == n_params
                 and all(type(x) in (int, float) and math.isfinite(x) for x in fit['params'])
                 and type(fit.get('nfev')) is int and 1 <= fit['nfev'] <= 100
                 and type(fit.get('candidate_calls')) is int and 1 <= fit['candidate_calls'] <= 100000
                 and fit.get('max_nfev') == 100, 'Invalid fit numerical metadata')
        row['metrics'] = copy.deepcopy(metrics)
    return row


def project_baseline(root, state_id, references, *, _inventory=None):
    """Verify frozen source feedback: learning seed0 for P, selection train for S.

    Evaluation-state baselines are intentionally unavailable here. Their future
    construction must use authorize_state_phase before any task execution.
    """
    from .role_executor import runtime_inventory
    inventory = {} if _inventory is None else _inventory
    _require(state_id in SELECTION_STATES, 'Only selection-state baseline projection is available')
    slots, partition = _fixed_metadata(root, inventory)
    slot = slots[state_id]
    candidate = slot['candidate']
    source_path = str(Path(SOURCE_FREEZE).parent / 'sessions' / state_id / 'source.py').replace('\\', '/')
    source = _read(root, dict(path=source_path, sha256=candidate['source_sha256']), inventory, json_value=False)
    planning = slot['family'] == 'planning'
    role = 'learning' if planning else 'selection'
    tasks = [t['task_id'] for t in partition['planning']['tasks'] if t['role'] == 'learning'] if planning else ['oscillator2']
    data = _data_entries(partition, slot['family'], tasks, role)
    _, runtime = runtime_inventory()
    state = dict(family=slot['family'], evaluator_sha256=runtime, data_sha256=digest(data),
                 metric_scope=role if planning else 'train')
    _require(type(references) is list and len(references) == len(data)
             and len({r['path'] for r in references}) == len(references), 'Incomplete or duplicated baseline receipts')
    rows = [_raw_evaluation(root, ref, source, candidate['n_params'], 'baseline', state, item, inventory, role)
            for ref, item in zip(references, data)]
    _require(all(row['status'] != 'infrastructure_error' for row in rows), 'Infrastructure failure cannot define baseline feedback')
    return rows


def bind_selection(root, manifest_path, expected_sha256):
    """Replay concrete files into one select_strategy call; never execute code."""
    root = Path(root)
    inventory = {}
    manifest = _read(root, dict(path=manifest_path, sha256=expected_sha256), inventory)
    required = {'version', 'evidence_kind', 'replicate_id', 'allocation', 'parent_policy', 'candidate_policy',
                'contexts', 'baseline_evaluations', 'request_template', 'budget', 'sessions'}
    _require(type(manifest) is dict and set(manifest) == required and manifest['version'] == VERSION,
             'Binding manifest fields/version')
    _require(manifest['evidence_kind'] in ('observed', 'synthetic'), 'Evidence kind')
    replicate = manifest['replicate_id']
    parent = _policy(root, _read(root, manifest['parent_policy'], inventory))
    candidate = _policy(root, _read(root, manifest['candidate_policy'], inventory))
    _require(parent['content'] == S0, 'Parent must be frozen S0')
    for runtime_file in ('rsi_eval/revision_policy.py', 'rsi_eval/goal_alignment.py',
                         'rsi_eval/strategy_binding.py', 'rsi_eval/strategy_learning.py'):
        _read(root, file_ref(root, runtime_file), inventory, json_value=False)
    _read(root, file_ref(root, 'prompts/strategy-pair/actor.md'), inventory, json_value=False)
    contexts = {key: _read(root, ref, inventory) for key, ref in manifest['contexts'].items()}
    _require(set(manifest['baseline_evaluations']) == set(SELECTION_STATES), 'Baseline state allocation')
    for identifier, context in contexts.items():
        rows = project_baseline(root, identifier, manifest['baseline_evaluations'][identifier], _inventory=inventory)
        _require(context['baseline_feedback'] == rows, 'Actor baseline differs from verified raw observations')
        task_contract(root, identifier, _inventory=inventory)
    allocation = _read(root, manifest['allocation'], inventory)
    expected = build_selection_allocation(root, contexts, manifest['request_template'], manifest['budget'], replicate)
    _require(allocation == expected, 'Allocation differs from source/data/context/runtime')
    template = _read(root, manifest['request_template'], inventory)
    _read(root, manifest['budget'], inventory)
    _, partition = _fixed_metadata(root, inventory)
    _require(type(manifest['sessions']) is list and len(manifest['sessions']) == 8, 'Exactly eight finals per proposal')
    future = _read(root, dict(path=FUTURE_ALLOCATION, sha256=FUTURE_ALLOCATION_SHA256), inventory)
    expected_order = [slot['id'] for slot in future['slots'] if slot['phase'] == 'selection' and slot['replicate'] == replicate]
    _require([session.get('slot_id') for session in manifest['sessions']] == expected_order,
             'Selection slots differ from frozen counterbalanced order')
    states = {s['id']: s for s in allocation['states']}
    measurements = {}
    request_ids, request_paths, result_paths = set(), set(), set()
    for session in manifest['sessions']:
        keys = {'slot_id', 'state_id', 'arm', 'request_id', 'request', 'submission', 'source', 'evaluations'}
        _require(type(session) is dict and set(session) == keys, 'Session binding fields')
        identifier, arm = session['state_id'], session['arm']
        _require(identifier in states and arm in ('fixed', 'updated'), 'Unexpected actor slot')
        slot = f'{replicate}-selection-{identifier}-{arm}'
        _require(session['slot_id'] == slot and (identifier, arm) not in measurements, 'Duplicate or wrong allocated slot')
        request_id = session['request_id']
        _require(type(request_id) is str and request_id and request_id not in request_ids, 'Reused request ID')
        request_ids.add(request_id)
        _require(session['request']['path'] not in request_paths, 'Reused model request file')
        request_paths.add(session['request']['path'])
        policy = parent if arm == 'fixed' else candidate
        request = _read(root, session['request'], inventory)
        packet, normalized = _request_packet(request)
        _require(normalized == template and packet == render_actor_packet(root, contexts[identifier], policy['content']),
                 'Actual request differs from frozen common context/policy/settings')
        submission = _read(root, session['submission'], inventory)
        subkeys = {'version', 'slot_id', 'request_id', 'request_sha256', 'status', 'source_sha256', 'n_params'}
        _require(type(submission) is dict and set(submission) == subkeys
                 and submission['version'] == 'strategy-submission-v0.1'
                 and submission['slot_id'] == slot and submission['request_id'] == request_id
                 and submission['request_sha256'] == session['request']['sha256'], 'Submission/request binding mismatch')
        state = states[identifier]
        if submission['status'] == 'missing':
            _require(session['source'] is None and submission['source_sha256'] is None
                     and submission['n_params'] is None and session['evaluations'] == [], 'Missing submission has fabricated measurements')
            source_hash = n_params = rows = None
            status = 'missing'
        else:
            _require(submission['status'] == 'accepted', 'Submission status')
            source = _read(root, session['source'], inventory, json_value=False)
            source_hash = hashlib.sha256(source).hexdigest()
            n_params = submission['n_params']
            _require(submission['source_sha256'] == source_hash and type(n_params) is int and 0 <= n_params <= 16
                     and (state['family'] != 'planning' or n_params == 0), 'Final artifact identity/parameter count')
            entries = _data_entries(partition, state['family'], state['task_ids'])
            _require(type(session['evaluations']) is list and len(session['evaluations']) == len(entries), 'Incomplete task measurement set')
            rows = []
            for ref, data in zip(session['evaluations'], entries):
                _require(ref['path'] not in result_paths, 'Executor result reused across actor slots')
                result_paths.add(ref['path'])
                rows.append(_raw_evaluation(root, ref, source, n_params, policy['sha256'], state, data, inventory))
            status = 'infrastructure_error' if any(r['status'] == 'infrastructure_error' for r in rows) else 'measured'
            if status != 'measured':
                rows = None
        value = dict(policy_sha256=policy['sha256'], allocation_sha256=allocation['sha256'],
            context_sha256=digest(state), state_id=identifier, replicate_id=replicate,
            request_id=request_id, source_sha256=source_hash, n_params=n_params, status=status, results=rows)
        value['evaluation_sha256'] = digest(value)
        measurements[identifier, arm] = value
    pairs = [dict(state_id=identifier, replicate_id=replicate,
                  parent=measurements[identifier, 'fixed'], candidate=measurements[identifier, 'updated'])
             for identifier in SELECTION_STATES]
    decision = goal_alignment.select_strategy(parent, candidate, allocation, pairs)
    return dict(version=VERSION, evidence_kind=manifest['evidence_kind'], replicate_id=replicate,
        manifest=dict(path=manifest_path, sha256=expected_sha256), parent_policy=parent, candidate_policy=candidate,
        allocation=allocation, paired_results=pairs, decision=decision,
        common_context_sha256={key: digest(value) for key, value in contexts.items()},
        request_files=sorted(request_paths), evaluation_files=sorted(result_paths),
        dependency_hashes=dict(sorted(inventory.items())),
        evidence_boundary='Persisted trusted-client chain; not provider attestation or freeze-time proof.')


def _write_once(root, relative, value):
    path = safe_path(root, relative)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        stream.write(canonical(value) + b'\n')
    return file_ref(root, relative)


def freeze_selection(root, manifest_path, expected_sha256, output_path):
    replay = bind_selection(root, manifest_path, expected_sha256)
    chosen = replay['candidate_policy'] if replay['decision']['decision'] == 'promote' else replay['parent_policy']
    body = dict(version='strategy-decision-freeze-v0.1', replay=replay, selected_policy=chosen)
    return _write_once(root, output_path, body)


@dataclass(frozen=True)
class EvaluationGate:
    path: str
    sha256: str


def _decision(root, ref):
    value = _read(root, ref, {})
    _require(type(value) is dict and set(value) == {'version', 'replay', 'selected_policy'}
             and value['version'] == 'strategy-decision-freeze-v0.1', 'Decision freeze format')
    old = value['replay']
    replay = bind_selection(root, old['manifest']['path'], old['manifest']['sha256'])
    _require(old == replay, 'Decision dependencies or selector result changed')
    _require(replay['evidence_kind'] == 'observed', 'Synthetic records cannot unlock evaluation data')
    selected = replay['candidate_policy'] if replay['decision']['decision'] == 'promote' else replay['parent_policy']
    _require(value['selected_policy'] == selected, 'Frozen S* does not follow selector decision')
    return value


def freeze_evaluation_gate(root, decision_paths, output_path):
    _require(type(decision_paths) is dict and set(decision_paths) == {'r1', 'r2'}, 'Both proposal decisions required')
    decisions = {rep: _decision(root, ref) for rep, ref in decision_paths.items()}
    _verify_decision_pair(decisions)
    value = dict(version='strategy-evaluation-gate-v0.1', decisions=decision_paths,
                 selected_policy_sha256={rep: item['selected_policy']['sha256'] for rep, item in decisions.items()})
    ref = _write_once(root, output_path, value)
    return EvaluationGate(**ref)


def _verify_decision_pair(decisions):
    ids, paths, request_files, evaluation_files = set(), set(), set(), set()
    _require(set(decisions) == {'r1', 'r2'}, 'Both proposal decisions required')
    first, second = decisions['r1']['replay'], decisions['r2']['replay']
    _require(first['common_context_sha256'] == second['common_context_sha256'], 'Proposal repetitions use different common context')
    oldstates = [{k: v for k, v in state.items() if k != 'replicate_ids'} for state in first['allocation']['states']]
    newstates = [{k: v for k, v in state.items() if k != 'replicate_ids'} for state in second['allocation']['states']]
    _require(oldstates == newstates and first['parent_policy'] == second['parent_policy'], 'Proposal repetitions use different frozen allocation/context')
    for rep, item in decisions.items():
        replay = item['replay']
        _require(replay['replicate_id'] == rep, 'Decision replicate mismatch')
        for pair in replay['paired_results']:
            for arm in ('parent', 'candidate'):
                identifier = pair[arm]['request_id']
                _require(identifier not in ids, 'Request reused across proposal repetitions')
                ids.add(identifier)
        path = replay['manifest']['path']
        _require(path not in paths, 'Decision manifest reused')
        paths.add(path)
        for key, seen in [('request_files', request_files), ('evaluation_files', evaluation_files)]:
            values = replay[key]
            _require(not seen.intersection(values), 'Raw request or evaluation file reused across repetitions')
            seen.update(values)


def verify_evaluation_gate(root, gate):
    if type(gate) is not EvaluationGate:
        raise PermissionError('Evaluation requires a replay-verifiable gate object')
    value = _read(root, dict(path=gate.path, sha256=gate.sha256), {})
    _require(type(value) is dict and set(value) == {'version', 'decisions', 'selected_policy_sha256'}
             and value['version'] == 'strategy-evaluation-gate-v0.1'
             and set(value['decisions']) == {'r1', 'r2'}, 'Evaluation gate fields')
    decisions = {rep: _decision(root, ref) for rep, ref in value['decisions'].items()}
    _verify_decision_pair(decisions)
    _require(value['selected_policy_sha256'] == {rep: item['selected_policy']['sha256'] for rep, item in decisions.items()},
             'Evaluation S* hashes mismatch')
    return gate.sha256


def authorize_state_phase(root, state_id, *, evaluation_gate=None):
    """Must precede any execution, including seed0 feedback, of an eval source."""
    if state_id in EVALUATION_STATES:
        return verify_evaluation_gate(root, evaluation_gate)
    _require(state_id in SELECTION_STATES, 'Unknown frozen state')
    return None
