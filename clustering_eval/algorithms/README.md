# Local and federated clustering methods (clustering_eval/algorithms)

## Summary

Look up an algorithm by its registered name and follow it to its implementation or adapter.

## References

- [registry.py](registry.py) — Registered method names and their implementations.
- [base.py](base.py) — ClusteringAlgorithm interface and AlgorithmResult fields.
- [sklearn_algorithms.py](sklearn_algorithms.py) — Local K-Means, DBSCAN, Gaussian mixture and agglomerative clustering.
- [fed_kmeans_numpy.py](fed_kmeans_numpy.py) — NumPy federated K-Means.
- [federated_extra.py](federated_extra.py) — NumPy federated fuzzy c-means and diagonal Gaussian mixtures.
- [author_adapters.py](author_adapters.py) — Framework wrappers for the five methods in the [author source collection](../third_party/README.md).
