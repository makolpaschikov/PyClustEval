# Measurement diagnostics patch

This patch makes the non-IID benchmark auditable instead of assuming that a changed client partition must change global ARI/NMI.

## Common evaluation space

All algorithms keep their declared training preprocessing (`standard`, `minmax`, or `raw`), but internal geometric metrics are now evaluated on one common matrix:

`StandardScaler(original_raw_X)`

This makes Silhouette, Davies–Bouldin, and Calinski–Harabasz comparable across algorithms. In Gaussian-DP runs the clean evaluation matrix remains outside the privacy mechanism, like `y_true` used for ARI/NMI; the privatized training matrix is separately fingerprinted.

## Prediction fingerprint

Every run records `prediction_hash`, a SHA-256 based fingerprint of the complete predicted partition after canonicalizing arbitrary cluster IDs. Two hashes are equal only when the sample-to-cluster assignment is the same up to label permutation (`-1` noise is preserved).

The raw label-vector hash is also recorded for debugging.

## Client-level quality

For federated runs, ARI and NMI are additionally computed on every client's subset and summarized as:

- mean;
- sample-weighted mean;
- worst client;
- standard deviation.

These are diagnostics of client-level heterogeneity. They are not replacements for global ARI/NMI and should not be interpreted as mathematically equivalent to the global metric.

## Active-data fingerprint

Each participation/dropout round records:

- successful client IDs;
- number of active samples;
- `active_data_hash` for the union of sample IDs used in the round.

The complete schedule has an `active_data_fingerprint`. This distinguishes “different partition, same complete dataset” from experiments where the actually participating sample set changes.

## Federated initialization

Native and Flower Fed K-Means / Fuzzy C-Means / diagonal-GMM no longer initialize by sampling directly from the full server-side `X`.

Initial means/centers use `federated_priority_topk_v1`:

1. each active client ranks its own samples with a deterministic seed-based priority;
2. each client transmits at most `k` candidate vectors;
3. the server picks the global top-`k` candidates from those messages.

When all clients participate, the selected initialization is invariant to how the same objects are partitioned between clients. With partial participation, only successful round-1 clients contribute.

GMM initial global feature variance is computed from client `count / sum / sum(x^2)` sufficient statistics rather than `np.var(X)` on the server.

Initialization communication is included in `communication_bytes`.

## Expected interpretation

For exact sufficient-statistic algorithms with 100% participation, 0% dropout, and no privacy perturbation, IID and non-IID partitions may still produce the exact same global prediction. That is now directly visible as:

- different `partition_id`;
- same `active_data_fingerprint` (all samples participate);
- same `prediction_hash`;
- potentially different client-level ARI/NMI distributions.

With partial participation/dropout or Gaussian DP, the benchmark additionally shows whether the active data or privatized training matrix actually changed.
