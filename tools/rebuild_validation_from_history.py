"""Rebuild an empirical audit from native histories, including portable series archives."""
from __future__ import annotations

from collections import defaultdict
import json
from pathlib import Path
import sys

import numpy as np

from clustering_eval.experiments.plan_identity import scientific_id
from clustering_eval.metrics.paired_statistics import paired_bootstrap, summarize_metric
from clustering_eval.results.archive_history import GENERAL, archive_path, manifest_at, native_histories
from clustering_eval.results.archive_science import group_ids
from real_world_benchmark_v2 import json_safe


def derive_scenario(req: dict) -> str:
    """Reconstruct the original validated_* suite's four fixed federated cases."""
    if req["mode"] == "local":
        return "local_estimated" if req["cluster_count_mode"] == "estimated_k" else "local_known"
    base = "dirichlet_01" if req["partition_mode"] == "dirichlet" else "iid"
    return base + ("_partial" if req["participation_rate"] < 1 or req["dropout_rate"] > 0 else "_full")


def _measurement(result: dict, report: dict, scenario: str, path: Path) -> dict:
    state = result["model_state"]
    diag = state.get("diagnostics") or {}
    benchmark = state.get("benchmark") or {}
    partition = report.get("partition") or {}
    req = report["request"]
    return {
        "dataset": req["dataset_name"], "seed": req["seed"], "scenario": scenario,
        "algorithm": result["algorithm"], **{k: result.get(k) for k in ("ari", "ami", "nmi", "silhouette")},
        "coverage": diag.get("assigned_fraction"), "n_clusters": diag.get("cluster_count_excluding_noise"),
        "k": benchmark.get("target_clusters"), "cluster_count_source": benchmark.get("cluster_count_source"),
        "runtime_wall_with_preprocessing": diag.get("runtime_wall_including_preprocessing_sec"),
        "logical_communication_bytes": result.get("communication_bytes"),
        "degenerate": diag.get("degenerate"), "near_degenerate": diag.get("near_degenerate"),
        "client_worst_ari": ((diag.get("client_metrics") or {}).get("ari") or {}).get("worst"),
        "partition_fingerprint": partition.get("fingerprint"),
        "partition_js": (partition.get("heterogeneity") or {}).get("class_js_divergence_weighted_bits"),
        "pred_hash": diag.get("prediction_hash"), "metric_schema": diag.get("metric_schema_version"),
        "tuning": diag.get("unsupervised_parameter_tuning"), "history": str(path.parent),
    }


def _legacy_archive_group(series: str, scenario: str, report: dict, result: dict,
                          protocol: dict, source_head: str | None, ordinal: int) -> str:
    # Legacy results had no group_id. Retain explicit settings even when they happen
    # to equal the repeat seed, and isolate an entry when comparable data are unknown.
    req = dict(report["request"])
    req.pop("seed", None)
    state = result["model_state"]
    bench = state.get("benchmark") or {}
    source_run = state.get("source_run") or {}
    data = protocol.get("data_verification") or {}
    conditions = {
        "source_head": source_head, "x_sha256": data.get("x_sha256"), "y_sha256": data.get("y_sha256"),
        "scenario": scenario, "request": req, "algorithm": result["algorithm"], "backend": result.get("backend"),
        "params": bench.get("effective_params"), "preprocessing": bench.get("preprocessing"),
        "metric_schema": bench.get("metric_schema_version"), "evaluation_space": bench.get("evaluation_space"),
        "execution_resources": protocol.get("execution_resources"),
        "execution_profile": source_run.get("execution_profile"),
    }
    if any(conditions[key] is None for key in ("source_head", "x_sha256", "y_sha256", "params", "backend",
                                               "preprocessing", "evaluation_space", "metric_schema",
                                               "execution_resources")):
        conditions["unverified_entry"] = [series, report["experiment_id"], ordinal, source_run.get("run_id"), result["algorithm"]]
    return scientific_id("legacy-analysis-group", conditions)


def _measurements(root: Path, archive: bool) -> tuple[list[dict], int]:
    rows = []
    seen = set()
    if archive:
        manifest = manifest_at(root)
        paths = native_histories(root, manifest)
        groups = {}
        protocols = {}
        if manifest["format"] == GENERAL:
            plan = json.loads(archive_path(root, "reproduce/resolved_plan.json").read_text(encoding="utf-8"))
            groups = group_ids(plan)
        else:
            for series in manifest["series"]:
                protocol = archive_path(root, series["path"] + "/protocol.json")
                protocols[series["name"]] = json.loads(protocol.read_text(encoding="utf-8"))
    else:
        reports = sorted(root.glob("validated_*/history/*/report.json"))
        if not reports:
            raise SystemExit("No saved comparison reports found")
        paths = ((None, None, path) for path in reports)
    for series, scenario, path in paths:
        report = json.loads(path.read_text(encoding="utf-8"))
        key = (series, report["experiment_id"])
        if key in seen:
            raise ValueError(f"Repeated experiment ID: {key}")
        seen.add(key)
        if scenario is None:
            scenario = derive_scenario(report["request"])
        for ordinal, result in enumerate(report["results"]):
            row = _measurement(result, report, scenario, path)
            if archive:
                if manifest["format"] == GENERAL:
                    job_id = result["model_state"]["execution"]["job_id"]
                    group = groups[job_id]
                    row["job_id"] = job_id
                else:
                    group = _legacy_archive_group(series, scenario, report, result, protocols[series],
                                                  manifest.get("source_head"), ordinal)
                row.update(group_id=group, series=series, comparison_id=report["experiment_id"])
            rows.append(row)
    return rows, len(seen)


def _archive_pairs(rows: list[dict], left: str, right: str) -> list[dict]:
    """Pair only methods run in the same comparison and keep each grid variant separate."""
    comparisons = defaultdict(list)
    for row in rows:
        comparisons[row["series"], row["comparison_id"]].append(row)
    pairs = defaultdict(list)
    for batch in comparisons.values():
        for a in (row for row in batch if row["algorithm"] == left):
            for b in (row for row in batch if row["algorithm"] == right):
                pairs[a["group_id"], b["group_id"]].extend((a, b))
    output = []
    for (left_group, right_group), matched in pairs.items():
        keys = {(r["seed"], r["algorithm"], r["partition_fingerprint"]) for r in matched}
        if len(keys) != len(matched):
            raise ValueError(f"Ambiguous scientific repetitions for pair {left_group}, {right_group}")
        for summary in paired_bootstrap(matched, left=left, right=right):
            output.append(dict(summary, left_group_id=left_group, right_group_id=right_group))
    return output


def _validated_invariance(rows: list[dict]) -> list[dict]:
    matches = defaultdict(dict)
    methods = {"fed_kmeans_numpy", "fed_fuzzy_cmeans_numpy", "fed_gmm_diag_numpy"}
    for row in rows:
        if row["algorithm"] in methods and row["scenario"] in ("iid_full", "dirichlet_01_full"):
            key = (row["dataset"], row["seed"], row["algorithm"])
            matches[key].setdefault(row["scenario"], row)
    output = []
    for (dataset, seed, algorithm), pair in sorted(matches.items()):
        if len(pair) == 2:
            a, b = pair["iid_full"], pair["dirichlet_01_full"]
            same_ari = None if a["ari"] is None or b["ari"] is None else bool(np.isclose(a["ari"], b["ari"]))
            same_prediction = None if None in (a["pred_hash"], b["pred_hash"]) else a["pred_hash"] == b["pred_hash"]
            output.append(dict(dataset=dataset, seed=seed, algorithm=algorithm, same_ari=same_ari,
                               same_prediction=same_prediction, iid_js=a["partition_js"],
                               dirichlet_js=b["partition_js"]))
    return output


def main(source_root: str | Path, dest: str | Path) -> None:
    root = Path(source_root)
    archive = (root / "manifest.json").is_file()
    rows, n_comparisons = _measurements(root, archive)
    summaries = {
        "n_comparisons": n_comparisons, "n_results": len(rows),
        "unique_conditions": sorted({(r["dataset"], r["scenario"]) for r in rows}),
        "degenerate_counts": {}, "invariance_cases": [],
    }
    groups = defaultdict(list)
    for row in rows:
        group = row["group_id"] if archive else (row["dataset"], row["algorithm"])
        groups[group].append(row)
    for metric in ("ari", "ami"):
        if archive:
            summaries[metric] = [dict(summary, group_id=gid) for gid, batch in groups.items()
                                 for summary in summarize_metric(batch, metric)]
        else:
            summaries[metric] = summarize_metric(rows, metric)
    left = "fed_kmeans_numpy"
    for key, right in (("kmeans_minus_fuzzy_paired", "fed_fuzzy_cmeans_numpy"),
                       ("kmeans_minus_diag_gmm_paired", "fed_gmm_diag_numpy")):
        summaries[key] = (_archive_pairs(rows, left, right) if archive else
                          paired_bootstrap(rows, left=left, right=right))
    for key, batch in groups.items():
        title = key if archive else " / ".join(key)
        flags = [r["degenerate"] for r in batch if r["degenerate"] is not None]
        summaries["degenerate_counts"][title] = sum(flags) if flags else None
    if archive:
        summaries["invariance_status"] = "not_checked: archive defines no cross-scenario invariance pairs"
    else:
        summaries["invariance_cases"] = _validated_invariance(rows)
    dest = Path(dest)
    if archive and dest.resolve().is_relative_to(root.resolve()):
        raise ValueError("Analysis destination must be outside the source archive")
    dest.mkdir(parents=True, exist_ok=True)
    for name, value in (("empirical_rows.json", rows), ("empirical_summary.json", summaries)):
        (dest / name).write_text(json.dumps(json_safe(value), ensure_ascii=False, indent=2, allow_nan=False),
                                 encoding="utf-8")
    print("Reconstructed", n_comparisons, "actual comparisons,", len(rows), "actual algorithm results")
    print("Invariances:", sum(x["same_ari"] is True for x in summaries["invariance_cases"]),
          "/", len(summaries["invariance_cases"]))
    print("Degenerates:", sum(v for v in summaries["degenerate_counts"].values() if v is not None))
    for item in summaries["ari"]:
        print(item)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
