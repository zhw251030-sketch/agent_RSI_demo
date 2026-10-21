"""Compare the actual SDK-to-LiteLLM payload with the persisted budget record.

Only a known public settings projection and payload hashes are retained. Keys,
headers and arbitrary provider kwargs are neither serialized nor hashed. This
is a synchronous trusted-process boundary record, not an HTTP trace or provider
attestation. LiteLLM's later provider-specific transformation is not observed.
"""
from contextlib import contextmanager
import hashlib
import importlib
from pathlib import Path
import threading
from unittest.mock import patch

from .state_generation_transport import observed_transport, _request_binding, _safe_path, _write_once, _flags
from .strategy_learning import canonical
from .strategy_pair_controller import strict_json

VERSION='strategy-pair-dispatch-v0.1'
_LOCK=threading.Lock()
_PUBLIC_ENDPOINT='https://api.minimax.cn/anthropic'
_OPTIONAL_DEFAULTS=('top_p','top_k','frequency_penalty','presence_penalty','stop','n',
    'logit_bias','logprobs','top_logprobs','parallel_tool_calls','response_format',
    'stream_options','fallbacks','context_window_fallbacks','thinking')


def _require(condition,message):
    if not condition:
        raise ValueError(message)


def _digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def safe_settings(settings):
    """Select only fixed public fields; never inspect/hash authentication."""
    _require(type(settings) is dict,'Expected a public settings object')
    expected=dict(model='anthropic/MiniMax-M3',base_url=_PUBLIC_ENDPOINT,
        temperature=1.0,max_output_tokens=8192,timeout=180,num_retries=0,caching_prompt=False,
        reasoning_effort='none',litellm_extra_body={'thinking':{'type':'disabled'}})
    _require(all(settings.get(key)==value for key,value in expected.items()),'Public strategy model settings differ')
    _require(type(settings['temperature']) in (int,float) and type(settings['max_output_tokens']) is int
        and type(settings['timeout']) in (int,float) and type(settings['num_retries']) is int
        and type(settings['caching_prompt']) is bool,'Public model setting types differ')
    # Values are known constants, so unrecognized caller values never enter a
    # digest or output. Defaults are checked at the actual callable boundary.
    return expected | dict(seed=None,drop_params=True)


def _request(directory):
    name,digest=_request_binding(Path(directory))
    body=strict_json(_safe_path(Path(directory)/name).read_bytes())
    _require(type(body) is dict and set(body)=={'model','messages','tools','tool_choice','max_output_tokens'},
        'Unexpected saved request projection')
    _require(body['model']=='anthropic/MiniMax-M3' and body['max_output_tokens']==8192
        and type(body['max_output_tokens']) is int,'Saved model/output bound differs')
    return name,digest,body


def validate_dispatch(directory,kwargs,expected_settings):
    """Return an allowlisted record only if actual dispatch matches saved input."""
    settings=safe_settings(expected_settings)
    _require(type(kwargs) is dict,'Expected keyword dispatch')
    _flags(kwargs,180)
    _require(kwargs.get('model')=='MiniMax-M3' and kwargs.get('custom_llm_provider')=='anthropic',
        'Actual provider model mapping differs')
    _require(kwargs.get('api_base')==_PUBLIC_ENDPOINT,'Actual public provider endpoint differs')
    _require(type(kwargs.get('max_completion_tokens')) is int and kwargs['max_completion_tokens']==8192
        and 'max_tokens' not in kwargs,'Actual output token bound differs')
    _require(type(kwargs.get('temperature')) in (int,float) and kwargs['temperature']==1.0
        and 'seed' in kwargs and kwargs['seed'] is None and kwargs.get('drop_params') is True,
        'Actual sampling/default parameters differ')
    _require('reasoning_effort' not in kwargs and kwargs.get('extra_body')=={'thinking':{'type':'disabled'}},
        'Actual thinking parameters differ')
    _require(all(kwargs.get(name) is None for name in _OPTIONAL_DEFAULTS),
        'Unfrozen functional provider option')
    _require(all(kwargs.get(name) in (None,False) for name in ('cache','caching','caching_prompt')),
        'Unfrozen provider caching option')
    name,digest,body=_request(directory)
    actual=dict(model='anthropic/MiniMax-M3',messages=kwargs.get('messages'),tools=kwargs.get('tools'),
        tool_choice=kwargs.get('tool_choice'),max_output_tokens=kwargs['max_completion_tokens'])
    _require(canonical(actual)==canonical(body),'Actual dispatched messages/tools/choice differ from budgeted request')
    observed=dict(model='MiniMax-M3',custom_llm_provider='anthropic',public_endpoint_matches=True,
        max_completion_tokens=8192,tool_choice=body['tool_choice'],temperature=1.0,seed=None,drop_params=True,
        extra_body={'thinking':{'type':'disabled'}},reasoning_effort_present=False,
        messages_sha256=_digest(body['messages']),tools_sha256=_digest(body['tools']))
    return dict(version=VERSION,request_file=name,request_sha256=digest,request_payload_sha256=_digest(body),
        settings_sha256=_digest(settings),observed=observed)


def verify_dispatch_record(directory,expected_settings):
    """Replay the persisted allowlisted proof; no SDK import or provider call."""
    directory=_safe_path(directory)
    settings=safe_settings(expected_settings)
    name,digest,body=_request(directory)
    expected=dict(version=VERSION,request_file=name,request_sha256=digest,request_payload_sha256=_digest(body),
        settings_sha256=_digest(settings),observed=dict(model='MiniMax-M3',custom_llm_provider='anthropic',
            public_endpoint_matches=True,max_completion_tokens=8192,tool_choice=body['tool_choice'],
            temperature=1.0,seed=None,drop_params=True,extra_body={'thinking':{'type':'disabled'}},
            reasoning_effort_present=False,messages_sha256=_digest(body['messages']),tools_sha256=_digest(body['tools'])))
    actual=strict_json(_safe_path(directory/'sdk-dispatch.json').read_bytes())
    _require(actual==expected,'Actual dispatch projection or request/settings binding changed')
    return actual


@contextmanager
def observed_strategy_transport(directory,expected_settings):
    """Verify one actual call, then preserve existing timeout/duration receipts."""
    directory=_safe_path(directory)
    safe_settings(expected_settings)
    proof=_safe_path(directory/'sdk-dispatch.json')
    if proof.exists():
        raise FileExistsError('Refusing to overwrite SDK dispatch evidence')
    if not _LOCK.acquire(blocking=False):
        raise RuntimeError('A strategy dispatch observer is already active')
    try:
        module=importlib.import_module('openhands.sdk.llm.llm')
        provider=module.litellm_completion
        def verified(*args,**kwargs):
            _require(not args,'Actual SDK provider call requires keyword arguments')
            record=validate_dispatch(directory,kwargs,expected_settings)
            _write_once(proof,record)
            return provider(**kwargs)
        # The original observer records timeout/retry and elapsed return/raise;
        # this inner provider wrapper compares actual content before dispatch.
        with patch.object(module,'litellm_completion',verified):
            with observed_transport(directory,expected_timeout=180):
                yield
    finally:
        _LOCK.release()
