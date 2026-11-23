"""The Windows cold campaign runtime attested by the Flower pilot."""

import platform
import sys
from importlib.metadata import PackageNotFoundError, version


FLOWER_ALGORITHMS = frozenset((
    "fed_kmeans_flower", "fed_fuzzy_cmeans_flower", "fed_gmm_diag_flower",
))


# Runtime, transport and numerical libraries used in the real Windows pilot.
_TRANSPORT_VERSIONS = {
    "flwr": "1.41.0", "ray": "2.55.1", "grpcio": "1.85.3",
    "grpcio-health-checking": "1.81.2", "protobuf": "6.33.6",
}
FLOWER_TRANSPORT_PACKAGES = tuple(_TRANSPORT_VERSIONS)
_VERIFIED_VERSIONS = {
    **_TRANSPORT_VERSIONS,
    "numpy": "2.5.5", "scipy": "1.18.1", "scikit-learn": "1.9.1",
}


def runtime_rejection(job: dict, protocol: dict) -> str | None:
    """Explain why a planned job cannot run in this process environment."""
    profile = job["execution_profile"]
    lifecycle = profile.get("lifecycle") if isinstance(profile, dict) else profile
    if lifecycle != "cold":
        return f"Unverified backend/lifecycle: {job['backend']}/{lifecycle}"
    name = job["algorithm"]
    if not name.endswith("_flower") and "flower" not in job["backend"].lower():
        return None
    if name not in FLOWER_ALGORITHMS or job["backend"] != "flower-simulation":
        return f"Unverified backend: {job['backend']}/{name}"
    if (not isinstance(profile, dict) or profile.get("processes") != 1
            or profile.get("blas_threads") != 1 or protocol.get("privacy_mode") != "none"
            or protocol.get("stopping_profile") not in {"current_gui", "historical_paper"}
            or "historical_implementation" in protocol):
        return f"Unverified backend: {name} requires an ordinary non-private cold campaign with one BLAS thread"
    params = job["effective_params"]
    if params.get("client_gpus", 0) != 0 or params.get("client_cpus", 1) != 1:
        return f"Unverified backend: {name} requires one CPU and zero GPUs per Ray actor"
    if (sys.platform != "win32" or platform.machine().upper() != "AMD64"
            or sys.implementation.name != "cpython" or sys.version_info[:3] != (3, 12, 10)
            or sys.getwindowsversion().build != 26200):
        return f"Unverified backend: {name} requires Windows build 26200 x64 and CPython 3.12.10"
    for package, expected in _VERIFIED_VERSIONS.items():
        try:
            installed = version(package)
        except PackageNotFoundError as exc:
            return f"Unverified backend: {exc}"
        if installed != expected:
            return f"Unverified backend: {package} {installed}, expected {expected}"
    return None
