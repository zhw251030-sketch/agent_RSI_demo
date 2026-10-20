"""Bounded host-side STRIPS replay observations for public prompt tasks only.

This module never runs candidate code or VAL and does not decide task scores.
The caller must compare replay validity with trusted VAL's semantic verdict.
Task-data errors propagate so they cannot be mistaken for candidate failures.
"""

import json
from pathlib import Path
import re

from rsi_eval import planning


MAX_FACTS = 20
MAX_ACTION_CHARACTERS = 4096
_ACTION = re.compile(r"\s*\([a-zA-Z][a-zA-Z0-9_-]*(?:\s+[a-zA-Z][a-zA-Z0-9_-]*)*\)\s*")


def is_public_prompt(task_id, root):
    """Check an exact, unique prompt manifest entry without loading task data.

    Unknown, ambiguous and non-public IDs return False. Manifest IO/schema
    errors propagate to the caller as infrastructure errors.
    """
    if type(task_id) is not str:
        return False
    path = Path(root).resolve() / "configs/tasks/planning-spanner-v0.1.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    tasks = manifest["tasks"]
    if type(tasks) is not list or any(type(entry) is not dict for entry in tasks):
        raise ValueError("Invalid planning task manifest")
    matches = [entry for entry in tasks if entry.get("id") == task_id]
    return len(matches) == 1 and matches[0].get("pilot_role") == "prompt"


def _empty_result(plan_length):
    return {
        "status": "invalid_output",
        "error_kind": None,
        "executed_actions": 0,
        "plan_length": plan_length,
        "first_failed_action": None,
        "missing_preconditions": [],
        "missing_preconditions_truncated": False,
        "unsatisfied_goals": [],
        "unsatisfied_goals_truncated": False,
    }


def _record_facts(result, field, facts):
    ordered = sorted(facts)
    result[field] = [list(atom) for atom in ordered[:MAX_FACTS]]
    result[field + "_truncated"] = len(ordered) > MAX_FACTS


def _ground(atom, bindings):
    return (atom[0], *(bindings[arg] for arg in atom[1:]))


def diagnose_plan(task_id, plan, root):
    """Return deterministic bounded observations after validating the whole plan.

    Non-public IDs raise PermissionError before any domain/problem file reads.
    ``first_failed_action.index`` is zero-based. Its ``action`` is normalized
    only for semantic failures; malformed candidate strings are never echoed.
    Unsatisfied goals describe the state after the successfully executed prefix.
    Invalid output has no replayed state, so both fact lists are empty.
    """
    if not is_public_prompt(task_id, root):
        raise PermissionError("Planning diagnostics require one public prompt task")
    domain, task, _ = planning._load_task(task_id, root)
    result = _empty_result(len(plan) if type(plan) is list else None)
    if type(plan) is not list:
        result["error_kind"] = "output_not_plan"
        return result
    if len(plan) > planning.MAX_ACTIONS:
        result["error_kind"] = "plan_too_long"
        return result

    normalized = []
    for index, action in enumerate(plan):
        def invalid(kind):
            result["error_kind"] = kind
            result["first_failed_action"] = {"index": index, "action": None}
            return result

        if (type(action) is not str or len(action) > MAX_ACTION_CHARACTERS
                or not _ACTION.fullmatch(action)):
            return invalid("operator_syntax")
        tokens = action.strip()[1:-1].lower().split()
        name, *args = tokens
        if name not in domain["operators"]:
            return invalid("unknown_operator")
        operator = domain["operators"][name]
        parameters = operator["parameters"]
        if len(args) != len(parameters):
            return invalid("operator_arity")
        for arg, required in zip(args, parameters.values()):
            if arg not in task["objects"]:
                return invalid("unknown_object")
            if not planning._subtype(task["objects"][arg], required, domain["types"]):
                return invalid("object_type")
        normalized.append(("(" + " ".join(tokens) + ")", operator, dict(zip(parameters, args))))

    state = set(task["init"])
    for index, (action, operator, bindings) in enumerate(normalized):
        missing = {_ground(atom, bindings) for _, atom in operator["preconditions"]} - state
        if missing:
            result["status"] = "precondition_failure"
            result["first_failed_action"] = {"index": index, "action": action}
            _record_facts(result, "missing_preconditions", missing)
            _record_facts(result, "unsatisfied_goals", task["goal"] - state)
            return result
        # STRIPS effects are simultaneous: remove delete facts, then add facts.
        delete = {_ground(atom, bindings) for negative, atom in operator["effects"] if negative}
        add = {_ground(atom, bindings) for negative, atom in operator["effects"] if not negative}
        state.difference_update(delete)
        state.update(add)
        result["executed_actions"] += 1

    remaining = task["goal"] - state
    result["status"] = "goal_unsatisfied" if remaining else "valid"
    _record_facts(result, "unsatisfied_goals", remaining)
    return result
