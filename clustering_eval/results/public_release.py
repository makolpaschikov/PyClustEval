"""Fail closed: prevent accidental public release of the trusted DP benchmark.

Input perturbation is not end-to-end DP. A sanitized report with statistical
claims of DP requires a separately audited end-to-end accounting mechanism.
"""
from __future__ import annotations

from typing import Any
from ..application.dto import ComparisonReport


def build_public_report(report: ComparisonReport) -> dict[str, Any]:
    if report.request.privacy_mode != "none":
        raise PermissionError(
            "PUBLIC RELEASE BLOCKED: Gaussian input perturbation does not make "
            "the report (which uses clean X, y, partitions and metrics) DP. "
            "Keep full report inside the trusted evaluation boundary."
        )
    return {
        "experiment_id": report.experiment_id,
        "dataset": report.request.dataset_name,
        "algorithm_results": [
            {"algorithm": r.algorithm, "ari": r.ari, "ami": r.ami,
             "nmi": r.nmi, "silhouette": r.silhouette,
             "logical_communication_bytes": r.communication_bytes,
             "runtime_algorithm_reported_sec": r.runtime_sec,
             "metric_schema_version": (r.model_state.get("diagnostics") or {}).get("metric_schema_version")}
            for r in report.results
        ],
        "publication_note": "This is a NON-private research report; no DP claim.",
    }
