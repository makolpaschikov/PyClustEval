#!/usr/bin/env python3
"""Manage task artifacts, explicit checks and evidence. Requires Python 3.10+ and Git."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from task_support.artifacts import (CODE_ROOT, initialize, load, repository,
                                    spec_digest, stable_snapshot, workspace)
from task_support.formats import SECTIONS, TaskError, require
from task_support.gates import check_gate
from task_support.lint import lint
from task_support.migration import migrate
from task_support import snapshots, state, execution, evidence

AUTOMATION = (snapshots, state, execution, evidence)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=CODE_ROOT, help="repository root; isolated repository for tests")
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init", help="create a draft from a versioned template; no overwrite")
    init.add_argument("directory", type=Path)
    init.add_argument("--id", required=True)
    init.add_argument("--kind", choices=SECTIONS, required=True)
    init.add_argument("--branch", required=True)
    init.add_argument("--scope", choices=("harness", "application"), required=True)
    init.add_argument("--parent")
    init.add_argument("--expect-sha256", help="current manifest hash when adding to an existing task")
    migration = commands.add_parser("migrate", help="explicit v1-to-v2 migration; preserve original evidence")
    migration.add_argument("directory", type=Path)
    migration.add_argument("--expect-sha256", required=True, help="current SHA-256 of task.json")
    for name in ("lint", "snapshot", "check"):
        command = commands.add_parser(name, help="read-only inspection")
        command.add_argument("directory", type=Path)
        if name != "lint":
            command.add_argument("--id", required=True)
        if name == "check":
            command.add_argument("--gate", choices=("specification", "start", "completion", "resumption"), required=True)
    for module in AUTOMATION:
        module.add_commands(commands)
    arguments = list(sys.argv[1:] if argv is None else argv)
    command_argv = None
    # Only the top-level command token controls argv splitting; option values
    # (including a repository named "run-check") must not affect legacy parsing.
    position = 0
    while position < len(arguments):
        token = arguments[position]
        option = token.split("=", 1)[0]
        if option.startswith("--") and "--repo".startswith(option) and len(option) > 2:
            position += 1 if "=" in token else 2
        else:
            break
    is_run_check = position < len(arguments) and arguments[position] == "run-check"
    if is_run_check and "--" in arguments[position + 1:]:
        separator = arguments.index("--", position + 1)
        command_argv = arguments[separator + 1:]
        arguments = arguments[:separator]
    args = parser.parse_args(arguments)
    if args.command == "run-check":
        args.argv = command_argv or []
    try:
        repo = repository(args.repo)
        for module in AUTOMATION:
            if args.command in module.COMMANDS:
                report, exit_code = module.run_command(args, repo)
                print(json.dumps(report, indent=2, ensure_ascii=False))
                return exit_code
        directory = workspace(repo, args.directory)
        if args.command == "init":
            initialize(repo, directory, args.id, args.kind, args.branch, args.scope, args.parent, args.expect_sha256)
        backup = migrate(repo, directory, args.expect_sha256) if args.command == "migrate" else None
        manifest, revision = load(directory)
        index, _ = lint(repo, directory, manifest)
        report = {"command": args.command, "manifest_sha256": revision, "items": list(index)}
        if backup:
            report.update(backup=backup, reassessment_required=True,
                          notice="Assess mathematical impact and revalidate existing evidence; prior approvals and reviews were not rebound.")
        if args.command in ("snapshot", "check"):
            require(args.id in index, f"Unknown item: {args.id}")
            snapshot = stable_snapshot(repo)
            report.update(snapshot)
            report["spec_sha256"] = spec_digest(directory, manifest, index[args.id])
            if args.command == "check":
                report["gate"] = args.gate
                report["receipt"] = check_gate(repo, directory, manifest, args.id, args.gate, snapshot)
            require(snapshot == stable_snapshot(repo), "Source changed during inspection; retry when writers stop")
            require(report["spec_sha256"] == spec_digest(directory, manifest, index[args.id]), "Task documents changed during inspection")
        require(load(directory)[1] == revision, "Manifest changed during inspection")
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0
    except (TaskError, OSError, UnicodeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
