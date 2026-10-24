"""Deterministic train-only development splits for symbolic tasks.

The official test and OOD files are deliberately outside this API.  It accepts
already-loaded rows and records only original row indices, so a split manifest
can be checked against a separately hashed source file without copying data
into the repository.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Any


VERSION = "replacement-dev-splits-v0.1"
SPLIT_ORDER = ("fit_dev", "check_dev", "outcome_dev")
RATIOS = {"fit_dev": 0.60, "check_dev": 0.20, "outcome_dev": 0.20}
TASKS = {
    "bactgrow": {
        "headers": ("b", "s", "temp", "pH", "db"),
        "target": "db",
        "strata": ("target_decile",),
    },
    "stressstrain": {
        "headers": ("strain", "temp", "stress"),
        "target": "stress",
        "strata": ("temp", "target_decile"),
    },
}


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256(value: str | bytes) -> str:
    if isinstance(value, str):
        value = value.encode("utf-8")
    return hashlib.sha256(value).hexdigest()


def _source_key(task_id: str, version: str, row_index: int) -> str:
    return _sha256(f"{task_id}|{version}|row:{row_index}")


def _target_counts(row_count: int) -> dict[str, int]:
    # The remainder is assigned to outcome_dev by protocol.  This gives the
    # official 2161-row stressstrain split 1296/432/433 exactly.
    fit = math.floor(row_count * RATIOS["fit_dev"])
    check = math.floor(row_count * RATIOS["check_dev"])
    return {"fit_dev": fit, "check_dev": check, "outcome_dev": row_count - fit - check}


def _deciles(values: list[float]) -> list[int]:
    if not values:
        raise ValueError("cannot compute deciles for empty data")
    order = sorted(range(len(values)), key=lambda index: (values[index], index))
    result = [0] * len(values)
    for rank, index in enumerate(order):
        result[index] = min(9, (10 * rank) // len(values))
    return result


def _number(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be numeric")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def _row_index_hash(indices: list[int]) -> str:
    return _sha256(_canonical(indices))


def _split_data_hash(source_data_sha256: str, indices: list[int]) -> str:
    """Bind membership to the exact source file, not to row indices alone."""
    return _sha256(_canonical({"source_data_sha256": source_data_sha256.lower(),
                               "row_indices": indices}))


def build_split_manifest(
    *,
    task_id: str,
    headers: Sequence[str],
    rows: Sequence[Mapping[str, Any]],
    data_sha256: str,
    version: str = VERSION,
) -> dict[str, Any]:
    """Build a frozen, disjoint fit/check/outcome manifest from train rows."""

    if task_id not in TASKS:
        raise ValueError(f"unknown task: {task_id}")
    config = TASKS[task_id]
    if tuple(headers) != config["headers"]:
        raise ValueError(f"{task_id} headers do not match frozen schema")
    if not isinstance(rows, Sequence) or not rows:
        raise ValueError("rows must be a nonempty sequence")
    if not isinstance(data_sha256, str) or len(data_sha256) != 64:
        raise ValueError("data_sha256 must be a SHA-256 hex digest")
    if any(character not in "0123456789abcdefABCDEF" for character in data_sha256):
        raise ValueError("data_sha256 must be a SHA-256 hex digest")

    target_values = [_number(row[config["target"]], config["target"]) for row in rows]
    deciles = _deciles(target_values)
    strata: dict[tuple[str, ...], list[int]] = defaultdict(list)
    for index, row in enumerate(rows):
        if set(row) != set(headers):
            raise ValueError(f"row {index} keys do not match headers")
        if task_id == "bactgrow":
            key = (f"decile:{deciles[index]}",)
        else:
            _number(row["temp"], "temp")
            key = (f"temp:{row['temp']}", f"stress_decile:{deciles[index]}")
        strata[key].append(index)

    # Start with within-stratum largest-remainder allocation.  The subsequent
    # deterministic transfers only correct the global requested counts.
    assignments: dict[str, list[int]] = {split: [] for split in SPLIT_ORDER}
    stratum_records: list[dict[str, Any]] = []
    for key in sorted(strata):
        indices = sorted(strata[key], key=lambda index: _source_key(task_id, version, index))
        n = len(indices)
        ideals = {split: n * RATIOS[split] for split in SPLIT_ORDER}
        counts = {split: math.floor(ideals[split]) for split in SPLIT_ORDER}
        for _ in range(n - sum(counts.values())):
            split = max(
                SPLIT_ORDER,
                key=lambda candidate: (ideals[candidate] - counts[candidate], -SPLIT_ORDER.index(candidate)),
            )
            counts[split] += 1
        cursor = 0
        for split in SPLIT_ORDER:
            chosen = indices[cursor:cursor + counts[split]]
            assignments[split].extend(chosen)
            cursor += counts[split]
        stratum_records.append({
            "key": list(key),
            "row_count": n,
            "initial_counts": counts,
            "row_index_sha256": _row_index_hash(indices),
        })

    target_counts = _target_counts(len(rows))
    actual = {split: len(assignments[split]) for split in SPLIT_ORDER}
    # Correct global rounding while keeping every transfer inside a stratum.
    # A row can be transferred only when the source is over target and the
    # destination is under target; deterministic hash order removes discretion.
    while actual != target_counts:
        destinations = [split for split in SPLIT_ORDER if actual[split] < target_counts[split]]
        sources = [split for split in SPLIT_ORDER if actual[split] > target_counts[split]]
        if not destinations or not sources:
            raise RuntimeError("unable to reconcile stratified split counts")
        destination = destinations[0]
        source = sources[0]
        candidates = sorted(assignments[source], key=lambda index: _source_key(task_id, version, index))
        moved = None
        for index in candidates:
            key = next(key for key, members in strata.items() if index in members)
            if len([member for member in assignments[destination] if member in strata[key]]) < math.ceil(
                len(strata[key]) * RATIOS[destination]
            ):
                moved = index
                break
        if moved is None:
            # The global target can require the final row of a small stratum;
            # the exact-count correction remains deterministic and documented.
            moved = candidates[0]
        assignments[source].remove(moved)
        assignments[destination].append(moved)
        actual[source] -= 1
        actual[destination] += 1

    split_payload: dict[str, dict[str, Any]] = {}
    for split in SPLIT_ORDER:
        indices = sorted(assignments[split])
        split_payload[split] = {
            "row_indices": indices,
            "row_index_sha256": _row_index_hash(indices),
            "data_sha256": _split_data_hash(data_sha256, indices),
            "n": len(indices),
        }
    body = {
        "schema": VERSION,
        "task_id": task_id,
        "source": {
            "split": "train",
            "data_sha256": data_sha256.lower(),
            "row_count": len(rows),
            "headers": list(headers),
            "official_test_read": False,
            "official_test_ood_read": False,
        },
        "allocation": {
            "version": version,
            "ratios": RATIOS,
            "target_counts": target_counts,
            "stratification": list(config["strata"]),
            "row_order": "sha256(task_id|version|row:<0-based-index>) within strata",
            "remainder_rule": "floor per stratum; deterministic global correction to fit/check/outcome counts",
        },
        "split_order": list(SPLIT_ORDER),
        "split_counts": target_counts,
        "strata": stratum_records,
        "splits": split_payload,
    }
    body["manifest_sha256"] = _sha256(_canonical(body))
    return body
