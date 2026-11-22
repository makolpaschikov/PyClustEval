"""Public campaign commands, using bounded local and NumPy Iris jobs."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

from test_runner_state import plan_document

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="campaign process ownership requires Windows")

REPO = Path(__file__).resolve().parents[1]


def series(*args: str | Path, code: int, prefix: str | None = None) -> dict:
    argv = (["-c", prefix] if prefix else ["-m", "clustering_eval.cli"])
    result = subprocess.run([sys.executable, "-B", *argv, "series", *map(str, args), "--json"],
                            cwd=REPO, text=True, capture_output=True, timeout=150)
    assert result.returncode == code, (result.returncode, result.stdout, result.stderr)
    return json.loads(result.stdout) if result.stdout.strip() else {}


def write_plan(tmp_path: Path, doc: dict) -> Path:
    source = tmp_path / "input plan.json"
    source.write_text(json.dumps(doc), encoding="utf-8")
    return source


def test_cli_identity_and_idempotency(tmp_path):
    from clustering_eval.experiments.runner_reader import read_campaign

    root = tmp_path / "results with spaces"
    plan = plan_document(root)
    plan["scenarios"]["numpy"] = {"mode": "federated", "stopping_profile": "current_gui",
                                  "algorithms": ["fed_kmeans_numpy"], "rounds": 2, "num_clients": 3}
    plan["series"][0]["scenarios"].append("numpy")
    source = write_plan(tmp_path, plan)
    assert series("run", source, code=0)["totals"]["ok"] == 2
    first = read_campaign(root)
    assert first["format"] == "pyclusteval.campaign-reader.v1"
    pointers = [j["accepted"] for j in first["jobs"]]
    assert len({x["attempt_id"] for x in pointers}) == 2
    assert "resume" in series("run", source, code=3)["error"]
    assert series("resume", root, code=0)["attempts_started"] == 0
    assert series("retry", root, "--status", "error", code=0)["attempts_started"] == 0
    assert [j["accepted"] for j in read_campaign(root)["jobs"]] == pointers
    hit = pointers[0]
    stdout = root / hit["directory"] / "stdout.log"
    original = stdout.read_bytes()
    stdout.write_bytes(original + b"changed")
    invalid = series("status", root, code=4)
    assert "stdout/stderr" in invalid["integrity_errors"][0]
    stdout.write_bytes(original)
    labels = root / hit["directory"] / hit["candidate"]["labels"]["path"]
    labels.write_bytes(b"broken")
    assert series("status", root, code=4)["totals"]["ok"] == 1
    assert read_campaign(root)["jobs"][0]["accepted"] is None
    assert "failed verification" in series("resume", root, code=4)["error"]
    assert len(read_campaign(root)["jobs"][0]["attempts"]) == 1


def test_persisted_timeout_budget_manual_and_automatic_retries(tmp_path):
    from clustering_eval.experiments.runner_reader import read_campaign

    root = tmp_path / "timed"
    plan = plan_document(root)
    plan["execution"] = {"timeout_sec": 0.01, "max_retries": 1}
    source = write_plan(tmp_path, plan)
    timed = series("run", source, code=3)
    assert timed["totals"]["timeout"] == 1 and timed["attempts_started"] == 2
    assert series("resume", root, code=3)["attempts_started"] == 0
    assert series("retry", root, "--status", "error", code=3)["attempts_started"] == 0
    assert series("retry", root, "--status", "timeout", "--timeout-sec", "none", code=0)["totals"]["ok"] == 1
    record = read_campaign(root)
    job, = record["jobs"]
    assert [a["kind"] for a in job["attempts"]] == ["initial", "automatic", "manual"]
    assert [a["status"] for a in job["attempts"]] == ["timeout", "timeout", "ok"]
    assert len({a["request"]["input_release_id"] for a in job["attempts"]}) == 1
    assert record["sessions"][0]["limits"]["timeout_sec"] == 0.01
    assert record["sessions"][-1]["limits"]["timeout_sec"] is None


def test_total_deadline_survives_resume_and_explicit_extension(tmp_path):
    root = tmp_path / "deadline"
    plan = plan_document(root)
    plan["execution"] = {"total_time_sec": 0.001}
    source = write_plan(tmp_path, plan)
    assert series("run", source, code=3)["stop_reason"] == "total_time"
    assert series("resume", root, code=3)["attempts_started"] == 0
    assert series("resume", root, "--total-time-sec", "180", code=0)["totals"]["ok"] == 1


@pytest.mark.parametrize("policy,expected", [("stop", "pending"), ("continue", "ok")])
def test_unsupported_backend_in_mixed_campaign(tmp_path, policy, expected):
    from clustering_eval.experiments.runner_reader import read_campaign

    root = tmp_path / "mixed"
    plan = plan_document(root)
    plan["scenarios"]["flower"] = {"mode": "federated", "stopping_profile": "current_gui",
                                   "algorithms": ["fed_kmeans_flower"], "num_clients": 3}
    plan["series"][0]["scenarios"].insert(0, "flower")
    plan["execution"] = {"failure_policy": policy}
    source = write_plan(tmp_path, plan)
    totals = series("run", source, code=3)["totals"]
    assert totals["skipped"] == 1 and totals[expected] == 1
    assert not read_campaign(root)["jobs"][0]["attempts"]
    if policy == "stop":
        assert series("resume", root, code=3)["totals"]["ok"] == 1


def test_reject_unverified_profile_before_creating_campaign(tmp_path):
    root = tmp_path / "unverified"
    plan = plan_document(root)
    plan["execution"] = {"processes": 2}
    assert "processes=1" in series("run", write_plan(tmp_path, plan), code=2)["error"]
    assert not root.exists()
