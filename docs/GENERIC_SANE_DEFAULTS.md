# Generic sane defaults (v2)

This profile is intentionally **dataset-agnostic**.  No parameter below was
chosen by maximizing ARI/NMI on Iris, Wine, Digits, Dry Bean, MNIST, or any
other PyClustEval dataset.

| Algorithm | Generic configuration | Rationale |
|---|---|---|
| KMeans | `init=k-means++`, `n_init=10`, `max_iter=300`, `tol=1e-4` | Stable/common KMeans configuration; explicit 10 restarts avoids version-dependent `n_init='auto'` behavior. |
| DBSCAN | `eps=median k-distance` (`q=0.50`), `min_samples=5`, Euclidean | Label-free adaptive radius computed after StandardScaler. The rule is fixed across datasets and never uses `y_true`. |
| GMM | `covariance_type=full`, `reg_covar=1e-6`, `n_init=1`, `init_params=kmeans`; common benchmark `max_iter=300`, `tol=1e-4` | Standard sklearn structure/initialization with the same generous convergence budget used by the benchmark harness. |
| Agglomerative | Ward linkage, Euclidean | sklearn/default Ward hierarchy. |
| Fed KMeans (NumPy/Flower) | common round budget, `tol=1e-4` | Round budget is an experimental communication control, not dataset tuning. |
| Fed Fuzzy C-Means | common round budget, `m=2.0`, `tol=1e-4` | Classical FCM fuzzifier. |
| Fed diagonal GMM | common round budget, `reg_covar=1e-6`, `tol=1e-4` | Numerical regularization only. |
| Adapted FKM | `iter_local=1`, weighted aggregation, drop empty clusters, `k-means++` | Author configuration. |
| Adapted HF_DBSCAN | MinMax input, `L=0.15`, `MIN_POINTS=4` | `MIN_POINTS=4` is author default; `L=0.15` is PyClustEval's documented generic normalized-space setting, not a dataset-tuned value. |
| Adapted FKDC | fixed constants from vendored author source | Kept unchanged to preserve author implementation. |
| Adapted NN-FC | fixed constants from vendored author source | Kept unchanged to preserve author implementation. |
| Adapted p-FClus | `max_iters=10` | Author default. |

## Important limitation

There is no universal good fixed radius for DBSCAN-family methods.  Therefore
DBSCAN v2 no longer uses a cross-dataset numeric `eps`.  It computes one
pre-registered label-free radius from the input geometry: the 0.50 quantile
(median) of distances to the `min_samples`-th non-self neighbor after the
algorithm's StandardScaler preprocessing.  `y_true`, ARI and NMI are not used.

HF_DBSCAN remains on its author-preserving normalized-space baseline `L=0.15`;
its cell-edge parameter is not semantically identical to sklearn DBSCAN `eps`.
Neither rule is a claim of per-dataset optimality, especially on high-dimensional
data such as MNIST.
