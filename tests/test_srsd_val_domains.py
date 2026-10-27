import csv

from analysis.replacement_evidence.external_task_config import EXTERNAL_TASK_DEFINITIONS
from scripts.build_srsd_easy_val_domains import build_task_report


def _write(path, rows):
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(("x0", "x1", "y"))
        writer.writerows(rows)


def test_val_blocks_use_train_fit_rules_and_have_reproducible_rows(tmp_path):
    train = tmp_path / "train.csv"
    val = tmp_path / "val.csv"
    train_rows = [[i / 10, (i % 10) / 10, (i / 10) * ((i % 10) / 10)] for i in range(100)]
    val_rows = [[i / 10 + 0.05, (i % 10) / 10, (i / 10 + 0.05) * ((i % 10) / 10)] for i in range(100)]
    _write(train, train_rows)
    _write(val, val_rows)
    report = build_task_report(
        task_id="srsd-feynman-i12-1",
        definition=EXTERNAL_TASK_DEFINITIONS[0],
        train_path=train,
        val_path=val,
        fit_indices=list(range(60)),
        min_rows=1,
    )
    assert report["fit_row_count"] == 60
    assert report["val_row_count"] == 100
    assert report["ordinary"]["source_split"] == "val_external"
    assert all(block["source_split"] == "val_external" for block in report["blocks"])
    assert all(len(block["source_row_indices"]) == block["n_rows"] for block in report["blocks"])
    assert len(report["blocks"]) >= 2
