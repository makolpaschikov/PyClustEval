FILES TO COPY INTO THE PROJECT ROOT

clustering_eval/algorithms/federated_extra.py
clustering_eval/flower_adapter/federated_extra_flower.py
clustering_eval/algorithms/registry.py
pyclusteval_ui.py

The patch registers six federated choices:
- fed_kmeans_numpy
- fed_kmeans_flower
- fed_fuzzy_cmeans_numpy
- fed_fuzzy_cmeans_flower
- fed_gmm_diag_numpy
- fed_gmm_diag_flower

Run:
    python pyclusteval_ui.py

Flower variants require:
    python -m pip install "flwr[simulation]"
