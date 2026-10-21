"""One SDK request and one durable submission for a frozen strategy slot.

Only provider transport is replaceable in offline tests. The actual SDK builds
messages/tools and dispatches the action. No task execution lives in this tool.
The 80 KiB packet limit is distinct from the complete 96 KiB request limit.
"""
import copy
import hashlib
import importlib.metadata
import json
from pathlib import Path
from typing import ClassVar, Literal
from unittest.mock import patch

from openhands.sdk import Agent, Tool, ToolDefinition
from openhands.sdk.tool import ToolExecutor, register_tool
from pydantic import Field, PrivateAttr, StrictInt, StrictStr

from .pilot_agent import BoundedPilotLLM, ControlledPilotConversation, PilotResponseContractError, safe_error_metadata, write_json
from .state_packet import replace_messages, wire_payload
from .strategy_binding import _request_packet
from .strategy_learning import canonical
from .strategy_pair_controller import SDK_SECURITY_RISKS, StrategyPairController, reference, write_once
from .two_stage_agent import _SubmissionAction, TwoStageObservation

VERSION = 'strategy-pair-agent-v0.2'
UPDATE_SYSTEM = ('Select one fixed-weight external strategy using only the complete supplied historical '
    'learning packet. Return exactly one tool call: submit_policy with four distinct catalog rule IDs in order. '
    'This is the only available tool. Do not call finish or any additional tool; the host ends this single step. '
    'Any optional explanation is unverified archive-only text. No task execution, source submission, '
    'additional request, files, networks or subprocesses are available.')
ACTOR_SYSTEM = ('Make one complete artifact revision using the supplied current_state and repair_policy. '
    'Return exactly one tool call: submit_candidate with complete Python source and its declared parameter count. '
    'This is the only available tool. Do not call finish or any additional tool; the host ends this single step. '
    'No task execution, repair of your output, additional request, files, networks or subprocesses are '
    'available in this conversation. The host will evaluate separately under its frozen allocation. '
    'Any optional explanation is unverified archive-only text.')
Rule = Literal['R01','R02','R03','R04','R05','R06','R07','R08']


class _StrategySubmissionAction(_SubmissionAction):
    @classmethod
    def to_mcp_schema(cls):
        schema = super().to_mcp_schema()
        definitions = cls.model_json_schema().get('$defs', {})

        def resolve(value, trail=()):
            if isinstance(value, list):
                return [resolve(item, trail) for item in value]
            if not isinstance(value, dict):
                return value
            if '$ref' in value:
                ref = value['$ref']
                prefix = '#/$defs/'
                if (not isinstance(ref, str) or not ref.startswith(prefix)
                        or ref in trail or ref[len(prefix):] not in definitions):
                    raise ValueError('Unresolved strategy tool schema reference')
                target = definitions[ref[len(prefix):]]
                value = resolve(target, trail + (ref,)) | {k: v for k, v in value.items() if k != '$ref'}
            return {key: resolve(item, trail) for key, item in value.items()}

        # The historical wrapper preserves authored bounds by restoring original
        # properties. Restore their definitions too by inlining, including the
        # SDK-added SecurityRisk enum, instead of sending dangling local refs.
        schema = resolve(schema)
        risk = schema['properties'].get('security_risk')
        if risk is not None and (risk.get('type') != 'string'
                or tuple(risk.get('enum', ())) != SDK_SECURITY_RISKS):
            raise ValueError('Installed SDK risk schema differs from strict raw contract')
        return schema


class StrategyUpdateAction(_StrategySubmissionAction):
    rule_1: Rule = Field(description='First fixed-catalog rule ID.')
    rule_2: Rule = Field(description='Second distinct fixed-catalog rule ID.')
    rule_3: Rule = Field(description='Third distinct fixed-catalog rule ID.')
    rule_4: Rule = Field(description='Fourth distinct fixed-catalog rule ID.')
    explanation: StrictStr = Field(default='', max_length=4096,
        description='Optional unverified explanation, at most 4096 UTF-8 bytes; archived only.')


class StrategyActorAction(_StrategySubmissionAction):
    source: StrictStr = Field(min_length=1, max_length=16384,
        description='Complete Python source, at most 16384 UTF-8 bytes; no patch or prose.')
    n_params: StrictInt = Field(ge=0, le=16, description='Declared formula parameter count; zero for planning.')
    explanation: StrictStr = Field(default='', max_length=4096,
        description='Optional unverified explanation, at most 4096 UTF-8 bytes; archived only.')


class _TemplateCaptured(RuntimeError):
    pass


class StrategyPacketLLM(BoundedPilotLLM):
    _controller: object = PrivateAttr(default=None)
    _guard: object = PrivateAttr(default=None)
    _capture_only: bool = PrivateAttr(default=False)
    _captured_payload: dict | None = PrivateAttr(default=None)
    _payload: dict | None = PrivateAttr(default=None)
    _request_id: str | None = PrivateAttr(default=None)
    _response_id: str | None = PrivateAttr(default=None)
    _tool_call_id: str | None = PrivateAttr(default=None)
    _validated_business: dict | None = PrivateAttr(default=None)
    _audit: dict | None = PrivateAttr(default=None)
    _transport_error: str | None = PrivateAttr(default=None)
    _attempted: bool = PrivateAttr(default=False)

    def bind_controller(self, controller):
        if type(controller) is not StrategyPairController:
            raise ValueError('Dedicated strategy controller required')
        self._controller = controller
        return self

    def _pilot_transport_started(self, request_id):
        self._request_id = request_id
        self._audit.update(request_id=request_id, request_reserved=True)
        write_json(self._pilot_output/'input-audit.json', self._audit)
        if self._guard is not None:
            self._guard(copy.deepcopy(self._payload))
        self._audit.update(transport_called=True, status='dispatched')
        write_json(self._pilot_output/'input-audit.json', self._audit)

    def _transport_call(self, *, messages, enable_streaming=False, on_token=None, **kwargs):
        if self._attempted:
            raise PilotResponseContractError('One request per slot; no automatic retry')
        self._attempted = True
        packet = self._controller.task_packet()
        if len(canonical(packet)) > 81920:
            raise ValueError('Strategy packet exceeds 81920 bytes')
        replacement = replace_messages(messages, packet)
        output = kwargs.get('max_tokens', kwargs.get('max_completion_tokens', self.max_output_tokens))
        payload = wire_payload(self.model, replacement, kwargs.get('tools'), kwargs.get('tool_choice'), output)
        expected_tool = 'submit_policy' if self._controller.stage == 'update' else 'submit_candidate'
        advertised = payload.get('tools')
        if (type(advertised) is not list or len(advertised) != 1
                or advertised[0].get('type') != 'function'
                or advertised[0].get('function', {}).get('name') != expected_tool
                or payload.get('tool_choice') is not None):
            raise ValueError('Strategy request must advertise only its single business tool')
        self._payload = payload
        if self._capture_only:
            self._captured_payload = payload
            raise _TemplateCaptured('SDK request captured without budget or provider access')
        self._audit = dict(version='strategy-pair-input-audit-v0.1', request_id=None,
            slot_id=self._pilot_session, actual_input_bytes=len(canonical(payload)),
            max_input_bytes=self._pilot_ledger.config['max_input_bytes'], payload_sha256=hashlib.sha256(canonical(payload)).hexdigest(),
            request_reserved=False, transport_called=False, status='pending', error_type=None)
        write_once(self._pilot_output/'packet.json', packet)
        write_once(self._pilot_output/'input-audit.json', self._audit)
        try:
            if self._guard is not None:
                self._guard(copy.deepcopy(payload))
            response = super()._transport_call(messages=replacement, enable_streaming=enable_streaming,
                                               on_token=on_token, **kwargs)
            summary = self._pilot_ledger.summary()
            if summary['halted'] or summary['reserved_count'] or summary['usage_unknown_count']:
                raise PilotResponseContractError('Known settled usage is required for SDK acceptance')
            choice = response.choices[0]
            calls = choice.message.tool_calls
            if choice.finish_reason == 'tool_calls' and not calls:
                raise PilotResponseContractError('Provider announced tool calls without a call')
            if calls:
                # Strict raw JSON validation precedes SDK parsing/normalization.
                # Extra keys, duplicate keys and coercions cannot disappear in
                # an SDK repair and subsequently become accepted evidence.
                self._validated_business = self._controller.validate_arguments(calls[0].function.arguments)
                self._response_id = response.id
                self._tool_call_id = calls[0].id
                if not all(type(v) is str and v for v in (self._response_id,self._tool_call_id)):
                    raise PilotResponseContractError('Response and tool call identities required')
            self._audit['status'] = 'completed'
            return response
        except Exception as error:
            self._transport_error = type(error).__name__
            self._audit.update(status='error',error_type=self._transport_error)
            raise
        finally:
            write_json(self._pilot_output/'input-audit.json', self._audit)


class StrategyUpdateLLM(StrategyPacketLLM):
    _pilot_allowed_tools: ClassVar[frozenset[str]] = frozenset({'submit_policy'})


class StrategyActorLLM(StrategyPacketLLM):
    _pilot_allowed_tools: ClassVar[frozenset[str]] = frozenset({'submit_candidate'})


def make_llm(settings, controller, ledger):
    settings = dict(settings)
    required = dict(max_output_tokens=8192,num_retries=0,timeout=180,caching_prompt=False,
        api_mode='chat',stream=False,native_tool_calling=True,force_string_serializer=False,
        fallback_strategy=None,log_completions=False)
    for name,value in required.items():
        if name in settings and settings[name] != value:
            raise ValueError('Unbounded or inconsistent model setting: '+name)
        settings[name] = value
    cls = StrategyUpdateLLM if controller.stage == 'update' else StrategyActorLLM
    return cls(**settings).bind_controller(controller).bind_pilot(ledger, controller.slot_id,
                                                                  controller.output_dir/'requests')


class _Executor(ToolExecutor):
    def __init__(self, controller, llm):
        self.controller, self.llm = controller, llm

    def __call__(self, action, conversation=None):
        c, llm = self.controller,self.llm
        try:
            business = action.model_dump(exclude={'kind'})
            if c.validate_arguments(business) != llm._validated_business:
                raise ValueError('SDK action differs from strict provider submission')
            summary = llm._pilot_ledger.summary()
            if (summary['halted'] or summary['reserved_count'] or summary['usage_unknown_count']
                    or summary['session_counts'].get(c.slot_id) != 1 or llm._transport_error is not None):
                raise ValueError('One known settled request is required for submission')
            request = reference(c.root, llm._pilot_output/(llm._request_id+'.request.json'))
            response = reference(c.root, llm._pilot_output/(llm._request_id+'.response.json'))
            receipt = dict(version='strategy-sdk-submission-v0.1',stage=c.stage,slot_id=c.slot_id,
                tool='submit_policy' if c.stage=='update' else 'submit_candidate',
                request_id=llm._request_id,request=request,response=response,response_id=llm._response_id,
                tool_call_id=llm._tool_call_id,business=business)
            write_once(c.output_dir/'sdk-submission.json', receipt)
            feedback = c.accept(business,llm._request_id,request,reference(c.root,c.output_dir/'sdk-submission.json'))
            return TwoStageObservation.from_text(json.dumps(feedback,sort_keys=True),feedback=feedback)
        except Exception as error:
            c.halted=True
            write_json(c.output_dir/'controller-error.json',dict(error_type=type(error).__name__,stage=c.stage))
            raise


def _tool(controller,llm):
    action = StrategyUpdateAction if controller.stage=='update' else StrategyActorAction
    business_name = 'submit_policy' if controller.stage=='update' else 'submit_candidate'
    class SubmissionTool(ToolDefinition):
        name: ClassVar[str] = business_name
        @classmethod
        def create(cls,conv_state=None,**params):
            if params:
                raise ValueError('Submission tool accepts no initialization settings')
            return [cls(action_type=action,observation_type=TwoStageObservation,executor=_Executor(controller,llm),
                description='Archive one strict complete submission. No source is executed or scored. Optional explanation remains archive-only.')]
    registry_name='StrategyPair_'+controller.slot_id
    register_tool(registry_name,SubmissionTool)
    return Tool(name=registry_name)


def _validate(controller,llm,session_id,directory):
    expected=StrategyUpdateLLM if controller.stage=='update' else StrategyActorLLM
    if (type(llm) is not expected or llm._controller is not controller
            or llm._pilot_session!=session_id or session_id!=controller.slot_id
            or Path(directory).absolute()!=controller.output_dir or llm._pilot_output!=controller.output_dir/'requests'
            or controller.status!='pending' or controller.halted or llm._attempted):
        raise ValueError('Strategy session binding or lifecycle mismatch')
    limits=llm._pilot_ledger.config
    if (limits['max_requests_per_session']!=1 or limits['max_input_bytes']>98304
            or limits['max_output_tokens']!=8192 or llm.max_output_tokens!=8192
            or llm.timeout!=180 or llm.num_retries!=0 or llm.stream or llm.caching_prompt
            or llm.api_mode!='chat' or llm.fallback_strategy is not None):
        raise ValueError('Strategy requires one bounded 96 KiB request, 8192 output tokens, 180 seconds and no retries')
    if importlib.metadata.version('openhands-sdk')!='1.55.1':
        raise RuntimeError('Strategy adapter requires OpenHands SDK 1.55.1')
    for path in (controller.output_dir/'requests',controller.output_dir,*controller.output_dir.parents):
        if path.is_symlink() or (hasattr(path,'is_junction') and path.is_junction()):
            raise ValueError('Symlinked session output')


def _conversation(controller,llm,directory,callback=None):
    model = Agent(llm=llm,tools=[_tool(controller,llm)],include_default_tools=[],
        system_prompt=UPDATE_SYSTEM if controller.stage=='update' else ACTOR_SYSTEM,
        agent_context=None,mcp_config={},condenser=None,critic=None,tool_concurrency_limit=1)
    conv=ControlledPilotConversation(model,workspace=Path(directory)/'workspace',persistence_dir=None,
        callbacks=[callback] if callback else [],max_iteration_per_run=1,stuck_detection=False,
        visualizer=None,plugins=[],delete_on_close=False,profile_store_dir=Path(directory)/'empty-profiles')
    try:
        with patch('openhands.sdk.agent.base.has_vision_profile_available',return_value=False):
            conv.send_message(controller.task_prompt())
        if (set(conv.agent.tools_map)!=llm._pilot_allowed_tools or conv.agent.mcp_config
                or conv.agent.agent_context is not None or conv._hook_processor is not None):
            raise RuntimeError('Unexpected strategy tools or ambient context')
    except Exception:
        conv.close()
        raise
    return conv


def prepare_request_template(controller,llm,session_id,directory):
    """Capture actual SDK serialization before ledger reserve or provider use.

    The template controller/LLM are consumed; use fresh instances for real slots.
    User content alone becomes None, matching the frozen binding normalizer.
    """
    _validate(controller,llm,session_id,directory)
    llm._capture_only=True
    conv=None
    try:
        conv=_conversation(controller,llm,directory)
        try:
            conv.run()
        except Exception as error:
            # SDK wraps transport exceptions in ConversationRunError. Accept
            # only our own capture sentinel in that explicit cause chain.
            cause = error
            while cause is not None and not isinstance(cause, _TemplateCaptured):
                cause = cause.__cause__
            if cause is None:
                raise
    finally:
        if conv is not None:
            conv.close()
        llm._capture_only=False
    if llm._captured_payload is None:
        raise RuntimeError('SDK did not reach request serialization')
    return _request_packet(llm._captured_payload)[1]


def run_session(controller,llm,session_id,directory,*,pre_request_guard=None):
    """Run one SDK lifecycle; original request/response and dispatch stay separate."""
    _validate(controller,llm,session_id,directory)
    output=controller.output_dir
    if any((output/name).exists() for name in ('events.jsonl','session-summary.json','sdk-submission.json','submission.json')):
        raise FileExistsError('Refusing to overwrite an SDK session')
    if pre_request_guard is not None and not callable(pre_request_guard):
        raise ValueError('Pre-request guard must be callable')
    llm._guard=pre_request_guard
    write_once(output/'transport-settings.json',dict(version=VERSION,timeout=llm.timeout,
        num_retries=llm.num_retries,provider_max_retries=0,stream=False,max_output_tokens=llm.max_output_tokens))
    errors=[]
    def record(event):
        value=dict(type=type(event).__name__,source=getattr(event,'source',None))
        if type(event).__name__=='ConversationErrorEvent':
            value['code']=getattr(event,'code',None)
            errors.append(value['code'])
        else:
            for key in ('tool_name','tool_call_id','llm_response_id'):
                if getattr(event,key,None) is not None:
                    value[key]=getattr(event,key)
        with (output/'events.jsonl').open('a',encoding='utf-8') as stream:
            stream.write(json.dumps(value,ensure_ascii=False,allow_nan=False)+'\n')
    result=dict(version=VERSION,slot_id=session_id,stage=controller.stage,status='error',
        request_id=None,request=None,response=None,submission=None,source=None,policy=None,
        sdk_submission=None,input_audit=None,error_type=None)
    conv=None
    try:
        conv=_conversation(controller,llm,directory,record)
        conv.run()
        result['conversation_status']=str(conv.state.execution_status)
    except Exception as error:
        result.update(error_type=type(error).__name__,**safe_error_metadata(error))
    finally:
        if conv is not None:
            conv.close()
        result['request_id']=llm._request_id
        for field,path in [('request',llm._pilot_output/((llm._request_id or '')+'.request.json')),
                           ('response',llm._pilot_output/((llm._request_id or '')+'.response.json')),
                           ('sdk_submission',output/'sdk-submission.json'),
                           ('input_audit',llm._pilot_output/'input-audit.json')]:
            if path.is_file():
                result[field]=reference(controller.root,path)
        budget=llm._pilot_ledger.summary()
        # SDK 1.55.1 emits MaxIterationsReached after a successfully dispatched
        # one-step tool. It is expected only when the controller accepted that
        # action; every other error code or missing acceptance remains fatal.
        unexpected_errors=[code for code in errors
                           if code!='MaxIterationsReached' or controller.status!='accepted']
        fatal=(result['error_type'] is not None or llm._transport_error is not None or unexpected_errors
               or controller.halted or budget['halted'] or budget['usage_unknown_count'] or budget['reserved_count'])
        if not fatal and controller.status=='pending' and result['request'] is not None:
            controller.missing(llm._request_id,result['request'])
        result['status']=controller.status if not fatal and controller.status in ('accepted','missing') else 'error'
        result['error_type']=result['error_type'] or llm._transport_error
        result.update(submission=controller.submission,source=controller.source,policy=controller.policy,
            sdk_error_codes=errors,controller=controller.summary())
        write_once(output/'session-summary.json',result)
    return result
