"""Record-level Gaussian DP local-aggregate author-SERVER variants.

Only bounded, Gaussian-privatized client count/sum aggregates reach the
original author server stages. The authors' original LOCAL clustering routines
are replaced by DP-compatible, publicly initialized local representatives.
Consequently these five methods are MODIFIED SURROGATES, not the exact original
algorithms. Their outputs for trusted raw-X benchmark evaluation and the
non-DP benchmark report are NOT protected by an end-to-end privacy guarantee.

For IID/quantity_skew, partition membership is fixed independently of data
values. Per-client output mechanisms protect one record (replace-one adjacency)
with (eps,delta). Because the clients' records are disjoint, outputs in one
round enjoy PARALLEL composition; adaptive rounds compose SEQUENTIALLY.
For HF_DBSCAN one private candidate-representative release is followed by a
private histogram release (sequential composition).
"""
from __future__ import annotations

from time import perf_counter
from typing import Any

import numpy as np
from sklearn.cluster import KMeans
from sklearn.metrics import pairwise_distances_argmin

from .aggregate_dp import (
    make_dp_aggregate_config, noisy_joint_aggregate, project_centers,
    public_initial_centers, stable_noisy_count_threshold,
)
from ..algorithms.base import AlgorithmResult
from ..federated.environment import participation_entry_for_round
from .gaussian import analytic_gaussian_sigma, secure_normal_noise

_DP_VARIANTS = {
    'Adapted FKM': 'author_server_iterative_DP_local_prototypes',
    'Adapted FKDC': 'author_SNN_server_on_DP_local_prototypes',
    'Adapted HF_DBSCAN': 'author_density_server_on_DP_candidate_histogram',
    'Adapted NN-FC': 'author_SNN_server_on_DP_local_prototypes',
    'Adapted p-FClus': 'author_server_kmeans_on_DP_local_prototypes',
}


def _local_private_prototypes(Xc: np.ndarray, anchors: np.ndarray,
                              cfg: dict[str, Any]) -> tuple[np.ndarray, np.ndarray]:
    """DP count+sum query of bounded records assigned to public/DP anchors.

    Data-independent/public anchors or previously sanitized global anchors are
    conditioning inputs. Release only postprocessed noisy (means, weights),
    never unnoised centers/cluster membership. This protects REPLACEMENT of
    any one clipped input row in the current client's dataset.
    """
    assignment = pairwise_distances_argmin(Xc, anchors)
    local_counts = np.bincount(assignment, minlength=len(anchors)).astype(float)
    local_sums = np.zeros_like(anchors, dtype=float)
    np.add.at(local_sums, assignment, Xc)
    sums, counts = noisy_joint_aggregate(cfg, local_sums, local_counts)
    good = counts > stable_noisy_count_threshold(cfg)
    if not np.any(good):
        return np.empty((0, Xc.shape[1])), np.empty((0,))
    means = project_centers(sums[good] / counts[good, None], cfg['clip_norm'])
    weights = np.maximum(1., counts[good])
    return means, weights


def _local_releases(X: np.ndarray, partition: list[np.ndarray],
                    active: list[int], anchors: np.ndarray,
                    cfg: dict[str, Any]) -> tuple[np.ndarray, np.ndarray, int]:
    centers: list[np.ndarray] = []
    weights: list[np.ndarray] = []
    communication = 0
    for idx in active:
        local, count = _local_private_prototypes(X[partition[idx]], anchors, cfg)
        if len(local):
            centers.append(local)
            weights.append(count)
            communication += local.nbytes + count.nbytes
    if not centers:
        return np.empty((0, X.shape[1])), np.empty((0,)), 0
    return np.concatenate(centers), np.concatenate(weights), communication


def _ensure_candidates(centers: np.ndarray, weights: np.ndarray,
                       anchors: np.ndarray, required: int) -> tuple[np.ndarray, np.ndarray]:
    # Data-independent padding is DP-safe. Padding is used ONLY if extreme noise
    # removes all/most valid private representatives on very small datasets.
    if len(centers) < required:
        need = required - len(centers)
        reps = np.resize(anchors, (need, anchors.shape[1]))
        centers = np.concatenate((centers, reps), axis=0)
        weights = np.concatenate((weights, np.ones(need)))
    return centers, weights


def _dp_histogram_cells(X: np.ndarray, partition: list[np.ndarray],
                        active: list[int], candidates: np.ndarray,
                        *, size: float, epsilon: float, delta: float,
                        min_points: int, enabled: bool) -> tuple[dict[tuple[int, ...], float], int]:
    """Gaussian histogram over a candidate domain built ONLY from DP releases.

    Candidate keys are DP postprocessing. Unlisted cells are folded into the
    omitted category. Replacing one record changes at most two histogram cells,
    hence sensitivity <= sqrt(2), conservatively (2 for compatibility).
    """
    anchors = np.floor(candidates / size).astype(int)
    candidates_set = {tuple(map(int, row)) for row in anchors}
    # Axial neighbors improve coverage without looking at private occupied cells.
    for row in anchors:
        key = tuple(map(int, row))
        for axis in range(len(row)):
            for direction in (-1, 1):
                q = list(key)
                q[axis] += direction
                candidates_set.add(tuple(q))
    fixed_keys = sorted(candidates_set)
    mapping = {key: i for i, key in enumerate(fixed_keys)}
    counts = np.zeros(len(fixed_keys), dtype=float)
    for client_id in active:
        for row in np.floor(X[partition[client_id]] / size).astype(int):
            j = mapping.get(tuple(map(int, row)))
            if j is not None:
                counts[j] += 1
    sigma = (analytic_gaussian_sigma(epsilon=epsilon,delta=delta,sensitivity=2.0)
             if enabled else 0.0)
    if enabled:
        counts = counts + secure_normal_noise(counts.shape, sigma)
    # The key set released to the author server depends ONLY on DP counts.
    selected = {key: float(count) for key, count in zip(fixed_keys, counts)
                if count >= min_points}
    return selected, counts.nbytes


def run_dp_author_proxy(name: str, X: np.ndarray, partition: list[np.ndarray],
                        params: dict[str, Any], seed: int) -> AlgorithmResult:
    if name not in _DP_VARIANTS:
        raise ValueError(f'No adapted DP server variant for: {name}')
    dp = params.get('dp_aggregate')
    if dp is None or dp.get('kind') != 'kmeans':
        raise ValueError('Adapted DP mode requires calibrated Gaussian count+sum config')
    k = int(params.get('k', params.get('n_clusters', 3)))
    if k < 2 or len(partition) < 1:
        raise ValueError('Invalid k or client partition')
    started = perf_counter()
    d = X.shape[1]
    C = float(dp['clip_norm'])
    enabled = bool(dp['enabled'])
    rounds = int(dp['budgeted_rounds'])
    is_fkm = name == 'Adapted FKM'
    is_density = name == 'Adapted HF_DBSCAN'
    # A SINGLE round of DP release for four one-shot server adapters.
    # FKM retains scheduled, sequentially composed 20 rounds.
    q = (k if is_fkm else max(24, 4*k))
    anchors = public_initial_centers(q, d, seed, C)
    from ..algorithms import author_adapters as author
    traffic = 0
    history: list[dict[str, Any]] = []
    state_extra: dict[str, Any] = {}

    if is_fkm:
        mod = author._fedkmeans_module()
        server = mod.server_FKM(k, weighted=bool(params.get('weighted_agg', True)))
        for rnd in range(rounds):
            participation = participation_entry_for_round(params, rnd, len(partition))
            active = participation['successful_clients']
            local_centers, weights, upload = _local_releases(X, partition, active, anchors, dp)
            local_centers, weights = _ensure_candidates(local_centers, weights, anchors, k)
            # Author's weighted server KMeans over DP local representatives.
            with author._numpy_seed(seed + rnd):
                global_centers = server.aggregate(local_centers, weights)
            anchors = project_centers(np.asarray(global_centers), C)
            traffic += upload + anchors.nbytes * len(active)
            history.append({
                'round': rnd + 1, 'selected_clients': participation['selected_clients'],
                'successful_clients': active, 'dropped_clients': participation['dropped_clients'],
                'num_dp_representatives': len(local_centers),
            })
        centers = anchors
        labels = pairwise_distances_argmin(X, centers)
        state_extra['weighted_server_aggregation'] = bool(params.get('weighted_agg', True))
        state_extra['dp_sigma_prototype_per_coordinate'] = float(dp['sigma_per_coordinate'])
    else:
        participation = participation_entry_for_round(params, 0, len(partition))
        active = participation['successful_clients']
        # HF_DBSCAN spends HALF the budget on candidate representatives and
        # HALF on the subsequent candidate-cell histogram. Sequential composition
        # preserves the single-run configured (epsilon,delta).
        if is_density and enabled:
            cfg = make_dp_aggregate_config(kind='kmeans',epsilon=float(dp['epsilon_total'])/2,
                    delta=float(dp['delta_total'])/2,clip_norm=C,rounds=1,enabled=True)
        else:
            cfg = dp
        state_extra['dp_sigma_prototype_per_coordinate'] = float(cfg['sigma_per_coordinate'])
        candidates, weights, upload = _local_releases(X, partition, active, anchors, cfg)
        candidates, weights = _ensure_candidates(candidates, weights, anchors, max(21, k))
        traffic += upload
        with author._numpy_seed(seed):
            if name == 'Adapted FKDC':
                mod = author._fkdc_module()
                selected = np.asarray(mod.SNN(20, k, candidates), dtype=int)
                centers = candidates[selected]
                labels = pairwise_distances_argmin(X, centers)
            elif name == 'Adapted NN-FC':
                mod = author._nnfc_module()
                selected, _ = mod.SNN(2, k, candidates)
                centers = candidates[np.asarray(selected, dtype=int)]
                labels = pairwise_distances_argmin(X, centers)
            elif name == 'Adapted p-FClus':
                centers = KMeans(n_clusters=k, random_state=seed,n_init=10).fit(
                    candidates, sample_weight=weights).cluster_centers_
                centers = project_centers(centers, C)
                labels = pairwise_distances_argmin(X, centers)
                state_extra['known_limitation'] = ('Author client-level personalization omitted: '
                    'it would disclose nonprivatized data-dependent personalized centers')
            else:
                mod = author._fdbscan_module()
                L = float(params.get('dp_proxy_cell_size', 0.75))
                if L <= 0:
                    raise ValueError('dp_proxy_cell_size must be positive')
                if d < 2:
                    raise ValueError('DP density projection requires >=2 features')
                # Fixed PUBLIC data-independent 2D orthonormal projection.
                # Original high-dimensional density grids are too sparse for
                # useful cells; the 2D projection is a declared algorithm change.
                rng = np.random.default_rng(int(seed) ^ 0x44DB5CAA)
                projection, _ = np.linalg.qr(rng.normal(size=(d, 2)), mode='reduced')
                X_density = X @ projection
                proto_density = candidates @ projection
                min_points = int(params.get('min_points', 4))
                mapping, count_bytes = _dp_histogram_cells(
                    X_density, partition, active, proto_density, size=L,
                    epsilon=(float(dp['epsilon_total'])/2 if enabled else 20.),
                    delta=(float(dp['delta_total'])/2 if enabled else 1e-5),
                    min_points=min_points, enabled=enabled)
                traffic += count_bytes
                server = mod.FDBSCAN_Server()
                server.initialize({'MIN_POINTS': min_points})
                if mapping:
                    cells, cell_labels = server.compute_clusters(mapping)
                else:
                    cells, cell_labels = [], []
                cell_to_label = {tuple(cell): int(label)
                                 for cell, label in zip(cells, cell_labels)}
                labels = np.array([cell_to_label.get(tuple(map(int, row)), -1)
                        for row in np.floor(X_density / L).astype(int)], dtype=int)
                centers = candidates
                state_extra.update({'dp_proxy_cell_size': L,
                    'histogram_candidate_count': int(len(mapping)),
                    'dp_sigma_histogram_per_coordinate': (analytic_gaussian_sigma(
                        epsilon=float(dp['epsilon_total'])/2,delta=float(dp['delta_total'])/2,
                        sensitivity=2.0) if enabled else 0.0),
                    'dp_density_projection': 'public-seeded random orthonormal 2D projection',
                    'dp_density_projection_seed': int(seed),
                    'known_limitation': ('Author density server uses privatized '
                        'DP-candidate histogram in a public 2D projection, not the '
                        'original full-dimensional sparse occupied-cell map')})
        history.append({'round':1, 'selected_clients': participation['selected_clients'],
                        'successful_clients':active, 'dropped_clients':participation['dropped_clients'],
                        'num_dp_representatives':len(candidates)})
        if is_density:
            state_extra['privacy_budget_split'] = ('epsilon/2,delta/2 for local prototypes; '
                                                   'epsilon/2,delta/2 for histogram')
    state = {
        'backend': 'author-server DP proxy',
        'author_algorithm': name,
        'dp_variant': _DP_VARIANTS[name],
        'dp_mechanism': 'record_level_Gaussian_local_aggregate_representatives',
        'algorithm_fidelity': ('MODIFIED: author SERVER retained, original LOCAL '
                               'client stage replaced with bounded DP aggregates'),
        'not_equivalent_to_author_original': True,
        'protected_release': 'DP local aggregate representatives (and DP cells for HF_DBSCAN)',
        'private_raw_x_used_for_evaluation_only': True,
        'dp_accounting': dp['accounting'],
        'dp_budgeted_rounds': rounds,
        'rounds': len(history),
        'global_centers': np.asarray(centers).tolist(),
        'dp_noise_rng': 'OS CSPRNG; benchmark seed does not reproduce DP noise',
        **state_extra,
    }
    return AlgorithmResult(labels=np.asarray(labels, dtype=int), model_state=state,
        history=history, runtime_sec=perf_counter()-started, communication_bytes=int(traffic))
