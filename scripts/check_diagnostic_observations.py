#!/usr/bin/env python3
"""Replay fixed pilot artifacts with narrowly scoped human diagnostic interventions.

No model or SDK is imported. Candidate code runs exclusively through the existing
sandbox executor. These interventions test specific program errors; their scores
are not Agent improvements, strategy effects, or held-out evaluation results.
"""
import argparse
import ast
from collections import Counter
import contextlib
from datetime import datetime, timezone
import difflib
import hashlib
import io
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from rsi_eval.executor import evaluate_candidate

PILOT = Path("artifacts/pilot/2026-10-20")
PLANNING_TASKS = tuple("spannerlearning/seed0/problem%d" % i for i in range(10))
PUBLIC_TASKS = frozenset(PLANNING_TASKS[:2])
HELPERS = {"planning-002": ("_man_location", "_carried_spanner"),
           "planning-003": ("_man_at", "_carrying")}
# Fixed bytes from the already reviewed pilot artifacts/acceptance fixture.
PINNED_SOURCES = {
    "planning-002": "0e78844ff86947136a96ab63bbfff709de8605fe59c7bdeed26145256b62ea78",
    "planning-003": "14256dd1c5566584839bef13f8749e07544bb411350c25607624991bc40d703b",
    "symbolic-001": "78591b5b201f15ee390a724bdb1b0302712bc88ff62a9479bbbe898dd4bd3018",
    "symbolic-002": "c0389afc4e793d01812c7b84e5604a415cd77fd5f2b95f249e6ab097646feebf",
    "symbolic-003": "f3c893f0989dc6a72029687090cd1e3c444eca24e8643740a0a62dddd21d801e",
    "planning-sanity": "1a8042aa6d82e918bce0ff824e75d65dadc20295c4ac223c57a4f651c74b9dac",
}
SCOPE = ("Human-authored offline diagnostic replay on the existing development tasks; "
         "not an Agent improvement, strategy comparison, or generalization result.")


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _repair_helper(source, name, predicate):
    """Replace one exact helper segment, preserving every other source byte."""
    tree = ast.parse(source)
    matches = [node for node in ast.walk(tree)
               if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name]
    if len(matches) != 1 or matches[0] not in tree.body:
        raise ValueError("Expected exactly one top-level named helper")
    node = matches[0]
    lines = source.splitlines(keepends=True)
    segment = "".join(lines[node.lineno - 1:node.end_lineno])
    newline = "\r\n" if "\r\n" in segment else "\n"
    expected = (f"def {name}(state, man):\n"
                "    for f in state:\n"
                f'        if len(f) == 3 and f[0] == "{predicate}" and f[2] == man:\n'
                "            return f[1]\n"
                "    return None\n").replace("\n", newline)
    if segment != expected or source.count(expected) != 1:
        raise ValueError("Expected helper segment must match exactly once")
    if segment.count("f[2] == man") != 1 or segment.count("return f[1]") != 1:
        raise ValueError("Expected helper index expressions must each match exactly once")
    repaired = segment.replace("f[2] == man", "f[1] == man").replace("return f[1]", "return f[2]")
    return "".join(lines[:node.lineno - 1]) + repaired + "".join(lines[node.end_lineno:])


def build_planning_variants(parent_name, source):
    """Build original/at-only/at+carrying snapshots without executing source."""
    if parent_name not in HELPERS or not isinstance(source, str):
        raise ValueError("Unsupported diagnostic parent")
    at_helper, carrying_helper = HELPERS[parent_name]
    at_fixed = _repair_helper(source, at_helper, "at")
    both_fixed = _repair_helper(at_fixed, carrying_helper, "carrying")
    parent_hash = _sha(source.encode("utf-8"))
    result = []
    descriptions = ["No changes; original pilot candidate replay.",
                    f"Only {at_helper}: match man at argument 1 and return location at argument 2.",
                    f"Only {at_helper} and {carrying_helper}: match man at argument 1 and return argument 2."]
    for variant, text, description in zip(("original", "at_only", "at_and_carrying"),
                                         (source, at_fixed, both_fixed), descriptions):
        candidate_id = parent_name + "-" + variant
        delta = "".join(difflib.unified_diff(source.splitlines(keepends=True), text.splitlines(keepends=True),
                                            fromfile=parent_name + ".py", tofile=candidate_id + ".py"))
        result.append({"candidate_id": candidate_id, "variant": variant, "family": "planning",
                       "parent_id": parent_name, "parent_source_sha256": parent_hash,
                       "source_sha256": _sha(text.encode("utf-8")), "source": text,
                       "derivative": ("unchanged_model_candidate" if variant == "original" else
                                      "human_authored_diagnostic_intervention"),
                       "patch_description": description, "patch": delta,
                       "parent_file": (PILOT / (parent_name + ".py")).as_posix()})
    return result


def _safe_path(root, relative):
    path = root
    for part in Path(relative).parts:
        path = path / part
        if path.is_symlink():
            raise ValueError("Symlink refused in diagnostic probe path")
    if not path.resolve().is_relative_to(root):
        raise ValueError("Diagnostic probe path is outside project")
    return path


def _valid_run_id(value):
    return (isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", value)
            and not re.fullmatch(r"CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9]", value, re.IGNORECASE))


def _write_json(path, value):
    path.write_bytes((json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2) + "\n").encode("utf-8"))


def _load_candidates(root):
    candidates, original_hashes = [], {}
    for stem in PINNED_SOURCES:
        relative = (Path("fixtures/planning/collect_then_tighten.py") if stem == "planning-sanity"
                    else PILOT / (stem + ".py"))
        raw = _safe_path(root, relative).read_bytes()
        digest = _sha(raw)
        if digest != PINNED_SOURCES[stem]:
            raise ValueError("Pinned diagnostic source integrity mismatch")
        original_hashes[relative.as_posix()] = digest
        source = raw.decode("utf-8")
        if stem in HELPERS:
            candidates.extend(build_planning_variants(stem, source))
        else:
            sanity = stem == "planning-sanity"
            candidates.append({"candidate_id": stem, "variant": "sanity" if sanity else "original",
                               "family": "planning" if sanity else "symbolic", "source": source,
                               "source_sha256": digest, "parent_source_sha256": digest,
                               "parent_id": stem, "parent_file": relative.as_posix(),
                               "derivative": ("existing_hand_authored_sanity_fixture" if sanity else
                                              "unchanged_model_candidate"),
                               "patch_description": "No changes; fixed existing source replay.", "patch": "",
                               **({} if sanity else {"n_params": int(stem[-3:]) + 1})})
    # Planning interventions, existing hand-authored sanity, then symbolic replay.
    candidates.sort(key=lambda row: row["family"] != "planning")
    return candidates, original_hashes


def _compact_observations(result):
    diagnostics = result.get("diagnostics", {})
    result_summary = {key: result[key] for key in ("task_id", "status", "error_kind", "candidate_line",
                                                 "exception_type", "plan_length", "metrics") if key in result}
    if "trace" in diagnostics:
        trace = diagnostics["trace"]
        # Include function summaries and truncation flags; detailed line hits stay in feedback.
        result_summary["trace"] = {key: trace[key] for key in (
            "status", "reason", "events_seen", "event_limit", "truncated", "interrupted",
            "functions", "provenance", "interpretation_limits", "none_return_caveat") if key in trace}
    if "plan_replay" in diagnostics:
        result_summary["plan_replay"] = diagnostics["plan_replay"]
    if "residuals" in diagnostics:
        result_summary["residuals"] = diagnostics["residuals"]
    return result_summary


def _diagnostic_issue(result, candidate, task_id):
    """Check replay provenance without changing the executor's original score."""
    expected = candidate["family"] == "symbolic" or task_id in PUBLIC_TASKS
    diagnostic = result.get("diagnostics")
    if not expected:
        return "nonpublic_diagnostics" if diagnostic is not None else None
    if diagnostic is None:
        return "missing_diagnostics" if result["status"] in {"success", "task_failure"} else None
    scope = "train" if candidate["family"] == "symbolic" else "public_prompt"
    if (not isinstance(diagnostic, dict) or diagnostic.get("scope") != scope
            or diagnostic.get("task_id") != task_id
            or diagnostic.get("candidate_sha256") != candidate["source_sha256"]
            or diagnostic.get("version") != "diagnostics-v0.1"):
        return "diagnostic_provenance"
    if candidate["family"] == "symbolic" and result["status"] == "success":
        if diagnostic.get("residuals", {}).get("status") != "ok":
            return "residual_diagnostic_error"
    if candidate["family"] == "planning" and result["status"] in {"success", "task_failure"}:
        if not isinstance(diagnostic.get("plan_replay"), dict) or not isinstance(diagnostic.get("trace"), dict):
            return "missing_planning_diagnostics"
    return None


def _evaluate(root, candidate, task_id, diagnostics):
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            result = evaluate_candidate(candidate["family"], task_id, candidate["source"], root=root,
                                        candidate_id=candidate["candidate_id"], parent_id=candidate["parent_id"],
                                        n_params=candidate.get("n_params", 0), diagnostics=diagnostics,
                                        strategy_version="human-diagnostic-probe-v0.1")
        if not isinstance(result, dict) or not isinstance(result.get("status"), str):
            raise TypeError("Invalid executor feedback")
        # Copy only host feedback, not candidate stdout/stderr or arbitrary worker payloads.
        return json.loads(json.dumps(result, allow_nan=False))
    except Exception as error:
        return {"family": candidate["family"], "task_id": task_id,
                "candidate_id": candidate["candidate_id"], "candidate_hash": candidate["source_sha256"],
                "status": "infrastructure_error", "error_kind": "executor_exception",
                "exception_type": type(error).__name__, "executions": [],
                "model_calls": 0, "sealed_tasks_executed": 0}


def run_probe(root, run_id):
    """Own a new output directory and retain every fixed evaluation, including errors."""
    if not _valid_run_id(run_id):
        raise ValueError("Invalid diagnostic run identifier")
    root = Path(root).resolve()
    output = _safe_path(root, Path("runs/diagnostic-checks") / run_id)
    output.mkdir(parents=True, exist_ok=False)
    report = {"schema_version": "0.1", "run_id": run_id, "status": "error", "scope": SCOPE,
              "started_at_utc": datetime.now(timezone.utc).isoformat(), "model_calls": 0,
              "sealed_tasks_executed": 0, "strategy_updated": False,
              "evaluation_counts": {"planning": 0, "symbolic": 0},
              "execution_counts": {"planning": 0, "symbolic": 0},
              "infrastructure_error_count": 0, "diagnostic_error_count": 0, "sanity_passed": False,
              "planning": [], "symbolic": [], "summary_file": str(output / "summary.json")}
    try:
        candidates, original_hashes = _load_candidates(root)
        (output / "sources").mkdir()
        (output / "patches").mkdir()
        (output / "feedback").mkdir()
        manifest = {"schema_version": "0.1", "scope": SCOPE, "model_calls": 0, "sealed_tasks_executed": 0,
                    "planning_tasks": list(PLANNING_TASKS), "public_diagnostic_tasks": sorted(PUBLIC_TASKS),
                    "symbolic_tasks": [{"task_id": "oscillator1", "split": "train"}],
                    "original_source_sha256": original_hashes, "candidates": []}
        for candidate in candidates:
            source_file = "sources/" + candidate["candidate_id"] + ".py"
            patch_file = "patches/" + candidate["candidate_id"] + ".diff"
            (output / source_file).write_bytes(candidate["source"].encode("utf-8"))
            (output / patch_file).write_bytes(candidate["patch"].encode("utf-8"))
            manifest["candidates"].append({key: value for key, value in candidate.items()
                                           if key not in ("source", "patch")})
            manifest["candidates"][-1].update(source_file=source_file, patch_file=patch_file,
                                               patch_sha256=_sha(candidate["patch"].encode("utf-8")))
        # Hash code/config metadata, never task data, external source mirrors, or credentials.
        provenance = sorted((root / "rsi_eval").glob("*.py"))
        provenance += [root / "scripts/check_diagnostic_observations.py",
                       root / "configs/tasks/planning-spanner-v0.1.json",
                       root / "configs/tasks/downloads-v0.1.json",
                       root / "docs/protocols/2026-10-20-diagnostic-comparison.md"]
        manifest["trusted_source_sha256"] = {path.relative_to(root).as_posix(): _sha(path.read_bytes())
                                              for path in provenance if path.is_file()}
        _write_json(output / "manifest.json", manifest)
        number = 0
        for candidate in candidates:
            family = candidate["family"]
            records = []
            diagnostic_issues = []
            for task_id in (PLANNING_TASKS if family == "planning" else ("oscillator1",)):
                number += 1
                result = _evaluate(root, candidate, task_id, family == "symbolic" or task_id in PUBLIC_TASKS)
                feedback_file = "feedback/%03d.json" % number
                _write_json(output / feedback_file, result)
                records.append((result, feedback_file))
                report["evaluation_counts"][family] += 1
                report["execution_counts"][family] += len(result.get("executions", []))
                if result["status"] in {"infrastructure_error", "invalid_request"}:
                    report["infrastructure_error_count"] += 1
                issue = _diagnostic_issue(result, candidate, task_id)
                if issue:
                    report["diagnostic_error_count"] += 1
                    diagnostic_issues.append({"task_id": task_id, "error_kind": issue})
            entry = {"candidate_id": candidate["candidate_id"], "variant": candidate["variant"],
                     "derivative": candidate["derivative"], "source_sha256": candidate["source_sha256"],
                     "successes": sum(result["status"] == "success" for result, _ in records),
                     "evaluation_count": len(records),
                     "outcome_counts": dict(Counter(result["status"] + ":" + str(result.get("error_kind") or "none")
                                                     for result, _ in records)),
                     "feedback_files": [filename for _, filename in records],
                     "diagnostic_issues": diagnostic_issues,
                     "observations": [_compact_observations(result) for result, _ in records
                                      if result.get("diagnostics") or family == "symbolic"]}
            report[family].append(entry)
            if candidate["candidate_id"] == "planning-sanity":
                report["sanity_passed"] = entry["successes"] == 10
            _write_json(output / "summary.json", report)
        report["original_sources_unchanged"] = all(
            _sha(_safe_path(root, relative).read_bytes()) == digest for relative, digest in original_hashes.items())
        if (report["infrastructure_error_count"] == 0 and report["diagnostic_error_count"] == 0
                and report["sanity_passed"]
                and report["original_sources_unchanged"]):
            report["status"] = "completed"
    except Exception as error:
        report["error_type"] = type(error).__name__
    report["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
    _write_json(output / "summary.json", report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args(argv)
    if not _valid_run_id(args.run_id):
        parser.error("run-id must be a safe 1-64 character identifier, not a reserved device name")
    try:
        report = run_probe(ROOT, args.run_id)
        result = {key: report[key] for key in ("status", "summary_file", "evaluation_counts", "execution_counts",
                                               "model_calls", "sealed_tasks_executed", "infrastructure_error_count",
                                               "diagnostic_error_count")}
        if "error_type" in report:
            result["error_type"] = report["error_type"]
    except Exception as error:
        result = {"status": "error", "error_type": type(error).__name__}
    print(json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2))
    return 0 if result["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
