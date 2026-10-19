"""Verify Spanner files and fixed VAL fixtures without models or candidate code.

The structural check only checks balanced parentheses and a single ``define``
expression. It is not an official PDDL parser or a benchmark evaluation.
"""

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import tempfile
import time


PDDL_PREFIX = "llm_genplan/envs/assets/pddl/pg3/"
PROMPT_ID = "spannerlearning/seed0/problem0"
VAL_DIRECTORY = "llm_genplan/third_party/val/linux64"
VAL_HASHES = {
    "Validate": "752b40692acb14f9c9d165e57662f84b9ada9a4d1d33ea31ed897aea6d8bb06d",
    "libVAL.so": "b889dfee9450cd32f55b0a74b8cebd78a4eb5104f2184c1dd87db919a887f2f2",
}
# Hand-authored installation fixture for the public prompt problem, not a solver.
VALID_PLAN = [
    "(walk shed location1 bob)",
    "(pickup_spanner location1 spanner3 bob)",
    "(walk location1 location2 bob)",
    "(walk location2 location3 bob)",
    "(walk location3 location4 bob)",
    "(pickup_spanner location4 spanner1 bob)",
    "(pickup_spanner location4 spanner2 bob)",
    "(walk location4 gate bob)",
    "(tighten_nut gate spanner1 bob nut1)",
    "(tighten_nut gate spanner2 bob nut2)",
    "(tighten_nut gate spanner3 bob nut3)",
]


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def structural_check(data):
    """Check shape only; never claim type, action, or semantic validation."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    text = re.sub(r";[^\r\n]*", "", text).strip()
    if not re.match(r"\(\s*define(?:\s|\()", text, flags=re.IGNORECASE):
        return False
    depth = 0
    roots = 0
    for char in text:
        if char == "(":
            if depth == 0:
                roots += 1
            depth += 1
        elif char == ")":
            depth -= 1
            if depth < 0:
                return False
        elif depth == 0 and not char.isspace():
            return False
    return depth == 0 and roots == 1


def safe_file(base, relative):
    """Reject traversal and symlink escapes in manifest-relative paths."""
    rel = PurePosixPath(relative)
    if rel.is_absolute() or ".." in rel.parts or "\\" in relative:
        raise ValueError("Unsafe manifest path")
    path = (base / Path(*rel.parts)).resolve()
    if not path.is_relative_to(base.resolve()):
        raise ValueError("Manifest path escapes its data root")
    return path


def check_files(manifest, source, data_root):
    entries = [manifest["domain"]] + manifest["tasks"]
    if len(entries) != 401 or len({e["upstream_path"] for e in entries}) != 401:
        raise ValueError("Expected exactly 401 distinct manifest files")
    records = []
    for entry in entries:
        upstream = entry["upstream_path"]
        if not upstream.startswith(PDDL_PREFIX):
            raise ValueError("Unexpected PDDL manifest prefix")
        relative = upstream[len(PDDL_PREFIX):]
        record = {"path": relative, "expected_sha256": entry["sha256"]}
        for label, base, name in (
            ("vendor", source, upstream), ("copied_data", data_root, relative)
        ):
            path = safe_file(base, name)
            try:
                content = path.read_bytes()
            except OSError:
                record[label] = {"status": "missing_or_unreadable"}
                continue
            digest = sha256(content)
            shape_ok = structural_check(content)
            record[label] = {
                "status": "passed" if digest == entry["sha256"] and shape_ok else "failed",
                "sha256": digest,
                "sha256_matches": digest == entry["sha256"],
                "balanced_single_define": shape_ok,
                "bytes": len(content),
            }
        records.append(record)
    return {
        "status": "passed" if all(
            record[label]["status"] == "passed"
            for record in records for label in ("vendor", "copied_data")
        ) else "failed",
        "expected_files_per_copy": 401,
        "verified_files_per_copy": {
            label: sum(r[label]["status"] == "passed" for r in records)
            for label in ("vendor", "copied_data")
        },
        "structural_check_scope": "Balanced parentheses and one define form only; not an official PDDL parser.",
        "official_subset_counts": dict(Counter(t["official_subset"] for t in manifest["tasks"])),
        "pilot_role_counts": dict(Counter(t["pilot_role"] for t in manifest["tasks"])),
        "files": records,
    }


def classify_val_output(returncode, stdout, stderr):
    """Require recognized semantic evidence; unknown output fails closed."""
    output = stdout + "\n" + stderr
    lowered = output.lower()
    infrastructure_markers = (
        "error while loading shared libraries", "cannot open shared object file",
        "symbol lookup error", "exec format error", "permission denied",
        "segmentation fault", "syntax error", "failed to parse", "parse error",
        "failed to open", "cannot open file", "could not open",
    )
    if returncode < 0 or returncode not in (0, 1) or any(
        marker in lowered for marker in infrastructure_markers
    ):
        return {"status": "infrastructure_error", "reason": "validator_process_or_input_error"}
    valid = bool(re.search(r"^\s*Plan valid\s*$", output, flags=re.MULTILINE | re.IGNORECASE))
    invalid = any(marker in lowered for marker in (
        "plan invalid", "plan failed", "unsatisfied precondition", "unsatisfied goal",
        "goal not satisfied", "goal is not satisfied", "goal not achieved",
    ))
    if valid and not invalid and returncode == 0:
        return {"status": "valid", "reason": "plan_valid_marker"}
    if invalid and not valid:
        return {"status": "invalid", "reason": "semantic_failure_marker"}
    return {"status": "infrastructure_error", "reason": "unrecognized_or_conflicting_output"}


def run_val(binary, domain, problem, actions, scratch, name, timeout):
    plan = scratch / (name + ".plan")
    plan_bytes = "".join(f"{i}: {action}\n" for i, action in enumerate(actions)).encode("utf-8")
    plan.write_bytes(plan_bytes)
    result = {"plan_length": len(actions), "plan_sha256": sha256(plan_bytes)}
    # Do not inherit model credentials. This is not a sandbox for untrusted code.
    environment = {"PATH": os.defpath, "LANG": "C", "LC_ALL": "C"}
    environment["LD_LIBRARY_PATH"] = str(binary.parent)
    started = time.monotonic()
    try:
        completed = subprocess.run(
            [str(binary), "-v", str(domain), str(problem), str(plan)],
            cwd=scratch, env=environment, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout, check=False,
        )
    except FileNotFoundError:
        result.update(status="infrastructure_error", reason="missing_executable", returncode=None)
    except subprocess.TimeoutExpired:
        result.update(status="infrastructure_error", reason="validator_timeout", returncode=None)
    except OSError as exc:
        result.update(status="infrastructure_error", reason="validator_os_error", returncode=None, errno=exc.errno)
    else:
        result.update(classify_val_output(completed.returncode, completed.stdout, completed.stderr))
        result.update(
            returncode=completed.returncode,
            stdout_sha256=sha256(completed.stdout.encode("utf-8")),
            stderr_sha256=sha256(completed.stderr.encode("utf-8")),
            stdout_bytes=len(completed.stdout.encode("utf-8")),
            stderr_bytes=len(completed.stderr.encode("utf-8")),
        )
    result["elapsed_seconds"] = round(time.monotonic() - started, 6)
    return result


def check_fixtures(manifest, source, data_root, root, timeout):
    prompts = [t for t in manifest["tasks"] if t["id"] == PROMPT_ID]
    if len(prompts) != 1 or prompts[0].get("pilot_role") != "prompt":
        raise ValueError("The fixed smoke fixture must be an explicitly allowed prompt task")
    domain = safe_file(data_root, manifest["domain"]["upstream_path"][len(PDDL_PREFIX):])
    problem = safe_file(data_root, prompts[0]["upstream_path"][len(PDDL_PREFIX):])
    val_dir = safe_file(source, VAL_DIRECTORY)
    artifacts = {}
    for name, expected in VAL_HASHES.items():
        path = val_dir / name
        try:
            digest = sha256(path.read_bytes())
        except OSError:
            artifacts[name] = {"status": "missing_or_unreadable", "expected_sha256": expected}
        else:
            artifacts[name] = {
                "status": "passed" if digest == expected else "failed",
                "sha256": digest, "expected_sha256": expected,
            }
    if any(a["status"] != "passed" for a in artifacts.values()):
        return {"status": "failed", "artifacts": artifacts, "reason": "validator_integrity_failed"}
    if sys.platform != "linux":
        return {"status": "failed", "artifacts": artifacts, "reason": "linux_runtime_required"}
    (root / "tmp").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="planning-data-check-", dir=root / "tmp") as directory:
        scratch = Path(directory).resolve()
        fixtures = {}
        for name, actions, expected in (
            ("valid_hand_authored_plan", VALID_PLAN, "valid"),
            ("empty_plan", [], "invalid"),
            ("unsatisfied_precondition", [VALID_PLAN[8]], "invalid"),
        ):
            observed = run_val(val_dir / "Validate", domain, problem, actions, scratch, name, timeout)
            observed["expected_status"] = expected
            observed["passed"] = observed["status"] == expected
            fixtures[name] = observed
        # A missing process must never become a planning failure.
        missing = run_val(scratch / "deliberately-missing-Validate", domain, problem, [], scratch, "missing_binary", timeout)
        missing["expected_status"] = "infrastructure_error"
        missing["passed"] = missing["status"] == "infrastructure_error" and missing["reason"] == "missing_executable"
        fixtures["missing_binary"] = missing
    return {
        "status": "passed" if all(f["passed"] for f in fixtures.values()) else "failed",
        "artifacts": artifacts,
        "task_id": PROMPT_ID,
        "task_role": "prompt",
        "fixtures": fixtures,
        "sealed_tasks_executed": 0,
        "reference_solver_implemented": False,
    }


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=root / "vendor/llm-genplan")
    parser.add_argument("--data-root", type=Path, default=root / "data/planning/spanner")
    parser.add_argument("--manifest", type=Path, default=root / "configs/tasks/planning-spanner-v0.1.json")
    parser.add_argument("--output", type=Path, default=root / "runs/data-preparation/planning.json")
    parser.add_argument("--timeout", type=float, default=10.0)
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    report = {
        "schema_version": "1.0",
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "script_sha256": sha256(Path(__file__).read_bytes()),
        "scope": "Downloaded data integrity and hand-authored VAL installation fixtures; not a benchmark or candidate evaluation.",
        "model_calls": 0, "agent_rollouts": 0, "sealed_tasks_executed": 0,
        "official_pddl_parser_executed": False,
        "generated_code_executed": False,
    }
    try:
        manifest_bytes = args.manifest.read_bytes()
        manifest = json.loads(manifest_bytes)
        report["manifest_sha256"] = sha256(manifest_bytes)
        report["upstream_commit"] = manifest["upstream"]["commit"]
        source = args.source.resolve()
        data_root = args.data_root.resolve()
        report["integrity"] = check_files(manifest, source, data_root)
        if report["integrity"]["status"] == "passed":
            report["validator"] = check_fixtures(manifest, source, data_root, root, args.timeout)
        else:
            report["validator"] = {"status": "not_run", "reason": "task_integrity_failed"}
        report["status"] = "passed" if (
            report["integrity"]["status"] == "passed" and report["validator"]["status"] == "passed"
        ) else "failed"
    except (OSError, ValueError, KeyError, TypeError) as exc:
        report.update(status="failed", failure_kind="configuration_or_data_error", error_type=type(exc).__name__)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": report["status"],
        "integrity": report.get("integrity", {}).get("status"),
        "validator": report.get("validator", {}).get("status"),
        "model_calls": 0, "sealed_tasks_executed": 0,
    }))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
