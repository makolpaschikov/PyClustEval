from __future__ import annotations

import argparse
import csv
from pathlib import Path

from clustering_eval.benchmarks.density_sensitivity import run_density_sensitivity


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Equal-budget, label-free DBSCAN/HF_DBSCAN radius sensitivity sweep"
    )
    parser.add_argument(
        "--datasets",
        nargs="+",
        default=["iris", "wine", "blobs", "digits"],
    )
    parser.add_argument("--output", default="docs/density_sensitivity.csv")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--clients", type=int, default=5)
    parser.add_argument("--density-min-samples", type=int, default=4)
    args = parser.parse_args()

    rows: list[dict[str, object]] = []
    for dataset in args.datasets:
        rows.extend(
            run_density_sensitivity(
                dataset,
                seed=args.seed,
                num_clients=args.clients,
                density_min_samples=args.density_min_samples,
            )
        )

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    counts: dict[str, int] = {}
    for row in rows:
        counts[str(row["status"])] = counts.get(str(row["status"]), 0) + 1
    print(f"wrote {len(rows)} cases to {output}")
    print("status counts:", counts)
    print("No candidate was selected using ARI/NMI; this is a sensitivity report only.")


if __name__ == "__main__":
    main()
