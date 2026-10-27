#!/usr/bin/env python3
"""Fetch only the five-input i14.4 Easy-Dummy development files."""

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


DATASET = "yoshitomo-matsubara/srsd-feynman_easy_dummy"
BASE = f"https://huggingface.co/datasets/{DATASET}/resolve/main"
TASK_ID = "srsd-feynman-i14-4-dummy-v02"
SOURCE_ID = "feynman-i.14.4"


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
    metadata = supp[SOURCE_ID]
    task_dir = root / TASK_ID
    task_dir.mkdir(parents=True, exist_ok=True)
    record = {"source_id": SOURCE_ID, "equation": metadata["sympy_eq_str"],
              "symbols": metadata["symbols"], "symbols_descs": metadata["symbols_descs"], "files": {}}
    for split in ("train", "val", "test"):
        url = f"{BASE}/{split}/{SOURCE_ID}.txt?download=true"
        item = {"url": url, "read": False}
        if split != "test" or include_test:
            raw = _get(url)
            path = task_dir / f"{split}.txt"
            path.write_bytes(raw)
            rows, csv_sha = _convert(raw, path)
            item.update({"read": True, "raw_sha256": _sha(raw), "raw_bytes": len(raw),
                         "row_count": rows,
                         "csv_path": str(path.with_suffix(".csv").relative_to(ROOT)).replace("\\", "/"),
                         "csv_sha256": csv_sha})
        record["files"][split] = item
    result = {"schema": "srsd-feynman-easy-dummy-i144-v02-source-v0.1",
              "dataset": DATASET,
              "dataset_card_url": f"https://huggingface.co/datasets/{DATASET}",
              "source_license": "CC-BY-4.0",
              "source_split_policy": "train and val are public development files; test is reserved",
              "official_test_read": False, "official_test_ood_read": False,
              "supp_info_sha256": _sha(supp_raw), "tasks": {TASK_ID: record}}
    result["manifest_sha256"] = _sha(json.dumps(result, ensure_ascii=False, sort_keys=True,
                                                  separators=(",", ":")).encode("utf-8"))
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT / "data/external/srsd-feynman-easy-dummy-i144-v02")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--include-test", action="store_true")
    args = parser.parse_args()
    report = fetch(args.root, include_test=args.include_test)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "fetched", "manifest_sha256": report["manifest_sha256"],
                      "official_test_read": report["official_test_read"],
                      "row_counts": {split: value.get("row_count")
                                     for split, value in report["tasks"][TASK_ID]["files"].items()}},
                     ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
