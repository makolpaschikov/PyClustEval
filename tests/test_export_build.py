from __future__ import annotations

import csv
from datetime import datetime, timedelta
from hashlib import sha256
import errno
import json
from pathlib import Path
import sqlite3
import sys
from uuid import uuid4
from zipfile import ZipFile

import numpy as np
import pytest

from clustering_eval.application import compute, HistoryQueryService
from clustering_eval.experiments import prepared_store, runner_campaign, runner_queue, runner_reader, runner_records, runner_state
from clustering_eval.results.archive_build import build_archive

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="RUNNER snapshot observes the Windows supervisor")


@pytest.fixture
def small_campaign(tmp_path):
    root = tmp_path / "job directory"
    matrix = np.arange(42, dtype=np.int16).reshape(14, 3)
    labels = np.repeat([0, 1], 7).astype(np.int8)
    original = tmp_path / "external input.npz"
    np.savez_compressed(original, X=matrix, y=labels)
    document = {
        "format": "pyclusteval.plan.v1", "campaign": {"name": "sample", "output_dir": str(root)},
        "datasets": {"input": {"provider": "npz", "name": "custom", "path": original.name,
                               "sha256": sha256(original.read_bytes()).hexdigest()}},
        "scenarios": {"local": {"algorithms": ["agglomerative", "kmeans"], "mode": "local"}},
        "series": [{"name": "datasets", "dataset": "input", "seed": 17, "scenarios": ["local"]}],
    }
    source = tmp_path / "sample.json"
    source.write_text(json.dumps(document), encoding="utf-8")
    raw, plan = runner_campaign.input_plan(source)
    runner_campaign.create_campaign(root, source, raw, plan)
    return root, source, plan, original


def mark_running(db, root, job, plan, binding, session):
    request = dict(binding, attempt_id=uuid4().hex, job_id=job["job_id"],
                   comparison_id=job["comparison_id"], source_id=plan["source_id"], job=job)
    runner_state.begin_attempt(db, request, session, "initial")
    folder = root / "attempts" / request["attempt_id"]
    folder.mkdir()
    (folder / "request.json").write_text(runner_state.encode(request), encoding="utf-8")
    return request, folder


def accept_current_result(db, root, job, plan, binding, inputs, session, **measurements):
    request, folder = mark_running(db, root, job, plan, binding, session)
    execution = compute.execute_one(inputs, job["job_id"])
    worker = dict(pid=123, started_at_utc=execution.started_at.isoformat(),
                  finished_compute_at_utc=execution.finished_at.isoformat(), **measurements)
    runner_records.publish_success(folder, request, execution, worker)
    (folder / "stdout.log").write_bytes(b"Finished\n")
    (folder / "stderr.log").write_bytes(b"")
    runner_queue.accept(db, root, request, {})
    return request, folder, execution


def test_unprepared_export_uses_only_saved_materials(small_campaign, tmp_path):
    root, source, plan, original = small_campaign
    source.unlink()
    original.unlink()
    output = tmp_path / "empty archive"
    output.mkdir()
    manifest = build_archive(root, output)
    for field in ("started_at_utc", "finished_at_utc"):
        assert datetime.fromisoformat(manifest["observation"][field]).utcoffset() == timedelta(0)
    assert manifest["planned"] == 2 and not manifest["complete"]
    assert manifest["totals"]["pending"] == 2
    assert manifest["series"][0]["path"] != "datasets"
    assert manifest["comparisons"][0]["preparation_status"] == "unprepared"
    assert manifest["comparisons"][0]["history_report"] is None
    assert manifest["datasets"][0]["available"] is False
    assert not list(output.rglob("dataset.npz"))
    assert all(job["reason"] and not job["attempts"] for job in manifest["jobs"])
    assert not list(csv.DictReader((output / "all_results.csv").read_text().splitlines()))
    assert json.loads((output / "reproduce/resolved_plan.json").read_bytes()) == plan


def test_partial_keeps_worker_bytes_and_records_live_attempt(small_campaign, tmp_path):
    root, source, plan, external = small_campaign
    first, second = plan["jobs"]
    cid = first["comparison_id"]
    with runner_state.journal(root) as db:
        binding = runner_campaign.ensure_prepared(db, root, plan, cid, source.parent)
        inputs = prepared_store.read(runner_campaign.descriptor_path(root, cid), plan["source_id"], cid)
        session = runner_state.start_session(db, "run", plan["execution"])
        request, folder, result = accept_current_result(db, root, first, plan, binding, inputs, session)
        _, live_folder = mark_running(db, root, second, plan, binding, session)
        (live_folder / "stdout.log").write_bytes(b"growing stream")
    external.unlink()
    output = tmp_path / "partial"
    output.mkdir()
    manifest = build_archive(root, output)
    first_job, live_job = manifest["jobs"]
    assert manifest["totals"]["ok"] == manifest["totals"]["running"] == 1
    assert first_job["accepted"]["attempt_id"] == request["attempt_id"]
    assert live_job["accepted"] is None
    assert live_job["attempts"][0]["archive_logs"]["stdout"]["status"] == "in_progress"
    accepted = first_job["accepted"]
    assert (output / accepted["result_path"]).read_bytes() == (folder / "result.json").read_bytes()
    with ZipFile(output / accepted["prediction_path"]) as archive:
        assert archive.read("labels.npy") == (folder / "labels.npy").read_bytes()
    directory = output / manifest["datasets"][0]["path"]
    with np.load(directory / "dataset.npz", allow_pickle=False) as data:
        np.testing.assert_array_equal(data["X"], inputs.X_raw, strict=True)
        np.testing.assert_array_equal(data["y"], inputs.y, strict=True)
    native_path = output / accepted["history_report"]
    native = json.loads(native_path.read_bytes())
    assert not native["complete"] and native["results"][0]["history"] == result.report.history
    collection = json.loads((output / manifest["series"][0]["path"] / "report.json").read_bytes())
    assert collection["runs"][0]["job"]["id"] == first["run_id"]
    assert collection["runs"][0]["job"]["local"] is True
    assert collection["runs"][0]["input_shape"] == list(inputs.X_raw.shape)
    assert native["results"][0]["ari"] == result.report.ari
    history = HistoryQueryService(native_path.parents[1]).get_experiment(native_path.parent.name)
    assert len(history.results) == 1 and history.results[0].ami == result.report.ami
    replay = output / "reproduce/portable_plan.json"
    from clustering_eval.experiments.plan_io import read_document
    from clustering_eval.experiments.series_plan import resolve_document

    relocated = resolve_document(read_document(replay), base_dir=replay.parent, source_id=plan["source_id"])
    assert [j["job_id"] for j in relocated["jobs"]] == [j["job_id"] for j in plan["jobs"]]
    # The accepted worker bundle is still intact. Damage to the recorded input
    # must prevent export even though RUNNER's snapshot can read both job records.
    descriptor = runner_campaign.descriptor_path(root, cid)
    (descriptor.parent / "X_raw.npy").write_bytes(b"changed")
    next_output = tmp_path / "damaged"
    next_output.mkdir()
    with pytest.raises(runner_state.IntegrityError, match="prepar|checksum"):
        build_archive(root, next_output)


def test_optional_worker_measurements_retain_recorded_values_and_origins(small_campaign, tmp_path):
    root, source, plan, _ = small_campaign
    cid = plan["comparisons"][0]["comparison_id"]
    measured = {"cpu_affinity": [1, 3], "elapsed_to_observation_sec": 0.0}
    with runner_state.journal(root) as db:
        binding = runner_campaign.ensure_prepared(db, root, plan, cid, source.parent)
        inputs = prepared_store.read(runner_campaign.descriptor_path(root, cid), plan["source_id"], cid)
        session = runner_state.start_session(db, "run", plan["execution"])
        for job, worker_fields in zip(plan["jobs"], (measured, {}), strict=True):
            accept_current_result(db, root, job, plan, binding, inputs, session, **worker_fields)
    output = tmp_path / "observations"
    output.mkdir()
    manifest = build_archive(root, output)
    collection = json.loads((output / manifest["series"][0]["path"] / "report.json").read_bytes())
    native = json.loads((output / manifest["comparisons"][0]["history_report"]).read_bytes())
    for job, run, result in zip(manifest["jobs"], collection["runs"], native["results"], strict=True):
        worker = json.loads((output / job["accepted"]["result_path"]).read_bytes())["worker"]
        assert run["cpu_affinity"] == worker.get("cpu_affinity")
        assert run["total_wall_sec"] == worker.get("elapsed_to_observation_sec")
        for origin in (run["source_run"], result["source_run"], result["model_state"]["source_run"]):
            for field, source_key in (("cpu_affinity", "cpu_affinity"), ("total_wall_sec", "elapsed_to_observation_sec")):
                assert origin[field] == worker.get(source_key)
                expected = "worker." + source_key if source_key in worker else "not recorded"
                assert origin["field_origins"][field] == expected


def test_locked_original_plan_names_its_read_stage(small_campaign, tmp_path):
    import msvcrt

    root, _, _, _ = small_campaign
    original = root / "raw" / "plan.json"
    output = tmp_path / "locked-plan"
    output.mkdir()
    with original.open("r+b") as handle:
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        try:
            with pytest.raises(PermissionError) as error:
                build_archive(root, output)
            location = Path(error.value.filename)
            assert location in (original, original.parent)
            if location == original.parent:
                assert original.parent.as_posix() in str(error.value)
                assert "Reading saved plans and captured source" in str(error.value)
        finally:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


def test_access_failure_during_export_preserves_operational_error(small_campaign, tmp_path, monkeypatch):
    root, source, plan, _ = small_campaign
    job = plan["jobs"][0]
    cid = job["comparison_id"]
    with runner_state.journal(root) as db:
        binding = runner_campaign.ensure_prepared(db, root, plan, cid, source.parent)
        descriptor = runner_campaign.descriptor_path(root, cid)
        inputs = prepared_store.read(descriptor, plan["source_id"], cid)
        session = runner_state.start_session(db, "run", plan["execution"])
        _, folder, _ = accept_current_result(db, root, job, plan, binding, inputs, session)

    original_open = Path.open
    protected = (root / "raw" / "plan.json", descriptor.parent / "X_raw.npy",
                 folder / "result.json", folder / "stdout.log")
    for index, blocked in enumerate(protected):
        def deny(path, *args, **kwargs):
            if path == blocked:
                # On Windows, a lock can fail a read on an open handle without a filename.
                raise PermissionError(errno.EACCES, "test sharing violation")
            return original_open(path, *args, **kwargs)

        output = tmp_path / f"blocked-{index}"
        output.mkdir()
        with monkeypatch.context() as patch:
            patch.setattr(Path, "open", deny)
            with pytest.raises(PermissionError, match="test sharing violation") as error:
                build_archive(root, output)
            assert blocked.parent.as_posix() in str(error.value)
            if blocked.parent == root / "raw":
                assert "Reading saved plans and captured source" in str(error.value)
            if blocked.parent == folder:
                # Existing status callers still obtain a per-job integrity diagnostic.
                assert runner_reader.read_campaign(root)["jobs"][0]["accepted"] is None

    (folder / "result.json").unlink()
    missing = tmp_path / "missing"
    missing.mkdir()
    with pytest.raises(runner_state.IntegrityError, match="result.json"):
        build_archive(root, missing)


@pytest.mark.parametrize("code,operational", [
    (sqlite3.SQLITE_CANTOPEN, True), (sqlite3.SQLITE_IOERR_READ, True), (sqlite3.SQLITE_NOTADB, False),
])
def test_journal_operational_errors_retain_primary_codes(code, operational):
    cause = sqlite3.OperationalError("SQLite journal")
    cause.sqlite_errorcode = code
    wrapped = runner_state.IntegrityError("wrapped journal read")
    wrapped.__cause__ = cause
    assert isinstance(runner_state.operational_read_error(wrapped), OSError) is operational


def test_migrated_jobs_retain_global_order_and_partial_group_membership(tmp_path):
    from clustering_eval.experiments.plan_legacy import migrate_legacy
    from clustering_eval.results.archive_science import group_ids

    old = {"experiment": {"name": "legacy", "seeds": [17, 29]},
           "datasets": [{"name": "iris"}], "algorithms": [{"name": "agglomerative"}, {"name": "kmeans"}]}
    document = migrate_legacy(old, plan_dir=tmp_path, legacy_cwd=tmp_path)
    root = tmp_path / "interleaved"
    document["campaign"]["output_dir"] = str(root)
    source = tmp_path / "input.json"
    source.write_text(json.dumps(document), encoding="utf-8")
    raw, plan = runner_campaign.input_plan(source)
    runner_campaign.create_campaign(root, source, raw, plan)
    planned = plan["jobs"]
    assert [job["series"] for job in planned] == ["series-1", "series-2", "series-1", "series-2"]
    with runner_state.journal(root) as db:
        session = runner_state.start_session(db, "run", plan["execution"])
        for job in planned[:3]:
            cid = job["comparison_id"]
            binding = runner_campaign.ensure_prepared(db, root, plan, cid, tmp_path)
            inputs = prepared_store.read(runner_campaign.descriptor_path(root, cid), plan["source_id"], cid)
            accept_current_result(db, root, job, plan, binding, inputs, session)
        runner_state.stop_session(db, session, "test partial snapshot")

    output = tmp_path / "archive"
    output.mkdir()
    manifest = build_archive(root, output)
    expected = [job["job_id"] for job in planned]
    assert [job["job_id"] for job in manifest["jobs"]] == expected
    assert [cmp["comparison_id"] for cmp in manifest["comparisons"]] == [
        cmp["comparison_id"] for cmp in plan["comparisons"]]
    with (output / "all_results.csv").open(encoding="utf-8", newline="") as stream:
        assert [row["job_id"] for row in csv.DictReader(stream)] == expected[:3]
    groups = group_ids(plan)
    assert [(job["job_id"], job["group_id"]) for job in manifest["jobs"]] == [(key, groups[key]) for key in expected]
    assert manifest["jobs"][-1]["reason"] and manifest["jobs"][-1]["accepted"] is None
    for series in manifest["series"]:
        subset = [j for j in planned if j["series"] == series["name"]]
        records = json.loads((output / series["path"] / "experiment_plan.json").read_bytes())
        assert [(j["job_id"], j["group_id"]) for j in records] == [
            (j["job_id"], groups[j["job_id"]]) for j in subset]
