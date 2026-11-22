from __future__ import annotations

from hashlib import sha256

import numpy as np
import pytest

from clustering_eval.experiments.plan_data import resolve_dataset


def test_dataset_identity_covers_content_order_and_preparation_not_location(tmp_path):
    X = np.arange(12).reshape(6, 2)
    y = np.array([0, 1, 0, 1, 0, 1])
    first = tmp_path / "original.npz"
    second = tmp_path / "relocated input.npz"
    np.savez(first, X=X, y=y)
    np.savez_compressed(second, X=X, y=y)
    def resolve(file, **extra):
        return resolve_dataset({"provider": "npz", "path": file.name, **extra}, base_dir=tmp_path, path="datasets.fixture")
    original = resolve(first, expected_shape=[6, 2], sha256=sha256(first.read_bytes()).hexdigest())
    copied = resolve(second)
    assert copied["dataset_id"] == original["dataset_id"]
    assert copied["file_sha256"] != original["file_sha256"]
    assert copied["x_sha256"] == sha256(X.tobytes()).hexdigest()
    assert copied["n_classes"] == 2
    assert resolve(second, preparation_seed=5)["dataset_id"] != copied["dataset_id"]
    np.savez(second, X=X[::-1], y=y[::-1])
    assert resolve(second)["dataset_id"] != original["dataset_id"]
    for field, value in (("expected_shape", [2, 6]), ("y_sha256", "a"*64), ("unexpected", False)):
        with pytest.raises(ValueError, match=field):
            resolve(first, **{field: value})


@pytest.mark.parametrize("arrays", [
    {"X": np.ones((4, 2)), "y": np.ones(3)},
    {"X": np.ones(5), "y": np.ones(5)},
    {"X": np.full((4, 2), np.nan), "y": np.ones(4)},
    {"X": np.ones((4, 2))},
    {"X": np.ones((4, 2)), "y": np.array([{}, {}, {}, {}], dtype=object)},
])
def test_invalid_npz_is_localized(tmp_path, arrays):
    np.savez(tmp_path/"bad.npz", **arrays)
    with pytest.raises(ValueError, match="datasets.bad"):
        resolve_dataset({"provider":"npz", "path":"bad.npz"}, base_dir=tmp_path, path="datasets.bad")


def test_registry_defaults_and_offline_policy(tmp_path, monkeypatch):
    def resolve(spec):
        return resolve_dataset({"provider":"registry", **spec}, base_dir=tmp_path, path="datasets.input")
    baseline = resolve({"name":"blobs"})
    assert resolve({"name":"blobs", "params":{"random_state":42}})["dataset_id"] == baseline["dataset_id"]
    assert resolve({"name":"blobs", "preparation_seed":43})["x_sha256"] != baseline["x_sha256"]
    iris = resolve({"name":"iris"})
    assert (iris["n_samples"], iris["n_features"]) == (150, 4)
    def no_network(*args, **kwargs):
        pytest.fail("unexpected download")
    monkeypatch.setattr("urllib.request.urlopen", no_network)
    for name in ("dry_bean", "mnist_10k", "mnist_full"):
        with pytest.raises(ValueError, match="params.path"):
            resolve({"name":name})
    with pytest.raises(ValueError, match="random_state"):
        resolve({"name":"blobs", "preparation_seed":6, "params":{"random_state":7}})
