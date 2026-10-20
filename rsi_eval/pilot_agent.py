"""A bounded OpenHands research conversation; no ambient tools or filesystem access.

SDK-specific integration for the development pilot. Candidate execution remains
in the trusted controller and its existing isolated task executors.
"""
import json
import importlib.metadata
from pathlib import Path
from typing import ClassVar
from unittest.mock import patch

from openhands.sdk import Agent, LLM, Action, Observation, Tool, ToolDefinition
from openhands.sdk.conversation.impl.local_conversation import LocalConversation
from openhands.sdk.tool import ToolExecutor, register_tool
from pydantic import Field, PrivateAttr, StrictInt, field_validator


SYSTEM_PROMPT = """You are a research agent running a small development pilot.
The task packet defines the only authorized task and the candidate interface.
Use submit_candidate to execute candidate Python source. Do not claim execution
or improvement unless the tool returned supporting feedback. You have at most
three candidate submissions and four model requests including the final reply.
Start from the supplied baseline and feedback. Make one useful revision at a
time, briefly state its rationale, inspect the feedback, and revise again when
appropriate. Do not submit all revisions without observing intervening feedback.
Do not read files, use network services, create processes, or exploit the evaluator.
After at most three submissions finish with a concise account of changes,
observed development results, failures, and remaining uncertainty. These are
development observations, not held-out evaluation or evidence of a new method.
"""


class PilotResponseContractError(RuntimeError):
    """A paid response is recorded but cannot dispatch its proposed actions."""


def safe_error_metadata(error):
    """Read only status integers and a fixed code vocabulary, never HTTP bodies."""
    allowed_codes = {"internal_server_error", "api_error", "overloaded_error",
                     "service_unavailable", "rate_limit_error", "timeout",
                     "invalid_request_error", "authentication_error", "permission_error",
                     "not_found_error", "request_too_large"}
    result = {}
    current = error
    for _ in range(3):
        if current is None:
            break
        for carrier in (current, getattr(current, "response", None)):
            status = getattr(carrier, "status_code", None)
            if "http_status" not in result and type(status) is int and 100 <= status <= 599:
                result["http_status"] = status
        code = getattr(current, "code", None)
        if type(code) is str and code in allowed_codes:
            result.setdefault("error_code", code)
        current = current.__cause__
    return result


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, allow_nan=False,
                                    indent=2) + "\n", encoding="utf-8")


class SubmitCandidateAction(Action):
    source: str = Field(min_length=1, max_length=65536)
    n_params: StrictInt = Field(default=3, ge=0, le=16)
    rationale: str = Field(default="", max_length=2000)

    @field_validator("source")
    @classmethod
    def bounded_source(cls, value):
        if len(value.encode("utf-8")) > 65536:
            raise ValueError("Candidate exceeds 65536 UTF-8 bytes")
        return value


class SubmitCandidateObservation(Observation):
    feedback: dict = Field(default_factory=dict)


class _SubmitExecutor(ToolExecutor[SubmitCandidateAction, SubmitCandidateObservation]):
    def __init__(self, controller):
        self.controller = controller

    def __call__(self, action, conversation=None):
        action = SubmitCandidateAction.model_validate(action.model_dump())
        feedback = self.controller.submit(action.source, action.n_params, action.rationale)
        text = json.dumps(feedback, ensure_ascii=False, allow_nan=False, sort_keys=True)
        return SubmitCandidateObservation.from_text(text, feedback=feedback)


def candidate_tool(controller, session_id):
    """Bind one controller in process; task identities are not model arguments."""
    class SubmitCandidateTool(ToolDefinition[SubmitCandidateAction, SubmitCandidateObservation]):
        name: ClassVar[str] = "submit_candidate"

        @classmethod
        def create(cls, conv_state=None, **params):
            if params:
                raise ValueError("Candidate tool accepts no initialization options")
            return [cls(action_type=SubmitCandidateAction,
                        observation_type=SubmitCandidateObservation,
                        executor=_SubmitExecutor(controller),
                        description=("Submit one complete candidate Python program for this fixed task. "
                                     "The controller evaluates authorized development data only and records "
                                     "source, rationale, feedback and parent candidate. At most three submissions. "
                                     "Task identities, paths, shell commands and evaluation roles are not inputs."))]

    registry_name = "PilotSubmitCandidate_" + session_id
    register_tool(registry_name, SubmitCandidateTool)
    return Tool(name=registry_name)


class BoundedPilotLLM(LLM):
    """Reserve before every transport, including unexpected SDK retry paths."""
    _pilot_ledger: object = PrivateAttr(default=None)
    _pilot_session: str = PrivateAttr(default="")
    _pilot_output: Path | None = PrivateAttr(default=None)

    def bind_pilot(self, ledger, session_id, output_dir):
        self._pilot_ledger = ledger
        self._pilot_session = session_id
        self._pilot_output = Path(output_dir)
        self._pilot_output.mkdir(parents=True, exist_ok=True)
        return self

    def _pilot_transport_started(self, request_id):
        """Optional audit hook immediately before the provider dispatch attempt."""
        return None

    def _transport_call(self, *, messages, enable_streaming=False, on_token=None, **kwargs):
        if self._pilot_ledger is None or self._pilot_output is None:
            raise RuntimeError("Pilot LLM is not bound to a budget ledger")
        if enable_streaming or self.stream or self.num_retries != 0 or self.fallback_strategy is not None:
            raise RuntimeError("Unbounded transport configuration rejected")
        if self.caching_prompt or self.api_mode != "chat":
            raise RuntimeError("Pilot requires uncached chat completions")
        # Never log authentication, headers, arbitrary provider kwargs or errors.
        output_tokens = kwargs.get("max_tokens", kwargs.get("max_completion_tokens", self.max_output_tokens))
        if type(output_tokens) is not int or output_tokens <= 0:
            raise RuntimeError("Pilot needs a positive output token limit")
        payload = {"model": self.model, "messages": messages,
                   "tools": kwargs.get("tools"), "tool_choice": kwargs.get("tool_choice"),
                   "max_output_tokens": output_tokens}
        request_id = self._pilot_ledger.reserve(self._pilot_session, payload, output_tokens)
        # IDs are generated by the trusted ledger, not the model.
        request_path = self._pilot_output / (request_id + ".request.json")
        response_path = self._pilot_output / (request_id + ".response.json")
        write_json(request_path, payload)
        usage = None
        error_type = None
        try:
            kwargs["max_retries"] = 0
            self._pilot_transport_started(request_id)
            response = super()._transport_call(messages=messages, enable_streaming=False,
                                               on_token=None, **kwargs)
            raw_usage = getattr(response, "usage", None)
            usage = ({key: getattr(raw_usage, key, None)
                      for key in ("prompt_tokens", "completion_tokens", "total_tokens")}
                     if raw_usage is not None else None)
            usage_details = {}
            if raw_usage is not None:
                for key in ("prompt_tokens_details", "completion_tokens_details",
                            "cache_creation_input_tokens", "cache_read_input_tokens"):
                    value = getattr(raw_usage, key, None)
                    if value is not None:
                        usage_details[key] = value.model_dump(mode="json", exclude_none=True) if hasattr(value, "model_dump") else value
            choices = []
            for choice in response.choices:
                message = choice.message.model_dump(mode="json", exclude_none=True)
                choices.append({"message": message, "finish_reason": choice.finish_reason})
            response_record = {"response_id": response.id, "usage": usage,
                               "usage_details": usage_details, "choices": choices}
            write_json(response_path, response_record)
            calls = response.choices[0].message.tool_calls if len(response.choices) == 1 else None
            if (len(response.choices) != 1 or (calls and (len(calls) != 1
                    or calls[0].function.name not in {"submit_candidate", "finish"}))):
                response_record["error_type"] = "PilotResponseContractError"
                write_json(response_path, response_record)
                raise PilotResponseContractError("One candidate submission or finish is allowed per response")
            return response
        except Exception as error:
            error_type = type(error).__name__
            if not response_path.exists():
                write_json(response_path, {"error_type": error_type, **safe_error_metadata(error)})
            raise
        finally:
            self._pilot_ledger.settle(request_id, usage, error_type=error_type)


class ControlledPilotConversation(LocalConversation):
    """SDK 1.55.1 adapter disabling implicit home/project plugin discovery.

This intentionally overrides private lifecycle hooks and is version-specific.
It does not change Canvas or globally alter the installed SDK.
"""
    def _ensure_plugins_loaded(self):
        if self._plugins_loaded:
            return
        if self._plugin_specs or self._pending_hook_config is not None:
            raise ValueError("Research pilot does not allow plugins or hooks")
        if self.agent.agent_context is not None or self.agent.mcp_config:
            raise ValueError("Research pilot does not allow ambient context or MCP")
        self._plugins_loaded = True

    def _register_file_based_agents(self):
        # No child/delegation tool is exposed; skip ambient agent discovery too.
        return None


def create_conversation(controller, llm, session_id, output_dir, callback=None, *, tool_factory=candidate_tool):
    if importlib.metadata.version("openhands-sdk") != "1.55.1":
        raise RuntimeError("Pilot lifecycle adapter requires OpenHands SDK 1.55.1")
    output_dir = Path(output_dir)
    agent = Agent(llm=llm, tools=[tool_factory(controller, session_id)],
                  include_default_tools=["FinishTool"], system_prompt=SYSTEM_PROMPT,
                  agent_context=None, mcp_config={}, condenser=None, critic=None,
                  tool_concurrency_limit=1)
    conversation = ControlledPilotConversation(
        agent, workspace=output_dir / "workspace", persistence_dir=None,
        callbacks=[callback] if callback else [], max_iteration_per_run=4,
        stuck_detection=False, visualizer=None, plugins=[], delete_on_close=False,
        profile_store_dir=output_dir / "empty-profiles")
    # SDK auto-adds a vision tool if any ambient saved vision profile exists.
    # Suppress discovery during initialization; reject every unexpected tool.
    with patch("openhands.sdk.agent.base.has_vision_profile_available", return_value=False):
        conversation.send_message(controller.task_prompt())
    actual_tools = set(conversation.agent.tools_map)
    if actual_tools != {"submit_candidate", "finish"}:
        conversation.close()
        raise RuntimeError("Unexpected pilot tool set")
    if (conversation.agent.mcp_config or conversation.agent.agent_context is not None
            or conversation._hook_processor is not None):
        conversation.close()
        raise RuntimeError("Unexpected pilot context or hook")
    return conversation


def run_session(controller, llm, session_id, output_dir, *, tool_factory=candidate_tool):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    events_path = output_dir / "events.jsonl"
    if events_path.exists():
        raise FileExistsError("Refusing to overwrite a pilot event log")

    def record(event):
        # Error event detail may originate from a provider; never persist it.
        value = {"type": type(event).__name__, "source": getattr(event, "source", None)}
        if type(event).__name__ == "ConversationErrorEvent":
            value["code"] = getattr(event, "code", None)
        else:
            for key in ("tool_name", "tool_call_id", "llm_response_id"):
                if getattr(event, key, None) is not None:
                    value[key] = getattr(event, key)
        with events_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(value, ensure_ascii=False, allow_nan=False) + "\n")

    conversation = None
    result = {"session_id": session_id, "status": "error", "model_error_type": None,
              "sdk_version": importlib.metadata.version("openhands-sdk")}
    try:
        conversation = create_conversation(controller, llm, session_id, output_dir, record,
                                           tool_factory=tool_factory)
        result["tools"] = sorted(conversation.agent.tools_map)
        conversation.run()
        result["conversation_status"] = str(conversation.state.execution_status)
        result["status"] = "completed" if result["conversation_status"].lower().endswith("finished") else "stopped"
    except Exception as error:
        result["model_error_type"] = type(error).__name__
        result.update(safe_error_metadata(error))
        if error.__cause__ is not None:
            result["cause_type"] = type(error.__cause__).__name__
    finally:
        if conversation is not None:
            conversation.close()
        result["controller"] = controller.summary()
        write_json(output_dir / "session-summary.json", result)
    return result
