"""Structural mathematical review scope; semantic classification stays with the analyst."""
from __future__ import annotations

from .artifacts import spec_digest
from .formats import canonical, digest


def review_scope(index, item, *, descendants=True):
    """Include ancestors/dependencies and an epic's integrated children, not siblings."""
    pending = [(item["id"], descendants and item["kind"] == "epic")]
    visited, included = set(), {}
    while pending:
        item_id, descend = pending.pop()
        if (item_id, descend) in visited:
            continue
        visited.add((item_id, descend))
        current = index[item_id]
        included[item_id] = current
        if current["parent"]:
            pending.append((current["parent"], False))
        pending.extend((dependency, False) for dependency in current["depends_on"])
        if descend:
            pending.extend((child["id"], True) for child in index.values()
                           if child["parent"] == item_id)
    return list(included.values())


def scope_digest(directory, manifest, item, stage):
    """Bind math evidence to included contracts without widening human approval.

    Formulation review covers shared contracts and dependencies before children
    are elaborated. Integrated implementation review additionally covers children.
    """
    index = {entry["id"]: entry for entry in manifest["items"]}
    scope = review_scope(index, item, descendants=stage == "implementation")
    values = []
    for current in sorted(scope, key=lambda entry: entry["id"]):
        required = current["mathematics"]["required"]
        values.append([current["id"], required,
                       spec_digest(directory, manifest, current) if required is True else None])
    return digest(canonical([stage, values]))


def exclusions(index, item, coordinator, stage):
    authors, reviewers = {coordinator}, set()
    for current in review_scope(index, item):
        mathematics = current["mathematics"]
        if mathematics["required"] is not True:
            continue
        authors.update(mathematics["authors"])
        authors.update(current["contributors"])
        review = mathematics["specification_review"]
        if review:
            reviewers.add(review["reviewer"])
    return authors | reviewers if stage == "implementation" else authors
