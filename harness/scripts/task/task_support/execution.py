"""Run explicitly selected planned checks and preserve bounded raw evidence."""
from __future__ import annotations
from datetime import datetime, timezone
import math
import os
from pathlib import Path
import signal
import subprocess
import threading
import time
import uuid
from .artifacts import git, load, repository, workspace
from .bundles import MAX_FILE_SIZE, contexts_match, write_bundle
from .formats import TaskError, identifier, require
from .lint import lint
from .snapshots import capture_context

COMMANDS = ('run-check',)

def add_commands(subparsers):
    p = subparsers.add_parser('run-check', help='run an explicit planned check')
    p.add_argument('directory',type=Path); p.add_argument('--id',required=True)
    p.add_argument('--check-id',required=True); p.add_argument('--source-repo',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True); p.add_argument('--timeout',type=float,required=True)


def _time(): return datetime.now(timezone.utc).isoformat()

def _stop(p):
    if p.poll() is not None: return
    if os.name == 'nt':
        try:
            subprocess.run(['taskkill','/PID',str(p.pid),'/T','/F'], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW, check=False)
        except (OSError,subprocess.TimeoutExpired): pass
    else:
        try: os.killpg(p.pid,signal.SIGKILL)
        except ProcessLookupError: pass
    if p.poll() is None:
        try: p.kill()
        except OSError: pass
    try: p.wait(timeout=10)
    except subprocess.TimeoutExpired: pass

def _drain(stream, path, exceeded, errors):
    written=0
    try:
        with path.open('xb') as out:
            while True:
                block=stream.read(65536)
                if not block: break
                allowed=max(0, MAX_FILE_SIZE-written)
                if allowed: out.write(block[:allowed]); written += min(allowed,len(block))
                if len(block)>allowed: exceeded.set()
    except OSError as exc:
        errors.append(str(exc)); exceeded.set()
    finally:
        stream.close()

def _safe_output(source, value):
    value = Path(value)
    if not value.is_absolute(): value=source/value
    # Reject symlink traversal even if it resolves within the task workspace.
    absolute=Path(os.path.abspath(value))
    allowed=source/'.agent-work'/'tasks'
    require(absolute.is_relative_to(allowed) and absolute != allowed, 'Output must be inside source task workspace')
    resolved_root = allowed.resolve()
    resolved_output = absolute.resolve()
    require(resolved_root == allowed and resolved_output.is_relative_to(resolved_root) and resolved_output != resolved_root, 'Output resolves outside source task workspace')
    current=source
    for part in absolute.relative_to(source).parts:
        current=current/part
        require(not current.is_symlink(), 'Output path must not contain symlinks')
    require(absolute.parent.is_dir() and not absolute.exists(), 'Output parent must exist and output must be new')
    git(source,'check-ignore','--quiet','--',absolute.relative_to(source).as_posix())
    return absolute

def run_command(args, repo):
    source=repository(args.source_repo); directory=workspace(repo,args.directory)
    require(math.isfinite(args.timeout) and args.timeout>0, 'Timeout must be positive and finite')
    identifier(args.check_id,'check id')
    argv=args.argv[1:] if args.argv and args.argv[0]=='--' else args.argv
    require(argv and all(isinstance(a,str) and a and '\x00' not in a for a in argv), 'Explicit argv required after --')
    output=_safe_output(source,args.output)
    before=capture_context(repo,directory,args.id,source)
    manifest,revision=load(directory); index,_=lint(repo,directory,manifest)
    require(manifest['scope'] != 'application' or manifest['application_authorization'] is not None, 'Application authorization record required')
    planned={v for values in index[args.id]['verification'].values() for v in values}
    require(args.check_id in planned, 'Check is not planned')
    # Validate again after reading the plan, closing the validation/capture window.
    require(contexts_match(before,capture_context(repo,directory,args.id,source),execution=True) and load(directory)[1] == revision, 'Inputs changed before execution')
    attempt=output.parent / ('.run-check-' + uuid.uuid4().hex)
    attempt.mkdir()
    stdout=attempt/'stdout.bin'; stderr=attempt/'stderr.bin'; start=_time(); exit_code=None; reason='completed'
    exceeded=threading.Event(); errors=[]; threads=[]; process=None
    try:
        options={'cwd':str(source),'stdin':subprocess.DEVNULL,'stdout':subprocess.PIPE,'stderr':subprocess.PIPE,'shell':False}
        if os.name=='nt': options['creationflags']=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
        else: options['start_new_session']=True
        try:
            process=subprocess.Popen(argv,**options)
        except OSError as exc:
            reason='launch_error'; stdout.write_bytes(b''); stderr.write_bytes(str(exc).encode('utf-8',errors='replace'))
        if process is not None:
            for stream,path in ((process.stdout,stdout),(process.stderr,stderr)):
                t=threading.Thread(target=_drain,args=(stream,path,exceeded,errors),daemon=True); t.start(); threads.append(t)
            deadline=time.monotonic()+args.timeout
            try:
                while process.poll() is None:
                    if exceeded.is_set(): reason='output_limit'; break
                    if time.monotonic() >= deadline: reason='timeout'; break
                    time.sleep(.02)
            except KeyboardInterrupt:
                reason='interrupted'
            if reason != 'completed': _stop(process)
            exit_code=process.poll()
            for t in threads: t.join(timeout=2)
            if any(t.is_alive() for t in threads):
                # A descendant may retain inherited pipes. Do not finalize evidence.
                _stop(process)
                raise TaskError(f'Output streams did not close; raw attempt retained at {attempt}')
            require(not errors, f'Could not capture raw output; attempt retained at {attempt}: {errors}')
            if exceeded.is_set() and reason=='completed': reason='output_limit'
        end=_time(); after=None
        try: after=capture_context(repo,directory,args.id,source)
        except (TaskError,OSError,ValueError): pass
        stable=after is not None and contexts_match(before,after,execution=True)
        if not stable and reason=='completed': reason='input_drift'
        outcome=('passed' if reason=='completed' and exit_code==0 and stable else
                 'not_run' if reason=='launch_error' else 'failed')
        metadata={'format_version':1,'kind':'check','before':before,'after':after,
                  'record':{'id':args.check_id,'command':argv,'exit_code':exit_code,'outcome':outcome},
                  'execution':{'cwd':str(source),'started_at':start,'finished_at':end,'timeout_seconds':args.timeout,
                               'reason':reason,'inputs_stable':stable},'files':[]}
        temp=attempt/'bundle.zip'
        write_bundle(temp,metadata,{'stdout.bin':stdout.read_bytes(),'stderr.bin':stderr.read_bytes()})
        os.link(temp,output) # Atomic no-overwrite publication after full finalization.
        return {'command':'run-check','bundle':str(output),'attempt':str(attempt),'record':metadata['record'],
                'execution':metadata['execution']}, 0 if outcome=='passed' else 1
    except BaseException:
        if process is not None: _stop(process)
        raise
