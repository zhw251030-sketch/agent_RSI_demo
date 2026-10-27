#!/usr/bin/env python3
"""Fetch train/validation files for the independent SRSD Easy replication round."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.fetch_srsd_easy import _convert, _sha


DATASET = "yoshitomo-matsubara/srsd-feynman_easy"
BASE = f"https://huggingface.co/datasets/{DATASET}/resolve/main"
SELECTED = {
    "srsd-feynman-i12-5": "feynman-i.12.5",
    "srsd-feynman-i14-3": "feynman-i.14.3",
}


def _get(url: str, attempts: int = 3) -> bytes:
    error = None
    for attempt in range(attempts):
        try:
            with urlopen(url, timeout=120) as response:  # noqa: S310 - fixed public HTTPS base
                return response.read()
        except Exception as exc:
            error = exc
            if attempt + 1 < attempts:
                time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"download failed after {attempts} attempts: {url}") from error


def fetch(root: Path, *, include_test: bool = False) -> dict:
    root.mkdir(parents=True, exist_ok=True)
    supp_raw = _get(f"{BASE}/supp_info.json?download=true")
    supp = json.loads(supp_raw.decode("utf-8"))
    result = {
        "schema": "srsd-feynman-easy-replication-source-v0.1",
        "dataset": DATASET,
        "dataset_card_url": f"https://huggingface.co/datasets/{DATASET}",
        "source_license": "CC-BY-4.0",
        "source_split_policy": "train and val are public development files; test is reserved",
        "official_test_read": False, "official_test_ood_read": False,
        "supp_info_sha256": _sha(supp_raw), "tasks": {},
    }
    for task_id, source_id in SELECTED.items():
        metadata = supp[source_id]
        task_dir = root / task_id
        task_dir.mkdir(parents=True, exist_ok=True)
        record = {"source_id": source_id, "equation": metadata["sympy_eq_str"],
                  "symbols": metadata["symbols"], "symbols_descs": metadata["symbols_descs"], "files": {}}
        for split in ("train", "val", "test"):
            url = f"{BASE}/{split}/{source_id}.txt?download=true"
            file_record = {"url": url, "read": False}
            if split != "test" or include_test:
                raw = _get(url)
                path = task_dir / f"{split}.txt"
                path.write_bytes(raw)
                rows, csv_sha = _convert(raw, path)
                file_record.update({"read": True, "raw_sha256": _sha(raw), "raw_bytes": len(raw),
                                    "row_count": rows,
                                    "csv_path": str(path.with_suffix(".csv").relative_to(ROOT)).replace("\\", "/"),
                                    "csv_sha256": csv_sha})
            record["files"][split] = file_record
        result["tasks"][task_id] = record
    result["manifest_sha256"] = _sha(json.dumps(result, ensure_ascii=False, sort_keys=True,
                                                  separators=(",", ":")).encode("utf-8"))
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT / "data/external/srsd-feynman-easy-replication")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--include-test", action="store_true")
    args = parser.parse_args()
    report = fetch(args.root, include_test=args.include_test)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "fetched", "manifest_sha256": report["manifest_sha256"],
                      "official_test_read": report["official_test_read"],
                      "tasks": {task: {split: value["files"][split].get("row_count")
                                        for split in ("train", "val", "test")}
                                for task, value in report["tasks"].items()}},
                     ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
