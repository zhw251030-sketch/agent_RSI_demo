"""Offline diagnosis plus two actual-SDK/fake-provider replay conversations.

No real provider call, benchmark task execution, or research policy acceptance.
The metadata-omitted control accepts one explicitly synthetic policy in tmp.
The original measured run and all tracked implementation files remain unchanged.
"""
import argparse
import copy
import hashlib
import importlib.metadata
import inspect
import json
import logging
import os
from pathlib import Path
import socket
import sys
import traceback
from unittest.mock import patch

os.environ['OPENHANDS_SUPPRESS_BANNER'] = '1'
os.environ['LITELLM_LOCAL_MODEL_COST_MAP'] = 'True'
parser = argparse.ArgumentParser()
parser.add_argument('--root', type=Path, default=Path.cwd())
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
root = args.root.resolve()
sys.path.insert(0, str(root))

def sha(raw):
    return hashlib.sha256(raw).hexdigest()

def inventory(path):
    return {p.relative_to(root).as_posix(): sha(p.read_bytes())
            for p in sorted(path.rglob('*')) if p.is_file()}

run = root/'runs/strategy-pair/measured-v01'
before = inventory(run)
output = args.output.resolve()
assert output.is_relative_to(root/'tmp'), 'Only ignored tmp output is allowed'
assert not output.exists(), 'Never overwrite an earlier replay'
session = run/'experiment/sessions/r1-update-updated'
request_path = session/'requests/request-0001.request.json'
response_path = session/'requests/request-0001.response.json'
request_bytes, response_bytes = request_path.read_bytes(), response_path.read_bytes()
request, response = json.loads(request_bytes), json.loads(response_bytes)
raw = response['choices'][0]['message']['tool_calls'][0]['function']['arguments']
tool = next(x['function'] for x in request['tools'] if x['function']['name'] == 'submit_policy')
schema = tool['parameters']

with patch.object(socket.socket, 'connect', side_effect=AssertionError('No network in failure replay')), \
     patch('socket.create_connection', side_effect=AssertionError('No network in failure replay')):
    from openhands.sdk import Action, Agent
    from openhands.sdk.agent.utils import parse_tool_call_arguments, normalize_tool_call, fix_malformed_tool_arguments
    from openhands.sdk.tool.tool import create_action_type_with_risk, _create_action_type_with_summary
    from litellm.types.utils import ModelResponse
    from rsi_eval.strategy_pair_agent import StrategyUpdateAction, make_llm, run_session
    from rsi_eval.strategy_pair_budget import StrategyPairBudgetLedger
    from rsi_eval.strategy_pair_controller import StrategyPairController, strict_json
    from rsi_eval.strategy_learning import canonical
    from rsi_eval.two_stage_agent import _SubmissionAction

    controller = StrategyPairController(root, json.loads((session/'requests/packet.json').read_bytes()),
        'r1-update-updated', root/'tmp/measured-failure-replay-never-written')
    assert not controller.output_dir.exists()
    parsed = strict_json(raw)
    raw_error = None
    try:
        controller.validate_arguments(raw)
    except ValueError as error:
        raw_error = {'type': type(error).__name__, 'message': str(error),
            'traceback': ''.join(traceback.format_exception(error))}
    assert raw_error and raw_error['message'] == 'Submission fields differ from contract'

    base_sdk_error = None
    try:
        StrategyUpdateAction.model_validate(parsed)
    except ValueError as error:
        base_sdk_error = {'type': type(error).__name__, 'message': str(error),
            'traceback': ''.join(traceback.format_exception(error))}
    assert base_sdk_error is not None
    enhanced = _create_action_type_with_summary(create_action_type_with_risk(StrategyUpdateAction))
    enhanced_schema = enhanced.model_json_schema()
    enhanced_error = None
    try:
        enhanced.model_validate(parsed)
    except ValueError as error:
        enhanced_error = {'type': type(error).__name__, 'message': str(error),
            'traceback': ''.join(traceback.format_exception(error))}
    # SDK uses the enhanced class for tool schema only. Its inherited finite-JSON
    # validator rejects a parsed SecurityRisk enum; actual execution extracts
    # metadata first and validates the unenhanced action instead.
    assert enhanced_error is not None
    sdk_arguments = parse_tool_call_arguments(raw)
    name, sdk_arguments = normalize_tool_call('submit_policy', sdk_arguments, ('submit_policy','finish'))
    sdk_arguments = fix_malformed_tool_arguments(sdk_arguments, StrategyUpdateAction)
    extracted_risk = Agent._extract_security_risk(None, sdk_arguments, False, None)
    extracted_summary = Agent._extract_summary(None, name, sdk_arguments, None)
    action = StrategyUpdateAction.model_validate(sdk_arguments)
    sdk_dump = action.model_dump(exclude={'kind'})
    sdk_original_dump = action.model_dump()
    sdk_business = controller.validate_arguments(sdk_dump)
    expected = {k:v for k,v in parsed.items() if k not in {'summary','security_risk'}}
    assert sdk_business == controller.validate_arguments(expected)

    # Counterfactual helper ONLY. It is not inserted into the production runner.
    # Raw duplicate detection precedes any projection. Unknown fields must not
    # disappear inside Pydantic's action model. SDK metadata is validated using
    # the actual SDK-enhanced schema. The sent schema has a dangling risk ref
    # because the legacy schema wrapper restores an unresolved original $ref.
    required = {'rule_1','rule_2','rule_3','rule_4'}
    allowed = required | {'explanation','summary','security_risk'}
    def projected_business(raw_input):
        value = strict_json(raw_input)
        if type(value) is not dict or not required <= set(value) <= allowed:
            raise ValueError('Unknown or missing tool fields')
        if 'summary' in value and value['summary'] is not None and type(value['summary']) is not str:
            raise ValueError('SDK summary must be a string or null')
        risk_schema = enhanced_schema['$defs']['SecurityRisk']
        if 'security_risk' in value and (type(value['security_risk']) is not str
                or value['security_risk'] not in risk_schema['enum']):
            raise ValueError('SDK risk must be one declared enum string')
        # SDK normalization must agree with the strict controller projection.
        business = controller.validate_arguments({k:v for k,v in value.items()
            if k not in {'summary','security_risk'}})
        normalized = copy.deepcopy(value)
        Agent._extract_security_risk(None, normalized, False, None)
        Agent._extract_summary(None, 'submit_policy', normalized, None)
        projected = StrategyUpdateAction.model_validate(normalized).model_dump(exclude={'kind'})
        if controller.validate_arguments(projected) != business:
            raise ValueError('SDK normalization changed business values')
        return business

    def encode(value):
        return json.dumps(value, ensure_ascii=False, separators=(',', ':'))
    cases = [('actual_valid_sdk_metadata', raw, True),
             ('business_without_optional_sdk_metadata', encode(expected), True),
             ('nullable_sdk_summary', encode(parsed | {'summary': None}), True)]
    for name, updates in [
        ('unknown_extra', {'unexpected': 'must reject'}),
        ('internal_discriminator', {'kind': 'StrategyUpdateAction'}),
        ('malformed_risk_enum', {'security_risk': 'NOT_A_VALID_RISK'}),
        ('malformed_risk_type', {'security_risk': 1}),
        ('malformed_summary_type', {'summary': ['text']}),
        ('invalid_rule_enum', {'rule_1': 'R99'}),
        ('invalid_rule_type', {'rule_1': True}),
        ('repeated_rule', {'rule_2': 'R01'}),
        ('oversize_explanation_utf8', {'explanation': '\u4e2d'*2000}),
    ]:
        cases.append((name, encode(parsed | updates), False))
    no_rule = dict(parsed)
    del no_rule['rule_4']
    cases.extend([
        ('missing_rule', encode(no_rule), False),
        ('duplicate_business_key', raw[:-1]+',"rule_1":"R02"}', False),
        ('duplicate_metadata_key', raw[:-1]+',"security_risk":"LOW"}', False),
        ('nonfinite_business', raw[:-1]+',"unexpected":NaN}', False),
    ])
    tests = []
    for name, value, expect in cases:
        try:
            business = projected_business(value)
            actual, error_type = True, None
        except Exception as error:
            actual, error_type = False, type(error).__name__
        tests.append({'case': name, 'expected_accept': expect,
            'actual_accept': actual, 'error_type': error_type, 'passed': actual == expect})
    assert all(row['passed'] for row in tests)

    replay_root = root/'tmp/measured-failure-sdk-artifacts'
    assert not replay_root.exists(), 'Never overwrite a replay directory'
    public_settings = json.loads((run/'preparation/settings.json').read_bytes())['effective']
    slots = [x['id'] for x in json.loads((run/'experiment/allocation.json').read_bytes())['slots']]
    sdk_replays = []
    logging.disable(logging.CRITICAL)
    for label, provider_args, expected_status in [
            ('original_response', raw, 'error'),
            ('counterfactual_metadata_omitted', encode(expected), 'accepted')]:
        replay_dir = replay_root/label
        replay_controller = StrategyPairController(root, controller.task_packet(), 'r1-update-updated', replay_dir/'session')
        ledger = StrategyPairBudgetLedger(replay_dir/'synthetic-ledger.json', slots)
        llm = make_llm(public_settings | {'api_key':'offline-placeholder'}, replay_controller, ledger)
        fixture_choices = copy.deepcopy(response['choices'])
        fixture_choices[0]['message']['tool_calls'][0]['function']['arguments'] = provider_args
        fixture = ModelResponse(id=response['response_id'], model=request['model'],
            choices=fixture_choices, usage=response['usage'])
        with patch('openhands.sdk.llm.llm.litellm_completion', return_value=fixture) as fake:
            result = run_session(replay_controller, llm, 'r1-update-updated', replay_controller.output_dir)
        assert result['status'] == expected_status, result
        replay_request = root/result['request']['path']
        same_request_bytes = replay_request.read_bytes() == request_bytes
        assert same_request_bytes
        assert fake.call_count == 1
        assert replay_controller.summary()['candidate_executions'] == 0
        assert replay_controller.summary()['task_evaluations'] == 0
        sdk_replays.append({'kind': label, 'status': result['status'], 'fake_provider_calls': fake.call_count,
            'same_original_request_file_bytes': same_request_bytes,
            'request_sha256': sha(replay_request.read_bytes()), 'result': result,
            'synthetic_usage_copied_from_original_for_transport_replay_only': True,
            'scope': 'Synthetic SDK replay, excluded from research budget and all policy/measurement results.'})
    after = inventory(run)
    assert before == after
    assert not controller.output_dir.exists()
    assert controller.status == 'pending' and controller.policy is None
    report = {
        'version': 'measured-failure-sdk-replay-v0.1',
        'scope': 'Offline diagnostic only; hypothetical projection is not a production fix or accepted policy.',
        'sdk_version': importlib.metadata.version('openhands-sdk'),
        'python_version': sys.version,
        'source_files': {str(p.relative_to(root)): sha(p.read_bytes()) for p in [
            root/'rsi_eval/strategy_pair_agent.py', root/'rsi_eval/strategy_pair_controller.py',
            root/'rsi_eval/two_stage_agent.py']},
        'request': {'path': str(request_path.relative_to(root)), 'raw_file_sha256': sha(request_bytes),
            'raw_file_bytes': len(request_bytes), 'canonical_payload_sha256': sha(canonical(request)),
            'canonical_payload_bytes': len(canonical(request))},
        'response': {'path': str(response_path.relative_to(root)), 'raw_file_sha256': sha(response_bytes),
            'raw_file_bytes': len(response_bytes), 'tool_argument_sha256': sha(raw.encode('utf-8')),
            'argument_keys': sorted(parsed)},
        'sent_submit_policy_schema': schema,
        'action_model_fields': sorted(StrategyUpdateAction.model_fields),
        'action_model_config': dict(StrategyUpdateAction.model_config),
        'raw_controller_rejection': raw_error,
        'base_action_model_validate_raw_rejection': base_sdk_error,
        'schema_only_enhanced_model_validate_raw_rejection': enhanced_error,
        'sdk_enhanced_model_json_schema': enhanced_schema,
        'sent_security_risk_reference_has_no_definition': '$ref' in schema['properties']['security_risk'] and '$defs' not in schema,
        'sdk_extracted_metadata': {'security_risk': str(extracted_risk), 'summary': extracted_summary},
        'base_action_model_validate_after_sdk_extraction_succeeded': True,
        'actual_sdk_model_dump': sdk_original_dump,
        'actual_sdk_business_dump': sdk_dump,
        'sdk_normalized_business_validates': True,
        'sdk_replays': sdk_replays,
        'hypothetical_projection_cases': tests,
        'hypothetical_projection_test_count': len(tests),
        'all_hypothetical_projection_cases_passed': True,
        'original_run_file_count': len(before),
        'original_run_hashes_unchanged': before == after,
        'original_run_inventory': before,
        'controller': controller.summary(),
        'actual_requests': 0, 'candidate_executions': 0, 'task_measurements': 0,
        'research_policy_acceptances': 0,
        'counterfactual_synthetic_policy_acceptances': 1,
        'interpretation': 'The advertised SDK tool schema contains summary/security_risk. The strict raw business gate rejects those metadata fields before SDK normalization. Actual Agent extraction removes metadata and the base action validates/dumps business. The enhanced action class is only used to construct a schema: directly validating it also fails because its inherited finite-JSON validator rejects SecurityRisk enum values. Exact original response replay fails under unchanged code; a response with only metadata omitted is synthetically accepted. This identifies an interface mismatch, not a strategy benefit. Proposed future projection must validate metadata/unknown fields before parsing; SDK itself ignores malformed risk when no security analyzer is configured.',
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
print(json.dumps({'status': 'offline_reproduction_passed', 'tests': len(tests),
    'unchanged_files': len(before), 'request_sha256': sha(request_bytes),
    'response_sha256': sha(response_bytes), 'metadata_properties': {k:schema['properties'][k] for k in ('summary','security_risk')},
    'action_fields': sorted(StrategyUpdateAction.model_fields), 'output': str(output)}, ensure_ascii=False))
