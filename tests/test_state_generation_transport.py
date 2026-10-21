"""Transport observation with fake providers; SDK integration is explicit."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

try:
    import rsi_eval.state_generation_transport as observer
except ModuleNotFoundError as error:
    if error.name != 'rsi_eval.state_generation_transport':
        raise
    observer = None

try:
    SDK_PRESENT = importlib.util.find_spec('openhands.sdk') is not None
except ModuleNotFoundError:
    SDK_PRESENT = False


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(observer, 'The transport observer is not implemented')
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.directory = Path(temp.name)/'session'
        (self.directory/'requests').mkdir(parents=True)
        self.request = self.directory/'requests/request-0003.request.json'
        self.request.write_text('{"model":"fixture","messages":[]}\n', encoding='utf-8')
        self.provider = Mock(return_value=object())
        self.module = SimpleNamespace(litellm_completion=self.provider)
        self.lookup = patch('rsi_eval.state_generation_transport.importlib.import_module', return_value=self.module)
        self.lookup.start()
        self.addCleanup(self.lookup.stop)

    def invoke(self, **changes):
        args = {'timeout': 180, 'max_retries': 0, 'stream': False,
                'api_key': 'private-key-fixture', 'extra_headers': {'secret': 'private-header'}}
        args.update(changes)
        with observer.observed_transport(self.directory):
            return self.module.litellm_completion(**args)

    def read(self, name):
        return json.loads((self.directory/name).read_text())

    def test_receipts_bind_unique_request_and_are_durable_before_dispatch(self):
        expected = self.provider.return_value
        def call(**kwargs):
            receipt = self.read('transport-request.json')
            self.assertEqual(receipt['request_file'], 'requests/request-0003.request.json')
            self.assertEqual(receipt['request_sha256'], hashlib.sha256(self.request.read_bytes()).hexdigest())
            self.assertEqual(receipt['timeout_seconds'], 180)
            self.assertEqual(kwargs['api_key'], 'private-key-fixture')
            self.assertFalse((self.directory/'transport-result.json').exists())
            return expected
        self.provider.side_effect = call
        with patch.object(observer.os, 'fsync', wraps=__import__('os').fsync) as fsync:
            self.assertIs(self.invoke(), expected)
        self.assertGreaterEqual(fsync.call_count, 2)
        receipt = self.read('transport-request.json')
        self.assertEqual(set(receipt), {'version','expected_timeout_seconds','timeout_seconds','max_retries',
            'stream_present','stream','num_retries_present','num_retries','request_file','request_sha256'})
        result = self.read('transport-result.json')
        self.assertEqual(result['status'], 'returned')
        self.assertIsNone(result['error_type'])
        self.assertGreaterEqual(result['elapsed_seconds'], 0)
        self.assertEqual(result['request_receipt_sha256'],
            hashlib.sha256((self.directory/'transport-request.json').read_bytes()).hexdigest())
        for path in self.directory.glob('transport-*.json'):
            self.assertNotIn('private', path.read_text())
        self.assertIs(self.module.litellm_completion, self.provider)

    def test_optional_fields_record_presence_and_effective_false(self):
        with observer.observed_transport(self.directory):
            self.module.litellm_completion(timeout=180, max_retries=0)
        saved = self.read('transport-request.json')
        self.assertFalse(saved['stream_present'])
        self.assertIs(saved['stream'], False)
        self.assertFalse(saved['num_retries_present'])
        self.assertIsNone(saved['num_retries'])

    def test_explicit_zero_num_retries_is_preserved(self):
        self.invoke(num_retries=0)
        saved = self.read('transport-request.json')
        self.assertTrue(saved['num_retries_present'])
        self.assertEqual(saved['num_retries'], 0)

    def test_invalid_transport_flags_refuse_before_dispatch(self):
        cases = [{'timeout':60}, {'timeout':None}, {'timeout':True}, {'timeout':float('nan')},
                 {'max_retries':True}, {'max_retries':1}, {'max_retries':0.0},
                 {'num_retries':False}, {'num_retries':1}, {'num_retries':None},
                 {'stream':True}, {'stream':0}, {'stream':None}]
        for changes in cases:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.invoke(**changes)
            self.provider.assert_not_called()
            self.assertFalse((self.directory/'transport-request.json').exists())

    def test_missing_max_retries_is_not_assumed_safe(self):
        with observer.observed_transport(self.directory):
            with self.assertRaises(ValueError):
                self.module.litellm_completion(timeout=180)
        self.provider.assert_not_called()

    def test_second_dispatch_refused_without_overwriting_first_receipts(self):
        with observer.observed_transport(self.directory):
            self.module.litellm_completion(timeout=180, max_retries=0)
            before = {p.name:p.read_bytes() for p in self.directory.glob('transport-*.json')}
            with self.assertRaises(RuntimeError):
                self.module.litellm_completion(timeout=180, max_retries=0)
        self.assertEqual(self.provider.call_count, 1)
        self.assertEqual(before, {p.name:p.read_bytes() for p in self.directory.glob('transport-*.json')})

    def test_existing_receipt_refuses_before_network(self):
        for name in ('transport-request.json','transport-result.json'):
            target = self.directory/name
            target.write_bytes(b'original')
            with self.assertRaises(FileExistsError):
                self.invoke()
            self.assertEqual(target.read_bytes(), b'original')
            target.unlink()
        self.provider.assert_not_called()

    def test_request_must_be_present_unique_and_regular(self):
        self.request.unlink()
        with self.assertRaises(ValueError):
            self.invoke()
        self.request.write_text('{}')
        second = self.request.with_name('request-0004.request.json')
        second.write_text('{}')
        with self.assertRaises(ValueError):
            self.invoke()
        second.unlink()
        self.request.unlink()
        self.request.mkdir()
        with self.assertRaises(ValueError):
            self.invoke()
        self.provider.assert_not_called()

    def test_provider_exception_is_reraised_without_sensitive_text(self):
        error = TimeoutError('private-error-fixture')
        self.provider.side_effect = error
        with self.assertRaises(TimeoutError) as caught:
            self.invoke()
        self.assertIs(caught.exception, error)
        saved = self.read('transport-result.json')
        self.assertEqual(saved['status'], 'raised')
        self.assertEqual(saved['error_type'], 'TimeoutError')
        self.assertNotIn('private-error-fixture', json.dumps(saved))
        self.assertIs(self.module.litellm_completion, self.provider)

    def test_elapsed_uses_monotonic_clock(self):
        with patch.object(observer.time, 'monotonic', side_effect=[10.5, 13.25]):
            self.invoke()
        self.assertEqual(self.read('transport-result.json')['elapsed_seconds'], 2.75)

    def test_context_without_dispatch_creates_no_receipts(self):
        with observer.observed_transport(self.directory):
            pass
        self.assertEqual(list(self.directory.glob('transport-*.json')), [])
        self.provider.assert_not_called()

    def test_nested_observers_and_non180_expectations_refuse(self):
        with self.assertRaises(ValueError):
            with observer.observed_transport(self.directory, expected_timeout=60):
                pass
        with observer.observed_transport(self.directory):
            with self.assertRaises(RuntimeError):
                with observer.observed_transport(self.directory):
                    pass
        self.provider.assert_not_called()


@unittest.skipUnless(SDK_PRESENT, 'Requires server OpenHands SDK 1.55.1; no local SDK installed')
class TransportSDKTests(unittest.TestCase):
    def test_real_sdk_call_boundary_uses_180_and_zero_retries(self):
        self.assertIsNotNone(observer)
        from tests.test_state_generation_agent import Recorder, GenerationSDKTests
        from rsi_eval.state_generation_agent import GenerationStatePacketLLM, run_generation_session
        from rsi_eval.pilot_budget import BudgetLedger
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            c = Recorder(output)
            ledger = BudgetLedger(output/'budget-ledger.json',session_ids=['sdk180'],
                max_requests=1,max_requests_per_session=1,max_output_tokens=8192,
                max_input_bytes=65536,max_reserved_tokens=1000000,max_cost_cny=5)
            llm = GenerationStatePacketLLM(model='anthropic/minimax-m3',api_key='offline-placeholder',
                base_url='https://example.invalid',timeout=180,num_retries=0,max_output_tokens=8192,
                caching_prompt=False,stream=False,api_mode='chat',reasoning_effort='none',
                native_tool_calling=True,force_string_serializer=False,fallback_strategy=None,
                log_completions=False).bind_controller(c).bind_pilot(ledger,'sdk180',output/'requests')
            with patch('openhands.sdk.llm.llm.litellm_completion',
                       return_value=GenerationSDKTests.response(GenerationSDKTests.arguments())) as provider:
                with observer.observed_transport(output):
                    result = run_generation_session(c,llm,'sdk180',output)
            self.assertEqual(provider.call_count,1)
            self.assertEqual(provider.call_args.kwargs['timeout'],180)
            self.assertEqual(provider.call_args.kwargs['max_retries'],0)
            self.assertEqual(len(c.calls),1)
            self.assertEqual(result['controller']['candidate_executions'],0)
            receipt = json.loads((output/'transport-request.json').read_text())
            self.assertEqual(receipt['timeout_seconds'],180)
            self.assertEqual(receipt['request_file'],'requests/request-0001.request.json')


if __name__ == '__main__':
    unittest.main()
