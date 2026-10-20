"""Pure, bounded checks of typed evidence and preregistered numeric changes.

The caller owns evidence production, the evaluation/selection lifecycle, and
trusted storage of registrations made before child execution. A registration
is a JSON record, not a cryptographic attestation. This module does not execute
candidates, identify causes, interpret prose, or decide which child to retain.

All input objects have closed schemas. Oversize values are rejected rather than
truncated before comparison, so truncation cannot change a binding or a fact.
Only a checked reference, one scalar/atom, and fixed fields can enter a report;
fact inventories and malformed caller data are never echoed.
"""

from __future__ import annotations

import math
import re
from typing import Literal, TypedDict


VERSION = "evidence-v0.1"
ABS_TOL = 1e-10
REL_TOL = 1e-8
MAX_TEXT = 128
MAX_ATOM_PARTS = 16
MAX_SNAPSHOTS = 128
MAX_KEYS = 512
MAX_FACTS = 1024

Status = Literal["supported", "contradicted", "unavailable", "schema_invalid"]
Reason = Literal[
    "claim_schema_invalid", "reference_schema_invalid", "snapshots_schema_invalid",
    "prediction_schema_invalid", "registration_schema_invalid", "unsupported_version",
    "reference_not_found", "ambiguous_reference", "key_missing", "value_unavailable",
    "comparison_supported", "comparison_contradicted", "fact_present", "fact_absent",
    "prediction_registered", "child_not_found", "child_ambiguous", "child_not_distinct",
    "prediction_supported", "prediction_contradicted", "numeric_overflow",
]


class Binding(TypedDict):
    session_id: str
    candidate_id: str
    candidate_sha256: str
    task_id: str
    version: str
    scope: str


class Reference(Binding):
    key: str


class EvidenceSnapshot(TypedDict):
    binding: Binding
    scalars: dict[str, float | None]
    facts: dict[str, list[list[str]]]


class Claim(TypedDict):
    kind: Literal["scalar", "fact"]
    reference: Reference
    op: Literal["eq", "lt", "le", "gt", "ge", "contains", "not_contains"]
    value: float | list[str]


class Prediction(TypedDict):
    reference: Reference
    direction: Literal["decrease", "increase"]
    min_delta: float


class Report(TypedDict, total=False):
    status: Status
    reason: Reason
    reference: Reference
    child_reference: Reference
    op: str
    actual: float | bool
    expected: float | list[str]
    tolerance: float
    before: float
    after: float
    direction: Literal["decrease", "increase"]
    min_delta: float


_BINDING_KEYS = frozenset(Binding.__annotations__)
_REFERENCE_KEYS = _BINDING_KEYS | {"key"}
_SNAPSHOT_KEYS = frozenset({"binding", "scalars", "facts"})
_CLAIM_KEYS = frozenset({"kind", "reference", "op", "value"})
_PREDICTION_KEYS = frozenset({"reference", "direction", "min_delta"})
_REGISTERED_KEYS = _PREDICTION_KEYS | {"status", "reason", "before"}
_SCALAR_OPS = frozenset({"eq", "lt", "le", "gt", "ge"})
_FACT_OPS = frozenset({"contains", "not_contains"})
_HASH = re.compile(r"[0-9a-fA-F]{64}\Z")


def _closed(value: object, keys: frozenset[str]) -> bool:
    return (type(value) is dict and len(value) == len(keys)
            and all(type(key) is str and key in keys for key in value))


def _text(value: object) -> bool:
    return type(value) is str and 0 < len(value) <= MAX_TEXT


def _number(value: object) -> bool:
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value)
    except (OverflowError, ValueError):
        return False


def _binding(value: object, *, reference: bool = False) -> bool:
    keys = _REFERENCE_KEYS if reference else _BINDING_KEYS
    return (_closed(value, keys) and all(_text(part) for part in value.values())
            and _HASH.fullmatch(value["candidate_sha256"]) is not None)


def _atom(value: object) -> bool:
    return (type(value) is list and 0 < len(value) <= MAX_ATOM_PARTS
            and all(_text(part) for part in value))


def _mapping(value: object) -> bool:
    return (type(value) is dict and len(value) <= MAX_KEYS
            and all(_text(key) for key in value))


def _snapshots(value: object) -> bool:
    if type(value) is not list or len(value) > MAX_SNAPSHOTS:
        return False
    for snapshot in value:
        if not _closed(snapshot, _SNAPSHOT_KEYS) or not _binding(snapshot["binding"]):
            return False
        scalars, facts = snapshot["scalars"], snapshot["facts"]
        if not _mapping(scalars) or not _mapping(facts):
            return False
        if any(number is not None and not _number(number) for number in scalars.values()):
            return False
        for atoms in facts.values():
            if (type(atoms) is not list or len(atoms) > MAX_FACTS
                    or any(not _atom(atom) for atom in atoms)):
                return False
    return True


def _report(status: Status, reason: Reason, **details: object) -> Report:
    return {"status": status, "reason": reason, **details}


def _lookup(reference: Reference, snapshots: list[EvidenceSnapshot]) -> tuple[EvidenceSnapshot | None, Reason | None]:
    if reference["version"] != VERSION:
        return None, "unsupported_version"
    matches = [snapshot for snapshot in snapshots
               if all(snapshot["binding"][key] == reference[key] for key in _BINDING_KEYS)]
    if not matches:
        return None, "reference_not_found"
    if len(matches) != 1:
        return None, "ambiguous_reference"
    return matches[0], None


def _scalar(snapshot: EvidenceSnapshot, key: str) -> tuple[float | None, Reason | None]:
    if key not in snapshot["scalars"]:
        return None, "key_missing"
    value = snapshot["scalars"][key]
    if value is None:
        return None, "value_unavailable"
    return float(value), None


def _compare(actual: float, expected: float, op: str) -> tuple[bool, float]:
    tolerance = ABS_TOL + REL_TOL * max(abs(actual), abs(expected))
    # Overflow of a difference between opposite finite extremes is safely
    # outside this finite tolerance; it never becomes a report value.
    close = abs(actual - expected) <= tolerance
    if op == "eq":
        outcome = close
    elif op == "lt":
        outcome = actual < expected and not close
    elif op == "gt":
        outcome = actual > expected and not close
    elif op == "le":
        outcome = actual < expected or close
    else:  # validated "ge"
        outcome = actual > expected or close
    return outcome, tolerance


def check_claim(claim: object, snapshots: object) -> Report:
    """Check one exact bound scalar comparison or ordered fact membership.

    A known empty fact list is evidence of absence. A missing key, missing
    binding, or scalar ``None`` is unavailable evidence, never a contradiction.
    Fact ``actual`` is membership, not the potentially large fact inventory.
    """
    if not _closed(claim, _CLAIM_KEYS):
        return _report("schema_invalid", "claim_schema_invalid")
    if not _binding(claim["reference"], reference=True):
        return _report("schema_invalid", "reference_schema_invalid")
    kind, op, value = claim["kind"], claim["op"], claim["value"]
    if type(kind) is not str or type(op) is not str:
        return _report("schema_invalid", "claim_schema_invalid")
    if not ((kind == "scalar" and op in _SCALAR_OPS and _number(value))
            or (kind == "fact" and op in _FACT_OPS and _atom(value))):
        return _report("schema_invalid", "claim_schema_invalid")
    if not _snapshots(snapshots):
        return _report("schema_invalid", "snapshots_schema_invalid")
    reference = dict(claim["reference"])
    expected = float(value) if kind == "scalar" else list(value)
    context = {"reference": reference, "op": op, "expected": expected}
    snapshot, error = _lookup(reference, snapshots)
    if error:
        return _report("unavailable", error, **context)
    if kind == "scalar":
        actual, error = _scalar(snapshot, reference["key"])
        if error:
            return _report("unavailable", error, **context)
        outcome, tolerance = _compare(actual, expected, op)
        return _report("supported" if outcome else "contradicted",
                       "comparison_supported" if outcome else "comparison_contradicted",
                       actual=actual, tolerance=tolerance, **context)
    if reference["key"] not in snapshot["facts"]:
        return _report("unavailable", "key_missing", **context)
    present = value in snapshot["facts"][reference["key"]]
    outcome = present if op == "contains" else not present
    return _report("supported" if outcome else "contradicted",
                   "fact_present" if present else "fact_absent", actual=present, **context)


def _prediction(value: object) -> bool:
    return (_closed(value, _PREDICTION_KEYS)
            and _binding(value["reference"], reference=True)
            and type(value["direction"]) is str
            and value["direction"] in {"decrease", "increase"}
            and _number(value["min_delta"]) and value["min_delta"] >= 0)


def register_prediction(prediction: object, snapshots: object) -> Report:
    """Capture the numeric parent value before the caller executes a child.

    ``supported/prediction_registered`` means registration succeeded; it makes
    no claim that the future change will occur. Store this exact report in a
    trusted host record and later pass it to ``check_prediction``.
    """
    if not _prediction(prediction):
        return _report("schema_invalid", "prediction_schema_invalid")
    if not _snapshots(snapshots):
        return _report("schema_invalid", "snapshots_schema_invalid")
    reference = dict(prediction["reference"])
    context = {"reference": reference, "direction": prediction["direction"],
               "min_delta": float(prediction["min_delta"])}
    snapshot, error = _lookup(reference, snapshots)
    if error:
        return _report("unavailable", error, **context)
    before, error = _scalar(snapshot, reference["key"])
    if error:
        return _report("unavailable", error, **context)
    return _report("supported", "prediction_registered", before=before, **context)


def check_prediction(registered: object, child_snapshots: object) -> Report:
    """Check a registered absolute change against an explicit child's data.

    The caller must supply that executed child's snapshots, including rejected
    or unselected children. There is no implicit best-child lookup. Multiple
    candidate identities are ambiguous. Parent-ID reuse is unavailable even
    when its digest changes; a new child ID may repeat the parent's source.
    Missing/failed child observations remain unavailable, not successful.
    """
    if (not _closed(registered, _REGISTERED_KEYS)
            or type(registered["status"]) is not str or registered["status"] != "supported"
            or type(registered["reason"]) is not str or registered["reason"] != "prediction_registered"
            or not _number(registered["before"])
            or not _prediction({key: registered[key] for key in _PREDICTION_KEYS})):
        return _report("schema_invalid", "registration_schema_invalid")
    if not _snapshots(child_snapshots):
        return _report("schema_invalid", "snapshots_schema_invalid")
    reference = dict(registered["reference"])
    context = {"reference": reference, "before": float(registered["before"]),
               "direction": registered["direction"], "op": "ge",
               "expected": float(registered["min_delta"])}
    if reference["version"] != VERSION:
        return _report("unavailable", "unsupported_version", **context)
    shared_keys = ("session_id", "task_id", "scope", "version")
    matches = [snapshot for snapshot in child_snapshots
               if all(snapshot["binding"][key] == reference[key] for key in shared_keys)]
    if not matches:
        return _report("unavailable", "child_not_found", **context)
    identities = {(snapshot["binding"]["candidate_id"], snapshot["binding"]["candidate_sha256"])
                  for snapshot in child_snapshots}
    if len(identities) != 1 or len(matches) != 1:
        return _report("unavailable", "child_ambiguous", **context)
    child = matches[0]
    if child["binding"]["candidate_id"] == reference["candidate_id"]:
        return _report("unavailable", "child_not_distinct", **context)
    child_reference = {**child["binding"], "key": reference["key"]}
    context["child_reference"] = child_reference
    after, error = _scalar(child, reference["key"])
    if error:
        return _report("unavailable", error, **context)
    before = context["before"]
    delta = before - after if registered["direction"] == "decrease" else after - before
    context["after"] = after
    if not math.isfinite(delta):
        return _report("unavailable", "numeric_overflow", **context)
    outcome, tolerance = _compare(delta, context["expected"], "ge")
    return _report("supported" if outcome else "contradicted",
                   "prediction_supported" if outcome else "prediction_contradicted",
                   actual=delta, tolerance=tolerance, **context)
