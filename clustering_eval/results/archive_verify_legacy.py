"""Verify evidence actually present in historical paper archives."""
from __future__ import annotations

from collections import defaultdict

import numpy as np

from ..application.history_query_service import HistoryQueryService
from ..experiments.archive_inputs import REPRODUCE
from ..experiments.archive_protocol import check_schedule
from .archive_verify import Archive, check_cells, checking, expect, file_sha, index
from .archive_verify_science import (
    FLAT, METRICS, check_dataset, check_native, check_partition, check_summary, label_evidence, prediction,
)


def _series(a: Archive, series: dict, y: np.ndarray) -> list[dict]:
    folder = series["path"]
    archive_path = lambda name: f"{folder}/{name}"
    name = series["name"]
    protocol = a.json(archive_path("protocol.json"))
    plan = index(a.json(archive_path("experiment_plan.json")), "id", folder)
    parts = a.json(archive_path("partitions.json"))
    collection = a.json(archive_path("report.json"))
    rows = a.csv(archive_path("results.csv"), FLAT)
    by_id = index(rows, "run_id", folder)
    runs = index([dict(id=r["job"]["id"], run=r) for r in collection["runs"]], "id", folder)
    experiments = index(collection["experiments"], "scenario", folder)
    expect(protocol == collection["protocol"] and collection["format"] == "pyclusteval.benchmark-series.v1"
           and protocol["series"] == name == collection["series"] and protocol["dataset_name"] == series["dataset"]
           and series["seed"] == protocol["seed"] == collection["seed"], folder, "legacy protocol mismatch")
    expect(plan.keys() == by_id.keys() == runs.keys() and
           len(plan) == series["run_count"] == collection["run_count"] and
           len(experiments) == series["comparison_count"] == collection["comparison_count"],
           folder, "legacy planned run/comparison counts")
    groups = defaultdict(list)
    for job in plan.values():
        groups[job["scenario"]].append(job)
    expect(groups.keys() == experiments.keys(), folder, "legacy comparison set differs")
    for alias, part in parts.items():
        check_partition(part, y, protocol["num_clients"], 1, archive_path(f"partitions.json#{alias}"))
    history_root = archive_path("history")
    observed_keys = {s.history_key for s in HistoryQueryService(a.root / history_root).list_experiments()}
    expect(observed_keys == {x["history_key"] for x in experiments.values()}, history_root, "native history key set")
    for scenario, jobs in groups.items():
        exp = experiments[scenario]
        hist_rel = f"history/{exp['history_key']}/report.json"
        expect(exp["history_report"] == hist_rel, folder, "invalid history link")
        path = archive_path(hist_rel)
        hist = a.json(path)
        check_native(a, path, hist)
        expect(hist["request"] == exp["request"] and len(hist["results"]) == len(jobs), path, "legacy request/results")
        for job, result in zip(jobs, hist["results"], strict=True):
            rid = job["id"]
            run, row = runs[rid]["run"], by_id[rid]
            source = result["model_state"]["source_run"]
            loc = f"{name}/{rid}"
            expect(run["job"] == job and job["series"] == name and job["seed"] == series["seed"] and
                   run["source_run"] == source and source["series"] == name and source["run_id"] == rid and
                   run["history_report"] == hist_rel and run["status"] == "ok", loc, "legacy source_run binding")
            prediction_path = archive_path(source["prediction_file"])
            expect(source["prediction_file"] == f"predictions/{rid}-labels.npz", loc, "prediction link")
            labels = prediction(a, prediction_path, len(y))
            diag = result["model_state"]["diagnostics"]
            label_evidence(labels, diag, loc)
            expect(run["prediction_hash"] == diag["prediction_hash"] and
                   run["metrics"] == {k: result[k] for k in METRICS} and
                   run["history_length"] == len(result["history"]) and
                   all(result[k] == run[k] for k in ("runtime_sec", "rounds", "communication_bytes")) and
                   run["display_algorithm"] == result["algorithm"] and
                   run["cluster_count"] == diag["cluster_count_excluding_noise"] and
                   run["noise_fraction"] == diag["noise_fraction"], loc, "legacy native result mismatch")
            part = parts[job["partition"]] if "partition" in job else None
            expect(run["partition_hash"] == (part["fingerprint"] if part else None), loc, "legacy partition binding")
            if part:
                check_schedule(run["schedule"], protocol["num_clients"], protocol["rounds"], loc)
                expect(hist["partition"]["round_schedule"] == run["schedule"], loc, "legacy native schedule mismatch")
            a.file(archive_path(f"logs/{rid}.log"))
            fields = {k: run[k] for k in ("backend", "status", "runtime_sec", "algorithm_wall_sec", "communication_bytes",
                       "rounds", "cluster_count", "noise_fraction", "history_length", "prediction_hash",
                       "started_at", "finished_at", "display_algorithm")}
            fields.update(run["metrics"])
            fields.update(series=name, dataset=series["dataset"], seed=series["seed"], scenario=scenario,
                          run_id=rid, algorithm=job["algorithm"], n_samples=len(y), n_features=protocol["n_features"],
                          partition_mode=part["mode"] if part else None, alpha=part["alpha"] if part else None,
                          partition_fingerprint=run["partition_hash"], participation_rate=job.get("participation"),
                          dropout_rate=job.get("dropout"), epsilon=job.get("epsilon"),
                          active_data_fingerprint=result["model_state"]["benchmark"]["active_data_fingerprint"],
                          privacy_mode=hist["request"]["privacy_mode"],
                          client_size_cv=part["heterogeneity"]["size_cv"] if part else None,
                          class_js_divergence_weighted_bits=part["heterogeneity"].get("class_js_divergence_weighted_bits") if part else None)
            check_cells(row, fields, loc)
    return rows


def verify_legacy(a: Archive, manifest: dict) -> None:
    for name in ("README.md", "merge_history.py", "verification.json"):
        a.file(name)
    for name in REPRODUCE:
        a.file(f"reproduce/{name}")
    origin = a.json("reproduce/source_code_verification.json")
    expect(origin["source_head"] == manifest["source_head"] and origin["working_tree_patch_sha256"] ==
           file_sha(a.file("reproduce/source_changes.patch")), "reproduce", "historical source binding")
    series = index(manifest["series"], "name", "manifest.series")
    index(manifest["series"], "path", "manifest.series")
    expect(len(series) == manifest["series_count"], "manifest.series_count", "count mismatch")
    labels = {}
    rows = []
    for item in series.values():
        dataset = item["dataset"]
        with checking(item["path"]):
            if dataset not in labels:
                folder = f"datasets/{dataset}"
                verification = a.json(f"{folder}/verification.json")
                spec = dict(verification, n_samples=item["n_samples"], n_features=item["n_features"],
                            x_dtype="<f8", y_dtype="<i8")
                y, _ = check_dataset(a, f"{folder}/dataset.npz", spec)
                expect(verification["shape"] == [item["n_samples"], item["n_features"]] and
                       np.bincount(y).tolist() == verification["class_counts"], folder, "legacy dataset record")
                labels[dataset] = y
            rows.extend(_series(a, item, labels[dataset]))
    expect(len(rows) == manifest["run_count"] and a.counts["native_histories"] == manifest["comparison_count"],
           "manifest.json", "historical total differs")
    all_rows = a.csv("all_results.csv", FLAT)
    expect(all_rows == rows, "all_results.csv", "legacy root and series tables differ")
    check_summary(a, rows, None)
    a.counts["scientific_jobs"] = len(rows)
    a.skip("original_worker_results", "manifest.json", "historical format omits raw worker results and attempt ledger")
    a.complete = True
