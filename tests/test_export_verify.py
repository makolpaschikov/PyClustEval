"""Archive verification from an actual small campaign, with independently resealed corrupt copies."""
from __future__ import annotations

import csv
import json
from pathlib import Path
import shutil
import sys

import numpy as np
import pytest

from clustering_eval.results.archive_verify import file_sha, verify_archive


def dump(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, allow_nan=False), encoding="utf-8")


def seal(folder: Path) -> None:
    """Rebuild the file inventory even after semantic corruption."""
    files = []
    for p in sorted(folder.rglob("*")):
        if p.is_file() and p != folder / "checksums.json":
            files.append(dict(path=p.relative_to(folder).as_posix(), bytes=p.stat().st_size, sha256=file_sha(p)))
    dump(folder / "checksums.json", dict(algorithm="sha256", files=files))


@pytest.fixture(scope="module")
def archive(tmp_path_factory):
    if sys.platform != "win32":
        pytest.skip("RUNNER process isolation requires Windows")
    from clustering_eval.results.archive_build import build_archive
    from test_runner_cli import series, write_plan
    from test_runner_state import plan_document

    temp = tmp_path_factory.mktemp("archive-evidence")
    campaign = temp / "campaign"
    doc = plan_document(campaign)
    doc["scenarios"]["test"] = dict(mode="federated", algorithms=["fed_kmeans_numpy"], rounds=2,
                                    num_clients=3, partition_mode="dirichlet", dirichlet_alpha=0.5,
                                    stopping_profile="current_gui")
    assert series("run", write_plan(temp, doc), code=0)["totals"]["ok"] == 1
    result = temp / "portable"
    result.mkdir()
    build_archive(campaign, result)
    initial = verify_archive(result, check_checksums=False)
    assert initial["valid"] and initial["complete"], initial
    dump(result / "verification.json", initial)
    seal(result)
    return result


def test_verify_survives_relocation_and_writes_nothing(archive, tmp_path):
    relocated = shutil.copytree(archive, tmp_path / "relocated results")
    before = {p.relative_to(relocated): (p.stat().st_mtime_ns, file_sha(p))
              for p in relocated.rglob("*") if p.is_file()}
    report = verify_archive(relocated)
    assert report["valid"] and report["complete"], report
    assert {p.relative_to(relocated): (p.stat().st_mtime_ns, file_sha(p))
            for p in relocated.rglob("*") if p.is_file()} == before


@pytest.mark.parametrize("change", ["labels", "indices", "native_state", "attempt", "aggregate",
                                    "group_condition", "foreign_row", "orphan", "path", "count"])
def test_content_errors_after_resealing(archive, tmp_path, change):
    p = shutil.copytree(archive, tmp_path / "changed")
    manifest = json.loads((p / "manifest.json").read_bytes())
    job, = manifest["jobs"]
    loc = job["accepted"]
    series, = manifest["series"]
    cmp, = manifest["comparisons"]
    if change == "labels":
        pred = p / loc["prediction_path"]
        with np.load(pred, allow_pickle=False) as z:
            labels = z["labels"]
        np.savez(pred, labels=labels[::-1].astype(np.int16))
    elif change == "indices":
        target = p / series["path"] / "partitions.json"
        parts = json.loads(target.read_bytes())
        rows = parts[cmp["comparison_id"]]["indices"]
        rows[1][0] = rows[0][0]
        dump(target, parts)
    elif change == "native_state":
        target = p / loc["history_report"]
        native = json.loads(target.read_bytes())
        native["results"][0]["model_state"]["spurious_measurement"] = 1
        dump(target, native)
    elif change == "attempt":
        job["attempts"][0]["request"]["source_id"] = "f" * 64
        dump(p / "manifest.json", manifest)
    elif change in ("aggregate", "foreign_row", "group_condition"):
        target = p / ("all_results.csv" if change == "foreign_row" else "aggregate_by_dataset.csv")
        with target.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            columns, rows = reader.fieldnames, list(reader)
        fields = {"aggregate": ("ari_valid_n", "9"), "group_condition": ("conditions_json", "{}"),
                  "foreign_row": ("job_id", "another_job")}
        key, value = fields[change]
        rows[0][key] = value
        with target.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            writer.writerows(rows)
    elif change == "orphan":
        (p / "extra-result.txt").write_text("unreferenced", encoding="utf-8")
    elif change == "count":
        series["comparison_count"] += 1
        dump(p / "manifest.json", manifest)
    else:
        loc["result_path"] = "../unknown.json"
        dump(p / "manifest.json", manifest)
    seal(p)
    report = verify_archive(p)
    assert report["valid"] is False and report["errors"], (change, report)
    assert not any("catalog differs" in error or "checksum size" in error for error in report["errors"])


def test_legacy_checksum_diagnosis_names_bad_file(tmp_path):
    dump(tmp_path / "manifest.json", dict(format="pyclusteval.three-datasets-three-seeds.v1"))
    (tmp_path / "README.md").write_text("original", encoding="utf-8")
    seal(tmp_path)
    (tmp_path / "README.md").write_text("changed", encoding="utf-8")
    report = verify_archive(tmp_path)
    assert report["valid"] is False and "README.md" in report["errors"][0]
    assert report["not_checked"]


def test_unknown_format_is_an_unsupported_input(tmp_path):
    dump(tmp_path / "manifest.json", dict(format="future.version"))
    with pytest.raises(ValueError, match="Unsupported archive format"):
        verify_archive(tmp_path)


@pytest.mark.parametrize(("location", "field", "replacement"), [
    ("collection", "input_shape", [7200, 91]), ("collection", "id", "unrelated_id"),
    ("collection", "partition_hash", "wrong_partition"), ("collection", "client_sizes", []),
    ("collection", "total_wall_sec", -42), ("partition", "dirichlet_alpha", 0.98765),
    ("partition", "num_clients", 15), ("partition", "dropout_rate", 0.5),
    ("provenance", "plan_path", "absent/experiment_plan.json"),
    ("provenance", "plan_path", "reproduce/resolved_plan.json"),
])
def test_redundant_scientific_fields_agree_after_resealing(archive, tmp_path, location, field, replacement):
    p = shutil.copytree(archive, tmp_path / "changed")
    manifest = json.loads((p / "manifest.json").read_bytes())
    if location == "collection":
        target = p / manifest["series"][0]["path"] / "report.json"
        obj = json.loads(target.read_bytes())
        record = obj["runs"][0]
    else:
        target = p / manifest["comparisons"][0]["history_report"]
        obj = json.loads(target.read_bytes())
        record = obj["partition" if location == "partition" else "export_provenance"]
    assert record[field] != replacement
    record[field] = replacement
    dump(target, obj)
    seal(p)
    report = verify_archive(p)
    assert not report["valid"] and any(field in e for e in report["errors"]), report


@pytest.fixture(scope="module")
def pending(tmp_path_factory):
    if sys.platform != "win32":
        pytest.skip("RUNNER campaign snapshots require Windows")
    from clustering_eval.experiments.runner_campaign import create_campaign, input_plan
    from clustering_eval.results.archive_build import build_archive
    from test_runner_cli import write_plan
    from test_runner_state import plan_document

    temp = tmp_path_factory.mktemp("unprepared-archive")
    campaign = temp / "campaign"
    doc = plan_document(campaign)
    doc["scenarios"]["test"]["algorithms"].append("agglomerative")
    source = write_plan(temp, doc)
    raw, plan = input_plan(source)
    create_campaign(campaign, source, raw, plan)
    result = temp / "partial"
    result.mkdir()
    build_archive(campaign, result)
    initial = verify_archive(result, check_checksums=False)
    assert initial["valid"] and not initial["complete"], initial
    dump(result / "verification.json", initial)
    seal(result)
    return result


@pytest.mark.parametrize("location", ["manifest", "series_plan"])
def test_unaccepted_job_cannot_change_statistical_group(pending, tmp_path, location):
    p = shutil.copytree(pending, tmp_path / "changed")
    manifest = json.loads((p / "manifest.json").read_bytes())
    target = p / "manifest.json" if location == "manifest" else p / manifest["series"][0]["path"] / "experiment_plan.json"
    file = json.loads(target.read_bytes())
    jobs = file["jobs"] if location == "manifest" else file
    assert jobs[0]["group_id"] != jobs[1]["group_id"] and all(j["status"] == "pending" for j in jobs)
    jobs[0]["group_id"] = jobs[1]["group_id"]
    dump(target, file)
    seal(p)
    report = verify_archive(p)
    assert not report["valid"] and any("group" in e for e in report["errors"])


@pytest.mark.parametrize("name", ["history", "predictions", "logs"])
def test_empty_series_directories_are_required(pending, tmp_path, name):
    p = shutil.copytree(pending, tmp_path / "changed")
    manifest = json.loads((p / "manifest.json").read_bytes())
    (p / manifest["series"][0]["path"] / name).rmdir()
    report = verify_archive(p)
    assert not report["valid"] and any(name in e for e in report["errors"])


def test_windows_sharing_failure_is_operational(pending):
    import msvcrt

    manifest = pending / "manifest.json"
    with manifest.open("r+b") as stream:
        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        with pytest.raises(PermissionError, match="manifest.json"):
            verify_archive(pending)
    assert verify_archive(pending)["valid"]


@pytest.mark.skipif(sys.platform != "win32", reason="RUNNER campaign snapshots require Windows")
@pytest.mark.parametrize("observations", [
    {}, {"cpu_affinity": [0, 2]}, {"cpu_affinity": [], "elapsed_to_observation_sec": 0.0},
    {"cpu_affinity": None, "elapsed_to_observation_sec": None},
], ids=["unobserved", "observed-affinity", "observed-empty-and-zero", "explicitly-unknown"])
def test_worker_observations_and_their_origins_survive_partial_export(tmp_path, observations):
    from clustering_eval.application.compute import execute_one
    from clustering_eval.experiments import prepared_store, runner_campaign, runner_queue, runner_records, runner_state
    from clustering_eval.results.archive_build import build_archive
    from test_export_build import mark_running
    from test_runner_cli import write_plan
    from test_runner_state import plan_document

    root = tmp_path / "campaign"
    doc = plan_document(root)
    doc["scenarios"]["test"]["algorithms"].append("agglomerative")
    source = write_plan(tmp_path, doc)
    original, plan = runner_campaign.input_plan(source)
    runner_campaign.create_campaign(root, source, original, plan)
    job = plan["jobs"][0]
    cid = job["comparison_id"]
    with runner_state.journal(root) as db:
        binding = runner_campaign.ensure_prepared(db, root, plan, cid, tmp_path)
        prepared = prepared_store.read(runner_campaign.descriptor_path(root, cid), plan["source_id"], cid)
        session = runner_state.start_session(db, "run", plan["execution"])
        request, attempt = mark_running(db, root, job, plan, binding, session)
        execution = execute_one(prepared, job["job_id"])
        worker = {"pid": 123, "started_at_utc": execution.started_at.isoformat(),
                  "finished_compute_at_utc": execution.finished_at.isoformat()}
        worker.update(observations)
        runner_records.publish_success(attempt, request, execution, worker)
        (attempt / "stdout.log").write_bytes(b"")
        (attempt / "stderr.log").write_bytes(b"")
        runner_queue.accept(db, root, request, {})
        runner_state.stop_session(db, session, "partial test snapshot")

    folder = tmp_path / "archive"
    folder.mkdir()
    manifest = build_archive(root, folder)
    assert manifest["totals"]["ok"] == manifest["totals"]["pending"] == 1
    accepted = manifest["jobs"][0]["accepted"]
    worker = json.loads((folder / accepted["result_path"]).read_bytes())["worker"]
    for key in ("elapsed_to_observation_sec", "cpu_affinity"):
        assert (key in worker) == (key in observations) and worker.get(key) == observations.get(key)
    collection_path = folder / manifest["series"][0]["path"] / "report.json"
    collection = json.loads(collection_path.read_bytes())
    run, = collection["runs"]
    elapsed = observations.get("elapsed_to_observation_sec")
    affinity = observations.get("cpu_affinity")
    assert run["total_wall_sec"] == elapsed and run["cpu_affinity"] == affinity
    expected_origins = {"total_wall_sec": "not recorded" if elapsed is None else "worker.elapsed_to_observation_sec",
                        "cpu_affinity": "not recorded" if affinity is None else "worker.cpu_affinity"}
    for key, origin in expected_origins.items():
        assert run["source_run"]["field_origins"][key] == origin

    preseal = verify_archive(folder, check_checksums=False)
    assert preseal["valid"] and not preseal["complete"], preseal
    dump(folder / "verification.json", preseal)
    seal(folder)
    assert verify_archive(folder)["valid"]
    run["total_wall_sec"] = 0.0 if elapsed is None else 1.0
    dump(collection_path, collection)
    seal(folder)
    invalid = verify_archive(folder)
    assert not invalid["valid"] and any("total_wall_sec" in error for error in invalid["errors"]), invalid
    run.update(total_wall_sec=elapsed, cpu_affinity=[3])
    dump(collection_path, collection)
    seal(folder)
    invalid = verify_archive(folder)
    assert not invalid["valid"] and any("cpu_affinity" in error for error in invalid["errors"]), invalid
    run["cpu_affinity"] = affinity
    # Alter every display copy together to isolate comparison with the primary worker evidence.
    native_path = folder / accepted["history_report"]
    native = json.loads(native_path.read_bytes())
    native_result, = native["results"]
    for key, origin in expected_origins.items():
        for view in (run["source_run"], native_result["source_run"], native_result["model_state"]["source_run"]):
            view["field_origins"].update(expected_origins)
            view["field_origins"][key] = "worker.fake_measurement" if origin == "not recorded" else "not recorded"
        dump(collection_path, collection)
        dump(native_path, native)
        seal(folder)
        invalid = verify_archive(folder)
        assert not invalid["valid"] and any("field_origins" in e and key in e for e in invalid["errors"]), invalid
