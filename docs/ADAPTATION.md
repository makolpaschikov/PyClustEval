# Author implementation adaptations

This build is intended to benchmark the **specific implementations supplied by the user**, not reimplementations with equivalent scikit-learn estimators. Author source files are vendored under `clustering_eval/third_party/`.

## Adapted FKM

- Source: https://github.com/swiergarst/fedKMeans
- Commit embedded by the supplied ZIP: `b1f39cf481721da232f9426bc35feb2b79cf18d1`
- Executed author code: `fed_kmeans.py` → `client_FKM`, `server_FKM`.
- Framework adaptation: author file is unchanged. PyClustEval supplies client arrays instead of `load_data`, sets validation-only client labels to `None`, executes the same aggregate/broadcast/local-update loop in process, and derives final point labels from the resulting global centers.
- The source imports `common`; the adapter provides an empty `common` module because the two executed classes do not use the repository's dataset/plotting helpers.

## Adapted HF_DBSCAN

- Source: https://github.com/GM862001/F_DBSCAN
- Commit: `6223c2d9a0f893f5b92699afd918775c2e09adf4`
- Executed author code: `HF_DBSCAN/fd_dbscan.py` → `FDBSCAN_Client`, `FDBSCAN_Server`.
- Framework adaptation: Flask/HTTP transport and ARFF/StratifiedKFold partition preparation are replaced by direct method calls on PyClustEval partitions. The clustering kernel is the unmodified author source.
- **Author preprocessing is retained:** `MinMaxScaler()` from `HF_DBSCAN/main_client.py` is applied before the horizontal sample partition is consumed by the author client kernel. The old global `StandardScaler` path caused empty dense-cell maps and ARI≈0.
- `MIN_POINTS=4` remains the author default. The author repository uses `L=0.03` specifically for `banana.arff`; PyClustEval exposes `L` in the UI and uses `0.15` as a generic benchmark default for its built-in normalized datasets. Set `L=0.03` to reproduce the author banana configuration.

## Adapted FKDC

- Source: https://github.com/mlyizhang/FKDC
- Commit: `37f10faa27fbc6bc0335882909cf744b8a2c237e`
- Executed author code: `federatedclustering/FKDC/utils.py` → `results`, `SNN`. `utils_original.txt` preserves the exact uploaded file; executable `utils.py` changes the scalar `min(a,b)` call to NumPy `minimum(a,b)` because `from numpy import *` shadows Python `min` and breaks under current NumPy.
- Framework adaptation: `load_dataset` is temporarily replaced with an in-memory PyClustEval dataset dictionary. The author function only returns validation metrics, so its metric function is temporarily replaced to capture its already-computed prediction array. No clustering step is replaced.
- `results()` derives the final cluster count from `true_label`; the adapter therefore supplies synthetic labels containing exactly the benchmark-requested `k` distinct values. These synthetic labels carry **no class assignment information**, only the number of clusters.
- The original code performs final assignment over `full_data` centrally; this behavior is retained and called out in `model_state`.

## Adapted NN-FC

- Source: https://github.com/mlyizhang/nnfc
- Commit: `404af20bf4abd524dd1c5bc0968e0e1a2491f828`
- Executed author code: `codes/utils.py` → `nnfc`, `SNN`.
- The supplied author `utils.py` does not compile because line 209 mixes tabs and spaces. `utils_original.txt` preserves the exact source; executable `utils.py` fixes that indentation and changes the same shadowed scalar `min(a,b)` call in `SNN` to NumPy `minimum(a,b)`. Both are compatibility fixes; the equations/control flow are unchanged.
- Input/label capture is adapted using the same narrow seams as FKDC; the clustering/noise/SNN logic is otherwise author code.
- The original code also derives `cnum` from `true_label` and assigns `full_data` centrally; both behaviors are retained.

## Cluster-count benchmark condition

The current `ComparisonService` derives the default `k`/`n_clusters` from the dataset labels. This is an **oracle-k benchmark condition**. For FKDC and NN-FC this mirrors the supplied author functions, which themselves derive `cnum` from `true_label`; for FKM it supplies `k_global`. F_DBSCAN does not use `k`. The adapters never receive the per-sample ground-truth assignments, only the requested number of clusters where the author implementation requires it.

## Reproducibility changes

The original repositories often rely on implicit global random state. PyClustEval seeds NumPy around each adapted run and restores the previous state afterward. This is a benchmark-harness change, not an algorithmic replacement.

## Communication metric

- F_DBSCAN: estimated from the same JSON payload shapes used by the author's HTTP implementation.
- FKM: NumPy payload bytes for initial/local centers, counts, and global-center broadcasts.
- FKDC/NN-FC: representative-center upstream payload only. Their provided experiment functions perform final assignment on a centrally available `full_data`, so there is no faithful client-return payload in those functions to count.

## Licensing

No `LICENSE`, `COPYING`, or `NOTICE` file was present in any of the four supplied repository archives. The sources are included here because they were explicitly supplied for adaptation; redistribution rights should be verified before publishing this combined project.
