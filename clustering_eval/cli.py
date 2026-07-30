from __future__ import annotations
import argparse
from .experiments.config import RawConfig
from .experiments.planner import build_plan
from .experiments.runner import ExperimentRunner


def main() -> None:
    parser = argparse.ArgumentParser(prog="clustereval")
    sub = parser.add_subparsers(dest="command", required=True)
    run_p = sub.add_parser("run", help="Run benchmark config")
    run_p.add_argument("config", help="Path to YAML config")
    run_p.add_argument("--limit", type=int, default=None, help="Run only first N planned experiments")
    args = parser.parse_args()

    if args.command == "run":
        raw = RawConfig.from_yaml(args.config).data
        specs = build_plan(raw)
        if args.limit is not None:
            specs = specs[:args.limit]
        output_dir = raw.get("experiment", {}).get("output_dir", "results")
        metrics = raw.get("metrics", ["ari", "nmi", "silhouette"])
        print(f"Planned experiments: {len(specs)}")
        runner = ExperimentRunner(metrics=metrics, output_dir=output_dir)
        runner.run_many(specs)
        print(f"Done. Results: {output_dir}/metrics.csv")

if __name__ == "__main__":
    main()
