"""Explicit, per-worktree optional staged harness checks."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

from .common import QualityError
from . import git_checks

COMMANDS = {"hooks", "precommit"}
CONFIG = Path('.agent-work/tasks/.quality-hook/config')
FAST = {'test_quality_validation.py', 'test_quality_git.py', 'test_task.py', 'test_journal.py'}
FOCUSED = {
    'harness/scripts/journal.py': {'test_journal.py'},
    'harness/scripts/quality_support/validation.py': {'test_quality_validation.py'},
    'harness/scripts/quality_support/git_checks.py': {'test_quality_git.py', 'test_quality_handoff.py'},
    'harness/scripts/quality_support/doctor.py': {'test_quality_doctor.py'},
    'harness/scripts/quality_support/handoff.py': {'test_quality_handoff.py'},
    'harness/scripts/quality_support/hooks.py': {'test_quality_hooks.py'},
    'harness/scripts/task/task.py': {'test_task.py'},
    **{f'harness/scripts/task/task_support/{name}.py': {'test_task.py', 'test_evidence.py', 'test_state.py'}
       for name in ('__init__', 'formats', 'artifacts', 'gates', 'lint', 'migration')},
    **{f'harness/scripts/task/task_support/{name}.py': {f'test_{name}.py', 'test_task.py'}
       for name in ('evidence', 'execution', 'bundles', 'state', 'snapshots', 'mathematics')},
}


def select_tests(paths):
    selected = set()
    for path in paths:
        if path.startswith('harness/tests/test_') and path.endswith('.py'):
            selected.add(path.rsplit('/', 1)[-1])
        elif path.startswith('harness/scripts/'):
            selected.update(FOCUSED.get(path, FAST))
    return sorted(selected)
LAUNCHER = b'''#!/bin/sh
# PyClustEval quality hook v1
root=$(git rev-parse --show-toplevel) || exit 1
common=$(git rev-parse --git-common-dir) || exit 1
case "$common" in /*|[A-Za-z]:/*) ;; *) common="$root/$common";; esac
config="$root/.agent-work/tasks/.quality-hook/config"
[ -f "$config" ] || exit 0
IFS= read -r python < "$config" || exit 1
exec "$python" -E -S -B "$common/hooks/quality-runner.py" "$root" "$config"
'''

# Installed verbatim in the common Git directory. This trusted bootstrap uses
# only index blobs; no Python module is imported from the working tree.
RUNNER = r'''import hashlib, json, os, pathlib, subprocess, sys, tempfile
root, config = map(pathlib.Path, sys.argv[1:])
env = os.environ.copy()
for k in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_PREFIX", "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES"):
    env.pop(k, None)
env["GIT_OPTIONAL_LOCKS"] = "0"
def git(*args):
    return subprocess.check_output(["git", "--no-replace-objects", "-C", str(root), *args], env=env, timeout=60)
def identity():
    index = pathlib.Path(os.fsdecode(git("rev-parse", "--git-path", "index")).strip())
    if not index.is_absolute(): index = root / index
    return hashlib.sha256(index.read_bytes() + git("ls-files", "--stage", "-z") + git("diff", "--cached", "--raw", "-z", "--no-ext-diff", "--ignore-submodules=none")).hexdigest(), git("rev-parse", "HEAD")
try:
    binding = config.read_bytes()
    settings = json.loads(binding.split(b"\n", 1)[1])
    before = identity()
    if git("ls-files", "--unmerged", "-z"):
        raise RuntimeError("index contains unresolved entries")
    entries = {}
    for entry in filter(None, git("ls-tree", "-r", "-z", "--full-tree", "HEAD").split(b"\0")):
        meta, path = entry.split(b"\t", 1)
        mode, kind, oid = meta.split()
        entries[path] = (mode, oid)
    fields = git("diff", "--cached", "--raw", "-z", "--no-abbrev", "--no-renames", "--ita-invisible-in-index", "--ignore-submodules=none", "--no-ext-diff", "HEAD").split(b"\0")
    if fields[-1] != b"": raise RuntimeError("truncated cached diff")
    fields.pop()
    if len(fields) % 2: raise RuntimeError("invalid cached diff")
    for meta, path in zip(fields[::2], fields[1::2]):
        oldmode, mode, oldoid, oid, status = meta.split()
        if not oldmode.startswith(b":") or status not in (b"A", b"M", b"D", b"T"):
            raise RuntimeError("unsupported cached diff status")
        if status == b"D": entries.pop(path, None)
        else: entries[path] = (mode, oid)
    with tempfile.TemporaryDirectory(prefix="quality-index-", dir=str(config.parent)) as tmp:
        snapshot = pathlib.Path(tmp)
        for raw, (mode, oid) in entries.items():
            path = pathlib.PurePosixPath(os.fsdecode(raw))
            if path.is_absolute() or ".." in path.parts or b"\\" in raw or b":" in raw or mode not in (b"100644", b"100755"):
                raise RuntimeError("unsupported index path or file mode: " + str(path))
            dest = snapshot.joinpath(*path.parts)
            if not dest.resolve().is_relative_to(snapshot.resolve()):
                raise RuntimeError("index path escapes snapshot: " + str(path))
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(git("cat-file", "blob", oid.decode("ascii")))
        command = [sys.executable, "-E", "-S", "-B", str(snapshot / "harness/scripts/quality.py"), "--repo", str(root), "precommit", "--snapshot", str(snapshot), "--binding", str(config)]
        result = subprocess.run(command, env=env, timeout=300)
        if identity() != before or config.read_bytes() != binding:
            raise RuntimeError("index, HEAD or hook configuration changed during checks")
        sys.exit(result.returncode)
except (OSError, ValueError, KeyError, subprocess.SubprocessError, RuntimeError) as exc:
    print("precommit: bootstrap failed: " + str(exc), file=sys.stderr)
    sys.exit(1)
'''.encode('utf-8')


def _locations(repo):
    repo = Path(repo).resolve(strict=True)
    root = Path(os.fsdecode(git_checks.git(repo, 'rev-parse', '--show-toplevel', index=False).stdout).strip()).resolve()
    if root != repo:
        raise QualityError('Select the worktree root')
    setting = git_checks.git(repo, 'config', '--get-all', 'core.hooksPath', index=False, check=False)
    if setting.returncode == 0:
        raise QualityError('core.hooksPath is configured; refusing to modify hooks')
    if setting.returncode != 1:
        raise QualityError('Cannot inspect core.hooksPath')
    common = Path(os.fsdecode(git_checks.git(repo, 'rev-parse', '--git-common-dir', index=False).stdout).strip())
    if not common.is_absolute(): common = repo / common
    common = common.resolve()
    hooks = common / 'hooks'
    config = repo / CONFIG
    for path in (repo / '.agent-work', repo / '.agent-work/tasks', config.parent, config,
                 hooks, hooks / 'pre-commit', hooks / 'quality-runner.py'):
        if path.is_symlink() or path.resolve() != path.absolute():
            raise QualityError(f'Refusing redirected hook path: {path}')
    return config, hooks / 'pre-commit', hooks / 'quality-runner.py'


def _read_config(config):
    raw = config.read_bytes()
    python, data = raw.split(b'\n', 1)
    value = json.loads(data)
    if not isinstance(value, dict) or set(value) != {'assignment', 'assignment_sha256'}:
        raise QualityError('Invalid hook configuration')
    python = os.fsdecode(python)
    if not Path(python).is_absolute() or '\n' in python:
        raise QualityError('Hook Python must be an absolute path')
    a, pin = value['assignment'], value['assignment_sha256']
    if bool(a) != bool(pin) or (a is not None and (not isinstance(a, str) or not Path(a).is_absolute())):
        raise QualityError('Invalid assignment binding')
    return python, a, pin


def _check_entrypoint(repo):
    path = 'harness/scripts/quality.py'
    if git_checks.git(repo, 'ls-files', '--unmerged', '-z', '--', path).stdout:
        raise QualityError(f'The selected index must contain one stage-0 regular {path}')
    entries = git_checks.git(repo, 'ls-files', '--stage', '-z', '--', path).stdout.split(b'\0')
    entries = [entry for entry in entries if entry]
    if len(entries) != 1:
        raise QualityError(f'The selected index must contain one stage-0 regular {path}')
    try:
        meta, name = entries[0].split(b'\t', 1)
        mode, _, stage = meta.split()
    except ValueError as exc:
        raise QualityError(f'Cannot inspect staged {path}') from exc
    if name != path.encode() or mode not in (b'100644', b'100755') or stage != b'0':
        raise QualityError(f'The selected index must contain one stage-0 regular {path}')
    diff = git_checks.git(repo, 'diff', '--cached', '--raw', '-z', '--no-abbrev', '--no-renames', '--ita-invisible-in-index', '--ignore-submodules=none', '--no-ext-diff', 'HEAD', '--', path).stdout
    if diff:
        fields = diff.split(b'\0')
        if len(fields) != 3 or fields[1] != path.encode() or fields[2]:
            raise QualityError(f'Cannot inspect staged {path}')
        parts = fields[0].split()
        if len(parts) != 5 or parts[1] not in (b'100644', b'100755') or parts[4] not in (b'A', b'M', b'T'):
            raise QualityError(f'The selected index must contain one stage-0 regular {path}')
    else:
        tree = git_checks.git(repo, 'ls-tree', '-z', 'HEAD', '--', path).stdout
        if not tree.startswith((b'100644 blob ', b'100755 blob ')):
            raise QualityError(f'The selected index must contain one stage-0 regular {path}')


def hook_status(repo):
    result = {'state': 'unavailable', 'diagnostics': [], 'python': None, 'assignment': None, 'assignment_sha256': None}
    try:
        config, launcher, runner = _locations(repo)
        for path, expected in ((launcher, LAUNCHER), (runner, RUNNER)):
            if path.exists() and (not path.is_file() or path.read_bytes() != expected):
                raise QualityError(f'Foreign hook conflicts with installation: {path}')
        if not config.exists():
            result['state'] = 'not_configured'
            return result
        python, assignment, pin = _read_config(config)
        result.update(python=python, assignment=assignment, assignment_sha256=pin)
        if launcher.read_bytes() != LAUNCHER or runner.read_bytes() != RUNNER:
            raise QualityError('Installed hook or runner differs from owned bytes')
        _check_entrypoint(repo)
        if os.name != 'nt' and not launcher.stat().st_mode & 0o111:
            raise QualityError('Installed hook is not executable')
        probe = subprocess.run([python, '-I', '-B', '-S', '-c', 'import sys; sys.exit(sys.version_info < (3,10))'], timeout=5)
        if probe.returncode: raise QualityError('Hook Python probe failed')
        result['state'] = 'ready'
    except (QualityError, OSError, ValueError, TypeError, subprocess.SubprocessError) as exc:
        result['diagnostics'].append({'code': 'hook-unavailable', 'message': str(exc)})
    return result


def add_commands(subparsers):
    parser = subparsers.add_parser('hooks', help='manage optional per-worktree pre-commit checks')
    actions = parser.add_subparsers(dest='action', required=True)
    install = actions.add_parser('install')
    install.add_argument('--python', required=True, type=Path)
    install.add_argument('--assignment', type=Path)
    install.add_argument('--assignment-sha256')
    actions.add_parser('status')
    actions.add_parser('uninstall')
    pre = subparsers.add_parser('precommit', help='run checks on the staged index')
    pre.add_argument('--snapshot', type=Path, help=argparse.SUPPRESS)
    pre.add_argument('--binding', type=Path, help=argparse.SUPPRESS)


def _manage(args, repo):
    config, launcher, runner = _locations(repo)
    if args.action == 'status':
        status = hook_status(repo)
        return {'command': 'hooks status', 'ok': status['state'] != 'unavailable', **status}
    for path, expected in ((launcher, LAUNCHER), (runner, RUNNER)):
        if path.exists() and (not path.is_file() or path.read_bytes() != expected):
            raise QualityError(f'Refusing to replace or remove foreign hook: {path}')
    if args.action == 'uninstall':
        # Shared launcher remains for other worktrees; only disable this one.
        if config.exists():
            _read_config(config)
            config.unlink()
        return {'command': 'hooks uninstall', 'ok': True, 'diagnostics': []}
    _check_entrypoint(repo)
    python = args.python.resolve(strict=True)
    if '\n' in str(python): raise QualityError('Invalid Python path')
    probe = subprocess.run([str(python), '-I', '-B', '-S', '-c', 'import sys; sys.exit(sys.version_info < (3,10))'], timeout=5)
    if probe.returncode: raise QualityError('Python 3.10 or newer is required')
    if bool(args.assignment) != bool(args.assignment_sha256):
        raise QualityError('Supply both assignment and SHA-256')
    assignment = str(args.assignment.resolve(strict=True)) if args.assignment else None
    if assignment:
        loaded = git_checks.load_assignment(assignment, args.assignment_sha256)
        git_checks.validate_checkout(repo, loaded)
    if git_checks.git(repo, 'check-ignore', '-q', '--', CONFIG.as_posix(), index=False, check=False).returncode:
        raise QualityError('Per-worktree configuration must be Git-ignored')
    if config.exists(): _read_config(config)
    launcher.parent.mkdir(parents=True, exist_ok=True)
    if not runner.exists():
        with runner.open('xb') as stream: stream.write(RUNNER)
    if not launcher.exists():
        with launcher.open('xb') as stream: stream.write(LAUNCHER)
        launcher.chmod(0o755)
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_bytes(os.fsencode(str(python)) + b'\n' + json.dumps({'assignment': assignment, 'assignment_sha256': args.assignment_sha256}).encode())
    status = hook_status(repo)
    return {'command': 'hooks install', 'ok': status['state'] == 'ready', **status}


def _precommit(args, repo):
    if not args.snapshot and not args.binding:
        status = hook_status(repo)
        if status['state'] != 'ready':
            raise QualityError('Configure the optional hook before running precommit')
        config, _, _ = _locations(repo)
        result = subprocess.run([status['python'], '-E', '-S', '-B', '-c', RUNNER.decode('utf-8'), str(repo), str(config)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=310)
        output = result.stdout.decode('utf-8', 'replace')
        return {'command': 'precommit', 'ok': result.returncode == 0,
                'diagnostics': [] if result.returncode == 0 else [{'code': 'precommit-failed', 'message': output}],
                'output': output}
    if not args.snapshot or not args.binding:
        raise QualityError('Incomplete staged snapshot binding')
    snapshot = args.snapshot.resolve(strict=True)
    config, _, _ = _locations(repo)
    if args.binding.resolve() != config.resolve(): raise QualityError('Incorrect hook binding')
    python, assignment, pin = _read_config(config)
    before = git_checks.git_identity(repo)
    diagnostics = []
    if assignment:
        staged = git_checks.run_command(argparse.Namespace(assignment=Path(assignment), assignment_sha256=pin), repo)
        diagnostics.extend(staged['diagnostics'])
    from .validation import validate_repository
    validation = validate_repository(snapshot)
    diagnostics.extend(validation['diagnostics'])
    paths = git_checks.changed_paths(git_checks.git(repo, 'diff', '--cached', '--name-status', '-z', '--find-renames', '--no-ext-diff', '--ignore-submodules=none').stdout)
    tests = [snapshot / 'harness/tests' / name for name in select_tests(paths)]
    test_env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
    for test in tests:
        if not test.is_file():
            diagnostics.append({'code': 'tests-missing', 'path': test.relative_to(snapshot).as_posix(), 'message': 'Required selected test is absent from index'})
            continue
        result = subprocess.run([python, '-E', '-S', '-B', '-m', 'unittest', 'discover', '-s', 'harness/tests', '-p', test.name], cwd=snapshot, env=test_env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=120)
        output = result.stdout.decode('utf-8', 'replace')
        count = re.search(r'Ran (\d+) tests?', output)
        if result.returncode or not count or int(count.group(1)) == 0 or 'skipped=' in output:
            diagnostics.append({'code': 'test-failed', 'path': test.relative_to(snapshot).as_posix(), 'message': output})
    if git_checks.git_identity(repo) != before:
        diagnostics.append({'code': 'changed-input', 'message': 'HEAD or index changed during checks'})
    if assignment:
        git_checks.validate_checkout(repo, git_checks.load_assignment(assignment, pin))
    return {'command': 'precommit', 'ok': not diagnostics, 'diagnostics': diagnostics, 'tests': [p.name for p in tests], 'index_sha256': before['index_sha256'], 'delivery': 'Run the full harness suite before delivery.'}


def run_command(args, repo):
    try:
        return _manage(args, repo) if args.command == 'hooks' else _precommit(args, repo)
    except subprocess.SubprocessError as exc:
        raise QualityError(f'Hook operation failed: {exc}') from exc
