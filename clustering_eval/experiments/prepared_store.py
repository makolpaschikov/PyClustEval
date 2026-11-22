"""Immutable, local prepared-comparison bundles for a trusted research directory."""
from __future__ import annotations

from hashlib import file_digest, sha256
import os
from pathlib import Path
from typing import BinaryIO
from uuid import uuid4

import numpy as np

from .archive_inputs import canonical, document
from .prepared import PreparedComparison, ProtectedPartition, build_inputs

FORMAT = "pyclusteval.prepared-comparison.v1"
DESCRIPTOR = "prepared.json"
METADATA = "metadata.json"


def _flush(stream: BinaryIO) -> None:
    stream.flush()
    os.fsync(stream.fileno())


def _write_bytes(path: Path, value: bytes) -> None:
    with path.open("xb") as output:
        output.write(value)
        _flush(output)


def _write_array(path: Path, array: np.ndarray) -> dict:
    with path.open("x+b") as stream:
        np.save(stream, array, allow_pickle=False)
        _flush(stream)
        stream.seek(0)
        digest = file_digest(stream, "sha256").hexdigest()
    return {"file": path.name, "sha256": digest, "dtype": array.dtype.str, "shape": list(array.shape)}


def publish(destination: Path, inputs: dict, source_id: str) -> Path:
    destination = destination.absolute()
    descriptor = destination / DESCRIPTOR
    comparison_id = inputs["comparison"]["comparison_id"]
    if descriptor.exists():
        existing = read(descriptor, source_id, comparison_id)
        if existing.jobs != inputs["jobs"] or existing.comparison != inputs["comparison"]:
            raise ValueError("Existing prepared comparison has different job or protocol records")
        return descriptor
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise ValueError(f"Destination already exists without a complete descriptor: {destination}")
    reservation = destination.with_name(destination.name + ".reservation")
    attempt = uuid4().hex
    try:
        _write_bytes(reservation, canonical(dict(format=FORMAT, attempt_id=attempt, source_id=source_id,
                         comparison_id=comparison_id, privacy_mode=inputs["comparison"]["protocol"]["privacy_mode"],
                         on_incomplete="release status unknown; do not regenerate")))
    except FileExistsError as exc:
        raise ValueError(f"Preparation already reserved; release status unknown: {reservation}") from exc

    # Claim before drawing noise. Failed publication deliberately retains the reservation.
    destination.mkdir(mode=0o700)
    prepared = build_inputs(**inputs)
    arrays = {}
    for key in ("X_raw", "X_train", "X_eval", "y"):
        value = getattr(prepared, key)
        if value is None:
            arrays[key] = None
        elif key == "X_train" and value is prepared.X_raw:
            arrays[key] = arrays["X_raw"]
        else:
            arrays[key] = _write_array(destination / f"{key}.npy", value)
    state = {key: getattr(prepared, key) for key in (
        "source_id", "dataset", "comparison", "jobs", "schedule", "active_data", "privacy_report",
        "fingerprints", "estimated_k", "k_tuning", "setup_sec")}
    partition = prepared.partition
    state["partition"] = None if partition is None else [row.tolist() for row in partition]
    metadata = canonical(dict(format=FORMAT, attempt_id=attempt, arrays=arrays, state=state))
    _write_bytes(destination / METADATA, metadata)
    final = canonical(dict(format=FORMAT, source_id=source_id, comparison_id=comparison_id,
                           metadata_sha256=sha256(metadata).hexdigest()))
    staging = destination / "publishing.json"
    _write_bytes(staging, final)
    staging.rename(descriptor)
    return descriptor


def _member(directory: Path, name: str) -> Path:
    path = directory / name
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Missing or linked prepared member {path}")
    return path


def _read_array(directory: Path, key: str, item: dict) -> np.ndarray:
    name = item["file"]
    if name != f"{key}.npy":
        raise ValueError(f"Unexpected {key} locator {name!r}")
    with _member(directory, name).open("rb") as stream:
        if file_digest(stream, "sha256").hexdigest() != item["sha256"]:
            raise ValueError(f"Prepared array {name}: checksum mismatch")
        stream.seek(0)
        array = np.load(stream, allow_pickle=False)
        if array.dtype.str != item["dtype"] or list(array.shape) != item["shape"]:
            raise ValueError(f"Prepared array {name}: dtype or shape mismatch")
    array.flags.writeable = False
    return array


def read(descriptor: Path, source_id: str, comparison_id: str | None) -> PreparedComparison:
    try:
        if descriptor.name != DESCRIPTOR:
            raise ValueError(f"Expected a {DESCRIPTOR} descriptor")
        directory = descriptor.parent
        header = document(_member(directory, DESCRIPTOR).read_bytes(), DESCRIPTOR)
        if header["format"] != FORMAT or header["source_id"] != source_id:
            raise ValueError("Prepared descriptor has incompatible format or source_id")
        if comparison_id is not None and header["comparison_id"] != comparison_id:
            raise ValueError("Prepared comparison_id mismatch")
        raw = _member(directory, METADATA).read_bytes()
        if sha256(raw).hexdigest() != header["metadata_sha256"]:
            raise ValueError("Prepared metadata checksum mismatch")
        metadata = document(raw, METADATA)
        reservation = directory.with_name(directory.name + ".reservation")
        if reservation.exists():
            claim = document(reservation.read_bytes(), reservation.name)
            if (claim["attempt_id"] != metadata["attempt_id"] or claim["source_id"] != header["source_id"]
                    or claim["comparison_id"] != header["comparison_id"]):
                raise ValueError("Prepared release does not match the reserved attempt")
        state, arrays = metadata["state"], metadata["arrays"]
        if (metadata["format"] != FORMAT or state["source_id"] != source_id or
                state["comparison"]["comparison_id"] != header["comparison_id"]):
            raise ValueError("Inconsistent prepared source, comparison or format")
        for key in ("X_raw", "X_train", "X_eval", "y"):
            item = arrays[key]
            if key == "y" and item is None:
                state[key] = None
            elif key == "X_train" and item == arrays["X_raw"]:
                state[key] = state["X_raw"]
            else:
                state[key] = _read_array(directory, key, item)
        if state["partition"] is not None:
            state["partition"] = ProtectedPartition(np.asarray(row, dtype=np.int64) for row in state["partition"])
        return PreparedComparison(**state)
    except (KeyError, TypeError, OSError, EOFError) as exc:
        raise ValueError(f"Incomplete or invalid prepared comparison {descriptor}: {exc}") from exc
