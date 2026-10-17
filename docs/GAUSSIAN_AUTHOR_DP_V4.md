# Gaussian DP v4: DP-author-server variants for ALL five adapted methods

**Status:** Implemented; 165 automated tests passed, five skipped because of optional dependencies. 144 **REAL** outcome rows from public Iris, Wine and Digits (3 benchmark seeds × 2 modes × 8 executable methods). Official UCI Dry Bean has not been executed because the original ARFF is not present in the validation environment. Flower/Ray simulations have not been executed here.

## Scientific honesty: what changed, and what did not

The original adapted-author algorithms are **NOT automatically DP**. In Privacy=None their existing implementation remains unchanged. When aggregate DP or the matched clipped control is selected, the adapted algorithms are displayed as `Adapted NAME [DP proxy]`, with backend `author-server DP proxy`. This is a **NEW ALGORITHM VARIANT**, preserving author SERVER postprocessing only; original author LOCAL computation is replaced by private count/sum statistics. Results must NOT be grouped or pooled with the unmodified algorithms.

| Adapted algorithm | DP client-side protocol | Author server step | Rounds | Distinction from original |
|---|---|---|---:|---|
| FKM | public/DP anchor assignments, clipped local sums and counts with Gaussian noise **each round** | weighted author `server_FKM.aggregate` | requested 20 | local iterative KMeans is replaced by DP aggregation |
| FKDC | one noisy per-client count+sum release, DP centers | author SNN density-peaks selection | 1 | original local KMeans+ad hoc Laplace noise is **not** used |
| NN-FC | one noisy per-client count+sum release, DP centers | author SNN neighbor selection | 1 | original local KMeans+ad hoc Laplace noise is **not** used |
| p-FClus | one noisy per-client count+sum release, DP centers | author server weighted KMeans | 1 | client personalization omitted because unprotected private data would leak |
| HF_DBSCAN | one private local count+sum prototype release, then **separately privatized candidate-cell histogram** | author sparse-cell connectivity server in **fixed public 2D projection** | 1 | projection and data-independent DP candidate-domain construction replace author private occupied-cell disclosure; can still collapse to a single/no cluster |

The existing native NumPy / Flower KMeans, Fuzzy CMeans and diagonal GMM methods retain their own previous global trusted-server aggregate-DP implementation, not this author-server proxy path. Three Flower simulations were not run in the audit environment because their optional backend was unavailable.

## Bounds, randomness, accounting and trust

1. Use fixed, public reference centering/scaling (not fitted on confidential X). Clip each transformed **row** to L2 bound `C=4`.
2. For each client and each round, assign its rows to public or previously privatized anchor centers, calculate bounded **counts and sums**, and independently add CSPRNG-calibrated Gaussian noise to their **joint** vector. Conservative replace-one L2 sensitivity: `2 sqrt(1+C²)`. If clients are disjoint and their assignment is fixed independent of private features, releases across clients in a round compose in parallel; adaptive rounds compose sequentially. FKM splits configured ε,δ over all requested rounds; the four one-shot variants use one round.
3. For HF_DBSCAN, split `(ε,δ)` in half: first private representatives, then a Gaussian noisy histogram over a fixed candidate domain derived solely from the previous DP release. That second count-vector query has conservative replacement sensitivity 2. The author server receives **DP-derived cell counts and selected keys**, not the actual private occupied-cell key set. Projection is data-independent, seeded publicly; it is not private-data PCA.
4. Initial anchors are public-seed, independent of private data. DP noise uses OS cryptographic randomness and must **not** be reproduced by user-provided benchmark seed. Multiple selected algorithms and repeated experiments **compose**; no persistent accountant exists.
5. The trusted benchmark evaluator *still evaluates private X and true labels* and can export client distributions, predictions/hashes, raw-data metadata and clipping diagnostics. **THE EXCEL/HISTORY/LOG REPORT IS NOT DP.** Do not publish raw reports on genuinely confidential data. The server might observe unprotected intermediate statistics in centralized simulation: the mechanism is NOT a malicious-server or secure-aggregation defense.

### What is a valid comparison?

Use `Контроль для DP (только clipping)` with **exactly the same DP proxy variant** as the matched control; then `Gaussian DP (агрегаты; Adapted = DP proxy)` with epsilon=20/10/5/1 and delta=1e-5, clip_norm=4, IID, 10 clients, 100% participation, no dropout, 20 requested rounds. For one-shot adapted methods only 1 round is used and **that is correct**. Run ≥10 independent benchmark seeds *and* note independent DP noise for repeated runs with the same seed. Compare ARI/AMI/NMI **and** assigned fraction, number of clusters, degenerate/near-degenerate flags, communication and stability. Failure/near-zero ARI must be included in analyses.

For a clean per-method DP utility comparison, do NOT compare the `Adapted NAME [DP proxy]` row with the original `Adapted NAME` as if only ε changed: the methods differ. The right question is *what quality does each explicitly defined DP-compatible variant achieve under the same privacy budget, dataset and client environment?*

### Dry Bean REAL experiment

Provide official `Dry_Bean_Dataset.arff` (13,611 rows / 16 numeric features / 7 classes). No synthetic substitute is ever accepted as a verified Dry Bean benchmark. On your Windows PC from the unzipped project root:

```powershell
python tools/benchmark_dry_bean_gaussian_aggregate.py --arff "C:\\path\\Dry_Bean_Dataset.arff" --backend all --clip 4 --epsilons 20 10 5 1 --seeds 42 43 44
```

`--backend all` checks the five Adapted DP proxy variants plus three NumPy algorithms. `--backend adapted`, `--backend numpy` and optional `--backend flower` are also supported. The script saves actual metrics, run IDs, model variants, diagnostics, dataset SHA-256, control runs and JSON histories. As with the previous version, Dirichlet/label-limited (private-class-dependent) partitions are rejected in the aggregate-DP training mode because partition formation itself is not DP-accounted; IID and Quantity Skew are allowed.

## Known algorithmic limitations

- **HF_DBSCAN is scientifically problematic in this proxy formulation**. Its sparse density connectivity frequently produces one/no cluster on Wine/Digits despite valid execution. This is a failure of useful clustering, not evidence of a software exception or privacy guarantee failure. Do not rank it with an arbitrarily zero-valued ARI without stating degeneracy and coverage.
- FKM (20 sequential releases) may lose much more quality than one-shot FKDC/NN-FC/p-FClus, because the same total ε is spent over many rounds. A direct comparison must consider rounds as part of the protocol.
- For FKM, author-local iterative KMeans is replaced. For p-FClus, author personalization is omitted. The 2D projection in HF_DBSCAN changes the geometry and cannot be equated to the original 16D Dry Bean density method. These differences cannot be solved by relabeling the output.
- There is no independently audited formal privacy proof of the entire application. The conservative Gaussian calibration covers only the described aggregate releases conditional on the trusted-server threat model; logs/export remain non-private.
