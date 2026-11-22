"""Crash after worker publication and verify the durable recovery boundary through the CLI."""
from __future__ import annotations

import subprocess
import sys
import time

import pytest

from test_runner_cli import REPO, series, write_plan
from test_runner_state import plan_document


@pytest.mark.skipif(sys.platform != "win32", reason="campaign process ownership requires Windows")
def test_supervisor_death_after_publication_accepts_candidate_exactly_once(tmp_path):
    from clustering_eval.experiments.runner_reader import read_campaign

    root = tmp_path / "recovery"
    marker = tmp_path / "worker returned"
    source = write_plan(tmp_path, plan_document(root))
    # Pause only the test's supervisor between actual worker exit and its journal commit.
    hold = (
        "import sys,time; from pathlib import Path; from clustering_eval.experiments import runner_queue;"
        "from clustering_eval.cli import main; "
        f"runner_queue.accept=lambda *args: (Path({str(marker)!r}).touch(), time.sleep(120)); main()"
    )
    supervisor = subprocess.Popen([sys.executable, "-B", "-c", hold, "series", "run", str(source), "--json"],
                                  cwd=REPO, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        deadline = time.monotonic() + 80
        while not marker.exists() and supervisor.poll() is None and time.monotonic() < deadline:
            time.sleep(0.1)
        if not marker.exists() and supervisor.poll() is not None:
            pytest.fail(str(supervisor.communicate()))
        assert marker.exists()
        live = series("status", root, code=0)
        assert live["current"][0]["supervisor_active"]
        original = live["current"][0]["attempt_id"]
        assert "error" in series("resume", root, code=3)
    finally:
        supervisor.kill()
        supervisor.communicate(timeout=15)
    stale = series("status", root, code=0)
    assert stale["totals"]["running"] == 1
    assert not stale["current"][0]["supervisor_active"]
    report = series("resume", root, code=0)
    assert report["totals"]["ok"] == 1 and report["attempts_started"] == 0
    job, = read_campaign(root)["jobs"]
    assert job["accepted"]["attempt_id"] == original
    assert len(job["attempts"]) == 1 and job["attempts"][0]["details"]["recovered"]


@pytest.mark.skipif(sys.platform != "win32", reason="campaign process ownership requires Windows")
def test_shared_gaussian_release_survives_failed_attempt_and_reopen(tmp_path):
    from clustering_eval.experiments.runner_reader import read_campaign

    root = tmp_path / "dp restart"
    plan = plan_document(root)
    plan["scenarios"]["test"] = {"algorithms": ["fed_kmeans_numpy", "fed_fuzzy_cmeans_numpy"],
                                 "mode": "federated", "privacy_mode": "gaussian_dp",
                                 "stopping_profile": "current_gui", "num_clients": 3, "rounds": 2}
    plan["execution"] = {"timeout_sec": 0.01, "failure_policy": "stop"}
    source = write_plan(tmp_path, plan)
    assert series("run", source, code=3)["totals"]["timeout"] == 1
    assert series("retry", root, "--status", "timeout", "--timeout-sec", "none", code=3)["totals"]["ok"] == 1
    assert series("resume", root, code=0)["totals"]["ok"] == 2
    snapshot = read_campaign(root)
    attempts = [a for job in snapshot["jobs"] for a in job["attempts"]]
    assert len(attempts) == 3
    assert len({a["request"]["fingerprints"]["train"] for a in attempts}) == 1
    release_ids = {a["request"]["input_release_id"] for a in attempts}
    assert len(release_ids) == 1 and None not in release_ids
    binding, = snapshot["preparations"].values()
    assert binding["input_release_id"] in release_ids


@pytest.mark.skipif(sys.platform != "win32", reason="campaign process ownership requires Windows")
def test_crash_after_input_dp_draw_never_regenerates_release(tmp_path):
    from clustering_eval.experiments.runner_reader import read_campaign

    root = tmp_path / "aborted release"
    draws = tmp_path / "observed draws.txt"
    plan = plan_document(root)
    plan["scenarios"]["test"] = {"algorithms": ["fed_kmeans_numpy"], "mode": "federated",
                                 "privacy_mode": "gaussian_dp", "stopping_profile": "current_gui",
                                 "num_clients": 3, "rounds": 2}
    source = write_plan(tmp_path, plan)
    # The test supervisor dies after a real draw and before its descriptor can be published.
    crash = f"""
import hashlib, os
from pathlib import Path
from clustering_eval.experiments import prepared
from clustering_eval.cli import main
draw = prepared.apply_gaussian_input_dp
def draw_then_exit(*args, **kwargs):
    matrix, _ = draw(*args, **kwargs)
    with Path({str(draws)!r}).open('a', encoding='ascii') as log:
        log.write(hashlib.sha256(matrix.tobytes()).hexdigest() + chr(10))
    os._exit(47)
prepared.apply_gaussian_input_dp = draw_then_exit
main()
"""
    series("run", source, code=47, prefix=crash)
    assert len(draws.read_text(encoding="ascii").splitlines()) == 1
    initial = read_campaign(root)
    job, = initial["jobs"]
    cid = job["job"]["comparison_id"]
    reservation = root / "cache" / (cid + ".reservation")
    before = reservation.read_bytes()
    assert initial["preparation_status"][cid] == "release_outcome_unknown"
    assert job["attempts"] == [] and not (root / "cache" / cid / "prepared.json").exists()

    refusal = series("resume", root, code=4, prefix=crash)
    assert "release may be unknown" in refusal["error"]
    after = read_campaign(root)
    assert after["summary"]["stop_reason"] == refusal["error"]
    assert after["preparations"][cid] is None and after["jobs"][0]["attempts"] == []
    assert len(draws.read_text(encoding="ascii").splitlines()) == 1
    assert reservation.read_bytes() == before


@pytest.mark.parametrize("partial", [False, True])
@pytest.mark.skipif(sys.platform != "win32", reason="campaign process ownership requires Windows")
def test_resume_rebuilds_unpublished_non_dp_preparation_after_disk_failure(tmp_path, partial):
    from clustering_eval.experiments.runner_reader import read_campaign

    root = tmp_path / "retry preparation"
    source = write_plan(tmp_path, plan_document(root))
    point = "prepared_store._write_array" if partial else "runner_campaign.prepare"
    fail = f"""
import errno
from clustering_eval.experiments import prepared_store, runner_campaign
from clustering_eval.cli import main
def no_room(*args, **kwargs):
    raise OSError(errno.ENOSPC, 'injected before preparation publication')
{point} = no_room
main()
"""
    assert "injected" in series("run", source, code=3, prefix=fail)["error"]
    interrupted = read_campaign(root)
    cid = interrupted["jobs"][0]["job"]["comparison_id"]
    assert interrupted["preparations"][cid] is None and not interrupted["jobs"][0]["attempts"]
    assert interrupted["preparation_status"][cid] == "preparation_incomplete"
    reservation = root / "cache" / (cid + ".reservation")
    earlier = reservation.read_bytes() if partial else None

    assert series("resume", root, code=0)["totals"]["ok"] == 1
    job, = read_campaign(root)["jobs"]
    assert len(job["attempts"]) == 1 and job["accepted"] is not None
    preserved = list((root / "cache").glob(cid + ".incomplete-*"))
    if partial:
        assert len(preserved) == 1 and (preserved[0] / "reservation").read_bytes() == earlier
        assert (preserved[0] / "bundle").is_dir()
    else:
        assert preserved == []
