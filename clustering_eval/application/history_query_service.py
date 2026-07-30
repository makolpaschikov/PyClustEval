from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from .dto import (
    AlgorithmRunReport,
    HistoryExperimentDetails,
    HistoryExperimentSummary,
    PartitionReport,
)


class HistoryQueryService:
    """Read-only access to persisted experiment history.

    The UI receives typed DTOs and never reads JSON/CSV files directly.
    """

    def __init__(self, root: str | Path = "history") -> None:
        self.root = Path(root)

    def list_experiments(
        self,
        *,
        limit: int | None = None,
    ) -> list[HistoryExperimentSummary]:
        if not self.root.exists():
            return []

        summaries: list[HistoryExperimentSummary] = []
        for directory in self.root.iterdir():
            if not directory.is_dir():
                continue
            report_path = directory / "report.json"
            if not report_path.is_file():
                continue
            try:
                payload = self._read_json(report_path)
                summaries.append(self._to_summary(directory.name, payload))
            except (OSError, ValueError, TypeError, KeyError):
                # One damaged experiment must not hide the rest of history.
                continue

        summaries.sort(key=lambda item: item.started_at, reverse=True)
        return summaries if limit is None else summaries[: max(limit, 0)]

    def get_experiment(self, history_key: str) -> HistoryExperimentDetails:
        directory = self._resolve_directory(history_key)
        payload = self._read_json(directory / "report.json")
        log_path = directory / "execution.log"
        log_text = log_path.read_text(encoding="utf-8") if log_path.exists() else ""
        return self._to_details(directory.name, payload, log_text)

    def _resolve_directory(self, history_key: str) -> Path:
        if not history_key or Path(history_key).name != history_key:
            raise ValueError("Invalid history key")
        directory = self.root / history_key
        if not directory.is_dir():
            raise FileNotFoundError(f"History experiment not found: {history_key}")
        return directory

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if not isinstance(payload, dict):
            raise ValueError(f"Invalid report format: {path}")
        return payload

    @staticmethod
    def _parse_datetime(value: Any) -> datetime:
        if not isinstance(value, str):
            raise TypeError("Expected ISO datetime string")
        return datetime.fromisoformat(value)

    def _to_summary(
        self,
        history_key: str,
        payload: dict[str, Any],
    ) -> HistoryExperimentSummary:
        request = self._request(payload)
        results = self._result_payloads(payload)
        algorithms = tuple(
            str(item.get("algorithm", "unknown")) for item in results
        ) or tuple(str(item) for item in request.get("algorithms", []))
        started_at = self._parse_datetime(payload["started_at"])
        duration = float(payload.get("duration_sec", 0.0))
        return HistoryExperimentSummary(
            history_key=history_key,
            experiment_id=str(payload.get("experiment_id", history_key)),
            started_at=started_at,
            mode=str(request["mode"]),  # type: ignore[arg-type]
            dataset_name=str(request["dataset_name"]),
            algorithms=algorithms,
            duration_sec=duration,
            result_count=len(results),
        )

    def _to_details(
        self,
        history_key: str,
        payload: dict[str, Any],
        log_text: str,
    ) -> HistoryExperimentDetails:
        request = self._request(payload)
        results = [self._to_algorithm_result(item) for item in self._result_payloads(payload)]
        partition = self._to_partition(payload.get("partition"))
        algorithms = tuple(result.algorithm for result in results)
        if not algorithms:
            algorithms = tuple(str(item) for item in request.get("algorithms", []))
        return HistoryExperimentDetails(
            history_key=history_key,
            experiment_id=str(payload.get("experiment_id", history_key)),
            started_at=self._parse_datetime(payload["started_at"]),
            finished_at=self._parse_datetime(payload["finished_at"]),
            mode=str(request["mode"]),  # type: ignore[arg-type]
            dataset_name=str(request["dataset_name"]),
            dataset_display_name=str(
                payload.get("dataset_display_name", request["dataset_name"])
            ),
            n_samples=int(payload.get("n_samples", 0)),
            n_features=int(payload.get("n_features", 0)),
            seed=int(request.get("seed", 42)),
            algorithms=algorithms,
            results=results,
            duration_sec=float(payload.get("duration_sec", 0.0)),
            partition=partition,
            log_text=log_text,
        )

    @staticmethod
    def _request(payload: dict[str, Any]) -> dict[str, Any]:
        request = payload.get("request")
        if not isinstance(request, dict):
            raise ValueError("Report does not contain a request object")
        return request

    @staticmethod
    def _result_payloads(payload: dict[str, Any]) -> list[dict[str, Any]]:
        results = payload.get("results", [])
        if not isinstance(results, list):
            raise ValueError("Report results must be a list")
        return [item for item in results if isinstance(item, dict)]

    @staticmethod
    def _to_algorithm_result(item: dict[str, Any]) -> AlgorithmRunReport:
        return AlgorithmRunReport(
            algorithm=str(item.get("algorithm", "unknown")),
            backend=str(item.get("backend", "unknown")),
            runtime_sec=float(item.get("runtime_sec", 0.0)),
            communication_bytes=int(item.get("communication_bytes", 0)),
            rounds=item.get("rounds", "—"),
            ari=_optional_float(item.get("ari")),
            nmi=_optional_float(item.get("nmi")),
            silhouette=_optional_float(item.get("silhouette")),
            davies_bouldin=_optional_float(item.get("davies_bouldin")),
            calinski_harabasz=_optional_float(item.get("calinski_harabasz")),
            model_state=dict(item.get("model_state") or {}),
            history=list(item.get("history") or []),
        )

    @staticmethod
    def _to_partition(value: Any) -> PartitionReport | None:
        if not isinstance(value, dict):
            return None
        return PartitionReport(
            mode=str(value.get("mode", "iid")),  # type: ignore[arg-type]
            num_clients=int(value.get("num_clients", 0)),
            client_sample_counts=[
                int(item) for item in value.get("client_sample_counts", [])
            ],
            fingerprint=str(value.get("fingerprint", "")),
            dirichlet_alpha=_optional_float(value.get("dirichlet_alpha")),
        )


def _optional_float(value: Any) -> float | None:
    return None if value is None else float(value)
