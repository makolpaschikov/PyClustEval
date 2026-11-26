# PyClustEval

PyClustEval compares local and federated clustering algorithms on the same dataset. Use the Tkinter desktop app to compare methods interactively, inspect client partitions and export results to Excel. Use the `clustereval series` CLI to run a campaign from a YAML plan, resume interrupted work and verify a portable archive.

## Install and run

The package requires Python 3.12 or later. The tested Windows x64 setup uses CPython 3.12.10 with Tcl/Tk, a project-local virtual environment and pinned dependencies. Follow the installation guide to create or check the environment and install the project. Flower simulations use a separate environment with pinned Flower and Ray versions. [Windows setup guide](STARTER.md) · [Tested backend profiles](docs/CAMPAIGN_PROFILE.md)

From PowerShell in the repository root, run the following command to launch the desktop app.

```powershell
& '.\.venv\Scripts\python.exe' '.\pyclusteval_ui.py'
```

### Run a campaign

To try the bundled Iris pilot, first validate the plan. The second command starts the jobs and writes to the plan's output directory, which must be new or empty. The Windows runner executes one job at a time in a fresh process.

```powershell
$cli = '.\.venv\Scripts\clustereval.exe'
$plan = '.\configs\series\pilot.yaml'
& $cli series validate $plan --json
& $cli series run $plan --json
```

For this pilot, `series status` and `series resume` take the campaign directory `.\results\iris-pilot`. Use `series retry` to retry jobs by failure status and optionally by job ID. Use `series export` on the campaign directory and `series verify` on the resulting archive directory, including after moving it. [Iris pilot plan](configs/series/pilot.yaml) · [Plan format](docs/CAMPAIGN_PLANS.md) · [Run and recovery commands](docs/CAMPAIGN_RUNNER.md) · [Archive export and verification](docs/CAMPAIGN_EXPORT.md)

## Algorithms and datasets

| Execution mode | Methods |
| --- | --- |
| Local (scikit-learn) | K-Means, DBSCAN, Gaussian mixture model (GMM), agglomerative clustering |
| Federated (NumPy or Flower Simulation) | K-Means, fuzzy c-means, diagonal GMM |
| Federated (adapted author implementations) | `Adapted FKM`, `Adapted HF_DBSCAN`, `Adapted FKDC`, `Adapted NN-FC`, `Adapted p-FClus` |

The adapters use code from swiergarst/fedKMeans, the horizontal implementation of GM862001/F_DBSCAN, mlyizhang/FKDC, mlyizhang/nnfc and the supplied p-FClus archive (arXiv:2407.04302), respectively. The adaptation notes identify the source revisions, executed files and changes for each method. [Adaptation notes](docs/ADAPTATION.md)

Iris, Wine, Digits and synthetic Blobs are available locally. Dry Bean and MNIST are downloaded on first use and cached under `~/.cache/pyclusteval/datasets/`. Set `PYCLUSTEVAL_DATA_DIR` to choose a different cache root.

| Dataset ID | Data used by the desktop app |
| --- | --- |
| `dry_bean` | All 13,611 samples, 16 numeric features and 7 classes from UCI Dry Bean (dataset 602, DOI `10.24432/C50S4B`, CC BY 4.0). The loader extracts `dry_bean/Dry_Bean_Dataset.arff` from the official ZIP. |
| `mnist_10k` | A deterministic, stratified sample of 10,000 images from the full MNIST corpus, using subset seed 42. |
| `mnist_full` | All 70,000 images, with 784 features (28 × 28 pixels) and 10 classes. |

Both MNIST profiles use the same four compressed IDX files under `mnist/`. The loader converts pixel values from integers in 0–255 to `float32` in [0, 1] before algorithm-specific preprocessing. History and Excel preserve the profile name. Allow for the cost of the full datasets when choosing methods, particularly FKDC and NN-FC on Dry Bean and high-dimensional density methods on MNIST. [Dataset loaders](clustering_eval/datasets/README.md)

## Compare algorithms in the desktop app

Choose the local or federated tab, select a dataset and at least two algorithms, then start the comparison. The methods share the experiment seed and applicable benchmark controls, including the requested number of clusters, round budget, convergence tolerance and local iteration limit (default 300). Each result records its effective parameters and diagnostics. The Python API also accepts per-algorithm overrides through `RunRequest.algorithm_params_by_name`. [Benchmark controls](docs/BENCHMARK_FAIRNESS.md) · [Default parameters by algorithm](docs/GENERIC_SANE_DEFAULTS.md)

**Number of clusters.** For methods that require `k`, the desktop app offers known-k and estimated-k. In an ordinary labeled benchmark, known-k uses the number of ground-truth classes and records that choice as oracle-k. Estimated-k evaluates candidate values using K-Means and the silhouette score without class labels. The aggregate privacy modes require a public known-k.

**DBSCAN tuning.** By default, local DBSCAN uses `min_samples=5` and derives its radius from the median distance to the fifth nearest neighbor, counting the point itself. Optional unlabeled tuning evaluates `min_samples` values 5 and 10 with several candidate radii and scores viable candidates by silhouette and assigned-sample coverage. Adapted HF_DBSCAN has its own defaults of `MIN_POINTS=4` and `L=0.15` after MinMax scaling.

### Client partitions and participation

A federated comparison constructs one partition and reuses the same sample indices for every selected algorithm, including methods with different feature preprocessing. By default each client needs at least three samples to accommodate NN-FC. The federated tab shows the realized sample and class counts before the methods run, and the saved report includes the partition fingerprint.

| Partition | Effect |
| --- | --- |
| IID | Random assignment with approximately equal client sizes. |
| Dirichlet | The concentration parameter `alpha` controls how unevenly classes are distributed across clients. |
| Quantity skew | Client sizes differ. With five clients the target shares are 10%, 15%, 20%, 25% and 30%. |
| Label-limited | Each client receives samples from at most two classes by default. |

The experiment seed determines one participation schedule for all methods. Each round selects the requested fraction of clients, rounded up, then applies the dropout probability to each selected client. If all selected clients drop out, the scheduler retains one of them. A round with a single selected client therefore always receives its update. The UI and Excel report show selected, successful and dropped client IDs.

Federated K-Means, fuzzy c-means, diagonal GMM and Adapted FKM consume the schedule round by round. The one-shot HF_DBSCAN, FKDC, NN-FC and p-FClus adapters use the first round. Flower clients apply the schedule using their partition IDs. Inactive clients send no-op updates, and the reported byte count measures logical benchmark payloads. [Participation and dropout implementation](clustering_eval/federated/README.md)

### Privacy modes

| Mode | What happens during training |
| --- | --- |
| `none` | Runs the selected methods with their usual preprocessing. |
| `gaussian_dp` (input perturbation) | Clips each raw feature vector to the L2 bound and adds calibrated Gaussian noise before fitting any data-dependent scaler. All selected methods and rounds reuse one perturbed matrix. Under replace-one record adjacency, the L2 sensitivity is twice the clip norm. |
| `gaussian_dp_aggregate` | Scales features using a fixed public reference, clips each row and applies Gaussian noise to bounded statistics used for model updates. Each method has a privacy budget for its rounds. The budgets of separate methods compose. Supported partitions are IID and quantity skew. |
| `public_clipped_control` | Uses the same public scaling, clipping and model variant as the aggregate experiment, with zero noise. This control carries no privacy guarantee. |

Record the mode, epsilon, delta and clip norm when reporting a DP run. For input perturbation, a clip norm of 1 can strongly clip Dry Bean rows because their raw feature scales differ, and MNIST rows even after pixel normalization. Interpret the clip norm in the feature space used by the chosen mechanism.

In both aggregate modes, results for the five adapted methods carry the suffix `[DP proxy]`. These variants replace local updates with bounded statistics and retain the original server computation where feasible. Adapted FKM uses the requested round budget, while the four one-shot variants use one round. Pair each noisy variant with its matching clipping control. [Aggregate mechanism](docs/GAUSSIAN_AGGREGATE_DP.md) · [Accounting and changes by author method](docs/GAUSSIAN_AUTHOR_DP_V4.md)

The full report is for a trusted evaluator. Ground-truth labels, partition metadata and evaluation on original data remain outside the privacy guarantee. The aggregate mechanism assumes a trusted server, and the project does not implement secure aggregation. Repeated releases on the same records compose across experiments. PyClustEval has no cross-experiment privacy accountant.

## Results, history and export

The app reports adjusted Rand index (ARI), adjusted mutual information (AMI), normalized mutual information (NMI), silhouette, Davies–Bouldin and Calinski–Harabasz scores. Diagnostics include client-level metrics, prediction hashes, active-data fingerprints and flags for degenerate or near-degenerate clustering. [Measurement and evaluation space](docs/MEASUREMENT_DIAGNOSTICS.md)

Each completed desktop comparison creates a history directory. Runs started in the same second receive suffixes such as `_2` and `_3`.

```text
history/
└── YYYY-MM-DD_HH-MM-SS/
    ├── report.json
    ├── results.csv
    └── execution.log
```

Export a completed comparison to Excel for full-precision results, effective configuration, diagnostics and the execution log. Federated reports also include the client partition and participation schedule. For either Gaussian mechanism, the Privacy sheet records the calibration and the scope of the release. The Results sheet stores ARI, AMI and NMI as numeric values in columns F, G and H when available. [AMI in exports and saved history](docs/FIX_AMI_EXPORT_2026-10-17.md)

The app saves the workbook before opening it in the system's default spreadsheet viewer. Either comparison tab lets you disable automatic opening. Export works without Excel installed, and the saved file remains available if the viewer fails to open. To copy the displayed, rounded values with their headers as tab-separated text, use the copy button on the results or history tab. In a results table, Ctrl+C copies selected rows or all rows when the selection is empty. Ctrl+A selects all rows.

## Tests and benchmark evidence

Run the tests from the repository root using the development environment. Tests that execute native Flower simulations require the separate Flower/Ray environment.

```powershell
& '.\.venv\Scripts\python.exe' -m pytest
```

The saved compatibility matrix covers Iris, Wine, Blobs and Digits without Flower. Its 80 cases comprise 73 normal, 6 degenerate and 1 near-degenerate outcome, with zero execution errors. The density sensitivity sweep compares five unlabeled radius candidates per method and records ARI and NMI for evaluation. At the default sweep setting, DBSCAN and HF_DBSCAN both use a neighborhood threshold of 4. Changing `--density-min-samples` changes the candidate radius calculation for both methods and the DBSCAN threshold. The HF_DBSCAN adapter retains its own `min_points=4`. [Saved compatibility matrix](docs/compatibility_matrix.csv) · [Saved density sweep](docs/density_sensitivity.csv)

Run these commands to write fresh tables to the current directory.

```powershell
& '.\.venv\Scripts\python.exe' '.\tools\compatibility_matrix.py' --output '.\compatibility_matrix.csv'
& '.\.venv\Scripts\python.exe' '.\tools\density_sensitivity.py' --output '.\density_sensitivity.csv'
```

The October 2026 protocol audit reports Iris, Wine and Digits experiments, including a six-seed Digits stress test, failures, privacy limitations and reproduction commands. Its empirical coverage excludes MNIST, UCI Dry Bean and native Flower. The Windows campaign profile separately documents the Iris pilots and Dry Bean measurements. [Protocol audit](docs/PROTOCOL_V2_REAL_WORLD_AUDIT_2026-10-14.md) · [Windows campaign profile](docs/CAMPAIGN_PROFILE.md)

## Project map

The desktop app creates a typed `RunRequest`, runs `ComparisonService` in a worker thread and displays a `ComparisonReport`. Use the project index to find the owning code, configuration and tests for a capability. [Project index](INDEX.md) · [Architecture](docs/PyClustEval_TECHNICAL_ARCHITECTURE.md) · [Editable component diagram](docs/PyClustEval_UI_Component_Interaction.drawio)
