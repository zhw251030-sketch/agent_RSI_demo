"""Use a frozen, externally selected rule order for one archived-state repair."""
import copy
import hashlib
import json

from .compact_controller import CompactController
from .revision_policy import catalog, render_policy, validate_policy
from .state_packet import payload_bytes


def canonical(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True,
                      separators=(',', ':')).encode('utf-8')


def common_packet(packet):
    value = copy.deepcopy(packet)
    for key in ('repair_policy', 'experience_memory'):
        value.pop(key, None)
    return value


def verify_triplets(prepared):
    groups = {}
    for controller, _, entry in prepared:
        groups.setdefault(entry['pair_id'], []).append((controller, entry))
    proofs = {}
    for pair, group in groups.items():
        if len(group) != 3 or {e['condition'] for _,e in group} != {'fixed','memory','updated'}:
            raise ValueError('Every group requires three distinct policy conditions')
        packets = [canonical(common_packet(c.state_packet())) for c,_ in group]
        starts = [c.records[0] for c,_ in group]
        if len(set(packets)) != 1:
            raise ValueError('Policy comparison common inputs differ')
        if len({(r['source_sha256'],r['n_params']) for r in starts}) != 1:
            raise ValueError('Policy comparison starting artifacts differ')
        proofs[pair] = {'common_sha256':hashlib.sha256(packets[0]).hexdigest(),
            'common_bytes':len(packets[0]), 'source_sha256':starts[0]['source_sha256'],
            'n_params':starts[0]['n_params']}
    if not proofs:
        raise ValueError('No policy comparison groups')
    return proofs


class PolicyTransferController(CompactController):
    def __init__(self, root, session_config, output_dir, *, session_id, policy_text,
                 repair_state, policy, experience_memory, policy_guard=None):
        self.revision_policy = validate_policy(policy)
        if type(experience_memory) is not list or len(experience_memory) not in (0,2):
            raise ValueError('Memory contains either zero or exactly the two update experiences')
        self.experience_memory = copy.deepcopy(experience_memory)
        self.policy_guard = policy_guard
        super().__init__(root, session_config, output_dir, condition='hidden',
            session_id=session_id, policy_text=policy_text, repair_state=repair_state)
        self.strategy_version = 'finite-rule-policy-transfer-v0.1'

    def state_packet(self):
        if self.policy_guard is not None:
            self.policy_guard()
        packet = super().state_packet()
        packet['version'] = 'finite-rule-policy-state-v0.1'
        packet['available_revision_rules'] = catalog()
        packet['repair_policy'] = render_policy(self.revision_policy)
        packet['experience_memory'] = copy.deepcopy(self.experience_memory)
        if payload_bytes(packet) > 65536:
            raise ValueError('Policy comparison packet exceeds 65536 bytes')
        return packet

    def summary(self):
        result = super().summary()
        result['policy'] = copy.deepcopy(self.revision_policy)
        result['strategy_updated'] = False  # The actor cannot update S during this session.
        result['scope'] = ('One development repair with an externally frozen rule selection; '
                           'the actor cannot update policy, weights, or evaluation data.')
        return result
