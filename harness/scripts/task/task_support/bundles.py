"""Strict, bounded transport for evidence bundle v1."""
from __future__ import annotations
import json
import math
import os
from pathlib import Path, PurePosixPath
import stat
import zipfile
from .formats import TaskError, digest, fields, identifier, nonempty, require, sha

MAX_ENTRIES = 17
MAX_FILE_SIZE = 8 * 1024 * 1024
MAX_TOTAL_SIZE = 16 * 1024 * 1024 + 1024 * 1024
MAX_ARCHIVE_SIZE = 20 * 1024 * 1024
KINDS = ('check', 'spec_review', 'code_review', 'math_specification', 'math_implementation')

def validate_context(c):
    fields(c, {'format_version','task_root','item_id','spec_sha256','source_sha256','stage','scope_sha256','origin'}, 'context')
    require(type(c['format_version']) is int and c['format_version'] == 1, 'Invalid context version')
    identifier(c['task_root'], 'task_root'); identifier(c['item_id'], 'item_id')
    sha(c['spec_sha256'], 'spec_sha256'); sha(c['source_sha256'], 'source_sha256')
    require(c['stage'] in (None, 'specification', 'implementation'), 'Invalid stage')
    if c['stage'] is None: require(c['scope_sha256'] is None, 'Unexpected scope')
    else: sha(c['scope_sha256'], 'scope_sha256')
    fields(c['origin'], {'repository','branch','head'}, 'origin')
    nonempty(c['origin']['repository'], 'repository'); nonempty(c['origin']['branch'], 'branch')
    head = c['origin']['head']
    require(head is None or (isinstance(head, str) and len(head) in (40,64) and all(x in '0123456789abcdef' for x in head)), 'Invalid head')

def contexts_match(a, b, *, execution=False):
    validate_context(a); validate_context(b)
    keys = ('task_root','item_id','spec_sha256','source_sha256','stage','scope_sha256')
    return all(a[k] == b[k] for k in keys) and (not execution or all(a['origin'][k] == b['origin'][k] for k in ('repository','branch')))

def _name(name):
    require(isinstance(name,str) and name and '\\' not in name and ':' not in name and '\x00' not in name, 'Unsafe payload path')
    p = PurePosixPath(name)
    require(not p.is_absolute() and all(x not in ('', '.', '..') for x in name.split('/')) and name != 'bundle.json', 'Unsafe payload path')

def validate_metadata(m):
    fields(m, {'format_version','kind','before','after','record','execution','files'}, 'bundle')
    require(type(m['format_version']) is int and m['format_version'] == 1, 'Invalid bundle version')
    require(m['kind'] in KINDS, 'Invalid bundle kind')
    validate_context(m['before'])
    if m['after'] is not None: validate_context(m['after'])
    kind = m['kind']; record = m['record']
    stage = {'math_specification':'specification', 'math_implementation':'implementation'}.get(kind)
    require(m['before']['stage'] == stage and (m['after'] is None or m['after']['stage'] == stage), 'Bundle stage mismatch')
    if kind == 'check':
        fields(record, {'id','command','exit_code','outcome'}, 'record'); identifier(record['id'],'check id')
        require(isinstance(record['command'],list) and bool(record['command']) and all(isinstance(x,str) and x and '\x00' not in x for x in record['command']), 'Invalid command')
        require(type(record['exit_code']) is int or record['exit_code'] is None, 'Invalid exit code')
        require(record['outcome'] in ('passed','failed','not_run'), 'Invalid outcome')
        e=m['execution']; fields(e, {'cwd','started_at','finished_at','timeout_seconds','reason','inputs_stable'}, 'execution')
        for k in ('cwd','started_at','finished_at'): nonempty(e[k],k)
        require(type(e['timeout_seconds']) in (int,float) and math.isfinite(e['timeout_seconds']) and e['timeout_seconds'] > 0, 'Invalid timeout')
        require(e['reason'] in ('completed','timeout','interrupted','launch_error','input_drift','output_limit') and type(e['inputs_stable']) is bool, 'Invalid execution')
        stable = m['after'] is not None and contexts_match(m['before'],m['after'],execution=True)
        require(e['inputs_stable'] == stable, 'Inconsistent stability')
        if record['outcome'] == 'passed': require(e['reason'] == 'completed' and record['exit_code'] == 0 and stable, 'Invalid pass')
        if e['reason'] == 'completed': require(record['exit_code'] is not None and record['outcome'] == ('passed' if record['exit_code'] == 0 and stable else 'failed'), 'Invalid completed result')
        if e['reason'] == 'input_drift': require(not stable, 'Drift requires changed or unavailable context')
        if e['reason'] == 'launch_error':
            require(record['exit_code'] is None and record['outcome'] == 'not_run', 'Invalid launch failure')
        if e['reason'] in ('timeout','interrupted','input_drift','output_limit'):
            require(record['outcome'] == 'failed', 'Invalid failed result')
    else:
        expected = {'reviewer','verdict'} | ({'kind'} if kind == 'spec_review' else set())
        fields(record,expected,'record'); nonempty(record['reviewer'],'reviewer')
        require(record['verdict'] in ('accepted','changes_requested','incomplete'), 'Invalid verdict')
        if kind == 'spec_review': require(record['kind'] in ('readiness','alignment','combined'), 'Invalid review kind')
        require(m['execution'] is None, 'Review execution must be null')
    require(isinstance(m['files'],list) and len(m['files']) <= MAX_ENTRIES-1, 'Invalid files')
    names=set(); total=0
    for f in m['files']:
        fields(f,{'path','sha256','size'},'file'); _name(f['path']); sha(f['sha256'],'file hash')
        require(f['path'] not in names, 'Duplicate payload'); names.add(f['path'])
        require(type(f['size']) is int and 0 <= f['size'] <= MAX_FILE_SIZE, 'Payload too large')
        total += f['size']
    require(total <= MAX_TOTAL_SIZE, 'Bundle too large')
    by_name={f['path']: f for f in m['files']}
    if kind == 'check':
        require({'stdout.bin','stderr.bin'} <= set(by_name), 'Missing check streams')
    else:
        require('report.bin' in by_name and by_name['report.bin']['size'] > 0, 'Missing or empty review report')

def write_bundle(output, metadata, payloads):
    require(isinstance(payloads,dict), 'Payloads must be a mapping')
    entries=[]
    for name, data in payloads.items():
        _name(name); require(isinstance(data,bytes), 'Payload must be bytes')
        entries.append({'path':name,'sha256':digest(data),'size':len(data)})
    m=dict(metadata); m['files']=sorted(entries,key=lambda f:f['path']); validate_metadata(m)
    manifest=json.dumps(m,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8')
    require(len(manifest) <= 1024*1024, 'Metadata too large')
    # Exclusive creation ensures an existing output is never overwritten.
    output=Path(output)
    with output.open('xb') as raw:
        try:
            with zipfile.ZipFile(raw,'w',compression=zipfile.ZIP_DEFLATED) as z:
                z.writestr('bundle.json',manifest)
                for f in m['files']: z.writestr(f['path'],payloads[f['path']])
        except BaseException:
            raw.close(); output.unlink(missing_ok=True); raise
    return m

def read_bundle(path):
    def pairs(items):
        d={}
        for k,v in items:
            require(k not in d,'Duplicate JSON key'); d[k]=v
        return d
    try:
        path=Path(path); require(path.stat().st_size <= MAX_ARCHIVE_SIZE, 'Archive too large')
        with zipfile.ZipFile(path) as z:
            infos=z.infolist(); require(1 <= len(infos) <= MAX_ENTRIES, 'Invalid entry count')
            names=[i.filename for i in infos]; require(len(set(names)) == len(names) and names.count('bundle.json') == 1, 'Duplicate or missing entry')
            for i in infos:
                require(not i.is_dir() and not stat.S_ISLNK(i.external_attr >> 16) and not (i.flag_bits & 1), 'Invalid ZIP entry')
                if i.filename != 'bundle.json': _name(i.filename)
                require(i.file_size <= (1024*1024 if i.filename == 'bundle.json' else MAX_FILE_SIZE), 'Entry too large')
            require(sum(i.file_size for i in infos) <= MAX_TOTAL_SIZE, 'Bundle too large')
            m=json.loads(z.read('bundle.json').decode('utf-8'),object_pairs_hook=pairs,parse_constant=lambda _: (_ for _ in ()).throw(TaskError('Invalid JSON number')))
            validate_metadata(m)
            require(set(names) == {'bundle.json'} | {f['path'] for f in m['files']}, 'Unexpected ZIP entries')
            payloads={f['path']:z.read(f['path']) for f in m['files']}
            for f in m['files']:
                data=payloads[f['path']]; require(len(data)==f['size'] and digest(data)==f['sha256'], 'Payload mismatch')
            return m,payloads
    except (zipfile.BadZipFile, EOFError, UnicodeError, ValueError, RuntimeError, OSError) as exc:
        raise TaskError(f'Invalid bundle: {exc}') from exc
