"""Join archive members to the scientific plan and the original accepted worker records."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta
from hashlib import sha256
from uuid import UUID

from ..application.history_query_service import HistoryQueryService
from ..experiments.archive_inputs import canonical
from ..experiments.archive_protocol import check_schedule
from ..experiments.plan_identity import comparison_key, group_key, job_key
from ..experiments.runner_records import _inspect_success
from ..experiments.runner_state import STATUSES
from ..experiments.source_archive import verify_source_snapshot
from .archive_verify import Archive, check_cells, checking, expect, file_sha, index
from .archive_verify_science import (
    FLAT, METRICS, check_dataset, check_native, check_partition, check_privacy, check_summary, label_evidence, prediction,
)


def _subset(record: dict, expected: dict, loc: str) -> None:
    for key, value in expected.items():
        expect(canonical(record[key]) == canonical(value), loc, f"{key} differs from source")


def _data(a: Archive, plan: dict, manifest: dict) -> dict:
    loc = "manifest.datasets"
    actual = index(manifest["datasets"], "dataset_id", loc)
    index(manifest["datasets"], "path", loc)
    grouped = defaultdict(list)
    for record in plan["datasets"]:
        grouped[record["dataset_id"]].append(record)
    expect(grouped.keys() == actual.keys(), loc, "dataset ID coverage")
    saved = {}
    for did, aliases in grouped.items():
        item = actual[did]
        definition = aliases[0]
        scientific = {k: definition[k] for k in ("provider", "name", "params", "preparation_seed", "n_samples",
                      "n_features", "n_classes", "x_sha256", "y_sha256", "x_dtype", "y_dtype")}
        expect(did == sha256(canonical(["pyclusteval.dataset.v1", scientific])).hexdigest(), loc, "dataset identity")
        for alias in aliases:
            _subset(alias, scientific, did)
        folder = item["path"]
        expect(folder.startswith("datasets/") and folder in a.dirs, loc, f"invalid dataset path {folder}")
        info = a.json(f"{folder}/verification.json")
        expect(set(item["keys"]) == {x["key"] for x in aliases} and
               info["dataset_id"] == did and info["dataset"] == definition and
               info["available"] is item["available"] and info["reason"] == item["reason"], folder,
               "dataset verification disagrees")
        recorded = [c["comparison_id"] for c in manifest["comparisons"]
                    if c["dataset_id"] == did and c["preparation_status"] == "recorded"]
        expect(set(info["checked_comparisons"]) == set(recorded) and len(info["checked_comparisons"]) == len(recorded)
               and item["available"] is bool(recorded), folder, "prepared dataset coverage")
        path = folder + "/dataset.npz"
        if recorded:
            saved[did] = check_dataset(a, path, definition)
        else:
            expect(item["reason"] and path not in a.files, folder, "missing unprepared-data evidence")
            a.skip("dataset_arrays", folder, item["reason"])
    return saved


def _inputs(a: Archive, cmp: dict, record: dict, part: dict | None, data: dict) -> None:
    cid = cmp["comparison_id"]
    status, prep = record["preparation_status"], record["preparation"]
    if prep is None:
        allowed = {"unprepared", "release_outcome_unknown" if cmp["protocol"]["privacy_mode"] == "gaussian_dp"
                   else "preparation_incomplete"}
        expect(status in allowed and part is None, cid, "unbound comparison carries prepared inputs")
        a.skip("prepared_comparison", cid, status)
        return
    y, raw_hash = data[cmp["dataset_id"]]
    protocol = cmp["protocol"]
    expect(status == "recorded" and prep["dataset_id"] == cmp["dataset_id"] and prep["n_samples"] == len(y)
           and prep["privacy_mode"] == protocol["privacy_mode"] and prep["fingerprints"]["raw"] == raw_hash,
           cid, "preparation binding differs")
    for key in ("descriptor_sha256", "reservation_sha256"):
        h = prep[key]
        expect(isinstance(h, str) and len(h) == 64 and bytes.fromhex(h).hex() == h, cid, key)
    if part is None:
        expect(protocol["mode"] == "local" and prep["fingerprints"]["partition"] is None
               and prep["fingerprints"]["schedule"] is None, cid, "missing recorded federated inputs")
    else:
        check_partition(part, y, protocol["num_clients"], protocol["min_samples_per_client"], cid)
        schedule = part["schedule"]
        rounds = 0 if protocol.get("schedule") == "legacy_adapter_default" else protocol["schedule_rounds"]
        check_schedule(schedule, protocol["num_clients"], rounds, cid)
        alpha = protocol.get("dirichlet_alpha") if protocol["partition_mode"] == "dirichlet" else None
        expect(part["mode"] == protocol["partition_mode"] and part["alpha"] == alpha and
               prep["fingerprints"]["partition"] == sha256(canonical(part["indices"])).hexdigest() and
               prep["fingerprints"]["schedule"] == (sha256(canonical(schedule)).hexdigest() if schedule else None),
               cid, "partition or schedule differs from preparation")
        a.counts["partitions"] += 1


def _attempts(a: Archive, job: dict, rec: dict, cmp: dict, source: str,
              sessions: dict, seen: set) -> None:
    job_id = job["job_id"]
    status, attempts, accepted = rec["status"], rec["attempts"], rec["accepted"]
    expect(status in STATUSES and (accepted is not None) == (status == "ok"), job_id, "invalid acceptance status")
    expect((attempts[-1]["status"] == status if attempts else status in ("pending", "skipped")),
           job_id, "job differs from last technical attempt")
    for number, att in enumerate(attempts, 1):
        aid = att["attempt_id"]
        expect(UUID(aid).hex == aid and aid not in seen and att["number"] == number
               and att["session_id"] in sessions and att["status"] in STATUSES[1:-1]
               and att["kind"] in ("initial", "resumed", "manual", "automatic"), job_id, "invalid attempt identity/sequence")
        seen.add(aid)
        request = att["request"]
        expect(cmp["preparation"] is not None, aid, "attempt without preparation")
        _subset(request, {**cmp["preparation"], "attempt_id": aid, "job": job, "job_id": job_id,
                          "comparison_id": cmp["comparison_id"], "source_id": source}, aid)
        expect((att["status"] == "ok") == (accepted is not None and aid == accepted["attempt_id"])
               and (att["status"] == "running") == (att["ended"] is None), aid, "inconsistent terminal record")
        if att["status"] not in ("ok", "running"):
            expect(bool(att["reason"]), aid, "failed attempt lacks a reason")
        failure = att["details"].get("failure")
        if failure:
            provenance = failure.get("provenance") or {}
            for field in ("source_id", "dataset_id", "job_id", "comparison_id", "privacy_mode", "input_release_id"):
                if field in provenance:
                    expect(provenance[field] == request[field], aid, f"error provenance {field}")
            payload = {k: failure[k] for k in ("message","reason","traceback","worker","exit_code","provenance",
                                               "aggregate_release_status")}
            binding = {"format": failure["format"], "attempt_id": aid, "request_sha256": sha256(canonical(request)).hexdigest()}
            original_failure = dict(binding, payload=payload, payload_sha256=sha256(canonical(payload)).hexdigest())
            _subset(failure, binding, aid)
            expect(sha256(canonical(original_failure)).hexdigest() == failure["failure_sha256"], aid, "original failure hash")
        logs = att["archive_logs"]
        for lane in ("stdout", "stderr"):
            log = logs[lane]
            path = log["path"]
            if path is None:
                expect(log["status"] in ("unavailable", "in_progress") and att["status"] != "ok", aid,
                       "missing accepted log or unexplained missing log")
                a.skip("attempt_log", aid + "/" + lane, log["status"])
            else:
                target = a.file(path)
                digest = file_sha(target)
                expect(log["status"] in ("available", "in_progress") and target.stat().st_size == log["bytes"]
                       and digest == log["sha256"], path, "archived attempt log differs")
                if att["status"] == "ok":
                    origin = att["details"]["logs"][lane + ".log"]
                    expect(log["status"] == "available" and digest == origin["sha256"]
                           and log["bytes"] == origin["bytes"], path, "verified worker log differs")
        a.counts["technical_attempts"] += 1


def _accepted(a: Archive, job: dict, cmp: dict, outcome: dict, run: dict,
              native: dict, row: dict, part: dict | None, folder: str, protocol: dict, n_features: int) -> dict:
    acc = outcome["accepted"]
    jid = job["job_id"]
    path = acc["result_path"]
    expect(path.startswith(folder + "/") and file_sha(a.file(path)) == acc["result_sha256"], path, "worker result hash")
    raw = a.json(path)
    att = outcome["attempts"][-1]
    labels = prediction(a, acc["prediction_path"], att["request"]["n_samples"], acc["labels_sha256"])
    _inspect_success(raw, labels, att["request"])
    expect(labels.dtype.str == acc["labels_dtype"] and list(labels.shape) == acc["labels_shape"],
           acc["prediction_path"], "declared original labels type or dimensions differ")
    expect(acc["compute_attempt_id"] == raw["compute_attempt_id"] and acc["attempt_id"] == raw["attempt_id"],
           jid, "accepted attempt mismatch")
    primary = raw["report"]
    state = primary["model_state"]
    diag, bench, provenance = state["diagnostics"], state["benchmark"], state["execution"]
    label_evidence(labels, diag, jid)
    source_run = native["source_run"]
    worker = raw["worker"]
    total = worker.get("elapsed_to_observation_sec")
    affinity = worker.get("cpu_affinity")
    _subset(source_run["field_origins"], {
        "total_wall_sec": "not recorded" if total is None else "worker.elapsed_to_observation_sec",
        "cpu_affinity": "not recorded" if affinity is None else "worker.cpu_affinity",
    }, f"{jid}/source_run.field_origins")
    _subset(source_run, dict(total_wall_sec=total, cpu_affinity=affinity,
            algorithm_wall_sec=diag["runtime_algorithm_call_sec"], seed=bench["seed"],
            started_at=worker["started_at_utc"], finished_at=worker["finished_compute_at_utc"]), jid)
    _subset(source_run, {"series": job["series"], "run_id": job["run_id"], "result_path": path,
                         "prediction_path": acc["prediction_path"], "attempt_id": acc["attempt_id"],
                         "compute_attempt_id": acc["compute_attempt_id"], "worker_pid": raw["worker"]["pid"],
                         "started_at_utc": provenance["started_at_utc"], "finished_at_utc": provenance["finished_at_utc"]}, jid)
    _subset(source_run, dict(job_id=jid, comparison_id=cmp["comparison_id"], dataset_id=cmp["dataset_id"],
            source_id=att["request"]["source_id"], source_json_sha256=acc["result_sha256"],
            source_labels_sha256=acc["labels_sha256"], worker=raw["worker"],
            result={"path":"result.json","sha256":acc["result_sha256"]},
            predictions={"path":"labels.npy","sha256":acc["labels_sha256"],"dtype":labels.dtype.str,"shape":list(labels.shape)}), jid)
    candidate = {key: raw[key] for key in ("format", "attempt_id", "request_sha256")}
    candidate.update(result=source_run["result"], labels=source_run["predictions"])
    expect(sha256(canonical(candidate)).hexdigest() == acc["candidate_sha256"], jid, "accepted candidate hash")
    collection_job = dict(job, id=job["run_id"], scenario=cmp["scenario"], seed=bench["seed"])
    if protocol["mode"] == "local":
        collection_job["local"] = True
    else:
        collection_job.update(partition=cmp["comparison_id"], participation=protocol.get("participation_rate"),
                              dropout=protocol.get("dropout_rate"))
    if bench.get("dp_epsilon") is not None:
        collection_job["epsilon"] = bench["dp_epsilon"]
    expect(canonical(run["job"]) == canonical(collection_job), jid, "series job definition differs")
    _subset(run, dict(id=job["run_id"], input_shape=[att["request"]["n_samples"], n_features],
                      partition_hash=part["fingerprint"] if part else None, client_sizes=part["sizes"] if part else [],
                      total_wall_sec=total, cpu_affinity=affinity), jid)
    model_state = native["model_state"].copy()
    if "source_run" not in state:
        expect(model_state.pop("source_run") == source_run, jid, "native result provenance disagrees")
    expect(canonical(model_state) == canonical(state), jid, "native model_state differs from worker result")
    _subset(native, {k: v for k,v in primary.items() if k != "model_state"}, jid)
    history_path = cmp["history_report"]
    expect(acc["history_report"] == history_path and run["history_report_path"] == history_path
           and folder + "/" + run["history_report"] == history_path and
           folder + "/" + source_run["prediction_file"] == acc["prediction_path"]
           and folder + "/" + run["prediction_file"] == acc["prediction_path"] and run["log_path"] == acc["log_path"] and run["source_run"] == source_run, jid, "series result links")
    expect(acc["log_path"].startswith(folder + "/logs/") and acc["prediction_path"].startswith(folder + "/predictions/"),
           jid, "file linked across series")
    merged = "".join("[" + lane + "]\n" + a.file(att["archive_logs"][lane]["path"]).read_bytes().decode(
        "utf-8", errors="backslashreplace") + "\n" for lane in ("stdout", "stderr"))
    expect(a.file(acc["log_path"]).read_bytes() == merged.encode("utf-8"), acc["log_path"], "merged attempt log differs")
    metrics = {k: primary[k] for k in METRICS}
    expect(run["metrics"] == metrics and run["execution_profile"] == job["execution_profile"] and
           run["preprocessing"] == bench["preprocessing"] and run["params"] == bench["effective_params"] and
           run["schedule"] == (part["schedule"] if part else []), jid, "series conditions or metrics differ")
    expected = dict(series=job["series"], run_id=job["run_id"], algorithm=job["algorithm"],
                    display_algorithm=primary["algorithm"], backend=primary["backend"], status="ok",
                    job_id=jid, comparison_id=cmp["comparison_id"], attempt_id=att["attempt_id"],
                    scenario=cmp["scenario"], seed=bench["seed"], n_samples=len(labels),
                    history_length=len(primary["history"]), cluster_count=diag["cluster_count_excluding_noise"],
                    noise_fraction=diag["noise_fraction"], prediction_hash=diag["prediction_hash"],
                    runtime_sec=primary["runtime_sec"], communication_bytes=primary["communication_bytes"],
                    rounds=primary["rounds"], algorithm_wall_sec=diag["runtime_algorithm_call_sec"],
                    started_at=raw["worker"]["started_at_utc"], finished_at=raw["worker"]["finished_compute_at_utc"],
                    partition_fingerprint=part["fingerprint"] if part else None,
                    partition_mode=part["mode"] if part else None, alpha=part["alpha"] if part else None,
                    class_js_divergence_weighted_bits=part["heterogeneity"].get("class_js_divergence_weighted_bits") if part else None,
                    client_size_cv=part["heterogeneity"]["size_cv"] if part else None,
                    active_data_fingerprint=bench.get("active_data_fingerprint"), privacy_mode=bench["privacy_mode"],
                    epsilon=bench.get("dp_epsilon"), **metrics)
    check_cells(row, expected, jid)
    for key in row.keys() & set(FLAT + ("job_id", "comparison_id", "attempt_id", "group_id")):
        check_cells(row, {key: run[key]}, jid)
    a.counts["accepted_worker_results"] += 1
    return raw


def _comparison(a: Archive, definition: dict, record: dict, planned: list[dict], outcomes: dict,
                series: dict, part: dict | None, runs: dict, experiment: dict | None,
                by_job: dict, data: dict, sessions: dict, seen: set, source: str) -> None:
    cid = definition["comparison_id"]
    proto = definition["protocol"]
    input_id = comparison_key(source_id=source, dataset_id=definition["dataset_id"], seed=definition["seed"], protocol=proto)
    expect(input_id == definition["input_id"] and group_key(input_id, [j["job_id"] for j in planned]) == cid,
           cid, "comparison identity")
    actual = [outcomes[j["job_id"]] for j in planned]
    ok = [j for j in actual if j["accepted"] is not None]
    expect(record["planned"] == len(planned) and record["accepted"] == len(ok)
           and record["complete"] is (len(ok) == len(planned)) and
           (record["history_report"] is None) == (not ok) and (experiment is None) == (not ok), cid, "comparison completeness")
    _inputs(a, definition, record, part, data)
    native_items = []
    if ok:
        path = record["history_report"]
        folder = series["path"]
        expect(path == f"{folder}/history/{experiment['history_key']}/report.json"
               and path == experiment["history_report_path"] == folder + "/" + experiment["history_report"],
               cid, "comparison history path")
        native = a.json(path)
        native_items = native["results"]
        expect(native["experiment_id"] == cid and len(native_items) == len(ok) and
               native["request"] == experiment["request"] and native["n_samples"] == len(data[record["dataset_id"]][0])
               and native["request"]["dataset_name"] == series["dataset_name"]
               and native["request"]["seed"] == definition["seed"] and native["n_features"] == series["n_features"],
               path, "native comparison header")
        _subset(native["request"], dict(proto, algorithms=[r["algorithm"] for r in native_items]), path)
        expect(native["complete"] is record["complete"] and native["comparison_id"] == cid
               and native["history_directory"] == "history/" + cid and experiment["complete"] is record["complete"],
               path, "native completeness or identity differs")
        plan_path = f"{folder}/experiment_plan.json"
        _subset(native["export_provenance"], dict(plan_path=plan_path, series=series["name"],
                source_scenario=definition["scenario"], source_run_ids=[j["run_id"] for j in ok],
                exported_without_rerun=True, timestamp_timezone="UTC"), path + "#export_provenance")
        a.file(plan_path)
        expect(native["privacy_report"] == record["privacy_report"], path, "native privacy scope")
        if part is None:
            expect(native["partition"] is None, path, "unexpected native partition")
        else:
            _subset(native["partition"], {"fingerprint": part["fingerprint"], "round_schedule": part["schedule"],
                    "client_sample_counts": part["sizes"], "client_class_counts": part["class_counts"],
                    "heterogeneity": part["heterogeneity"], "mode": part["mode"], "num_clients": len(part["indices"]),
                    "dirichlet_alpha": part["alpha"], "participation_rate": proto.get("participation_rate", 1.),
                    "dropout_rate": proto.get("dropout_rate", 0.), "labels_per_client": (
                        proto.get("labels_per_client") if proto["partition_mode"] == "label_limited" else None)}, path)
        check_native(a, path, native)
    natives = iter(native_items)
    original_jobs = []
    workers = []
    for job, rec in zip(planned, actual, strict=True):
        jid = job["job_id"]
        expect(jid == job_key(comparison_id=input_id, algorithm=job["algorithm"], backend=job["backend"],
                              effective_params=job["effective_params"], execution_profile=job["execution_profile"]),
               jid, "job identity")
        if rec["status"] != "ok":
            expect(isinstance(rec["reason"], str) and rec["reason"].strip(), jid, "missing reason for unaccepted job")
        _subset(rec, {k: job[k] for k in ("job_id", "series", "comparison_id", "run_id")}, jid)
        _attempts(a, job, rec, record, source, sessions, seen)
        original = dict(job=job, attempts=rec["attempts"], accepted=None, status=rec["status"], reason=rec["reason"])
        if rec["accepted"]:
            row = by_job[jid]
            check_cells(row, dict(dataset=series["dataset_name"], n_features=native["n_features"],
                                  participation_rate=proto.get("participation_rate") if part else None,
                                  dropout_rate=proto.get("dropout_rate") if part else None), jid)
            raw = _accepted(a, job, record, rec, runs[jid], next(natives), row, part, series["path"], proto, series["n_features"])
            workers.append(raw["worker"])
            original["accepted"] = {"attempt_id": rec["accepted"]["attempt_id"], "candidate": raw}
        original_jobs.append(original)
    if workers:
        first = min(datetime.fromisoformat(w["started_at_utc"]) for w in workers)
        last = max(datetime.fromisoformat(w["finished_compute_at_utc"]) for w in workers)
        expect(datetime.fromisoformat(native["started_at"]) == first and datetime.fromisoformat(native["finished_at"]) == last
               and native["duration_sec"] == (last-first).total_seconds(), path, "comparison UTC interval")
    check_privacy(record, definition, original_jobs)
    a.counts["comparisons"] += 1


def _replay(a: Archive, manifest: dict) -> None:
    """The replay plan may rebind locations, preserving scientific settings and dataset evidence."""
    from ..experiments.plan_io import read_document

    original = read_document(a.file(manifest["original_plan_path"]))
    by_key = {key: d for d in manifest["datasets"] for key in d["keys"]}
    missing = []
    replay = "reproduce/portable_plan.json"
    original["campaign"]["output_dir"] = "../../replayed-campaign"
    for key, definition in original["datasets"].items():
        rec = by_key[key]
        fixed = rec["dataset"]
        if definition["provider"] == "npz" and rec["available"]:
            target = rec["path"] + "/dataset.npz"
            definition["path"] = "../" + target
            if "sha256" in definition:
                definition["sha256"] = file_sha(a.file(target))
        elif definition["provider"] == "npz" or "input_path" in fixed:
            missing.append(key)
        definition.update(x_sha256=fixed["x_sha256"], y_sha256=fixed["y_sha256"])
    if missing:
        expect(replay not in a.files, replay, "replay claims unavailable provider inputs")
        a.skip("automatic_replay", replay, "required original provider inputs: " + ", ".join(missing))
    else:
        expect(canonical(a.json(replay)) == canonical(original), replay, "scientific conditions or local bindings differ")


def verify_general(a: Archive, manifest: dict) -> None:
    for filename in ("README.md", "merge_history.py"):
        a.file(filename)
    a.file("reproduce/README.md")
    original = manifest["original_plan_path"]
    expect(original in ("reproduce/plan.yaml", "reproduce/plan.json") and file_sha(a.file(original)) == manifest["plan_sha256"],
           original, "original plan identity")
    resolved = "reproduce/resolved_plan.json"
    expect(file_sha(a.file(resolved)) == manifest["resolved_sha256"], resolved, "resolved plan identity")
    source = manifest["source_id"]
    identity = [source, manifest["campaign_created_utc_epoch"], manifest["plan_sha256"], manifest["resolved_sha256"]]
    expect(sha256(canonical(identity)).hexdigest() == manifest["campaign_id"], "manifest.campaign_id", "campaign binding")
    for path in ("source_changes.patch", "source_snapshot.zip", "source_code_verification.json"):
        a.file("reproduce/" + path)
    expect(manifest["source_record_sha256"] == file_sha(a.file("reproduce/source_code_verification.json")),
           "manifest.source_record_sha256", "SOURCE record hash differs")
    verify_source_snapshot(a.root / "reproduce", expected_source_id=source)
    a.counts["source_snapshots"] += 1
    runtime = a.json("reproduce/environment.json")
    expect(all(k in runtime for k in ("python", "packages", "platform")), "reproduce/environment.json", "runtime data")
    plan = a.json(resolved)
    expect(plan["source_id"] == source and plan["format"] == "pyclusteval.resolved-plan.v1", resolved, "source or version")
    from .archive_science import group_ids

    groups = group_ids(plan)
    jobs = index(plan["jobs"], "job_id", resolved)
    cmps = index(plan["comparisons"], "comparison_id", resolved)
    series = index(plan["series"], "name", resolved)
    expect(plan["counts"] == dict(series=len(series), comparisons=len(cmps), jobs=len(jobs)), resolved, "plan counts")
    outcomes = index(manifest["jobs"], "job_id", "manifest.jobs")
    observed = index(manifest["comparisons"], "comparison_id", "manifest.comparisons")
    series_entries = index(manifest["series"], "name", "manifest.series")
    index(manifest["series"], "path", "manifest.series")
    expect(list(outcomes) == list(jobs) and list(cmps) == list(observed) and list(series_entries) == list(series),
           "manifest.json", "plan coverage or ordering differs")
    seen_external = {(j["series"], j["run_id"]) for j in jobs.values()}
    expect(len(seen_external) == len(jobs), resolved, "duplicate external run identity")
    totals = dict.fromkeys(STATUSES, 0) | dict(Counter(x["status"] for x in outcomes.values()))
    expect(set(totals) == set(STATUSES) and manifest["planned"] == len(jobs) and manifest["totals"] == totals and
           manifest["complete"] is (totals["ok"] == len(jobs)), "manifest.json", "job totals/completeness")
    expect(manifest["run_count"] == totals["ok"] and manifest["series_count"] == len(series)
           and manifest["comparison_count"] == sum(c["accepted"] > 0 for c in observed.values()),
           "manifest.json", "collection counts differ")
    expect(manifest["privacy"]["end_to_end_report_is_dp"] is False and manifest["privacy"]["global_privacy_bound"] is None,
           "manifest.privacy", "unfounded global privacy claim")
    observation = manifest["observation"]
    times = [datetime.fromisoformat(observation[k]) for k in ("started_at_utc", "finished_at_utc")]
    expect(all(t.utcoffset() == timedelta(0) for t in times) and times[0] <= times[1] and observation["boundary"],
           "manifest.observation", "invalid snapshot time interval")
    data = _data(a, plan, manifest)
    _replay(a, manifest)
    sessions = index(manifest["sessions"], "session_id", "manifest.sessions")
    attempts = set()
    headers = FLAT + ("job_id","comparison_id","attempt_id","group_id")
    all_rows = a.csv("all_results.csv", headers)
    by_job = index(all_rows, "job_id", "all_results.csv")
    successes = [j for j in jobs if outcomes[j]["status"] == "ok"]
    expect(list(by_job) == successes, "all_results.csv", "missing, duplicate, reordered or extra success")
    by_cmp = defaultdict(list)
    for job in jobs.values():
        expect(job["comparison_id"] in cmps and job["series"] == cmps[job["comparison_id"]]["series"],
               job["job_id"], "job comparison membership")
        by_cmp[job["comparison_id"]].append(job)
    for name, entry in series_entries.items():
        _subset(entry, series[name], name)
        folder = entry["path"]
        expect(folder in a.dirs and "/" not in folder and folder not in ("datasets","reproduce"),
               name, f"invalid series directory {folder}")
        comparisons = [c for c in cmps.values() if c["series"] == name]
        planned = [j for j in jobs.values() if j["series"] == name]
        with checking(folder):
            for subdir in ("history", "logs", "predictions"):
                expect(f"{folder}/{subdir}" in a.dirs, folder, f"missing required directory {subdir}")
            series_totals = dict.fromkeys(STATUSES, 0) | dict(Counter(outcomes[j["job_id"]]["status"] for j in planned))
            history_count = sum(observed[c["comparison_id"]]["accepted"] > 0 for c in comparisons)
            facts = {"planned": len(planned), "run_count": series_totals["ok"], "comparison_count": history_count,
                     "complete": len(planned) == series_totals["ok"], "n_features": entry["n_features"],
                     "n_samples": entry["n_samples"], "n_classes": entry["n_classes"]}
            definition = next(d for d in plan["datasets"] if d["key"] == entry["dataset"])
            _subset(entry, dict(facts, totals=series_totals, accepted=series_totals["ok"], planned_comparisons=len(comparisons),
                                dataset_name=definition["name"], n_features=definition["n_features"],
                                n_samples=definition["n_samples"], n_classes=definition["n_classes"]), folder)
            protocol = a.json(f"{folder}/protocol.json")
            _subset(protocol, dict(format="pyclusteval.series-protocol.v1", series=name, dataset_name=entry["dataset_name"], dataset_id=entry["dataset_id"],
                                   seed=entry["seed"], comparisons=comparisons, execution=plan["execution"]), folder)
            exp_plan = a.json(f"{folder}/experiment_plan.json")
            expect(len(exp_plan) == len(planned), folder, "series plan coverage")
            for row, job in zip(exp_plan, planned, strict=True):
                result = outcomes[job["job_id"]]
                gid = groups[job["job_id"]]
                expect(result["group_id"] == gid, job["job_id"], "manifest job statistical group differs")
                _subset(row, dict(job, id=job["run_id"], group_id=gid, status=result["status"], reason=result["reason"],
                                  accepted_attempt_id=(result["accepted"] or {}).get("attempt_id")), folder)
            collection = a.json(f"{folder}/report.json")
            _subset(collection, facts, folder)
            expect(collection["format"] == "pyclusteval.benchmark-series.v1" and collection["series"] == name and
                   collection["protocol"] == protocol and collection["seed"] == entry["seed"] and
                   collection["dataset_name"] == entry["dataset_name"], folder, "series collection header")
            rows = a.csv(f"{folder}/results.csv", headers)
            expect(rows == [r for r in all_rows if r["series"] == name], folder, "series and root flat tables differ")
            runs = index(collection["runs"], "job_id", folder)
            experiments = index(collection["experiments"], "comparison_id", folder)
            expect(list(runs) == [r["job_id"] for r in rows] and
                   list(experiments) == [c["comparison_id"] for c in comparisons if observed[c["comparison_id"]]["accepted"]],
                   folder, "series report coverage")
            parts = a.json(f"{folder}/partitions.json")
            expect(set(parts) == {c["comparison_id"] for c in comparisons}, folder, "partition scope")
            history_keys = {s.history_key for s in HistoryQueryService(a.root / folder / "history").list_experiments()}
            expect(history_keys == {e["history_key"] for e in experiments.values()}, folder, "native history set")
            for cmp in comparisons:
                cid = cmp["comparison_id"]
                rec = observed[cid]
                _subset(rec, {k: cmp[k] for k in ("series", "comparison_id", "dataset_id", "scenario")}, cid)
                _comparison(a, cmp, rec, by_cmp[cid], outcomes, entry, parts[cid], runs, experiments.get(cid),
                            by_job, data, sessions, attempts, source)
    check_summary(a, all_rows, plan)
    a.counts["scientific_jobs"] = len(jobs)
    a.complete = manifest["complete"]
