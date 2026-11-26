# Client participation and initialization (clustering_eval/federated)

## Summary

Find which clients contribute in each round and how initial centers are selected from participating clients.

## References

- [environment.py](environment.py) — Selection and dropout schedules, successful clients, round budgets and early stopping.
- [initialization.py](initialization.py) — Priority sampling of centers and federated variance calculation.
- [../datasets/partitioning.py](../datasets/partitioning.py) — Sample assignments used by those client schedules.
