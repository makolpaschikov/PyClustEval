"""Inspect the runtime, installed checks and effective hook without changing them."""
from __future__ import annotations

import importlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

from .common import QualityError

COMMANDS = ("doctor",)
CHECKERS = {
    "validation": ("validate",),
    "git_checks": ("staged",),
    "handoff": ("handoff",),
    "hooks": ("hooks", "precommit"),
}
MINIMUM_PYTHON = (3, 10)
PROBE_TIMEOUT = 5
PYTHON_PROBE = (
    "import json, sys; "
    "print(json.dumps([sys.executable, list(sys.version_info[:3])]))"
)
GIT_LOCATION_VARIABLES = ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR")


def add_commands(subparsers):
    parser = subparsers.add_parser("doctor", help="inspect harness readiness")
    parser.add_argument("--python", type=Path, help="probe this Python executable")


def unavailable(diagnostics, code, message, **details):
    diagnostics.append({"code": code, "message": message})
    return {"state": "unavailable", **details}


def probe(*argv, env=None):
    return subprocess.run(
        argv, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        timeout=PROBE_TIMEOUT, env=env,
    )


def inspect_python(executable, diagnostics, code):
    executable = Path(executable).absolute()
    retry = "Supply an executable for Python 3.10 or newer."
    try:
        result = probe(str(executable), "-I", "-B", "-S", "-c", PYTHON_PROBE)
    except subprocess.TimeoutExpired:
        return unavailable(diagnostics, code, f"The Python probe timed out. {retry}",
                           executable=str(executable))
    except OSError:
        return unavailable(diagnostics, code, f"Could not launch Python. {retry}",
                           executable=str(executable))

    try:
        actual, version = json.loads(result.stdout)
        if (result.returncode != 0 or not isinstance(actual, str) or not actual
                or not isinstance(version, list) or len(version) != 3
                or any(type(part) is not int or part < 0 for part in version)):
            raise ValueError
    except (TypeError, ValueError):
        return unavailable(diagnostics, code, f"The Python probe failed. {retry}",
                           executable=str(executable))

    details = {"executable": actual, "version": ".".join(map(str, version))}
    if tuple(version[:2]) < MINIMUM_PYTHON:
        return unavailable(diagnostics, code, f"Python {details['version']} is too old. {retry}",
                           **details)
    return {"state": "ready", **details}


def inspect_git(repo, diagnostics):
    executable = shutil.which("git")
    repository = {"state": "unavailable", "path": str(repo)}
    retry = "Make Git available on PATH and rerun doctor."
    if not executable:
        return unavailable(diagnostics, "git-missing", retry), repository
    try:
        result = probe(executable, "--version")
        version = re.match(rb"git version (\d[\w.+-]*)(?:\s|$)", result.stdout)
    except (subprocess.TimeoutExpired, OSError):
        return unavailable(diagnostics, "git-probe", f"Could not run Git. {retry}"), repository
    if result.returncode != 0 or not version:
        return unavailable(diagnostics, "git-probe", f"The Git version probe failed. {retry}"), repository

    git = {"state": "ready", "version": version[1].decode("ascii")}
    if any(name in os.environ for name in GIT_LOCATION_VARIABLES):
        diagnostics.append({
            "code": "repository-environment",
            "message": "Git checkout overrides are present. Rerun doctor in a shell without "
                       "GIT_DIR, GIT_WORK_TREE or GIT_COMMON_DIR.",
        })
        return git, repository

    try:
        result = probe(executable, "-C", str(repo), "rev-parse", "--show-toplevel",
                       env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"})
        if result.returncode == 0:
            reported = Path(os.fsdecode(result.stdout).rstrip("\r\n"))
            if reported.is_absolute() and reported.resolve() == repo:
                repository["state"] = "ready"
                return git, repository
    except (subprocess.TimeoutExpired, OSError, RuntimeError, ValueError):
        pass
    diagnostics.append({
        "code": "repository-root",
        "message": "Could not verify the selected Git worktree root. Pass its root directory with --repo.",
    })
    return git, repository


def inspect_checkers(diagnostics):
    modules = {}
    states = {}
    for name, commands in CHECKERS.items():
        try:
            module = importlib.import_module(f".{name}", __package__)
            if not (callable(getattr(module, "add_commands", None))
                    and callable(getattr(module, "run_command", None))
                    and all(command in getattr(module, "COMMANDS", ()) for command in commands)):
                raise ImportError
        except (ImportError, OSError, RuntimeError, SyntaxError, TypeError, ValueError):
            states[name] = unavailable(
                diagnostics, "checker-unavailable",
                f"The {name} checker could not be loaded. Use a complete harness checkout.",
            )
        else:
            modules[name] = module
            states[name] = {"state": "ready"}
    return modules, states


def inspect_assignment(repo, hook, git_checks, diagnostics):
    path = hook.get("assignment")
    digest = hook.get("assignment_sha256")
    if not path and not digest:
        state = "unavailable" if hook["state"] == "unavailable" else "not_applicable"
        return {"state": state}
    if not path or not digest:
        return unavailable(
            diagnostics, "assignment-binding",
            "The hook assignment binding is incomplete. Obtain the assignment path and hash from the analyst.",
        )
    if git_checks is None:
        return {"state": "unavailable"}
    load = getattr(git_checks, "load_assignment", None)
    validate = getattr(git_checks, "validate_checkout", None)
    if not callable(load) or not callable(validate):
        return unavailable(
            diagnostics, "assignment-checker",
            "The assignment checker is unavailable. Use a complete harness checkout.",
        )
    try:
        assignment = load(Path(path), digest)
        validate(repo, assignment)
    except QualityError as exc:
        return unavailable(
            diagnostics, "assignment-invalid",
            f"{exc} Confirm the assigned checkout and current assignment hash with the analyst.",
            path=str(path),
        )
    except (ImportError, OSError, TypeError, ValueError):
        return unavailable(
            diagnostics, "assignment-unavailable",
            "Could not verify the hook assignment. Check that the assigned file is readable.",
            path=str(path),
        )
    return {"state": "ready", "path": str(path), "sha256": digest}


def inspect_hook(repo, modules, repository, executable, python, diagnostics):
    hooks = modules.get("hooks")
    if repository["state"] != "ready" or hooks is None:
        return {"state": "unavailable"}, {"state": "unavailable"}
    hook_status = getattr(hooks, "hook_status", None)
    if not callable(hook_status):
        hook = unavailable(
            diagnostics, "hook-probe", "The hook status checker is unavailable. Use a complete harness checkout.",
        )
        return hook, {"state": "unavailable"}
    try:
        status = hook_status(repo)
    except (QualityError, OSError, subprocess.TimeoutExpired, ValueError):
        hook = unavailable(
            diagnostics, "hook-probe", "Could not inspect the effective hook. Run hooks status for the selected worktree.",
        )
        return hook, {"state": "unavailable"}
    diagnostics.extend(status["diagnostics"])
    hook = {"state": status["state"]}
    assignment = inspect_assignment(repo, status, modules.get("git_checks"), diagnostics)
    if hook["state"] == "not_configured" and not status["diagnostics"]:
        diagnostics.append({
            "code": "hook-not-configured",
            "message": "The optional pre-commit hook is unconfigured for this worktree. "
                       "See hooks install --help to enable it.",
        })
    if hook["state"] == "ready":
        hook_python = status.get("python")
        if not hook_python:
            hook["python"] = unavailable(
                diagnostics, "hook-python", "The configured hook has no Python binding. Review hooks status.",
            )
        elif Path(hook_python).absolute() == Path(executable).absolute():
            hook["python"] = python
        else:
            hook["python"] = inspect_python(hook_python, diagnostics, "hook-python")
        if hook["python"]["state"] != "ready" or assignment["state"] == "unavailable":
            hook["state"] = "unavailable"
    return hook, assignment


def run_command(args, repo):
    """Report readiness. A missing optional hook does not fail the required checks."""
    executable = args.python if args.python is not None else sys.executable
    diagnostics = []
    python = inspect_python(executable, diagnostics, "python")
    git, repository = inspect_git(repo, diagnostics)
    modules, checkers = inspect_checkers(diagnostics)
    hook, assignment = inspect_hook(repo, modules, repository, executable, python, diagnostics)
    ok = (
        all(check["state"] == "ready" for check in (python, git, repository, *checkers.values()))
        and hook["state"] in {"ready", "not_configured"}
        and assignment["state"] in {"ready", "not_applicable"}
    )
    return {
        "command": "doctor",
        "ok": ok,
        "diagnostics": diagnostics,
        "components": {
            "python": python,
            "git": git,
            "repository": repository,
            "checkers": checkers,
            "hook": hook,
            "assignment": assignment,
        },
    }
