"""Shared 36-slot budget; no provider or task execution."""
import json
from pathlib import Path
import tempfile
import unittest

try:
    from rsi_eval.strategy_pair_budget import StrategyPairBudgetLedger
except ModuleNotFoundError as error:
    if error.name != 'rsi_eval.strategy_pair_budget':
        raise
    StrategyPairBudgetLedger = None
from rsi_eval.pilot_budget import BudgetExceeded

ROOT = Path(__file__).resolve().parents[1]
SLOTS = [s['id'] for s in json.loads((ROOT / 'configs/pilots/strategy-pair-allocation-v0.1.json').read_text(encoding='utf-8'))['slots']]
USAGE = dict(prompt_tokens=2, completion_tokens=3, total_tokens=5)


class StrategyPairBudgetTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(StrategyPairBudgetLedger, '36-slot strategy budget successor is missing')
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'ledger.json'

    def ledger(self):
        return StrategyPairBudgetLedger(self.path, list(SLOTS))

    def test_complete_36_requests_have_one_shared_cap_and_unique_ids(self):
        ledger = self.ledger()
        identifiers = []
        for slot in SLOTS:
            request = ledger.reserve(slot, {}, 8192)
            identifiers.append(request)
            ledger.settle(request, USAGE)
        self.assertEqual(identifiers, [f'request-{i:04d}' for i in range(1, 37)])
        report = ledger.summary()
        self.assertEqual(report['request_count'], 36)
        self.assertEqual(report['session_counts'], dict.fromkeys(SLOTS, 1))
        self.assertEqual(report['known_total_tokens'], 180)
        self.assertEqual(report['config']['max_cost_cny'], 12)
        self.assertEqual(report['config']['max_reserved_tokens'], 4128768)
        self.assertEqual(report['config']['max_requests_per_session'], 1)
        before = self.path.read_bytes()
        with self.assertRaises(BudgetExceeded):
            ledger.reserve(SLOTS[0], {}, 8192)
        self.assertEqual(self.path.read_bytes(), before)

    def test_only_exact_frozen_allowlist_is_accepted_before_creation(self):
        invalid = [SLOTS[:-1], SLOTS+[SLOTS[0]], list(reversed(SLOTS)),
                   SLOTS[:1]+SLOTS[:35], ['replacement']+SLOTS[1:], tuple(SLOTS), None]
        for ids in invalid:
            with self.subTest(ids=ids):
                with self.assertRaises(ValueError):
                    StrategyPairBudgetLedger(self.path, ids)
                self.assertFalse(self.path.exists())

    def test_out_of_order_and_duplicate_slots_do_not_spend(self):
        ledger = self.ledger()
        before = self.path.read_bytes()
        with self.assertRaises(BudgetExceeded):
            ledger.reserve(SLOTS[1], {}, 8192)
        self.assertEqual(self.path.read_bytes(), before)
        request = ledger.reserve(SLOTS[0], {}, 8192)
        ledger.settle(request, USAGE)
        before = self.path.read_bytes()
        for slot in (SLOTS[0], SLOTS[2]):
            with self.assertRaises(BudgetExceeded):
                ledger.reserve(slot, {}, 8192)
            self.assertEqual(self.path.read_bytes(), before)

    def test_unsettled_request_blocks_next_slot_and_reopen(self):
        ledger = self.ledger()
        request = ledger.reserve(SLOTS[0], {}, 8192)
        for attempt in (ledger, self.ledger()):
            with self.assertRaises(BudgetExceeded):
                attempt.reserve(SLOTS[1], {}, 8192)
        ledger.settle(request, USAGE)
        self.assertEqual(self.ledger().reserve(SLOTS[1], {}, 8192), 'request-0002')

    def test_unknown_usage_halts_every_phase_and_never_recovers(self):
        ledger = self.ledger()
        request = ledger.reserve(SLOTS[0], {}, 8192)
        reserved = ledger.summary()['reserved_cost_cny']
        ledger.settle(request, None, error_type='APIConnectionError')
        for attempt in (ledger, self.ledger()):
            with self.assertRaises(BudgetExceeded):
                attempt.reserve(SLOTS[1], {}, 8192)
            with self.assertRaises(BudgetExceeded):
                attempt.resume_after_transport_failure()
        summary = ledger.summary()
        self.assertIsNone(summary['actual_estimated_cost_cny'])
        self.assertEqual(summary['usage_unknown_count'], 1)
        self.assertEqual(summary['reserved_cost_cny'], reserved)
        self.assertIsNone(summary['recovery'])

    def test_invalid_usage_blocks_acceptance_even_without_transport_error(self):
        ledger = self.ledger()
        request = ledger.reserve(SLOTS[0], {}, 8192)
        ledger.settle(request, dict(prompt_tokens=1, completion_tokens=1, total_tokens=3))
        self.assertTrue(ledger.summary()['halted'])
        with self.assertRaises(BudgetExceeded):
            ledger.reserve(SLOTS[1], {}, 8192)

    def test_known_usage_transport_failure_still_stops_the_experiment(self):
        ledger = self.ledger()
        request = ledger.reserve(SLOTS[0], {}, 8192)
        ledger.settle(request, USAGE, error_type='TimeoutError')
        self.assertEqual(ledger.summary()['usage_unknown_count'], 0)
        with self.assertRaises(BudgetExceeded):
            ledger.reserve(SLOTS[1], {}, 8192)

    def test_tampered_persisted_order_is_rejected_on_reopen(self):
        ledger = self.ledger()
        request = ledger.reserve(SLOTS[0], {}, 8192)
        ledger.settle(request, USAGE)
        data = json.loads(self.path.read_text(encoding='utf-8'))
        data['requests'][0]['session_id'] = SLOTS[1]
        self.path.write_text(json.dumps(data), encoding='utf-8')
        with self.assertRaises(ValueError):
            self.ledger()

    def test_full_request_input_limit_and_output_limit_are_preserved(self):
        ledger = self.ledger()
        for payload, output in [({'text':'x'*98304},8192), ({},8193)]:
            with self.subTest(output=output):
                with self.assertRaises(BudgetExceeded):
                    ledger.reserve(SLOTS[0], payload, output)
        self.assertEqual(ledger.summary()['request_count'], 0)

    def test_reopen_requires_identical_config_and_keeps_known_usage(self):
        ledger = self.ledger()
        request = ledger.reserve(SLOTS[0], {}, 8192)
        ledger.settle(request, USAGE)
        self.assertEqual(self.ledger().summary()['actual_tokens'], 5)
        data = json.loads(self.path.read_text(encoding='utf-8'))
        data['config']['max_cost_cny'] = 13
        self.path.write_text(json.dumps(data), encoding='utf-8')
        with self.assertRaises(ValueError):
            self.ledger()

    def test_unknown_slot_and_caller_list_mutation_are_rejected(self):
        ids = list(SLOTS)
        ledger = StrategyPairBudgetLedger(self.path, ids)
        ids[0] = 'injected'
        for slot in ('injected', 'planning', True, None):
            with self.assertRaises(ValueError):
                ledger.reserve(slot, {}, 8192)
        self.assertEqual(ledger.session_ids, tuple(SLOTS))


if __name__ == '__main__':
    unittest.main()
