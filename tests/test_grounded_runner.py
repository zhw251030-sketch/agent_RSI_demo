import copy
import json
from pathlib import Path
import tempfile
import unittest

from scripts.run_grounded_policy import (evaluation_order, update_order, validate_config,
    verify_pairs, settled_request, review_common)

ROOT = Path(__file__).resolve().parents[1]


class GroundedRunnerTests(unittest.TestCase):
    def test_dispatch_balances_order_and_uses_four_states(self):
        updates = update_order()
        self.assertEqual([r['condition'] for r in updates],
                         ['proposal','self','checked','proposal','checked','self'])
        rows = evaluation_order()
        self.assertEqual(len(rows), 8)
        self.assertEqual(len({r['state_id'] for r in rows}), 4)
        self.assertEqual(len({r['session_id'] for r in updates+rows}), 14)

    def test_config_rejects_extra_requests_and_selection_gate(self):
        config = json.loads((ROOT/'configs/pilots/grounded-policy-v0.1.json').read_text())
        validate_config(config)
        for key, val in [('max_requests',15),('max_cost_cny',5.01),('max_requests_per_session',2)]:
            changed = copy.deepcopy(config); changed['budgets'][key] = val
            with self.assertRaises(ValueError): validate_config(changed)
        changed = copy.deepcopy(config); changed['checks_gate_execution'] = True
        with self.assertRaises(ValueError): validate_config(changed)

    def test_known_settlement_required_and_global_unknown_blocks(self):
        state = {'halted':False,'requests':[{'request_id':'request-0001','session_id':'p1-proposal',
                    'status':'settled','usage_state':'known','usage':{'prompt_tokens':10}}]}
        self.assertEqual(settled_request(state, 'p1-proposal'), 'request-0001')
        state['requests'].append(dict(state['requests'][0],session_id='other',usage_state='unknown'))
        with self.assertRaises(ValueError): settled_request(state,'p1-proposal')

    def test_review_only_feedback_is_ignored(self):
        a = {'pair_id':'p1','proposal':{'rule_1':'R01'},'premise_feedback':None}
        b = copy.deepcopy(a); b['premise_feedback'] = {'pass':False}
        self.assertEqual(review_common(a),review_common(b))
        b['proposal']['rule_1'] = 'R02'
        self.assertNotEqual(review_common(a),review_common(b))

    def test_actor_pair_comparison_detects_memory_leak(self):
        class C:
            records = [{'source_sha256':'x','n_params':3}]
            def __init__(self,packet): self.packet=packet
            def state_packet(self): return self.packet
        a = {'repair_policy':{'rule_ids':['R01']},'experience_memory':[],'evidence':'same'}
        b = dict(a,repair_policy={'rule_ids':['R02']})
        rows = [(C(a),None,{'pair_id':'x','condition':'self'}),
                (C(b),None,{'pair_id':'x','condition':'checked'})]
        self.assertEqual(len(verify_pairs(rows)),1)
        b['experience_memory'] = ['leak']
        with self.assertRaises(ValueError): verify_pairs(rows)


if __name__ == '__main__': unittest.main()
