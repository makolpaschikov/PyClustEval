from copy import deepcopy
import json

import pytest

from clustering_eval.experiments.series_plan import resolve_document
from clustering_eval.results.archive_science import AGGREGATE_COLUMNS, aggregate_rows, group_ids, privacy_report


def resolved(tmp_path, scenario, *, seeds=(17, 43), dataset="iris", threads=1):
    document = {
        "format": "pyclusteval.plan.v1", "campaign": {"name": "control"},
        "datasets": {"data": {"provider": "registry", "name": dataset}},
        "scenarios": {"trial": scenario}, "execution": {"blas_threads": threads},
        "series": [{"name": f"sample-{seed}", "dataset": "data", "seed": seed, "scenarios": ["trial"]}
                   for seed in seeds],
    }
    return resolve_document(document, base_dir=tmp_path, source_id="f" * 64)


def test_finite_values_have_independent_denominators_across_grid_and_missing_jobs(tmp_path):
    case = {"mode": "local", "algorithms": ["kmeans"], "grid": {"kmeans": {"n_init": [2, 3]}}}
    plan = resolved(tmp_path, case, seeds=(17, 43, 61, 99))
    groups = group_ids(plan)
    jobs = [job for job in plan["jobs"] if job["effective_params"]["n_init"] == 2]
    assert len(set(groups.values())) == 2
    rows = []
    for job, ari, ami, db in zip(jobs[:3], (0., 1., None), (-.2, .2, None), (2., 4., 6.)):
        rows.append({"job_id": job["job_id"], "group_id": groups[job["job_id"]], "status": "ok",
                     "ari": ari, "ami": ami, "davies_bouldin": db, "calinski_harabasz": 10.,
                     "silhouette": 0. if not rows else None, "nmi": None, "communication_bytes": 0,
                     "cluster_count": 1})
    result, absent = aggregate_rows(plan, rows)
    assert set(AGGREGATE_COLUMNS) == set(result)
    assert (result["repetitions"], result["planned_repetitions"], result["seeds"]) == (3, 4, "17,43,61")
    assert (result["ari_valid_n"], result["ari_mean"], result["ari_std"]) == (2, .5, pytest.approx(2**-.5))
    assert (result["ami_mean"], result["ami_std"]) == (0, pytest.approx((.08)**.5))
    assert result["nmi_valid_n"] == 0 and result["nmi_mean"] is None
    assert result["silhouette_mean"] == 0. and result["silhouette_std"] is None
    assert (result["davies_bouldin_mean"], result["davies_bouldin_std"]) == (4., 2.)
    assert (result["calinski_harabasz_min"], result["calinski_harabasz_max"],
            result["calinski_harabasz_std"], result["communication_bytes_valid_n"]) == (10., 10., 0., 3)
    assert absent["repetitions"] == 0 and absent["planned_repetitions"] == absent["missing_repetitions"] == 4
    assert absent["ari_std"] is None and absent["cluster_count_max"] is None
    assert json.loads(absent["conditions_json"])["method"]["effective_params"]["n_init"] == 3
    with pytest.raises(ValueError, match="Duplicate"):
        aggregate_rows(plan, rows + rows[:1])
    for changed in (resolved(tmp_path, case, dataset="wine"), resolved(tmp_path, case, threads=2)):
        assert not set(group_ids(changed).values()).intersection(groups.values())


def test_shared_input_group_normalizes_seed_rule_and_effective_members(tmp_path):
    method = "Adapted HF_DBSCAN"
    case = {"mode": "federated", "algorithms": [method, "fed_kmeans_numpy"],
            "num_clients": 5, "privacy_mode": "gaussian_dp", "stopping_profile": "current_gui"}
    automatic = resolved(tmp_path, case)
    ids = group_ids(automatic)
    assert len(set(ids.values())) == 2
    assert automatic["comparisons"][0]["protocol"]["input_release_members"] != (
        automatic["comparisons"][1]["protocol"]["input_release_members"])
    fixed = resolved(tmp_path, dict(case, algorithm_params_by_name={method: {"clients_selection_seed": 17}}))
    assert not set(group_ids(fixed).values()).intersection(ids.values())
    other = resolved(tmp_path, dict(case, algorithms=[method]))
    assert not set(group_ids(other).values()).intersection(ids.values())


def _attempt(number, mode, outcome, *, epsilon=None, delta=None, accepted=False, release=None):
    evidence = {"attempt_id": f"compute-{number}", "comparison_id": "cmp", "privacy_mode": mode,
                "input_release_id": release, "aggregate_release_status": outcome}
    if epsilon is not None:
        evidence.update(upper_bound_epsilon=epsilon, upper_bound_delta=delta, noise_source="OS CSPRNG",
                        stages={"client_prototypes": {"joint_queries": 2}})
    attempt = {"attempt_id": str(number), "request": {"input_release_id": release},
               "status": "ok" if accepted else "error",
               "details": {} if accepted else {"failure": {"provenance": evidence}}}
    success = ({"attempt_id": str(number), "candidate": {"report": {"model_state": {"execution": evidence}}}}
               if accepted else None)
    return attempt, success


def test_composition_after_failure_unknown_retry_and_no_noise_control():
    mode = "gaussian_dp_aggregate"
    cmp = {"comparison_id": "cmp", "protocol": {"privacy_mode": mode}}
    a, _ = _attempt(1, mode, "observed", epsilon=5, delta=.00001)
    b, success = _attempt(2, mode, "observed", epsilon=7, delta=.00002, accepted=True)
    before, _ = _attempt(0, mode, "not_started")
    jobs = [{"job": {"job_id": "j"}, "attempts": [before, a, b], "accepted": success}]
    report = privacy_report(cmp, jobs, "recorded", None)
    assert report["upper_bound_epsilon"] == 12 and report["upper_bound_delta"] == pytest.approx(.00003)
    assert report["attempts"][1]["evidence"]["stages"]["client_prototypes"]["joint_queries"] == 2
    jobs[0]["attempts"][1]["details"]["failure"]["provenance"]["upper_bound_delta"] = 1.
    assert privacy_report(cmp, jobs, "recorded", None)["upper_bound_delta"] == 1
    jobs[0]["attempts"][1]["details"] = {"aggregate_release_status": "unknown"}
    uncertain = privacy_report(cmp, jobs, "recorded", None)
    assert uncertain["upper_bound_epsilon"] is None and uncertain["upper_bound_delta"] is None
    assert uncertain["attempts"][2]["aggregate_release_status"] == "observed"
    assert uncertain["end_to_end_report_is_dp"] is False
    clipped = deepcopy(cmp)
    clipped["protocol"]["privacy_mode"] = "public_clipped_control"
    control, current = _attempt(1, "public_clipped_control", "no_noise_control", accepted=True)
    report = privacy_report(clipped, [{"job": {"job_id": "j"}, "attempts": [control], "accepted": current}],
                            "recorded", None)
    assert report["upper_bound_epsilon"] is None and report["attempts"][0]["aggregate_release_status"] == "no_noise_control"
    assert privacy_report(cmp, [], "not_prepared", None)["upper_bound_epsilon"] is None


def test_shared_input_release_has_one_scoped_bound_or_explicit_unknown():
    mode = "gaussian_dp"
    cmp = {"comparison_id": "cmp", "protocol": {"privacy_mode": mode}}
    observed = {"mode": mode, "release_id": "shared", "comparison_id": "cmp", "release_status": "released",
                "protected_scope": "features", "adjacency": "replace-one", "mechanism": "record-level Gaussian",
                "epsilon": 5., "delta": 1e-5}
    jobs = []
    for i in range(3):
        attempt, success = _attempt(i, mode, "not_applicable", accepted=True, release="shared")
        jobs.append({"job": {"job_id": str(i)}, "attempts": [attempt], "accepted": success})
    report = privacy_report(cmp, jobs, "recorded", "shared", input_privacy_report=observed)
    assert (report["upper_bound_epsilon"], report["upper_bound_delta"]) == (5., 1e-5)
    assert report["input_release"]["status"] == "released" and len(report["attempts"]) == 3
    for status, release, evidence in (("release_outcome_unknown", None, None), ("recorded", "shared", None)):
        report = privacy_report(cmp, [], status, release, input_privacy_report=evidence)
        assert report["upper_bound_epsilon"] is None and report["input_release"]["status"] == status
