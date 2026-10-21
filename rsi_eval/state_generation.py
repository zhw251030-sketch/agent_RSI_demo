"""Store eight cold-start sources without reading task data or executing code."""
import copy
import hashlib
import json
from pathlib import Path

from .strategy_partition import safe_path, validate_manifest, SOURCE_HASHES

VERSION = 'state-generation-v0.1'
CONFIG_PATH = 'configs/pilots/state-generation-v0.1.json'
PARTITION_PATH = 'configs/tasks/strategy-partition-v0.1.json'
PARTITION_SHA256 = 'bf49dd855d591863bc938a37d889cc5afc9a2ea2e1bfab87d71a951c39692ed7'
PROTOCOL = 'docs/protocols/2026-10-21-state-generation-v0.1.md'
SLOT_SPECS = (
    ('P-select-1', 'planning', 'selection', None),
    ('S-select-1', 'symbolic', 'selection', 'oscillator2'),
    ('P-eval-1', 'planning', 'evaluation', None),
    ('S-bact-eval-1', 'symbolic', 'evaluation', 'bactgrow'),
    ('P-select-2', 'planning', 'selection', None),
    ('S-select-2', 'symbolic', 'selection', 'oscillator2'),
    ('P-eval-2', 'planning', 'evaluation', None),
    ('S-stress-eval-1', 'symbolic', 'evaluation', 'stressstrain'),
)
SLOT_ORDER = [row[0] for row in SLOT_SPECS]
PUBLIC_IDS = ['spannerlearning/seed0/problem0', 'spannerlearning/seed0/problem1']
# Canonical prepared public TaskViews, independently archived before this round.
# These are public instance bindings, not scores, solutions or generated code.
PUBLIC_PREPARED_SHA256 = [
    'cfa3a0584dd1e4724b528d9ee158c44e8e961fa1505e088e7f38b8f052aac9ca',
    '834f86423965d0f76e609742f374dc9067ac8a49f493a2077e6d7c882a7a723c',
]


def canonical(value):
    try:
        return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True,
                          separators=(',', ':')).encode('utf-8')
    except (ValueError, TypeError, UnicodeError, OverflowError, RecursionError) as exc:
        raise ValueError('Expected finite UTF-8 JSON') from exc


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def validate_config(config):
    expected = dict(version=VERSION, protocol=PROTOCOL, partition_path=PARTITION_PATH,
        partition_sha256=PARTITION_SHA256, slot_order=SLOT_ORDER, resume=False,
        candidate_executions=0, new_probe_executions=0, sealed_tasks_executed=0,
        strategy_updates=0, budgets=dict(max_requests=8, max_requests_per_session=1,
        max_output_tokens=8192, max_input_bytes=65536, max_reserved_tokens=1000000,
        max_cost_cny=5, input_cny_per_million=2.1, output_cny_per_million=8.4))
    if canonical(config) != canonical(expected):
        raise ValueError('Frozen source-generation configuration changed')
    return copy.deepcopy(config)


def _interface(family, dimension):
    if family == 'planning':
        return {'signature': 'get_plan(objects, init, goal)', 'n_params': 0,
                'output': 'list of grounded action strings'}
    names = [f'u{i}' for i in range(dimension)]
    return {'signature': 'equation(' + ', '.join(names + ['params']) + ')',
            'n_params_min': 0, 'n_params_max': 16,
            'output': 'finite numeric array of shape (len(u0),)'}


def build_inputs(root, planning_examples):
    """Build anonymous packets; the caller loads only the two pinned public tasks."""
    bindings = {}
    def read(relative):
        raw = safe_path(root, relative).read_bytes()
        bindings[relative] = hashlib.sha256(raw).hexdigest()
        return raw
    config = validate_config(json.loads(read(CONFIG_PATH)))
    partition = json.loads(read(PARTITION_PATH))
    if bindings[PARTITION_PATH] != PARTITION_SHA256:
        raise ValueError('Task partition bytes changed')
    validate_manifest(root, partition)
    sources = {relative: json.loads(read(relative)) for relative in SOURCE_HASHES}
    if type(planning_examples) is not list or len(planning_examples) != 2:
        raise ValueError('Exactly two pinned public TaskViews are required')
    clean_examples = []
    example_bindings = []
    planning_manifest = sources['configs/tasks/planning-spanner-v0.1.json']
    task_map = {item['id']: item for item in planning_manifest['tasks']}
    for index, example in enumerate(planning_examples):
        if (type(example) is not dict or set(example) != {'family', 'task_id', 'objects', 'init', 'goal'}
                or example['family'] != 'planning' or example['task_id'] != PUBLIC_IDS[index]
                or digest(example) != PUBLIC_PREPARED_SHA256[index]):
            raise ValueError('Public TaskView identity, content or order mismatch')
        clean_examples.append({key: copy.deepcopy(example[key]) for key in ('objects', 'init', 'goal')})
        example_bindings.append(dict(task_id=PUBLIC_IDS[index],
            pddl_sha256=task_map[PUBLIC_IDS[index]]['sha256'], prepared_sha256=digest(example)))
    prompts = {family: read('prompts/state-generation/' + family + '.md').decode('utf-8')
               for family in ('planning', 'symbolic')}
    symbols = {item['relative_path'].split('/')[0]: item for item in
               sources['configs/tasks/downloads-v0.1.json']['symbolic']['files']
               if item['relative_path'].endswith('/train.csv')}
    slots = []
    for identifier, family, role, task in SLOT_SPECS:
        dimension = None if family == 'planning' else len(symbols[task]['columns']) - 1
        task_ids = ([item['task_id'] for item in partition['planning']['tasks'] if item['role'] == role]
                    if family == 'planning' else [task])
        packet = dict(version='state-generation-packet-v0.1', family=family,
                      instructions=prompts[family])
        if family == 'planning':
            packet.update(interface=_interface(family, dimension),
                          examples=copy.deepcopy(clean_examples))
        else:
            names = [f'u{i}' for i in range(dimension)]
            packet.update(input_dimension=dimension, input_names=names,
                          interface=_interface(family, dimension))
        slots.append(dict(id=identifier, family=family, role=role, task_ids=task_ids,
                          input_dimension=dimension, packet=packet, packet_sha256=digest(packet)))
    return dict(version=VERSION, config=config, config_sha256=bindings[CONFIG_PATH],
                source_bindings=bindings, public_example_bindings=example_bindings, slots=slots)


def _slot(slot):
    if (type(slot) is not dict or set(slot) != {'id', 'family', 'role', 'task_ids',
            'input_dimension', 'packet', 'packet_sha256'} or slot['id'] not in SLOT_ORDER):
        raise ValueError('Invalid source slot')
    _, family, role, task = SLOT_SPECS[SLOT_ORDER.index(slot['id'])]
    dimension = None if family == 'planning' else {'oscillator2': 3, 'bactgrow': 4, 'stressstrain': 2}[task]
    if (slot['family'] != family or slot['role'] != role or slot['input_dimension'] != dimension
            or slot['packet_sha256'] != digest(slot['packet'])):
        raise ValueError('Source slot metadata or packet binding mismatch')
    if family == 'symbolic':
        expected_tasks = [task]
    elif role == 'selection':
        expected_tasks = [f'spannerlearning/seed1/problem{i}' for i in range(10) if i != 4]
        expected_tasks += [f'spannerlearning/seed2/problem{i}' for i in range(10)]
    else:
        excluded = {(3, 1), (5, 4), (6, 5), (7, 0), (7, 9), (8, 0), (8, 2)}
        expected_tasks = [f'spannerlearning/seed{s}/problem{i}' for s in range(3, 10)
                          for i in range(10) if (s, i) not in excluded]
    if slot['task_ids'] != expected_tasks:
        raise ValueError('Source slot task allocation mismatch')
    packet = slot['packet']
    keys = {'version', 'family', 'instructions', 'interface'} | (
        {'examples'} if family == 'planning' else {'input_dimension', 'input_names'})
    if (type(packet) is not dict or set(packet) != keys or packet['family'] != family
            or packet['version'] != 'state-generation-packet-v0.1'
            or type(packet['instructions']) is not str or not packet['instructions'].strip()
            or canonical(packet['interface']) != canonical(_interface(family, dimension))):
        raise ValueError('Unexpected anonymous packet fields')
    if family == 'planning':
        examples = packet['examples']
        if type(examples) is not list or len(examples) != 2:
            raise ValueError('Unexpected public example count')
        for index, example in enumerate(examples):
            if (type(example) is not dict or set(example) != {'objects', 'init', 'goal'}
                    or digest(dict(example, family='planning', task_id=PUBLIC_IDS[index]))
                    != PUBLIC_PREPARED_SHA256[index]):
                raise ValueError('Public example content or anonymity changed')
    elif (type(packet['input_dimension']) is not int or packet['input_dimension'] != dimension
          or packet['input_names'] != [f'u{i}' for i in range(dimension)]):
        raise ValueError('Anonymous symbolic input contract changed')
    return copy.deepcopy(slot)


def _write_once(path, value):
    raw = canonical(value) + b'\n'
    with Path(path).open('xb') as stream:
        stream.write(raw)


class GenerationController:
    """One submission is saved verbatim; syntax and task performance are unknown."""
    def __init__(self, slot, output_dir):
        self.slot = _slot(slot)
        self.output_dir = Path(output_dir)
        for path in (self.output_dir, *self.output_dir.parents):
            if path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction()):
                raise ValueError('Symlinked source-generation output')
        self.output_dir.mkdir(parents=True, exist_ok=True)
        _write_once(self.output_dir / 'controller-binding.json', {
            'version': VERSION, 'slot_id': slot['id'], 'packet_sha256': slot['packet_sha256']})
        self.candidate = None
        self.attempts = []
        self.halted = False
        self.infrastructure_error_type = None

    def task_packet(self):
        return copy.deepcopy(self.slot['packet'])

    def task_prompt(self):
        return canonical(self.task_packet()).decode('utf-8')

    def state_packet(self):
        return self.task_packet()

    def submit(self, session_id=None, source='', n_params=0):
        if self.halted:
            return {'status': 'infrastructure_error', 'error_kind': 'controller_halted'}
        if self.attempts:
            return {'status': 'budget_exhausted', 'error_kind': 'one_source_submission'}
        attempt = dict(session_id=session_id, status='invalid_request')
        self.attempts.append(attempt)
        try:
            if (session_id != self.slot['id'] or type(source) is not str or not source.strip()
                    or len(source.encode('utf-8')) > 16384 or type(n_params) is not int
                    or not 0 <= n_params <= 16 or (self.slot['family'] == 'planning' and n_params != 0)):
                raise ValueError('Source submission contract')
        except (ValueError, TypeError, UnicodeError):
            attempt['error_kind'] = 'source_submission_contract'
            _write_once(self.output_dir / 'submission-attempt.json', attempt)
            return copy.deepcopy(attempt)
        candidate = dict(version=VERSION, slot_id=self.slot['id'], family=self.slot['family'],
            origin='model_generated_without_task_feedback', status='stored_unexecuted',
            source_file='source.py', source_sha256=hashlib.sha256(source.encode('utf-8')).hexdigest(),
            n_params=n_params, packet_sha256=self.slot['packet_sha256'])
        for name in ('source.py', 'candidate.json'):
            path = self.output_dir / name
            if path.exists() or path.is_symlink():
                raise FileExistsError('Refusing to replace a generated source artifact')
        with (self.output_dir / 'source.py').open('xb') as stream:
            stream.write(source.encode('utf-8'))
        _write_once(self.output_dir / 'candidate.json', candidate)
        self.candidate = candidate
        attempt.update(status='accepted', source_sha256=candidate['source_sha256'])
        _write_once(self.output_dir / 'submission-attempt.json', attempt)
        _write_once(self.output_dir / 'controller-summary.json', self.summary())
        return dict(status='accepted', source_sha256=candidate['source_sha256'], candidate_executions=0)

    def summary(self):
        return dict(version=VERSION, slot_id=self.slot['id'], candidate=copy.deepcopy(self.candidate),
                    attempts=len(self.attempts), halted=self.halted,
                    infrastructure_error_type=self.infrastructure_error_type,
                    candidate_executions=0, task_scores=0, sealed_tasks_executed=0,
                    strategy_updates=0, model_calls_owned=0)
