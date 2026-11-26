"""Comparable experimental repeats and privacy accounting for portable campaign archives."""

from __future__ import annotations

from collections import defaultdict
from math import isfinite
from statistics import mean, stdev
import json

from ..experiments.plan_identity import scientific_id


SUMMARY_FIELDS = (
    "ari", "ami", "nmi", "silhouette", "davies_bouldin", "calinski_harabasz",
    "runtime_sec", "communication_bytes", "cluster_count", "noise_fraction",
    "class_js_divergence_weighted_bits", "client_size_cv",
)
AGGREGATE_COLUMNS = (
    "dataset", "scenario", "algorithm", "repetitions", "seeds",
    *(f"{field}_{stat}" for field in SUMMARY_FIELDS for stat in ("valid_n", "mean", "std", "min", "max")),
    "group_id", "planned_repetitions", "planned_seeds", "missing_repetitions", "conditions_json",
)


def _method_conditions(job: dict, seed: int) -> dict:
    """Use the rule for each seed-derived control, retaining a coincidentally equal override."""
    params = job["effective_params"].copy()
    for name, origin in job.get("parameter_sources", {}).items():
        if origin == "benchmark_seed":
            if params[name] != seed:
                raise ValueError(f"{job['job_id']}: inconsistent benchmark-derived {name}")
            params[name] = {"from": "benchmark_seed"}
    return {
        "algorithm": job["algorithm"], "backend": job["backend"],
        "display_algorithm": job.get("display_algorithm", job["algorithm"]),
        "preprocessing": job["preprocessing"], "effective_params": params,
        "deferred": job.get("deferred", {}), "execution_profile": job["execution_profile"],
        **{k: job[k] for k in ("legacy_benchmark_k", "preparation_seed_source") if k in job},
    }


def _group_conditions(plan: dict) -> dict[str, dict]:
    """Return the inspectable scientific grouping inputs for every planned job."""
    jobs_by_comparison = defaultdict(list)
    for job in plan["jobs"]:
        jobs_by_comparison[job["comparison_id"]].append(job)
    conditions = {}
    for comparison in plan["comparisons"]:
        members = jobs_by_comparison[comparison["comparison_id"]]
        protocol = comparison["protocol"].copy()
        seed = comparison["seed"]
        # PLAN's two generated seeds follow the benchmark seed in ordinary campaigns.
        for name in ("partition_seed", "schedule_seed"):
            if name in protocol and protocol[name] == seed and "historical_implementation" not in protocol:
                protocol[name] = {"from": "benchmark_seed"}
        methods = [_method_conditions(job, seed) for job in members]
        if "input_release_members" in protocol:
            original = [scientific_id("release-member", {k: job[k] for k in
                        ("algorithm", "backend", "effective_params")}) for job in members]
            if sorted(original) != protocol["input_release_members"]:
                raise ValueError(f"{comparison['comparison_id']}: inconsistent input release membership")
            protocol["input_release_members"] = sorted(
                ({k: method[k] for k in ("algorithm", "backend", "effective_params", "deferred")}
                 for method in methods), key=_json)
        for job, method in zip(members, methods, strict=True):
            conditions[job["job_id"]] = {
                "dataset_id": comparison["dataset_id"], "source_id": plan["source_id"],
                "scenario": comparison["scenario"], "protocol": protocol, "method": method,
            }
    if len(conditions) != len(plan["jobs"]):
        raise ValueError("Job grouping differs from the resolved plan")
    return conditions


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def group_ids(plan: dict) -> dict[str, str]:
    """Stable per-job group keys for repetitions that vary the benchmark seed."""
    return {job_id: scientific_id("aggregate-group-v1", record)
            for job_id, record in _group_conditions(plan).items()}


def aggregate_rows(plan: dict, rows: list[dict]) -> list[dict]:
    """Describe accepted repeats, retaining planned groups with no usable measurements."""
    conditions = _group_conditions(plan)
    accepted = {row["job_id"]: row for row in rows}
    if len(accepted) != len(rows) or accepted.keys() - conditions.keys():
        raise ValueError("Duplicate or unplanned accepted job in summary")
    names = {d["dataset_id"]: d["name"] for d in plan["datasets"]}
    comparisons = {c["comparison_id"]: c for c in plan["comparisons"]}
    groups = defaultdict(list)
    for job in plan["jobs"]:
        record = conditions[job["job_id"]]
        groups[scientific_id("aggregate-group-v1", record)].append(job)

    output = []
    for group_id, jobs in groups.items():
        first = jobs[0]
        condition = conditions[first["job_id"]]
        planned_seeds = []
        observed_seeds = []
        observed = []
        for job in jobs:
            seed = comparisons[job["comparison_id"]]["seed"]
            planned_seeds.append(str(seed))
            row = accepted.get(job["job_id"])
            if row is None:
                continue
            if row.get("status", "ok") != "ok" or row.get("group_id", group_id) != group_id:
                raise ValueError(f"{job['job_id']}: invalid accepted status or group")
            observed.append(row)
            observed_seeds.append(str(seed))
        summary = {
            "dataset": names[condition["dataset_id"]], "scenario": condition["scenario"],
            "algorithm": first["algorithm"], "repetitions": len(observed), "seeds": ",".join(observed_seeds),
            "group_id": group_id, "planned_repetitions": len(jobs), "planned_seeds": ",".join(planned_seeds),
            "missing_repetitions": len(jobs) - len(observed), "conditions_json": _json(condition),
        }
        for field in SUMMARY_FIELDS:
            values = [row[field] for row in observed if row.get(field) is not None and isfinite(row[field])]
            summary.update({
                field + "_valid_n": len(values), field + "_mean": mean(values) if values else None,
                field + "_std": stdev(values) if len(values) > 1 else None,
                field + "_min": min(values, default=None), field + "_max": max(values, default=None),
            })
        output.append(summary)
    return output


def _bounded(epsilon: object, delta: object) -> bool:
    return (type(epsilon) in (float, int) and isfinite(epsilon) and epsilon >= 0
            and type(delta) in (float, int) and isfinite(delta) and 0 <= delta <= 1)


def _attempt_observations(comparison: dict, jobs: list[dict]) -> list[dict]:
    mode = comparison["protocol"]["privacy_mode"]
    observations = []
    for job in jobs:
        accepted = job["accepted"]
        for attempt in job["attempts"]:
            details = attempt["details"]
            failure = details.get("failure") or {}
            if accepted and attempt["attempt_id"] == accepted["attempt_id"]:
                evidence = accepted["candidate"]["report"]["model_state"]["execution"]
            else:
                evidence = failure.get("provenance") or {}
            default = "unknown" if mode == "gaussian_dp_aggregate" else "not_applicable"
            status = evidence.get("aggregate_release_status", failure.get("aggregate_release_status",
                                  details.get("aggregate_release_status", default)))
            observations.append({
                "job_id": job["job"]["job_id"], "attempt_id": attempt["attempt_id"],
                "attempt_status": attempt["status"], "aggregate_release_status": status,
                "input_release_id": attempt["request"]["input_release_id"],
                "upper_bound_epsilon": evidence.get("upper_bound_epsilon"),
                "upper_bound_delta": evidence.get("upper_bound_delta"),
                "evidence": {k: evidence[k] for k in (
                    "attempt_id", "comparison_id", "source_id", "dataset_id", "privacy_mode",
                    "requested_backend", "aggregate_release_status",
                    "joint_queries", "stages", "noise_source", "sigma_per_coordinate",
                    "input_release_status", "input_release_id",
                ) if k in evidence},
            })
    return observations


def privacy_report(comparison: dict, jobs: list[dict], preparation_status: str,
                  input_release_id: str | None, *, input_privacy_report: dict | None = None) -> dict:
    """Bound only mechanisms established by the recorded preparation and all attempts of one comparison."""
    protocol = comparison["protocol"]
    mode = protocol["privacy_mode"]
    observations = _attempt_observations(comparison, jobs)
    source = input_privacy_report or {}
    release = {"status": "not_applicable", "release_id": input_release_id,
               "upper_bound_epsilon": None, "upper_bound_delta": None}
    epsilon = delta = None
    reason = "No DP budget for this mode"
    if mode == "gaussian_dp":
        release["status"] = preparation_status
        identified = (preparation_status == "recorded" and bool(input_release_id)
                      and source.get("release_id") == input_release_id
                      and source.get("comparison_id") == comparison["comparison_id"]
                      and source.get("mode") == mode and source.get("release_status") == "released"
                      and bool(source.get("protected_scope")) and bool(source.get("adjacency"))
                      and bool(source.get("mechanism"))
                      and all(a["input_release_id"] == input_release_id for a in observations))
        if identified and _bounded(source.get("epsilon"), source.get("delta")):
            epsilon, delta = source["epsilon"], source["delta"]
            release.update(status="released", upper_bound_epsilon=epsilon, upper_bound_delta=delta,
                           protected_scope=source["protected_scope"], adjacency=source["adjacency"],
                           mechanism=source["mechanism"])
            reason = "One recorded shared release of the feature matrix"
        else:
            reason = "No confirmed shared release with a known scope and bound"
    elif mode == "gaussian_dp_aggregate":
        reason = "No observed aggregate release with a confirmed bound"
        draws = [a for a in observations if a["aggregate_release_status"] != "not_started"]
        if draws:
            if all(a["aggregate_release_status"] == "observed"
                   and a["evidence"].get("privacy_mode") == mode
                   and a["evidence"].get("comparison_id") == comparison["comparison_id"]
                   and bool(a["evidence"].get("noise_source"))
                   and _bounded(a["upper_bound_epsilon"], a["upper_bound_delta"]) for a in draws):
                epsilon = sum(a["upper_bound_epsilon"] for a in draws)
                delta = min(1.0, sum(a["upper_bound_delta"] for a in draws))
                reason = "Sequential upper bound over recorded aggregate mechanisms of this comparison"
            else:
                reason = "Possible aggregate release with unknown outcome or bound"
    return {
        "comparison_id": comparison["comparison_id"], "privacy_mode": mode,
        "scope": "recorded_comparison_attempts_and_preparation", "end_to_end_report_is_dp": False,
        "preparation_status": preparation_status, "input_release": release, "attempts": observations,
        "upper_bound_epsilon": epsilon, "upper_bound_delta": delta, "bound_reason": reason,
    }
