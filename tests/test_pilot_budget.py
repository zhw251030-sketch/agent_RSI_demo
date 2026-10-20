import json
import tempfile
import unittest
from pathlib import Path

from rsi_eval.pilot_budget import BudgetExceeded, BudgetLedger


class PilotBudgetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'budget.json'

    def test_ninth_request_and_fifth_session_request_are_blocked(self):
        ledger = BudgetLedger(self.path)
        for session in ('planning', 'symbolic'):
            for _ in range(4):
                ledger.reserve(session, {}, 10)
        with self.assertRaises(BudgetExceeded):
            ledger.reserve('planning', {}, 10)
        self.assertEqual(ledger.summary()['request_count'], 8)

        other = BudgetLedger(Path(self.temp.name) / 'other.json')
        for _ in range(4):
            other.reserve('planning', {}, 10)
        with self.assertRaises(BudgetExceeded):
            other.reserve('planning', {}, 10)
        self.assertEqual(other.summary()['request_count'], 4)

    def test_failed_or_unknown_call_keeps_reservation_and_is_not_zero_usage(self):
        ledger = BudgetLedger(self.path, max_requests=1)
        request_id = ledger.reserve('planning', {}, 10)
        before = ledger.summary()
        ledger.settle(request_id, None, error_type='TimeoutError')
        after = ledger.summary()
        self.assertEqual(after['request_count'], 1)
        self.assertEqual(after['reserved_tokens'], before['reserved_tokens'])
        self.assertEqual(after['reserved_cost_cny'], before['reserved_cost_cny'])
        self.assertIsNone(after['actual_tokens'])
        self.assertEqual(after['usage_unknown_count'], 1)
        self.assertTrue(after['halted'])
        self.assertIn('usage_unknown', after['halt_reasons'])
        with self.assertRaises(BudgetExceeded):
            ledger.reserve('symbolic', {}, 10)

    def test_success_without_usage_halts_and_preserves_reservation(self):
        ledger = BudgetLedger(self.path)
        request_id = ledger.reserve('planning', {}, 10)
        before = ledger.summary()
        ledger.settle(request_id, None)
        self.assertTrue(ledger.summary()['halted'])
        self.assertEqual(ledger.summary()['reserved_cost_cny'], before['reserved_cost_cny'])
        with self.assertRaises(BudgetExceeded):
            ledger.reserve('symbolic', {}, 10)

    def test_input_is_utf8_counted_and_payload_not_stored(self):
        payload = {'messages': ['秘密']}
        ledger = BudgetLedger(self.path, max_input_bytes=23)
        request_id = ledger.reserve('planning', payload, 10)
        state = json.loads(self.path.read_text(encoding='utf-8'))
        request = state['requests'][0]
        self.assertEqual(request['input_bytes'], 23)
        self.assertEqual(request['request_id'], request_id)
        self.assertEqual(len(request['payload_sha256']), 64)
        self.assertNotIn('秘密', self.path.read_text(encoding='utf-8'))

    def test_input_byte_cap_rejects_request_before_recording(self):
        ledger = BudgetLedger(self.path, max_input_bytes=5)
        with self.assertRaises(BudgetExceeded):
            ledger.reserve('planning', {'x': '汉'}, 10)
        self.assertEqual(ledger.summary()['request_count'], 0)

    def test_token_and_cost_limits_block_without_adding_request(self):
        tokens = BudgetLedger(self.path, max_reserved_tokens=8204)
        tokens.reserve('planning', {}, 10)
        with self.assertRaises(BudgetExceeded):
            tokens.reserve('symbolic', {}, 10)
        self.assertEqual(tokens.summary()['reserved_tokens'], 8204)
        cost = BudgetLedger(Path(self.temp.name) / 'cost.json', max_cost_cny=0.0173)
        cost.reserve('planning', {}, 10)
        with self.assertRaises(BudgetExceeded):
            cost.reserve('symbolic', {}, 10)
        self.assertAlmostEqual(cost.summary()['reserved_cost_cny'], 0.0172914)

    def test_bad_session_and_output_cap_rejected(self):
        ledger = BudgetLedger(self.path)
        for session, output in [('other', 10), ('planning', 4097),
                                ('planning', 0), ('planning', True)]:
            with self.subTest(session=session, output=output):
                with self.assertRaises((ValueError, BudgetExceeded)):
                    ledger.reserve(session, {}, output)
        self.assertEqual(ledger.summary()['request_count'], 0)

    def test_reopening_retains_usage_and_config_changes_are_rejected(self):
        ledger = BudgetLedger(self.path, max_requests=1)
        ledger.reserve('planning', {}, 10)
        reopened = BudgetLedger(self.path, max_requests=1)
        with self.assertRaises(BudgetExceeded):
            reopened.reserve('symbolic', {}, 10)
        with self.assertRaises(ValueError):
            BudgetLedger(self.path, max_requests=2)
        self.assertEqual(reopened.summary()['request_count'], 1)

    def test_settle_known_usage_is_idempotent_and_cost_is_uncached_estimate(self):
        ledger = BudgetLedger(self.path)
        request_id = ledger.reserve('planning', {}, 100)
        usage = {'prompt_tokens': 100, 'completion_tokens': 10, 'total_tokens': 110,
                 'prompt_tokens_details': {'cached_tokens': 90}}
        ledger.settle(request_id, usage)
        ledger.settle(request_id, usage)
        summary = ledger.summary()
        self.assertEqual(summary['actual_tokens'], 110)
        self.assertAlmostEqual(summary['actual_estimated_cost_cny'], 0.000294)
        with self.assertRaises(ValueError):
            ledger.settle(request_id, {'prompt_tokens': 101, 'completion_tokens': 10,
                                       'total_tokens': 111})

    def test_invalid_or_over_reservation_usage_halts_later_requests(self):
        bad_usage = [
            {'prompt_tokens': -1, 'completion_tokens': 1, 'total_tokens': 0},
            {'prompt_tokens': True, 'completion_tokens': 1, 'total_tokens': 2},
            {'prompt_tokens': 1, 'completion_tokens': 1, 'total_tokens': 999},
            {'prompt_tokens': 1, 'completion_tokens': 1},
            {'prompt_tokens': 8195, 'completion_tokens': 1, 'total_tokens': 8196},
            {'prompt_tokens': 1, 'completion_tokens': 11, 'total_tokens': 12},
            {'prompt_tokens': float('nan'), 'completion_tokens': 1, 'total_tokens': 2},
            {'prompt_tokens': float('inf'), 'completion_tokens': 1, 'total_tokens': 2},
            {'prompt_tokens': 10 ** 5000, 'completion_tokens': 1, 'total_tokens': 2},
        ]
        for i, usage in enumerate(bad_usage):
            with self.subTest(case=i):
                ledger = BudgetLedger(Path(self.temp.name) / f'bad-{i}.json')
                request_id = ledger.reserve('planning', {}, 10)
                ledger.settle(request_id, usage)
                self.assertTrue(ledger.summary()['halted'])
                with self.assertRaises(BudgetExceeded):
                    ledger.reserve('symbolic', {}, 10)

    def test_unsettled_request_remains_unknown_across_reopen(self):
        BudgetLedger(self.path).reserve('planning', {}, 10)
        summary = BudgetLedger(self.path).summary()
        self.assertEqual(summary['reserved_count'], 1)
        self.assertEqual(summary['usage_unknown_count'], 1)
        self.assertIsNone(summary['actual_tokens'])

    def test_held_lock_fails_closed_without_changing_ledger(self):
        ledger = BudgetLedger(self.path)
        original = self.path.read_bytes()
        lock_path = self.path.with_name(self.path.name + '.lock')
        lock_path.write_text('locked', encoding='utf-8')
        with self.assertRaises(BudgetExceeded):
            ledger.reserve('planning', {}, 10)
        self.assertEqual(self.path.read_bytes(), original)

    def test_error_message_cannot_be_written_as_exception_type(self):
        ledger = BudgetLedger(self.path)
        request_id = ledger.reserve('planning', {}, 10)
        with self.assertRaises(ValueError):
            ledger.settle(request_id, None, error_type='TimeoutError: secret')
        self.assertNotIn('secret', self.path.read_text(encoding='utf-8'))

    def test_transport_recovery_preserves_counts_and_reserved_budget(self):
        ledger = BudgetLedger(self.path, max_requests=2)
        request_id = ledger.reserve('planning', {}, 10)
        ledger.settle(request_id, None, error_type='InternalServerError')
        before = ledger.summary()
        ledger.resume_after_transport_failure()
        after = ledger.summary()
        self.assertFalse(after['halted'])
        self.assertEqual(after['request_count'], 1)
        self.assertEqual(after['reserved_tokens'], before['reserved_tokens'])
        self.assertEqual(after['reserved_cost_cny'], before['reserved_cost_cny'])
        self.assertEqual(after['usage_unknown_count'], 1)
        self.assertIsNone(after['actual_tokens'])
        self.assertEqual(after['recovery']['kind'], 'operator_transport_recovery')
        self.assertEqual(after['recovery']['unknown_request_ids'], [request_id])
        ledger.reserve('symbolic', {}, 10)
        with self.assertRaises(BudgetExceeded):
            ledger.reserve('symbolic', {}, 10)

    def test_transport_recovery_is_allowed_only_once_even_after_reopen(self):
        ledger = BudgetLedger(self.path)
        first = ledger.reserve('planning', {}, 10)
        ledger.settle(first, None, error_type='APIConnectionError')
        ledger.resume_after_transport_failure()
        second = ledger.reserve('planning', {}, 10)
        ledger.settle(second, None, error_type='ReadTimeout')
        reopened = BudgetLedger(self.path)
        with self.assertRaises(BudgetExceeded):
            reopened.resume_after_transport_failure()
        self.assertTrue(reopened.summary()['halted'])

    def test_transport_recovery_rejects_nontransport_missing_usage(self):
        for i, error_type in enumerate((None, 'ValueError', 'TimeoutError')):
            with self.subTest(error_type=error_type):
                ledger = BudgetLedger(Path(self.temp.name) / f'recovery-{i}.json')
                request_id = ledger.reserve('planning', {}, 10)
                ledger.settle(request_id, None, error_type=error_type)
                with self.assertRaises(BudgetExceeded):
                    ledger.resume_after_transport_failure()
                self.assertTrue(ledger.summary()['halted'])

    def test_transport_recovery_rejects_invalid_usage_and_pending_requests(self):
        invalid = BudgetLedger(self.path)
        request_id = invalid.reserve('planning', {}, 10)
        invalid.settle(request_id, {}, error_type='InternalServerError')
        with self.assertRaises(BudgetExceeded):
            invalid.resume_after_transport_failure()
        pending = BudgetLedger(Path(self.temp.name) / 'pending.json')
        first = pending.reserve('planning', {}, 10)
        pending.reserve('symbolic', {}, 10)
        pending.settle(first, None, error_type='Timeout')
        with self.assertRaises(BudgetExceeded):
            pending.resume_after_transport_failure()


if __name__ == '__main__':
    unittest.main()
