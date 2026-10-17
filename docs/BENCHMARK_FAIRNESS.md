# Benchmark fairness profile

PyClustEval compares implementations under a shared benchmark profile wherever the parameters have the same meaning. It deliberately does **not** force algorithm-specific knobs to the same numeric value when their semantics differ.

## Common conditions

For UI `ComparisonService` runs the following settings are shared by both compared algorithms:

- `seed` — one benchmark seed;
- `target_clusters` / `k` — the same requested cluster count for algorithms that consume `k`;
- `rounds` — the same maximum communication-round budget for iterative federated implementations (default `10`);
- `tol` — common convergence tolerance where the implementation supports it (default `1e-4`);
- `max_iter` — common local iterative budget for compatible local estimators (default `300`);
- `density_min_samples` — common DBSCAN neighborhood control defaults to `5`; HF_DBSCAN intentionally preserves the author `MIN_POINTS=4` instead of forcing numerical equality;
- `num_clients` — same number of clients;
- one partition is generated once and reused by both algorithms;
- `min_samples_per_client=3` by default, because NN-FC is the strictest currently integrated author implementation;
- identical client CPU/GPU resource requests for Flower adapters.

`target_clusters=None` keeps the historical benchmark convention: `k` is derived from the number of distinct ground-truth classes. This is explicitly recorded as `cluster_count_source="ground_truth_oracle"`. Per-sample labels are **not** supplied to algorithms. Set `target_clusters` explicitly to avoid oracle-k.

Every result stores the effective common and algorithm-specific parameters in `model_state["benchmark"]`. It also records `common_param_support` and `common_params_not_applicable`, so a parameter is never presented as "equalized" for an implementation that does not actually consume it.

## Parameters that are intentionally not equalized

These parameters are implementation-specific and forcing a common value would change the tested algorithm:

- preprocessing: standard scaling for the historical PyClustEval algorithms, author-required MinMax scaling for HF_DBSCAN, raw input for p-FClus;
- HF_DBSCAN `L` and sklearn DBSCAN `eps` (different geometric meanings, so they are not forced to the same numeric value);
- Fuzzy C-Means `fuzziness`;
- GMM `reg_covar`;
- author FKM local iteration count, empty-cluster handling and weighted aggregation;
- p-FClus personalization iterations;
- fixed internal choices hard-coded by the FKDC/NN-FC author implementations.

One-shot algorithms (HF_DBSCAN, FKDC, NN-FC, p-FClus) naturally report one round. They are not artificially repeated to match a 10-round iterative method.

## No label-based parameter tuning

The compatibility suite does not tune `L`, `eps`, or other algorithm-specific hyperparameters separately for each dataset using ARI/NMI. DBSCAN's default `eps` is data-adaptive but label-free: it is the fixed `q=0.50` k-distance quantile computed from `X` after StandardScaler. A run that completes but returns one cluster or all noise is recorded as a **degenerate result**, not silently retuned. A result with at least 95% of non-noise samples in one cluster is marked **near-degenerate**.

This distinction matters: a crash is an implementation compatibility problem, while a degenerate clustering can be a legitimate consequence of a fixed hyperparameter on a different dataset.


## Density sensitivity protocol

`tools/density_sensitivity.py` provides a pre-registered, equal-budget sensitivity sweep for sklearn DBSCAN and Adapted HF_DBSCAN. It does **not** select a best parameter using ARI/NMI.

- both algorithms receive the same `density_min_samples`;
- both receive exactly five candidate radius/cell-size settings at quantiles `0.20, 0.35, 0.50, 0.65, 0.80`;
- candidates are generated from k-nearest-neighbor distances using only `X`, never `y`;
- DBSCAN uses Euclidean kNN distances because `eps` is an Euclidean neighborhood radius by default;
- HF_DBSCAN uses Chebyshev kNN distances because `L` is an axis-aligned cell edge and therefore lives on a per-coordinate/max-coordinate scale;
- candidates are computed after each implementation's declared preprocessing, so StandardScaler and MinMaxScaler are respected;
- every candidate is reported. ARI/NMI are evaluation columns only and are never used to choose or retune a candidate.

This equalizes **search budget and unlabeled scale construction**, not the raw numeric radius, because `eps` and `L` are not the same parameter.

## Compatibility fixes applied to author sources

Two fixes were added because the original code could not reasonably execute across the built-in matrix while preserving the same mathematical operation:

- **HF_DBSCAN**: dense d-dimensional cell tensors were replaced with a sparse dictionary of occupied cells; exponential `3^d` neighbor generation was replaced with direct generation of the same `2*d` axial neighbors. The untouched uploaded file is preserved as `fd_dbscan_original.py` and low-dimensional equivalence is regression-tested.
- **NN-FC**: the all-pairs Python loop used only to compute the maximum ratio over positive folded-uniform values was replaced by the exact identity `max(arr) / min(arr)`. This removes the pathological runtime on high-dimensional Digits without changing the computed ratio. The original source remains in `utils_original.txt`.
- **FKDC and NN-FC SNN**: `indexSharedNeighbor` was allocated with `numpy.empty` and later searched beyond the initialized slice, so random memory contents could masquerade as shared-neighbor indices and trigger nondeterministic `0/0` similarity calculations. The executable copies initialize the buffer with the impossible sentinel `-1`; original files remain preserved. This implements the apparent intended semantics without altering valid populated entries.

These changes mean runtime numbers belong to the **PyClustEval-adapted executable version** of those implementations. Source provenance and patches are listed in `SOURCE_MANIFEST.json`.

## Test matrix

`tests/test_algorithm_dataset_matrix.py` covers:

- all four local algorithms × Iris/Wine/Blobs/Digits;
- all eight non-Flower federated algorithms × Iris/Wine/Blobs/Digits × IID/Dirichlet;
- shared benchmark parameter propagation;
- oracle-k disclosure;
- per-algorithm override isolation;
- degenerate/near-degenerate diagnostics.

Flower tests are conditional because `flwr[simulation]`/Ray is an optional dependency. When it is installed, the registry readiness test is enabled; the base test environment does not pretend that Flower simulation was executed.

To regenerate a human-readable CSV compatibility sweep:

```bash
python tools/compatibility_matrix.py --output docs/compatibility_matrix.csv
```

## Multi-algorithm experiment fairness

A single `RunRequest` may contain two or more algorithms. In federated mode, the client partition
is generated once from the raw dataset before the algorithm loop and the same partition indices are
reused for every selected algorithm. This removes pairwise-run partition drift inside a benchmark.
Per-algorithm preprocessing is still preserved when required by an author implementation; it changes
feature values, not which samples belong to which clients.
