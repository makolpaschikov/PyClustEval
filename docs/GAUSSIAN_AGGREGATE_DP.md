> **UPDATE 2026-10-17:** For the five adapted author methods, see the
> replacement implementation and limitations in [GAUSSIAN_AUTHOR_DP_V4.md](GAUSSIAN_AUTHOR_DP_V4.md).
> This earlier v3 document describes the original native KMeans/FCM/GMM aggregate
> modes. Statements below saying author algorithms are REJECTED are historical,
> **no longer true for v4**; the v4 variants are explicitly **modified DP proxy
> algorithms, not original author algorithms**.

# Gaussian aggregate DP v3: scientific scope and validation

## Why the original Dry Bean experiment produced ARI≈0

The older UI option `Gaussian DP (входы, legacy)` perturbs *each row* of the raw, unscaled 16-feature matrix. For raw L2 clipping threshold `100000`, the replacement-neighbor sensitivity is `200000`; the independent Gaussian noise added per **feature value** is large even at epsilon=20. Choosing another arbitrary raw clip threshold does not fix the fundamental per-record SNR problem.

**Do not combine or compare old input-DP results with new aggregate-DP results as though they used the same mechanism.** The old input-DP code remains as a clearly named legacy option for reproducibility.

## New modes and fair paired controls

- `Контроль для DP (только clipping)` / `public_clipped_control`: applies **fixed public scaling and L2 clipping**, initializes models independently of data, but adds NO privacy noise. This is the correct control for the new mechanism. It does NOT claim privacy.
- `Gaussian DP (агрегаты, доверенный сервер)` / `gaussian_dp_aggregate`: applies the **same public scaling and clipping**, then adds CSPRNG Gaussian noise to **aggregated sufficient statistics** in every model-update round. The native aggregate mechanisms remain enabled for `fed_kmeans_numpy`, `fed_fuzzy_cmeans_numpy`, `fed_gmm_diag_numpy`, and their `_flower` equivalents. Five Adapted methods now have separate modified DP local-proxy variants in v4. Since v4, five adapted methods also support explicitly modified DP proxy/server variants (the original author client-stage algorithms are NOT private). See GAUSSIAN_AUTHOR_DP_V4.md.
- `Gaussian DP (входы, legacy)`: original noise on every raw input row; NOT the recommended method for Dry Bean.

### Fixed public normalization of Dry Bean

The 16-dimensional Dry Bean vectors are transformed using **published** feature medians and IQRs from Krishnan et al. (2023), Table 2, DOI:10.1155/2023/2556066, with `center=published median`, `scale=published IQR/1.349`. These numbers are **fixed constants**, never learned from the current private dataset. The public table has limited precision for low-magnitude shape factors, so this is a dataset-specific reference rather than exact `StandardScaler` normalization. Iris/Wine/Digits use *public scikit-learn built-in reference datasets* to define their fixed normalizers. No private-fit scaler is permitted in the new mode.

Every transformed record is clipped to norm `C`, with suggested **C=4.0 in the public scaled space**. This is **not** 4 raw feature units and definitely not 100000. Report separately the fraction of clipped records, median/p95 input norms, and mean clipping distortion (these are **trusted-only** diagnostics).

### Privacy mechanism and accounting

Given fixed current model parameters, each clipped input contributes a bounded vector to the total of counts, sums, and optionally squared sums. For replacement of one record, conservative joint-vector L2 sensitivities per round are:

- KMeans: `2 sqrt(1+C²)`.
- Fuzzy CMeans (`m>1`): `2 sqrt(1+C²)` because the powered memberships are in [0,1] and have sum ≤1.
- Diagonal GMM: `2 sqrt(1+C²+C⁴)`.

A Gaussian perturbation is added jointly to all corresponding aggregate arrays **once per round**, using the existing analytic Gaussian calibrator and OS CSPRNG. The total configured epsilon/delta is split over **all scheduled rounds**, with conservative *basic sequential composition*; early stopping can only spend less. Three algorithm runs, each budgeted `(20, 1e-5)`, have a conservative across-algorithm bound of `(60,3e-5)`. Separate experiments on the same private dataset also **compose**. No multi-experiment persistent accountant exists.

Data-independent random initialization avoids revealing private data in starting centers or variances. Post-processing clips unstable noisy model estimates to public feasible ranges; a noisy denominator below roughly 2 sigma is treated as unreliable. This may lower accuracy and is an explicitly documented design choice.

### SECURITY SCOPE: not an end-to-end DP federated system

This is a **trusted-server** simulation, NOT local DP, NOT secure aggregation, and NOT a defense against a malicious server. Clients send raw per-client statistics to the server, which adds noise only **after** summing all active clients' messages. A server adversary observing individual client messages is not protected. The public-clipped control is **not DP**. Even in aggregate-DP mode, the full benchmark log/history/Excel report **IS NOT DP**: clean X/y, class-aware partitions, local evaluation metrics, input fingerprints, clipping fraction, and other diagnostics are exposed to the trusted evaluator. Sharing results from genuine confidential data requires independent privacy design/review and a privacy-safe results exporter; existing public release guard intentionally rejects these reports.

`Dirichlet`/`Label-limited` are rejected in aggregate-DP mode because their label-dependent partitioning is not privacy-accounted. IID and Quantity Skew are eligible. `known-k` is public metadata in this mode, not deduced from private `y`, and unbudgeted `estimated-k` is disallowed. The reported DP budget is per **single algorithm run** and does not cover report/evaluation data.

### Known limitations and validation status

- No Flower/Ray package was available in the audit runtime. `_flower` code is statically checked and included but NOT executed against a real Flower simulation here.
- True Gaussian aggregation was exercised on **real public Iris, Wine, and Digits**, including paired clipped controls and ε values, and on a **separately labelled synthetic 13,611-row / 16-dimensional scale sanity check**. This synthetic check is NOT Dry Bean.
- The full official Dry Bean ARFF is NOT available in this isolated environment; UCI / mirrored HTTP downloads are blocked. Consequently **no actual Dry Bean DP ARI is claimed**. The executable official-ARFF-only script below provides a falsifiable, transparent experiment once the real file is accessible.
- DP noise can *still* destroy Fuzzy and GMM on small datasets (Digits), even in aggregate mode. Do not assume meaningful ARI at ε=1/5/10/20.

## How to perform the REAL Dry Bean test

The application auto-caches the real dataset, ordinarily at:

`%USERPROFILE%\\.cache\\pyclusteval\\datasets\\dry_bean\\Dry_Bean_Dataset.arff`

On the machine holding the original ARFF, from the project folder:

```bash
python tools/benchmark_dry_bean_gaussian_aggregate.py --arff "C:\\path\\Dry_Bean_Dataset.arff" --clip 4 --epsilons 20 10 5 1 --seeds 42 43 44
```

The script validates 13,611 rows, 16 features, seven true classes and saves file SHA-256, real ARI/AMI/NMI, clipping fraction, parameter settings, and experiment histories. No fake fallback is provided. Flower needs separate installation:

```bash
python tools/benchmark_dry_bean_gaussian_aggregate.py --arff "C:\\path\\Dry_Bean_Dataset.arff" --backend flower --clip 4 --epsilons 20 10 --seeds 42 43 44
```

In the GUI, choose the native 3 NumPy/Flower methods or the 5 Adapted [DP proxy] variants (KMeans/FCM/GMM), use IID/10 clients/20 rounds/Participation100%/Dropout0%, `DP clip norm=4`, `delta=1e-5`. First run the `Контроль для DP (только clipping)` mode, then `Gaussian DP (агрегаты, доверенный сервер)` at ε=20 (then 10, 5, 1). For scientific conclusions use at least 10 seeds and keep the same control pipeline. The old `Privacy=None` baseline runs its conventional preprocessing and therefore is not an exact counterpart to the aggregate-DP configuration.
