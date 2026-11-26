"""Preparation must never silently draw a replacement shared Gaussian input."""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import shutil
import subprocess
import sys

import numpy as np
import pytest

from clustering_eval.experiments import prepared
from clustering_eval.experiments.series_plan import checkout_source_id, resolve_document


@pytest.fixture(scope="module")
def source():
    return checkout_source_id()


def plan_for(tmp_path: Path, source: str) -> dict:
    doc = dict(format="pyclusteval.plan.v1", campaign={"name": "release"},
               datasets={"d": dict(provider="registry", name="iris")},
               scenarios={"s": dict(mode="federated", stopping_profile="current_gui",
                                    algorithms=["fed_kmeans_numpy", "fed_fuzzy_cmeans_numpy"],
                                    privacy_mode="gaussian_dp", rounds=2, num_clients=3)},
               series=[dict(name="a", dataset="d", scenarios=["s"], seed=17)])
    return resolve_document(doc, base_dir=tmp_path, source_id=source)


def test_shared_release_survives_reopen_in_a_new_process_and_relocation(tmp_path, source, monkeypatch):
    plan = plan_for(tmp_path, source)
    cmp = plan["comparisons"][0]["comparison_id"]
    descriptor = prepared.prepare(plan, cmp, tmp_path / "state", source_id=source, base_dir=tmp_path)
    first = prepared.reopen(descriptor, source_id=source, comparison_id=cmp)
    assert len(first.jobs) == 2
    assert first.privacy_report["release_status"] == "released"
    assert first.privacy_report["release_fingerprint"] == first.fingerprints["train"]
    assert not np.array_equal(first.X_train, first.X_raw)

    def forbidden(*args, **kwargs):
        raise AssertionError("Unexpected second privacy draw")
    monkeypatch.setattr(prepared, "apply_gaussian_input_dp", forbidden)
    assert prepared.prepare(plan, cmp, descriptor.parent, source_id=source, base_dir=tmp_path) == descriptor
    moved = tmp_path / "moved"
    shutil.copytree(descriptor.parent, moved)
    code = """
from hashlib import sha256
import json, sys
from pathlib import Path
from clustering_eval.experiments.prepared import reopen
state = reopen(Path(sys.argv[1]), source_id=sys.argv[2], comparison_id=sys.argv[3])
print(json.dumps([state.privacy_report['release_id'],sha256(state.X_train.tobytes()).hexdigest(),
                  state.fingerprints,[c.tolist() for c in state.partition],state.schedule]))
"""
    result = subprocess.run([sys.executable, "-B", "-c", code, str(moved/descriptor.name), source, cmp],
                            check=True, capture_output=True, text=True)
    assert json.loads(result.stdout) == [first.privacy_report["release_id"],
        sha256(first.X_train.tobytes()).hexdigest(), first.fingerprints, [c.tolist() for c in first.partition],
        first.schedule]
    with pytest.raises(ValueError, match="source_id"):
        prepared.reopen(descriptor, source_id="b"*64)
    with pytest.raises(ValueError, match="comparison_id"):
        prepared.reopen(descriptor, source_id=source, comparison_id="b"*64)

    reservation = descriptor.parent.with_name(descriptor.parent.name + ".reservation")
    claim = json.loads(reservation.read_bytes())
    reservation.write_text(json.dumps(dict(claim, attempt_id="different-attempt")), encoding="utf-8")
    with pytest.raises(ValueError, match="reserved attempt"):
        prepared.reopen(descriptor, source_id=source)
    reservation.write_text(json.dumps(claim), encoding="utf-8")
    (descriptor.parent / "X_train.npy").rename(descriptor.parent / "renamed.npy")
    with pytest.raises(ValueError, match="X_train.npy"):
        prepared.prepare(plan, cmp, descriptor.parent, source_id=source, base_dir=tmp_path)
    (moved / "X_eval.npy").write_bytes(b"altered")
    with pytest.raises(ValueError, match="checksum"):
        prepared.reopen(moved/descriptor.name, source_id=source)


def test_incomplete_publication_and_lost_bundle_refuse_another_draw(tmp_path, source, monkeypatch):
    plan = plan_for(tmp_path, source)
    cmp = plan["comparisons"][0]["comparison_id"]
    attempts = []
    def interrupt(*args, **kwargs):
        attempts.append(1)
        raise RuntimeError("injected interruption at release boundary")
    monkeypatch.setattr(prepared, "apply_gaussian_input_dp", interrupt)
    target = tmp_path / "incomplete"
    with pytest.raises(RuntimeError, match="interruption"):
        prepared.prepare(plan, cmp, target, source_id=source, base_dir=tmp_path)
    with pytest.raises(ValueError, match="complete descriptor"):
        prepared.prepare(plan, cmp, target, source_id=source, base_dir=tmp_path)
    target.rmdir()
    with pytest.raises(ValueError, match="unknown"):
        prepared.prepare(plan, cmp, target, source_id=source, base_dir=tmp_path)
    assert attempts == [1]
