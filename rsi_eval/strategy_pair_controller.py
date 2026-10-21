"""Archive one strict strategy proposal or actor submission; never execute it.

The SDK adapter owns dispatch and known-usage checks. The scheduler owns phase
authorization and measurement. Accepted files here alone are not provider
attestation, a useful policy, or a task performance result.
"""
import hashlib
import json
import os
from pathlib import Path

from .revision_policy import VERSION as POLICY_VERSION, validate_policy
from .strategy_binding import SOURCE_FREEZE, SOURCE_FREEZE_SHA256, FUTURE_ALLOCATION, FUTURE_ALLOCATION_SHA256, task_contract
from .strategy_learning import build_learning_package, canonical, render_actor_packet, render_update_packet
from .strategy_partition import safe_path

VERSION = 'strategy-pair-controller-v0.1'
SDK_METADATA_FIELDS = frozenset({'summary', 'security_risk'})
# OpenHands SDK 1.55.1 advertises these exact strings. The SDK itself may ignore
# malformed metadata when no security analyzer is configured, so validate here
# before allowing its metadata extraction or any business normalization.
SDK_SECURITY_RISKS = ('UNKNOWN', 'LOW', 'MEDIUM', 'HIGH')


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def strict_json(raw):
    def pairs(items):
        value = {}
        for key, item in items:
            _require(key not in value, 'Duplicate JSON key')
            value[key] = item
        return value
    value = json.loads(raw, object_pairs_hook=pairs,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Nonfinite JSON')))
    canonical(value)
    return value


def reference(root, path):
    root, path = Path(root).resolve(), Path(path)
    relative = path.relative_to(root).as_posix()
    checked = safe_path(root, relative)
    _require(checked.is_file(), 'Reference is not a file')
    return dict(path=relative, sha256=hashlib.sha256(checked.read_bytes()).hexdigest())


def write_once(path, value, *, raw=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = value if raw else canonical(value) + b'\n'
    with path.open('xb') as stream:
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())


def _fixed(root, name, expected):
    raw = safe_path(root, name).read_bytes()
    _require(hashlib.sha256(raw).hexdigest() == expected, 'Frozen input bytes changed')
    return strict_json(raw)


class StrategyPairController:
    def __init__(self, root, packet, slot_id, output_dir):
        self.root = Path(root).resolve()
        self.output_dir = Path(output_dir).absolute()
        safe_path(self.root, self.output_dir.relative_to(self.root).as_posix())
        slots = _fixed(self.root, FUTURE_ALLOCATION, FUTURE_ALLOCATION_SHA256)['slots']
        selected = [s for s in slots if s['id'] == slot_id]
        _require(len(selected) == 1, 'Unknown frozen request slot')
        self.slot_id = slot_id
        self.slot = selected[0]
        self.stage = 'update' if self.slot['phase'] == 'update' else 'actor'
        _require(type(packet) is dict, 'Packet must be an object')
        if self.stage == 'update':
            expected = render_update_packet(self.root, build_learning_package(self.root))
        else:
            _require(set(packet) == {'version','task_text','current_state','repair_policy'}, 'Actor packet fields')
            context = packet['current_state']
            _require(type(context) is dict and context.get('state_id') == self.slot['state_id'], 'Actor state differs from slot')
            contract = task_contract(self.root, context['state_id'])
            _require(all(context.get(k) == v for k,v in contract.items()), 'Actor task contract changed')
            sources = _fixed(self.root, SOURCE_FREEZE, SOURCE_FREEZE_SHA256)['slots']
            original = next(s for s in sources if s['id'] == context['state_id'])
            candidate = original['candidate']
            _require(context.get('family') == original['family']
                     and context.get('source_sha256') == candidate['source_sha256']
                     and context.get('n_params') == candidate['n_params'], 'Actor original source changed')
            policy = {k: packet['repair_policy'].get(k) for k in ('version','rule_ids')}
            expected = render_actor_packet(self.root, context, policy)
        _require(packet == expected, 'Packet differs from fixed renderer')
        self._packet_bytes = canonical(packet)
        self.halted = False
        self.status = 'pending'
        self.policy = None
        self.source = None
        self.submission = None

    def task_packet(self):
        return strict_json(self._packet_bytes)

    def task_prompt(self):
        return self._packet_bytes.decode('utf-8')

    def validate_arguments(self, raw):
        value = strict_json(raw) if isinstance(raw, (str, bytes)) else strict_json(canonical(raw))
        required = {'rule_1','rule_2','rule_3','rule_4'} if self.stage == 'update' else {'source','n_params'}
        _require(type(value) is dict and required <= set(value) <= required | {'explanation'} | SDK_METADATA_FIELDS,
            'Submission fields differ from contract')
        if 'summary' in value:
            _require(value['summary'] is None or type(value['summary']) is str,
                'SDK summary must be a string or null')
        if 'security_risk' in value:
            _require(type(value['security_risk']) is str and value['security_risk'] in SDK_SECURITY_RISKS,
                'SDK security_risk must be a declared enum string')
        # Parse and validate every raw field before projecting. Metadata stays in
        # the immutable response, but is never a policy, candidate or explanation.
        value = {key: item for key, item in value.items() if key not in SDK_METADATA_FIELDS}
        explanation = value.get('explanation', '')
        _require(type(explanation) is str and len(explanation.encode('utf-8')) <= 4096, 'Explanation byte bound')
        if self.stage == 'update':
            validate_policy(dict(version=POLICY_VERSION, rule_ids=[value[f'rule_{i}'] for i in range(1,5)]))
        else:
            source, count = value['source'], value['n_params']
            _require(type(source) is str and bool(source.strip()) and len(source.encode('utf-8')) <= 16384, 'Source byte bound')
            _require(type(count) is int and 0 <= count <= 16
                     and (self.task_packet()['current_state']['family'] != 'planning' or count == 0), 'Parameter declaration')
        return value | {'explanation': explanation}

    def _check_open(self, request_id, request_ref):
        _require(self.status == 'pending' and not self.halted, 'Controller has already submitted or halted')
        _require(type(request_id) is str and request_id and '/' not in request_id and '\\' not in request_id, 'Invalid request identity')
        _require(type(request_ref) is dict and reference(self.root, self.root/request_ref['path']) == request_ref, 'Request reference changed')

    def accept(self, business, request_id, request_ref, sdk_ref):
        self._check_open(request_id, request_ref)
        _require(reference(self.root, self.root/sdk_ref['path']) == sdk_ref, 'SDK receipt changed')
        value = self.validate_arguments(business)
        common = dict(slot_id=self.slot_id, request_id=request_id, request_sha256=request_ref['sha256'], status='accepted')
        # A durable attempt precedes all output writes. Partial writes remain
        # inspectable and cannot be replaced by a second controller.
        write_once(self.output_dir/'acceptance-attempt.json', dict(version=VERSION, **common,
            sdk_submission=sdk_ref, business_sha256=hashlib.sha256(canonical(value)).hexdigest()))
        if self.stage == 'actor':
            raw = value['source'].encode('utf-8')
            write_once(self.output_dir/'source.py', raw, raw=True)
            receipt = dict(version='strategy-submission-v0.1', **common,
                source_sha256=hashlib.sha256(raw).hexdigest(), n_params=value['n_params'])
            write_once(self.output_dir/'submission.json', receipt)
            self.source = reference(self.root, self.output_dir/'source.py')
        else:
            self.policy = dict(version=POLICY_VERSION, rule_ids=[value[f'rule_{i}'] for i in range(1,5)])
            write_once(self.output_dir/'policy.json', self.policy)
            receipt = dict(version='strategy-policy-submission-v0.1', **common,
                policy_sha256=hashlib.sha256(canonical(self.policy)).hexdigest())
            write_once(self.output_dir/'submission.json', receipt)
        write_once(self.output_dir/'explanation.json', dict(explanation=value['explanation'],
            scope='Unverified model explanation, archived only; never actor context or measured benefit.'))
        self.submission = reference(self.root, self.output_dir/'submission.json')
        self.status = 'accepted'
        return dict(status='accepted', candidate_executions=0)

    def missing(self, request_id, request_ref):
        self._check_open(request_id, request_ref)
        common = dict(slot_id=self.slot_id, request_id=request_id, request_sha256=request_ref['sha256'], status='missing')
        receipt = (dict(version='strategy-submission-v0.1', **common, source_sha256=None, n_params=None)
            if self.stage == 'actor' else dict(version='strategy-policy-submission-v0.1', **common, policy_sha256=None))
        write_once(self.output_dir/'submission.json', receipt)
        self.submission = reference(self.root, self.output_dir/'submission.json')
        self.status = 'missing'

    def summary(self):
        return dict(version=VERSION, stage=self.stage, status=self.status, halted=self.halted,
            candidate_executions=0, task_evaluations=0, model_weight_updates=0,
            policy=self.policy, source=self.source, submission=self.submission)
