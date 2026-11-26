"""Operator-facing export and independent archive verification."""
from __future__ import annotations

from argparse import Namespace
import json
import sys

from ..experiments.runner_state import IntegrityError
from .archive_publish import PublicationBusy, VerificationFailure, publish_archive


def cli(args: Namespace) -> int:
    """Report an operation outcome, including a distinct exit for valid partial archives."""
    operation = args.operation
    path = args.input.absolute()
    report = {"action": operation, "path": str(path / "archive" if operation == "export" else path),
              "published": False, "complete": None}
    try:
        path = path.resolve()
        report["path"] = str(path / "archive" if operation == "export" else path)
        if operation == "export":
            report.update(publish_archive(path))
        else:
            if not path.is_dir():
                raise ValueError(f"Expected an archive directory: {path}")
            if not any((path / name).exists() for name in ("manifest.json", "checksums.json", "verification.json")):
                raise ValueError(f"Unrecognized archive directory: {path}")
            from .archive_verify import verify_archive

            checked = verify_archive(path)
            if not checked["valid"]:
                raise VerificationFailure(checked)
            report["verification"] = checked
            report["complete"] = checked["complete"]
            for key in ("planned", "totals", "run_count", "comparison_count", "series_count"):
                if key in checked:
                    report[key] = checked[key]
        report["result"] = "complete" if report["complete"] else "partial"
        code = 0 if report["complete"] else 3
    except IntegrityError as exc:
        report.update(result="invalid", error=str(exc))
        if isinstance(exc, VerificationFailure):
            report["verification"] = exc.report
        code = 4
    except ValueError as exc:
        report.update(result="invalid_input", error=str(exc))
        code = 2
    except (OSError, KeyboardInterrupt) as exc:
        report.update(result="busy" if isinstance(exc, PublicationBusy) else "operation_failed",
                      error=str(exc) or "Operation interrupted")
        code = 3
    if args.json:
        print(json.dumps(report, ensure_ascii=False, allow_nan=False))
    else:
        print(f"{operation}: {report['result']} | {report['path']}")
        if "totals" in report:
            print(" ".join(f"{status}={count}" for status, count in report["totals"].items()))
        if "verification" in report:
            verification = report["verification"]
            print(" ".join(f"{item['scope']}={item['count']}" for item in verification["checks"]))
            for item in verification["not_checked"]:
                print("not_checked", json.dumps(item, ensure_ascii=False))
        if "error" in report:
            print(report["error"], file=sys.stderr)
        for message in report.get("warnings", []):
            print(message, file=sys.stderr)
    return code
