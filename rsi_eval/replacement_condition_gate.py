"""Condition names for the replacement-sufficiency round.

The historical gate calls its evidence arm ``real_check``.  This round uses
the protocol name ``replacement_check`` so old measured-v02 records remain
unchanged while the new report is self-consistent.
"""

from __future__ import annotations

from typing import Any

from .edit_condition_gate import apply_gate as _apply_historical_gate


CONDITIONS = ("no_check", "sham_check", "replacement_check")


def apply_gate(edit: dict[str, Any], *, condition: str, check_id: str,
               replacement_status: str | None = None,
               scope: str = "development") -> dict[str, Any]:
    if condition not in CONDITIONS:
        raise ValueError("unknown replacement condition")
    internal = "real_check" if condition == "replacement_check" else condition
    result = _apply_historical_gate(
        edit, condition=internal, check_id=check_id,
        real_status=replacement_status if condition == "replacement_check" else None,
        scope=scope,
    )
    result = dict(result)
    result["condition"] = condition
    return result

