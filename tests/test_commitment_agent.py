"""Commitment tool contracts and real SDK loops with an offline provider."""
import ast
import copy
import importlib.util
import json
import logging
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
EDIT_CLAIMS = ('keep_bytes', 'keep_ast', 'apply_format_patch',
               'remove_selected_term', 'general_edit')
DEPLOYMENT_CLAIMS = ('raw_validation', 'probe_repair_deployed', 'unspecified')
try:
    SDK_PRESENT = importlib.util.find_spec('openhands.sdk') is not None
except ModuleNotFoundError:
    SDK_PRESENT = False

if SDK_PRESENT:
    from jsonschema import Draft202012Validator
    from litellm.types.utils import ModelResponse
    from pydantic import ValidationError
    from rsi_eval.pilot_budget import BudgetExceeded, BudgetLedger
    from rsi_eval.commitment_agent import (
        CommitmentAction, DraftStatePacketLLM, ReviewStatePacketLLM,
        run_commitment_session, DRAFT_SYSTEM_PROMPT, REVIEW_SYSTEM_PROMPT,
    )


class CommitmentDeclaredContractTests(unittest.TestCase):
    def test_claim_fields_are_explicit_required_literal_business_fields(self):
        # This checks the public declaration when this interpreter has no SDK;
        # runtime coercion and model-facing schema are tested with the real SDK.
        tree = ast.parse((ROOT/'rsi_eval/commitment_agent.py').read_text(encoding='utf-8'))
        action = next(node for node in tree.body
                      if isinstance(node, ast.ClassDef) and node.name == 'CommitmentAction')
        fields = {node.target.id: node for node in action.body
                  if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)}
        for name, values in [('edit_claim', EDIT_CLAIMS), ('deployment_claim', DEPLOYMENT_CLAIMS)]:
            field = fields[name]
            self.assertEqual(field.annotation.value.id, 'Literal')
            self.assertEqual(ast.literal_eval(field.annotation.slice), values)
            self.assertIsInstance(field.value, ast.Call)
            self.assertFalse(field.value.args)
            self.assertNotIn('default', [keyword.arg for keyword in field.value.keywords])


class Recorder:
    def __init__(self, output, stage, feedback=None):
        self.output_dir = output
        self.stage = stage
        self.feedback = copy.deepcopy(feedback)
        self.calls = []
        self.halted = False
        self.infrastructure_error_type = None

    def task_packet(self):
        return {'version': 'commitment-sdk-fixture', 'stage': self.stage,
                'source': 'def solve(): return []',
                'checker_feedback': copy.deepcopy(self.feedback)}

    def task_prompt(self):
        return json.dumps(self.task_packet())

    def submit(self, *, session_id, source, n_params, rationale, auxiliary,
               edit_claim, deployment_claim):
        self.calls.append(dict(session_id=session_id, source=source, n_params=n_params,
            rationale=rationale, auxiliary=copy.deepcopy(auxiliary), edit_claim=edit_claim,
            deployment_claim=deployment_claim))
        return {'status': 'recorded', 'candidate_executions': 0}

    def summary(self):
        return {'submissions': len(self.calls), 'halted': self.halted,
                'candidate_executions': 0}


@unittest.skipUnless(SDK_PRESENT, 'OpenHands SDK is not installed in this interpreter')
class CommitmentSDKTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        level = logging.root.manager.disable
        logging.disable(logging.CRITICAL)
        self.addCleanup(logging.disable, level)

    @staticmethod
    def arguments(**changes):
        return dict(source='def solve(): return []', n_params=0, rationale='Keep the source.',
                    auxiliary={}, edit_claim='keep_bytes', deployment_claim='raw_validation') | changes

    @staticmethod
    def response(args=None, *, tool='submit_draft', second=False, reason='tool_calls'):
        message = {'role': 'assistant', 'content': 'Offline fixture.'}
        if args is not None:
            call = {'id': 'call-1', 'type': 'function',
                    'function': {'name': tool, 'arguments': json.dumps(args)}}
            message['tool_calls'] = [call]
            if second:
                message['tool_calls'].append({**copy.deepcopy(call), 'id': 'call-2'})
        return ModelResponse(id='response-fixture', model='minimax-m3',
            choices=[{'message': message, 'finish_reason': reason}],
            usage={'prompt_tokens': 100, 'completion_tokens': 20, 'total_tokens': 120})

    def bound(self, name, stage, feedback=None, **budgets):
        output = self.root/name
        output.mkdir()
        controller = Recorder(output, stage, feedback)
        ledger = BudgetLedger(output/'budget-ledger.json', session_ids=[name],
            max_requests=1, max_requests_per_session=1, **budgets)
        cls = DraftStatePacketLLM if stage == 'draft' else ReviewStatePacketLLM
        llm = cls(model='anthropic/minimax-m3', api_key='offline-placeholder',
            base_url='https://example.invalid', max_output_tokens=4096, num_retries=0,
            caching_prompt=False, api_mode='chat', stream=False, reasoning_effort='none',
            native_tool_calling=True, force_string_serializer=False, fallback_strategy=None,
            log_completions=False).bind_controller(controller).bind_pilot(
                ledger, name, output/'requests')
        return controller, llm, ledger, output

    def run_mock(self, name, stage, args=None, **options):
        c, llm, ledger, output = self.bound(name, stage)
        options.setdefault('tool', 'submit_draft' if stage == 'draft' else 'submit_candidate')
        with patch('openhands.sdk.llm.llm.litellm_completion',
                   return_value=self.response(args, **options)) as provider:
            result = run_commitment_session(c, llm, name, output, stage=stage)
        self.assertEqual(provider.call_count, 1)
        return c, llm, ledger, output, result

    def test_schema_preserves_required_enum_claims_and_primitive_bounds(self):
        schema = CommitmentAction.to_mcp_schema()
        self.assertEqual(set(schema['properties']), set(self.arguments()))
        self.assertIs(schema['additionalProperties'], False)
        self.assertTrue({'source', 'n_params', 'edit_claim', 'deployment_claim'} <= set(schema['required']))
        self.assertEqual(tuple(schema['properties']['edit_claim']['enum']), EDIT_CLAIMS)
        self.assertEqual(tuple(schema['properties']['deployment_claim']['enum']), DEPLOYMENT_CLAIMS)
        self.assertNotIn('session_id', schema['properties'])
        Draft202012Validator(schema).validate(self.arguments())

    def test_missing_or_wrong_claims_and_unsafe_source_never_validate(self):
        for field in ('edit_claim', 'deployment_claim'):
            args = self.arguments(); del args[field]
            with self.subTest(missing=field), self.assertRaises(ValidationError):
                CommitmentAction.model_validate(args)
        for changes in [{'edit_claim': 'verified'}, {'edit_claim': True},
                        {'deployment_claim': None}, {'deployment_claim': ['raw_validation']},
                        {'n_params': True}, {'source': '中'*5462},
                        {'rationale': 'x'*4001}, {'task_id': 'sealed'}]:
            with self.subTest(changes=list(changes)), self.assertRaises(ValidationError):
                CommitmentAction.model_validate(self.arguments(**changes))

    def test_auxiliary_remains_soft_but_finite_and_bounded(self):
        auxiliary = {'forecast': 'wrong type is retained', 'notes': [None, True, 9]}
        self.assertEqual(CommitmentAction.model_validate(self.arguments(auxiliary=auxiliary)).auxiliary,
                         auxiliary)
        for auxiliary in [{'x': float('nan')}, {'x': '\ud800'}, {'x': 'x'*65536}]:
            with self.subTest(auxiliary_type=type(auxiliary['x'])), self.assertRaises(ValidationError):
                CommitmentAction.model_validate(self.arguments(auxiliary=auxiliary))

    def test_both_stages_roundtrip_once_with_only_the_declared_tool(self):
        for stage in ('draft', 'review'):
            args = self.arguments(); name = 'roundtrip_'+stage
            c, _, ledger, output, result = self.run_mock(name, stage, args)
            tool = 'submit_draft' if stage == 'draft' else 'submit_candidate'
            self.assertEqual(c.calls, [dict(session_id=name, **args)])
            self.assertEqual(result['tools'], sorted(['finish', tool]))
            self.assertEqual(result['stage'], stage)
            self.assertEqual(result['controller']['candidate_executions'], 0)
            self.assertEqual(ledger.summary()['known_total_tokens'], 120)
            saved = json.loads((output/'sdk-submission.json').read_text())
            self.assertEqual(saved, {'stage': stage, 'tool': tool, 'session_id': name,
                                    'business': args})
            payload = json.loads((output/'requests/request-0001.request.json').read_text())
            content = payload['messages'][0]['content']
            text = content if isinstance(content, str) else ''.join(x['text'] for x in content if x['type']=='text')
            self.assertIn(DRAFT_SYSTEM_PROMPT if stage == 'draft' else REVIEW_SYSTEM_PROMPT, text)
            self.assertEqual(json.loads(payload['messages'][1]['content']), c.task_packet())

    def test_submission_is_durable_before_keyword_only_controller_dispatch(self):
        for stage in ('draft', 'review'):
            name = 'before_'+stage; c, llm, _, output = self.bound(name, stage)
            original = c.submit; args = self.arguments()
            def observe(**values):
                self.assertEqual(json.loads((output/'sdk-submission.json').read_text())['business'], args)
                return original(**values)
            tool = 'submit_draft' if stage == 'draft' else 'submit_candidate'
            with patch.object(c, 'submit', side_effect=observe), \
                 patch('openhands.sdk.llm.llm.litellm_completion', return_value=self.response(args, tool=tool)), \
                 patch('rsi_eval.commitment_agent.os.fsync', wraps=__import__('os').fsync) as fsync:
                run_commitment_session(c, llm, name, output, stage=stage)
            self.assertEqual(len(c.calls), 1)
            self.assertGreaterEqual(fsync.call_count, 1)

    def test_raw_metadata_response_and_normalized_dispatch_remain_separate(self):
        raw_args = self.arguments(auxiliary=None, summary=42, security_risk=None)
        c, _, _, output, _ = self.run_mock('metadata', 'draft', raw_args)
        self.assertEqual(c.calls, [dict(session_id='metadata', **self.arguments())])
        raw = json.loads((output/'requests/request-0001.response.json').read_text())
        self.assertEqual(json.loads(raw['choices'][0]['message']['tool_calls'][0]['function']['arguments']), raw_args)
        self.assertEqual(json.loads((output/'sdk-submission.json').read_text())['business'], self.arguments())

    def test_same_review_envelope_differs_only_in_checker_feedback(self):
        payloads = []
        for name, feedback in [('self_arm', None), ('checked_arm', {'status': 'unknown'})]:
            c, llm, _, output = self.bound(name, 'review', feedback)
            with patch('openhands.sdk.llm.llm.litellm_completion',
                       return_value=self.response(self.arguments(), tool='submit_candidate')):
                run_commitment_session(c, llm, name, output, stage='review')
            payload = json.loads((output/'requests/request-0001.request.json').read_text())
            packet = json.loads(payload['messages'][1]['content']); packet.pop('checker_feedback')
            payload['messages'][1]['content'] = packet
            payloads.append(payload)
        self.assertEqual(*payloads)

    def test_wrong_stage_ambient_and_multiple_tools_are_never_dispatched(self):
        for name, tool, second in [('wrongstage', 'submit_candidate', False),
                                   ('ambient', 'read_file', False), ('multiple', 'submit_draft', True)]:
            c, _, ledger, _, _ = self.run_mock(name, 'draft', self.arguments(), tool=tool, second=second)
            self.assertEqual(c.calls, [])
            self.assertEqual(ledger.summary()['known_total_tokens'], 120)

    def test_invalid_claim_or_extra_business_field_is_not_a_submission(self):
        for name, changes in [('badclaim', {'edit_claim': 'make_it_pass'}),
                              ('extrafield', {'command': 'cat secret'}),
                              ('nestedclaim', {'edit_claim': {'kind': 'keep_ast'}})]:
            c, _, _, output, _ = self.run_mock(name, 'draft', self.arguments(**changes))
            self.assertEqual(c.calls, [])
            self.assertFalse((output/'sdk-submission.json').exists())
            audit = json.loads((output/'requests/input-audit-0001.json').read_text())
            self.assertEqual(audit['response_tool_validation']['status'], 'invalid_request')

    def test_finish_plain_text_and_absent_tool_calls_do_not_fabricate_artifacts(self):
        for name, args, options in [('finish', {'message': 'done'}, {'tool': 'finish'}),
                                   ('text', None, {'reason': 'stop'}), ('missing', None, {})]:
            c, _, ledger, output, _ = self.run_mock(name, 'draft', args, **options)
            self.assertEqual(c.calls, [])
            self.assertFalse((output/'sdk-submission.json').exists())
            self.assertEqual(ledger.summary()['request_count'], 1)

    def test_unknown_usage_and_second_request_refuse_further_transport(self):
        c, llm, ledger, output = self.bound('unknown', 'draft')
        response = self.response(self.arguments()); response.usage = None
        with patch('openhands.sdk.llm.llm.litellm_completion', return_value=response) as provider:
            run_commitment_session(c, llm, 'unknown', output, stage='draft')
            with self.assertRaises(BudgetExceeded):
                llm._transport_call(messages=[], max_tokens=4096)
        self.assertEqual(provider.call_count, 1)
        self.assertTrue(ledger.summary()['halted'])

    def test_existing_dispatch_record_and_controller_exceptions_halt_without_message_leak(self):
        c, llm, _, output = self.bound('existing', 'draft')
        (output/'sdk-submission.json').write_bytes(b'original')
        with patch('openhands.sdk.llm.llm.litellm_completion', return_value=self.response(self.arguments())):
            run_commitment_session(c, llm, 'existing', output, stage='draft')
        self.assertTrue(c.halted); self.assertEqual(c.calls, [])
        self.assertEqual((output/'sdk-submission.json').read_bytes(), b'original')
        c, llm, _, output = self.bound('storage', 'draft')
        with patch.object(c, 'submit', side_effect=OSError('PRIVATE EXCEPTION CONTENT')), \
             patch('openhands.sdk.llm.llm.litellm_completion', return_value=self.response(self.arguments())):
            run_commitment_session(c, llm, 'storage', output, stage='draft')
        self.assertTrue(c.halted)
        self.assertEqual(c.infrastructure_error_type, 'OSError')
        self.assertNotIn('PRIVATE EXCEPTION CONTENT', (output/'controller-error.json').read_text())

    def test_binding_wrong_stage_repeat_and_request_cap_refuse_before_network(self):
        c, llm, _, output = self.bound('bound', 'draft')
        for changes in [{'session_id': 'wrong', 'stage': 'draft'},
                        {'session_id': 'bound', 'stage': 'review'},
                        {'session_id': 'bound', 'stage': 'invalid'}]:
            with patch('openhands.sdk.llm.llm.litellm_completion') as provider:
                with self.assertRaises(ValueError):
                    run_commitment_session(c, llm, changes['session_id'], output, stage=changes['stage'])
            provider.assert_not_called()
        c, llm, _, output, _ = self.run_mock('repeat', 'draft', self.arguments())
        with patch('openhands.sdk.llm.llm.litellm_completion') as provider:
            with self.assertRaises(FileExistsError):
                run_commitment_session(c, llm, 'repeat', output, stage='draft')
        provider.assert_not_called()
        c, llm, ledger, output = self.bound('cap', 'draft', max_input_bytes=32)
        with patch('openhands.sdk.llm.llm.litellm_completion') as provider:
            run_commitment_session(c, llm, 'cap', output, stage='draft')
        provider.assert_not_called(); self.assertEqual(ledger.summary()['request_count'], 0)

    def test_controller_output_directory_mismatch_is_rejected(self):
        c, llm, _, output = self.bound('location', 'draft')
        c.output_dir = self.root/'elsewhere'
        with patch('openhands.sdk.llm.llm.litellm_completion') as provider:
            with self.assertRaises(ValueError):
                run_commitment_session(c, llm, 'location', output, stage='draft')
        provider.assert_not_called()


if __name__ == '__main__':
    unittest.main()
