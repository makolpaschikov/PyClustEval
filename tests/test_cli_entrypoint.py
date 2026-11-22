from __future__ import annotations

import csv
import json
from pathlib import Path
import subprocess
import sys


def test_run_from_fresh_process(tmp_path: Path) -> None:
    """The CLI must start without a prior import of the application services."""
    output = tmp_path / "results"
    config = tmp_path / "small run.yaml"
    config.write_text(json.dumps({
        "experiment": {"output_dir": str(output)},
        "datasets": [{"name": "iris"}],
        "algorithms": [{"name": "kmeans"}],
        "metrics": ["ari"],
    }), encoding="utf-8")

    subprocess.run(
        [sys.executable, "-m", "clustering_eval.cli", "run", str(config)],
        cwd=Path(__file__).resolve().parents[1],
        check=True,
        timeout=60,
    )

    with (output / "metrics.csv").open(encoding="utf-8", newline="") as stream:
        row, = csv.DictReader(stream)
    record = json.loads((output / "history.jsonl").read_text(encoding="utf-8"))
    assert row["dataset_name"] == record["spec"]["dataset_name"] == "iris"
    assert row["algorithm_name"] == record["spec"]["algorithm_name"] == "kmeans"
