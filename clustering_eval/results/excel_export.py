from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import xlsxwriter

from ..application.dto import ComparisonReport


def _jsonable(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    return value


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list, tuple, set, np.ndarray)):
        return json.dumps(_jsonable(value), ensure_ascii=False, sort_keys=True)
    return str(_jsonable(value))


def export_comparison_xlsx(report: ComparisonReport, destination: str | Path) -> Path:
    """Export one completed comparison to a readable Excel workbook."""
    path = Path(destination)
    if path.suffix.lower() != ".xlsx":
        path = path.with_suffix(".xlsx")
    path.parent.mkdir(parents=True, exist_ok=True)

    workbook = xlsxwriter.Workbook(path)
    title = workbook.add_format({
        "bold": True, "font_size": 16, "font_color": "white",
        "bg_color": "#17365D", "align": "center", "valign": "vcenter",
    })
    header = workbook.add_format({
        "bold": True, "font_color": "white", "bg_color": "#2F5597",
        "border": 1, "align": "center", "valign": "vcenter",
    })
    subheader = workbook.add_format({
        "bold": True, "bg_color": "#D9EAF7", "border": 1,
    })
    cell = workbook.add_format({"border": 1})
    integer = workbook.add_format({"border": 1, "num_format": "0"})
    number = workbook.add_format({"border": 1, "num_format": "0.0000"})
    wrap = workbook.add_format({"border": 1, "text_wrap": True, "valign": "top"})
    good = workbook.add_format({"border": 1, "bg_color": "#E2F0D9"})
    warn = workbook.add_format({"border": 1, "bg_color": "#FCE4D6"})

    # Results
    ws = workbook.add_worksheet("Results")
    ws.merge_range("A1:R1", "PyClustEval — comparison report", title)
    metadata = [
        ("Experiment ID", report.experiment_id),
        ("Started", report.started_at.isoformat()),
        ("Finished", report.finished_at.isoformat()),
        ("Mode", report.request.mode),
        ("Dataset", report.request.dataset_name),
        ("Dataset display name", report.dataset_display_name),
        ("Shape", f"{report.n_samples} × {report.n_features}"),
        ("Seed", report.request.seed),
        ("Participation", report.request.participation_rate if report.request.mode == "federated" else ""),
        ("Dropout", report.request.dropout_rate if report.request.mode == "federated" else ""),
        ("Privacy", report.request.privacy_mode if report.request.mode == "federated" else "none"),
    ]
    for row, (name, value) in enumerate(metadata, start=2):
        ws.write(row - 1, 0, name, subheader)
        ws.write(row - 1, 1, value, cell)

    table_row = len(metadata) + 3
    columns = [
        "Algorithm", "Backend", "Runtime, s", "Traffic, bytes", "Rounds",
        "ARI", "NMI", "Silhouette", "Davies-Bouldin", "Calinski-Harabasz",
        "Status", "Preprocessing", "Participation", "Dropout", "Privacy",
        "DP epsilon", "DP delta", "DP clip norm",
    ]
    for col, value in enumerate(columns):
        ws.write(table_row, col, value, header)

    for offset, result in enumerate(report.results, start=1):
        row = table_row + offset
        diagnostics = dict(result.model_state.get("diagnostics") or {})
        benchmark = dict(result.model_state.get("benchmark") or {})
        status = "degenerate" if diagnostics.get("degenerate") else (
            "near_degenerate" if diagnostics.get("near_degenerate") else "ok"
        )
        row_fmt = warn if status != "ok" else cell
        values = [
            result.algorithm,
            result.backend,
            result.runtime_sec,
            result.communication_bytes,
            result.rounds,
            result.ari,
            result.nmi,
            result.silhouette,
            result.davies_bouldin,
            result.calinski_harabasz,
            status,
            benchmark.get("preprocessing", ""),
            benchmark.get("participation_rate", ""),
            benchmark.get("dropout_rate", ""),
            benchmark.get("privacy_mode", "none"),
            benchmark.get("dp_epsilon", ""),
            benchmark.get("dp_delta", ""),
            benchmark.get("dp_clip_norm", ""),
        ]
        for col, value in enumerate(values):
            if col in (2, 5, 6, 7, 8, 9, 12, 13, 15, 16, 17) and isinstance(value, (int, float)):
                ws.write_number(row, col, float(value), number)
            elif col in (3,) and isinstance(value, (int, float)):
                ws.write_number(row, col, float(value), integer)
            else:
                ws.write(row, col, "" if value is None else value, row_fmt)

    ws.autofilter(table_row, 0, table_row + len(report.results), len(columns) - 1)
    ws.freeze_panes(table_row + 1, 0)
    ws.set_column("A:A", 27)
    ws.set_column("B:B", 18)
    ws.set_column("C:K", 16)
    ws.set_column("L:L", 18)
    ws.set_column("M:R", 14)
    if report.results:
        ws.conditional_format(table_row + 1, 5, table_row + len(report.results), 7, {
            "type": "3_color_scale",
            "min_color": "#F4CCCC", "mid_color": "#FFF2CC", "max_color": "#D9EAD3",
        })
        ws.conditional_format(table_row + 1, 8, table_row + len(report.results), 8, {
            "type": "3_color_scale",
            "min_color": "#D9EAD3", "mid_color": "#FFF2CC", "max_color": "#F4CCCC",
        })

    # Partition distribution
    if report.partition is not None:
        ps = workbook.add_worksheet("Partition")
        ps.merge_range("A1:F1", "Client data distribution", title)
        ps.write_row("A3", [
            "Mode", "Partition ID", "Clients", "Dirichlet alpha",
            "Participation", "Dropout",
        ], header)
        ps.write_row(3, 0, [
            report.partition.mode,
            report.partition.fingerprint,
            report.partition.num_clients,
            report.partition.dirichlet_alpha if report.partition.dirichlet_alpha is not None else "",
            report.partition.participation_rate,
            report.partition.dropout_rate,
        ], cell)
        ps.write_row("A6", ["Client", "Samples", "Class counts", "Classes"], header)
        for client_id, sample_count in enumerate(report.partition.client_sample_counts, start=1):
            distribution = (
                report.partition.client_class_counts[client_id - 1]
                if client_id - 1 < len(report.partition.client_class_counts)
                else {}
            )
            class_text = " | ".join(f"{label}: {count}" for label, count in distribution.items())
            ps.write(client_id + 5, 0, f"Client {client_id}", cell)
            ps.write_number(client_id + 5, 1, int(sample_count), integer)
            ps.write(client_id + 5, 2, class_text, wrap)
            ps.write_number(client_id + 5, 3, len(distribution), integer)
        ps.set_column("A:A", 16)
        ps.set_column("B:B", 12)
        ps.set_column("C:C", 55)
        ps.set_column("D:D", 12)
        ps.set_column("E:F", 14)
        ps.freeze_panes(6, 0)

        if report.partition.round_schedule:
            schedule_row = 7 + len(report.partition.client_sample_counts)
            ps.write(schedule_row, 0, "Participation / dropout schedule", subheader)
            ps.write_row(
                schedule_row + 1,
                0,
                ["Round", "Selected clients", "Successful clients", "Dropped clients"],
                header,
            )
            for offset, entry in enumerate(report.partition.round_schedule, start=1):
                selected = [int(value) + 1 for value in entry.get("selected_clients", [])]
                successful = [int(value) + 1 for value in entry.get("successful_clients", [])]
                dropped = [int(value) + 1 for value in entry.get("dropped_clients", [])]
                ps.write_number(schedule_row + 1 + offset, 0, int(entry.get("round", offset)), integer)
                ps.write(schedule_row + 1 + offset, 1, _stringify(selected), cell)
                ps.write(schedule_row + 1 + offset, 2, _stringify(successful), cell)
                ps.write(schedule_row + 1 + offset, 3, _stringify(dropped), cell)

    # Benchmark configuration / effective params.
    cs = workbook.add_worksheet("Configuration")
    cs.merge_range("A1:D1", "Benchmark configuration", title)
    request_items = [
        ("dataset_name", report.request.dataset_name),
        ("algorithms", list(report.request.algorithms)),
        ("seed", report.request.seed),
        ("num_clients", report.request.num_clients),
        ("partition_mode", report.request.partition_mode),
        ("dirichlet_alpha", report.request.dirichlet_alpha),
        ("target_clusters", report.request.target_clusters),
        ("rounds", report.request.rounds),
        ("tol", report.request.tol),
        ("max_iter", report.request.max_iter),
        ("density_min_samples", report.request.density_min_samples),
        ("min_samples_per_client", report.request.min_samples_per_client),
        ("labels_per_client", report.request.labels_per_client),
        ("participation_rate", report.request.participation_rate),
        ("dropout_rate", report.request.dropout_rate),
        ("privacy_mode", report.request.privacy_mode),
        ("dp_epsilon", report.request.dp_epsilon if report.request.privacy_mode == "gaussian_dp" else None),
        ("dp_delta", report.request.dp_delta if report.request.privacy_mode == "gaussian_dp" else None),
        ("dp_clip_norm", report.request.dp_clip_norm if report.request.privacy_mode == "gaussian_dp" else None),
    ]
    cs.write_row("A3", ["Setting", "Value"], header)
    for row, (name, value) in enumerate(request_items, start=3):
        cs.write(row, 0, name, cell)
        cs.write(row, 1, _stringify(value), cell)

    alg_start = 3 + len(request_items) + 2
    cs.write_row(alg_start, 0, ["Algorithm", "Effective params", "Diagnostics", "Model-state summary"], header)
    for offset, result in enumerate(report.results, start=1):
        benchmark = dict(result.model_state.get("benchmark") or {})
        diagnostics = dict(result.model_state.get("diagnostics") or {})
        state_summary = {k: v for k, v in result.model_state.items() if k not in {"benchmark", "diagnostics"}}
        cs.write(alg_start + offset, 0, result.algorithm, cell)
        cs.write(alg_start + offset, 1, _stringify(benchmark.get("effective_params", {})), wrap)
        cs.write(alg_start + offset, 2, _stringify(diagnostics), wrap)
        cs.write(alg_start + offset, 3, _stringify(state_summary), wrap)
    cs.set_column("A:A", 27)
    cs.set_column("B:D", 55)

    if report.request.privacy_mode == "gaussian_dp":
        privacy = workbook.add_worksheet("Privacy")
        privacy.merge_range("A1:B1", "Gaussian DP configuration", title)
        privacy.write_row("A3", ["Setting", "Value"], header)
        privacy_items = list((report.privacy_report or {}).items())
        for row, (name, value) in enumerate(privacy_items, start=3):
            privacy.write(row, 0, str(name), cell)
            privacy.write(row, 1, _stringify(value), wrap)
        privacy.set_column("A:A", 30)
        privacy.set_column("B:B", 90)

    # Execution log.
    ls = workbook.add_worksheet("Log")
    ls.write("A1", "Execution log", header)
    for row, line in enumerate(report.log_lines, start=1):
        ls.write(row, 0, line.rstrip("\n"))
    ls.set_column("A:A", 120)

    workbook.close()
    return path
