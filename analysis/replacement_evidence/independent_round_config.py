"""Frozen configuration and novelty checks for the next p04 development batch."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping

from analysis.replacement_evidence.cross_task_config import CROSS_TASK_DEFINITIONS
from analysis.replacement_evidence.round_runner import ParentDefinition, TaskDefinition


P04_TASK_DEFINITIONS = (
    TaskDefinition(
        task_id="bactgrow", input_names=("b", "s", "temp", "pH"),
        headers=("b", "s", "temp", "pH", "db"), target="db",
        parents=(ParentDefinition(
            "bactgrow-p04",
            ("m_0_0_0_0", "m_1_0_0_0", "m_0_1_0_0", "m_0_0_1_0", "m_1_1_0_0"),
        ),),
    ),
    TaskDefinition(
        task_id="stressstrain", input_names=("strain", "temp"),
        headers=("strain", "temp", "stress"), target="stress",
        parents=(ParentDefinition(
            "stressstrain-p04",
            ("m_0_0", "m_1_0", "m_0_1", "m_1_1", "m_2_0"),
        ),),
    ),
    TaskDefinition(
        task_id="oscillator1", input_names=("x", "v"),
        headers=("x", "v", "a"), target="a",
        parents=(ParentDefinition(
            "oscillator1-p04",
            ("m_0_0", "m_1_0", "m_0_1", "m_1_1", "m_2_0"),
        ),),
    ),
    TaskDefinition(
        task_id="oscillator2", input_names=("t", "x", "v"),
        headers=("t", "x", "v", "a"), target="a",
        parents=(ParentDefinition(
            "oscillator2-p04",
            ("m_0_0_0", "m_1_0_0", "m_0_1_0", "m_0_0_1", "m_1_1_0", "m_0_1_1"),
        ),),
    ),
)


def slot_ids() -> list[str]:
    return [
        f"{task.parents[0].parent_id}-r{repeat}"
        for task in P04_TASK_DEFINITIONS
        for repeat in (1, 2)
    ]


def assert_source_novelty(
    *,
    proposed_parent_hashes: Iterable[str],
    proposed_candidate_hashes: Iterable[str],
    historical_hashes: Iterable[str],
) -> None:
    parents = set(proposed_parent_hashes)
    candidates = set(proposed_candidate_hashes)
    historical = set(historical_hashes)
    if parents & historical or candidates & historical:
        raise ValueError("source collision with historical round")
    if parents & candidates:
        raise ValueError("parent/candidate source collision")


def historical_source_hashes(summary: Mapping[str, object]) -> dict[str, set[str]]:
    """Extract task-scoped parent/candidate source hashes from a round summary."""

    result: dict[str, set[str]] = defaultdict(set)
    records = summary.get("records", [])
    if not isinstance(records, list):
        raise ValueError("round summary records must be a list")
    for record in records:
        if not isinstance(record, Mapping):
            raise ValueError("round summary record must be an object")
        task_id = record.get("task_id")
        if not isinstance(task_id, str) or not task_id:
            raise ValueError("round summary record has no task_id")
        for field in ("parent_source_sha256", "candidate_source_sha256"):
            value = record.get(field)
            if isinstance(value, str) and value:
                result[task_id].add(value)
    return dict(result)


def assert_records_novelty(
    records: Iterable[Mapping[str, object]],
    historical_by_task: Mapping[str, Iterable[str]],
) -> None:
    """Reject source reuse within each task while allowing cross-task reuse."""

    grouped: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for record in records:
        task_id = record.get("task_id")
        if not isinstance(task_id, str) or not task_id:
            raise ValueError("proposal record has no task_id")
        grouped[task_id].append(record)
    for task_id, task_records in grouped.items():
        parents: set[str] = set()
        candidates: set[str] = set()
        for record in task_records:
            parent = record.get("parent_source_sha256")
            candidate = record.get("candidate_source_sha256")
            if not isinstance(parent, str) or not parent:
                raise ValueError("proposal record has no parent source hash")
            if not isinstance(candidate, str) or not candidate:
                raise ValueError("proposal record has no candidate source hash")
            parents.add(parent)
            if record.get("edit_mode", "swap_one") == "swap_one":
                candidates.add(candidate)
        assert_source_novelty(
            proposed_parent_hashes=parents,
            proposed_candidate_hashes=candidates,
            historical_hashes=historical_by_task.get(task_id, ()),
        )
