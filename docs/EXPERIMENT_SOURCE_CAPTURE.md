# Campaign source snapshots

A campaign can identify the working source tree before starting a worker. The capture uses Git and the Python standard library. Verification of a saved bundle needs only Python.

```python
from pathlib import Path
from clustering_eval.experiments.source_capture import capture_source_snapshot
from clustering_eval.experiments.source_archive import verify_source_snapshot

bundle = capture_source_snapshot(Path.cwd(), Path("campaign/state/source"))
saved_id = bundle.source_id
checked = verify_source_snapshot(bundle.directory, expected_source_id=saved_id)
```

Pass the actual PyClustEval checkout root and a dedicated destination. The returned `SourceSnapshot` exposes `source_id`, `source_head`, `directory`, `archive`, `patch`, and `verification`. Export those three files to the campaign's `reproduce/` directory alongside the independently saved plan and environment.

## Captured files

The snapshot includes `pyproject.toml`, `pyclusteval_ui.py`, all Python sources under `clustering_eval/` (including vendored modules, GUI/CLI dependencies and newly created or ignored importable modules), and the literal resources named by setuptools `package-data` for this package. Dot directories, `__pycache__`, `build`, `dist`, and `venv` are excluded. An unsupported resource declaration, a linked source, or a missing required file stops capture. Deleted files still in the Git index must be restored or their deletion staged before capture. A staged removal of an optional Python module is recorded in the patch.

Pass additional Python reproduction scripts actually used by the campaign via `reproduction_scripts=("tools/replay.py",)` with existing checkout-relative paths under `tools/` or `reproduce/`. Files elsewhere, including unrelated checkout edits, local configuration, datasets and campaign outputs, are outside this source inventory. Selected code and declared resources are stored byte-for-byte.

## Identity and verification

- `source_snapshot.zip` stores the actual file bytes under UTF-8-compatible relative paths. Each file has its own SHA-256.
- `source_changes.patch` is a binary-capable Git diff between the recorded HEAD and the scoped working source, including untracked source additions. It uses a disposable index and object store. Git's checkout conversions may affect patch text. The ZIP preserves the exact bytes used.
- `source_code_verification.json` identifies format `pyclusteval.source-snapshot.v1`, source HEAD, file inventory, content ID, ZIP and patch hashes, and capture checks. The content ID is SHA-256 of UTF-8 JSON `[format, sorted([[path, sha256], ...])]` with unescaped Unicode and separators `,` and `:` without extra whitespace. File paths sort by Unicode code point. The ID excludes timestamps, checkout paths, Git HEAD, operating system and dependency versions.

Capture reads the source inventory twice and checks that HEAD and the bytes agree before publication. It writes and verifies all three files in a staging directory on the destination volume, then renames the complete directory into place. Treat the destination as immutable. A repeat verifies the existing bundle and returns it only if content, HEAD and scoped patch match. Choose a new destination for changed source. A failed attempt leaves an earlier valid bundle in place.

`verify_source_snapshot` reads the saved record, ZIP members and patch. It checks names, collisions, required members, hashes and optionally a caller-pinned content ID. It accepts a relocated directory independently of Git or the original checkout. A detected inconsistency raises `SourceSnapshotError`. Verification provides internal integrity and comparison to an independently retained ID. Authentication of the entire campaign, including its provenance record, belongs to the enclosing campaign archive. The capture checks current source consistency at read boundaries; callers must arrange that the worker subsequently executes that same version.
