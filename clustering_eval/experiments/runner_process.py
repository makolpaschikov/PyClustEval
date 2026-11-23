"""Exclusive local campaign ownership and a bounded lifetime for each worker tree."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from hashlib import sha256
import math
import os
from pathlib import Path
import sys
import time


if sys.platform == "win32":
    from . import runner_windows as win


class CampaignBusy(RuntimeError):
    """Another supervisor owns this campaign directory."""


@dataclass(frozen=True)
class ProcessOutcome:
    returncode: int | None
    reason: str
    wall_sec: float
    tree_resources: dict


_ownership: ContextVar[tuple[str, int] | None] = ContextVar("campaign_ownership", default=None)


def _windows_required() -> None:
    if sys.platform != "win32" or sys.getwindowsversion().major < 10:
        raise ValueError("Campaign process-tree ownership requires Windows 10 or newer")


def _object_name(root: Path) -> str:
    prefix = "\\\\?\\"
    # Normalize DOS spelling even for a missing suffix. Verbatim paths keep
    # their own filename semantics until filesystem aliases have been resolved.
    if not str(root).startswith(prefix):
        root = Path(os.path.abspath(root))
    canonical = os.path.normcase(str(root.resolve()))
    if canonical.startswith(prefix):
        tail = canonical[len(prefix):]
        if tail.startswith("unc\\"):
            canonical = "\\\\" + tail[4:]
        elif os.path.splitdrive(tail)[0].endswith(":"):
            canonical = tail
    return "Global\\PyClustEval-Campaign-" + sha256(canonical.encode("utf-8")).hexdigest()


@contextmanager
def campaign_lock(root: Path) -> Iterator[None]:
    """Hold one supervisor lease without creating any files in the campaign.

    On recovery, take over and drain an old job before any saved records are
    examined. Calls to run_owned execute inside this context on the same thread.
    """
    _windows_required()
    name = _object_name(root)
    with win.exclusive_name(name) as lease:
        if lease is None:
            raise CampaignBusy(f"Campaign already has an active supervisor: {root}")
        tree_name = name + "-Worker"
        win.recover_job(tree_name)
        token = _ownership.set((tree_name, lease))
        try:
            yield
        finally:
            _ownership.reset(token)


def is_campaign_active(root: Path) -> bool:
    """Query the live owner without opening the journal or inspecting a saved PID."""
    _windows_required()
    return win.owner_exists(_object_name(root))


def check_resources(memory_limit_mb: int | None) -> None:
    """Reject unavailable tree ownership or hard commit limits before execution."""
    _windows_required()
    if memory_limit_mb is None:
        return
    if type(memory_limit_mb) is not int or not 1 <= memory_limit_mb <= sys.maxsize // 1024**2:
        raise ValueError("memory_limit_mb must be a positive representable MiB limit")
    try:
        with win.job_object(None, memory_limit_mb):
            pass
    except OSError as error:
        raise ValueError(f"Cannot enforce the requested job memory limit: {error}") from error


def worker_env(blas_threads: int) -> dict[str, str]:
    """Build the child environment before its interpreter imports numerical libraries."""
    if type(blas_threads) is not int or blas_threads < 1:
        raise ValueError("blas_threads must be a positive integer")
    env = os.environ.copy()
    for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
        env[key] = str(blas_threads)
    env["PYTHONUNBUFFERED"] = "1"
    return env


def run_owned(argv: list[str], *, cwd: Path, env: dict[str, str], stdout_path: Path,
              stderr_path: Path, timeout_sec: float | None, deadline_utc: float | None,
              memory_limit_mb: int | None, on_stop: Callable[[str], None] | None = None
              ) -> ProcessOutcome:
    """Run one worker, closing its whole tree before returning to the caller.

    An absolute UTC deadline is converted to a monotonic deadline at entry. A
    stop callback can durably record the decision while the job is still held.
    Infrastructure or callback errors propagate after tree cleanup.
    """
    start = time.monotonic()
    check_resources(memory_limit_mb)
    limits = []
    if deadline_utc is not None:
        limits.append((start + deadline_utc - time.time(), "total_time"))
    if timeout_sec is not None:
        limits.append((start + timeout_sec, "timeout"))
    deadline, expiry = min(limits, default=(math.inf, "timeout"))
    reason = "exited"
    code = None
    resources = win.TreeResources()
    with ExitStack() as cleanup:
        try:
            job = cleanup.enter_context(win.job_object(_ownership.get(), memory_limit_mb,
                                                      after_drain=resources.after_drain))
            if time.monotonic() >= deadline:
                reason = expiry
            else:
                with win.start_process(job, argv, cwd, env, stdout_path, stderr_path) as process:
                    next_sample = 0.0
                    while code is None:
                        now = time.monotonic()
                        if next_sample <= now < deadline:
                            resources.sample(job)
                            next_sample = time.monotonic() + resources.working_set_sample_interval_sec
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            reason = expiry
                            break
                        wait_ms = math.ceil(min(remaining, 0.05) * 1000)
                        code = win.wait_for_exit(process, wait_ms)
        except KeyboardInterrupt:
            reason = "cancelled"
        if reason != "exited" and on_stop is not None:
            on_stop(reason)
    return ProcessOutcome(code, reason, time.monotonic() - start, resources.record())
