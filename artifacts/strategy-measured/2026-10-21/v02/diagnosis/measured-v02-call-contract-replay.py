"""Read-only diagnosis; synthetic SDK replays never alter the stopped real run."""
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
from unittest.mock import patch

os.environ['OPENHANDS_SUPPRESS_BANNER'] = '1'
os.environ['LITELLM_LOCAL_MODEL_COST_MAP'] = 'True'
parser = argparse.ArgumentParser()
parser.add_argument('--root', type=Path, default=Path.cwd())
args = parser.parse_args()
root = args.root.resolve()
sys.path.insert(0, str(root))
run = root/'runs/strategy-pair/measured-v02'
output = root/'tmp/measured-v02-call-contract-replay.json'
traces = root/'tmp/measured-v02-call-contract-traces'
assert not output.exists() and not traces.exists(), 'No replay overwrite'

def sha(raw):
    return hashlib.sha256(raw).hexdigest()

def inventory(directory):
    return {p.relative_to(root).as_posix(): sha(p.read_bytes())
            for p in sorted(directory.rglob('*')) if p.is_file()}

before = inventory(run)
frozen = json.loads((run/'preparation/runtime-freeze.json').read_bytes())['files']
runtime_before = {p: sha((root/p).read_bytes()) for p in frozen}
assert runtime_before == frozen
slot = 'r1-selection-S-select-1-updated'
session = run/'experiment/sessions'/slot
request_bytes = (session/'requests/request-0007.request.json').read_bytes()
response_bytes = (session/'requests/request-0007.response.json').read_bytes()
request, response = json.loads(request_bytes), json.loads(response_bytes)
packet = json.loads((session/'requests/packet.json').read_bytes())
settings = json.loads((run/'preparation/settings.json').read_bytes())['effective']
calls = response['choices'][0]['message']['tool_calls']
assert [call['function']['name'] for call in calls] == ['submit_candidate', 'finish']
original_business_raw = calls[0]['function']['arguments']

with patch.object(socket.socket, 'connect', side_effect=AssertionError('Offline replay forbids sockets')), \
     patch('socket.create_connection', side_effect=AssertionError('Offline replay forbids sockets')):
    from litellm.types.utils import ModelResponse
    from openhands.sdk import Agent
    from openhands.sdk.agent import agent as sdk_agent_module
    from openhands.sdk.agent import base as sdk_base_module
    from rsi_eval import strategy_pair_agent as adapter
    from rsi_eval.pilot_agent import ControlledPilotConversation
    from rsi_eval.pilot_budget import BudgetLedger
    from rsi_eval.strategy_pair_controller import StrategyPairController
    from rsi_eval.strategy_learning import canonical

    logging.disable(logging.CRITICAL)
    def bound(directory):
        controller = StrategyPairController(root, packet, slot, directory/'session')
        ledger = BudgetLedger(directory/'synthetic-ledger.json', session_ids=[slot], max_requests=1,
            max_requests_per_session=1, max_output_tokens=8192, max_input_bytes=98304,
            max_reserved_tokens=200000, max_cost_cny=2)
        llm = adapter.make_llm(settings | {'api_key': 'offline-placeholder'}, controller, ledger)
        return controller, ledger, llm

    replays = []
    for label, remove_finish, expected in (
            ('original_two_calls', False, 'error'), ('counterfactual_finish_omitted', True, 'accepted')):
        directory = traces/label
        controller, ledger, llm = bound(directory)
        choices = copy.deepcopy(response['choices'])
        if remove_finish:
            choices[0]['message']['tool_calls'] = choices[0]['message']['tool_calls'][:1]
        assert choices[0]['message']['tool_calls'][0]['function']['arguments'] == original_business_raw
        fixture = ModelResponse(id=response['response_id'], model=request['model'],
            choices=choices, usage=response['usage'])
        with patch('openhands.sdk.llm.llm.litellm_completion', return_value=fixture) as fake:
            result = adapter.run_session(controller, llm, slot, controller.output_dir)
        assert fake.call_count == 1 and result['status'] == expected, result
        sent = root/result['request']['path']
        assert sent.read_bytes() == request_bytes
        assert controller.summary()['candidate_executions'] == controller.summary()['task_evaluations'] == 0
        if remove_finish:
            business = controller.validate_arguments(original_business_raw)
            assert (controller.output_dir/'source.py').read_bytes() == business['source'].encode('utf-8')
        else:
            assert not (controller.output_dir/'source.py').exists()
            assert result['sdk_error_codes'] == ['PilotResponseContractError']
        replays.append(dict(kind=label, status=result['status'], fake_provider_calls=fake.call_count,
            actual_request_file_bytes_equal_original=True, request_sha256=sha(sent.read_bytes()),
            candidate_executions=0, task_measurements=0, result=result,
            synthetic_usage_copied_from_saved_response=True,
            scope='Isolated synthetic diagnostic. No acceptance or budget entry in the measured experiment.'))

    # Characterize the installed SDK option, without editing the strategy adapter
    # or calling a provider. This is only a hypothetical one-tool request capture.
    directory = traces/'hypothetical_without_finish_capture'
    controller, ledger, llm = bound(directory)
    llm._capture_only = True
    model = Agent(llm=llm, tools=[adapter._tool(controller,llm)], include_default_tools=[],
        system_prompt=adapter.ACTOR_SYSTEM, agent_context=None, mcp_config={}, condenser=None,
        critic=None, tool_concurrency_limit=1)
    conv = ControlledPilotConversation(model, workspace=directory/'workspace', persistence_dir=None,
        callbacks=[], max_iteration_per_run=1, stuck_detection=False, visualizer=None,
        plugins=[], delete_on_close=False, profile_store_dir=directory/'empty-profiles')
    try:
        with patch('openhands.sdk.agent.base.has_vision_profile_available', return_value=False):
            conv.send_message(controller.task_prompt())
        tools = sorted(conv.agent.tools_map)
        assert tools == ['submit_candidate']
        with patch('openhands.sdk.llm.llm.litellm_completion', side_effect=AssertionError('Capture cannot call provider')):
            try:
                conv.run()
            except Exception as error:
                cause = error
                while cause is not None and not isinstance(cause, adapter._TemplateCaptured):
                    cause = cause.__cause__
                assert cause is not None
    finally:
        conv.close()
    assert ledger.summary()['request_count'] == 0
    captured = llm._captured_payload
    assert [tool['function']['name'] for tool in captured['tools']] == ['submit_candidate']
    directory.mkdir(parents=True, exist_ok=True)
    (directory/'hypothetical-request.json').write_bytes(canonical(captured)+b'\n')
    sdk_sources = {}
    for label, module, needles in (
            ('agent_base', sdk_base_module, ('include_default_tools:', 'default_tool_names =')),
            ('agent_batch', sdk_agent_module, ('def _truncate_at_finish(', 'def finish(', 'def finalize('))):
        path = Path(module.__file__)
        lines = path.read_text().splitlines()
        excerpts = []
        for number, line in enumerate(lines):
            if any(needle in line for needle in needles):
                start, end = max(0, number-2), min(len(lines), number+35)
                excerpts.append(dict(start_line=start+1, end_line=end,
                    text='\n'.join(f'{i+1}: {lines[i]}' for i in range(start,end))))
        sdk_sources[label] = dict(path=str(path), sha256=sha(path.read_bytes()), excerpts=excerpts)
    (traces/'installed-sdk-evidence.json').write_text(json.dumps(sdk_sources, indent=2)+'\n')

after = inventory(run)
runtime_after = {p: sha((root/p).read_bytes()) for p in frozen}
assert before == after and runtime_before == runtime_after
report = dict(version='measured-v02-call-contract-diagnosis-v0.1',
    scope='Offline diagnosis only. No production fix, real requests, task evaluation or stopped-run recovery.',
    sdk_version=importlib.metadata.version('openhands-sdk'),
    request_sha256=sha(request_bytes), response_sha256=sha(response_bytes),
    original_response_tool_names=[call['function']['name'] for call in calls],
    original_response_business_arguments_sha256=sha(original_business_raw.encode('utf-8')),
    original_request_advertises_tools=[tool['function']['name'] for tool in request['tools']],
    replays=replays,
    omission_option=dict(installed_sdk_field_description=Agent.model_fields['include_default_tools'].description,
        explicit_empty_list_supported=True, observed_tools_without_defaults=tools,
        capture_request_count=ledger.summary()['request_count'],
        scope='Separate hypothetical SDK construction; production adapter/prompts/allowlist/audit unchanged.'),
    recommended_future_boundary='For single-step submissions, advertise only the business tool using include_default_tools=[]. Align system/task prompts, allowed tools, request binding and audits, and preserve strict one-business-call validation. Prototype and revalidate before any new run.',
    two_call_alternative='Allowing one business call followed by finish is possible only under a separately specified atomic boundary: validate both raw calls/identities/metadata before any acceptance, require exact order and no extra calls, and audit both SDK events. SDK truncates calls after finish, so generic len<=2 acceptance is unsafe. This alternative was not implemented or tested here.',
    causal_interpretation='The raw saved response is rejected by the existing one-tool-call limit before SDK action parsing. With only its trailing finish call omitted, unchanged candidate arguments are accepted by the unchanged strategy adapter. The current prompt requests one business submission but advertises finish and does not explicitly prohibit an accompanying finish call. This is distinct from the repaired optional-metadata mismatch.',
    original_run_file_count=len(before), original_run_hashes_unchanged=before == after,
    original_run_inventory=before, runtime_file_count=len(runtime_before), runtime_hashes_unchanged=runtime_before == runtime_after,
    real_requests=0, candidate_executions=0, task_measurements=0, research_policy_acceptances=0,
    synthetic_candidate_acceptances=1, trace_inventory=inventory(traces))
output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
print(json.dumps(dict(status='offline_causal_replay_passed', output=str(output),
    preserved_real_files=len(before), preserved_runtime_files=len(runtime_before),
    trace_files=len(report['trace_inventory']), replay_statuses=[r['status'] for r in replays],
    no_default_tools=tools, real_requests=0, task_measurements=0)))
