"""Strict one-submission SDK boundary for a host-owned symbolic basis contract.

This module does not create an Agent, contact a model, load data, or fit a model.
The caller validates the original response with ``prepare_response`` *before*
SDK argument parsing, then supplies the SDK action to this tool's executor.
Production provider dispatch, budget accounting, persistence and evidence-bound
task packets are deliberately outside this adapter's current scope.
"""
import copy
import json
import threading

VERSION = 'symbolic-basis-sdk-adapter-v0.1'
MAX_RAW_BYTES = 65536


def _json_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON key')
        result[key] = value
    return result


def _nonfinite(value):
    raise ValueError('Nonfinite JSON value')


def _decode_json(value):
    if type(value) is not str:
        raise ValueError('Original JSON text is required before SDK parsing')
    try:
        if len(value.encode('utf-8')) > MAX_RAW_BYTES:
            raise ValueError('Raw JSON exceeds bounded response size')
        return json.loads(value, object_pairs_hook=_json_pairs, parse_constant=_nonfinite)
    except (UnicodeError, TypeError, RecursionError) as error:
        raise ValueError('Invalid bounded UTF-8 JSON') from error


HOST_EXPLANATION = 'Host-generated execution payload; model explanation is archive-only.'


def _business_payload(value):
    if type(value) is not dict or set(value) != {'feature_ids'}:
        raise ValueError('Business payload must contain exactly feature_ids')
    ids = value['feature_ids']
    if (type(ids) is not list or not 1 <= len(ids) <= 16
            or any(type(item) is not str or not item or len(item) > 128 for item in ids)
            or len(set(ids)) != len(ids)):
        raise ValueError('Feature IDs must be distinct bounded strings in a JSON list')
    try:
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False).encode('utf-8')
    except (ValueError, UnicodeError, TypeError) as error:
        raise ValueError('Business payload must be finite UTF-8 JSON') from error
    if len(encoded) > MAX_RAW_BYTES:
        raise ValueError('Business payload exceeds bounded response size')
    return copy.deepcopy(value)


def parse_tool_response(response):
    """Validate one chat-completion response without repair or type coercion.

    A provider dictionary is supported because SDK transport normally returns an
    already-decoded envelope. Its function.arguments MUST still be the original
    JSON string; duplicate business keys can therefore be rejected. Duplicate
    envelope keys can only be detected when the complete response is supplied as
    JSON text. This parser never claims otherwise.
    """
    if type(response) is str:
        response = _decode_json(response)
    if type(response) is not dict:
        raise ValueError('Expected provider response object')
    choices = response.get('choices')
    if type(choices) is not list or len(choices) != 1 or type(choices[0]) is not dict:
        raise ValueError('Exactly one provider choice is required')
    choice = choices[0]
    message = choice.get('message')
    if (choice.get('finish_reason') != 'tool_calls' or type(message) is not dict
            or message.get('role') != 'assistant'):
        raise ValueError('Expected assistant tool-call completion')
    calls = message.get('tool_calls')
    if type(calls) is not list or len(calls) != 1 or type(calls[0]) is not dict:
        raise ValueError('Exactly one tool call is required')
    call = calls[0]
    function = call.get('function')
    if (set(call) != {'id', 'type', 'function'} or call.get('type') != 'function'
            or type(call.get('id')) is not str or not call['id']
            or type(function) is not dict or set(function) != {'name', 'arguments'}
            or function['name'] != 'submit_basis'):
        raise ValueError('Only the submit_basis function is accepted')
    return _business_payload(_decode_json(function['arguments']))


class BasisSubmissionHandler:
    """Bind one immutable host spec to one raw response and one callback attempt.

    No task identifier, dataset, executable source, coefficient values or role
    is accepted from the model. The callback belongs to the trusted host. A
    malformed response, mismatched SDK action or callback failure consumes this
    handler; creating a fresh handler is an explicit host scheduling decision.
    """
    def __init__(self, spec, callback):
        from .contract import make_spec
        if type(spec) is not dict or not callable(callback):
            raise ValueError('A trusted specification and callable host are required')
        expected = make_spec(spec.get('n_inputs'), spec.get('k'))
        try:
            self._spec_json = json.dumps(spec, ensure_ascii=False, allow_nan=False, sort_keys=True)
            expected_json = json.dumps(expected, ensure_ascii=False, allow_nan=False, sort_keys=True)
        except (ValueError, TypeError, UnicodeError) as error:
            raise ValueError('Specification must be exact finite JSON') from error
        if self._spec_json != expected_json:
            raise ValueError('Specification differs from the trusted host catalog')
        self._callback = callback
        self._state = 'pending'
        self._business = None
        self._compiled = None
        self._lock = threading.RLock()

    @property
    def spec(self):
        return json.loads(self._spec_json)

    @property
    def state(self):
        return self._state

    def prepare_response(self, response):
        """Freeze strict raw business fields before any SDK normalization."""
        from .contract import compile_submission
        with self._lock:
            if self._state != 'pending':
                raise ValueError('One raw response per handler; no retry')
            self._state = 'failed'
            business = parse_tool_response(response)
            compiled = compile_submission({**business, 'explanation': HOST_EXPLANATION}, self.spec)
            self._business = copy.deepcopy(business)
            self._compiled = copy.deepcopy(compiled)
            self._state = 'prepared'
            return copy.deepcopy(business)

    def accept_action(self, business):
        """Invoke the host at most once, only for the exact raw submission."""
        with self._lock:
            if self._state != 'prepared':
                if self._state == 'pending':
                    self._state = 'failed'
                raise ValueError('Exactly one previously validated raw response is required')
            self._state = 'failed'
            received = _business_payload(business)
            if received != self._business:
                raise ValueError('SDK action differs from the original raw submission')
            # Consume before the callback, including if it raises or re-enters.
            self._state = 'dispatching'
            compiled = copy.deepcopy(self._compiled)
        try:
            feedback = self._callback(compiled)
            if type(feedback) is not dict:
                raise ValueError('Host callback must return a feedback object')
            feedback = json.loads(json.dumps(feedback, ensure_ascii=False, allow_nan=False))
        except Exception:
            self._state = 'failed'
            raise
        self._state = 'accepted'
        return feedback


def build_tool_definition(handler):
    """Construct the actual SDK tool; imports SDK only when explicitly called.

    The action schema exposes exactly the feature selection field. SDK-generated
    metadata fields are not advertised or accepted by this successor contract.
    Integration with a future Agent must also disable its default tools and
    invoke prepare_response at the raw-provider boundary before SDK parsing.
    """
    if type(handler) is not BasisSubmissionHandler:
        raise ValueError('A dedicated basis submission handler is required')
    from typing import ClassVar
    from openhands.sdk import Action, Observation, ToolDefinition
    from openhands.sdk.tool import ToolExecutor
    from pydantic import ConfigDict, Field, StrictStr, model_validator
    from .contract import validate_submission

    spec = handler.spec
    schema = {
        'type': 'object',
        'properties': {
            'feature_ids': {'type': 'array', 'items': {'type': 'string', 'enum': spec['feature_ids']},
                            'minItems': spec['k'], 'maxItems': spec['k'], 'uniqueItems': True,
                            'description': 'Choose exactly the host-specified number of distinct catalog IDs, including the constant.'},
        },
        'required': ['feature_ids'],
        'additionalProperties': False,
    }

    class BasisSubmissionAction(Action):
        model_config = ConfigDict(extra='forbid', strict=True)
        feature_ids: list[StrictStr] = Field(min_length=spec['k'], max_length=spec['k'])

        @classmethod
        def to_mcp_schema(cls):
            return copy.deepcopy(schema)

        @model_validator(mode='after')
        def strict_contract(self):
            business = self.model_dump(exclude={'kind'})
            _business_payload(business)
            validate_submission({**business, 'explanation': HOST_EXPLANATION}, spec)
            return self

    class BasisSubmissionObservation(Observation):
        feedback: dict = Field(default_factory=dict)

    class BasisExecutor(ToolExecutor):
        def __call__(self, action, conversation=None):
            if type(action) is not BasisSubmissionAction:
                raise ValueError('Expected the bound SDK basis action type')
            feedback = handler.accept_action(action.model_dump(exclude={'kind'}))
            return BasisSubmissionObservation.from_text(
                json.dumps(feedback, ensure_ascii=False, allow_nan=False, sort_keys=True), feedback=feedback)

    class BasisSubmissionTool(ToolDefinition):
        name: ClassVar[str] = 'submit_basis'

        @classmethod
        def create(cls, conv_state=None, **params):
            if params:
                raise ValueError('Model-controlled tool initialization is not accepted')
            return [cls(action_type=BasisSubmissionAction, observation_type=BasisSubmissionObservation,
                        executor=BasisExecutor(), description='Submit one basis selection to a trusted host. The host owns coefficients and scoring.')]

    return BasisSubmissionTool.create()[0]
