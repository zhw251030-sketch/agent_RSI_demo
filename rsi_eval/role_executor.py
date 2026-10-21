"""Role-scoped successor to the immutable development executor.

Only trusted host callers construct this class. Evaluation access requires a
replay-verified strategy freeze; it is not an LLM-facing flag or tool argument.
Candidate source is never imported here. Every execution uses the existing
Linux sandbox, and only the host/VAL computes scores.
"""
import csv
import hashlib
import io
import json
import math
from pathlib import Path
import re
import tempfile
import time
import uuid

from . import planning, symbolic
from .sandbox import run_candidate
from .strategy_partition import read_json, safe_path, validate_manifest

VERSION = 'role-executor-v0.1'
ROOT = Path(__file__).resolve().parents[1]
PARTITION = 'configs/tasks/strategy-partition-v0.1.json'
DOMAIN_PATH = 'data/planning/spanner/spannerlearning.pddl'
LIMITS = dict(timeout_seconds=20, memory_mb=2048, cpu_seconds=10,
              max_output_bytes=2_000_000)
HEADERS = {'oscillator1': ['x', 'v', 'a'],
           'oscillator2': ['t', 'x', 'v', 'a'],
           'bactgrow': ['b', 's', 'temp', 'pH', 'db'],
           'stressstrain': ['strain', 'temp', 'stress']}
RUNTIME_FILES = ('rsi_eval/role_executor.py', 'rsi_eval/strategy_partition.py',
                 'rsi_eval/planning.py', 'rsi_eval/symbolic.py',
                 'rsi_eval/sandbox.py', 'rsi_eval/worker.py',
                 'rsi_eval/planning_worker.py', 'rsi_eval/symbolic_worker.py',
                 'scripts/check_planning_data.py')


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
                      separators=(',', ':')).encode('utf-8')


def runtime_inventory():
    """Hash the actual executing source tree, not caller-selected root files."""
    files = [{'path': name, 'sha256': _sha(safe_path(ROOT, name).read_bytes())}
             for name in RUNTIME_FILES]
    return files, _sha(canonical(files))


def _load_partition(root):
    document = read_json(root, PARTITION)
    validate_manifest(root, document, verify_data=False)
    return document, _sha(safe_path(root, PARTITION).read_bytes())


def _verified(root, entry):
    path = safe_path(root, entry['data_path'])
    raw = path.read_bytes()
    if _sha(raw) != entry['sha256']:
        raise ValueError('task data integrity mismatch')
    return path, raw


def _write(path, value):
    raw = (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8')
    with path.open('xb') as stream:
        stream.write(raw)
    return _sha(raw)


class RoleExecutor:
    """Prepare or evaluate only one frozen role; no role/data override flags.

    Construction reads role metadata only. Both prepare_task and evaluate check
    authorization before any task data read. Evaluation gates are reverified
    for every call so removing or modifying their evidence closes access.
    """
    def __init__(self, root=ROOT, *, role='selection', evaluation_gate=None):
        if role not in ('learning', 'selection', 'evaluation') or type(role) is not str:
            raise ValueError('unsupported execution role')
        if role != 'evaluation' and evaluation_gate is not None:
            raise ValueError('non-evaluation role cannot carry an evaluation gate')
        self.root = Path(root).absolute()
        self.role = role
        self._gate = evaluation_gate
        self._gate_sha256 = None
        self._check_gate()
        self._manifest, self.partition_sha256 = _load_partition(self.root)

    def _check_gate(self):
        if self.role != 'evaluation':
            return
        if self._gate is None or isinstance(self._gate, bool):
            raise PermissionError('evaluation requires a verified frozen strategy gate')
        from .strategy_binding import verify_evaluation_gate
        value = verify_evaluation_gate(self.root, self._gate)
        if type(value) is not str or re.fullmatch('[0-9a-f]{64}', value) is None:
            raise PermissionError('invalid evaluation gate verification')
        self._gate_sha256 = value

    def task_ids(self, family):
        """List metadata identities only; this does not open task files."""
        if family == 'planning':
            return [x['task_id'] for x in self._manifest['planning']['tasks']
                    if x['role'] == self.role]
        if family == 'symbolic':
            return [x['task_id'] for x in self._manifest['symbolic']['files']
                    if x['role'] == self.role and x['split'] == 'train']
        raise PermissionError('unsupported task family')

    def _authorize(self, family, task_id):
        self._check_gate()
        if type(task_id) is not str or task_id not in self.task_ids(family):
            raise PermissionError('task is not in the executor role')
        if family == 'planning':
            entries = [x for x in self._manifest['planning']['tasks'] if x['task_id'] == task_id]
        else:
            entries = [x for x in self._manifest['symbolic']['files']
                       if x['task_id'] == task_id and x['split'] == 'train']
        if len(entries) != 1:
            raise ValueError('ambiguous role entry')
        return entries[0]

    def prepare_task(self, family, task_id):
        """Return public worker input plus trusted provenance after role checks."""
        entry = self._authorize(family, task_id)
        path, raw = _verified(self.root, entry)
        provenance = dict(partition_sha256=self.partition_sha256,
                          data_sha256=entry['sha256'], domain_sha256=None,
                          metric_scope=self.role if family == 'planning' else 'train')
        if family == 'planning':
            domain_hash = self._manifest['planning']['domain_sha256']
            domain_path, domain_raw = _verified(self.root, dict(data_path=DOMAIN_PATH, sha256=domain_hash))
            domain = planning.parse_domain(domain_raw.decode('utf-8'))
            task = planning.parse_problem(raw.decode('utf-8'), domain)
            request = dict(family=family, task_id=task_id,
                           objects=[list(x) for x in sorted(task['objects'].items())],
                           init=[list(x) for x in sorted(task['init'])],
                           goal=[list(x) for x in sorted(task['goal'])])
            provenance['domain_sha256'] = domain_hash
            return dict(request=request, provenance=provenance,
                        planning_context=(domain, task, (domain_path, path)))
        headers = HEADERS[task_id]
        if entry['columns'] != headers or len(raw) != entry['bytes']:
            raise ValueError('training columns or size mismatch')
        reader = csv.reader(io.StringIO(raw.decode('utf-8'), newline=''), strict=True)
        if next(reader, None) != headers:
            raise ValueError('training column mismatch')
        X, y = [], []
        for row in reader:
            if len(row) != len(headers):
                raise ValueError('training row width mismatch')
            values = [float(x) for x in row]
            if not all(math.isfinite(x) for x in values):
                raise ValueError('training nonfinite value')
            X.append(values[:-1]); y.append(values[-1])
        if not X or len(X) != entry['rows']:
            raise ValueError('training row count mismatch')
        return dict(request=dict(family=family, task_id=task_id, X=X, y=y,
                                 input_names=headers[:-1]), provenance=provenance)

    def evaluate(self, family, task_id, source, *, n_params=0, candidate_id=None,
                 parent_id=None, strategy_version='unversioned'):
        """Journal one source/measurement; rejected roles never create records.

        Infrastructure failures remain explicit unmeasured failures. Callers
        bind these raw receipts to strategy/request/state allocation separately.
        """
        self._authorize(family, task_id)
        if type(source) is not str or not source or len(source.encode('utf-8')) > 65536:
            raise ValueError('source size or type')
        if type(n_params) is not int or not 0 <= n_params <= 16 or (family == 'planning' and n_params != 0):
            raise ValueError('invalid parameter count')
        for label, value in [('strategy_version', strategy_version), ('candidate_id', candidate_id), ('parent_id', parent_id)]:
            if value is not None and (type(value) is not str or not value or len(value) > 256):
                raise ValueError('invalid ' + label)
        started = time.monotonic()
        candidate_hash = _sha(source.encode('utf-8'))
        files, evaluator_hash = runtime_inventory()
        entry = self._authorize(family, task_id)
        domain_hash = self._manifest['planning']['domain_sha256'] if family == 'planning' else None
        run_id = uuid.uuid4().hex
        relative = f'runs/role_executor_feedback/{run_id}'
        directory = safe_path(self.root, relative)
        directory.mkdir(parents=True, exist_ok=False)
        (directory / 'source.py').write_bytes(source.encode('utf-8'))
        receipt = dict(version=VERSION, role=self.role, family=family, task_id=task_id,
                       candidate_sha256=candidate_hash, n_params=n_params,
                       strategy_version=strategy_version, partition_sha256=self.partition_sha256,
                       data_sha256=entry['sha256'], domain_sha256=domain_hash,
                       evaluator_sha256=evaluator_hash,
                       metric_scope=self.role if family == 'planning' else 'train', limits=dict(LIMITS))
        if self._gate_sha256:
            receipt['evaluation_gate_sha256'] = self._gate_sha256
        request_hash = _write(directory / 'request.json', receipt)
        result = dict(schema_version='0.1', version=VERSION, record_kind='executor_observation', run_id=run_id,
                      family=family, task_id=task_id, task_role=self.role,
                      candidate_id=candidate_id or candidate_hash, candidate_hash=candidate_hash,
                      n_params=n_params, parent_id=parent_id, strategy_version=strategy_version,
                      partition_sha256=self.partition_sha256, data_sha256=entry['sha256'],
                      domain_sha256=domain_hash, evaluator_sha256=evaluator_hash,
                      runtime_files=files, metric_scope=receipt['metric_scope'], limits=dict(LIMITS),
                      model_calls=0, sealed_tasks_executed=0, executions=[],
                      request_sha256=request_hash, journal_path=relative + '/result.json')
        if self._gate_sha256:
            result['evaluation_gate_sha256'] = self._gate_sha256

        def finish(values):
            result.update(values)
            result['elapsed_seconds'] = round(time.monotonic() - started, 6)
            _write(directory / 'result.json', result)
            return result

        try:
            prepared = self.prepare_task(family, task_id)
        except (OSError, ValueError, KeyError, TypeError, UnicodeError, csv.Error):
            return finish(dict(status='infrastructure_error', error_kind='task_data_integrity_or_parse'))
        task = prepared['request']

        def execute(request):
            response = run_candidate(source, request, deps_dir=self.root / '.task-runtime/python', **LIMITS)
            result['executions'].append({'phase': request.get('phase', 'plan'),
                **{k: v for k, v in response.items() if k not in ('result', 'stderr', 'stdout')}})
            if response.get('status') != 'completed':
                return None, dict(status=response.get('status', 'infrastructure_error'),
                    error_kind=response.get('error_kind', response.get('reason', 'sandbox_execution_failed')))
            payload = response.get('result')
            if type(payload) is not dict or payload.get('status') not in ('success', 'ok'):
                payload = payload if type(payload) is dict else {}
                error = dict(status='candidate_error', error_kind='invalid_worker_result')
                for key, value in [('error_kind', payload.get('error', payload.get('error_kind'))),
                                   ('exception_type', payload.get('exception_type'))]:
                    if type(value) is str and len(value) <= 128:
                        error[key] = value
                if type(payload.get('candidate_line')) is int and 1 <= payload['candidate_line'] <= 100000:
                    error['candidate_line'] = payload['candidate_line']
                return None, error
            return payload, None

        if family == 'planning':
            payload, error = execute(task)
            if error:
                return finish(error)
            return finish(_validate_plan(payload.get('plan'), prepared['planning_context'], self.root))

        payload, error = execute({**task, 'phase': 'fit', 'n_params': n_params})
        if error:
            return finish(error)
        params = payload.get('params')
        try:
            valid = (type(params) is list and len(params) == n_params
                     and all(type(v) in (int, float) and math.isfinite(float(v)) for v in params))
        except (ValueError, OverflowError):
            valid = False
        if not valid:
            return finish(dict(status='candidate_error', error_kind='invalid_fitted_parameters'))
        if (payload.get('converged') is not True or type(payload.get('nfev')) is not int
                or not 1 <= payload['nfev'] <= 100 or type(payload.get('candidate_calls')) is not int
                or not 1 <= payload['candidate_calls'] <= 100000):
            return finish(dict(status='candidate_error', error_kind='invalid_fit_metadata'))
        params = [float(v) for v in params]
        result['fitting'] = dict(params=params, n_params=n_params, nfev=payload['nfev'],
                                converged=True, candidate_calls=payload['candidate_calls'],
                                split='train', max_nfev=100)
        # Fresh sandbox invocation; labels and optimizer state are not passed.
        request = {k: v for k, v in task.items() if k != 'y'}
        payload, error = execute({**request, 'phase': 'predict', 'params': params})
        if error:
            return finish(error)
        score = symbolic.score_predictions(task['y'], payload.get('predictions'))
        if 'error' in score:
            score['error_kind'] = score.pop('error')
        score.update(metric_split='train', metric_description='Within-task training fit; not held-out prediction.')
        return finish(score)


def _validate_plan(plan, context, root):
    """Same syntax/VAL contract as the old executor with already-guarded data."""
    domain, task, paths = context
    outcome = planning._result
    if type(plan) is not list:
        return outcome('invalid_output', 'output_not_plan', 'get_plan must return a list of action strings.')
    if len(plan) > planning.MAX_ACTIONS:
        return outcome('invalid_output', 'plan_too_long', 'Plan exceeds the 1000-action limit.', len(plan))
    normalized = []
    for index, action in enumerate(plan):
        def invalid(kind, message):
            return outcome('invalid_output', kind, message, len(plan), first_invalid_action=index)
        if type(action) is not str or len(action) > 4096 or not re.fullmatch(r'\s*\([a-zA-Z][a-zA-Z0-9_-]*(?:\s+[a-zA-Z][a-zA-Z0-9_-]*)*\)\s*', action):
            return invalid('operator_syntax', 'Action must be one parenthesized grounded operator.')
        operator, *args = action.strip()[1:-1].lower().split()
        if operator not in domain['operators']:
            return invalid('unknown_operator', 'Unknown domain operator.')
        kinds = list(domain['operators'][operator]['parameters'].values())
        if len(args) != len(kinds):
            return invalid('operator_arity', 'Wrong operator argument count.')
        for arg, kind in zip(args, kinds):
            if arg not in task['objects']:
                return invalid('unknown_object', 'Unknown task object.')
            if not planning._subtype(task['objects'][arg], kind, domain['types']):
                return invalid('object_type', 'Incompatible object type.')
        normalized.append('(' + ' '.join([operator] + args) + ')')
    val_relative = 'vendor/llm-genplan/' + planning.VAL_DIRECTORY
    try:
        val_dir = safe_path(root, val_relative)
        for name, expected in planning.VAL_HASHES.items():
            if _sha(safe_path(root, val_relative + '/' + name).read_bytes()) != expected:
                raise ValueError('validator integrity mismatch')
    except (OSError, ValueError):
        return outcome('infrastructure_error', 'validator_integrity', 'Validator integrity check failed.', len(plan))
    try:
        scratch = safe_path(root, 'tmp')
        scratch.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='role-planning-', dir=scratch) as directory:
            observed = planning.run_val(val_dir / 'Validate', paths[0], paths[1], normalized,
                                        Path(directory), 'candidate', 10.0)
    except OSError:
        return outcome('infrastructure_error', 'validator_io', 'Validator temporary files unavailable.', len(plan))
    if observed['status'] == 'valid':
        return outcome('success', None, 'VAL verified the plan.', len(plan), validator=observed)
    if observed['status'] == 'invalid':
        return outcome('task_failure', 'plan_semantics', 'VAL rejected the plan.', len(plan), validator=observed)
    return outcome('infrastructure_error', observed['reason'], 'VAL produced no semantic verdict.', len(plan), validator=observed)
