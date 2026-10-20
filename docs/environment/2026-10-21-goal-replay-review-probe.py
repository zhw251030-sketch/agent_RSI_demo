"""Independent local read-only replay probe; ignored review evidence only."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
events = {"git_processes": 0, "task_data_reads": 0, "network_calls": 0}

def guard(event, args):
    if event == "open" and isinstance(args[0], (str, bytes)):
        name = str(args[0]).replace("\\", "/").lower()
        if "/data/planning/" in name or "/data/symbolic/" in name or name.endswith("auth.json"):
            events["task_data_reads"] += 1
            raise RuntimeError("Review refuses task data or credential read")
    if event == "subprocess.Popen":
        target = args[0] if args[0] is not None else (args[1][0] if isinstance(args[1], list) else args[1].split(" ", 1)[0])
        executable = str(target).strip('"').replace("\\", "/").split("/")[-1].lower()
        if executable not in ("git", "git.exe"):
            raise RuntimeError("Review refuses non-Git process")
        events["git_processes"] += 1
    if event.startswith("socket."):
        events["network_calls"] += 1
        raise RuntimeError("Review refuses network")

sys.addaudithook(guard)
from scripts.analyze_goal_alignment import analyze
report = analyze(ROOT)
summary = {key: report[key] for key in (
    "status", "historical_submissions", "historical_case_count",
    "distinct_final_source_count", "decisions", "decisions_by_archive",
    "new_model_calls", "new_candidate_executions", "strategy_selection_executed",
    "persistent_strategy_updated")}
summary["review_guards"] = events
summary["promotions"] = [dict(archive_id=row["archive_id"], session_id=row["session_id"],
    reason_codes=row["proposed_outcome"]["reason_codes"])
    for row in report["rows"] if row["retrospective_rule_action"] == "promote"]
summary["probe_propositions"] = [dict(case_id=p["case_id"], opportunity=p["opportunity"],
    proposition=p.get("proposition"), rows=p.get("rows")) for p in report["probes"]]
raw = json.dumps(summary, ensure_ascii=False, indent=2) + "\n"
(ROOT/"tmp/goal-replay-independent-probe.json").write_text(raw, encoding="utf-8")
print(raw)
