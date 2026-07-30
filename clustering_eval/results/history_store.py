from __future__ import annotations

import csv
import json
import os
import re
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

import numpy as np

from ..application.dto import ComparisonReport


CSV_COLUMNS = (
    "experiment_id",
    "started_at",
    "finished_at",
    "mode",
    "dataset",
    "algorithm",
    "backend",
    "runtime_sec",
    "communication_bytes",
    "rounds",
    "ari",
    "nmi",
    "silhouette",
    "davies_bouldin",
    "calinski_harabasz",
    "partition_id",
    "num_clients",
)


def _json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, set):
        return sorted(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _safe_component(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())
    return cleaned.strip("._") or "experiment"


class HistoryStore:
    """Persists every completed comparison in history/<datetime>/."""

    def __init__(self, root: str | Path = "history") -> None:
        self.root = Path(root)

    def save(self, report: ComparisonReport) -> Path:
        timestamp = report.started_at.strftime("%Y-%m-%d_%H-%M-%S")
        base_name = _safe_component(timestamp)
        destination = self._unique_directory(base_name)
        destination.mkdir(parents=True, exist_ok=False)

        report.history_directory = destination
        self._write_json_atomic(destination / "report.json", report.to_dict())
        self._write_csv_atomic(destination / "results.csv", report)
        self._write_text_atomic(
            destination / "execution.log",
            "".join(report.log_lines),
        )
        return destination

    def refresh_report(self, report: ComparisonReport) -> None:
        """Rewrite mutable report metadata and log after final UI messages."""
        if report.history_directory is None:
            raise ValueError("Report has not been saved yet")
        destination = Path(report.history_directory)
        self._write_json_atomic(destination / "report.json", report.to_dict())
        self._write_text_atomic(
            destination / "execution.log",
            "".join(report.log_lines),
        )

    def _unique_directory(self, base_name: str) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        candidate = self.root / base_name
        suffix = 2
        while candidate.exists():
            candidate = self.root / f"{base_name}_{suffix}"
            suffix += 1
        return candidate

    def _write_json_atomic(self, path: Path, payload: dict[str, Any]) -> None:
        content = json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            default=_json_default,
        )
        self._write_text_atomic(path, content + "\n")

    def _write_csv_atomic(self, path: Path, report: ComparisonReport) -> None:
        with NamedTemporaryFile(
            "w",
            encoding="utf-8-sig",
            newline="",
            dir=path.parent,
            delete=False,
        ) as handle:
            writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
            writer.writeheader()

            partition_id = report.partition.fingerprint if report.partition else ""
            num_clients = report.partition.num_clients if report.partition else ""

            for result in report.results:
                writer.writerow(
                    {
                        "experiment_id": report.experiment_id,
                        "started_at": report.started_at.isoformat(),
                        "finished_at": report.finished_at.isoformat(),
                        "mode": report.request.mode,
                        "dataset": report.request.dataset_name,
                        "algorithm": result.algorithm,
                        "backend": result.backend,
                        "runtime_sec": result.runtime_sec,
                        "communication_bytes": result.communication_bytes,
                        "rounds": result.rounds,
                        "ari": result.ari,
                        "nmi": result.nmi,
                        "silhouette": result.silhouette,
                        "davies_bouldin": result.davies_bouldin,
                        "calinski_harabasz": result.calinski_harabasz,
                        "partition_id": partition_id,
                        "num_clients": num_clients,
                    }
                )
            temp_path = Path(handle.name)
        os.replace(temp_path, path)

    def _write_text_atomic(self, path: Path, content: str) -> None:
        with NamedTemporaryFile(
            "w",
            encoding="utf-8",
            newline="",
            dir=path.parent,
            delete=False,
        ) as handle:
            handle.write(content)
            temp_path = Path(handle.name)
        os.replace(temp_path, path)
