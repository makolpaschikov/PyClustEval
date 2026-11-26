# Project Index

Search this page for a method, task or code name, then follow its coordinates to the owning file or directory overview. Update the entry and its overview when a capability moves, changes name or gains a new entry point.

## Product overview

Start here for supported comparisons, desktop features and installation links.

**Keywords:** getting started; PyClustEval; supported methods

**Coordinates:** [README.md](README.md)

## Set up the environment

Follow the Windows setup instructions for running PyClustEval from a checkout.

**Keywords:** install; virtual environment; Windows; .venv

**Coordinates:** [STARTER.md](STARTER.md)

## Desktop comparison and history tabs

Open the Tkinter entry point to trace dataset selection, comparison controls and the history view.

**Keywords:** GUI; desktop UI; clipboard; ComparisonTab; HistoryTab

**Coordinates:** [pyclusteval_ui.py](pyclusteval_ui.py)

## Packaging and console entry point

Find the distribution metadata, Python requirement, optional dependencies and clustereval command registration.

**Keywords:** setuptools; pip install; flower extra; pytest; clustereval

**Coordinates:** [pyproject.toml](pyproject.toml)

## Framework entry points

Start here to trace a command or find the defaults shared by clustering comparisons.

**Keywords:** clustereval; CLI; benchmark defaults; Python package

**Coordinates:** [clustering_eval/README.md](clustering_eval/README.md)

## Comparison requests and reports

Follow a desktop comparison from the selected algorithms and dataset to individual run reports and saved history.

**Keywords:** ComparisonService; RunRequest; ComparisonReport; execute a prepared job

**Coordinates:** [clustering_eval/application/README.md](clustering_eval/application/README.md)

## Local and federated clustering methods

Look up an algorithm by its registered name and follow it to its implementation or adapter.

**Keywords:** AlgorithmRegistry; scikit-learn; NumPy; fuzzy c-means; diagonal GMM; add an algorithm

**Coordinates:** [clustering_eval/algorithms/README.md](clustering_eval/algorithms/README.md)

## Datasets and client partitions

Find a dataset loader or trace how sample indices are assigned to clients.

**Keywords:** DatasetRegistry; MNIST; Dry Bean; IID; Dirichlet; quantity skew; label-limited

**Coordinates:** [clustering_eval/datasets/README.md](clustering_eval/datasets/README.md)

## Client participation and initialization

Find which clients contribute in each round and how initial centers are selected from participating clients.

**Keywords:** participation schedule; dropout; early stopping; federated initialization

**Coordinates:** [clustering_eval/federated/README.md](clustering_eval/federated/README.md)

## Flower simulations

Trace federated K-Means, fuzzy c-means and diagonal GMM through the Flower backend.

**Keywords:** Flower Simulation; Ray; fed_kmeans_flower; simulation resources

**Coordinates:** [clustering_eval/flower_adapter/README.md](clustering_eval/flower_adapter/README.md)

## Experiment planning and campaign execution

Trace how a YAML plan becomes a set of jobs, how inputs are shared and how a stopped campaign resumes.

**Keywords:** series plan; sequential runner; resume; retry; prepared comparison; source snapshot; legacy grid

**Coordinates:** [clustering_eval/experiments/README.md](clustering_eval/experiments/README.md)

## Clustering scores and diagnostics

Find the scoring functions, client-level diagnostics and summaries across paired seeds.

**Keywords:** ARI; AMI; NMI; silhouette; prediction fingerprint; estimate k; paired statistics

**Coordinates:** [clustering_eval/metrics/README.md](clustering_eval/metrics/README.md)

## Gaussian privacy mechanisms

Trace clipping, calibration and noise application for input perturbation or noisy aggregates.

**Keywords:** Gaussian DP; epsilon; delta; clip norm; local aggregates; DP proxy

**Coordinates:** [clustering_eval/privacy/README.md](clustering_eval/privacy/README.md)

## History, spreadsheets and portable archives

Find where comparison reports are stored, exported to Excel or packaged for later verification.

**Keywords:** HistoryStore; XLSX; metrics.csv; series export; verify archive; import history

**Coordinates:** [clustering_eval/results/README.md](clustering_eval/results/README.md)

## Density sensitivity benchmarks

Trace the radius sweep used to compare DBSCAN and adapted HF_DBSCAN.

**Keywords:** density sensitivity; DBSCAN eps; HF_DBSCAN L; radius candidates

**Coordinates:** [clustering_eval/benchmarks/README.md](clustering_eval/benchmarks/README.md)

## Vendored author implementations

Locate the supplied source for each adapted method and the wrappers that call it.

**Keywords:** Adapted FKM; HF_DBSCAN; FKDC; NN-FC; p-FClus; provenance

**Coordinates:** [clustering_eval/third_party/README.md](clustering_eval/third_party/README.md)

## Experiment configurations

Choose a YAML example for a legacy grid, a campaign pilot or a backend profile.

**Keywords:** example.yaml; pyclusteval.plan.v1; Iris pilot; stopping profile

**Coordinates:** [configs/README.md](configs/README.md)

## Regression tests

Find tests for comparison behavior, scientific inputs, campaign recovery and exported results.

**Keywords:** pytest; shared partition; regression tests; archive integrity

**Coordinates:** [tests/README.md](tests/README.md)

## Benchmark and dataset utilities

Find command-line scripts for fetching datasets, generating benchmark tables and examining campaign measurements.

**Keywords:** fetch MNIST; fetch Dry Bean; compatibility matrix; campaign profile; rebuild validation

**Coordinates:** [tools/README.md](tools/README.md)

## Research protocols and operator guides

Find the protocol, operating instructions or adaptation notes behind a benchmark.

**Keywords:** architecture; adaptation; campaign guide; benchmark fairness; measurement diagnostics

**Coordinates:** [docs/README.md](docs/README.md)

## Windows dependency profiles

Locate pinned dependencies for the CPython 3.12 Windows environments.

**Keywords:** dependency pins; Windows x64; Flower environment; CPython 3.12.10

**Coordinates:** [constraints/README.md](constraints/README.md)

## Saved validation results

Find archived observations from the real-data and Gaussian privacy evaluations.

**Keywords:** audit evidence; empirical rows; matched probe; Gaussian DP validation

**Coordinates:** [validation/README.md](validation/README.md)

## Agent roles and project workflows

Use the harness map to find role instructions, project rules and verification workflows.

**Keywords:** agent harness; AGENTS.md; role skills; Git workflow

**Coordinates:** [harness/README.md](harness/README.md)
