from __future__ import annotations
import argparse
import json
from pathlib import Path
from .experiments.config import RawConfig
from .experiments.planner import build_plan
from .experiments.runner import ExperimentRunner


def _series_parser(commands: argparse._SubParsersAction) -> None:
    series = commands.add_parser("series", help="Validate and expand a campaign without training")
    sub = series.add_subparsers(dest="operation", required=True)
    for name in ("validate", "plan", "import-archive", "migrate"):
        command = sub.add_parser(name)
        command.add_argument("input", type=Path, help="Archive directory" if name == "import-archive" else "Plan file")
        if name in ("plan", "import-archive", "migrate"):
            command.add_argument("--output", type=Path, required=name != "plan",
                                 help="Explicit destination for the complete JSON document")
        command.add_argument("--json", action="store_true", help="Report status as JSON")


def _protect_inputs(target: Path, source: Path, document: dict, base_dir: Path) -> None:
    candidate = target.resolve()
    for parent in candidate.parents:
        if (parent / "manifest.json").is_file() and (parent / "checksums.json").is_file() and (parent / "reproduce").is_dir():
            raise ValueError(f"--output: refusing to modify an existing campaign archive: {parent}")
    inputs = [source]
    historical = document.get("historical")
    if isinstance(historical, dict) and isinstance(historical.get("path"), str):
        base_dir = base_dir / historical["path"]
        inputs.append(base_dir)
    datasets = document.get("datasets", {})
    if isinstance(datasets, dict):
        for item in datasets.values():
            if isinstance(item, dict):
                params = item.get("params", {})
                paths = [item.get("path"), params.get("path") if isinstance(params, dict) else None]
                inputs.extend(base_dir / value for value in paths if isinstance(value, str))
    for input_path in inputs:
        actual = input_path.resolve()
        if (candidate == actual or actual.is_dir() and candidate.is_relative_to(actual)
                or candidate.is_file() and actual.is_file() and candidate.samefile(actual)):
            raise ValueError(f"--output: destination would overwrite an input: {candidate}")
    if target.is_symlink():
        raise ValueError(f"--output: destination is a symlink: {target}")


def _series(args: argparse.Namespace) -> None:
    from .experiments.plan_io import read_document, resolved_for_output, write_document
    from .experiments.series_plan import checkout_source_id, resolve_document

    source = args.input.resolve()
    output = getattr(args, "output", None)
    base_dir = source.parent
    if args.operation == "import-archive":
        from .experiments.plan_archive import import_archive
        base_dir = output.resolve().parent
        _protect_inputs(output, source, {}, base_dir)
        document = import_archive(source, plan_dir=base_dir)
    elif args.operation == "migrate":
        from .experiments.plan_legacy import migrate_legacy
        base_dir = output.resolve().parent
        document = migrate_legacy(read_document(source), plan_dir=base_dir, legacy_cwd=Path.cwd())
    else:
        document = read_document(source)
    if output is not None:
        _protect_inputs(output, source, document, base_dir)
    resolved = resolve_document(document, base_dir=base_dir, source_id=checkout_source_id())
    if args.operation == "plan" and output is None:
        print(json.dumps(resolved, ensure_ascii=False, indent=2, allow_nan=False))
        return
    if output is not None:
        if args.operation == "plan":
            document = resolved_for_output(resolved, source_dir=base_dir, output_dir=output.resolve().parent)
        write_document(document, output)
    summary = {"valid": True, "counts": resolved["counts"],
               "execution_readiness": resolved["execution_readiness"],
               "backends": sorted({job["backend"] for job in resolved["jobs"]})}
    if output is not None:
        summary["output"] = str(output.resolve())
    if args.json:
        print(json.dumps(summary, ensure_ascii=False))
    else:
        counts = resolved["counts"]
        print(f"{counts['series']} series, {counts['comparisons']} comparisons, {counts['jobs']} jobs")
        print("Backends: " + ", ".join(summary["backends"]))
        print("Execution readiness: " + summary["execution_readiness"]["status"])
        if output is not None:
            print(f"Written: {output}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="clustereval")
    sub = parser.add_subparsers(dest="command", required=True)
    run_p = sub.add_parser("run", help="Run benchmark config")
    run_p.add_argument("config", help="Path to YAML config")
    run_p.add_argument("--limit", type=int, default=None, help="Run only first N planned experiments")
    _series_parser(sub)
    args = parser.parse_args()

    if args.command == "series":
        try:
            _series(args)
        except (OSError, ValueError) as error:
            parser.exit(2, f"clustereval series {args.operation}: {error}\n")
        return

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
