"""Real Windows measurements of a worker with a resident child allocation."""

import json
from pathlib import Path
import sys

import pytest

from clustering_eval.experiments.runner_process import campaign_lock, run_owned, worker_env


def test_legacy_core_evidence_and_optional_flower_transport():
    from copy import deepcopy
    from clustering_eval.application.flower_profile import FLOWER_TRANSPORT_PACKAGES
    from clustering_eval.experiments.runner_environment import IncompatibleEnvironment, check_environment
    from clustering_eval.experiments.runner_state import supervisor_runtime

    current = supervisor_runtime()
    old = deepcopy(current)
    for key in ("implementation", "python_version", "os", "architecture"):
        old.pop(key)
    # Capture the actual interpreter, including on platforms with legacy
    # banners lacking an explicit Windows build marker.
    if sys.platform != "win32":
        old.update(implementation=current["implementation"], architecture=current["architecture"])
    old["executable"] = "old-venv"
    old["packages"] = [(key, ("1" if key.lower() == "packaging" else val)) for key, val in old["packages"]
                       if key.lower() not in FLOWER_TRANSPORT_PACKAGES]
    history = {"environment": old, "sessions": [{"session_id": "s", "command": "run", "runtime": None}],
               "jobs": [{"job": {"backend": "flower-simulation"}, "accepted": None, "attempts": []}]}
    check_environment(history, current)
    history["jobs"][0]["attempts"].append({"attempt_id": "a", "session_id": "s",
                                          "details": {"tree_resources": {"total_processes": 0}}})
    check_environment(history, current)
    history["jobs"][0]["attempts"][0]["details"] = {}
    with pytest.raises(IncompatibleEnvironment, match="flwr unknown for previous attempt"):
        check_environment(history, current)


def test_mismatched_numerical_evidence_remains_visible_after_later_rejected_session():
    from copy import deepcopy
    from clustering_eval.experiments.runner_environment import IncompatibleEnvironment, check_environment
    from clustering_eval.experiments.runner_state import supervisor_runtime

    current = supervisor_runtime()
    previous = deepcopy(current)
    previous["packages"] = [(name, "0.0" if name.lower() == "numpy" else version)
                            for name, version in previous["packages"]]
    session = {"session_id": "older", "command": "retry", "runtime": previous}
    entry = {"job": {"backend": "local"}, "accepted": None, "attempts": []}
    snapshot = {"environment": current, "sessions": [session], "jobs": [entry]}
    check_environment(snapshot, current)
    entry["attempts"].append({"attempt_id": "old", "session_id": "older", "details": {}})
    with pytest.raises(IncompatibleEnvironment, match="numpy recorded=0.0"):
        check_environment(snapshot, current)


@pytest.mark.parametrize("command,previous,policy", [("retry", "error", "stop"), ("retry", "timeout", "continue"),
                                                     ("resume", "cancelled", "stop"), ("resume", "interrupted", "continue")])
def test_unavailable_retry_or_resume_preserves_the_previous_outcome(tmp_path, monkeypatch, command, previous, policy):
    from clustering_eval.application import flower_profile
    from clustering_eval.experiments import runner_queue, runner_state

    (tmp_path / "state").mkdir()
    jobs = [{"job_id": name, "comparison_id": "cmp"} for name in ("blocked", "supported")]
    runner_state.initialize(tmp_path, {"format": runner_state.FORMAT}, jobs)
    plan = {"comparisons": [{"comparison_id": "cmp", "protocol": {}}], "jobs": jobs}
    limits = {"failure_policy": policy, "total_time_sec": None, "max_retries": 0}
    monkeypatch.setattr(flower_profile, "runtime_rejection",
                        lambda job, _: "Missing verified Flower" if job["job_id"] == "blocked" else None)
    calls = []
    def execute(db, root, plan, job, binding, **options):
        calls.append(job["job_id"])
        return "ok", "checked"

    monkeypatch.setattr(runner_queue, "ensure_prepared", lambda *args: {})
    monkeypatch.setattr(runner_queue, "execute", execute)
    with runner_state.journal(tmp_path) as db:
        first = runner_state.start_session(db, "run", limits)
        for job in jobs:
            aid = job["job_id"] + "-1"
            runner_state.begin_attempt(db, {"attempt_id": aid, **job}, first, "initial")
            runner_state.finish_attempt(db, aid, previous, "Original failure or interruption")
        runner_state.stop_session(db, first, "ended")
        current = runner_state.start_session(db, command, limits)
        selected = previous if command == "retry" else None
        reason, processed = runner_queue.schedule(db, tmp_path, {"base_dir": str(tmp_path)}, plan,
                                                 current, limits, command, selected, None)
        assert "Missing verified Flower" in reason
        assert processed == int(policy == "continue")
        assert calls == (["supported"] if policy == "continue" else [])
        assert tuple(db.execute("SELECT status,reason FROM jobs WHERE job_id='blocked'").fetchone()) == (
            previous, "Original failure or interruption")
        assert db.execute("SELECT count(*) FROM attempts WHERE job_id='blocked'").fetchone()[0] == 1
        row = db.execute("SELECT record,sha FROM unavailable_jobs WHERE session_id=? AND job_id='blocked'",
                         (current,)).fetchone()
        assert runner_state.unseal(*row) == {"job_id": "blocked", "prior_status": previous,
                                             "reason": "Missing verified Flower"}


@pytest.mark.skipif(sys.platform != "win32", reason="Windows Job Object accounting")
@pytest.mark.parametrize("outcome", ["success", "failure", "timeout"])
def test_measures_complete_tree_before_releasing_attempt(tmp_path, outcome):
    child = """
import time
resident = bytearray(32 * 1024**2)
resident[::4096] = b"x" * (len(resident) // 4096)
print("ready", flush=True)
time.sleep(30)
"""
    worker = """
import json, subprocess, sys, time
resident = bytearray(24 * 1024**2)
resident[::4096] = b"x" * (len(resident) // 4096)
child = subprocess.Popen([sys.executable, "-c", sys.argv[1]], stdout=subprocess.PIPE)
assert child.stdout.readline().strip() == b"ready"
print(json.dumps({"child": child.pid}), flush=True)
time.sleep(30 if sys.argv[2] == "timeout" else .8)
sys.exit(1 if sys.argv[2] == "failure" else 0)
"""
    with campaign_lock(tmp_path):
        result = run_owned([sys.executable, "-c", worker, child, outcome], cwd=Path.cwd(),
                           env=worker_env(1), stdout_path=tmp_path / "out",
                           stderr_path=tmp_path / "err", timeout_sec=4, deadline_utc=None,
                           memory_limit_mb=192)
    assert json.loads((tmp_path / "out").read_text())["child"] > 0
    expected = {"success": ("exited", 0), "failure": ("exited", 1), "timeout": ("timeout", None)}
    assert (result.reason, result.returncode) == expected[outcome]
    tree = result.tree_resources
    assert tree["total_processes"] >= 2
    assert tree["active_processes_after_cleanup"] == 0
    assert tree["memory_limit_bytes"] == 192 * 1024**2
    assert tree["peak_commit_bytes"] >= 56 * 1024**2
    assert tree["max_sampled_working_set_bytes"] >= 56 * 1024**2
    assert tree["working_set_samples"] > 0
