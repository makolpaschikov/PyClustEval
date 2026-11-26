"""Read a versioned plan as strict JSON-compatible data and publish complete output files."""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

import yaml


class _Pairs(list):
    """Retain duplicates until the full field path is known."""


class _PlanLoader(yaml.SafeLoader):
    def compose_node(self, parent, index):
        if self.check_event(yaml.AliasEvent):
            event = self.peek_event()
            raise ValueError(f"line {event.start_mark.line + 1}: YAML aliases are unsupported")
        return super().compose_node(parent, index)


_PlanLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    lambda loader, node: _Pairs(loader.construct_pairs(node, deep=True)),
)


def _json_value(value: Any, path: str) -> Any:
    if isinstance(value, _Pairs):
        result = {}
        for key, child in value:
            if not isinstance(key, str):
                raise ValueError(f"{path}: expected a string key, got {key!r}")
            if key in result:
                raise ValueError(f"{path}.{key}: duplicate key")
            result[key] = _json_value(child, f"{path}.{key}")
        return result
    if isinstance(value, list):
        return [_json_value(child, f"{path}[{i}]") for i, child in enumerate(value)]
    if value is None or type(value) in (str, bool, int):
        return value
    if type(value) is float and math.isfinite(value):
        return value
    raise ValueError(f"{path}: expected a finite JSON value, got {value!r}")


def read_document(path: Path) -> dict:
    """Read UTF-8 JSON or YAML; reject duplicate keys and non-JSON values at any depth."""
    try:
        with path.open(encoding="utf-8-sig") as source:
            if path.suffix.lower() == ".json":
                parsed = json.load(source, object_pairs_hook=_Pairs)
            else:
                parsed = yaml.load(source, Loader=_PlanLoader)
        value = _json_value(parsed, "$")
    except (ValueError, yaml.YAMLError, RecursionError) as error:
        raise ValueError(f"{path}: {error}") from error
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected a plan object")
    return value


def fields(value: Any, allowed: set[str], required: set[str], path: str) -> dict:
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected an object")
    for key in value:
        if key not in allowed:
            raise ValueError(f"{path}.{key}: unknown field")
    for key in sorted(required - value.keys()):
        raise ValueError(f"{path}.{key}: missing required field")
    return value


def text_value(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{path}: expected a nonempty string")
    return value


def integer(value: Any, path: str, minimum: int, maximum: int | None = None) -> int:
    if type(value) is not int or value < minimum or maximum is not None and value > maximum:
        upper = f" and <= {maximum}" if maximum is not None else ""
        raise ValueError(f"{path}: expected an integer >= {minimum}{upper}")
    return value


def write_document(document: dict, destination: Path) -> None:
    """Write valid JSON (also readable as YAML) before atomically replacing the destination."""
    data = json.dumps(document, ensure_ascii=False, indent=2, allow_nan=False)
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp = None
    try:
        with NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n",
                                dir=destination.parent, delete=False) as output:
            tmp = Path(output.name)
            output.write(data)
            output.write("\n")
        os.replace(tmp, destination)
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)


def relative_location(path: Path, base_dir: Path) -> str:
    """Spell a path relative to the published document, or absolute across Windows drives."""
    try:
        return Path(os.path.relpath(path, base_dir)).as_posix()
    except ValueError:
        return path.as_posix()


def resolved_for_output(resolved: dict, *, source_dir: Path, output_dir: Path) -> dict:
    """Rebase the archive root; its member references and scientific conditions stay intact."""
    if "historical" not in resolved:
        return resolved
    historical = resolved["historical"]
    archive_root = (source_dir / historical["path"]).resolve()
    return dict(resolved, historical=dict(historical, path=relative_location(archive_root, output_dir)))
