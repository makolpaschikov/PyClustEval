#!/usr/bin/env python3
"""Validate the harness and inspect assigned Git work. Requires Python 3.10+."""
from __future__ import annotations

import argparse
import importlib
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True

from quality_support.common import QualityError

ROOT = Path(__file__).resolve().parents[2]
MODULES = ("validation", "git_checks", "doctor", "hooks", "handoff")
MODULE_COMMANDS = {"validation": ("validate",), "git_checks": ("staged",),
                   "doctor": ("doctor",), "hooks": ("hooks", "precommit"),
                   "handoff": ("handoff",)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=ROOT)
    parser.add_argument("--json", action="store_true", help="emit structured diagnostics")
    commands = parser.add_subparsers(dest="command", required=True)
    modules, unavailable = [], {}
    for name in MODULES:
        try:
            module = importlib.import_module(f"quality_support.{name}")
        except Exception as exc:
            # Keep diagnostics available even when another checker cannot load.
            for command in MODULE_COMMANDS[name]:
                unavailable[command] = f"Cannot load {name}: {exc}"
                fallback = commands.add_parser(command, help="component unavailable")
                fallback.add_argument("arguments", nargs=argparse.REMAINDER)
            continue
        module.add_commands(commands)
        modules.append(module)
    args = parser.parse_args(argv)
    try:
        if args.command in unavailable:
            raise QualityError(unavailable[args.command])
        module = next(module for module in modules if args.command in module.COMMANDS)
        report = module.run_command(args, args.repo.resolve())
    except (QualityError, OSError, UnicodeError, ValueError) as exc:
        report = {"command": args.command, "ok": False,
                  "diagnostics": [{"code": "operation", "message": str(exc)}]}
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"{report['command']}: {'passed' if report['ok'] else 'not ready'}")
        for entry in report.get("diagnostics", []):
            location = f"{entry['path']}: " if entry.get("path") else ""
            print(f"{entry.get('code', 'check')}: {location}{entry['message']}")
        details = {key: value for key, value in report.items()
                   if key not in {"command", "ok", "diagnostics"}}
        if details:
            print(json.dumps(details, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
