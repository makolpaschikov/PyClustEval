"""Maintain the Markdown harness journals using only the Python standard library."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import date
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile


FILES = {"signal": "SIGNALS.md", "decision": "DECISIONS.md"}
PREFIXES = {"signal": "SIG", "decision": "DEC"}
STATUSES = {
    "signal": {"open", "investigating", "awaiting_agreement", "in_progress",
               "resolved", "deferred", "rejected", "duplicate"},
    "decision": {"proposed", "agreed", "implemented", "verified", "deferred",
                 "rejected", "superseded"},
}
FIELDS = {
    "signal": ("date", "origin", "owner", "request", "evidence", "status", "decisions"),
    "decision": ("date", "signals", "status", "decision", "why", "agreement", "result", "check"),
}
OPTIONAL = {
    "signal": ("agreement", "duplicate_of", "details"),
    "decision": ("supersedes", "details"),
}
LABELS = {"signals": "Signal", "decisions": "Decision", "duplicate_of": "Duplicate of"}
REFERENCES = {"signals": "SIG", "decisions": "DEC", "duplicate_of": "SIG", "supersedes": "DEC"}
ID_RE = re.compile(r"(?:SIG|DEC)-[0-9]{3,}")
DEFAULT_DIR = Path(__file__).resolve().parents[1] / "signals"
PENDING = {"pending", "none", "not started", "not run", "not recorded", "n/a"}
LOCKED_DECISION_FIELDS = {"signals", "decision", "why", "agreement", "supersedes"}


class JournalError(Exception):
    pass


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def text(value, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise JournalError(f"{name}: expected nonempty text")
    if any(ord(char) < 32 and char not in "\n\r\t" for char in value):
        raise JournalError(f"{name}: control characters are not allowed")
    return " ".join(value.split())


def reference_list(value, name: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise JournalError(f"{name}: expected an array of IDs")
    if len(set(value)) != len(value):
        raise JournalError(f"{name}: duplicate reference")
    prefix = REFERENCES[name]
    if any(not re.fullmatch(prefix + r"-[0-9]{3,}", item) for item in value):
        raise JournalError(f"{name}: invalid reference")
    return value.copy()


def normalize(kind: str, data: dict, *, partial=False) -> dict:
    if not isinstance(data, dict):
        raise JournalError("Record input must be a JSON object")
    allowed = {"title", *FIELDS[kind], *OPTIONAL[kind]}
    if unknown := set(data) - allowed:
        raise JournalError(f"Unknown or immutable fields: {', '.join(sorted(unknown))}")
    result = {}
    for key, value in data.items():
        if value is None and key in OPTIONAL[kind]:
            result[key] = None
        elif key in REFERENCES:
            result[key] = reference_list(value, key)
        else:
            result[key] = text(value, key)
    if not partial:
        missing = {"title", *FIELDS[kind]} - result.keys()
        if missing:
            raise JournalError(f"Missing fields: {', '.join(sorted(missing))}")
    return result


def header(kind: str, version: int = 2) -> str:
    return f"# Harness {FILES[kind][:-3].lower()}\n\n<!-- journal-format: {version} -->\n"


def label(key: str) -> str:
    return LABELS.get(key, key.capitalize())


def render(kind: str, records: list[dict]) -> bytes:
    lines = [header(kind).rstrip()]
    for record in records:
        lines += ["", f'<a id="{record["id"].lower()}"></a>',
                  f'## {record["id"]}: {record["title"]}', ""]
        for key in (*FIELDS[kind], *OPTIONAL[kind]):
            if key not in record:
                continue
            value = record[key]
            if key in REFERENCES:
                target = "SIGNALS.md" if REFERENCES[key] == "SIG" else "DECISIONS.md"
                value = ", ".join(f"[{item}]({target}#{item.lower()})" for item in value) or "none"
            lines.append(f"- {label(key)}: {value}")
    return ("\n".join(lines) + "\n").encode("utf-8")


def parse(kind: str, raw: bytes, *, legacy_history=False) -> list[dict]:
    try:
        content = raw.decode("utf-8-sig").replace("\r\n", "\n")
    except UnicodeDecodeError as exc:
        raise JournalError(f"{FILES[kind]}: invalid UTF-8") from exc
    opening = header(kind, 1 if legacy_history else 2)
    if not content.startswith(opening):
        raise JournalError(f"{FILES[kind]}: unsupported format; use the appropriate migrate command")
    records = []
    record = None
    anchor = None
    in_history = False
    names = {label(key): key for key in (*FIELDS[kind], *OPTIONAL[kind])}
    for line in content[len(opening):].splitlines():
        if not line:
            continue
        if match := re.fullmatch(r'<a id="((?:sig|dec)-[0-9]{3,})"></a>', line):
            if anchor is not None:
                raise JournalError("Duplicate or orphaned record anchor")
            anchor = match[1]
            continue
        if match := re.fullmatch(r"## ((?:SIG|DEC)-[0-9]{3,}): (.+)", line):
            if anchor != match[1].lower():
                raise JournalError(f"{match[1]}: missing or incorrect stable anchor")
            record = {"id": match[1], "title": match[2]}
            records.append(record)
            anchor = None
            in_history = False
            continue
        if record is None or anchor is not None:
            raise JournalError(f"Unexpected content: {line[:100]}")
        if legacy_history and line == "- History:":
            if "_legacy_history" in record:
                raise JournalError(f'{record["id"]}: duplicate History')
            record["_legacy_history"] = []
            in_history = True
        elif in_history and line.startswith("  - "):
            record["_legacy_history"].append(line[4:])
        elif match := re.fullmatch(r"- ([A-Za-z ]+): (.+)", line):
            if in_history or match[1] not in names:
                raise JournalError(f"Unknown or misplaced field: {match[1]}")
            key = names[match[1]]
            if key in record:
                raise JournalError(f'{record["id"]}: duplicate {match[1]}')
            value = match[2]
            if key in REFERENCES:
                if value == "none":
                    value = []
                else:
                    items = value.split(", ")
                    value = []
                    target = "SIGNALS.md" if REFERENCES[key] == "SIG" else "DECISIONS.md"
                    for item in items:
                        ref = re.fullmatch(r"\[((?:SIG|DEC)-[0-9]{3,})\]\(([^)]+)\)", item)
                        if not ref or ref[2] != f"{target}#{ref[1].lower()}":
                            raise JournalError(f"Malformed reference: {item}")
                        value.append(ref[1])
            record[key] = value
        else:
            raise JournalError(f"Unexpected content: {line[:100]}")
    if anchor is not None:
        raise JournalError("Orphaned record anchor")
    if legacy_history:
        for record in records:
            if not record.pop("_legacy_history", None):
                raise JournalError(f'{record["id"]}: missing legacy History block')
    return records


def supplied(value: str) -> bool:
    return value.strip().lower().rstrip(".") not in PENDING


def validate(journals: dict[str, list[dict]]) -> None:
    index = {}
    for kind, records in journals.items():
        for record in records:
            rid = record.get("id", "")
            if (not isinstance(rid, str) or not re.fullmatch(PREFIXES[kind] + r"-[0-9]{3,}", rid)
                    or int(rid.split("-")[1]) < 1
                    or rid != f'{PREFIXES[kind]}-{int(rid.split("-")[1]):03d}'):
                raise JournalError(f"Invalid {kind} ID: {rid}")
            if rid in index:
                raise JournalError(f"Duplicate ID: {rid}")
            index[rid] = record
            fields = {key: value for key, value in record.items() if key != "id"}
            if normalize(kind, fields) != fields:
                raise JournalError(f"{rid}: noncanonical whitespace or empty optional field")
            try:
                if date.fromisoformat(record["date"]).isoformat() != record["date"]:
                    raise ValueError()
            except ValueError as exc:
                raise JournalError(f"{rid}: date must be YYYY-MM-DD") from exc
            if record["status"] not in STATUSES[kind]:
                raise JournalError(f"{rid}: invalid status {record['status']}")
            if kind == "decision":
                if not record["signals"]:
                    raise JournalError(f"{rid}: at least one signal is required")
                if record["status"] in {"agreed", "implemented", "verified", "rejected", "deferred", "superseded"}:
                    if not supplied(record["agreement"]):
                        raise JournalError(f"{rid}: human agreement/rejection/deferment is required")
                if record["status"] in {"implemented", "verified"} and not supplied(record["result"]):
                    raise JournalError(f"{rid}: implementation result is required")
                if record["status"] == "verified" and not supplied(record["check"]):
                    raise JournalError(f"{rid}: verification evidence and limits are required")
            if kind == "signal" and record["status"] == "duplicate" and len(record.get("duplicate_of", [])) != 1:
                raise JournalError(f"{rid}: duplicate status requires one original signal")
    for kind, records in journals.items():
        for record in records:
            rid = record["id"]
            for field in REFERENCES:
                for target in record.get(field, []):
                    if target == rid or target not in index:
                        raise JournalError(f"{rid}: invalid/missing {field} target {target}")
            if kind == "signal":
                linked = [index[item] for item in record["decisions"]]
                if any(rid not in item["signals"] for item in linked):
                    raise JournalError(f"{rid}: decision does not refer back to this signal")
                if record["status"] == "resolved":
                    active = [item for item in index.values() if item["id"].startswith("DEC-")
                              and rid in item["signals"] and item["status"] != "superseded"]
                    if (not any(item["status"] == "verified" for item in active)
                            or any(item["status"] in {"proposed", "agreed", "implemented", "deferred"} for item in active)):
                        raise JournalError(f"{rid}: unresolved decisions or no verified decision")
            if kind == "decision":
                for target in record.get("supersedes", []):
                    if not set(record["signals"]) & set(index[target]["signals"]):
                        raise JournalError(f"{rid}: superseded decision must share a signal")
    for relation in ("duplicate_of", "supersedes"):
        def visit(rid, path):
            if rid in path:
                raise JournalError(f"Cycle in {relation}: {rid}")
            for target in index[rid].get(relation, []):
                visit(target, path | {rid})
        for rid in index:
            visit(rid, set())
    def accepted_replacement(rid):
        return any(
            rid in item.get("supersedes", [])
            and (item["status"] in {"agreed", "implemented", "verified"}
                 or (item["status"] == "superseded" and accepted_replacement(item["id"])))
            for item in index.values()
        )
    for record in journals["decision"]:
        if record["status"] == "superseded" and not accepted_replacement(record["id"]):
            raise JournalError(f'{record["id"]}: no agreed replacement decision in its supersession chain')


def snapshot(directory: Path) -> dict[str, bytes]:
    try:
        return {kind: (directory / filename).read_bytes() for kind, filename in FILES.items()}
    except OSError as exc:
        raise JournalError(f"Cannot read journals: {exc}") from exc


def load(raw: dict[str, bytes]) -> dict[str, list[dict]]:
    records = {kind: parse(kind, data) for kind, data in raw.items()}
    validate(records)
    return records


@contextmanager
def writer_lock(directory: Path):
    path = directory / ".journal.lock"
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise JournalError(f"Writer lock exists: {path}; inspect the owner, do not bypass it") from exc
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(f"pid={os.getpid()}\n")
        yield
    finally:
        path.unlink()


def atomic_write(path: Path, data: bytes) -> None:
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def save(directory: Path, before: dict[str, bytes], after: dict[str, bytes]) -> None:
    if snapshot(directory) != before:
        raise JournalError("Journal changed during preparation; reread and retry")
    written = []
    try:
        for kind in FILES:
            if before[kind] != after[kind]:
                atomic_write(directory / FILES[kind], after[kind])
                written.append(kind)
    except OSError as exc:
        for kind in reversed(written):
            atomic_write(directory / FILES[kind], before[kind])
        raise JournalError(f"Write failed; previous journal content restored: {exc}") from exc


def create(directory: Path, kind: str, payload: dict) -> str:
    with writer_lock(directory):
        before = snapshot(directory)
        journals = load(before)
        defaults = {"date": date.today().isoformat(), "status": "open" if kind == "signal" else "proposed"}
        defaults.update({"decisions": []} if kind == "signal" else
                        {"agreement": "pending", "result": "pending", "check": "pending"})
        record = normalize(kind, {**defaults, **payload})
        record = {key: value for key, value in record.items() if value is not None}
        number = max((int(item["id"].split("-")[1]) for item in journals[kind]), default=0) + 1
        rid = f"{PREFIXES[kind]}-{number:03d}"
        record["id"] = rid
        journals[kind].append(record)
        validate(journals)
        save(directory, before, {**before, kind: render(kind, journals[kind])})
        return rid


def update(directory: Path, rid: str, patch: dict, expected: str) -> bool:
    kind = "signal" if rid.startswith("SIG-") else "decision"
    with writer_lock(directory):
        before = snapshot(directory)
        if digest(before[kind]) != expected:
            raise JournalError("Stale journal revision; reread, reconcile the patch, and retry")
        journals = load(before)
        record = next((item for item in journals[kind] if item["id"] == rid), None)
        if record is None:
            raise JournalError(f"Unknown ID: {rid}")
        patch = normalize(kind, patch, partial=True)
        if "date" in patch and patch["date"] != record["date"]:
            raise JournalError("Creation date is immutable")
        changed = {key for key, value in patch.items() if record.get(key) != value}
        if not changed:
            return False
        if kind == "decision" and record["status"] in {"agreed", "implemented", "verified", "superseded", "rejected"}:
            if changed & LOCKED_DECISION_FIELDS:
                raise JournalError("Decision substance/approval is locked; create a superseding DEC")
            if patch.get("status") in {"proposed", "deferred"}:
                raise JournalError("An agreed/rejected decision cannot return to draft; create a new DEC")
        for key, value in patch.items():
            if value is None:
                record.pop(key, None)
            else:
                record[key] = value
        validate(journals)
        save(directory, before, {**before, kind: render(kind, journals[kind])})
        return True


def migrate(directory: Path, plan: dict) -> None:
    """Apply a reviewed replacement, refusing omitted IDs and stale source files."""
    if not isinstance(plan, dict) or set(plan) != {"expected_sha256", "signals", "decisions"}:
        raise JournalError("Migration requires expected_sha256, signals, and decisions")
    with writer_lock(directory):
        before = snapshot(directory)
        if any(b"<!-- journal-format:" in raw for raw in before.values()):
            raise JournalError("Already migrated; use create/update or migrate --remove-history for version 1")
        if plan["expected_sha256"] != {FILES[kind]: digest(raw) for kind, raw in before.items()}:
            raise JournalError("Migration source changed; review the plan again")
        journals = {}
        for kind, name in (("signal", "signals"), ("decision", "decisions")):
            if not isinstance(plan[name], list):
                raise JournalError(f"{name}: expected a list")
            ids = re.findall(r"(?m)^## ((?:SIG|DEC)-[0-9]{3,}):", before[kind].decode("utf-8-sig"))
            if not ids or len(set(ids)) != len(ids):
                raise JournalError(f"{FILES[kind]}: legacy IDs missing or duplicated")
            journals[kind] = []
            for original in plan[name]:
                if not isinstance(original, dict) or "id" not in original:
                    raise JournalError("Migrated records must supply their original ID")
                record = normalize(kind, {key: value for key, value in original.items() if key != "id"})
                record = {key: value for key, value in record.items() if value is not None}
                record["id"] = original["id"]
                journals[kind].append(record)
            if [item["id"] for item in journals[kind]] != ids:
                raise JournalError(f"{FILES[kind]}: migration must preserve every ID and its order")
        validate(journals)
        save(directory, before, {kind: render(kind, records) for kind, records in journals.items()})


def remove_history(directory: Path) -> bool:
    """Upgrade v1 journals without changing any current record field."""
    with writer_lock(directory):
        before = snapshot(directory)
        journals = {}
        has_v1 = False
        for kind, raw in before.items():
            normalized = raw.removeprefix(b"\xef\xbb\xbf").replace(b"\r\n", b"\n")
            legacy = normalized.startswith(header(kind, 1).encode("utf-8"))
            has_v1 = has_v1 or legacy
            journals[kind] = parse(kind, raw, legacy_history=legacy)
        validate(journals)
        if not has_v1:
            return False
        save(directory, before, {kind: render(kind, records) for kind, records in journals.items()})
        return True


def read_json(path: Path) -> dict:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise JournalError(f"Duplicate JSON key: {key}")
            result[key] = value
        return result
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"), object_pairs_hook=unique)
    except (OSError, ValueError) as exc:
        raise JournalError(f"Cannot read JSON input: {exc}") from exc
    if not isinstance(data, dict):
        raise JournalError("Input must be a JSON object")
    return data


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--journal-dir", type=Path, default=DEFAULT_DIR,
                        help="journal directory; use an isolated directory for fixtures")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check", help="read-only validation and revision hashes")
    new = commands.add_parser("create")
    new.add_argument("kind", choices=FILES)
    edit = commands.add_parser("update")
    edit.add_argument("id")
    edit.add_argument("--expect-sha256", required=True, help="target journal hash reported by check")
    migration = commands.add_parser("migrate")
    for command in (new, edit):
        command.add_argument("--input", type=Path, required=True)
    migration_mode = migration.add_mutually_exclusive_group(required=True)
    migration_mode.add_argument("--input", type=Path, help="reviewed plan for unversioned legacy journals")
    migration_mode.add_argument("--remove-history", action="store_true",
                                help="upgrade v1 to v2, removing only automatic History blocks")
    args = parser.parse_args(argv)
    try:
        directory = args.journal_dir.resolve()
        if args.command == "check":
            if (directory / ".journal.lock").exists():
                raise JournalError("Writer lock exists; retry after the writer finishes")
            before = snapshot(directory)
            journals = load(before)
            if snapshot(directory) != before:
                raise JournalError("Journals changed while checking; retry")
            for kind, raw in before.items():
                print(f"{FILES[kind]}: {len(journals[kind])} records; sha256={digest(raw)}")
        elif args.command == "create":
            print(create(directory, args.kind, read_json(args.input)))
        elif args.command == "update":
            if not ID_RE.fullmatch(args.id):
                raise JournalError("Invalid record ID")
            changed = update(directory, args.id, read_json(args.input), args.expect_sha256)
            print(f"{args.id}: {'updated' if changed else 'unchanged'}")
        elif args.remove_history:
            changed = remove_history(directory)
            print("Automatic history removed; current fields preserved" if changed else "Already version 2; unchanged")
        else:
            migrate(directory, read_json(args.input))
            print("Both journals migrated without automatic history")
        return 0
    except (JournalError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
