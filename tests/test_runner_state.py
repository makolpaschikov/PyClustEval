"""Durability and no-regeneration boundaries that do not need an algorithm process."""
from __future__ import annotations

import errno
import json
from pathlib import Path
import sqlite3

import pytest

from clustering_eval.experiments import runner_campaign as campaign, runner_queue as queue, runner_state as state


def plan_document(directory: Path) -> dict:
    return {"format": "pyclusteval.plan.v1", "campaign": {"name": "campaign", "output_dir": str(directory)},
            "datasets": {"d": {"provider": "registry", "name": "iris"}},
            "scenarios": {"test": {"algorithms": ["kmeans"], "mode": "local"}},
            "series": [{"name": "series", "dataset": "d", "seed": 17, "scenarios": ["test"]}]}


@pytest.fixture
def initialized(tmp_path):
    journal_root = tmp_path / "new campaign"
    source = tmp_path / "input.json"
    source.write_text(json.dumps(plan_document(journal_root)), encoding="utf-8")
    raw, plan = campaign.input_plan(source)
    campaign.create_campaign(journal_root, source, raw, plan)
    return journal_root, source, plan


def test_accepted_pointer_and_state_commit_in_one_transaction(initialized):
    root, _, plan = initialized
    job = plan["jobs"][0]
    with state.journal(root) as db:
        session = state.start_session(db, "run", plan["execution"])
        state.begin_attempt(db, {"attempt_id": "attempt-1", "job_id": job["job_id"]}, session, "initial")
        db.execute("CREATE TEMP TRIGGER fail_commit BEFORE UPDATE ON jobs WHEN NEW.status='ok' "
                   "BEGIN SELECT RAISE(ABORT, 'injected failure'); END")
        with pytest.raises(sqlite3.IntegrityError, match="injected failure"):
            state.finish_attempt(db, "attempt-1", "ok", "accepted", accepted_hash="a" * 64)
        assert tuple(db.execute("SELECT status,accepted_hash FROM attempts").fetchone()) == ("running", None)
        assert db.execute("SELECT status FROM jobs").fetchone()[0] == "running"
    with state.journal(root) as db:
        state.finish_attempt(db, "attempt-1", "ok", "accepted", accepted_hash="a" * 64)
        assert tuple(db.execute("SELECT status,accepted_hash FROM attempts").fetchone()) == ("ok", "a" * 64)
        with pytest.raises(state.IntegrityError, match="Invalid attempt start"):
            state.begin_attempt(db, {"job_id": job["job_id"], "attempt_id": "new"}, session, "manual")


def test_save_and_recheck_plan_source_and_original_data(initialized, monkeypatch):
    root, source, plan = initialized
    with state.journal(root) as db:
        meta = state.header(db)
    assert campaign.saved_plan(root, meta) == plan
    source.write_text("{}", encoding="utf-8")
    with pytest.raises(state.IntegrityError, match="Original plan bytes changed"):
        campaign.verify_live_inputs(root, meta, plan)
    source.unlink()
    monkeypatch.setattr(campaign, "checkout_source_id", lambda: "0" * 64)
    with pytest.raises(state.IntegrityError, match="Current checkout"):
        campaign.verify_live_inputs(root, meta, plan)
    (root / "raw" / "plan.json").write_bytes(b"{}")
    with pytest.raises(state.IntegrityError, match="Saved plan checksum"):
        campaign.saved_plan(root, meta)


def test_recover_completed_preparation_without_recalculation(initialized, monkeypatch):
    root, source, plan = initialized
    cid = plan["comparisons"][0]["comparison_id"]
    descriptor = campaign.descriptor_path(root, cid)
    with state.journal(root) as db:
        with db:
            db.execute("INSERT INTO preparations VALUES (?,NULL,NULL)", (cid,))
        campaign.prepare(plan, cid, descriptor.parent, source_id=plan["source_id"], base_dir=source.parent)
        monkeypatch.setattr(campaign, "prepare", lambda *a, **kw: pytest.fail("regeneration"))
        binding = campaign.ensure_prepared(db, root, plan, cid, source.parent)
        assert binding["n_samples"] == 150
        assert campaign.ensure_prepared(db, root, plan, cid, source.parent) == binding
        descriptor.unlink()
        descriptor.parent.with_suffix(".reservation").unlink()
        with pytest.raises(state.IntegrityError, match="release may be unknown"):
            campaign.ensure_prepared(db, root, plan, cid, source.parent)


def test_disk_write_failure_stops_before_launch_and_preserves_attempt(initialized, monkeypatch):
    root, source, plan = initialized
    job = plan["jobs"][0]
    def no_room(*args):
        raise OSError(errno.ENOSPC, "injected disk full")
    monkeypatch.setattr(queue, "create_file", no_room)
    with state.journal(root) as db:
        binding = campaign.ensure_prepared(db, root, plan, job["comparison_id"], source.parent)
        session = state.start_session(db, "run", plan["execution"])
        with pytest.raises(OSError, match="injected disk full"):
            queue.execute(db, root, plan, job, binding, policy=plan["execution"],
                          deadline=None, session=session, kind="initial")
        assert db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == 1
        assert db.execute("SELECT status FROM jobs").fetchone()[0] == "running"
        queue.recover_running(db, root)
        assert db.execute("SELECT status FROM jobs").fetchone()[0] == "interrupted"


def test_slow_verification_reader_releases_live_database(initialized, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from clustering_eval.experiments import runner_reader

    root, _, plan = initialized
    reached, release = Event(), Event()
    read = runner_reader.saved_plan

    def slow_verify(*args):
        reached.set()
        assert release.wait(timeout=20)
        return read(*args)

    monkeypatch.setattr(runner_reader, "saved_plan", slow_verify)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(runner_reader.read_campaign, root)
        try:
            assert reached.wait(timeout=10)
            with state.journal(root) as db:
                db.execute("PRAGMA busy_timeout=100")
                session = state.start_session(db, "resume", plan["execution"])
                state.stop_session(db, session, "verification fixture")
        finally:
            release.set()
        snapshot = future.result(timeout=20)
    assert snapshot["sessions"] == []
    assert runner_reader.read_campaign(root)["sessions"][0]["stop_reason"] == "verification fixture"


def test_interrupted_creation_is_recognized_before_any_worker(tmp_path, monkeypatch):
    root = tmp_path / "interrupted"
    source = tmp_path / "p.json"
    source.write_text(json.dumps(plan_document(root)), encoding="utf-8")
    raw, plan = campaign.input_plan(source)

    def fail_capture(*args):
        raise OSError(errno.ENOSPC, "injected during initialization")

    monkeypatch.setattr(campaign, "capture_source_snapshot", fail_capture)
    with pytest.raises(OSError, match="during initialization"):
        campaign.create_campaign(root, source, raw, plan)
    with pytest.raises(state.IntegrityError, match="initialization was interrupted"):
        campaign.create_campaign(root, source, raw, plan)
    assert not any((root / "attempts").iterdir())
