# Audit patch — 2026-10-14

Changes made after reviewing the `PyClustEval_Measurement_Diagnostics_Patch` distribution.

## 1. Internal metric schema v2 (breaking interpretation)

Internal geometric metrics (`silhouette`, `davies_bouldin`,
`calinski_harabasz`) **exclude labels `-1` (noise)** instead of incorrectly
counting all noise observations as one compact cluster. They are `NaN`
when fewer than two non-noise clusters exist, or the non-noise sample count is
insufficient. Non-noise **coverage** (`assigned_fraction`) must always be
reported alongside them. Silhouette is computed exactly up to 2,000 records;
for larger datasets it uses the same fixed 2,000 original sample indices
across all algorithms (filtered to assigned records per algorithm). These
sampling indices, and the count actually assigned, are recorded. Davies–Bouldin
and Calinski–Harabasz use all non-noise records. ARI and NMI still use all records, treating `-1`
as one predicted category, maintaining the previous overall quality definition.

**Do not combine pre-patch and post-patch geometric metrics in statistical
aggregates without recomputing them.** Every new run is marked
`clustering_metrics_v2_assigned_only` in the history and Excel export.

## 2. Consistent user-level wall time

A separate `runtime_wall_including_preprocessing_sec` records preprocessing
and the complete algorithm `run()` call; the old algorithm-reported
`runtime_sec` remains as a legacy field because its scope varies among
adapters (some skip initialization). The new field still excludes dataset
load, partition construction, metric calculation, history writes, and Excel
export. Results over multiple seeds and dedicated warmups are needed for
performance conclusions.

## 3. Accurate privacy disclosure

A Gaussian input perturbation run **does not produce an end-to-end DP
report**, because clean features and ground truth are used for evaluation
and class-based partitions are exported. The report and logs now disclose
this limitation explicitly. No privacy guarantee for the complete report is
claimed, and this patch does not implement an end-to-end private evaluator.

**Critical security fix:** The old implementation publicly logged `privacy_seed`
computed from the user-controlled run seed. This made added noise reconstructible
and therefore invalidated the privacy of the perturbed feature matrix to an
adversary who could obtain it. Noise now uses operating-system CSPRNG entropy
with a chunked Box-Muller transform; the benchmark seed does not reproduce
private noise and no privacy RNG seed is stored. This intentionally sacrifices
seed-level repeatability for privacy. Repeated independent releases consume
privacy budget and still need an external accountant. The report still contains
unprotected clean-feature hashes, clipped-data summaries, labels and metrics,
so it is **not safe as an end-to-end DP public release**.

## 4. What remains for a rigorous benchmark

- Multi-seed and paired confidence intervals with the same `dataset x seed x partition`.
- Explicit k protocols (oracle-k vs unsupervised k selection).
- Separately measured preprocessing, initialization, training, inference,
  evaluation, logical network payload and actual Flower transport overhead.
- Natural client data (not only label-aware synthesized non-IID partitioning).
- Real DP end-to-end threat model/accounting if publishing non-private metrics.
- Dedicated scaling experiments for varying sample count, dimensionality,
  clients and round count with quality / bandwidth / latency Pareto plots.
- Code-level concurrency protections for vendored modules and honest hardware metadata.

## Historical data warning

The archived `history/2026-10-13_16-47-06` record describes
`mnist_10k` but contains `n_samples=100, n_features=4`.
Do not treat it as a valid MNIST benchmark observation.
