"""Analyst gates check recorded evidence; they do not grant execution authority."""
from __future__ import annotations

from .artifacts import contained, spec_digest
from .formats import digest, require
from .lint import lint, parse_document
from .mathematics import exclusions, scope_digest


def check_gate(repo, directory, manifest, item_id, gate, snapshot):
    index, _ = lint(repo, directory, manifest)
    require(item_id in index, f"Unknown item: {item_id}")
    item = index[item_id]
    require(snapshot["branch"] == manifest["branch"], "Checkout differs from selected task branch")

    def signature(entry):
        return spec_digest(directory, manifest, entry)

    def artifact(record, entry, source=None):
        require(record["spec_sha256"] == signature(entry), f"{entry['id']}: evidence refers to a stale specification")
        if source is not None:
            require(record["source_sha256"] == source, f"{entry['id']}: evidence refers to stale source content")
        path = contained(directory, record["artifact"])
        require(path.is_file() and path.stat().st_size > 0, f"Missing/empty evidence: {record['artifact']}")
        require(digest(path.read_bytes()) == record["sha256"], f"Evidence content changed: {record['artifact']}")

    def specification(entry):
        require(entry["kind"] != "subtask" or entry["specification"], f"{entry['id']}: detailed specification is missing")
        for key, kind in (("document", entry["kind"]), ("specification", "specification")):
            if entry[key]:
                parse_document(contained(directory, entry[key]).read_text(encoding="utf-8-sig"), kind, entry["id"], ready=True)
        kind = "specification" if entry["specification"] else entry["kind"]
        primary = contained(directory, entry["specification"] or entry["document"])
        parsed = parse_document(primary.read_text(encoding="utf-8-sig"), kind, entry["id"], ready=True)
        reqs, criteria = parsed["ids"]["REQ"], parsed["ids"]["AC"]
        require(set(entry["coverage"]) == reqs and all(entry["coverage"].values()), f"{entry['id']}: every requirement needs acceptance coverage")
        require(set(entry["verification"]) == criteria and all(entry["verification"].values()), f"{entry['id']}: every criterion needs a planned check")
        require(entry["mathematics"]["required"] is not None,
                f"{entry['id']}: mathematical impact is unassessed")
        if entry["kind"] == "subtask":
            brief = parse_document(contained(directory, entry["document"]).read_text(encoding="utf-8-sig"), "subtask", entry["id"], ready=True)
            require(brief["ids"]["AC"] <= criteria, f"{entry['id']}: detailed specification lost brief criteria")
        parent = entry["parent"]
        if parent:
            specification(index[parent])

    def mathematical_review(entry, stage, source=None, *, accepted=True):
        record = entry["mathematics"][f"{stage}_review"]
        if accepted:
            require(record is not None and record["verdict"] == "accepted",
                    f"{entry['id']}: accepted mathematical {stage} review is missing")
        if record is not None:
            require(record["reviewer"] not in exclusions(index, entry, manifest["coordinator"], stage),
                    f"{entry['id']}: mathematical {stage} reviewer is not independent of scoped authors or specification reviewers")
            artifact(record, entry, source)
            require(record["scope_sha256"] == scope_digest(directory, manifest, entry, stage),
                    f"{entry['id']}: mathematical {stage} review refers to stale included contracts")

    def mathematical_specifications(entry):
        current = entry
        while current:
            if current["mathematics"]["required"] is True:
                mathematical_review(current, "specification")
                require(not any(finding["blocking"] and finding["disposition"] != "resolved"
                                for finding in current["findings"]),
                        f"{current['id']}: mathematical contract has an unresolved blocking finding")
            current = index[current["parent"]] if current["parent"] else None

    def agreement(entry):
        approval = entry["approval"]
        require(approval is not None and approval["spec_sha256"] == signature(entry), f"{entry['id']}: current specification approval is missing")
        expected = {"readiness", "alignment"} if entry["review_policy"] == "separate" else {"combined"}
        require({review["kind"] for review in entry["spec_reviews"]} == expected, f"{entry['id']}: required specification reviews are missing")
        reviewers = []
        for review in entry["spec_reviews"]:
            require(review["verdict"] == "accepted", f"{entry['id']}: specification review requests changes")
            require(review["reviewer"] != manifest["coordinator"], "Specification reviewer must differ from coordinator")
            reviewers.append(review["reviewer"])
            artifact(review, entry)
        require(len(reviewers) == len(set(reviewers)), "Separate specification reviews require separate reviewers")
        mathematical_specifications(entry)

    def scope_authority():
        require(manifest["scope"] != "application" or manifest["application_authorization"] is not None,
                "Application work needs a recorded explicit bootstrap expansion and scope authorization")

    def implementation_ready(entry):
        require(entry["status"] in ("ready", "approved", "in_progress"),
                f"{entry['id']}: select a ready task or explicitly reconcile its status")
        require(not any(finding["blocking"] and finding["disposition"] != "resolved"
                        for finding in entry["findings"]), f"{entry['id']}: blocking finding is unresolved")

    visited = set()
    def completion(entry, source):
        key = (entry["id"], source)
        if key in visited:
            return
        visited.add(key)
        specification(entry)
        agreement(entry)
        for dependency in entry["depends_on"]:
            completed_dependency(index[dependency])
        for finding in entry["findings"]:
            require(finding["disposition"] != "open", f"{entry['id']}: finding needs a disposition")
            require(not finding["blocking"] or finding["disposition"] == "resolved", f"{entry['id']}: blocking finding is unresolved")
        expected = {check for checks in entry["verification"].values() for check in checks}
        require({check["id"] for check in entry["checks"]} == expected, f"{entry['id']}: planned checks have missing results")
        for check in entry["checks"]:
            require(check["outcome"] == "passed" and check["exit_code"] == 0, f"{entry['id']}: check {check['id']} did not pass")
            artifact(check, entry, source)
        require(bool(entry["contributors"]), f"{entry['id']}: record implementation contributors")
        review = entry["code_review"]
        require(review is not None and review["verdict"] == "accepted", f"{entry['id']}: implementation review is missing or requests changes")
        require(review["reviewer"] not in {*entry["contributors"], manifest["coordinator"]}, "Implementation reviewer must be independent of contributors and coordinator")
        artifact(review, entry, source)
        if entry["mathematics"]["required"] is True:
            mathematical_review(entry, "implementation", source)
        if entry["kind"] == "epic":
            children = [child for child in index.values() if child["parent"] == entry["id"]]
            require(bool(children), "Epic has no subtasks")
            for child in children:
                completed_dependency(child)

    def completed_dependency(entry):
        receipt = entry["completion"]
        require(entry["status"] == "done" and receipt is not None, f"{entry['id']}: dependency is not completed with evidence")
        require(receipt["spec_sha256"] == signature(entry), f"{entry['id']}: dependency contract changed since completion")
        # Predecessor evidence belongs to its accepted source revision. Successors are
        # checked on current source; requiring predecessor source == current would
        # invalidate every dependency as soon as its successor made a change.
        completion(entry, receipt["source_sha256"])

    current = {"spec_sha256": signature(item), "source_sha256": snapshot["source_sha256"]}
    if gate == "specification":
        specification(item)
    elif gate == "start":
        scope_authority()
        implementation_ready(item)
        specification(item)
        agreement(item)
        require(item["kind"] != "epic", "Select a subtask for implementation; use epic completion for integration")
        for dependency in item["depends_on"]:
            completed_dependency(index[dependency])
    elif gate == "completion":
        scope_authority()
        completion(item, snapshot["source_sha256"])
    elif gate == "resumption":
        require(item["checkpoint"] == current, "Checkpoint differs from source/specification; reconcile before refreshing it")
        for review in item["spec_reviews"]:
            artifact(review, item)
        if item["approval"]:
            require(item["approval"]["spec_sha256"] == current["spec_sha256"], "Approval is stale")
        for check in item["checks"]:
            artifact(check, item, snapshot["source_sha256"])
        if item["code_review"]:
            artifact(item["code_review"], item, snapshot["source_sha256"])
        mathematical_review(item, "specification", accepted=False)
        mathematical_review(item, "implementation", snapshot["source_sha256"], accepted=False)
        if item["status"] == "done":
            require(item["completion"] == current, "Completion receipt is stale")
            scope_authority()
            completion(item, snapshot["source_sha256"])
        elif item["status"] in ("approved", "in_progress"):
            scope_authority()
            implementation_ready(item)
            specification(item)
            agreement(item)
            for dependency in item["depends_on"]:
                completed_dependency(index[dependency])
    else:
        raise ValueError(f"Unknown gate {gate}")
    return current
