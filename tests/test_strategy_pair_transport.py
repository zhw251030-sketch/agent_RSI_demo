"""The actual SDK provider boundary must match the budgeted public payload."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

try:
    from rsi_eval import strategy_pair_transport as transport
except ImportError:
    transport=None
try:
    SDK=importlib.util.find_spec('openhands.sdk') is not None
except ModuleNotFoundError:
    SDK=False


def settings():
    return dict(model='anthropic/MiniMax-M3',base_url='https://api.minimax.cn/anthropic',
        temperature=1.0,max_output_tokens=8192,timeout=180,num_retries=0,caching_prompt=False,
        reasoning_effort='none',litellm_extra_body={'thinking':{'type':'disabled'}})


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(transport,'Actual dispatch fidelity observer is not implemented')
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.output=Path(tmp.name)
        (self.output/'requests').mkdir()
        self.request=dict(model='anthropic/MiniMax-M3',messages=[dict(role='user',content='{"task":"fixture"}')],
            tools=[dict(type='function',function=dict(name='submit_policy',parameters={'type':'object'}))],
            tool_choice=None,max_output_tokens=8192)
        (self.output/'requests/request-0001.request.json').write_text(json.dumps(self.request),encoding='utf-8')
        self.kwargs=dict(model='MiniMax-M3',custom_llm_provider='anthropic',api_base='https://api.minimax.cn/anthropic',
            timeout=180,max_retries=0,temperature=1.0,seed=None,drop_params=True,max_completion_tokens=8192,
            messages=copy.deepcopy(self.request['messages']),tools=copy.deepcopy(self.request['tools']),
            extra_body={'thinking':{'type':'disabled'}},api_key='secret-fixture-value',
            extra_headers={'authorization':'secret-fixture-header'})

    def observed(self,kwargs=None):
        called=[]
        module=SimpleNamespace(litellm_completion=lambda **values: called.append(True) or 'response')
        with patch('rsi_eval.strategy_pair_transport.importlib.import_module',return_value=module):
            with transport.observed_strategy_transport(self.output,settings()):
                result=module.litellm_completion(**(kwargs or self.kwargs))
        return called,result

    def test_matching_dispatch_is_persisted_and_secret_values_are_excluded(self):
        called,result=self.observed()
        self.assertEqual(called,[True])
        self.assertEqual(result,'response')
        proof=transport.verify_dispatch_record(self.output,settings())
        self.assertEqual(proof['version'],'strategy-pair-dispatch-v0.1')
        self.assertEqual(proof['observed']['max_completion_tokens'],8192)
        self.assertTrue((self.output/'transport-request.json').is_file())
        self.assertTrue((self.output/'transport-result.json').is_file())
        text=''.join(p.read_text() for p in self.output.glob('*.json'))
        self.assertNotIn('secret-fixture-value',text)
        self.assertNotIn('secret-fixture-header',text)

    def test_changed_messages_or_tools_cannot_reach_provider(self):
        for name,value in [('messages',[dict(role='user',content='altered')]),('tools',[])]:
            with self.subTest(name=name):
                output=self.output/name
                output.mkdir();(output/'requests').mkdir()
                (output/'requests/request-0001.request.json').write_text(json.dumps(self.request))
                module=SimpleNamespace(litellm_completion=lambda **_: self.fail('Altered payload reached provider'))
                with patch('rsi_eval.strategy_pair_transport.importlib.import_module',return_value=module):
                    with transport.observed_strategy_transport(output,settings()):
                        with self.assertRaises(ValueError):
                            module.litellm_completion(**(self.kwargs|{name:value}))
                self.assertFalse((output/'sdk-dispatch.json').exists())

    def test_changed_sampling_model_output_or_thinking_are_rejected(self):
        bad=[dict(temperature=0.1),dict(seed=42),dict(drop_params=False),dict(max_completion_tokens=4096),
             dict(model='another-model'),dict(custom_llm_provider='openai'),dict(api_base='https://another.invalid'),
             dict(tool_choice='none'),dict(reasoning_effort='none'),dict(extra_body={'thinking':{'type':'enabled'}}),
             dict(top_p=0.4),dict(fallbacks=['other']),dict(cache=True),dict(stream=True),dict(max_retries=1)]
        for changed in bad:
            with self.subTest(changed=changed),self.assertRaises(ValueError):
                transport.validate_dispatch(self.output,self.kwargs|changed,settings())

    def test_proof_replay_detects_request_or_safe_projection_mutation(self):
        self.observed()
        path=self.output/'sdk-dispatch.json'
        original=path.read_bytes()
        proof=json.loads(original);proof['observed']['temperature']=0.5
        path.write_text(json.dumps(proof))
        with self.assertRaises(ValueError): transport.verify_dispatch_record(self.output,settings())
        path.write_bytes(original)
        req=self.output/'requests/request-0001.request.json';req.write_text(json.dumps(self.request)+' ')
        with self.assertRaises(ValueError): transport.verify_dispatch_record(self.output,settings())

    def test_public_settings_digest_does_not_hash_credentials(self):
        first=transport.validate_dispatch(self.output,self.kwargs,settings()|{'api_key':'secret-first'})
        second=transport.validate_dispatch(self.output,self.kwargs,settings()|{'api_key':'secret-second'})
        self.assertEqual(first['settings_sha256'],second['settings_sha256'])
        self.assertEqual(first,second)

    def test_provider_failure_keeps_actual_dispatch_and_safe_error_class(self):
        module=SimpleNamespace(litellm_completion=lambda **_: (_ for _ in ()).throw(RuntimeError('private exception body')))
        with patch('rsi_eval.strategy_pair_transport.importlib.import_module',return_value=module):
            with transport.observed_strategy_transport(self.output,settings()):
                with self.assertRaises(RuntimeError): module.litellm_completion(**self.kwargs)
        proof=transport.verify_dispatch_record(self.output,settings())
        self.assertEqual(proof['request_file'],'requests/request-0001.request.json')
        result=json.loads((self.output/'transport-result.json').read_text())
        self.assertEqual(result['status'],'raised')
        self.assertEqual(result['error_type'],'RuntimeError')
        self.assertNotIn('private exception body',json.dumps(result))

    def test_second_provider_dispatch_and_proof_overwrite_are_denied(self):
        count=[]
        module=SimpleNamespace(litellm_completion=lambda **_: count.append(True))
        with patch('rsi_eval.strategy_pair_transport.importlib.import_module',return_value=module):
            with transport.observed_strategy_transport(self.output,settings()):
                module.litellm_completion(**self.kwargs)
                with self.assertRaises(RuntimeError): module.litellm_completion(**self.kwargs)
            with self.assertRaises(FileExistsError):
                with transport.observed_strategy_transport(self.output,settings()): pass
        self.assertEqual(len(count),1)


@unittest.skipUnless(SDK,'Requires actual server OpenHands SDK 1.55.1')
class ActualSDKDispatchTest(unittest.TestCase):
    def test_actual_sdk_normalization_matches_saved_request_and_frozen_sampling(self):
        from tests.test_strategy_pair_agent import SDKTests
        fixture=SDKTests('test_sdk_roundtrip_preserves_actual_packet_request_response_and_acceptance')
        fixture.setUp()
        try:
            controller,llm,ledger,slot=fixture.bound()
            # Actual settings must be bound before provider info is initialized.
            from rsi_eval.strategy_pair_agent import make_llm,run_session
            llm=make_llm(settings()|{'api_key':'offline-placeholder','capability_overrides':
                {'supports_reasoning_effort':False,'supports_sampling_params':True}},controller,ledger)
            with patch('openhands.sdk.llm.llm.litellm_completion',return_value=fixture.response({'source':'x','n_params':0})):
                with transport.observed_strategy_transport(fixture.output,settings()):
                    result=run_session(controller,llm,slot,fixture.output)
            self.assertEqual(result['status'],'accepted',result)
            proof=transport.verify_dispatch_record(fixture.output,settings())
            self.assertEqual(proof['observed']['model'],'MiniMax-M3')
            self.assertEqual(proof['observed']['custom_llm_provider'],'anthropic')
            self.assertFalse(proof['observed']['reasoning_effort_present'])
            self.assertEqual(ledger.summary()['request_count'],1)
        finally:
            fixture.doCleanups()


if __name__=='__main__':unittest.main()
