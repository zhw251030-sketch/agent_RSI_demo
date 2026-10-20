"""Offline, public-task calibration of an exact plan-formatting intervention.

Candidate source is executed once, by the existing sandbox only.  The original
plan and its edge-whitespace normalization are then checked independently by the
unchanged host adapter, VAL, and public STRIPS replay.  This module does not
rewrite historical scores or run models.  Its source patch is researcher-defined
and has a much narrower contract than a general candidate repair operation.
"""

import ast
import copy
import hashlib
import json
import math
from pathlib import Path
import re

from . import planning, planning_diagnostics
from .executor import LIMITS
from .sandbox import run_candidate


VERSION = "planning-format-probe-v0.1"
AST_PROJECTION_VERSION = "python310-empty-type-params-v0.1"
ASCII_SPACE = " \t\r\n\f\v"
MAX_SOURCE_BYTES = 65536
MAX_ACTION_CHARACTERS = 4096
_TOKENS = re.compile(r"[A-Za-z][A-Za-z0-9_-]*(?:[ \t\r\n\f\v]+[A-Za-z][A-Za-z0-9_-]*)*")
_OLD_RETURN = ast.parse('return "(" + " " + " ".join([name] + list(params)) + ")"').body[0]
_NEW_RETURN_TEXT = 'return "(" + " ".join([name] + list(params)) + ")"'
_NEW_RETURN = ast.parse(_NEW_RETURN_TEXT).body[0]


def _sha(content):
    return hashlib.sha256(content).hexdigest()


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def normalize_plan(plan):
    """Remove ASCII edge whitespace, without changing token or internal bytes.

Only a bounded list of ordinary strings is retained.  Lexically malformed but
bounded plans remain available as ``original``; arbitrary objects and oversized
inputs are not copied into the JSON result.  Unknown operator/argument semantics
are left for the unchanged trusted task adapter to check.
"""
    result = {"status": "unknown", "reason": "plan_type_or_bound", "original": None,
              "normalized": None, "changed_indices": [], "token_preserved": None}
    if type(plan) is not list or len(plan) > planning.MAX_ACTIONS:
        return result
    if any(type(action) is not str or len(action) > MAX_ACTION_CHARACTERS for action in plan):
        return result
    try:
        for action in plan:
            action.encode("utf-8")
    except UnicodeError:
        result["reason"] = "plan_utf8"
        return result
    result["original"] = list(plan)
    normalized = []
    for action in plan:
        outer = action.strip(ASCII_SPACE)
        if not outer.startswith("(") or not outer.endswith(")"):
            result["reason"] = "action_shape"
            return result
        inner = outer[1:-1].strip(ASCII_SPACE)
        if not _TOKENS.fullmatch(inner):
            result["reason"] = "action_tokens"
            return result
        # The interior is retained verbatim: never split/rejoin, lowercase,
        # reorder arguments, or add/remove actions during normalization.
        normalized.append("(" + inner + ")")
    changed = [index for index, (before, after) in enumerate(zip(plan, normalized))
               if before != after]
    result.update(status="normalized" if changed else "unchanged",
                  reason="ascii_edge_whitespace_only" if changed else "already_normalized",
                  normalized=normalized, changed_indices=changed, token_preserved=True)
    return result


def _source_bytes(source):
    if type(source) is not str:
        raise ValueError("Candidate source must be a string")
    try:
        content = source.encode("utf-8")
    except UnicodeError as exc:
        raise ValueError("Candidate source must be UTF-8") from exc
    if not content or len(content) > MAX_SOURCE_BYTES:
        raise ValueError("Candidate source is empty or exceeds its bound")
    return content


def _transport_metadata(response):
    """Preserve counts, never arbitrary candidate output or exception messages."""
    result = {}
    statuses = {"completed", "timeout", "resource_limit", "candidate_process_error",
                "infrastructure_error", "invalid_request"}
    status = response.get("status")
    result["status"] = status if type(status) is str and status in statuses else "unknown"
    for key in ("stdout_bytes", "stderr_bytes"):
        value = response.get(key)
        if type(value) is int and value >= 0:
            result[key] = value
    value = response.get("returncode")
    if type(value) is int:
        result["returncode"] = value
    value = response.get("elapsed_seconds")
    if type(value) in (int, float) and math.isfinite(value) and value >= 0:
        result["elapsed_seconds"] = value
    return result


def _consistent(validation, replay):
    status, replay_status = validation.get("status"), replay.get("status")
    if status == "success":
        return replay_status == "valid"
    if status == "task_failure":
        return replay_status in ("precondition_failure", "goal_unsatisfied")
    if status == "invalid_output":
        return (replay_status == "invalid_output"
                and validation.get("error_kind") == replay.get("error_kind"))
    return False


def probe_plan(source, task_id, *, root, source_sha256):
    """Test normalization sufficiency for one new, isolated public-task plan.

Only the public prompt role is authorized. Source/hash and authorization errors
raise before candidate execution. Other task/validator/transport infrastructure
errors produce an explicit unknown result, never a task failure. The caller owns
persisting this complete result; this function writes no score journal.
"""
    content = _source_bytes(source)
    digest = _sha(content)
    if type(source_sha256) is not str or source_sha256 != digest:
        raise ValueError("Candidate source hash mismatch")
    result = {
        "version": VERSION, "status": "completed", "verdict": "unknown",
        "reason": "not_evaluated", "source_sha256": digest, "task_id": task_id,
        "task_binding": None, "normalization": None, "raw": None,
        "normalized": None, "transport": None,
        "executions": {"new_candidate_executions": 0, "sandbox_calls": 0,
                       "host_validations": 0, "diagnostic_replays": 0,
                       "val_calls": 0, "val_count_complete": True},
        "model_calls": 0, "changes_historical_scores": False,
    }
    counts = result["executions"]

    def infrastructure(reason):
        result.update(status="infrastructure_error", verdict="unknown", reason=reason)
        return result

    root = Path(root).resolve()
    try:
        public = planning_diagnostics.is_public_prompt(task_id, root)
    except (OSError, ValueError, KeyError, TypeError):
        return infrastructure("task_manifest_unavailable_or_invalid")
    if not public:
        raise PermissionError("Planning format probes require one public prompt task")
    try:
        manifest_path = root / "configs/tasks/planning-spanner-v0.1.json"
        manifest_bytes = manifest_path.read_bytes()
        manifest = json.loads(manifest_bytes)
        entry = next(item for item in manifest["tasks"] if item["id"] == task_id)
        request = planning.prepare_task(task_id, root)
        result["task_binding"] = {
            "pilot_role": "prompt", "manifest_sha256": _sha(manifest_bytes),
            "domain_sha256": manifest["domain"]["sha256"],
            "problem_sha256": entry["sha256"], "request_sha256": _sha(_canonical(request)),
        }
    except (OSError, ValueError, KeyError, TypeError, StopIteration):
        return infrastructure("task_data_unavailable_or_invalid")

    counts["new_candidate_executions"] += 1
    counts["sandbox_calls"] += 1
    try:
        response = run_candidate(source, request, deps_dir=root / ".task-runtime/python", **LIMITS)
    except (OSError, ValueError, KeyError, TypeError):
        return infrastructure("sandbox_call_failed")
    if type(response) is not dict:
        return infrastructure("sandbox_response_invalid")
    result["transport"] = _transport_metadata(response)
    transport_status = result["transport"]["status"]
    if transport_status != "completed":
        if transport_status in ("infrastructure_error", "invalid_request", "unknown"):
            return infrastructure("sandbox_unavailable")
        result.update(status="unavailable", reason="candidate_execution_unavailable")
        return result
    payload = response.get("result")
    if type(payload) is not dict or payload.get("status") not in ("ok", "success"):
        result.update(status="unavailable", reason="candidate_plan_unavailable")
        return result
    original = payload.get("plan")
    normalization = normalize_plan(original)
    result["normalization"] = normalization

    def validate(label, plan):
        observation = {"validation": None, "replay": None}
        result[label] = observation
        try:
            counts["host_validations"] += 1
            validation = planning.validate_plan(task_id, plan, root)
            observation["validation"] = validation
            if "validator" in validation:
                counts["val_calls"] += 1
            elif (validation.get("status") == "infrastructure_error"
                  and validation.get("error_kind") == "validator_io"):
                # Adapter cannot distinguish temporary-file failure from an
                # OSError after entering run_val. Do not fabricate an exact count.
                counts["val_count_complete"] = False
            counts["diagnostic_replays"] += 1
            replay = planning_diagnostics.diagnose_plan(task_id, plan, root)
            observation["replay"] = replay
        except (OSError, ValueError, KeyError, TypeError):
            counts["val_count_complete"] = False
            infrastructure(label + "_validation_unavailable")
            return False
        if validation.get("status") == "infrastructure_error":
            infrastructure(label + "_validator_infrastructure_error")
            return False
        if not _consistent(validation, replay):
            infrastructure(label + "_validator_replay_disagreement")
            return False
        return True

    if not validate("raw", original):
        return result
    if normalization["normalized"] is None:
        result["reason"] = "normalization_contract_unavailable"
        return result
    if not validate("normalized", normalization["normalized"]):
        return result
    if result["raw"]["validation"]["status"] == "success":
        result["reason"] = "original_already_valid_not_applicable"
    elif result["normalized"]["validation"]["status"] == "success":
        result.update(verdict="supported", reason="edge_normalization_sufficient_on_this_plan")
    else:
        result.update(verdict="contradicted", reason="edge_normalization_insufficient_on_this_plan")
    return result


def _ast_dump(node):
    """Match Python 3.10 for empty fields introduced by Python 3.12.

Only the copied node's field projection changes; the caller's AST and nonempty
type parameters remain intact. This keeps static contracts reproducible across
the server's 3.10 parser and the local 3.12 parser for the supported sources.
"""
    projected = copy.deepcopy(node)
    for child in ast.walk(projected):
        if ("type_params" in child._fields
                and type(getattr(child, "type_params", None)) is list
                and not child.type_params):
            child._fields = tuple(field for field in child._fields if field != "type_params")
    return ast.dump(projected, annotate_fields=True, include_attributes=False)


def build_format_patch(source):
    """Statically patch only the unique exact ``_fmt(name, params)`` artifact.

The formatter may be nested; its position and every other AST node remain
unchanged. No source is imported or evaluated. This is a researcher-specified
intervention, not a model-generated repair or proof of planning correctness.
"""
    result = {"status": "rejected", "reason": "source_contract", "source": None,
              "source_sha256": None, "original_sha256": None, "contract": None}
    try:
        content = _source_bytes(source)
        result["original_sha256"] = _sha(content)
        tree = ast.parse(source)
    except (ValueError, SyntaxError, RecursionError):
        return result
    functions = [node for node in ast.walk(tree)
                 if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "_fmt"]
    if len(functions) != 1 or type(functions[0]) is not ast.FunctionDef:
        result["reason"] = "formatter_not_unique_plain_function"
        return result
    function = functions[0]
    args = function.args
    if (function.decorator_list or function.returns is not None or function.type_comment
            or getattr(function, "type_params", [])
            or args.posonlyargs or args.kwonlyargs or args.defaults or args.kw_defaults
            or args.vararg is not None or args.kwarg is not None
            or [arg.arg for arg in args.args] != ["name", "params"]
            or any(arg.annotation is not None or arg.type_comment for arg in args.args)
            or len(function.body) != 1 or _ast_dump(function.body[0]) != _ast_dump(_OLD_RETURN)):
        result["reason"] = "formatter_ast_contract_mismatch"
        return result
    old_return = function.body[0]
    lines = content.splitlines(keepends=True)
    start = sum(map(len, lines[:old_return.lineno - 1])) + old_return.col_offset
    end = sum(map(len, lines[:old_return.end_lineno - 1])) + old_return.end_col_offset
    patched_bytes = content[:start] + _NEW_RETURN_TEXT.encode("utf-8") + content[end:]
    try:
        patched_source = patched_bytes.decode("utf-8")
        patched_tree = ast.parse(patched_source)
    except (UnicodeError, SyntaxError, RecursionError):
        result["reason"] = "patched_source_invalid"
        return result
    expected = copy.deepcopy(tree)
    expected_function = next(node for node in ast.walk(expected)
                             if isinstance(node, ast.FunctionDef) and node.name == "_fmt")
    expected_function.body[0] = copy.deepcopy(_NEW_RETURN)
    if _ast_dump(expected) != _ast_dump(patched_tree):
        result["reason"] = "unrelated_ast_changed"
        return result
    # A digest of the full tree with only the formatter return masked gives the
    # auditor a stable witness that every other AST node was preserved.
    expected_function.body[0] = ast.Pass()
    result.update(status="accepted", reason="exact_formatter_return_replaced",
                  source=patched_source, source_sha256=_sha(patched_bytes),
                  contract={"function": "_fmt", "other_ast_unchanged": True,
                            "ast_projection_version": AST_PROJECTION_VERSION,
                            "other_ast_sha256": _sha(_ast_dump(expected).encode("utf-8")),
                            "original_return_ast_sha256": _sha(_ast_dump(_OLD_RETURN).encode("utf-8")),
                            "patched_return_ast_sha256": _sha(_ast_dump(_NEW_RETURN).encode("utf-8")),
                            "original_byte_span": [start, end],
                            "researcher_defined": True})
    return result
