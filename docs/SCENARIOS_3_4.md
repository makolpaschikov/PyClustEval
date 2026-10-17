# Scenario 3/4 benchmark semantics

## Scenario 3 — Partial Participation and Dropout

`RunRequest.participation_rate` controls how many clients are selected each round.
The selected count is `ceil(num_clients * participation_rate)`, with at least one
client. `RunRequest.dropout_rate` is applied independently after selection. If an
entire round would drop, the benchmark deterministically retains one successful
client so aggregation is defined.

The complete schedule is generated once from the experiment seed and stored in
`PartitionReport.round_schedule`. Every federated algorithm, including the
Flower Simulation variants, receives that exact logical schedule.

### Iterative algorithms

NumPy Fed K-Means, Fuzzy C-Means, diagonal GMM, and Adapted FKM consume the
schedule round by round. Adapted FKM retains the author's original iterative
flow; inactive clients keep their most recent local author state until they
participate again.

### One-shot author algorithms

HF_DBSCAN, FKDC, NN-FC, and p-FClus retain one communication stage. The first
schedule entry is interpreted as one-shot client availability. This is an
external benchmark wrapper and does not claim that the original author algorithm
was iterative.

### Flower

Flower's strategy-side `ClientProxy` does not expose the dataset partition ID,
so selecting proxies directly would not guarantee that independent algorithms
receive the same client identities. PyClustEval therefore keeps all Flower
supernodes alive and enforces the shared schedule inside each client, where
`context.node_config["partition-id"]` is stable. Non-selected and dropped clients
return a no-op update; only successful client updates enter aggregation.

`communication_bytes` for these runs is the **logical benchmark payload cost**:
server payloads are counted for selected clients and client payloads for
successful clients. The Flower simulator still dispatches the no-op calls, so
this metric is not a packet-level measurement of the simulator's physical
transport overhead.

## Scenario 4 — Gaussian DP

Gaussian DP is implemented as record-level feature input perturbation shared by
all algorithms in one comparison.

1. Each raw feature vector is L2-clipped to `C = dp_clip_norm`.
2. Replace-one sensitivity is bounded by `2C`.
3. `sigma` is calibrated with the analytic Gaussian mechanism for the requested
   `(epsilon, delta)`.
4. Isotropic Gaussian noise is sampled once in raw feature space.
5. The same privatized matrix is passed to every algorithm; each algorithm then
   applies its documented preprocessing.

No data-dependent global normalization is estimated before the DP mechanism.
Communication rounds and multiple algorithms in the same experiment are
post-processing of the same DP release. Separate independent experiments compose
privacy loss and are not tracked by a global accountant.

The mechanism protects `X` only. Ground-truth labels, oracle-k, label-based
partition creation, and exported partition class counts are evaluation metadata
and are not DP-protected.

## DP randomness security note (audit patch 2026-10-14)

Private noise now draws from OS CSPRNG entropy; the public run seed affects
other benchmark elements but does not reproduce DP noise. The old predictable
privacy_seed mechanism was unsafe for external DP claims.

The end-to-end report itself is **NOT** DP: clean X statistics, label-aware
partition information, raw-data-derived hashes and evaluation metrics are
publicly recorded. Never disclose benchmark reports as if they have an
`(epsilon, delta)` DP guarantee.
