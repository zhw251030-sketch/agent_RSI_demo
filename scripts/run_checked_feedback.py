#!/usr/bin/env python3
"""Prepare or execute the frozen four-session diagnostic development comparison.

Each invocation owns a new directory and a new shared ledger. There is no
resume/recovery mode, implicit retry, or replacement session after a failure.
"""
import argparse
import contextlib
import copy
import hashlib
import importlib.metadata
import io
import json
import logging
import math
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "configs/pilots/checked-feedback-v0.1.json"
sys.path.insert(0, str(ROOT))
os.environ["OPENHANDS_SUPPRESS_BANNER"] = "1"
os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"
os.environ["DO_NOT_TRACK"] = "1"

ORDER = (("planning", "hidden"), ("symbolic", "checked"),
         ("planning", "checked"), ("symbolic", "hidden"))
POLICY_FILE = "prompts/checked/policy.md"


def validate_config(config):
    """Reject changes to the four conditions or expansion of authorized budgets."""
    if not isinstance(config, dict) or config.get("schema_version") != "0.1":
        raise ValueError("Unsupported comparison schema")
    if (config.get("base_config") != "configs/pilots/development-v0.1.json"
            or config.get("policy_file") != POLICY_FILE
            or config.get("protocol") != "docs/protocols/2026-10-20-checked-feedback.md"
            or type(config.get("source_limit_bytes")) is not int or config["source_limit_bytes"] != 16384
            or any(config.get(key) is not False for key in ("strategy_updated", "checks_gate_execution",
                        "checks_change_selection", "automatic_recovery"))):
        raise ValueError("Comparison base configuration or policies changed")
    expected = [{"family": family, "condition": condition, "session_id": family + "_" + condition}
                for family, condition in ORDER]
    if config.get("order") != expected:
        raise ValueError("Comparison requires exactly the four frozen conditions in order")
    maxima = {"max_requests": 16, "max_requests_per_session": 4,
              "max_output_tokens": 4096, "max_input_bytes": 98304,
              "max_reserved_tokens": 3000000}
    budgets = config.get("budgets")
    if (not isinstance(budgets, dict) or set(budgets) != set(maxima) |
            {"max_cost_cny", "input_cny_per_million", "output_cny_per_million"}):
        raise ValueError("Unexpected comparison budget fields")
    for key, cap in maxima.items():
        if type(budgets[key]) is not int or not 0 < budgets[key] <= cap:
            raise ValueError("Comparison budget exceeds the authorized bound")
    for key in ("max_cost_cny", "input_cny_per_million", "output_cny_per_million"):
        value = budgets[key]
        if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
            raise ValueError("Comparison cost limits and prices must be finite and positive")
    if (budgets["max_cost_cny"] > 10 or budgets["input_cny_per_million"] < 2.1
            or budgets["output_cny_per_million"] < 8.4):
        raise ValueError("Comparison cost cap or conservative price is invalid")
    return copy.deepcopy(expected), dict(budgets)


def source_provenance():
    """Hash the trusted source and all prompt policies without importing the SDK."""
    paths = []
    for relative in ("rsi_eval", "scripts", "prompts", "configs", "fixtures"):
        paths.extend(path for path in (ROOT / relative).rglob("*") if path.is_file()
                     and path.suffix in {".py", ".json", ".md", ".txt"})
    protocol = ROOT / "docs/protocols/2026-10-20-checked-feedback.md"
    if protocol.is_file():
        paths.append(protocol)
    hashes = {path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
              for path in sorted(set(paths))}
    revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
                              text=True, check=True).stdout.strip()
    return {"code_commit": revision, "source_sha256": hashes,
            "sdk_version": importlib.metadata.version("openhands-sdk")}


def _write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2) + "\n",
                    encoding="utf-8")


def _asset(relative, prefix):
    root = ROOT.resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root / prefix) or not path.is_file():
        raise ValueError("Trusted comparison asset is outside its authorized directory")
    return path


def _base_sessions(base):
    from scripts.run_agent_pilot import validate_config as validate_base_config
    sessions, _ = validate_base_config(base)
    if base.get("model_configuration") != "configs/models/minimax-m3.json":
        raise ValueError("Comparison requires the existing MiniMax model configuration")
    result = {}
    for session in sessions:
        source = _asset(session["initial_candidate"], "fixtures").read_bytes()
        if hashlib.sha256(source).hexdigest() != session["initial_candidate_sha256"]:
            raise ValueError("Comparison initial candidate integrity mismatch")
        result[session["family"]] = copy.deepcopy(session)
    return result


def _model_configuration(path, budgets):
    """Validate the public model settings before copying any of them to reports."""
    raw = path.read_bytes()
    config = json.loads(raw)
    required = {
        "model": "anthropic/MiniMax-M3", "model_canonical_name": "minimax/MiniMax-M3",
        "base_url": "https://api.minimax.cn/anthropic", "api_mode": "chat",
        "native_tool_calling": True, "force_string_serializer": False,
        "reasoning_effort": "none",
        "capability_overrides": {"supports_reasoning_effort": False, "supports_sampling_params": True},
        "litellm_extra_body": {"thinking": {"type": "disabled"}},
        "temperature": 1.0, "max_output_tokens": 4096, "num_retries": 0,
        "timeout": 60, "caching_prompt": False,
    }
    if config != required:
        raise ValueError("Public model configuration differs from the frozen comparison model")
    effective = dict(config)
    effective.update(max_output_tokens=budgets["max_output_tokens"], num_retries=0,
                     stream=False, caching_prompt=False, api_mode="chat",
                     fallback_strategy=None, log_completions=False)
    return hashlib.sha256(raw).hexdigest(), config, effective


def _new_output(run_id):
    root = ROOT.resolve()
    parent = root / "runs/checked-feedback"
    if (root / "runs").is_symlink() or parent.is_symlink() or not parent.resolve().is_relative_to(root):
        raise ValueError("Comparison output must remain within this project")
    output = parent / run_id
    output.mkdir(parents=True, exist_ok=False)
    return output


def _run_prepared(controllers, report, ledger, model_config, auth_file):
    from rsi_eval.checked_agent import StatePacketLLM, checked_candidate_tool, run_session
    from scripts.configure_minimax import auth_path, read_key
    # All four baseline evaluations, initial digest checks, and prompt writes have
    # completed before credential resolution or credential access can occur.
    model_config = dict(model_config)
    model_config["api_key"] = read_key(auth_path(auth_file))
    stop_reason = None
    for controller, session_dir, entry in controllers:
        if stop_reason is not None:
            entry.update(status="not_started_after_stop", stop_reason=stop_reason,
                         controller=controller.summary())
            _write_json(session_dir / "session-summary.json", entry)
            continue
        try:
            if ledger.summary()["halted"]:
                stop_reason = "budget_halted"
                entry.update(status="not_started_after_stop", stop_reason=stop_reason,
                             controller=controller.summary())
            else:
                llm = StatePacketLLM(**model_config).bind_controller(controller).bind_pilot(
                    ledger, entry["session_id"], session_dir / "requests")
                result = run_session(controller, llm, entry["session_id"], session_dir,
                                     tool_factory=checked_candidate_tool)
                if (not isinstance(result, dict) or result.get("session_id") != entry["session_id"]
                        or result.get("status") not in {"completed", "stopped", "error"}):
                    raise ValueError("Invalid session result contract")
                entry.update(result)
                if result["status"] == "error" or result.get("model_error_type"):
                    stop_reason = "session_error"
                elif controller.halted or result.get("controller", {}).get("halted"):
                    stop_reason = "controller_infrastructure_error"
                budget = ledger.summary()
                if budget["halted"] or budget["usage_unknown_count"] or budget["reserved_count"]:
                    stop_reason = "budget_halted"
        except Exception as error:
            entry.update(status="error", model_error_type=type(error).__name__,
                         controller=controller.summary())
            stop_reason = "session_error"
        _write_json(session_dir / "session-summary.json", entry)
    if stop_reason:
        report["stop_reason"] = stop_reason
    # A normal SDK iteration stop is retained as stopped and never renamed a
    # successful completion. It alone does not abort the later conditions.
    report["status"] = ("completed_with_stops" if stop_reason or any(
        entry["status"] != "completed" for _, _, entry in controllers) else "completed")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--run-id", required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prepare-only", action="store_true")
    mode.add_argument("--execute", action="store_true")
    parser.add_argument("--auth-file", help="Existing server-local credential file; never a secret value.")
    args = parser.parse_args(argv)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", args.run_id):
        parser.error("run-id must be a short safe identifier")
    report = {"run_id": args.run_id, "mode": "execute" if args.execute else "prepare_only",
              "status": "error", "sessions": [], "sealed_test_evaluations": 0,
              "strategy_updated": False, "automatic_recovery_enabled": False}
    output = None
    ledger = None
    previous_logging_disable = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        # Third-party stdout/stderr and exception bodies can contain provider
        # details. Only fixed metadata and exception class names leave here.
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            output = _new_output(args.run_id)
            config_bytes = args.config.read_bytes()
            config = json.loads(config_bytes)
            order, budgets = validate_config(config)
            report["sessions"] = [dict(condition, status="not_started") for condition in order]
            base_bytes = _asset(config["base_config"], "configs").read_bytes()
            base = json.loads(base_bytes)
            sessions = _base_sessions(base)
            from rsi_eval.checked_controller import CheckedController
            from rsi_eval.pilot_budget import BudgetLedger
            from scripts.configure_minimax import CONFIG
            model_path = _asset(base["model_configuration"], "configs")
            if Path(CONFIG).resolve() != model_path:
                raise ValueError("Environment model configuration override is not authorized")
            model_hash, public_model, effective_model = _model_configuration(model_path, budgets)
            report.update(config_sha256=hashlib.sha256(config_bytes).hexdigest(),
                          base_config_sha256=hashlib.sha256(base_bytes).hexdigest(),
                          model_config_sha256=model_hash, model_config=public_model,
                          effective_model_config=effective_model)
            report.update(source_provenance())
            if report["sdk_version"] != "1.55.1":
                raise RuntimeError("Comparison requires OpenHands SDK 1.55.1")
            _write_json(output / "config.json", config)
            _write_json(output / "base-config.json", base)
            ledger_path = output / "budget-ledger.json"
            report["budget_ledger"] = ledger_path.relative_to(ROOT.resolve()).as_posix()
            ledger = BudgetLedger(ledger_path, session_ids=[item["session_id"] for item in order], **budgets)
            controllers = []
            for condition, entry in zip(order, report["sessions"]):
                session = copy.deepcopy(sessions[condition["family"]])
                policy_bytes = _asset(config["policy_file"], "prompts/checked").read_bytes()
                session_dir = output / condition["session_id"]
                controller = CheckedController(ROOT, session, session_dir, condition=condition["condition"],
                        session_id=args.run_id+":"+condition["session_id"], policy_text=policy_bytes.decode("utf-8"))
                baseline = controller.baseline()
                if baseline.get("source_sha256") != session["initial_candidate_sha256"]:
                    raise ValueError("Baseline does not match the fixed initial source")
                prompt_bytes = controller.task_prompt().encode("utf-8")
                (session_dir / "task-prompt.txt").write_bytes(prompt_bytes)
                digest = controller.initial_observation_digest()
                if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
                    raise ValueError("Initial observation digest is invalid")
                entry.update(status="prepared", baseline=baseline,
                             initial_source_sha256=session["initial_candidate_sha256"],
                             initial_observation_sha256=digest,
                             task_prompt_sha256=hashlib.sha256(prompt_bytes).hexdigest(),
                             policy_sha256=hashlib.sha256(policy_bytes).hexdigest())
                controllers.append((controller, session_dir, entry))
            if any(controller.halted for controller, _, _ in controllers):
                raise RuntimeError("Baseline infrastructure failure")
            for family in ("planning", "symbolic"):
                if len({entry["initial_observation_sha256"] for entry in report["sessions"]
                        if entry["family"] == family}) != 1:
                    raise ValueError("Initial observations differ across comparison arms")
            report["initial_observations_match"] = True
            if args.execute:
                _run_prepared(controllers, report, ledger, effective_model, args.auth_file)
            else:
                report["status"] = "prepared"
    except Exception as error:
        report["error_type"] = type(error).__name__
        for entry in report["sessions"]:
            if entry["status"] in {"not_started", "prepared"}:
                entry.update(status="not_started_after_stop", stop_reason="preparation_error")
    finally:
        logging.disable(previous_logging_disable)
    if ledger is not None:
        try:
            report["budget"] = ledger.summary()
        except Exception as error:
            report.update(status="error", error_type=type(error).__name__)
    if output is not None:
        _write_json(output / "summary.json", report)
    print(json.dumps({"status": report["status"],
                      "summary_file": str(output / "summary.json") if output else None,
                      "mode": report["mode"], "session_count": len(report["sessions"]),
                      "error_type": report.get("error_type"), "budget": report.get("budget")},
                     ensure_ascii=False, allow_nan=False, indent=2))
    return 0 if report["status"] in {"prepared", "completed"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
