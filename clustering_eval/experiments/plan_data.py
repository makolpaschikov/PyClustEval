"""Resolve built-in datasets and prepared NPZ files without starting a download."""
from __future__ import annotations

from hashlib import file_digest, sha256
import json
from pathlib import Path
import re
from typing import Any
from zipfile import BadZipFile, ZipFile

import numpy as np

from ..datasets.registry import default_registry
from .plan_parameters import choice, integer, mapping, number


def _location(value: Any, base_dir: Path, field: str) -> Path:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise ValueError(f"{field}: expected a local filesystem path")
    return (base_dir / value).resolve()


def _expected_hash(spec: dict, key: str, actual: str, path: str) -> None:
    if key in spec:
        value = spec[key]
        if not isinstance(value, str) or not re.fullmatch("[a-fA-F0-9]{64}", value):
            raise ValueError(f"{path}.{key}: expected a SHA-256 digest")
        if value.lower() != actual:
            raise ValueError(f"{path}.{key}: checksum mismatch")


def _registry_input(spec: dict, base_dir: Path, path: str) -> tuple[np.ndarray, np.ndarray, dict, dict, int | None]:
    name = choice(spec.get("name"), {"iris", "wine", "digits", "blobs", "dry_bean", "mnist_10k", "mnist_full"}, f"{path}.name")
    keys = {
        "blobs": {"n_samples", "centers", "cluster_std", "random_state"},
        "dry_bean": {"path"},
        "mnist_10k": {"path", "subset_size", "random_state"},
        "mnist_full": {"path"},
    }
    given = mapping(spec.get("params", {}), f"{path}.params", keys=keys.get(name, set()))
    options: dict = {}
    seed = None
    if name in {"blobs", "mnist_10k"}:
        seed = integer(spec.get("preparation_seed", given.get("random_state", 42)), f"{path}.preparation_seed", 0, 2**32-1)
        if "random_state" in given:
            other = integer(given["random_state"], f"{path}.params.random_state", 0, 2**32-1)
            if seed != other:
                raise ValueError(f"{path}.params.random_state: conflicts with preparation_seed")
        options["random_state"] = seed
    elif "preparation_seed" in spec:
        raise ValueError(f"{path}.preparation_seed: {name} has no random preparation step")
    if name == "blobs":
        options["n_samples"] = integer(given.get("n_samples", 500), f"{path}.params.n_samples", 3)
        options["centers"] = integer(given.get("centers", 3), f"{path}.params.centers", 1, options["n_samples"])
        options["cluster_std"] = number(given.get("cluster_std", 1.), f"{path}.params.cluster_std")
        if options["cluster_std"] < 0:
            raise ValueError(f"{path}.params.cluster_std: expected >= 0")
    if name == "mnist_10k":
        options["subset_size"] = integer(given.get("subset_size", 10_000), f"{path}.params.subset_size")
    # An explicit path is the existing loaders' offline entry point. Missing
    # files must not fall through to the downloader or mutate the user's cache.
    origin = {}
    if name in {"mnist_10k", "mnist_full", "dry_bean"}:
        location = _location(given.get("path"), base_dir, f"{path}.params.path")
        options["path"] = str(location)
        origin["input_path"] = str(location)
    ds = default_registry().load(name, options)
    scientific_options = {k: v for k, v in options.items() if k != "path"}
    return ds.X, ds.y, scientific_options, origin, seed


def _npz_input(location: Path, path: str) -> tuple[np.ndarray, np.ndarray, str]:
    # Use one file handle so hashes and the parsed arrays refer to the same file.
    with location.open("rb") as stream:
        file_hash = file_digest(stream, "sha256").hexdigest()
        stream.seek(0)
        with ZipFile(stream) as zipped:
            members = zipped.namelist()
            if len(set(members)) != len(members) or not {"X.npy", "y.npy"} <= set(members):
                raise ValueError(f"{path}: NPZ requires unambiguous X and y arrays")
        stream.seek(0)
        with np.load(stream, allow_pickle=False) as arrays:
            return arrays["X"], arrays["y"], file_hash


def resolve_dataset(spec: dict, *, base_dir: Path, path: str) -> dict:
    """Read a fixed input, verify optional expected evidence and identify scientific content.

    Array hashes cover contiguous C-order bytes. The dataset identity also binds
    dtype, shape, preparation and provider; it is independent of path and ZIP packaging.
    """
    spec = mapping(spec, path)
    provider = choice(spec.get("provider"), {"registry", "npz"}, f"{path}.provider")
    common = {"provider", "name", "expected_shape", "x_sha256", "y_sha256", "preparation_seed"}
    mapping(spec, path, keys=common | ({"params"} if provider == "registry" else {"sha256", "path"}))
    name = spec.get("name", "npz")
    if not isinstance(name, str) or not name.strip():
        raise ValueError(f"{path}.name: expected a nonempty name")
    try:
        if provider == "registry":
            X, y, params, origin, seed = _registry_input(spec, base_dir, path)
        else:
            seed = integer(spec["preparation_seed"], f"{path}.preparation_seed", 0, 2**32-1) if "preparation_seed" in spec else None
            input_file = _location(spec.get("path"), base_dir, f"{path}.path")
            X, y, file_hash = _npz_input(input_file, f"{path}.path")
            _expected_hash(spec, "sha256", file_hash, path)
            origin = {"input_path": str(input_file), "file_sha256": file_hash}
            params = {}
    except (ValueError, OSError, BadZipFile, EOFError, RuntimeError) as exc:
        raise ValueError(f"{path}: {exc}") from exc
    if X.ndim != 2 or X.shape[0] < 3 or X.shape[1] < 1 or X.dtype.kind not in "buif" or not np.isfinite(X).all():
        raise ValueError(f"{path}.X: expected a finite numeric matrix with >=3 rows and >=1 feature")
    if y.ndim != 1 or len(y) != len(X) or y.dtype.kind not in "buifSU":
        raise ValueError(f"{path}.y: expected one label per data row")
    if y.dtype.kind == "f" and not np.isfinite(y).all():
        raise ValueError(f"{path}.y: nonfinite labels")
    if "expected_shape" in spec:
        shape = spec["expected_shape"]
        if type(shape) is not list or len(shape) != 2 or any(type(v) is not int for v in shape) or tuple(shape) != X.shape:
            raise ValueError(f"{path}.expected_shape: expected actual shape {list(X.shape)}")
    x_hash = sha256(np.ascontiguousarray(X).view(np.uint8)).hexdigest()
    y_hash = sha256(np.ascontiguousarray(y).view(np.uint8)).hexdigest()
    _expected_hash(spec, "x_sha256", x_hash, path)
    _expected_hash(spec, "y_sha256", y_hash, path)
    scientific = {"provider": provider, "name": name, "params": params, "preparation_seed": seed,
                  "n_samples": len(X), "n_features": X.shape[1], "n_classes": len(np.unique(y)),
                  "x_sha256": x_hash, "y_sha256": y_hash, "x_dtype": X.dtype.str, "y_dtype": y.dtype.str}
    canonical = json.dumps(["pyclusteval.dataset.v1", scientific], sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return {**scientific, "dataset_id": sha256(canonical.encode("utf-8")).hexdigest(), **origin}
