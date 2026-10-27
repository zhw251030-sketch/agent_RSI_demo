#!/usr/bin/env python3
"""Fetch a small, provenance-traceable SRSD-Feynman Easy development pack.

Only the public train and validation files are downloaded by default.  The
official test URL is recorded but not fetched or inspected unless
``--include-test`` is supplied after the external protocol is frozen.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]
DATASET = "yoshitomo-matsubara/srsd-feynman_easy"
BASE = f"https://huggingface.co/datasets/{DATASET}/resolve/main"
SELECTED = {
    "srsd-feynman-i12-1": "feynman-i.12.1",
    "srsd-feynman-i14-4": "feynman-i.14.4",
    "srsd-feynman-ii8-31": "feynman-ii.8.31",
}


def _get(url: str) -> bytes:
    with urlopen(url, timeout=120) as response:  # noqa: S310 - fixed public HTTPS base
        return response.read()


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _convert(raw: bytes, path: Path) -> tuple[int, str]:
    lines = [line for line in raw.decode("utf-8").splitlines() if line.strip()]
    if not lines:
        raise ValueError(f"empty source file: {path}")
    parsed = [line.split() for line in lines]
    n_columns = len(parsed[0])
    if n_columns < 2 or any(len(row) != n_columns for row in parsed):
        raise ValueError(f"inconsistent numeric columns: {path}")
    headers = [f"x{i}" for i in range(n_columns - 1)] + ["y"]
    out = path.with_suffix(".csv")
    with out.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(headers)
        writer.writerows(parsed)
    return len(parsed), _sha(out.read_bytes())


def fetch(root: Path, *, include_test: bool = False) -> dict:
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    supp_url = f"{BASE}/supp_info.json"
    supp_raw = _get(supp_url)
    supp = json.loads(supp_raw.decode("utf-8"))
    result = {
        "schema": "srsd-feynman-easy-source-v0.1",
        "dataset": DATASET,
        "dataset_card_url": f"https://huggingface.co/datasets/{DATASET}",
        "source_license": "CC-BY-4.0",
        "source_split_policy": "train and val are public development files; test is reserved",
        "official_test_read": False,
        "official_test_ood_read": False,
        "supp_info_sha256": _sha(supp_raw),
        "tasks": {},
    }
    for task_id, source_id in SELECTED.items():
        metadata = supp[source_id]
        task_dir = root / task_id
        task_dir.mkdir(parents=True, exist_ok=True)
        task_record = {
            "source_id": source_id,
            "equation": metadata["sympy_eq_str"],
            "symbols": metadata["symbols"],
            "symbols_descs": metadata["symbols_descs"],
            "files": {},
        }
        for split in ("train", "val", "test"):
            url = f"{BASE}/{split}/{source_id}.txt"
            file_record = {"url": url, "read": False}
            if split != "test" or include_test:
                raw = _get(url)
                source_path = task_dir / f"{split}.txt"
                source_path.write_bytes(raw)
                n_rows, csv_sha = _convert(raw, source_path)
                file_record.update({
                    "read": True,
                    "raw_sha256": _sha(raw),
                    "raw_bytes": len(raw),
                    "row_count": n_rows,
                    "csv_path": str(source_path.with_suffix(".csv").relative_to(ROOT)).replace("\\", "/"),
                    "csv_sha256": csv_sha,
                })
            task_record["files"][split] = file_record
        result["tasks"][task_id] = task_record
    payload = json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    result["manifest_sha256"] = _sha(payload.encode("utf-8"))
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT / "data/external/srsd-feynman-easy")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--include-test", action="store_true")
    args = parser.parse_args()
    report = fetch(args.root, include_test=args.include_test)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": "fetched",
        "manifest_sha256": report["manifest_sha256"],
        "official_test_read": report["official_test_read"],
        "tasks": {task: {
            split: value["files"][split].get("row_count")
            for split in ("train", "val", "test")
        } for task, value in report["tasks"].items()},
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
