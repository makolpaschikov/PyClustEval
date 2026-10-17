from __future__ import annotations

from pathlib import Path
from zipfile import ZipFile

import numpy as np

from clustering_eval.application import ComparisonService, RunRequest
from clustering_eval.datasets.partitioning import (
    label_limited_partition,
    partition_class_counts,
    partition_fingerprint,
    quantity_skew_partition,
)
from clustering_eval.results import HistoryStore


def _assert_full_partition(partition: list[np.ndarray], n_samples: int) -> None:
    merged = np.concatenate(partition)
    assert len(merged) == n_samples
    assert sorted(int(v) for v in merged) == list(range(n_samples))


def test_quantity_skew_is_deterministic_and_unequal() -> None:
    first = quantity_skew_partition(150, 5, 42, min_samples_per_client=3)
    second = quantity_skew_partition(150, 5, 42, min_samples_per_client=3)
    _assert_full_partition(first, 150)
    assert partition_fingerprint(first) == partition_fingerprint(second)
    counts = [len(part) for part in first]
    assert counts == sorted(counts)
    assert counts[0] < counts[-1]
    assert sum(counts) == 150


def test_label_limited_caps_classes_per_client() -> None:
    y = np.repeat(np.arange(10), 20)
    partition = label_limited_partition(
        y, len(y), 5, 42, labels_per_client=2, min_samples_per_client=3
    )
    _assert_full_partition(partition, len(y))
    distributions = partition_class_counts(partition, y)
    assert all(1 <= len(item) <= 2 for item in distributions)
    assert set().union(*(set(item) for item in distributions)) == {str(i) for i in range(10)}


def test_service_reports_client_distribution_and_partition_callback(tmp_path: Path) -> None:
    service = ComparisonService(history_store=HistoryStore(tmp_path / "history"))
    seen = []
    report = service.compare(
        RunRequest(
            mode="federated",
            dataset_name="iris",
            algorithms=("fed_kmeans_numpy", "fed_fuzzy_cmeans_numpy"),
            seed=42,
            num_clients=5,
            partition_mode="label_limited",
        ),
        on_partition=seen.append,
    )
    assert report.partition is not None
    assert seen == [report.partition]
    assert len(report.partition.client_class_counts) == 5
    assert all(len(item) <= 2 for item in report.partition.client_class_counts)
    assert sum(report.partition.client_sample_counts) == report.n_samples


def test_excel_export_contains_results_and_partition_sheets(tmp_path: Path) -> None:
    service = ComparisonService(history_store=HistoryStore(tmp_path / "history"))
    report = service.compare(
        RunRequest(
            mode="federated",
            dataset_name="iris",
            algorithms=("fed_kmeans_numpy", "fed_fuzzy_cmeans_numpy"),
            seed=42,
            num_clients=5,
            partition_mode="quantity_skew",
        )
    )
    output = tmp_path / "comparison.xlsx"
    saved = Path(service.export_excel(report, str(output)))
    assert saved.exists()
    with ZipFile(saved) as archive:
        workbook_xml = archive.read("xl/workbook.xml").decode("utf-8")
        assert "Results" in workbook_xml
        assert "Partition" in workbook_xml
        assert "Configuration" in workbook_xml
        assert "Log" in workbook_xml
