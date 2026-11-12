"""Versioned structural contract shared by creation, linting and gates."""
from __future__ import annotations

import hashlib
import json
import re

VERSION = 2
DOCUMENT_VERSION = 1
ID = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,63}\Z")
SHA = re.compile(r"[0-9a-f]{64}\Z")
SECTIONS = {
    "epic": ("Request", "Goal", "Scope", "Constraints", "Shared contracts",
             "Requirements", "Acceptance", "Decomposition", "Open questions"),
    "subtask": ("Parent", "Goal", "Scope", "Dependencies", "Deliverables",
                "Acceptance", "Open questions"),
    "specification": ("Request", "Scope", "Requirements", "Behavior",
                      "Architecture and interfaces", "Compatibility",
                      "Acceptance", "Verification", "Open questions"),
}
ITEM_FIELDS = {
    "id", "kind", "parent", "depends_on", "document", "specification", "status",
    "scale", "review_policy", "review_rationale", "coverage", "verification",
    "approval", "spec_reviews", "contributors", "checks", "code_review",
    "findings", "checkpoint", "completion", "mathematics",
}
MANIFEST_FIELDS = {"format_version", "root", "branch", "scope", "coordinator",
                   "application_authorization", "handoff", "items"}


class TaskError(Exception):
    """A diagnosed task-format or workflow error."""


def require(condition, message):
    if not condition:
        raise TaskError(message)


def fields(value, expected, label):
    require(isinstance(value, dict), f"{label}: expected an object")
    require(set(value) == set(expected),
            f"{label}: missing {sorted(set(expected) - set(value))}; "
            f"unknown {sorted(set(value) - set(expected))}")


def nonempty(value, label):
    require(isinstance(value, str) and bool(value.strip()), f"{label}: expected nonempty text")


def identifier(value, label):
    require(isinstance(value, str) and ID.fullmatch(value), f"{label}: invalid ID")


def sha(value, label):
    require(isinstance(value, str) and SHA.fullmatch(value), f"{label}: invalid SHA-256")


def strings(value, label, *, ids=False):
    require(isinstance(value, list), f"{label}: expected a list")
    for entry in value:
        (identifier if ids else nonempty)(entry, label)
    require(len(set(value)) == len(value), f"{label}: duplicate values")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def new_mathematics():
    return {"required": None, "rationale": "", "authors": [],
            "specification_review": None, "implementation_review": None}


def new_item(item_id, kind, parent, document):
    return {
        "id": item_id, "kind": kind, "parent": parent, "depends_on": [],
        "document": document, "specification": None, "status": "draft",
        "scale": "large" if kind == "epic" else "small", "review_policy": "separate",
        "review_rationale": "", "coverage": {}, "verification": {}, "approval": None,
        "spec_reviews": [], "contributors": [], "checks": [], "code_review": None,
        "findings": [], "checkpoint": None, "completion": None,
        "mathematics": new_mathematics(),
    }
