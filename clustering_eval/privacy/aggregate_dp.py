"""Trusted-server, record-level Gaussian noise on round AGGREGATES.

This is NOT input perturbation, client-to-server protection, secure aggregation,
or end-to-end private reporting. See docs/GAUSSIAN_AGGREGATE_DP.md.
"""
from __future__ import annotations

import math
from typing import Any
import numpy as np
from sklearn.datasets import load_iris, load_wine, load_digits

from .gaussian import analytic_gaussian_sigma, secure_normal_noise

# Publicly PUBLISHED medians and IQRs for the full UCI Dry Bean dataset,
# Krishnan et al. (2023), Table 2, DOI:10.1155/2023/2556066.
# Small 4-decimal shape-factor features are published with limited precision.
# This transform is a BENCHMARK-SPECIFIC public reference, NOT a private fit.
_DRY_BEAN_MEDIANS = np.array([
    52981.50, 911.06, 350.62, 203.69, 1.575, 0.7724, 53858.50,
    259.73, 0.7637, 0.9880, 0.866, 0.795, 0.0063, 0.0014, 0.632, 0.996,
])
_DRY_BEAN_IQRS = np.array([
    34769.75, 327.30, 137.24, 57.70, 0.284, 0.0945, 35503.50,
    82.62, 0.0662, 0.0052, 0.085, 0.073, 0.0016, 0.0010, 0.116, 0.005,
])


def public_scaled_features(X_raw: np.ndarray, dataset_name: str) -> tuple[np.ndarray, dict[str, Any]]:
    """Deterministic transform using external PUBLIC reference moments only.

    Do NOT replace the reference with statistics fitted on private X without
    explicitly budgeting for their disclosure.
    """
    X = np.asarray(X_raw, dtype=np.float64)
    if dataset_name == 'dry_bean':
        if X.shape[1] != 16:
            raise ValueError('Dry Bean public reference requires 16 features')
        center = _DRY_BEAN_MEDIANS
        scale = _DRY_BEAN_IQRS / 1.349
        reference = 'published Dry Bean median/IQR, Krishnan et al. 2023, Table 2'
    elif dataset_name in ('iris', 'wine', 'digits'):
        public_ds = {'iris': load_iris, 'wine': load_wine, 'digits': load_digits}[dataset_name]()
        public_x = np.asarray(public_ds.data, dtype=np.float64)
        if X.shape[1] != public_x.shape[1]:
            raise ValueError('Feature count differs from the built-in public dataset')
        center = np.mean(public_x, axis=0)
        scale = np.std(public_x, axis=0)
        scale = np.where(scale > 1e-9, scale, 1.0)
        reference = f'public scikit-learn {dataset_name} reference data, not private X'
    else:
        raise ValueError(
            f'No PUBLIC feature normalization reference for {dataset_name!r}. '
            'Aggregate DP cannot safely use a StandardScaler fitted on private X.'
        )
    if not np.all(np.isfinite(X)):
        raise ValueError('Features must be finite')
    scaled = (X - center) / scale
    return scaled, {'source': reference, 'feature_count': int(X.shape[1]),
                    'center': center.tolist(), 'scale': scale.tolist(),
                    'private_data_fitted_scaler': False}


def clipped_public_features(X_raw: np.ndarray, dataset_name: str, clip_norm: float):
    if not np.isfinite(clip_norm) or clip_norm <= 0:
        raise ValueError('Aggregate clip norm must be finite and positive')
    X, ref = public_scaled_features(X_raw, dataset_name)
    norms = np.linalg.norm(X, axis=1)
    mult = np.minimum(1.0, float(clip_norm) / np.maximum(norms, 1e-12))
    clipped = X * mult[:, None]
    return clipped, {**ref, 'clip_norm_public_space': float(clip_norm),
                     'clipped_record_fraction_trusted_only': float(np.mean(norms > clip_norm)),
                     'median_norm_before_clipping_trusted_only': float(np.median(norms)),
                     'p95_norm_before_clipping_trusted_only': float(np.percentile(norms, 95)),
                     'mean_clipping_l2_distortion_trusted_only': float(np.mean(np.linalg.norm(X-clipped, axis=1)))}


def make_dp_aggregate_config(*, kind: str, epsilon: float, delta: float,
                             clip_norm: float, rounds: int, enabled: bool) -> dict[str, Any]:
    """Basic sequential composition over ALL scheduled rounds, not only executed rounds."""
    if kind not in ('kmeans', 'fuzzy', 'gmm'):
        raise ValueError(f'Unsupported aggregate family: {kind}')
    if rounds < 1:
        raise ValueError('rounds must be >=1')
    C = float(clip_norm)
    # Each clipped record contributes one vector to the concatenated
    # (counts, sums[, squared sums]) statistic. Replacement sensitivity <=2*bound.
    bound2 = 1.0 + C*C + (C**4 if kind == 'gmm' else 0.0)
    sensitivity = 2.0 * math.sqrt(bound2)
    sigma = (analytic_gaussian_sigma(epsilon=epsilon / rounds, delta=delta / rounds,
                                    sensitivity=sensitivity) if enabled else 0.0)
    return {'kind': kind, 'enabled': bool(enabled), 'epsilon_total': float(epsilon) if enabled else None,
            'delta_total': float(delta) if enabled else None,
            'epsilon_per_round': float(epsilon/rounds) if enabled else None,
            'delta_per_round': float(delta/rounds) if enabled else None,
            'sigma_per_coordinate': float(sigma), 'sensitivity_per_round': sensitivity,
            'budgeted_rounds': int(rounds), 'clip_norm': C,
            'accounting': 'basic sequential composition; conservative replace-one adjacency'}


def noisy_joint_aggregate(config: dict[str, Any], *arrays: np.ndarray) -> tuple[np.ndarray, ...]:
    """One JOINT Gaussian mechanism per round; zero noise for matched control."""
    sigma = float(config['sigma_per_coordinate'])
    if sigma <= 0:
        return tuple(np.asarray(a, dtype=np.float64) for a in arrays)
    return tuple(np.asarray(a, dtype=np.float64) + secure_normal_noise(np.shape(a), sigma) for a in arrays)


def public_initial_centers(k: int, n_features: int, seed: int, clip_norm: float) -> np.ndarray:
    """Public-seed initialization independent of any private data values."""
    rng = np.random.default_rng(int(seed) ^ 0x4B1A9C)
    centers = rng.normal(0.0, 0.6, size=(k, n_features))
    norms = np.linalg.norm(centers, axis=1)
    centers *= np.minimum(1.0, float(clip_norm) / np.maximum(norms, 1e-12))[:, None]
    return centers


def project_centers(centers: np.ndarray, clip_norm: float) -> np.ndarray:
    """Project noisy model parameters onto public feasible ball (DP postprocessing)."""
    centers = np.nan_to_num(np.asarray(centers, dtype=np.float64),
                            nan=0.0, posinf=0.0, neginf=0.0)
    norms = np.linalg.norm(centers, axis=1)
    return centers * np.minimum(1.0, float(clip_norm) / np.maximum(norms, 1e-12))[:, None]


def stable_noisy_count_threshold(dp: dict[str, Any]) -> float:
    """Noisy counts below ~2σ are not reliable denominators."""
    return max(1.0, 2.0 * float(dp.get('sigma_per_coordinate', 0.0)))
