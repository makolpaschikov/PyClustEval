# Datasets and client partitions (clustering_eval/datasets)

## Summary

Find a dataset loader or trace how sample indices are assigned to clients.

## References

- [registry.py](registry.py) — Dataset names and loader registration, including Iris, Wine, Digits and Blobs.
- [base.py](base.py) — Fields of the Dataset object returned by loaders.
- [mnist.py](mnist.py) — MNIST download, caching and selection of the 10k or full dataset.
- [dry_bean.py](dry_bean.py) — UCI Dry Bean download, cache and parsing.
- [partitioning.py](partitioning.py) — Client partition modes, class counts and partition fingerprints.
