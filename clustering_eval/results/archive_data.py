"""Transfer the immutable inputs that identify a campaign and its prepared comparisons."""
from __future__ import annotations

from contextlib import contextmanager
from hashlib import file_digest, sha256
import json
from pathlib import Path
import sqlite3
from typing import Iterator
import unicodedata

import numpy as np

from ..experiments.plan_io import read_document
from ..experiments.prepared import PreparedComparison
from ..experiments.prepared_store import read as read_prepared
from ..experiments.runner_campaign import descriptor_path
from ..experiments.runner_state import IntegrityError, checked_path, header, journal, raise_operational_read_error
from ..experiments.source_archive import (
    PATCH_NAME, RECORD_NAME, ZIP_NAME, portable_path, verify_source_snapshot,
)


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2) + "\n",
                    encoding="utf-8")


@contextmanager
def required_input(location: Path, stage: str) -> Iterator[None]:
    """Keep inaccessible saved bytes distinct from missing or inconsistent evidence."""
    try:
        yield
    except (OSError, ValueError, KeyError, TypeError, sqlite3.DatabaseError) as exc:
        raise_operational_read_error(exc, location, stage)
        if isinstance(exc, IntegrityError):
            raise
        raise IntegrityError(f"Invalid saved campaign artifact {location}: {exc}") from exc


def verified_bytes(path: Path, expected_sha256: str) -> bytes:
    """Bind the actual bytes transferred to the digest recorded at publication."""
    with required_input(path, "Reading saved file"):
        if path.is_dir():
            raise IntegrityError(f"Required a file, found a directory: {path}")
        data = path.read_bytes()
    if sha256(data).hexdigest() != expected_sha256:
        raise IntegrityError(f"Saved artifact checksum mismatch: {path}")
    return data


class DirectoryNames:
    """Allocate portable single components without case/normalization or reserved-name collisions."""

    def __init__(self, reserved: tuple[str, ...] = ()) -> None:
        self.used = {self.fold(name) for name in reserved}

    @staticmethod
    def fold(name: str) -> str:
        return unicodedata.normalize("NFC", name).casefold()

    def allocate(self, preferred: str, identity: str) -> str:
        try:
            # Leave room for the file extensions/suffixes used inside series.
            if "/" in preferred or len(preferred.encode("utf-8")) > 120:
                raise ValueError("oversized or nested component")
            component = portable_path(preferred)
        except ValueError:
            component = "item-" + sha256(identity.encode()).hexdigest()[:20]
        if self.fold(component) in self.used:
            component = "item-" + sha256(identity.encode()).hexdigest()[:20]
        while self.fold(component) in self.used:
            component += "_"
        self.used.add(self.fold(component))
        return component


def copy_reproduction(campaign: Path, output: Path, snapshot: dict) -> dict:
    """Copy immutable source and plan bytes verified against the RUNNER header."""
    with required_input(campaign / "state" / "journal.sqlite", "Reading campaign header"), journal(campaign, readonly=True) as db:
        meta = header(db)
    if (meta["source_id"] != snapshot["source_id"] or meta["runtime"] != snapshot["environment"]
            or meta["created"] != snapshot["summary"]["created_utc_epoch"]):
        raise IntegrityError("Campaign identity changed during export")
    original = meta["plan_file"]
    if original not in ("plan.yaml", "plan.json"):
        raise IntegrityError(f"Unexpected original plan filename: {original}")
    output.mkdir()
    for name, digest in ((original, meta["plan_sha256"]), ("resolved_plan.json", meta["resolved_sha256"])):
        value = verified_bytes(checked_path(campaign, "raw", name), digest)
        if name == "resolved_plan.json" and json.loads(value) != snapshot["plan"]:
            raise IntegrityError("Resolved plan differs from the observed snapshot")
        (output / name).write_bytes(value)

    source_record = verified_bytes(checked_path(campaign, "raw", "source", RECORD_NAME),
                                   meta["source_record_sha256"])
    (output / RECORD_NAME).write_bytes(source_record)
    record = json.loads(source_record)
    for name, key in ((ZIP_NAME, "snapshot_sha256"), (PATCH_NAME, "working_tree_patch_sha256")):
        data = verified_bytes(checked_path(campaign, "raw", "source", name), record[key])
        (output / name).write_bytes(data)
    with required_input(output, "Verifying copied source snapshot"):
        verify_source_snapshot(output, expected_source_id=snapshot["source_id"])
    write_json(output / "environment.json", meta["runtime"])
    return meta


def read_comparison(campaign: Path, plan: dict, comparison: dict, jobs: list[dict],
                    binding: dict) -> PreparedComparison:
    """Open existing bytes without requiring their original dataset path or creating a release."""
    cid = comparison["comparison_id"]
    descriptor = descriptor_path(campaign, cid)
    reservation = checked_path(campaign, "cache", cid + ".reservation")
    verified_bytes(descriptor, binding["descriptor_sha256"])
    verified_bytes(reservation, binding["reservation_sha256"])
    with required_input(descriptor.parent, "Reading saved prepared-comparison bundle"):
        prepared = read_prepared(descriptor, plan["source_id"], cid)
        # Recheck the seals after reading: the descriptor supplies the digest of all other files.
        verified_bytes(descriptor, binding["descriptor_sha256"])
        verified_bytes(reservation, binding["reservation_sha256"])
        if (prepared.comparison != comparison or prepared.jobs != jobs
                or prepared.fingerprints != binding["fingerprints"]
                or len(prepared.X_raw) != binding["n_samples"]
                or prepared.dataset["dataset_id"] != binding["dataset_id"]
                or prepared.privacy_report.get("release_id") != binding["input_release_id"]
                or comparison["protocol"]["privacy_mode"] != binding["privacy_mode"]):
            raise IntegrityError(f"Preparation differs from its journal binding: {descriptor}")
        return prepared


def write_dataset(root: Path, record: dict, prepared: PreparedComparison) -> None:
    """Check scientific content and preserve original array type, shape and row order."""
    expected = record["dataset"]
    x, y = prepared.X_raw, prepared.y
    if (prepared.dataset["dataset_id"] != expected["dataset_id"]
            or x.shape != (expected["n_samples"], expected["n_features"])
            or y is None or y.shape != (len(x),)):
        raise IntegrityError(f"Dataset identity or shape mismatch: {expected['dataset_id']}")
    for array, prefix in ((x, "x"), (y, "y")):
        digest = sha256(np.ascontiguousarray(array).view(np.uint8)).hexdigest()
        if digest != expected[prefix + "_sha256"] or array.dtype.str != expected[prefix + "_dtype"]:
            raise IntegrityError(f"Dataset {expected['dataset_id']}: {prefix} dtype or bytes differ")
    if not record["available"]:
        np.savez(root / record["path"] / "dataset.npz", X=x, y=y)
        record.update(available=True, reason=None)
    record["checked_comparisons"].append(prepared.comparison["comparison_id"])


def write_replay(root: Path, meta: dict, datasets: list[dict]) -> None:
    """Write a path-rebound input plan only when every required provider is portable."""
    reproduce = root / "reproduce"
    document = read_document(reproduce / meta["plan_file"])
    document["campaign"]["output_dir"] = "../../replayed-campaign"
    missing = []
    by_key = {key: entry for entry in datasets for key in entry["keys"]}
    for key, definition in document["datasets"].items():
        record = by_key[key]
        dataset = record["dataset"]
        if definition["provider"] == "npz" and record["available"]:
            relative = record["path"] + "/dataset.npz"
            definition["path"] = "../" + relative
            if "sha256" in definition:
                with (root / relative).open("rb") as stream:
                    definition["sha256"] = file_digest(stream, "sha256").hexdigest()
        elif definition["provider"] == "npz" or "input_path" in dataset:
            missing.append(key)
        definition.update(x_sha256=dataset["x_sha256"], y_sha256=dataset["y_sha256"])
    instruction = [
        "# Reproducing this campaign", "",
        "Use the Python version and package versions in environment.json. For inspecting an archive "
        "run `python -m clustering_eval.cli series verify <archive-directory>` with an EXPORT-capable installation.",
        "", "For a new run, create a clean separate Git working copy at the source_head in "
        "source_code_verification.json. From its root, if source_changes.patch is nonempty, "
        "run `git apply --check <archive>/reproduce/source_changes.patch` and then "
        "`git apply <archive>/reproduce/source_changes.patch` to restore changes, including "
        "deletions. Overlay the verified source_snapshot.zip members to restore exact working "
        "bytes, including original line endings. Verify checkout_source_id() from "
        "clustering_eval.experiments.series_plan against source_id before running the copied code.", "",
        f"Original input: {meta['plan_file']}. resolved_plan.json and the original input "
        "preserve historical paths as provenance. The archive manifest maps each dataset to its directory.",
    ]
    if not missing:
        write_json(reproduce / "portable_plan.json", document)
        instruction.extend(["", "Copy the archive to a writable location. From the restored working copy run "
                            "`python -m clustering_eval.cli series plan <archive>/reproduce/portable_plan.json` "
                            "and compare scientific job IDs with resolved_plan.json, then "
                            "`python -m clustering_eval.cli series run <archive>/reproduce/portable_plan.json` "
                            "to write into a new replayed-campaign directory beside the archive. "
                            "Use a fresh destination for each replay."])
    else:
        instruction.extend(["", "Supply the original local provider inputs for these plan keys: " +
                            ", ".join(missing) + ". For a registry provider with an external source, "
                            "restore its original raw provider file and set params.path in a copy of the "
                            "original plan. An exported X/y pair alone cannot reconstruct that file. "
                            "For an unprepared NPZ, supply and verify the original. Set NPZ paths and "
                            "campaign.output_dir explicitly, compare the resolved scientific IDs before running."])
    instruction.extend(["", "A new stochastic run draws new noise. Original worker outputs, private "
                        "training matrices and random OS draws have different reproduction requirements. "
                        "Use series verify to inspect saved results without rerunning the experiment."])
    (reproduce / "README.md").write_text("\n".join(instruction) + "\n", encoding="utf-8")
