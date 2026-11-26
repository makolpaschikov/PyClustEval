"""Public run, resume, retry and status entry points for sequential local campaigns."""
from __future__ import annotations

from argparse import SUPPRESS, ArgumentParser, Namespace
from functools import cache
from pathlib import Path
import json
import math
import sqlite3
import sys

from .runner_campaign import (create_campaign, descriptor_path, ensure_prepared, input_plan, protect_root, saved_plan,
                              verify_live_inputs)
from .runner_environment import IncompatibleEnvironment, check_environment
from .runner_queue import recover_running, release_evidence, schedule
from .runner_reader import read_campaign, read_snapshot
from .runner_state import (IntegrityError, finish_attempt, header, journal, latest_session, start_session, supervisor_runtime,
                           stop_session, unseal)
from .series_plan import execution_settings

COMMANDS = ("run", "status", "resume", "retry")


def _seconds(value: str) -> float | None:
    if value.lower() == "none":
        return None
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise ValueError("expected a positive duration or none")
    return number


def _megabytes(value: str) -> int | None:
    if value.lower() == "none":
        return None
    number = int(value)
    if number <= 0:
        raise ValueError("expected a positive memory limit or none")
    return number


def configure(command: ArgumentParser, name: str) -> None:
    command.add_argument("input", type=Path, help="Plan file" if name == "run" else "Campaign directory")
    command.add_argument("--json", action="store_true")
    if name in ("resume", "retry"):
        for flag, parse in (("--timeout-sec", _seconds), ("--total-time-sec", _seconds),
                            ("--memory-limit-mb", _megabytes)):
            command.add_argument(flag, type=parse, default=SUPPRESS)
    if name == "retry":
        command.add_argument("--status", choices=("error", "timeout"), required=True)
        command.add_argument("--job-id", help="Restrict the explicit retry to one scientific job")


def _latest_limits(db: sqlite3.Connection, plan: dict) -> dict:
    last = latest_session(db)
    return plan["execution"] if last is None else unseal(last["limits"], last["limits_sha"])


def _check_snapshot(db: sqlite3.Connection, root: Path, meta: dict, plan: dict) -> dict:
    snapshot = read_snapshot(db, root, meta, plan)
    if snapshot["integrity_errors"]:
        raise IntegrityError("; ".join(snapshot["integrity_errors"]))
    return snapshot


def _manage(root: Path, cmd: str, overrides: dict, selected: str | None,
            only_job: str | None) -> tuple[int, dict]:
    from .runner_process import check_resources

    with journal(root) as db:
        meta = header(db)
        plan = saved_plan(root, meta)
        policy = execution_settings(_latest_limits(db, plan) | overrides)
        check_resources(policy["memory_limit_mb"])
        if only_job is not None and only_job not in {j["job_id"] for j in plan["jobs"]}:
            raise ValueError(f"Unknown --job-id: {only_job}")
        runtime = supervisor_runtime()
        session = start_session(db, cmd, policy, runtime=runtime)
        processed = 0
        reason = "supervisor interrupted"
        differences = []
        try:
            snapshot = _check_snapshot(db, root, meta, plan)
            verify_live_inputs(root, meta, plan)

            @cache
            def before_work() -> None:
                if cmd != "run":
                    check_environment(snapshot, runtime)

            for row in db.execute("SELECT comparison_id,record FROM preparations").fetchall():
                if row["record"] is None and not descriptor_path(root, row["comparison_id"]).exists():
                    before_work()
                ensure_prepared(db, root, plan, row["comparison_id"], Path(meta["base_dir"]))
            recover_running(db, root)
            if snapshot["summary"]["current"]:
                snapshot = _check_snapshot(db, root, meta, plan)
                before_work.cache_clear()
            reason, processed = schedule(db, root, meta, plan, session, policy, cmd, selected, only_job,
                                         before_work=before_work)
        except IncompatibleEnvironment as exc:
            reason = str(exc)
            differences = exc.differences
        except KeyboardInterrupt:
            reason = "cancelled"
            active = db.execute("SELECT id,request,request_sha FROM attempts WHERE status='running' "
                                "AND session_id=?", (session,)).fetchone()
            if active is not None:
                request = unseal(active["request"], active["request_sha"])
                finish_attempt(db, active["id"], "cancelled", reason, details=release_evidence(request))
        except (OSError, sqlite3.Error, ValueError) as exc:
            reason = str(exc)
            raise
        finally:
            stop_session(db, session, reason)
        summary = _check_snapshot(db, root, meta, plan)["summary"]
        summary.update(command=cmd, attempts_started=processed)
        if differences:
            return 3, {**summary, "environment_differences": differences}
        return (0 if summary["totals"]["ok"] == summary["planned"] else 3), summary


def control(args: Namespace) -> tuple[int, dict]:
    from .runner_process import CampaignBusy, campaign_lock, check_resources

    operation = args.operation
    location = args.input.resolve()
    if operation == "status":
        snapshot = read_campaign(location)
        return (4 if snapshot["integrity_errors"] else 0), {
            **snapshot["summary"], "integrity_errors": snapshot["integrity_errors"]}
    if operation == "run":
        raw, plan = input_plan(location)
        root = Path(plan["campaign"]["output_dir"]).resolve()
        protect_root(root)
        check_resources(plan["execution"]["memory_limit_mb"])
    else:
        root = location
    overrides = {key: getattr(args, key) for key in ("timeout_sec", "total_time_sec", "memory_limit_mb")
                 if hasattr(args, key)}
    try:
        with campaign_lock(root):
            if operation == "run":
                create_campaign(root, location, raw, plan)
            return _manage(root, operation, overrides, getattr(args, "status", None), getattr(args, "job_id", None))
    except (CampaignBusy, FileExistsError) as exc:
        return 3, {"error": str(exc), "campaign": str(root)}


def cli(args: Namespace) -> int:
    try:
        code, report = control(args)
    except IntegrityError as exc:
        code, report = 4, {"error": str(exc)}
    except (ValueError, FileNotFoundError) as exc:
        code, report = 2, {"error": str(exc)}
    except (OSError, sqlite3.Error) as exc:
        code, report = 3, {"error": str(exc)}
    if args.json:
        print(json.dumps(report, ensure_ascii=False, allow_nan=False))
    elif "totals" in report:
        print(" ".join(f"{status}={total}" for status, total in report["totals"].items()))
        if report.get("stop_reason"):
            print(report["stop_reason"])
    if "error" in report:
        print(report["error"], file=sys.stderr)
    for error in report.get("integrity_errors", []):
        print(error, file=sys.stderr)
    return code
