"""Frozen-design builder for the first three-condition edit-gate pilot."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from extensions.symbolic_basis_v01.contract import compile_submission, make_spec


VERSION = "basis-edit-comparison-v0.1"
TASK_ID = "oscillator2"
SPLIT = "train"
CONDITIONS = ["no_check", "sham_check", "real_check"]
PARENT_FEATURES = {
    "P01": ["m_0_0_0", "m_0_0_1", "m_0_1_0", "m_1_1_0"],
    "P02": ["m_0_0_0", "m_0_0_1", "m_0_1_0", "m_2_0_0"],
    "P03": ["m_0_0_0", "m_0_0_1", "m_0_1_0", "m_0_1_1"],
}


def _digest(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, allow_nan=False,
                         sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_protocol() -> dict[str, Any]:
    spec = make_spec(3, 4)
    parents = {}
    for parent_id, features in PARENT_FEATURES.items():
        compiled = compile_submission(
            {"feature_ids": features,
             "explanation": "Researcher-fixed development parent; no model text."},
            spec,
        )
        parents[parent_id] = {
            "parent_id": parent_id,
            "feature_ids": compiled["feature_ids"],
            "source_sha256": compiled["source_sha256"],
            "structural_sha256": compiled["structural_sha256"],
            "n_params": compiled["n_params"],
        }
    slots = [
        {"slot_id": f"{parent_id}-r{repeat}", "parent_id": parent_id,
         "repeat": repeat, "conditions": CONDITIONS}
        for parent_id in parents for repeat in (1, 2)
    ]
    return {
        "schema": VERSION,
        "task": {"source": "LLM-SR", "task_id": TASK_ID, "split": SPLIT,
                  "role": "development_only", "input_names": ["t", "x", "v"],
                  "target": "a"},
        "contract": spec,
        "parents": parents,
        "slots": slots,
        "candidate_generation": {
            "model_requests": len(slots),
            "one_candidate_per_slot": True,
            "condition_replay": True,
            "model_condition_blind": True,
            "allowed_edit": "keep_or_one_feature_swap",
            "analysis_unit": "parent_id x repeat; three condition rows are paired",
        },
        "conditions": {
            "order": CONDITIONS,
            "common_gate": "execute_only_when_supported",
            "no_check": {"status": "supported", "reads_evidence": False},
            "sham_check": {"status": "supported", "reads_evidence": False},
            "real_check": {
                "status_source": "typed_parent_claim",
                "reads_evidence": True,
                "claim": "abs(parent coefficient of removed feature) < 0.05",
                "threshold": 0.05,
                "missing_status": "unknown",
            },
        },
        "metrics": {
            "primary": ["harmful_edit_rate", "parent_retention_rate",
                         "candidate_execution_rate"],
            "secondary": ["train_nmse_delta", "check_status_coverage"],
            "harmful_definition": "candidate NMSE - parent NMSE > 1e-5",
            "score_scope": "train_only",
            "shadow_outcome": "evaluate every candidate after all gate decisions; never feed it back",
            "non_independence_warning": "18 gate rows are not 18 independent samples",
        },
        "budget": {"max_model_requests": len(slots), "max_conditions": len(CONDITIONS),
                   "max_gate_records": len(slots) * len(CONDITIONS),
                   "max_cny_reservation": 4.0},
        "leakage_controls": {
            "sealed_data_read": False,
            "test_id_read": False,
            "test_ood_read": False,
            "old_v02_run_reused": False,
            "posthoc_score_changes_pre_edit_decision": False,
            "shadow_scores_visible_before_gate": False,
        },
        "status": "design_only",
    }


def validate_protocol(protocol: object) -> dict[str, Any]:
    if type(protocol) is not dict or protocol.get("schema") != VERSION:
        raise ValueError("invalid comparison protocol")
    expected = build_protocol()
    if protocol != expected:
        raise ValueError("comparison protocol differs from frozen design")
    if len({parent["source_sha256"] for parent in protocol["parents"].values()}) != 3:
        raise ValueError("parent sources must be distinct")
    if len(protocol["slots"]) != 6 or any(slot["conditions"] != CONDITIONS for slot in protocol["slots"]):
        raise ValueError("slot condition schedule mismatch")
    if protocol["leakage_controls"]["sealed_data_read"]:
        raise ValueError("sealed data cannot enter mechanism pilot")
    return protocol


def write_design(output_dir: Path | str) -> dict[str, Any]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=False)
    protocol = validate_protocol(build_protocol())
    protocol["protocol_sha256"] = _digest(protocol)
    (output_dir / "protocol.json").write_text(
        json.dumps(protocol, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# 三条件编辑检查实验协议",
        "",
        "日期：2026-10-24。状态：design_only；尚未调用模型或读取 CSV。",
        "",
        "## 研究问题",
        "",
        "在固定模型权重和同一个候选的条件下，编辑前的 typed check 能否减少有害结构修改？",
        "",
        "## 固定输入",
        "",
        "- 数据：公开 LLM-SR 的 `oscillator2/train`，只作开发评分；该任务曾在早期策略选择阶段出现过，因此不作为独立泛化证据。",
        "- 父结构：P01/P02/P03 三个研究者预先固定的四项基函数结构，每个重复生成一个候选。",
        "- 每个候选会在三种条件下重放，条件不会传给模型。",
        "- 正式候选执行前才应用编辑门；旧 v02 运行目录不重用、不重跑。",
        "- 统计单位是 6 个 `parent × repeat` 候选；18 条条件记录是配对结果，不是 18 个独立样本。",
        "",
        "## 条件和门",
        "",
        "| 条件 | 检查 | 最终规则 |",
        "|---|---|---|",
        "| no_check | 不读证据，固定 supported | 执行候选 |",
        "| sham_check | 不读证据，固定 supported | 执行候选 |",
        "| real_check | 检查被删除项的父系数绝对值是否小于 0.05 | supported 才执行，否则保留父结构 |",
        "",
        "真实检查阈值在运行前固定。它是一个可检验的启发式，不被解释为因果必要性；缺失系数必须是 `unknown`，不能默认放行。",
        "",
        "## 评价",
        "",
        "主要报告有害编辑率、父结构保留率和候选执行率；辅助报告训练 NMSE 变化、检查状态覆盖率以及每个候选在三条件下的配对结果。‘有害’定义为候选 NMSE 比父结构高超过 `1e-5`。所有候选在门控决策冻结后才做 shadow outcome，结果不回流。保持原结构的候选标记为 `not_applicable`，不进入检查校准分母。不读取 `test_id`、`test_ood` 或官方封存数据。",
        "",
        "这是一轮机制开发实验，不足以证明跨任务泛化。只有在接口、假 provider 预演和真实小试都通过后，才考虑在 Spanner 或其他 LLM-SR 方程上复制。",
    ]
    (output_dir / "protocol.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return protocol


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    write_design(args.output)
