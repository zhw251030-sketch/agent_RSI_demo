"""Offline replay of the stopped first policy response; never a real retry.

The original files and frozen controller are read unchanged. The full response
is reconstructed at the SDK provider boundary, including its recorded usage.
Those copied usage values describe a synthetic replay ledger, not new model
consumption. There is no credentials access, external call or task execution.
"""
import argparse
import hashlib
import json
import logging
from pathlib import Path
from unittest.mock import patch

from extensions.basis_trial_v01 import sdk_controller
from rsi_eval.pilot_budget import BudgetLedger
from rsi_eval.revision_policy import VERSION,validate_policy
from rsi_eval.strategy_learning import canonical
from rsi_eval.strategy_pair_controller import write_once

ROOT=Path(__file__).resolve().parents[2]
DEFAULT_SOURCE='artifacts/basis-trial/2026-10-22/measured-v01/raw/sessions/update'


def file_record(root,path):
    path=Path(path)
    return {'path':path.relative_to(root).as_posix(),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}


def diagnose(root,source):
    root,source=Path(root).resolve(),Path(source)
    responses=list((source/'requests').glob('*.response.json'))
    requests=list((source/'requests').glob('*.request.json'))
    if len(responses)!=1 or len(requests)!=1:
        raise ValueError('Exactly one archived request and response required')
    response=json.loads(responses[0].read_bytes())
    arguments=response['choices'][0]['message']['tool_calls'][0]['function']['arguments']
    business=json.loads(arguments)
    policy=validate_policy({'version':VERSION,'rule_ids':business['rule_ids']})
    error=None
    try:
        sdk_controller.parse_policy_response(response)
    except ValueError as failure:
        error={'type':type(failure).__name__,'message':str(failure)}
    if error is None:
        raise ValueError('Expected the original frozen parser to reject this response')
    boundary={}
    for size in (2000,2001):
        try:
            sdk_controller.validate_policy_business({'rule_ids':policy['rule_ids'],'explanation':'x'*size})
            boundary[str(size)]='accepted'
        except ValueError:
            boundary[str(size)]='rejected'
    return {'version':'basis-trial-stopped-response-diagnosis-v0.1',
        'request':file_record(root,requests[0]),'response':file_record(root,responses[0]),
        'packet':file_record(root,source/'packet.json'),
        'business_keys':sorted(business),'valid_policy':policy,
        'raw_arguments_characters':len(arguments),'raw_arguments_utf8_bytes':len(arguments.encode('utf-8')),
        'explanation_characters':len(business['explanation']),
        'explanation_utf8_bytes':len(business['explanation'].encode('utf-8')),
        'maximum_explanation_characters':2000,'excess_characters':len(business['explanation'])-2000,
        'parser_error':error,'synthetic_length_boundary_check':boundary,
        'original_recorded_usage':response['usage'],'new_model_requests':0,
        'candidate_executions':0,'original_files_modified':False}


def replay(root,source,output):
    root,source,output=Path(root).resolve(),Path(source),Path(output)
    diagnosis=diagnose(root,source)
    output.mkdir(parents=True,exist_ok=False)
    write_once(output/'diagnosis.json',diagnosis)
    original=json.loads((root/diagnosis['response']['path']).read_bytes())
    packet=json.loads((source/'packet.json').read_bytes())
    ledger=BudgetLedger(output/'synthetic-ledger.json',max_requests=13,max_requests_per_session=1,
        max_output_tokens=8192,max_input_bytes=98304,max_reserved_tokens=1500000,
        max_cost_cny=4,session_ids=['update'])
    callbacks=[]
    class ReplayProvider:
        calls=0
        def __call__(self,**kwargs):
            from litellm.types.utils import ModelResponse
            self.calls+=1
            if self.calls!=1: raise RuntimeError('No second replay dispatch')
            return ModelResponse(id=original['response_id'],model='MiniMax-M3',
                choices=original['choices'],usage=original['usage'])
    provider=ReplayProvider()
    def receive(value):
        callbacks.append(value)
        return {'status':'unexpected_callback'}
    old_logging=logging.root.manager.disable
    try:
        logging.disable(logging.CRITICAL)
        with patch('openhands.sdk.llm.llm.litellm_completion',provider):
            receipt=sdk_controller.run_session(root,output/'session','update',packet,ledger,
                sdk_controller.public_settings() | {'api_key':'offline-replay-not-a-credential'},
                stage='update',accept_callback=receive)
    finally:
        logging.disable(old_logging)
    saved=json.loads((root/receipt['response']['path']).read_bytes())
    original_args=original['choices'][0]['message']['tool_calls'][0]['function']['arguments']
    replay_args=saved['choices'][0]['message']['tool_calls'][0]['function']['arguments']
    request_unchanged=(root/receipt['request']['path']).read_bytes()==(root/diagnosis['request']['path']).read_bytes()
    budget=ledger.summary()
    report={'version':'basis-trial-frozen-response-sdk-replay-v0.1','kind':'engineering_simulation_only',
        'status':'passed' if (receipt['status']=='error' and provider.calls==1 and not callbacks
            and receipt['business'] is None and receipt['policy'] is None
            and request_unchanged and replay_args==original_args
            and budget['usage_unknown_count']==0 and budget['request_count']==1) else 'failed',
        'source_diagnosis':diagnosis,'sdk_result':receipt,
        'actual_sdk_fake_provider_dispatches':provider.calls,'host_acceptance_callbacks':len(callbacks),
        'original_arguments_unchanged':replay_args==original_args,
        'original_request_bytes_unchanged':request_unchanged,
        'replayed_usage':budget,'usage_scope':'Copied original usage for offline contract replay; excluded from research ledger.',
        'research_requests':0,'new_tokens':0,'new_model_cost_cny':0,'candidate_executions':0,
        'smallest_successor_option':'In a new frozen version remove archive-only explanation from policy action, retaining exactly four ordered rule IDs; never repair or accept this stopped response retroactively.'}
    if diagnose(root,source)!=diagnosis:
        raise ValueError('Original inputs changed during replay')
    write_once(output/'report.json',report)
    return report


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--source',default=DEFAULT_SOURCE)
    parser.add_argument('--output')
    args=parser.parse_args()
    report=(replay(ROOT,ROOT/args.source,ROOT/args.output) if args.output else diagnose(ROOT,ROOT/args.source))
    print(json.dumps(report,ensure_ascii=False,allow_nan=False))


if __name__=='__main__':main()
