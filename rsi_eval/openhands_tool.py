"""OpenHands SDK 1.55.1 bridge to the controlled development evaluator.

This module defines one custom tool; it does not instantiate an Agent, load a
model credential, or alter Canvas. Use only this tool in a dedicated research
Agent's configured tool list. Existing general Canvas sessions stay unchanged.
The SDK automatically supplies its own conversation-control tools.
"""
import json
import math
import re
from typing import ClassVar, Literal

from openhands.sdk import Action, Observation, Tool, ToolDefinition
from openhands.sdk.tool import ToolExecutor, register_tool
from pydantic import Field, StrictInt, field_validator

from .executor import evaluate_candidate


class EvaluateCandidateAction(Action):
    """Source text and task identity only; filesystem configuration is trusted."""
    family: Literal["planning", "symbolic"]
    task_id: str = Field(min_length=1, max_length=96)
    source: str = Field(min_length=1, max_length=65536,
                        description="Complete Python source defining get_plan or equation.")
    n_params: StrictInt = Field(default=3, ge=0, le=16,
                                description="Number of symbolic fit parameters; ignored for planning.")
    candidate_id: str | None = Field(default=None, max_length=128)
    parent_id: str | None = Field(default=None, max_length=128)
    strategy_version: str = Field(default="unversioned", max_length=128)

    @field_validator("source")
    @classmethod
    def bounded_utf8_source(cls, value):
        if len(value.encode("utf-8")) > 65536:
            raise ValueError("Source exceeds 65536 UTF-8 bytes")
        return value

    @field_validator("candidate_id", "parent_id", "strategy_version")
    @classmethod
    def bounded_identifier(cls, value):
        if value is not None and not re.fullmatch(r"[a-zA-Z0-9_.:-]{1,128}", value):
            raise ValueError("Metadata must be a short identifier")
        return value


class EvaluateCandidateObservation(Observation):
    feedback: dict = Field(default_factory=dict, description="Sanitized development-only execution feedback.")


_DIAGNOSTICS = {
    "success": "Authorized development evaluation completed.",
    "task_failure": "VAL rejected the plan: an action precondition or final goal is unsatisfied.",
    "invalid_output": "Candidate output violates the task output contract.",
    "invalid_request": "The task identity, split, or request is not authorized by this development interface.",
    "candidate_error": "Candidate code failed; inspect the sanitized error kind and candidate line.",
    "candidate_process_error": "Candidate process exited without a valid structured result.",
    "timeout": "Candidate execution exceeded its time limit.",
    "resource_limit": "Candidate execution exceeded a resource limit.",
    "output_limit": "Candidate execution exceeded its output limit.",
    "infrastructure_error": "The execution environment could not provide a trusted task verdict.",
}


def _public_feedback(raw, action):
    """Whitelist fields and reconstruct diagnostics; never echo worker logs."""
    status = raw.get("status", "infrastructure_error")
    if status not in _DIAGNOSTICS:
        status = "infrastructure_error"
    public = {"status": status, "family": action.family, "task_id": action.task_id,
              "feedback_role": "development_only", "public_diagnostic": _DIAGNOSTICS[status]}
    for name in ("error_kind", "exception_type"):
        value = raw.get(name)
        if isinstance(value, str) and re.fullmatch(r"[a-zA-Z0-9_]{1,96}", value):
            public[name] = value
    for name in ("candidate_hash", "run_id"):
        value = raw.get(name)
        if isinstance(value, str) and re.fullmatch(r"[a-f0-9]{16,64}", value):
            public[name] = value
    for name in ("candidate_line", "first_invalid_action", "plan_length"):
        value = raw.get(name)
        if type(value) is int and 0 <= value <= 100000:
            public[name] = value
    elapsed = raw.get("elapsed_seconds")
    if type(elapsed) in (int, float) and math.isfinite(elapsed) and elapsed >= 0:
        public["elapsed_seconds"] = elapsed
    if action.family == "symbolic":
        public["metric_split"] = "train"
        public["metric_scope"] = "Training fit only; not a held-out or generalization result."
        metrics = raw.get("metrics")
        if isinstance(metrics, dict):
            public["metrics"] = {key: value for key, value in metrics.items()
                                 if key in {"mse", "nmse"} and type(value) in (int, float)
                                 and math.isfinite(value) and value >= 0}
    return public


class EvaluateCandidateExecutor(ToolExecutor[EvaluateCandidateAction, EvaluateCandidateObservation]):
    def __call__(self, action, conversation=None):
        # Re-validate even direct Python calls, not only SDK argument dispatch.
        action = EvaluateCandidateAction.model_validate(action.model_dump())
        raw = evaluate_candidate(action.family, action.task_id, action.source,
                                 n_params=action.n_params, candidate_id=action.candidate_id,
                                 parent_id=action.parent_id, strategy_version=action.strategy_version)
        feedback = _public_feedback(raw, action)
        text = json.dumps(feedback, ensure_ascii=False, allow_nan=False, sort_keys=True)
        return EvaluateCandidateObservation.from_text(
            text, is_error=feedback["status"] != "success", feedback=feedback)


class EvaluateCandidateTool(ToolDefinition[EvaluateCandidateAction, EvaluateCandidateObservation]):
    name: ClassVar[str] = "evaluate_candidate"

    @classmethod
    def create(cls, conv_state=None, **params):
        if params:
            raise ValueError("EvaluateCandidateTool accepts no initialization parameters")
        return [cls(
            action_type=EvaluateCandidateAction, observation_type=EvaluateCandidateObservation,
            executor=EvaluateCandidateExecutor(),
            description=("Evaluate Python candidate source on authorized development data in a restricted sandbox. "
                         "Planning accepts get_plan(objects, init, goal) on seed0 prompt/development Spanner tasks. "
                         "Symbolic accepts equation(*inputs, params) for oscillator1/2 training data. "
                         "No official test tasks, shell commands, file paths or root overrides are accepted. "
                         "Feedback is development-only and is not an RSI performance or held-out result."),
        )]


def research_agent_tools():
    """Register this tool and return the sole custom tool spec for a future Agent.

    Registration is local process state; it creates no conversation and makes no
    model request. SDK built-in conversation controls are outside this list.
    """
    register_tool("EvaluateCandidateTool", EvaluateCandidateTool)
    return [Tool(name="EvaluateCandidateTool")]
