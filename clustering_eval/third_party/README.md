# Vendored author implementations (clustering_eval/third_party)

## Summary

Locate the supplied source for each adapted method and the wrappers that call it.

## References

- [../algorithms/author_adapters.py](../algorithms/author_adapters.py) — PyClustEval entry points that call the author implementations.
- [../../docs/ADAPTATION.md](../../docs/ADAPTATION.md) — Source provenance, executed code and adaptations for each method.
- [fedkmeans/fed_kmeans.py](fedkmeans/fed_kmeans.py) — FKM client and server implementation. See the [upstream README](fedkmeans/README.md).
- [fdbscan/fd_dbscan.py](fdbscan/fd_dbscan.py) — Horizontal federated DBSCAN kernel. See its [source record](fdbscan/SOURCE.md).
- [fkdc/fkdc_main.py](fkdc/fkdc_main.py) — FKDC implementation. See its [source record](fkdc/SOURCE.md).
- [nnfc/nnfc.py](nnfc/nnfc.py) — NN-FC implementation. See its [source record](nnfc/SOURCE.md).
- [pfclus/p-FClus.py](pfclus/p-FClus.py) — p-FClus implementation. See the [supplied README](pfclus/README.md).
