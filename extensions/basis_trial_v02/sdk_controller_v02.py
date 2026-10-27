"""One actual SDK Conversation step for a bounded basis-strategy trial.

Only the LiteLLM provider callable is substituted in offline rehearsals. The SDK
serializes the request and dispatches the action. No task is executed here.
The parent runner owns packet provenance, stage order and candidate evaluation.
"""
import copy
import hashlib
import importlib.metadata
import json
from pathlib import Path
import re
from typing import ClassVar
from unittest.mock import patch

from extensions.symbolic_basis_v02.sdk_adapter import BasisSubmissionHandler, _decode_json
from rsi_eval.revision_policy import VERSION as POLICY_VERSION, validate_policy
from rsi_eval.strategy_learning import canonical
from rsi_eval.strategy_pair_controller import reference, write_once
from rsi_eval.strategy_pair_transport import safe_settings

VERSION = 'basis-trial-sdk-v02-symbolic-contract'
UPDATE_SYSTEM = ('Select one external revision policy from the supplied historical evidence and fixed rule catalog. '
    'Return exactly one submit_policy tool call with four distinct ordered rule_ids and an explanation. '
    'Only rule IDs will transfer to actors. Explanations are unverified archive-only text. '
    'Do not call finish or any other tool. The host ends this single step. No task execution or additional model request is available.')
ACTOR_SYSTEM = ('Revise the supplied symbolic basis once using its feedback, host contract and repair_policy. '
    'Return exactly one submit_basis tool call with feature_ids and explanation. Follow the permitted structural edit exactly. '
    'Only this business tool is available; do not call finish or another tool. The host fits coefficients and evaluates separately. '
    'Your explanation is unverified archive-only text. No filesystem, network, task execution or additional model request is available.')


def public_settings():
    """Existing public provider settings; callers supply authentication in memory."""
    return dict(model='anthropic/MiniMax-M3', base_url='https://api.minimax.cn/anthropic',
        temperature=1.0, max_output_tokens=8192, timeout=180, num_retries=0,
        caching_prompt=False, reasoning_effort='none',
        litellm_extra_body={'thinking': {'type': 'disabled'}})


def normalize_envelope(response, tool):
    """Validate the LiteLLM envelope and project only its optional index=0.

    MiniMax's already-decoded LiteLLM tool-call envelope includes index:0.
    The prior frozen basis adapter accepts a narrower envelope. This explicit
    compatibility projection never changes function arguments; the original
    response is retained by BoundedPilotLLM before this function is invoked.
    """
    value = _decode_json(response) if type(response) is str else copy.deepcopy(response)
    if type(value) is not dict or tool not in ('submit_basis', 'submit_policy'):
        raise ValueError('Expected a known business response')
    choices = value.get('choices')
    if type(choices) is not list or len(choices) != 1 or type(choices[0]) is not dict:
        raise ValueError('Exactly one provider choice is required')
    choice = choices[0]
    message = choice.get('message')
    if choice.get('finish_reason') != 'tool_calls' or type(message) is not dict or message.get('role') != 'assistant':
        raise ValueError('Expected assistant tool-call completion')
    calls = message.get('tool_calls')
    if type(calls) is not list or len(calls) != 1 or type(calls[0]) is not dict:
        raise ValueError('Exactly one tool call is required')
    call = calls[0]
    required = {'id', 'type', 'function'}
    if not required <= set(call) <= required | {'index'}:
        raise ValueError('Unexpected tool envelope fields')
    if 'index' in call and (type(call['index']) is not int or call['index'] != 0):
        raise ValueError('The sole tool call must have exact integer index zero')
    function = call.get('function')
    if (call.get('type') != 'function' or type(call.get('id')) is not str or not call['id']
            or type(function) is not dict or set(function) != {'name', 'arguments'}
            or function['name'] != tool or type(function['arguments']) is not str):
        raise ValueError('Unexpected business function envelope')
    call.pop('index', None)
    return value


def validate_policy_business(value):
    if type(value) is not dict or set(value) != {'rule_ids', 'explanation'}:
        raise ValueError('Policy submission requires exactly rule_ids and explanation')
    validate_policy({'version': POLICY_VERSION, 'rule_ids': value['rule_ids']})
    text = value['explanation']
    if type(text) is not str or not text.strip() or len(text) > 2000:
        raise ValueError('Nonblank bounded policy explanation required')
    canonical(value)
    return copy.deepcopy(value)


def parse_policy_response(response):
    value = normalize_envelope(response, 'submit_policy')
    return validate_policy_business(_decode_json(value['choices'][0]['message']['tool_calls'][0]['function']['arguments']))


class FakeProvider:
    """Artificial replies, explicit synthetic usage, and no network access.

    Use only under patch('openhands.sdk.llm.llm.litellm_completion', provider).
    Each reply has tool/arguments; optional usage may be None to test failures.
    A reply containing raise supplies an exception for a once-only failure.
    """
    synthetic_only = True

    def __init__(self, responses):
        self.responses = copy.deepcopy(responses)
        self.calls = 0

    def __call__(self, **kwargs):
        from litellm.types.utils import ModelResponse
        if self.calls >= len(self.responses):
            raise RuntimeError('Synthetic provider exhausted; no fallback')
        item = self.responses[self.calls]
        self.calls += 1
        if 'raise' in item:
            raise item['raise']
        args = item['arguments']
        raw = args if type(args) is str else json.dumps(args, ensure_ascii=False, allow_nan=False)
        response = ModelResponse(id=f'synthetic-basis-{self.calls}', model='MiniMax-M3',
            choices=[dict(finish_reason='tool_calls',message=dict(role='assistant',content='Synthetic SDK rehearsal only.',
                tool_calls=[dict(index=0,id=f'synthetic-call-{self.calls}',type='function',
                                 function=dict(name=item['tool'],arguments=raw))]))],
            usage=item.get('usage',dict(prompt_tokens=100,completion_tokens=20,total_tokens=120)))
        if 'usage' in item and item['usage'] is None:
            response.usage = None
        return response


def _validate_inputs(root, output_dir, session_id, packet, ledger, settings, stage, spec, callback):
    root, output = Path(root).resolve(), Path(output_dir).absolute()
    output.relative_to(root)
    if any(p.is_symlink() or (hasattr(p,'is_junction') and p.is_junction()) for p in (output,*output.parents)):
        raise ValueError('Symlinked session output')
    if output.exists():
        raise FileExistsError('SDK session output must be new; no resume')
    if type(session_id) is not str or re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,63}',session_id) is None:
        raise ValueError('Invalid session identifier')
    if type(packet) is not dict or len(canonical(packet)) > 81920:
        raise ValueError('Expected a finite packet of at most 81920 bytes')
    if stage not in ('actor','update') or (stage == 'update' and spec is not None):
        raise ValueError('Known stage and host-owned actor specification required')
    if stage == 'actor':
        BasisSubmissionHandler(spec,lambda _: {})
    if callback is not None and not callable(callback):
        raise ValueError('Host callback must be callable')
    safe_settings(settings)
    limits = ledger.config
    if (limits['max_requests'] > 13 or limits['max_requests_per_session'] != 1
            or limits['max_input_bytes'] > 98304 or limits['max_output_tokens'] != 8192
            or limits['max_cost_cny'] > 4 or session_id not in ledger.session_ids):
        raise ValueError('One bounded request per trial slot, at most 13 requests and 4 CNY')
    summary=ledger.summary()
    if summary['session_counts'].get(session_id) or summary['halted'] or summary['reserved_count'] or summary['usage_unknown_count']:
        raise ValueError('Session was used or trial ledger is not settled')
    if importlib.metadata.version('openhands-sdk') != '1.55.1':
        raise RuntimeError('This controller requires OpenHands SDK 1.55.1')
    return root,output,json.loads(canonical(packet))


def _execute(root, output_dir, session_id, packet, ledger, settings, *, stage,
             spec=None, accept_callback=None, pre_request_guard=None, capture=False):
    from openhands.sdk import Action, Agent, Observation, Tool, ToolDefinition
    from openhands.sdk.tool import ToolExecutor, register_tool
    from pydantic import ConfigDict, Field, PrivateAttr, StrictStr, model_validator
    from extensions.symbolic_basis_v02.sdk_adapter import build_tool_definition
    from rsi_eval.pilot_agent import BoundedPilotLLM, ControlledPilotConversation, PilotResponseContractError, safe_error_metadata
    from rsi_eval.state_packet import replace_messages,wire_payload
    from rsi_eval.strategy_pair_transport import observed_strategy_transport

    root,output,packet = _validate_inputs(root,output_dir,session_id,packet,ledger,settings,stage,spec,accept_callback)
    if pre_request_guard is not None and not callable(pre_request_guard):
        raise ValueError('Pre-request guard must be callable')
    output.mkdir(parents=True,exist_ok=False)
    tool_name='submit_basis' if stage=='actor' else 'submit_policy'
    state={'business':None,'compiled':None,'policy':None,'accepted':False,'attempted':False,
           'request_id':None,'raw_response':None,'transport_error':None,'captured':None}
    errors=[]

    def accept(compiled_or_policy):
        if state['attempted']:
            raise ValueError('One host acceptance attempt per slot')
        state['attempted']=True
        budget=ledger.summary()
        if (budget['halted'] or budget['reserved_count'] or budget['usage_unknown_count']
                or budget['session_counts'].get(session_id)!=1 or state['transport_error'] is not None):
            raise ValueError('Known settled usage required before acceptance')
        request=reference(root,output/'requests'/(state['request_id']+'.request.json'))
        response=reference(root,output/'requests'/(state['request_id']+'.response.json'))
        raw=state['raw_response']
        call=raw['choices'][0]['message']['tool_calls'][0]
        write_once(output/'sdk-submission.json',dict(version=VERSION,stage=stage,session_id=session_id,
            request_id=state['request_id'],request=request,response=response,response_id=raw['response_id'],
            tool=tool_name,tool_call_id=call['id'],business=state['business']))
        write_once(output/'acceptance-attempt.json',dict(version=VERSION,request=request,response=response,
            business_sha256=hashlib.sha256(canonical(state['business'])).hexdigest()))
        if stage=='actor':
            write_once(output/'source.py',compiled_or_policy['source'].encode('utf-8'),raw=True)
            write_once(output/'compiled.json',compiled_or_policy)
        else:
            write_once(output/'policy.json',compiled_or_policy)
        if accept_callback is not None:
            feedback=accept_callback(copy.deepcopy(compiled_or_policy))
            if type(feedback) is not dict:
                raise ValueError('Host callback must return a JSON object')
            canonical(feedback)
        else:
            feedback={'status':'accepted','candidate_executions':0}
        write_once(output/'submission.json',dict(version=VERSION,status='accepted',stage=stage,
            request_id=state['request_id'],business=state['business'],candidate_executions=0))
        state['compiled' if stage=='actor' else 'policy']=copy.deepcopy(compiled_or_policy)
        state['accepted']=True
        return feedback

    handler=BasisSubmissionHandler(spec,accept) if stage=='actor' else None

    class CaptureReached(RuntimeError):
        pass

    class TrialLLM(BoundedPilotLLM):
        _pilot_allowed_tools: ClassVar[frozenset[str]]=frozenset({tool_name})
        _attempted: bool=PrivateAttr(default=False)

        def _pilot_transport_started(self,request_id):
            state['request_id']=request_id

        def _transport_call(self,*,messages,enable_streaming=False,on_token=None,**kwargs):
            if self._attempted:
                raise PilotResponseContractError('One request; no retry or repair')
            self._attempted=True
            replacement=replace_messages(messages,packet)
            payload=wire_payload(self.model,replacement,kwargs.get('tools'),kwargs.get('tool_choice'),
                kwargs.get('max_tokens',kwargs.get('max_completion_tokens',self.max_output_tokens)))
            advertised=payload.get('tools')
            if (type(advertised) is not list or len(advertised)!=1
                    or advertised[0].get('function',{}).get('name')!=tool_name or payload.get('tool_choice') is not None):
                raise ValueError('Only the single business tool may be advertised')
            fields=set(advertised[0]['function']['parameters']['properties'])
            if fields != ({'feature_ids','explanation'} if stage=='actor' else {'rule_ids','explanation'}):
                raise ValueError('SDK advertised unapproved action fields')
            if capture:
                state['captured']=copy.deepcopy(payload)
                raise CaptureReached('SDK serialization reached without provider or budget')
            write_once(output/'packet.json',packet)
            write_once(output/'input-audit.json',dict(version=VERSION,input_bytes=len(canonical(payload)),
                payload_sha256=hashlib.sha256(canonical(payload)).hexdigest(),max_input_bytes=ledger.config['max_input_bytes']))
            try:
                if pre_request_guard is not None:
                    pre_request_guard(copy.deepcopy(payload))
                response=super()._transport_call(messages=replacement,enable_streaming=enable_streaming,on_token=on_token,**kwargs)
                budget=ledger.summary()
                if budget['halted'] or budget['reserved_count'] or budget['usage_unknown_count']:
                    raise PilotResponseContractError('Known settled usage required')
                raw=json.loads((output/'requests'/(state['request_id']+'.response.json')).read_bytes())
                if type(raw.get('response_id')) is not str or not raw['response_id']:
                    raise ValueError('Response identity is required')
                state['raw_response']=raw
                normalized=normalize_envelope(raw,tool_name)
                state['business']=(handler.prepare_response(normalized) if stage=='actor' else parse_policy_response(normalized))
                return response
            except Exception as error:
                state['transport_error']=type(error).__name__
                raise

    model_settings=dict(settings)
    required=dict(api_mode='chat',stream=False,native_tool_calling=True,force_string_serializer=False,
        fallback_strategy=None,log_completions=False)
    for name,value in required.items():
        if name in model_settings and model_settings[name]!=value:
            raise ValueError('Unexpected model setting: '+name)
        model_settings[name]=value
    llm=TrialLLM(**model_settings).bind_pilot(ledger,session_id,output/'requests')

    if stage=='actor':
        definition=build_tool_definition(handler)
    else:
        schema={'type':'object','properties':{
            'rule_ids':{'type':'array','items':{'type':'string','enum':['R01','R02','R03','R04','R05','R06','R07','R08']},
                        'minItems':4,'maxItems':4,'uniqueItems':True},
            'explanation':{'type':'string','minLength':1,'maxLength':2000}},
            'required':['rule_ids','explanation'],'additionalProperties':False}

        class PolicyAction(Action):
            model_config=ConfigDict(extra='forbid',strict=True)
            rule_ids:list[StrictStr]=Field(min_length=4,max_length=4)
            explanation:StrictStr=Field(min_length=1,max_length=2000)
            @classmethod
            def to_mcp_schema(cls):
                return copy.deepcopy(schema)
            @model_validator(mode='after')
            def strict(self):
                validate_policy_business(self.model_dump(exclude={'kind'}))
                return self

        class PolicyObservation(Observation):
            feedback:dict=Field(default_factory=dict)

        class PolicyExecutor(ToolExecutor):
            def __call__(self,action,conversation=None):
                business=validate_policy_business(action.model_dump(exclude={'kind'}))
                if business!=state['business']:
                    raise ValueError('SDK business differs from original raw arguments')
                feedback=accept({'version':POLICY_VERSION,'rule_ids':business['rule_ids']})
                return PolicyObservation.from_text(json.dumps(feedback),feedback=feedback)

        class PolicyTool(ToolDefinition):
            name:ClassVar[str]='submit_policy'
            @classmethod
            def create(cls,conv_state=None,**params):
                if params:
                    raise ValueError('No policy tool initialization parameters')
                return [cls(description='Submit one ordered fixed-library policy; no execution.',
                    action_type=PolicyAction,observation_type=PolicyObservation,executor=PolicyExecutor())]

        definition=PolicyTool.create()[0]

    class BoundTool(ToolDefinition):
        name:ClassVar[str]=tool_name
        @classmethod
        def create(cls,conv_state=None,**params):
            if params:
                raise ValueError('No tool initialization parameters')
            return [definition]

    registry='BasisTrial_'+hashlib.sha256(str(output).encode()).hexdigest()[:16]
    register_tool(registry,BoundTool)
    agent=Agent(llm=llm,tools=[Tool(name=registry)],include_default_tools=[],
        system_prompt=ACTOR_SYSTEM if stage=='actor' else UPDATE_SYSTEM,agent_context=None,
        mcp_config={},condenser=None,critic=None,tool_concurrency_limit=1)

    def record(event):
        value={'type':type(event).__name__,'source':getattr(event,'source',None)}
        if type(event).__name__=='ConversationErrorEvent':
            value['code']=getattr(event,'code',None)
            errors.append(value['code'])
        else:
            for key in ('tool_name','tool_call_id','llm_response_id'):
                if getattr(event,key,None) is not None: value[key]=getattr(event,key)
        with (output/'events.jsonl').open('a',encoding='utf-8') as stream:
            stream.write(json.dumps(value,ensure_ascii=False,allow_nan=False)+'\n')

    result=dict(version=VERSION,stage=stage,session_id=session_id,status='error',error_type=None,
        request_id=None,request=None,response=None,dispatch=None,business=None,compiled=None,policy=None,
        candidate_executions=0,model_weight_updates=0)
    conv=None
    write_once(output/'transport-settings.json',public_settings())
    try:
        conv=ControlledPilotConversation(agent,workspace=output/'workspace',persistence_dir=None,
            callbacks=[record],max_iteration_per_run=1,stuck_detection=False,visualizer=None,
            plugins=[],delete_on_close=False,profile_store_dir=output/'empty-profiles')
        with patch('openhands.sdk.agent.base.has_vision_profile_available',return_value=False):
            conv.send_message(canonical(packet).decode('utf-8'))
        if (set(conv.agent.tools_map)!={tool_name} or conv.agent.mcp_config
                or conv.agent.agent_context is not None or conv._hook_processor is not None):
            raise RuntimeError('Unexpected tool or ambient context')
        if capture:
            conv.run()
        else:
            with observed_strategy_transport(output,settings):
                conv.run()
        result['conversation_status']=str(conv.state.execution_status)
    except Exception as error:
        cause=error
        while cause is not None and not isinstance(cause,CaptureReached): cause=cause.__cause__
        if not (capture and cause is not None):
            result.update(error_type=type(error).__name__,**safe_error_metadata(error))
    finally:
        if conv is not None: conv.close()
    if capture:
        if state['captured'] is None:
            write_once(output/'capture-error.json',result)
            raise RuntimeError('SDK failed before request template capture')
        write_once(output/'request-template.json',state['captured'])
        return state['captured']
    result['request_id']=state['request_id']
    for field,path in [('request',output/'requests'/((state['request_id'] or '')+'.request.json')),
                       ('response',output/'requests'/((state['request_id'] or '')+'.response.json')),
                       ('dispatch',output/'sdk-dispatch.json')]:
        if path.is_file(): result[field]=reference(root,path)
    budget=ledger.summary()
    unexpected=[code for code in errors if code!='MaxIterationsReached' or not state['accepted']]
    if (state['accepted'] and result['error_type'] is None and state['transport_error'] is None
            and not unexpected and not budget['halted'] and not budget['usage_unknown_count'] and not budget['reserved_count']):
        result.update(status='accepted',business=state['business'],compiled=state['compiled'],policy=state['policy'])
    result['error_type']=result['error_type'] or state['transport_error']
    result['sdk_error_codes']=errors
    write_once(output/'session-summary.json',result)
    return result


def run_session(root, output_dir, session_id, packet, ledger, settings, *, stage='actor',
                spec=None, accept_callback=None, pre_request_guard=None):
    """Execute one new SDK slot, returning receipts; never fit or score a task."""
    return _execute(root,output_dir,session_id,packet,ledger,settings,stage=stage,spec=spec,
        accept_callback=accept_callback,pre_request_guard=pre_request_guard)


def capture_request_template(root, output_dir, session_id, packet, ledger, settings, *, stage='actor',spec=None):
    """Build the full real SDK payload, without reserve or provider dispatch."""
    return _execute(root,output_dir,session_id,packet,ledger,settings,stage=stage,spec=spec,capture=True)

