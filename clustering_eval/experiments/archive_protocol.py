"""Translate verified worker records into the historical comparison and job contracts."""
from __future__ import annotations

from .archive_inputs import require
from .plan_identity import comparison_key, group_key, job_key


def indexed(rows: list[dict], key: str, location: str) -> dict:
    result = {}
    for row in rows:
        value = row[key]
        require(value not in result, location, f"duplicate {key} {value!r}")
        result[value] = row
    return result


def check_schedule(schedule: list[dict], n_clients: int, rounds: int, location: str) -> None:
    require(len(schedule) == rounds, location, "schedule length differs from round budget")
    for number, entry in enumerate(schedule, 1):
        require(entry["round"] == number, location, "round sequence mismatch")
        selected, good, dropped = (entry[k] for k in ("selected_clients", "successful_clients", "dropped_clients"))
        for ids in (selected, good, dropped):
            require(isinstance(ids, list) and all(type(v) is int and 0 <= v < n_clients for v in ids)
                    and len(ids) == len(set(ids)), location, f"invalid client IDs at round {number}")
        require(bool(good) and not set(good).intersection(dropped) and set(good) | set(dropped) == set(selected),
                location, f"inconsistent participation at round {number}")


def common_protocol(request: dict, definition: dict, first_job: dict, partition: dict | None,
                    schedule: list, sources: dict, location: str) -> dict:
    local = first_job.get("local") is True
    require((partition is None) == local, location, "partition is inconsistent with job mode")
    expected = {
        "mode": "local" if local else "federated", "partition_mode": "iid" if local else partition["mode"],
        "dirichlet_alpha": .5 if local else partition["alpha"],
        "num_clients": definition["num_clients"], "rounds": definition["rounds"], "tol": definition["tol"],
        "max_iter": definition["max_iter"], "density_min_samples": 5, "target_clusters": definition["n_classes"],
        "cluster_count_mode": "known_k", "min_samples_per_client": 3, "labels_per_client": 2,
        "participation_rate": first_job.get("participation", 1.), "dropout_rate": first_job.get("dropout", 0.),
        "privacy_mode": "gaussian_dp_aggregate" if "epsilon" in first_job else "none",
        "dp_epsilon": first_job.get("epsilon", 5.), "dp_delta": definition["dp_delta"],
        "dp_clip_norm": definition["dp_clip_norm"],
    }
    for key, value in expected.items():
        require(request[key] == value, f"{location}.request.{key}", "disagrees with source protocol or job")
    if local:
        require(schedule == [], location, "unexpected local participation schedule")
    else:
        check_schedule(schedule, expected["num_clients"], expected["rounds"], location)
    controls = {k: v for k, v in request.items() if k not in {
        "algorithms", "algorithm_params", "algorithm_params_by_name", "seed", "dataset_name"}}
    require(request["algorithm_params"] == {}, location, "unexpected common algorithm overrides")
    if not local:
        controls["stopping_profile"] = "historical_paper"
    return dict(controls, partition=partition, participation_schedule=schedule,
                evaluation_space="StandardScaler(original_raw_X)", historical_implementation=sources,
                metrics=["ari", "nmi", "ami", "silhouette", "davies_bouldin", "calinski_harabasz"],
                metric_schema_version="clustering_metrics_v3_ami_assigned_only",
                external_metric_population="all records; -1 is one predicted label",
                internal_metric_population="assigned non-noise records; silhouette fixed 2000-record reference",
                communication_scope="logical_payload_only_not_network_wire_bytes")


def effective_parameters(job: dict, run: dict, protocol: dict, request_params: dict, location: str) -> dict:
    params = dict(run["params"])
    schedule = params.pop("participation_schedule", [])
    require(schedule == run["schedule"] == protocol["participation_schedule"], location, "schedule mismatch")
    aggregate = params.pop("dp_aggregate", None)
    require(params == request_params, location, "worker parameters differ from native request overrides")
    for key in ("rounds", "tol", "max_iter", "density_min_samples"):
        require(params[key] == protocol[key], f"{location}.params.{key}", "worker and request disagree")
    require(params["k"] == params["n_clusters"] == protocol["target_clusters"],
            location, "effective K aliases disagree with oracle-K protocol")
    if "epsilon" in job:
        algorithm = job["algorithm"]
        kind = "fuzzy" if "fuzzy" in algorithm else "gmm" if "gmm" in algorithm else "kmeans"
        budget = protocol["rounds"] if algorithm == "Adapted FKM" or "flower" in algorithm else 1
        expected = dict(enabled=True, kind=kind, budgeted_rounds=budget, epsilon_total=job["epsilon"],
                        delta_total=protocol["dp_delta"], clip_norm=protocol["dp_clip_norm"])
        require(isinstance(aggregate, dict) and all(aggregate.get(k) == v for k, v in expected.items()),
                f"{location}.dp_aggregate", "worker DP parameters disagree with historical mechanism")
        require(run["preprocessing"] == "clipped", location, "expected clipped input")
        params["dp_aggregate"] = aggregate
    else:
        require(aggregate is None, location, "unexpected DP configuration")
    return params


def resolve_series(definition: dict, plan: list, parts: dict, report: dict, dataset: dict,
                   series_dir: str, sources: dict, source_id: str) -> tuple[list, list, dict]:
    """Join jobs by their names within a series; values from scientific outputs never select jobs."""
    series, seed = definition["series"], definition["seed"]
    require(report["format"] == "pyclusteval.benchmark-series.v1" and report["protocol"] == definition,
            f"{series_dir}/report.json", "series report disagrees with protocol")
    require(report["series"] == series and report["dataset_name"] == dataset["name"] and report["seed"] == seed,
            series, "inconsistent series, dataset or seed")
    planned = indexed(plan, "id", f"{series_dir}/experiment_plan.json")
    observed = indexed([{"id": run["job"]["id"], "run": run} for run in report["runs"]],
                       "id", f"{series_dir}/report.json.runs")
    experiments = indexed(report["experiments"], "scenario", f"{series_dir}/report.json.experiments")
    require(planned.keys() == observed.keys() and len(plan) == report["run_count"], series, "job set mismatch")
    groups: dict[str, list] = {}
    for job in plan:
        groups.setdefault(job["scenario"], []).append(job)
    require(groups.keys() == experiments.keys() and len(groups) == report["comparison_count"],
            series, "comparison set mismatch")

    comparisons, jobs, templates = [], [], {}
    for scenario, group in groups.items():
        loc = f"{series}.{scenario}"
        first = group[0]
        request = experiments[scenario]["request"]
        algorithms = [entry["algorithm"] for entry in group]
        require(request["algorithms"] == algorithms and len(set(algorithms)) == len(algorithms)
                and request["dataset_name"] == dataset["name"] and request["seed"] == seed,
                loc, "request, algorithm order or seed mismatch")
        alias = first.get("partition")
        partition = None if alias is None else parts[alias]
        schedule = observed[first["id"]]["run"]["schedule"]
        protocol = common_protocol(request, definition, first, partition, schedule, sources, loc)
        input_key = comparison_key(source_id=source_id, dataset_id=dataset["dataset_id"], seed=seed, protocol=protocol)
        job_rows = []
        for job in group:
            run_id, algorithm = job["id"], job["algorithm"]
            job_path = f"{series}.{run_id}"
            record = observed[run_id]["run"]
            require(job == dict(first, id=run_id, algorithm=algorithm)
                    and job == record["job"] and job["seed"] == seed and job["series"] == series,
                    job_path, "planned job disagrees with worker record or common conditions")
            require(record["status"] == "ok" and record["input_shape"] == [dataset["n_samples"], dataset["n_features"]]
                    and record["partition_hash"] == (partition["fingerprint"] if partition else None)
                    and record["client_sizes"] == (partition["sizes"] if partition else []),
                    job_path, "missing or inconsistent input evidence")
            params = effective_parameters(job, record, protocol, request["algorithm_params_by_name"][algorithm], job_path)
            backend = record["backend"]
            profile = record.get("execution_profile", "persistent_worker")
            identifier = job_key(comparison_id=input_key, algorithm=algorithm, backend=backend,
                                 effective_params=params, execution_profile=profile)
            job_rows.append(dict(job_id=identifier, series=series, scenario=scenario, run_id=run_id,
                                 dataset_id=dataset["dataset_id"], seed=seed, algorithm=algorithm, backend=backend,
                                 display_algorithm=record["display_algorithm"], preprocessing=record["preprocessing"],
                                 effective_params=params, execution_profile=profile,
                                 parameter_sources={"effective_params": f"{series_dir}/report.json#runs/job.id={run_id}/params",
                                                    "defaults": "reproduce/worker.py + historical source snapshot"}))
        comparison_id = group_key(input_key, [row["job_id"] for row in job_rows])
        for row in job_rows:
            row["comparison_id"] = comparison_id
        jobs.extend(job_rows)
        comparisons.append(dict(comparison_id=comparison_id, input_key=input_key, series=series, scenario=scenario,
                                dataset_id=dataset["dataset_id"], seed=seed, protocol=protocol,
                                provenance={"partition": f"{series_dir}/partitions.json#{alias}" if alias else None,
                                            "schedule": f"{series_dir}/report.json#runs/job.id={first['id']}/schedule"
                                                        if alias else None}))
        templates[scenario] = dict(mode=protocol["mode"], algorithms=algorithms, run_ids=[job["id"] for job in group],
                                   partition=alias, participation_rate=protocol["participation_rate"],
                                   dropout_rate=protocol["dropout_rate"], privacy_mode=protocol["privacy_mode"],
                                   epsilon=first.get("epsilon"), target_clusters_from="dataset.n_classes")
        if protocol["mode"] == "federated":
            templates[scenario]["stopping_profile"] = protocol["stopping_profile"]
    return comparisons, jobs, templates
