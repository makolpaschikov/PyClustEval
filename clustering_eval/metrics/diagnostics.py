from __future__ import annotations

import hashlib
import json
from typing import Any

import numpy as np
from sklearn.metrics import adjusted_rand_score, normalized_mutual_info_score


def array_fingerprint(value: np.ndarray, *, length: int = 16) -> str:
    array = np.ascontiguousarray(np.asarray(value))
    digest = hashlib.sha256()
    digest.update(str(array.dtype).encode("ascii"))
    digest.update(json.dumps(list(array.shape), separators=(",", ":")).encode("ascii"))
    digest.update(array.tobytes(order="C"))
    return digest.hexdigest()[:length]


def canonicalize_cluster_labels(labels: np.ndarray) -> np.ndarray:
    """Canonicalize cluster ids by first occurrence; keep DBSCAN noise at -1."""
    labels = np.asarray(labels)
    mapping: dict[Any, int] = {}
    next_id = 0
    out = np.empty(len(labels), dtype=np.int64)
    for index, raw in enumerate(labels.tolist()):
        if int(raw) == -1:
            out[index] = -1
            continue
        if raw not in mapping:
            mapping[raw] = next_id
            next_id += 1
        out[index] = mapping[raw]
    return out


def prediction_fingerprint(labels: np.ndarray) -> str:
    """Hash a clustering assignment modulo arbitrary cluster-id permutation."""
    return array_fingerprint(canonicalize_cluster_labels(labels))


def active_data_diagnostics(
    partition: list[np.ndarray],
    schedule: list[dict[str, Any]],
) -> dict[str, Any]:
    """Describe which sample ids actually contribute in every benchmark round."""
    round_rows: list[dict[str, Any]] = []
    for index, entry in enumerate(schedule):
        successful = [int(v) for v in entry.get("successful_clients", [])]
        if successful:
            active = np.unique(np.concatenate([
                np.asarray(partition[client_id], dtype=np.int64)
                for client_id in successful
            ]))
        else:
            active = np.asarray([], dtype=np.int64)
        round_rows.append({
            "round": int(entry.get("round", index + 1)),
            "active_sample_count": int(len(active)),
            "active_data_hash": array_fingerprint(active),
        })
    serialized = json.dumps(round_rows, sort_keys=True, separators=(",", ":"))
    return {
        "rounds": round_rows,
        "active_data_fingerprint": hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:16],
    }


def client_external_metrics(
    y_true: np.ndarray | None,
    y_pred: np.ndarray,
    partition: list[np.ndarray] | None,
) -> dict[str, Any]:
    """Compute per-client and aggregate ARI/NMI for diagnostic non-IID analysis."""
    if y_true is None or partition is None:
        return {}
    y_true = np.asarray(y_true)
    y_pred = np.asarray(y_pred)
    rows: list[dict[str, Any]] = []
    for client_id, raw_indices in enumerate(partition):
        indices = np.asarray(raw_indices, dtype=int)
        if len(indices) == 0:
            continue
        yt = y_true[indices]
        yp = y_pred[indices]
        ari = float(adjusted_rand_score(yt, yp))
        nmi = float(normalized_mutual_info_score(yt, yp))
        rows.append({
            "client_id": int(client_id),
            "n_samples": int(len(indices)),
            "n_true_classes": int(len(np.unique(yt))),
            "n_pred_clusters": int(len(set(np.unique(yp).tolist()) - {-1})),
            "ari": ari,
            "nmi": nmi,
        })

    def aggregate(key: str) -> dict[str, float] | None:
        if not rows:
            return None
        values = np.asarray([float(row[key]) for row in rows], dtype=float)
        weights = np.asarray([int(row["n_samples"]) for row in rows], dtype=float)
        return {
            "mean": float(np.mean(values)),
            "weighted_mean": float(np.average(values, weights=weights)),
            "worst": float(np.min(values)),
            "std": float(np.std(values, ddof=0)),
        }

    return {
        "per_client": rows,
        "ari": aggregate("ari"),
        "nmi": aggregate("nmi"),
    }
