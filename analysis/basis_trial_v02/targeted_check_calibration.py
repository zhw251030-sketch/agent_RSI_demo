"""Deterministic calibration of edit-level check-to-decision mapping."""

from __future__ import annotations

import json
from pathlib import Path

from rsi_eval.edit_evidence import build_edit
from rsi_eval.evidence_checks import VERSION as CHECK_VERSION
from rsi_eval.evidence_ids import EvidenceRegistry
from rsi_eval.targeted_edit_check import evaluate_targeted_claim


ROOT = Path(__file__).resolve().parents[2]
PARENT_SHA = "a" * 64
CHILD_SHA = "b" * 64
PARENT_FEATURES = ["m_0_0", "m_0_1", "m_1_0", "m_1_1"]
CHILD_FEATURES = ["m_0_0", "m_0_1", "m_1_0", "m_2_0"]


def _registry(*, coefficient: float | None, session_id: str) -> EvidenceRegistry:
    binding = {
        "session_id": session_id,
        "candidate_id": "parent-000",
        "candidate_sha256": PARENT_SHA,
        "task_id": "oscillator1",
        "version": CHECK_VERSION,
        "scope": "development",
    }
    scalars = {} if coefficient is None else {"coefficient:m_1_1": coefficient}
    return EvidenceRegistry([{"binding": binding, "scalars": scalars, "facts": {}}],
                            session_id=session_id)


def _case(name: str, coefficient: float | None, claim_op: str,
          claim_value: float, check_id: str) -> dict:
    session_id = "calibration-" + name
    registry = _registry(coefficient=coefficient, session_id=session_id)
    entries = [entry for entry in registry.entries()
               if entry["key"] == "coefficient:m_1_1"]
    evidence_id = entries[0]["evidence_id"] if entries else "e_0000000000000000"
    edit = build_edit(task_id="oscillator1", parent_source_sha256=PARENT_SHA,
                      candidate_source_sha256=CHILD_SHA,
                      parent_feature_ids=PARENT_FEATURES,
                      candidate_feature_ids=CHILD_FEATURES)
    result = evaluate_targeted_claim(
        edit, registry,
        {"evidence_id": evidence_id, "op": claim_op, "value": claim_value},
        check_id=check_id,
    )
    return {
        "name": name,
        "coefficient": coefficient,
        "claim": {"op": claim_op, "value": claim_value},
        "raw_status": result["raw_result"]["status"],
        "raw_reason": result["raw_result"]["reason"],
        "edit_check_status": result["checked_edit"]["check_status"],
        "decision": result["decision"]["decision"],
    }


def calibrate() -> dict:
    cases = [
        _case("small_coefficient", 0.01, "lt", 0.1, "check-small"),
        _case("large_coefficient", 0.495, "lt", 0.1, "check-large"),
        _case("missing_coefficient", None, "lt", 0.1, "check-missing"),
    ]
    expected = ["allow_candidate", "retain_parent", "defer"]
    observed = [case["decision"] for case in cases]
    return {
        "schema": "basis-targeted-check-calibration-v0.1",
        "model_calls": 0,
        "candidate_executions": 0,
        "archive_writes": 0,
        "cases": cases,
        "expected_decisions": expected,
        "observed_decisions": observed,
        "calibration_passed": observed == expected,
        "interpretation": (
            "The calibration verifies typed status propagation and explicit deferral. "
            "It does not show that coefficient magnitude identifies causal term necessity "
            "or improves a task score."
        ),
    }


def write_reports(output_dir: Path | str) -> dict:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=False)
    report = calibrate()
    (output_dir / "targeted-check-calibration.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# 编辑级 targeted check 校准",
        "",
        "日期：2026-10-24。范围：无模型调用、无候选执行、无旧归档写入。",
        "",
        "## 校准目的",
        "",
        "验证一个有界的 typed claim 是否能稳定传递为编辑级的三态决策：",
        "`supported → allow_candidate`、`contradicted → retain_parent`、",
        "`unavailable/schema_invalid → unknown → defer`。",
        "",
        "## 结果",
        "",
        "| 情形 | 原始检查 | 编辑级状态 | 临时决策 |",
        "|---|---|---|---|",
    ]
    for case in report["cases"]:
        lines.append(f"| {case['name']} | {case['raw_status']} ({case['raw_reason']}) | "
                     f"{case['edit_check_status']} | {case['decision']} |")
    lines.extend([
        "",
        f"校准通过：`{report['calibration_passed']}`。",
        "",
        "## 边界",
        "",
        "这里验证的是记录和决策映射，不是机制效果。特别是“系数较小”之类的 claim "
        "只有在宿主预先定义其含义时才可作为检查；它不能单独证明删除某项的因果必要性。",
        "下一步仍需在相同部署门下比较无检查、sham 检查和真实编辑检查。",
    ])
    (output_dir / "targeted-check-calibration.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    result = write_reports(args.output)
    if not result["calibration_passed"]:
        raise SystemExit("calibration failed")
