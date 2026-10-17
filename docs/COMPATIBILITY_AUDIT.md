# Compatibility audit

This audit distinguishes execution compatibility from clustering quality.

## Test coverage

- 4 local algorithms × Iris/Wine/Blobs/Digits.
- 8 non-Flower federated algorithms × Iris/Wine/Blobs/Digits × IID/Dirichlet.
- Shared benchmark parameter propagation and per-algorithm override isolation.
- Degenerate and near-degenerate output diagnostics.
- Author-adapter source/patch checks.
- HF_DBSCAN sparse-grid equivalence checks.
- FKDC/NN-FC SNN uninitialized-buffer regression check.
- Equal-budget density sensitivity tests.
- Runtime warnings are treated as errors in the final suite.

Final suite in the build environment: **103 passed, 1 skipped**. The skipped case is the optional Flower/Ray runtime, which is not installed in the build environment.

## Compatibility matrix

The generated `compatibility_matrix.csv` contains 80 non-Flower executions:

- 73 `ok`
- 6 `degenerate`
- 1 `near_degenerate`
- 0 execution errors

The non-OK baseline cases are not crashes:

- Wine / Adapted HF_DBSCAN / IID: all noise.
- Wine / Adapted HF_DBSCAN / Dirichlet: all noise.
- Wine / sklearn DBSCAN: all noise.
- Digits / Adapted HF_DBSCAN / IID: all noise.
- Digits / Adapted HF_DBSCAN / Dirichlet: all noise.
- Digits / sklearn DBSCAN: all noise.
- Digits / Adapted NN-FC / IID: 10 labels exist, but about 98% of samples fall into one cluster (`near_degenerate`).

These are kept visible rather than silently retuned against ground-truth labels.

## FKDC / NN-FC SNN fix

The author SNN code allocated `indexSharedNeighbor` with `numpy.empty`, filled only the prefix corresponding to actual shared neighbors, and then searched the entire uninitialized row. Random memory contents could therefore be mistaken for valid sample indices. In those false-positive branches, the actual initialized shared-neighbor slice could be empty and the similarity expression became `0/0`, producing the observed `RuntimeWarning`.

The executable compatibility copies now initialize unused slots with `-1`, an impossible sample index. Populated entries and the intended SNN calculation are unchanged. Original uploaded sources remain preserved as `utils_original.txt`.

The full suite passes with `RuntimeWarning` promoted to an error.

## Parameter fairness

Common benchmark controls are centralized and shared where they have the same meaning:

- seed
- target cluster count (`k`) where consumed
- communication-round budget where consumed
- convergence tolerance where consumed
- local max-iteration budget where consumed
- client count and the exact same partition
- minimum samples per client
- sklearn DBSCAN uses the generic `min_samples=5`; Adapted HF_DBSCAN preserves the author `MIN_POINTS=4`. They are not forced equal because these parameters have algorithm-specific semantics.

Each algorithm now declares `common_param_support`. Reports record both supported and non-applicable common parameters, so the benchmark does not claim that a parameter was equalized when the implementation ignores it.

Algorithm-specific quantities remain separate when they are not semantically equivalent, e.g. DBSCAN `eps`, HF_DBSCAN `L`, fuzzy exponent, GMM covariance regularization, author-specific local iteration choices, and p-FClus personalization iterations.

## Density sensitivity

`density_sensitivity.csv` contains a fixed five-candidate unlabeled sweep for DBSCAN and HF_DBSCAN. The sensitivity sweep may deliberately use one common neighborhood-count budget for controlled analysis; this is separate from the normal generic profile (DBSCAN 5, HF_DBSCAN author 4). Candidate scales are derived from `X` only; labels are never used to generate or select candidates.

DBSCAN uses Euclidean kNN distance because `eps` is an Euclidean radius. HF_DBSCAN uses Chebyshev kNN distance because `L` is an axis-aligned cell edge. Every candidate is retained in the report; ARI/NMI are evaluation columns only.

This sensitivity audit confirms that HF_DBSCAN remains especially brittle on high-dimensional Wine/Digits rather than merely crashing due to the previously fixed dense-grid implementation.
