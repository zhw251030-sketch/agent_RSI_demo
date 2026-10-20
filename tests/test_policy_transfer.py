"""Causal input boundary and independent-phase guards, without model calls."""
import copy
import importlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tests import test_compact_controller as compact_fixtures


class PolicyTransferTests(unittest.TestCase):
    def setUp(self):
        self.fixture = compact_fixtures.CompactControllerTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.module = importlib.import_module('rsi_eval.policy_transfer')
        self.rules = importlib.import_module('rsi_eval.revision_policy')
        self.new_policy = {'version': 'revision-policy-v0.1', 'rule_ids': ['R01','R02','R05','R07']}

    def controller(self, arm, guard=None):
        f = self.fixture
        seed = copy.deepcopy(f.seed)
        seed['historical_common'] = {}
        seed['historical_checks'] = {}
        return self.module.PolicyTransferController(f.root, f.config, f.root/arm,
            session_id='trial:ES-r1', policy_text='One revision.', repair_state=seed,
            policy=self.new_policy if arm == 'updated' else self.rules.S0,
            experience_memory=[{'case_id':'U-P','rationale':'untrusted experience'}, {'case_id':'U-S'}] if arm == 'memory' else [],
            policy_guard=guard)

    def test_three_arms_differ_only_in_two_named_channels(self):
        entries = []
        with patch('rsi_eval.diagnostic_controller.evaluate_candidate') as execute:
            for arm in ('fixed','memory','updated'):
                c = self.controller(arm)
                c.baseline()
                entries.append((c, c.output_dir, {'pair_id':'ES-r1','condition':arm}))
        execute.assert_not_called()
        proof = self.module.verify_triplets(entries)
        self.assertEqual(set(proof), {'ES-r1'})
        packets = [c.state_packet() for c,_,_ in entries]
        self.assertNotEqual(packets[0]['repair_policy'], packets[2]['repair_policy'])
        self.assertEqual(packets[0]['repair_policy'], packets[1]['repair_policy'])
        self.assertTrue(packets[1]['experience_memory'])
        self.assertEqual(packets[0]['available_revision_rules'], self.rules.catalog())
        self.assertNotIn('rationale', packets[2]['repair_policy'])

    def test_unrelated_metadata_and_missing_arm_fail_equality(self):
        entries = []
        for arm in ('fixed','memory','updated'):
            c = self.controller(arm)
            c.baseline()
            entries.append((c,c.output_dir,{'pair_id':'ES-r1','condition':arm}))
        with self.assertRaises(ValueError):
            self.module.verify_triplets(entries[:2])
        entries[0][0].evidence_session = 'leaked condition'
        with self.assertRaises(ValueError):
            self.module.verify_triplets(entries)

    def test_guard_is_rechecked_before_every_state_packet(self):
        guard = unittest.mock.Mock()
        c = self.controller('updated', guard)
        c.baseline()
        c.state_packet()
        guard.assert_called()
        guard.side_effect = ValueError('frozen policy changed')
        with self.assertRaises(ValueError):
            c.state_packet()

    def test_policy_and_memory_are_defensively_copied(self):
        c = self.controller('updated')
        self.new_policy['rule_ids'][0] = 'R08'
        c.baseline()
        packet = c.state_packet()
        self.assertEqual(packet['repair_policy']['rule_ids'][0], 'R01')
        packet['repair_policy']['rule_ids'][0] = 'R08'
        self.assertEqual(c.state_packet()['repair_policy']['rule_ids'][0], 'R01')


class PhaseGuardsTests(unittest.TestCase):
    def setUp(self):
        self.runner = importlib.import_module('scripts.run_policy_transfer')
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_phase_marker_is_exclusive(self):
        self.runner.exclusive_json(self.root/'phase.json', {'phase':'evaluation'})
        before = (self.root/'phase.json').read_bytes()
        with self.assertRaises(FileExistsError):
            self.runner.exclusive_json(self.root/'phase.json', {'phase':'replacement'})
        self.assertEqual((self.root/'phase.json').read_bytes(), before)

    def test_budget_gate_stops_unknown_unsettled_or_halted(self):
        normal = {'halted':False,'usage_unknown_count':0,'reserved_count':0}
        self.assertFalse(self.runner.budget_blocked(normal))
        for key,value in [('halted',True),('usage_unknown_count',1),('reserved_count',1)]:
            self.assertTrue(self.runner.budget_blocked(dict(normal, **{key:value})))

    def test_order_is_twelve_with_four_complete_triplets(self):
        order = self.runner.expected_order()
        self.assertEqual(len(order),12)
        self.assertEqual(len({e['session_id'] for e in order}),12)
        for pair in {e['pair_id'] for e in order}:
            self.assertEqual({e['condition'] for e in order if e['pair_id']==pair}, {'fixed','memory','updated'})
        self.assertEqual([(e['state_id'],e['condition']) for e in order[:6]],
                         list(reversed([(e['state_id'],e['condition']) for e in order[6:]])))

    def test_update_requires_exactly_one_settled_policy_request(self):
        ledger = {'requests':[{'session_id':'policy_update','request_id':'request-0001',
                               'status':'settled','usage_state':'known','usage':{'prompt_tokens':1,'completion_tokens':1}}]}
        self.assertEqual(self.runner.update_request_id(ledger), 'request-0001')
        for mutation in [lambda x:x['requests'].clear(),
                         lambda x:x['requests'].append(copy.deepcopy(x['requests'][0])),
                         lambda x:x['requests'][0].update(usage_state='unknown'),
                         lambda x:x['requests'][0].update(session_id='EP-r1-fixed')]:
            bad = copy.deepcopy(ledger)
            mutation(bad)
            with self.assertRaises(ValueError):
                self.runner.update_request_id(bad)

    def test_common_projection_does_not_remove_other_check_fields(self):
        module = importlib.import_module('rsi_eval.policy_transfer')
        packet = {'repair_policy':{},'experience_memory':[], 'audits':['must remain'],
                  'metadata':{'condition':'must fail'}}
        self.assertEqual(module.common_packet(packet), {'audits':['must remain'],
                  'metadata':{'condition':'must fail'}})


if __name__ == '__main__':
    unittest.main()
