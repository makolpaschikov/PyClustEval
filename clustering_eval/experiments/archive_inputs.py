"""Verified inputs for the paper's three-dataset, three-seed archive."""
from __future__ import annotations

from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
from typing import Any

import numpy as np

from ..datasets.partitioning import partition_class_counts, partition_fingerprint
from .source_archive import portable_path

PROFILE = "pyclusteval.three-datasets-three-seeds.v1"
# Digest of the scientific input catalog described in docs/IMPORT_CAMPAIGN_ARCHIVE.md.
INPUTS_SHA256 = "94bb66113d5d6812b86de55c038f47e6adc1b294cf1514c5c5c2e71be2690dda"
REPRODUCE = (
    "prepare.py", "worker.py", "run_persistent.py", "export_results.py",
    "source_snapshot.zip", "source_changes.patch", "source_code_verification.json",
    "environment.json", "drybean_source.json",
)
SERIES_INPUTS = ("protocol.json", "experiment_plan.json", "partitions.json", "report.json")
AUXILIARY = {
    "dry_bean": (),
    "mnist_10k": ("selected_corpus_indices.npy", "source_manifest.json"),
    "synthetic_anisotropic": ("generator_parameters.npz", "difficulty_check.json"),
}


def require(condition: bool, location: str, message: str) -> None:
    if not condition:
        raise ValueError(f"{location}: {message}")


def document(raw: bytes, location: str) -> Any:
    def unique(pairs: list[tuple[str, Any]]) -> dict:
        result = {}
        for key, value in pairs:
            require(key not in result, location, f"duplicate key {key!r}")
            result[key] = value
        return result

    def invalid(token: str) -> None:
        raise ValueError(f"{location}: invalid number {token}")

    try:
        return json.loads(raw.decode("utf-8-sig"), object_pairs_hook=unique, parse_constant=invalid)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{location}: {exc}") from exc


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode()


class ArchiveInputs:
    """Read only files used to reconstruct the recognized historical scientific profile."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        catalog = document(self._bytes("checksums.json"), "checksums.json")
        require(isinstance(catalog, dict) and catalog.get("algorithm") == "sha256"
                and isinstance(catalog.get("files"), list), "checksums.json", "expected SHA-256 catalog")
        self.entries = {}
        for item in catalog["files"]:
            require(isinstance(item, dict) and isinstance(item.get("path"), str)
                    and isinstance(item.get("sha256"), str) and type(item.get("bytes")) is int,
                    "checksums.json", "malformed file entry")
            name = item["path"]
            require(name not in self.entries, "checksums.json", f"duplicate {name!r}")
            self.entries[name] = item
        self.manifest = self.json("manifest.json")
        require(isinstance(self.manifest, dict) and self.manifest.get("format") == PROFILE,
                "manifest.json.format", f"expected {PROFILE}")
        rows = self.manifest.get("series")
        require(isinstance(rows, list) and len(rows) == self.manifest.get("series_count") == 9,
                "manifest.json.series", "expected nine declared series")
        names = {"manifest.json", *("reproduce/" + name for name in REPRODUCE)}
        for row in rows:
            require(isinstance(row, dict) and isinstance(row.get("path"), str)
                    and isinstance(row.get("dataset"), str) and row["dataset"] in AUXILIARY, "manifest.json.series", "unknown dataset or path")
            folder, dataset = portable_path(row["path"]), row["dataset"]
            names.update(f"{folder}/{name}" for name in SERIES_INPUTS)
            names.update(f"datasets/{dataset}/{name}" for name in
                         ("dataset.npz", "verification.json", *AUXILIARY[dataset]))
        hasher = sha256()
        for name in sorted(names):
            digest = self.checksum(name)
            hasher.update(f"{name}\0{digest}\n".encode())
        require(hasher.hexdigest() == INPUTS_SHA256, "historical.inputs_sha256",
                "scientific file catalog differs from the supported paper archive")

    def _bytes(self, name: str) -> bytes:
        path = self.root / portable_path(name)
        require(path.resolve().is_relative_to(self.root), name, "path escapes archive")
        try:
            return path.read_bytes()
        except OSError as exc:
            raise ValueError(f"{name}: {exc}") from exc

    def checksum(self, name: str) -> str:
        require(name in self.entries, "checksums.json", f"missing {name}")
        return self.entries[name]["sha256"]

    def read(self, name: str) -> bytes:
        expected = self.checksum(name)
        raw = self._bytes(name)
        require(len(raw) == self.entries[name]["bytes"] and sha256(raw).hexdigest() == expected,
                name, "size or SHA-256 mismatch")
        return raw

    def json(self, name: str) -> Any:
        return document(self.read(name), name)


def dataset_inputs(archive: ArchiveInputs, name: str) -> tuple[dict, dict, np.ndarray]:
    """Verify packed X/y in row order. Keep only labels for checking client indices."""
    directory = f"datasets/{name}"
    path = f"{directory}/dataset.npz"
    metadata = archive.json(f"{directory}/verification.json")
    with np.load(BytesIO(archive.read(path)), allow_pickle=False) as bundle:
        require(sorted(bundle.files) == ["X", "y"], path, "expected X and y")
        X, y = bundle["X"], bundle["y"]
    require(X.dtype == np.dtype("<f8") and y.dtype == np.dtype("<i8")
            and list(X.shape) == metadata["shape"] and X.ndim == 2 and y.shape == (len(X),),
            path, "unexpected dimensions or dtypes")
    hashes = {key: sha256(memoryview(np.ascontiguousarray(arr)).cast("B")).hexdigest()
              for key, arr in (("x_sha256", X), ("y_sha256", y))}
    require(all(hashes[key] == metadata[key] for key in hashes), path, "X/y row-order hash mismatch")
    require(metadata["dataset_name"] == name and np.isfinite(X).all()
            and np.bincount(y).tolist() == metadata["class_counts"]
            and len(np.unique(y)) == metadata["n_classes"], path, "dataset facts disagree with verification")
    params = metadata["metadata"]
    seed = {"mnist_10k": params.get("fixed_subset_seed"),
            "synthetic_anisotropic": params.get("generator_seed")}.get(name)
    auxiliary = {}
    for file in AUXILIARY[name]:
        ref = f"{directory}/{file}"
        raw = archive.read(ref)
        auxiliary[file] = archive.checksum(ref)
        if file == "selected_corpus_indices.npy":
            indices = np.load(BytesIO(raw), allow_pickle=False)
            require(indices.shape == y.shape and np.issubdtype(indices.dtype, np.integer)
                    and len(np.unique(indices)) == len(y) and indices.min() >= 0
                    and indices.max() < params["n_total_samples"], ref, "invalid subset membership")
    record = dict(name=name, provider="npz", path=path, n_samples=len(y), n_features=X.shape[1],
                  n_classes=metadata["n_classes"], preparation_seed=seed, **hashes,
                  x_dtype=str(X.dtype), y_dtype=str(y.dtype), file_sha256=archive.checksum(path),
                  verification=f"{directory}/verification.json", auxiliary_sha256=auxiliary,
                  dp_public_preprocessing_ref=f"{directory}/verification.json#dp_public_preprocessing")
    return record, metadata, y


def partitions_inputs(parts: dict, y: np.ndarray, protocol: dict, path: str) -> dict:
    """Bind every stored partition to the actual label vector and original client order."""
    result = {}
    for alias, part in parts.items():
        loc = f"{path}.{alias}"
        clients = part["indices"]
        require(isinstance(clients, list) and len(clients) == protocol["num_clients"]
                and all(isinstance(v, list) and len(v) >= 3 for v in clients),
                loc, "wrong client count or minimum size")
        arrays = [np.asarray(v) for v in clients]
        require(all(v.ndim == 1 and np.issubdtype(v.dtype, np.integer) for v in arrays),
                loc, "expected integer client indices")
        require(np.array_equal(np.sort(np.concatenate(arrays)), np.arange(len(y))),
                loc, "indices must be a disjoint cover of the dataset")
        require(part["sizes"] == [len(v) for v in arrays]
                and part["class_counts"] == partition_class_counts(arrays, y)
                and part["fingerprint"] == partition_fingerprint(arrays),
                loc, "partition fingerprint, sizes or class counts mismatch")
        result[alias] = dict(mode=part["mode"], alpha=part["alpha"], fingerprint=part["fingerprint"],
                             indices_sha256=sha256(canonical(clients)).hexdigest(),
                             sizes=part["sizes"], class_counts=part["class_counts"])
    return result
