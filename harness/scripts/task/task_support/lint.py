"""Strict machine fields and a small, explicit Markdown dialect for task records."""
from __future__ import annotations

import re
from urllib.parse import unquote, urlsplit

from .artifacts import contained
from .formats import (DOCUMENT_VERSION, ITEM_FIELDS, MANIFEST_FIELDS, SECTIONS, VERSION, fields,
                      identifier, nonempty, require, sha, strings)

PLACEHOLDER = re.compile(r"\[TODO(?::[^\]]*)?\]|\{\{[^}]+\}\}|\bTBD\b", re.I)


def parse_document(text, kind, item_id, *, ready=False):
    expected = f"<!-- task-format: {DOCUMENT_VERSION}; kind: {kind}; id: {item_id} -->"
    require(text.splitlines() and text.splitlines()[0] == expected,
            f"{item_id}: wrong document version/kind/ID header")
    headings, sections, visible_sections, current, fence = [], {}, {}, None, None
    title_count = 0
    visible, active_lines = [], []
    comment = False
    for line in text.splitlines()[1:]:
        if fence is None:
            remaining, chunks = line, []
            while remaining:
                if comment:
                    end = remaining.find("-->")
                    if end < 0:
                        remaining = ""
                    else:
                        remaining, comment = remaining[end + 3:], False
                else:
                    opening = re.search(r"`+|<!--", remaining)
                    if opening is None:
                        chunks.append(remaining)
                        remaining = ""
                    else:
                        chunks.append(remaining[:opening.start()])
                        token = opening.group()
                        remaining = remaining[opening.end():]
                        if token == "<!--":
                            comment = True
                        else:
                            closing = re.search(r"(?<!`)" + re.escape(token) + r"(?!`)", remaining)
                            if closing is None:
                                chunks.append(token)
                            else:
                                chunks.append(token + remaining[:closing.end()])
                                remaining = remaining[closing.end():]
            line = "".join(chunks)
        active_lines.append(line)
        marker = re.match(r"^\s*(`{3,}|~{3,})(.*)$", line)
        if marker and fence is None and marker.group(1)[0] == "`" and "`" in marker.group(2):
            marker = None
        if marker:
            token, suffix = marker.groups()
            if fence is None:
                fence = (token[0], len(token))
            elif token[0] == fence[0] and len(token) >= fence[1] and not suffix.strip():
                fence = None
            if current:
                sections[current].append(line)
            continue
        if fence:
            if current:
                sections[current].append(line)
            continue
        visible.append(line)
        if line.startswith("# "):
            title_count += 1
            require(bool(line[2:].strip()), f"{item_id}: empty title")
        elif line.startswith("## "):
            current = line[3:].strip()
            require(current not in sections, f"{item_id}: duplicate section {current}")
            headings.append(current)
            sections[current] = []
            visible_sections[current] = []
        elif current:
            sections[current].append(line)
            visible_sections[current].append(line)
    require(fence is None, f"{item_id}: unclosed code fence")
    require(not comment, f"{item_id}: unclosed HTML comment")
    require(title_count == 1, f"{item_id}: expected one document title")
    require(tuple(headings) == SECTIONS[kind],
            f"{item_id}: expected sections in order: {', '.join(SECTIONS[kind])}")
    blocks = {name: "\n".join(body).strip() for name, body in sections.items()}
    if ready:
        for name, body in blocks.items():
            meaningful = re.sub(r"<!--.*?-->", "", body, flags=re.S).strip()
            require(bool(meaningful), f"{item_id}: empty section {name}")
        require(not PLACEHOLDER.search("\n".join(active_lines)), f"{item_id}: unresolved template placeholder")
    ids = {}
    for section, prefix in (("Requirements", "REQ"), ("Acceptance", "AC")):
        id_source = "\n".join(visible_sections.get(section, []))
        matches = re.findall(rf"(?m)^- ({prefix}-[A-Za-z0-9_-]+):[ \t]*(.*)$", id_source)
        names = [name for name, _ in matches]
        require(len(names) == len(set(names)), f"{item_id}: duplicate {prefix} ID")
        if ready and section in SECTIONS[kind]:
            require(bool(matches) and all(value.strip() for _, value in matches),
                    f"{item_id}: {section} needs '- {prefix}-...: description' entries")
        ids[prefix] = set(names)
    return {"sections": blocks, "ids": ids, "visible": "\n".join(visible)}


def evidence(value, label, *, code=False, review=False, mathematical=False):
    expected = {"artifact", "sha256", "spec_sha256"}
    if code:
        expected.add("source_sha256")
    if review:
        expected |= {"reviewer", "verdict"}
    if mathematical:
        expected.add("scope_sha256")
    fields(value, expected, label)
    nonempty(value["artifact"], label)
    for key in ("sha256", "spec_sha256", "source_sha256", "scope_sha256"):
        if key in value:
            sha(value[key], f"{label}.{key}")
    if review:
        nonempty(value["reviewer"], label)
        require(value["verdict"] in ("accepted", "changes_requested"), f"{label}: invalid verdict")


def mapping(value, label):
    require(isinstance(value, dict), f"{label}: expected an object")
    for key, values in value.items():
        identifier(key, label)
        strings(values, label, ids=True)


def lint(repo, directory, manifest, *, legacy=False):
    fields(manifest, MANIFEST_FIELDS, "task.json")
    require(type(manifest["format_version"]) is int and manifest["format_version"] == (1 if legacy else VERSION),
            "Unsupported task format version; explicit migration is required")
    identifier(manifest["root"], "root")
    nonempty(manifest["branch"], "branch")
    nonempty(manifest["coordinator"], "coordinator")
    fields(manifest["handoff"], {"next_action", "active_agents", "permissions", "notes"}, "handoff")
    strings(manifest["handoff"]["active_agents"], "handoff.active_agents")
    for key in ("next_action", "permissions", "notes"):
        require(isinstance(manifest["handoff"][key], str), f"handoff.{key}: expected text")
    require(manifest["scope"] in ("harness", "application"), "Invalid task scope")
    auth = manifest["application_authorization"]
    if auth is not None:
        fields(auth, {"source", "scope"}, "application_authorization")
        for key in auth:
            nonempty(auth[key], f"application_authorization.{key}")
    require(isinstance(manifest["items"], list) and manifest["items"], "items must be a nonempty list")
    index, documents = {}, {}
    for item in manifest["items"]:
        fields(item, ITEM_FIELDS - {"mathematics"} if legacy else ITEM_FIELDS, "item")
        item_id = item["id"]
        identifier(item_id, "item.id")
        require(item_id not in index, f"Duplicate item ID: {item_id}")
        index[item_id] = item
        require(item["kind"] in SECTIONS, f"{item_id}: invalid kind")
        if item["parent"] is not None:
            identifier(item["parent"], f"{item_id}.parent")
        strings(item["depends_on"], f"{item_id}.depends_on", ids=True)
        strings(item["contributors"], f"{item_id}.contributors")
        if not legacy:
            mathematics = item["mathematics"]
            fields(mathematics, {"required", "rationale", "authors", "specification_review",
                                "implementation_review"}, f"{item_id}.mathematics")
            require(mathematics["required"] is None or type(mathematics["required"]) is bool,
                    f"{item_id}: mathematics.required must be Boolean or null")
            require(isinstance(mathematics["rationale"], str), f"{item_id}: mathematical rationale must be text")
            if mathematics["required"] is not None:
                nonempty(mathematics["rationale"], f"{item_id}: mathematical impact rationale")
            strings(mathematics["authors"], f"{item_id}.mathematics.authors")
            for stage in ("specification", "implementation"):
                record = mathematics[f"{stage}_review"]
                if record is not None:
                    require(mathematics["required"] is True,
                            f"{item_id}: mathematical reports require a required assessment; preserve obsolete reports on disk")
                    evidence(record, f"{item_id}.mathematics.{stage}_review",
                             review=True, code=stage == "implementation", mathematical=True)
        require(item["status"] in ("draft", "ready", "approved", "in_progress", "blocked", "done"), f"{item_id}: invalid status")
        require(item["scale"] in ("small", "large", "risky"), f"{item_id}: invalid scale")
        require(item["review_policy"] in ("separate", "combined"), f"{item_id}: invalid review policy")
        require(isinstance(item["review_rationale"], str), f"{item_id}: invalid review rationale")
        if item["review_policy"] == "combined":
            require(item["scale"] == "small" and bool(item["review_rationale"].strip()),
                    f"{item_id}: combined review requires a small task and rationale")
        mapping(item["coverage"], f"{item_id}.coverage")
        mapping(item["verification"], f"{item_id}.verification")
        for key, kind in (("document", item["kind"]), ("specification", "specification")):
            if key == "specification" and item[key] is None:
                continue
            require(key != "specification" or item["kind"] == "subtask", f"{item_id}: only subtasks have a separate specification")
            path = contained(directory, item[key])
            require(path not in documents, f"Duplicate document path: {item[key]}")
            parsed = parse_document(path.read_text(encoding="utf-8-sig"), kind, item_id)
            documents[path] = parsed
            # Check local Markdown file links without accessing anything outside this repo.
            for target in re.findall(r"\[[^\]\n]*\]\(([^)\n]+)\)", parsed["visible"]):
                target = target.strip().strip("<>")
                url = urlsplit(target)
                if url.scheme or target.startswith(("#", "//")):
                    continue
                if not url.path or PLACEHOLDER.search(target):
                    continue
                linked = (path.parent / unquote(url.path)).resolve()
                require(linked.is_relative_to(repo), f"{item_id}: local link escapes repository")
                require(linked.exists(), f"{item_id}: missing local link {target}")
        if item["approval"] is not None:
            fields(item["approval"], {"source", "spec_sha256"}, f"{item_id}.approval")
            nonempty(item["approval"]["source"], "approval.source")
            sha(item["approval"]["spec_sha256"], "approval.spec_sha256")
        require(isinstance(item["spec_reviews"], list), f"{item_id}: spec_reviews must be a list")
        review_kinds = []
        for review in item["spec_reviews"]:
            require(isinstance(review, dict) and "kind" in review, "Specification review needs kind")
            evidence({key: value for key, value in review.items() if key != "kind"}, "spec_review", review=True)
            require(review["kind"] in ("readiness", "alignment", "combined"), "Invalid spec review kind")
            review_kinds.append(review["kind"])
        require(len(review_kinds) == len(set(review_kinds)), "Duplicate specification review kind")
        require(isinstance(item["checks"], list), f"{item_id}: checks must be a list")
        check_ids = []
        for check in item["checks"]:
            fields(check, {"id", "command", "exit_code", "outcome", "artifact", "sha256", "spec_sha256", "source_sha256"}, "check")
            identifier(check["id"], "check.id")
            check_ids.append(check["id"])
            require(isinstance(check["command"], list) and check["command"] and all(isinstance(arg, str) and arg for arg in check["command"]), "check.command needs explicit argument strings")
            require(type(check["exit_code"]) is int or check["exit_code"] is None, "check.exit_code must be an integer or null")
            require(check["outcome"] in ("passed", "failed", "not_run"), "Invalid check outcome")
            evidence({key: check[key] for key in ("artifact", "sha256", "spec_sha256", "source_sha256")}, "check", code=True)
        require(len(check_ids) == len(set(check_ids)), "Duplicate check ID")
        if item["code_review"] is not None:
            evidence(item["code_review"], "code_review", code=True, review=True)
        for key in ("checkpoint", "completion"):
            if item[key] is not None:
                fields(item[key], {"spec_sha256", "source_sha256"}, key)
                for value in item[key].values():
                    sha(value, key)
        require(isinstance(item["findings"], list), f"{item_id}: findings must be a list")
        finding_ids = []
        for finding in item["findings"]:
            fields(finding, {"id", "blocking", "disposition", "reason"}, "finding")
            identifier(finding["id"], "finding.id")
            finding_ids.append(finding["id"])
            require(type(finding["blocking"]) is bool, "finding.blocking must be Boolean")
            require(finding["disposition"] in ("open", "resolved", "deferred", "unchanged"), "Invalid finding disposition")
            nonempty(finding["reason"], "finding.reason")
        require(len(finding_ids) == len(set(finding_ids)), "Duplicate finding ID")
    require(manifest["root"] in index, "Root item does not exist")
    roots = [item["id"] for item in index.values() if item["parent"] is None]
    require(roots == [manifest["root"]], "Exactly one root item is required")
    for item in index.values():
        if item["parent"] is not None:
            require(item["kind"] == "subtask" and item["parent"] in index and index[item["parent"]]["kind"] == "epic", "Subtask parent must be an existing epic")
        else:
            require(item["kind"] != "subtask", "Subtask cannot be a root")
        for dependency in item["depends_on"]:
            require(dependency in index and dependency != item["id"], f"{item['id']}: missing/self dependency")
            require(index[dependency]["kind"] != "epic", "Depend on an executable subtask, not its parent epic")
    done, active = set(), set()
    def visit(item_id):
        require(item_id not in active, "Dependency cycle")
        if item_id in done:
            return
        active.add(item_id)
        for dependency in index[item_id]["depends_on"]:
            visit(dependency)
        active.remove(item_id)
        done.add(item_id)
    for item_id in index:
        visit(item_id)
    # Maps are optional in drafts, but any supplied reference must already be real.
    for item in index.values():
        primary = contained(directory, item["specification"] or item["document"])
        ids = documents[primary]["ids"]
        for requirement, criteria in item["coverage"].items():
            require(requirement in ids["REQ"] and set(criteria) <= ids["AC"], f"{item['id']}: invalid requirement/acceptance coverage")
        require(set(item["verification"]) <= ids["AC"], f"{item['id']}: unknown acceptance criterion in verification")
        planned = {check for checks in item["verification"].values() for check in checks}
        require({check["id"] for check in item["checks"]} <= planned, f"{item['id']}: check was not included in verification plan")
    return index, documents
