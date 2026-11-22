"""Independent checks of numerical evidence common to both archive formats."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict
from hashlib import sha256
from io import BytesIO
import math
from pathlib import PurePosixPath
from statistics import fmean, stdev
from zipfile import ZipFile

import numpy as np

from ..application.history_query_service import HistoryQueryService
from ..datasets.partitioning import partition_class_counts, partition_fingerprint
from ..experiments.archive_inputs import canonical, document
from ..experiments.plan_identity import scientific_id
from ..metrics.diagnostics import array_fingerprint, prediction_fingerprint
from ..metrics.protocol_v2 import measure_partition_heterogeneity
from .archive_verify import Archive, check_cells, checking, expect
from .history_store import CSV_COLUMNS

METRICS = ("ari", "ami", "nmi", "silhouette", "davies_bouldin", "calinski_harabasz")
MEASURES = (*METRICS, "runtime_sec", "communication_bytes", "cluster_count", "noise_fraction",
            "class_js_divergence_weighted_bits", "client_size_cv")
FLAT = ("series", "dataset", "seed", "scenario", "run_id", "algorithm", "display_algorithm", "backend",
        "status", "n_samples", "n_features", "partition_mode", "alpha", "partition_fingerprint",
        "active_data_fingerprint", "participation_rate", "dropout_rate", "privacy_mode", "epsilon",
        "algorithm_wall_sec", "rounds", "history_length", "prediction_hash", "started_at", "finished_at",
        *MEASURES)


def check_dataset(a: Archive, path: str, record: dict) -> tuple[np.ndarray, str]:
    with checking(path), np.load(a.file(path), allow_pickle=False) as z:
        expect(sorted(z.files) == ["X", "y"], path, "expected X and y")
        X, y = z["X"], z["y"]
    expect(X.shape == (record["n_samples"], record["n_features"]) and y.shape == (len(X),),
           path, "dataset shape")
    for name, array in (("x", X), ("y", y)):
        expect(array.dtype == np.dtype(record[name + "_dtype"]), path, f"{name} dtype")
        digest = sha256(np.ascontiguousarray(array).view(np.uint8)).hexdigest()
        expect(digest == record[name + "_sha256"], path, f"{name} data or row order")
    expect(len(np.unique(y)) == record["n_classes"], path, "reference class count")
    a.counts["datasets"] += 1
    return y, array_fingerprint(X, length=64)


def check_partition(part: dict, y: np.ndarray, clients: int, minimum: int, loc: str) -> list[np.ndarray]:
    indices = part["indices"]
    expect(isinstance(indices, list) and len(indices) == clients and clients > 0, loc, "client count")
    for seq in indices:
        expect(isinstance(seq, list) and len(seq) >= minimum and all(type(i) is int for i in seq),
               loc, "invalid client indices")
    arrays = [np.asarray(seq, dtype=np.int64) for seq in indices]
    expect(np.array_equal(np.sort(np.concatenate(arrays)), np.arange(len(y))), loc, "client index coverage")
    expect(part["sizes"] == [len(row) for row in indices] and part["class_counts"] == partition_class_counts(arrays, y)
           and part["fingerprint"] == partition_fingerprint(arrays), loc, "partition properties")
    computed = measure_partition_heterogeneity(arrays, y)
    for key, value in computed.items():
        actual = part["heterogeneity"][key]
        if isinstance(value, (float, list)):
            matches = np.shape(actual) == np.shape(value) and np.allclose(actual, value, rtol=1e-12, atol=1e-14)
        else:
            matches = actual == value
        expect(matches, loc, f"partition heterogeneity {key}")
    return arrays


def prediction(a: Archive, path: str, n: int, expected_sha: str | None = None) -> np.ndarray:
    with checking(path), ZipFile(a.file(path)) as z:
        expect(z.namelist() == ["labels.npy"], path, "expected one labels.npy member")
        raw = z.read("labels.npy")
    if expected_sha is not None:
        expect(sha256(raw).hexdigest() == expected_sha, path, "original label file hash")
    with BytesIO(raw) as source:
        labels = np.load(source, allow_pickle=False)
        expect(isinstance(labels, np.ndarray) and labels.shape == (n,) and labels.dtype.kind in "iu"
               and not source.read(1), path, "invalid label shape, type or trailing data")
    a.counts["predictions"] += 1
    return labels


def label_evidence(labels: np.ndarray, diagnostics: dict, path: str) -> None:
    expect(prediction_fingerprint(labels) == diagnostics["prediction_hash"]
           and array_fingerprint(labels.astype(np.int64)) == diagnostics["raw_prediction_hash"]
           and len(set(labels.tolist()) - {-1}) == diagnostics["cluster_count_excluding_noise"]
           and float(np.mean(labels == -1)) == diagnostics["noise_fraction"],
           path, "label order, fingerprint or derived diagnostics differ")


def check_native(a: Archive, path: str, native: dict) -> None:
    """Cross-check the native CSV, logs and the service DTO against the native JSON."""
    from datetime import datetime

    folder = PurePosixPath(path).parent
    result_file = (folder / "results.csv").as_posix()
    rows = a.csv(result_file, CSV_COLUMNS)
    parts = native["partition"]
    req = native["request"]
    log_path = (folder / "execution.log").as_posix()
    log_text = a.file(log_path).read_text(encoding="utf-8")
    service = HistoryQueryService(a.root / folder.parent)
    details = service.get_experiment(folder.name)
    expect(details.experiment_id == native["experiment_id"] and details.log_text == log_text
           and details.started_at == datetime.fromisoformat(native["started_at"])
           and details.finished_at == datetime.fromisoformat(native["finished_at"])
           and details.seed == req["seed"] and details.dataset_name == req["dataset_name"]
           and len(details.results) == len(rows) == len(native["results"]),
           path, "native reader, CSV and report disagree")
    expect(log_text == "".join(native["log_lines"]).replace("\r\n", "\n").replace("\r", "\n"),
           log_path, "execution log differs from report")
    loaded_part = asdict(details.partition) if details.partition is not None else None
    expect(loaded_part == parts, path, "native reader changed partition settings")
    for result, row, loaded in zip(native["results"], rows, details.results, strict=True):
        expect(canonical(asdict(loaded)) == canonical({k: result[k] for k in asdict(loaded)}),
               path, "native history reader changed result values")
        diagnostics = result["model_state"]["diagnostics"]
        bench = result["model_state"]["benchmark"]
        client = diagnostics.get("client_metrics") or {}
        expected = {key: result[key] for key in ("algorithm", "backend", "runtime_sec", "rounds", "communication_bytes", *METRICS)}
        expected.update(experiment_id=native["experiment_id"], mode=req["mode"], dataset=req["dataset_name"],
                        started_at=native["started_at"], finished_at=native["finished_at"],
                        partition_id=parts["fingerprint"] if parts else None,
                        num_clients=parts["num_clients"] if parts else None,
                        prediction_hash=diagnostics["prediction_hash"],
                        participation_rate=req.get("participation_rate") if req["mode"] == "federated" else None,
                        dropout_rate=req.get("dropout_rate") if req["mode"] == "federated" else None,
                        privacy_mode=req.get("privacy_mode") if req["mode"] == "federated" else "none",
                        tuning_mode=bench.get("parameter_tuning_mode"),
                        class_js_divergence_weighted_bits=(parts["heterogeneity"].get("class_js_divergence_weighted_bits")
                                                          if parts else None))
        for key in ("dp_epsilon", "dp_delta", "dp_clip_norm"):
            use = req.get("privacy_mode") in ("gaussian_dp", "gaussian_dp_aggregate")
            expected[key] = req.get(key) if use else None
        for key in ("evaluation_space", "benchmark_input_hash", "active_data_fingerprint", "cluster_count_mode"):
            expected[key] = bench.get(key)
        for key in ("metric_schema_version", "assigned_fraction", "runtime_wall_including_preprocessing_sec"):
            expected[key] = diagnostics.get(key)
        for metric in ("ari", "nmi"):
            stats = client.get(metric) or {}
            for col, field in (("mean","mean"), ("weighted","weighted_mean"), ("worst","worst"), ("std","std")):
                expected[f"client_{metric}_{col}"] = stats.get(field)
        check_cells(row, expected, result_file)
    a.counts["native_histories"] += 1
    a.counts["native_results"] += len(rows)


def check_summary(a: Archive, rows: list[dict], plan: dict | None) -> None:
    """Recompute aggregates from verified accepted rows, retaining empty planned groups."""
    grouped = defaultdict(list)
    planned = defaultdict(list)
    identities = {}
    group_specs = {}
    if plan is not None:
        from .archive_science import group_ids
        identities = group_ids(plan)
        comparisons = {c["comparison_id"]: c for c in plan["comparisons"]}
        datasets = {d["dataset_id"]: d["name"] for d in plan["datasets"]}
        for job in plan["jobs"]:
            cmp = comparisons[job["comparison_id"]]
            gid = identities[job["job_id"]]
            planned[gid].append(cmp["seed"])
            group_specs[gid] = (datasets[cmp["dataset_id"]], cmp["scenario"], job["algorithm"])
    def key(row: dict) -> str | tuple:
        if plan is not None:
            return row["group_id"]
        return row["dataset"], row["scenario"], row["algorithm"]

    for row in rows:
        gid = key(row)
        if plan is not None:
            expect(identities[row["job_id"]] == gid, "all_results.csv", "incorrect scientific group")
        grouped[gid].append(row)
    name = "aggregate_by_dataset.csv"
    summary = a.csv(name, ("dataset", "scenario", "algorithm", "repetitions", "seeds"))
    seen = set()
    for row in summary:
        gid = key(row)
        expect(gid not in seen and gid in (planned if plan is not None else grouped), name,
               f"unexpected or duplicated group {gid}")
        seen.add(gid)
        values = grouped[gid]
        expected = {"repetitions": len(values), "seeds": ",".join(str(r["seed"]) for r in values)}
        if plan is not None:
            condition = document(row["conditions_json"].encode(), name)
            expect(scientific_id("aggregate-group-v1", condition) == gid, name, "group conditions differ from plan")
            expected.update(zip(("dataset", "scenario", "algorithm"), group_specs[gid], strict=True))
            expected.update(planned_repetitions=len(planned[gid]), planned_seeds=",".join(map(str, planned[gid])),
                            missing_repetitions=len(planned[gid])-len(values))
        check_cells(row, expected, name)
        for field in MEASURES:
            finite = [float(r[field]) for r in values if r[field] not in (None, "")]
            expect(all(map(math.isfinite, finite)), name, f"nonfinite {field} source")
            check_cells(row, {field + "_valid_n": len(finite)}, name)
            stats = (fmean(finite) if finite else None, stdev(finite) if len(finite) >= 2 else None,
                     min(finite) if finite else None, max(finite) if finite else None)
            for stat_name, value in zip(("mean", "std", "min", "max"), stats, strict=True):
                actual = row[field + "_" + stat_name]
                matches = actual == "" if value is None else actual != "" and math.isclose(
                    float(actual), value, rel_tol=1e-12, abs_tol=1e-14)
                expect(matches, name, f"group {gid} {field}_{stat_name} differs")
        a.counts["statistical_groups"] += 1
    expect(seen == set(planned if plan is not None else grouped), name, "missing planned group")



def check_privacy(record: dict, definition: dict, jobs: list[dict]) -> None:
    """Trace every claimed budget to the observed mechanism, including unsuccessful attempts."""
    cid = definition["comparison_id"]
    mode = definition["protocol"]["privacy_mode"]
    report = record["privacy_report"]
    prep = record["preparation"] or {}
    release_id = prep.get("input_release_id")
    status = record["preparation_status"]
    expect(report["scope"] == "recorded_comparison_attempts_and_preparation" and report["comparison_id"] == cid
           and report["preparation_status"] == status and report["privacy_mode"] == mode
           and report["end_to_end_report_is_dp"] is False and bool(report["bound_reason"]), cid, "privacy scope")
    observations = {a["attempt_id"]: a for a in report["attempts"]}
    total_attempts = sum(len(job["attempts"]) for job in jobs)
    expect(len(observations) == len(report["attempts"]) == total_attempts, cid, "privacy ledger coverage")
    possible_bounds = []
    for item in jobs:
        for att in item["attempts"]:
            aid = att["attempt_id"]
            obs = observations[aid]
            failure = att["details"].get("failure") or {}
            if att["status"] == "ok":
                ev = item["accepted"]["candidate"]["report"]["model_state"]["execution"]
            else:
                ev = failure.get("provenance") or {}
            fallback = "unknown" if mode == "gaussian_dp_aggregate" else "not_applicable"
            observed = ev.get("aggregate_release_status", failure.get("aggregate_release_status",
                              att["details"].get("aggregate_release_status", fallback)))
            evidence_fields = ("attempt_id", "comparison_id", "source_id", "dataset_id", "privacy_mode",
                               "requested_backend", "aggregate_release_status", "joint_queries", "stages",
                               "noise_source", "sigma_per_coordinate", "input_release_status", "input_release_id")
            reported = {k: ev[k] for k in evidence_fields if k in ev}
            eps, delta = ev.get("upper_bound_epsilon"), ev.get("upper_bound_delta")
            expect(obs["job_id"] == item["job"]["job_id"] and obs["attempt_status"] == att["status"] and
                   obs["input_release_id"] == release_id and obs["aggregate_release_status"] == observed and
                   obs["evidence"] == reported and obs["upper_bound_epsilon"] == eps and obs["upper_bound_delta"] == delta,
                   aid, "privacy ledger evidence differs")
            if mode == "gaussian_dp_aggregate" and observed != "not_started":
                certified = (observed == "observed" and ev.get("comparison_id") == cid and ev.get("privacy_mode") == mode
                             and bool(ev.get("noise_source")) and _bounds(eps, delta))
                possible_bounds.append((eps, delta) if certified else None)
    upper = (None, None)
    release = report["input_release"]
    expect(release["release_id"] == release_id, cid, "incorrect input release ID")
    if mode == "gaussian_dp":
        src = record["prepared_privacy_report"] or {}
        shared = (release_id and status == "recorded" and src.get("release_id") == release_id
                  and src.get("comparison_id") == cid and src.get("mode") == mode and
                  src.get("release_status") == "released" and all(src.get(k) for k in ("protected_scope","adjacency","mechanism"))
                  and _bounds(src.get("epsilon"), src.get("delta")))
        if shared:
            upper = (src["epsilon"], src["delta"])
            expect(all(release.get(k) == src[k] for k in ("protected_scope", "adjacency", "mechanism")),
                   cid, "public claim differs from input release scope")
        expect(release["status"] == ("released" if shared else status)
               and (release["upper_bound_epsilon"], release["upper_bound_delta"]) == upper, cid, "input release bound")
    else:
        expect(release["status"] == "not_applicable" and release["upper_bound_epsilon"] is None
               and release["upper_bound_delta"] is None, cid, "unexpected input DP bound")
    if possible_bounds and all(pair is not None for pair in possible_bounds):
        upper = (sum(pair[0] for pair in possible_bounds), min(1.0, sum(pair[1] for pair in possible_bounds)))
    expect((report["upper_bound_epsilon"], report["upper_bound_delta"]) == upper, cid,
           "privacy bound does not cover exactly the observed releases")


def _bounds(epsilon: object, delta: object) -> bool:
    return (type(epsilon) in (float, int) and math.isfinite(epsilon) and epsilon >= 0 and
            type(delta) in (float, int) and math.isfinite(delta) and 0 <= delta <= 1)
