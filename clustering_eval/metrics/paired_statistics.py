"""Paired multi-seed descriptive summaries for controlled benchmark conditions.

A bootstrap over seeds quantifies sensitivity to the *specified scenario*; it
is NOT a population-wide CI over datasets. Require both algorithms to have
all same (dataset, partition, seed, client setup) pairs before comparison.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable
import numpy as np


def summarize_metric(rows: Iterable[dict[str, Any]], metric: str = "ari") -> list[dict[str, Any]]:
    groups: dict[tuple[Any, ...], list[float]] = defaultdict(list)
    for row in rows:
        value = row.get(metric)
        if value is None or not np.isfinite(value):
            continue
        key = (row["dataset"], row["scenario"], row["algorithm"])
        groups[key].append(float(value))
    return [{"dataset": ds, "scenario": sc, "algorithm": alg,
             "metric": metric, "n": len(vals), "mean": float(np.mean(vals)),
             "sd": float(np.std(vals, ddof=1)) if len(vals)>1 else None,
             "min": float(min(vals)), "max": float(max(vals))}
            for (ds, sc, alg), vals in sorted(groups.items())]


def paired_bootstrap(
    rows: Iterable[dict[str, Any]], *, left: str, right: str,
    metric: str = "ari", draws: int = 5000, seed: int = 2026,
) -> list[dict[str, Any]]:
    by_scenario: dict[tuple[Any, Any], dict[tuple[Any, Any], dict[str, float]]] = defaultdict(lambda: defaultdict(dict))
    for r in rows:
        if r.get("algorithm") not in (left, right):
            continue
        value = r.get(metric)
        if value is None or not np.isfinite(value):
            continue
        key = (r["dataset"], r["scenario"])
        pair_id = (r["seed"], r.get("partition_fingerprint"))
        by_scenario[key][pair_id][r["algorithm"]] = float(value)
    rng = np.random.default_rng(seed)
    report: list[dict[str, Any]] = []
    for (dataset, scenario), candidate_pairs in sorted(by_scenario.items()):
        diffs = np.asarray([entry[left] - entry[right] for entry in candidate_pairs.values()
                            if left in entry and right in entry], dtype=float)
        if not len(diffs):
            continue
        means = np.mean(diffs[rng.integers(0, len(diffs), size=(draws, len(diffs)))], axis=1)
        report.append({"dataset": dataset, "scenario": scenario,
                       "left": left, "right": right, "metric": metric,
                       "n_pairs": len(diffs), "mean_difference": float(diffs.mean()),
                       "sd_difference": float(diffs.std(ddof=1)) if len(diffs)>1 else None,
                       "bootstrap_ci_95": [float(v) for v in np.quantile(means, [.025, .975])],
                       "fraction_left_better": float((diffs > 0).mean()),
                       "limitations": "CI conditional on tested datasets and scenario; no population generalization."})
    return report


def paired_scenario_delta(
    rows: Iterable[dict[str, Any]], *, algorithm: str,
    before: str, after: str, metric: str = "ari",
    draws: int = 5000, seed: int = 2026,
) -> list[dict[str, Any]]:
    """Difference (after - before) across same-dataset, same-seed runs.

    Useful for measuring stress effects, unlike comparing unpaired pooled means.
    Partition fingerprint intentionally differs across stress conditions.
    """
    groups: dict[str, dict[Any, dict[str, float]]] = defaultdict(lambda: defaultdict(dict))
    for r in rows:
        if r.get("algorithm") != algorithm or r.get("scenario") not in (before, after):
            continue
        value = r.get(metric)
        if value is not None and np.isfinite(value):
            groups[r["dataset"]][r["seed"]][r["scenario"]] = float(value)
    rng = np.random.default_rng(seed)
    summaries = []
    for dataset, seeds in sorted(groups.items()):
        deltas = np.asarray([v[after]-v[before] for v in seeds.values()
                             if before in v and after in v], dtype=float)
        if not len(deltas):
            continue
        means=np.mean(deltas[rng.integers(len(deltas),size=(draws,len(deltas)))],axis=1)
        summaries.append({"dataset":dataset,"algorithm":algorithm,"metric":metric,
                          "before":before,"after":after,"n_paired_seeds":len(deltas),
                          "mean_after_minus_before":float(deltas.mean()),
                          "bootstrap_ci_95": [float(x) for x in np.quantile(means,[.025,.975])],
                          "conditional_on_scenarios":True})
    return summaries
