#!/usr/bin/env python3
"""Prepare or explicitly execute the bounded two-session development pilot."""
import argparse
import contextlib
import hashlib
import importlib.metadata
import io
import json
import logging
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["OPENHANDS_SUPPRESS_BANNER"] = "1"
os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"
os.environ["DO_NOT_TRACK"] = "1"


def validate_config(config):
    sessions = config["sessions"]
    if [item.get("session_id") for item in sessions] != ["planning", "symbolic"]:
        raise ValueError("Pilot sessions must be exactly planning then symbolic")
    if any(item.get("family") != item["session_id"] for item in sessions):
        raise ValueError("Pilot session family mismatch")
    if any(item.get("max_generated_candidates") != 3 for item in sessions):
        raise ValueError("Pilot allows exactly three generated-candidate slots")
    maxima = {"max_requests": 8, "max_requests_per_session": 4, "max_output_tokens": 4096,
              "max_input_bytes": 98304, "max_reserved_tokens": 800000}
    budgets = config["budgets"]
    if set(budgets) != set(maxima) | {"max_cost_cny", "input_cny_per_million", "output_cny_per_million"}:
        raise ValueError("Unexpected pilot budget fields")
    if any(type(budgets[key]) is not int or not 0 < budgets[key] <= cap for key, cap in maxima.items()):
        raise ValueError("Pilot budget exceeds the authorized bound")
    if (type(budgets["max_cost_cny"]) not in (int, float) or not 0 < budgets["max_cost_cny"] <= 5
            or type(budgets["input_cny_per_million"]) not in (int, float)
            or type(budgets["output_cny_per_million"]) not in (int, float)
            or not budgets["input_cny_per_million"] >= 2.1 or not budgets["output_cny_per_million"] >= 8.4):
        raise ValueError("Invalid pilot cost cap or conservative price")
    return sessions, budgets


def source_provenance():
    paths = []
    for relative in ("rsi_eval", "scripts", "prompts/pilot", "configs", "fixtures"):
        paths.extend(p for p in (ROOT / relative).rglob("*") if p.is_file()
                     and p.suffix in {".py", ".json", ".md", ".txt"})
    hashes = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in sorted(paths)}
    revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
                              text=True, check=True).stdout.strip()
    return {"code_commit": revision, "source_sha256": hashes,
            "sdk_version": importlib.metadata.version("openhands-sdk")}


def resume_ledger_path(root, parent_run_id, new_run_id, config_sha256):
    """Validate a first-transport-failure recovery without resetting its budget."""
    if (not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", parent_run_id)
            or parent_run_id == new_run_id):
        raise ValueError("Recovery requires a distinct safe parent run identity")
    parent = root / "runs/agent-pilot" / parent_run_id
    ledger_path = parent / "budget-ledger.json"
    summary_path = parent / "summary.json"
    if (parent.is_symlink() or summary_path.is_symlink() or ledger_path.is_symlink()
            or not summary_path.is_file() or not ledger_path.is_file()):
        raise ValueError("Recovery needs an existing original run and budget ledger")
    previous = json.loads(summary_path.read_text(encoding="utf-8"))
    if (previous.get("run_id") != parent_run_id or previous.get("mode") != "execute"
            or previous.get("parent_run_id") is not None
            or previous.get("config_sha256") != config_sha256
            or previous.get("status") != "completed_with_stops"):
        raise ValueError("Recovery parent or protocol mismatch")
    sessions = previous.get("sessions", [])
    if (len(sessions) != 2 or {item.get("session_id") for item in sessions} != {"planning", "symbolic"}
            or any(item.get("controller", {}).get("generated_candidates") != 0 for item in sessions)):
        raise ValueError("Recovery is restricted to a pilot with no generated candidates")
    return ledger_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "configs/pilots/development-v0.1.json")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--resume-from", help="Explicit one-time recovery using the failed run's existing budget ledger.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prepare-only", action="store_true")
    mode.add_argument("--execute", action="store_true")
    parser.add_argument("--auth-file", help="Existing server-local credential file; never a secret value.")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", args.run_id):
        parser.error("run-id must be a short safe identifier")
    if args.resume_from and not args.execute:
        parser.error("resume-from requires explicit execute mode")
    output = ROOT / "runs/agent-pilot" / args.run_id
    output.mkdir(parents=True, exist_ok=False)
    report = {"run_id": args.run_id, "mode": "execute" if args.execute else "prepare_only",
              "status": "error", "sessions": [], "sealed_test_evaluations": 0}
    if args.resume_from:
        report["parent_run_id"] = args.resume_from
    ledger = None
    logging.disable(logging.CRITICAL)
    try:
        # Suppress third-party exception diagnostics that may contain request data.
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            from rsi_eval.pilot_controller import PilotController
            from rsi_eval.pilot_budget import BudgetLedger
            from rsi_eval.pilot_agent import BoundedPilotLLM, run_session, write_json
            from configure_minimax import CONFIG, auth_path, read_key
            config_bytes = args.config.read_bytes()
            config = json.loads(config_bytes)
            sessions, budgets = validate_config(config)
            report["config_sha256"] = hashlib.sha256(config_bytes).hexdigest()
            report.update(source_provenance())
            write_json(output / "config.json", config)
            ledger_path = (resume_ledger_path(ROOT, args.resume_from, args.run_id, report["config_sha256"])
                           if args.resume_from else output / "budget-ledger.json")
            report["budget_ledger"] = ledger_path.relative_to(ROOT).as_posix()
            ledger = BudgetLedger(ledger_path, **budgets)
            controllers = []
            for item in sessions:
                session_dir = output / item["session_id"]
                controller = PilotController(ROOT, item, session_dir, max_candidates=3)
                baseline = controller.baseline()
                session_dir.mkdir(parents=True, exist_ok=True)
                (session_dir / "task-prompt.txt").write_text(controller.task_prompt(), encoding="utf-8")
                controllers.append((item, session_dir, controller))
                report["sessions"].append({"session_id": item["session_id"], "baseline": baseline})
            if any(controller.halted for _, _, controller in controllers):
                raise RuntimeError("Pilot baseline infrastructure failed; no model request authorized")
            model_config_bytes = CONFIG.read_bytes()
            model_config = json.loads(model_config_bytes)
            if any(key in model_config for key in ("api_key", "extra_headers", "aws_secret_access_key")):
                raise ValueError("Public model configuration contains a credential field")
            report["model_config_sha256"] = hashlib.sha256(model_config_bytes).hexdigest()
            report["model_config"] = dict(model_config)
            model_config.update(max_output_tokens=budgets["max_output_tokens"],
                                num_retries=0, stream=False, caching_prompt=False,
                                api_mode="chat", fallback_strategy=None, log_completions=False)
            report["effective_model_config"] = dict(model_config)
            if args.execute:
                if args.resume_from:
                    ledger.resume_after_transport_failure()
                # Read the user's existing key only here, after preparation succeeded.
                model_config["api_key"] = read_key(auth_path(args.auth_file))
                report["sessions"] = []
                for item, session_dir, controller in controllers:
                    if ledger.summary()["halted"]:
                        report["sessions"].append({"session_id": item["session_id"], "status": "not_started_budget_halted",
                                                   "controller": controller.summary()})
                        continue
                    llm = BoundedPilotLLM(**model_config).bind_pilot(
                        ledger, item["session_id"], session_dir / "requests")
                    report["sessions"].append(run_session(controller, llm, item["session_id"], session_dir))
            report["budget"] = ledger.summary()
            report["status"] = ("completed_with_stops" if args.execute and any(
                item.get("status") != "completed" for item in report["sessions"]) else "completed")
    except Exception as error:
        report["error_type"] = type(error).__name__
    if ledger is not None:
        report["budget"] = ledger.summary()
    (output / "summary.json").write_text(json.dumps(report, ensure_ascii=False, allow_nan=False,
                                                   indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "summary_file": str(output / "summary.json"),
                      "mode": report["mode"], "session_count": len(report["sessions"]),
                      "error_type": report.get("error_type"), "budget": report.get("budget")},
                     ensure_ascii=False, allow_nan=False, indent=2))
    return 0 if report["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
