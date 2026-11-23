"""Scientific runtime conditions for continuing an existing campaign."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
import platform
import re
import sys

from packaging.version import InvalidVersion, Version
from ..application.flower_profile import FLOWER_TRANSPORT_PACKAGES


CORE_PACKAGES = ("numpy", "scipy", "scikit-learn")
CORE_FIELDS = ("implementation", "python", "os", "architecture", *CORE_PACKAGES)


def interpreter_fields() -> dict[str, str]:
    return {"implementation": sys.implementation.name, "python_version": platform.python_version(),
            "os": platform.system(), "architecture": platform.machine()}


def _version(value: object) -> Version | None:
    if not isinstance(value, str):
        return None
    try:
        return Version(value)
    except InvalidVersion:
        return None


def _identity(record: dict) -> dict:
    """Read current identity fields and the old Windows CPython build banner."""
    def word(key: str) -> str:
        value = record.get(key)
        return value if isinstance(value, str) else ""

    banner = word("python")
    platform_text = word("platform")
    build = re.search(r"\[MSC v\.\d+ (?:32|64) bit \(([^)]+)\)\]", banner)
    implementation = word("implementation")
    if not implementation and build and "(tags/v" in banner:
        implementation = "cpython"
    system = word("os") or platform_text.partition("-")[0]
    arch = word("architecture") or word("machine") or (build.group(1) if build else "")
    arch = {"x86_64": "amd64", "aarch64": "arm64"}.get(arch.lower(), arch.lower())
    version = word("python_version") or (banner.split()[0] if banner else None)
    return {"implementation": implementation.lower() if implementation else None,
            "python": _version(version), "os": system.lower() or None, "architecture": arch or None}


def _fields(record: dict) -> dict:
    values = _identity(record)
    # A supervisor records distribution metadata. Workers report installed and
    # imported versions; the native benchmark also records loaded numerical libraries.
    packages = record.get("packages", [])
    if isinstance(packages, Mapping):
        entries = ((k, v.get("imported_version") or v.get("installed")) for k, v in packages.items()
                   if isinstance(v, dict))
    elif isinstance(packages, (list, tuple)):
        entries = (p for p in packages if isinstance(p, (list, tuple)) and len(p) == 2)
    else:
        entries = ()
    for name, value in entries:
        if not isinstance(name, str):
            continue
        name = re.sub(r"[-_.]+", "-", name).lower()
        if name not in CORE_PACKAGES and name not in FLOWER_TRANSPORT_PACKAGES:
            continue
        version = _version(value)
        values[name] = version if name not in values or values[name] == version else None
    for name in CORE_PACKAGES:
        native = record.get("sklearn" if name == "scikit-learn" else name)
        if native is not None:
            values[name] = _version(native)
    return values


class IncompatibleEnvironment(ValueError):
    """Admission failure with human-readable locations and values."""

    def __init__(self, differences: list[str]) -> None:
        self.differences = differences
        super().__init__("Incompatible campaign environment: " + "; ".join(differences))


def check_environment(snapshot: dict, runtime: dict) -> None:
    """Require attested values before new work, independently of venv paths.

    Only sessions with previous attempts contribute historical evidence. A
    rejected resume cannot poison a future attempt in a compatible environment.
    """
    actual = _fields(runtime)
    creation = _fields(snapshot["environment"])
    sessions = {item["session_id"]: item for item in snapshot["sessions"]}
    session_fields = {sid: _fields(s["runtime"]) for sid, s in sessions.items() if s["runtime"] is not None}
    differences = set()
    available = set()
    for key, module in zip(CORE_PACKAGES, ("numpy", "scipy", "sklearn")):
        loaded = sys.modules.get(module)
        if loaded is not None:
            version = _version(getattr(loaded, "__version__", None))
            if version is None or version != actual.get(key):
                differences.add(f"current {key}: loaded={version or 'unknown'}, installed={actual.get(key) or 'unknown'}")

    def compare(source: str, values: dict, keys: Iterable[str]) -> set[str]:
        recorded = set()
        for key in keys:
            if values.get(key) is None:
                continue
            recorded.add(key)
            available.add(key)
            if actual.get(key) != values[key]:
                differences.add(f"{source}: {key} recorded={values[key]}, current={actual.get(key) or 'unknown'}")
        return recorded

    compare("campaign creation", creation, CORE_FIELDS)
    for job in snapshot["jobs"]:
        flower = job["job"]["backend"] == "flower-simulation"
        for attempt in job["attempts"]:
            if attempt["details"].get("tree_resources", {}).get("total_processes") == 0:
                continue
            sid = attempt["session_id"]
            session = sessions[sid]
            label = f"session {sid}"
            # The original run creates the campaign and manages its first session
            # in the same interpreter, including journals predating session_runtime.
            if sid in session_fields:
                saved = session_fields[sid]
            elif session is snapshot["sessions"][0] and session["command"] == "run":
                saved = creation
            else:
                saved = {}
            keys = (*CORE_FIELDS, *FLOWER_TRANSPORT_PACKAGES) if flower else CORE_FIELDS
            recorded = compare(label, saved, keys)
            aid = attempt["attempt_id"]
            worker = (attempt["details"].get("failure") or {}).get("worker", {})
            accepted = job["accepted"]
            if accepted and accepted["attempt_id"] == aid:
                candidate = accepted["candidate"]
                worker = candidate["worker"]
                benchmark = candidate["report"]["model_state"]["benchmark"].get("environment", {})
                recorded.update(compare(f"attempt {aid}", _fields(benchmark), CORE_FIELDS))
            if worker.get("runtime"):
                recorded.update(compare(f"worker {aid}", _fields(worker["runtime"]), keys))
            for key in set(keys) - recorded:
                differences.add(f"{label}: {key} unknown for previous attempt")
    for key in set(CORE_FIELDS) - available:
        differences.add(f"campaign: no recorded {key}")
    if differences:
        raise IncompatibleEnvironment(sorted(differences))
