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
- Framework adaptation: Flask/HTTP transport and ARFF/StratifiedKFold partition preparation are replaced by direct method calls on PyClustEval partitions. The executable author kernel has two exact-semantics scalability patches: occupied grid cells are counted in a sparse dictionary instead of an exponentially sized dense tensor, and the same axial neighbor set is generated directly in `2*d` operations instead of filtering a `3**d` Cartesian product. The untouched uploaded kernel is preserved as `fd_dbscan_original.py`, and low-dimensional equivalence is regression-tested.
- **Author preprocessing is retained:** `MinMaxScaler()` from `HF_DBSCAN/main_client.py` is applied before the horizontal sample partition is consumed by the author client kernel. The old global `StandardScaler` path caused empty dense-cell maps and ARI≈0.
- `MIN_POINTS=4` remains the author default. The author repository uses `L=0.03` specifically for `banana.arff`; PyClustEval exposes `L` in the UI and uses `0.15` as a generic benchmark default for its built-in normalized datasets. Set `L=0.03` to reproduce the author banana configuration.

## Adapted FKDC

- Source: https://github.com/mlyizhang/FKDC
- Commit: `37f10faa27fbc6bc0335882909cf744b8a2c237e`
- Executed author code: `federatedclustering/FKDC/utils.py` → `results`, `SNN`. `utils_original.txt` preserves the exact uploaded file; executable `utils.py` changes the scalar `min(a,b)` call to NumPy `minimum(a,b)` because `from numpy import *` shadows Python `min`, and initializes the SNN shared-neighbor index buffer with `-1` instead of uninitialized memory so unused entries cannot create false matches / `0/0` warnings.
- Framework adaptation: `load_dataset` is temporarily replaced with an in-memory PyClustEval dataset dictionary. The author function only returns validation metrics, so its metric function is temporarily replaced to capture its already-computed prediction array. No clustering step is replaced.
- `results()` derives the final cluster count from `true_label`; the adapter therefore supplies synthetic labels containing exactly the benchmark-requested `k` distinct values. These synthetic labels carry **no class assignment information**, only the number of clusters.
- The original code performs final assignment over `full_data` centrally; this behavior is retained and called out in `model_state`.

## Adapted NN-FC

- Source: https://github.com/mlyizhang/nnfc
- Commit: `404af20bf4abd524dd1c5bc0968e0e1a2491f828`
- Executed author code: `codes/utils.py` → `nnfc`, `SNN`.
- The supplied author `utils.py` does not compile because line 209 mixes tabs and spaces. `utils_original.txt` preserves the exact source; executable `utils.py` fixes that indentation, changes the same shadowed scalar `min(a,b)` call in `SNN` to NumPy `minimum(a,b)`, and initializes unused shared-neighbor indices with sentinel `-1` rather than leaving them uninitialized. It also replaces the all-pairs Python loop used to compute `max(max(i/j, j/i))` over strictly positive folded-uniform values with the exact identity `max(arr) / min(arr)`, removing an otherwise pathological high-dimensional runtime. These are compatibility/performance fixes; valid SNN entries and the computed max-ratio quantity are unchanged.
- Input/label capture is adapted using the same narrow seams as FKDC; the clustering/noise/SNN logic is otherwise author code.
- The original code also derives `cnum` from `true_label` and assigns `full_data` centrally; both behaviors are retained.


## Adapted p-FClus

- Source archive supplied by the user: `p-FClus-main.zip`.
- Commit embedded in the ZIP metadata: `3fd7c09d98fb23c9807931c6363ad1181eb283f1`.
- Paper: *Fair Federated Data Clustering through Personalization: Bridging the Gap between Diverse Data Distributions* (arXiv:2407.04302).
- Executed author code: `main_algo/p-FClus.py` → `sgd_scipy`, `pFClus`.
- The vendored `p-FClus.py` is byte-for-byte identical to the uploaded source. The script cannot be imported normally because it immediately reads `adult.csv` and starts the experiment at module import time. The adapter therefore parses the unchanged script and executes only the two function definitions; their function bodies are not rewritten.
- Client initialization is the author's `sgd_scipy`: each client runs the supplied KMeans-based local clustering and uploads only local centers.
- Server execution reproduces the author's top-level lines: concatenate all local centers, run `KMeans(n_clusters=k)`, and broadcast the resulting global centers.
- Client personalization calls the author's `pFClus()` directly. The original function reads the global variable `total_classes`; the adapter injects benchmark `k` into that same global rather than changing the function.
- The author function aliases `centroids = global_centers` and mutates the shared center array in place. Because the supplied experiment calls clients sequentially with the same `final_centers` object, personalization is order-dependent. PyClustEval intentionally retains this behavior instead of silently correcting it.
- The author script applies no scaler to its prepared numeric inputs, so the adapter declares `input_preprocessing = "raw"`.
- PyClustEval additionally records the author's per-client mean clustering cost and its mean/std/max, because fairness across client costs is a central output of the supplied experiment.

## Cluster-count and fairness benchmark condition

`ComparisonService` now has an explicit shared benchmark profile. `target_clusters` is passed as the same `k`/`n_clusters` to every implementation that consumes a cluster count. If `target_clusters` is left empty, PyClustEval derives it from the number of distinct dataset labels and records `cluster_count_source="ground_truth_oracle"`; per-sample ground-truth assignments are still not passed to the clustering implementations. The UI exposes `K`, round budget and local max-iteration budget explicitly.

Common settings (seed, partition, client count, minimum client size, round budget, tolerance and compatible local iteration budget) are shared. Algorithm-specific parameters and author-required preprocessing remain separate so that equalization does not silently change an implementation. See `BENCHMARK_FAIRNESS.md`.

## Reproducibility changes

The original repositories often rely on implicit global random state. PyClustEval seeds NumPy around each adapted run and restores the previous state afterward. This is a benchmark-harness change, not an algorithmic replacement.

## Communication metric

- F_DBSCAN: estimated from the same JSON payload shapes used by the author's HTTP implementation.
- FKM: NumPy payload bytes for initial/local centers, counts, and global-center broadcasts.
- p-FClus: uploaded local-center arrays plus one global-center broadcast to every client.
- FKDC/NN-FC: representative-center upstream payload only. Their provided experiment functions perform final assignment on a centrally available `full_data`, so there is no faithful client-return payload in those functions to count.

## Licensing

No `LICENSE`, `COPYING`, or `NOTICE` file was present in any of the five supplied clustering repository archives. The sources are included here because they were explicitly supplied for adaptation; redistribution rights should be verified before publishing this combined project.
