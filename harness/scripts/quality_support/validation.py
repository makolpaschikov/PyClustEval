"""Read-only harness validation.

Metadata supports unquoted single-line name and description text, excluding YAML
indicators and implicit numeric, Boolean and null scalars. Markdown
links support inline [text](path#fragment), ATX headings, explicit HTML id anchors,
comments and fenced code. Reference links and malformed inline links are diagnosed;
this is deliberately not a complete YAML or Markdown implementation.
"""
from __future__ import annotations

import importlib.util
from html.parser import HTMLParser
import os
import stat
import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

COMMANDS = ("validate",)


def add_commands(subparsers):
    subparsers.add_parser("validate", help="read-only checks of maintained harness files")


def run_command(args, repo):
    return validate_repository(repo)


def _load(name, path, package=False):
    spec = importlib.util.spec_from_file_location(name, path, submodule_search_locations=[str(path.parent)] if package else None)
    if spec is None or spec.loader is None:
        raise ValueError(f"Cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _visible(text, *, heading_text=False):
    """Strip fenced code, inline code and HTML comments, retaining line breaks."""
    result, comment, fence = [], False, None
    for line in text.splitlines():
        marker = re.match(r'^\s*(`{3,}|~{3,})(.*)$', line)
        if not comment and marker:
            token, tail = marker.groups()
            if fence is None:
                fence = (token[0], len(token)); result.append(''); continue
            if token[0] == fence[0] and len(token) >= fence[1] and not tail.strip():
                fence = None; result.append(''); continue
        if fence:
            result.append(''); continue
        chunks = []
        while line:
            if comment:
                end = line.find('-->')
                if end < 0: line = ''; continue
                line, comment = line[end + 3:], False
            else:
                m = re.search(r'<!--|`+', line)
                if not m: chunks.append(line); break
                chunks.append(line[:m.start()]); token = m.group(); line = line[m.end():]
                if token == '<!--': comment = True
                else:
                    end = line.find(token)
                    if end < 0: chunks.append(token); continue
                    if heading_text: chunks.append(line[:end])
                    line = line[end + len(token):]
        result.append(''.join(chunks))
    if comment or fence:
        raise ValueError('unclosed HTML comment or fenced code block')
    return '\n'.join(result)


def _anchors(text):
    visible = _visible(text, heading_text=True)
    class AnchorParser(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.ids = set()
        def handle_starttag(self, tag, attrs):
            self.ids.update(value for name, value in attrs if name == 'id' and value is not None)
        handle_startendtag = handle_starttag
    parser = AnchorParser()
    parser.feed(visible)
    parser.close()
    ids = parser.ids
    counts = {}
    for heading in re.findall(r'(?m)^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$', visible):
        heading = re.sub(r'<[^>]+>', '', heading).lower()
        slug = ''.join(c for c in heading if c.isalnum() or c in ' _-').replace(' ', '-')
        n = counts.get(slug, 0); counts[slug] = n + 1
        ids.add(slug if n == 0 else f'{slug}-{n}')
    return ids


def _metadata(path):
    lines = path.read_text(encoding='utf-8-sig').splitlines()
    if not lines or lines[0] != '---': raise ValueError('missing metadata opening delimiter')
    try: end = lines.index('---', 1)
    except ValueError: raise ValueError('missing metadata closing delimiter')
    values = {}
    for line in lines[1:end]:
        m = re.fullmatch(r'(name|description): ([^\s].*)', line)
        if not m: raise ValueError(f'unsupported metadata syntax: {line}')
        key, value = m.groups()
        if key in values: raise ValueError(f'duplicate metadata key: {key}')
        implicit = value.casefold() in {'null', '~', 'true', 'false', 'yes', 'no', 'on', 'off', '.nan', '.inf', '+.inf', '-.inf'}
        numeric = re.fullmatch(r'[+-]?(?:[0-9][0-9_]*(?:\.[0-9_]*)?(?:[eE][+-]?[0-9_]+)?|\.[0-9_]+(?:[eE][+-]?[0-9_]+)?|0[xXoObB][0-9a-fA-F_]+)', value)
        indicator = value[0] in "'\"[]{}>,|&*!%@`#" or value.startswith(('- ', '? ', ': '))
        if indicator or implicit or numeric or ' #' in value or ': ' in value or value.endswith(':'):
            raise ValueError(f'unsupported metadata scalar: {key}')
        values[key] = value
    if set(values) != {'name', 'description'}: raise ValueError('metadata requires name and description')
    if values['name'] != path.parent.name or not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', values['name']):
        raise ValueError('metadata name must match skill directory')


def _safe(repo, path):
    # Do not follow a maintained input through a symlink/junction, even when
    # its current destination happens to remain inside the repository.
    path = Path(path)
    if not path.resolve().is_relative_to(repo):
        raise ValueError('input escapes repository')
    relative = path.relative_to(repo)
    current = repo
    for part in relative.parts:
        current = current / part
        # lstat's Windows reparse flag also covers junctions on Python 3.10.
        attrs = getattr(os.lstat(current), 'st_file_attributes', 0) if current.exists() or current.is_symlink() else 0
        if current.is_symlink() or attrs & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400):
            raise ValueError(f'linked input is unsupported: {current}')
    return path


def _links(repo, path, text):
    visible = _visible(text)
    if re.search(r'(?m)^\s*\[[^\]]+\]:\s*\S|\[[^\]]+\]\[[^\]]*\]', visible):
        raise ValueError('reference-style links are unsupported')
    pattern = re.compile(r'!?\[[^\]\n]*\]\(([^)\n]*)\)')
    targets = [m.group(1) for m in pattern.finditer(visible)]
    if re.search(r'\]\(', pattern.sub('', visible)):
        raise ValueError('malformed or unsupported inline link')
    errors = []
    for target in targets:
        if not target or any(c in target for c in ' \t<>"\'()'):
            errors.append(f'unsupported link target: {target}'); continue
        parsed = urlsplit(target)
        if parsed.scheme or target.startswith('//'): continue
        if parsed.query: errors.append(f'local link query unsupported: {target}'); continue
        dest = (path.parent / unquote(parsed.path)).resolve() if parsed.path else path
        if not dest.is_relative_to(repo): errors.append(f'link escapes repository: {target}'); continue
        try: _safe(repo, (path.parent / unquote(parsed.path)) if parsed.path else path)
        except (OSError, ValueError) as exc: errors.append(f'unsafe target {target}: {exc}'); continue
        if not dest.exists(): errors.append(f'missing target: {target}'); continue
        if parsed.fragment:
            if not dest.is_file(): errors.append(f'anchor target is not a file: {target}'); continue
            try: anchors = _anchors(dest.read_text(encoding='utf-8-sig'))
            except (OSError, UnicodeError, ValueError) as exc:
                errors.append(f'cannot inspect anchor {target}: {exc}'); continue
            if unquote(parsed.fragment) not in anchors: errors.append(f'missing anchor: {target}')
    return errors


def validate_repository(repo):
    # Load owning parsers from the selected checkout, never stale imports, without
    # creating bytecode there. Restore process state for callers such as hooks.
    prefix = '_quality_task_support'
    saved = {k: v for k, v in sys.modules.items() if k == prefix or k.startswith(prefix + '.') or k == '_quality_journal'}
    for key in saved: del sys.modules[key]
    old_bytecode = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        return _validate_repository(repo)
    finally:
        sys.dont_write_bytecode = old_bytecode
        for key in list(sys.modules):
            if key == prefix or key.startswith(prefix + '.') or key == '_quality_journal': del sys.modules[key]
        sys.modules.update(saved)


def _validate_repository(repo):
    repo = Path(repo).resolve()
    diagnostics = []
    def error(code, path, exc):
        try: name = Path(path).relative_to(repo).as_posix()
        except ValueError: name = str(path)
        diagnostics.append({'code': code, 'path': name, 'message': str(exc)})
    root = repo / 'AGENTS.md'
    try:
        _safe(repo, root)
        if len(root.read_bytes()) > 32000: error('agents-size', root, 'exceeds 32,000 UTF-8 bytes')
    except OSError as exc: error('agents-size', root, exc)
    skills = repo / '.agents/skills'
    try:
        _safe(repo, skills)
        _safe(repo, repo / 'harness')
    except (OSError, ValueError) as exc:
        error('input', repo, exc)
        return {'command': 'validate', 'ok': False, 'diagnostics': diagnostics}
    if not skills.is_dir(): error('metadata', skills, 'skills directory missing')
    for directory in sorted(p for p in skills.iterdir() if p.is_dir()) if skills.is_dir() else []:
        if not (directory / 'SKILL.md').is_file(): error('metadata', directory, 'SKILL.md missing')
    for path in sorted(skills.glob('*/SKILL.md')):
        try:
            _safe(repo, path)
            _metadata(path)
        except (OSError, UnicodeError, ValueError) as exc: error('metadata', path, exc)
    docs = [root]
    for tree in (repo / 'harness', skills):
        for base, dirs, files in os.walk(tree, followlinks=False):
            for name in dirs[:]:
                directory = Path(base) / name
                try: _safe(repo, directory)
                except (OSError, ValueError) as exc:
                    error('input', directory, exc)
                    dirs.remove(name)
            docs.extend(Path(base) / name for name in files if name.endswith('.md'))
    docs = sorted(set(docs))
    for path in docs:
        try:
            _safe(repo, path)
            for problem in _links(repo, path, path.read_text(encoding='utf-8-sig')): error('link', path, problem)
        except (OSError, UnicodeError, ValueError) as exc: error('markdown', path, exc)
    try:
        for path in (repo / 'harness/scripts/journal.py', repo / 'harness/signals',
                     repo / 'harness/signals/SIGNALS.md', repo / 'harness/signals/DECISIONS.md'):
            _safe(repo, path)
        journal = _load('_quality_journal', repo / 'harness/scripts/journal.py')
        directory = repo / 'harness/signals'
        before = journal.snapshot(directory)
        if (directory / '.journal.lock').exists(): raise ValueError('journal writer lock exists')
        journal.load(before)
        if journal.snapshot(directory) != before: raise ValueError('journals changed during validation')
    except Exception as exc: error('journal', repo / 'harness/signals', exc)
    try:
        pkg = repo / 'harness/scripts/task/task_support'
        _safe(repo, pkg)
        for source in pkg.glob('*.py'):
            _safe(repo, source)
        _load('_quality_task_support', pkg / '__init__.py', True)
        lint = __import__('_quality_task_support.lint', fromlist=['parse_document'])
        bundles = __import__('_quality_task_support.bundles', fromlist=['validate_context'])
        artifacts = __import__('_quality_task_support.artifacts', fromlist=['initialize'])
        from unittest.mock import MagicMock, patch
        class TemplateChecked(Exception): pass
        for kind in ('epic', 'subtask', 'specification'):
            path = skills / 'analyst-orchestrator/assets' / f'{kind}.md'
            directory = MagicMock()
            directory.exists.return_value = kind == 'subtask'
            directory.__truediv__.return_value.exists.return_value = kind == 'subtask'
            manifest = {'branch': 'probe', 'scope': 'harness', 'items': [
                {'id': 'parent', 'kind': 'epic'}]}
            def consume(content, actual_kind, item_id):
                lint.parse_document_original(content, actual_kind, item_id)
                raise TemplateChecked()
            try:
                _safe(repo, path)
                # Stop immediately after the real producer passes generated text
                # to the real consumer, before any directory or file is created.
                lint.parse_document_original = lint.parse_document
                with patch.object(artifacts, 'git', return_value=b'probe'), \
                     patch.object(artifacts, 'load', return_value=(manifest, 'revision')), \
                     patch.object(lint, 'lint'), patch.object(lint, 'parse_document', side_effect=consume):
                    artifacts.initialize(repo, directory, 'probe', kind, 'probe', 'harness',
                                         'parent' if kind == 'subtask' else None,
                                         'revision' if kind == 'subtask' else None)
                raise ValueError('template producer did not invoke consumer')
            except TemplateChecked:
                pass
            except Exception as exc: error('template', path, exc)
            finally: del lint.parse_document_original
        # Run initialization through its real manifest producer and full lint,
        # replacing only filesystem effects and the document reader in memory.
        # This covers new_item and the manifest assembled by initialize without
        # recreating either schema in the quality checker.
        try:
            directory = MagicMock()
            directory.exists.return_value = False
            directory.__truediv__.return_value.exists.return_value = False
            target = MagicMock()
            target.exists.return_value = False
            document = MagicMock()
            template = (skills / 'analyst-orchestrator/assets/specification.md').read_text(encoding='utf-8')
            document.read_text.return_value = template.replace('{{ID}}', 'probe').replace('{{PARENT}}', 'None')
            with patch.object(artifacts, 'git', return_value=b'probe'), \
                 patch.object(artifacts, 'contained', return_value=target), \
                 patch.object(artifacts, 'atomic_write'), \
                 patch.object(artifacts, 'writer_lock') as lock, \
                 patch.object(lint, 'contained', return_value=document):
                lock.return_value.__enter__.return_value = None
                manifest = artifacts.initialize(repo, directory, 'probe', 'specification',
                                                'probe', 'harness', None, None)
            if not manifest:
                raise ValueError('task producer did not return a manifest')
        except Exception as exc:
            error('compatibility', repo / 'harness/scripts/task', f'task producer/lint: {exc}')
        # Exercise the actual context producer with synthetic read-only dependencies,
        # then pass its output to the bundle consumer.
        snapshots = __import__('_quality_task_support.snapshots', fromlist=['_capture'])
        from unittest.mock import patch
        item = {'id': 'probe'}
        manifest = {'root': 'probe', 'branch': 'probe', 'items': [item]}
        source = {'branch': 'probe', 'source_sha256': 'a' * 64,
                  'origin': {'repository': str(repo), 'branch': 'probe', 'head': None}}
        with patch.object(snapshots, 'repository', side_effect=lambda p: p), patch.object(snapshots, 'workspace', side_effect=lambda r, p: p), patch.object(snapshots, '_load_task', return_value=(manifest, 'rev')), patch.object(snapshots, '_source_inputs', return_value=source), patch.object(snapshots, '_document_inputs', return_value={}), patch.object(snapshots, 'lint', return_value=({'probe': item}, {})), patch.object(snapshots, 'spec_digest', return_value='b' * 64):
            context, _ = snapshots._capture(repo, repo, 'probe', None, None)
        bundles.validate_context(context)
        if not bundles.contexts_match(context, context, execution=True):
            raise ValueError('context consumer rejected producer context')
        # Exercise both archive writer and reader entirely in memory.
        import io
        from types import SimpleNamespace
        archive = io.BytesIO()
        class MemoryFile(io.BytesIO):
            def close(self):
                archive.seek(0); archive.truncate(); archive.write(self.getvalue())
                super().close()
        class MemoryPath:
            def __init__(self, _): pass
            def open(self, mode):
                if mode != 'xb': raise ValueError('unexpected archive open mode')
                return MemoryFile()
            def stat(self): return SimpleNamespace(st_size=len(archive.getvalue()))
            def unlink(self, missing_ok=False): archive.seek(0); archive.truncate()
        real_zip = bundles.zipfile.ZipFile
        def memory_zip(file, *args, **kwargs):
            if isinstance(file, MemoryPath): file = io.BytesIO(archive.getvalue())
            return real_zip(file, *args, **kwargs)
        metadata = {'format_version': 1, 'kind': 'spec_review', 'before': context,
                    'after': None, 'record': {'reviewer': 'probe', 'verdict': 'accepted',
                                               'kind': 'readiness'}, 'execution': None}
        with patch.object(bundles, 'Path', MemoryPath), patch.object(bundles.zipfile, 'ZipFile', side_effect=memory_zip):
            produced = bundles.write_bundle('memory', metadata, {'report.bin': b'probe'})
            consumed, payloads = bundles.read_bundle('memory')
        if produced != consumed or payloads != {'report.bin': b'probe'}:
            raise ValueError('bundle producer/consumer round trip differs')
    except Exception as exc: error('compatibility', repo / 'harness/scripts/task', exc)
    return {'command': 'validate', 'ok': not diagnostics, 'diagnostics': diagnostics}
