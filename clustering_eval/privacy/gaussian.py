from __future__ import annotations

import math
import secrets
from statistics import NormalDist
from typing import Any

import numpy as np

_NORMAL = NormalDist()


def secure_normal_noise(shape: tuple[int, ...], sigma: float) -> np.ndarray:
    """Generate iid Gaussian noise from OS CSPRNG via a Box-Muller transform.

    No deterministic benchmark seed is allowed to reconstruct privacy noise.
    Draws are chunked so full MNIST does not require a second huge random-byte
    buffer. Every 53-bit uniform is in the OPEN interval (0, 1).
    """
    n = int(np.prod(shape, dtype=np.int64))
    out = np.empty(n, dtype=np.float64)
    position = 0
    while position < n:
        pairs = min(262_144, (n - position + 1) // 2)
        bits = np.frombuffer(secrets.token_bytes(pairs * 16), dtype="<u8")
        uniform = ((bits >> np.uint64(11)).astype(np.float64) + 0.5) / float(1 << 53)
        radius = np.sqrt(-2.0 * np.log(uniform[::2])) * float(sigma)
        theta = (2.0 * np.pi) * uniform[1::2]
        normals = np.empty(pairs * 2, dtype=np.float64)
        normals[0::2] = radius * np.cos(theta)
        normals[1::2] = radius * np.sin(theta)
        count = min(len(normals), n - position)
        out[position:position + count] = normals[:count]
        position += count
    return out.reshape(shape)


def _delta_for_sigma(sigma: float, epsilon: float, sensitivity: float) -> float:
    if sigma <= 0:
        return 1.0
    a = sensitivity / (2.0 * sigma) - epsilon * sigma / sensitivity
    b = -sensitivity / (2.0 * sigma) - epsilon * sigma / sensitivity
    # Analytic Gaussian mechanism privacy-loss expression (Balle & Wang).
    value = _NORMAL.cdf(a) - math.exp(epsilon) * _NORMAL.cdf(b)
    return max(0.0, min(1.0, float(value)))


def analytic_gaussian_sigma(
    *, epsilon: float, delta: float, sensitivity: float
) -> float:
    """Return the minimum sigma for the analytic Gaussian mechanism."""
    if epsilon <= 0:
        raise ValueError("epsilon must be greater than zero")
    if not 0 < delta < 1:
        raise ValueError("delta must be in (0, 1)")
    if sensitivity <= 0:
        raise ValueError("sensitivity must be greater than zero")

    low = 0.0
    high = float(sensitivity)
    while _delta_for_sigma(high, epsilon, sensitivity) > delta:
        high *= 2.0
        if high > sensitivity * 1e12:
            raise RuntimeError("Could not calibrate Gaussian noise")

    for _ in range(90):
        mid = (low + high) / 2.0
        if _delta_for_sigma(mid, epsilon, sensitivity) > delta:
            low = mid
        else:
            high = mid
    return high


def apply_gaussian_input_dp(
    X_raw: np.ndarray,
    *,
    epsilon: float,
    delta: float,
    clip_norm: float,
    seed: int,
) -> tuple[np.ndarray, dict[str, Any]]:
    """Apply one shared record-level Gaussian input-perturbation mechanism.

    Each raw feature vector is L2-clipped to ``clip_norm`` and independent
    isotropic Gaussian noise is added directly in raw feature space.  No
    data-dependent global normalization is performed before the privacy
    mechanism, because estimating such normalization from the same private
    dataset without accounting for it would invalidate an end-to-end DP claim.

    Under replace-one adjacency, two clipped records can differ by at most
    ``2 * clip_norm`` in L2 norm.  Sigma is calibrated with the analytic
    Gaussian mechanism.  The privatized matrix is sampled once per experiment
    and reused by all algorithms and all communication rounds; subsequent
    *training* computations are post-processing of that same DP input. Public
    benchmark metadata and clean-X/y evaluation metrics are NOT DP.

    The public benchmarking seed must never reproduce DP noise. The noise is
    generated using operating-system cryptographic random bytes, and its secret
    entropy is neither retained nor recorded.
    """
    X = np.asarray(X_raw, dtype=np.float64)
    if X.ndim != 2 or len(X) == 0:
        raise ValueError("X_raw must be a non-empty 2D array")
    if clip_norm <= 0:
        raise ValueError("clip_norm must be greater than zero")

    norms = np.linalg.norm(X, axis=1)
    scale = np.minimum(1.0, clip_norm / np.maximum(norms, 1e-12))
    clipped = X * scale[:, None]

    sensitivity = 2.0 * float(clip_norm)
    sigma = analytic_gaussian_sigma(
        epsilon=float(epsilon),
        delta=float(delta),
        sensitivity=sensitivity,
    )
    # "seed" intentionally does NOT control DP randomness. A published or
    # guessable RNG seed would allow an adversary to subtract the noise.
    noise = secure_normal_noise(clipped.shape, sigma)
    privatized_raw = clipped + noise

    report = {
        "mode": "gaussian_dp",
        "mechanism": "record-level Gaussian input perturbation",
        "adjacency": "replace-one record",
        "calibration": "analytic Gaussian mechanism",
        "epsilon": float(epsilon),
        "delta": float(delta),
        "clip_norm": float(clip_norm),
        "l2_sensitivity": sensitivity,
        "sigma_raw_feature_space": float(sigma),
        "noise_rng": "OS CSPRNG (secrets.token_bytes) + Box-Muller; seed not exposed",
        "dp_noise_reproducible_from_benchmark_seed": False,
        "clipped_record_fraction": float(np.mean(norms > clip_norm)),
        "privacy_space": "raw feature space (no data-dependent global scaler)",
        "protected_scope": "feature matrix X only; y labels and partition metadata are not privatized",
        "round_composition": (
            "one privatized matrix is sampled once and reused; subsequent algorithm "
            "rounds are post-processing of the same DP release"
        ),
        "across_experiment_composition": (
            "separate benchmark runs on the same private data compose privacy loss; "
            "PyClustEval does not maintain a cross-experiment privacy accountant"
        ),
    }
    return np.asarray(privatized_raw, dtype=np.float64), report
