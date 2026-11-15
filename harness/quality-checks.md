# Harness quality checks

Use `harness/scripts/quality.py` with Python 3.10+ and Git. The tools use only the
standard library and do not change the application environment. On this machine
`py -3.14 -B` works outside the restricted sandbox. Diagnostics report actual
availability; a launcher failure does not establish that Python is uninstalled.

Run from the repository root. Global `--repo PATH` selects the checkout and
`--json` emits structured reports. A successful check exits 0, a refusal or failed
check exits 1, and invalid CLI usage exits 2. Read the diagnostics and any remaining
changes, not just the exit code. No command proves authentic human consent or
semantic task compliance.

## Common validation

```powershell
py -3.14 -B harness/scripts/quality.py validate
py -3.14 -B harness/scripts/quality.py --json doctor
```

Validation covers maintained harness skills, references, templates, journals and
root instructions. It checks metadata, local file links and fragments, the 32,000
UTF-8-byte AGENTS.md limit, and supported producer/consumer formats. Existing task
and journal parsers remain authoritative. Generated task archives and application
documents are not swept as harness inputs; referenced local targets may be read.
External URLs are not fetched. The supported Markdown and skill-metadata syntax
is a bounded project dialect, not a complete YAML/CommonMark implementation.

These static checks do not establish that instructions are useful, current agents
have read them, reviews are independent, or application delivery works. Substantial
instruction changes still require the maintainer's independent behavioral checks.

## Assigned developer Git checks

The analyst owns one canonical assignment JSON under its ignored
`.agent-work/tasks/<task>/` directory. Supply the absolute path and SHA-256 of its
exact bytes to the developer. The schema is separately versioned; task JSON v2 and
Markdown v1 are unchanged. In `handoff.notes`, refer to the assignment and its hash
instead of maintaining a second list of its Git ownership values. Retain the real
commit authority/source in `handoff.permissions` and the assignment provenance.
Updating ownership requires analyst reconciliation and an explicitly supplied new
hash, not automatic replacement of a failed expected hash by the developer.

Assignment fields:

| Field | Meaning |
| --- | --- |
| `format_version` | Integer `1`. |
| `task_id`, `developer_id` | The actual task and assigned worker identities. |
| `repository` | Absolute coordinator checkout root. |
| `worktree` | Absolute assigned developer checkout in the same Git repository. |
| `branch` | Exact assigned branch. |
| `base` | Full assigned base commit ID. |
| `allowed_files` | Exact repository-relative file paths. |
| `allowed_directories` | Repository-relative directories including descendants. |
| `authority` | Object with nonempty `source` and `scope`; provenance, not proof of consent. |

Ownership paths use forward slashes, no absolute paths, wildcards or parent
traversal. Directory ownership observes path-component boundaries. At least one
owned path is required. Git internals and `.agent-work` cannot be committed even
when a broad directory is assigned. Unknown fields, duplicate keys, unsupported
versions and a changed assignment are refused.

Before committing the developer runs:

```powershell
py -3.14 -B harness/scripts/quality.py --repo <developer-worktree> --json staged --assignment <assignment.json> --assignment-sha256 <sha256>
```

The check verifies checkout/branch/base, the complete index and both sides of
renames, and reports remaining work. It never stages, unstages, stashes, resets or
commits. Unrelated staged work holds the commit for analyst resolution. Unstaged
changes may remain and must be reported. Partial staging is valid: the check reads
the staged state rather than substituting working file contents. The developer
still inspects the complete staged diff and its semantic scope.

The report identifies the observed HEAD, index and assignment. It is an observation,
not a reusable permission token: changes after checking require another check.
Hook execution narrows the interval but cannot freeze arbitrary external writers.

## Analyst handoff checks

Before accepting the delivered commits, the analyst runs:

```powershell
py -3.14 -B harness/scripts/quality.py --repo <developer-worktree> --json handoff --assignment <assignment.json> --assignment-sha256 <sha256> --head <full-delivered-commit>
```

This checks every new commit from the assigned base to the supplied HEAD, including
out-of-scope changes later reverted. A net final diff alone is insufficient.
Unexpected history, unsupported merges or a changed HEAD require reconciliation.
Remaining changes are reported separately. The check does not integrate commits,
update task state or establish acceptance; the analyst still reviews exact input
versions, raw tests/reviews and existing completion gates.

## Optional hook and readiness

The pre-commit hook is optional and installed explicitly. It must not overwrite
another hook, change global Git configuration, or silently enable checks in other
worktrees. Installation/status diagnostics identify actual checkout activation.
Working-checkout activation is a separate human decision from this implementation.

After activation is authorized, use an absolute Python executable (not a launcher
plus arguments). Global options precede the command:

```powershell
py -3.14 -B harness/scripts/quality.py --repo <checkout> hooks install --python <python.exe>
py -3.14 -B harness/scripts/quality.py --repo <checkout> hooks status
py -3.14 -B harness/scripts/quality.py --repo <checkout> hooks uninstall
```

For a developer add `--assignment <assignment.json> --assignment-sha256 <sha256>`
to install. Installation uses the repository's shared Git hook directory and a
per-worktree binding at `.agent-work/tasks/.quality-hook/config`. Unconfigured
worktrees are not enabled. Uninstall removes only that checkout's binding; the
shared launcher remains for other worktrees. Existing `core.hooksPath` settings
are refused for explicit reconciliation. Modified/foreign launchers are preserved.

An assigned developer hook uses the canonical assignment and pinned hash. A
maintainer/human hook can run common validation without a fabricated assignment.
Hook checks run against an isolated staged snapshot, preserving user working files
and index. Intent-to-add placeholders are excluded from the future commit tree;
they cannot satisfy local links or supply the staged entrypoint. Python execution
ignores inherited Python import configuration and site customization. A
failed/unavailable required check blocks the commit and reports its
reason. Do not use Git's bypass options to present an unperformed check as passed.

Fast tests are selected explicitly from changed helper/test paths. The full
integrated harness suite remains a delivery check, not a claim made by the hook:

| Changed path | Selected tests |
| --- | --- |
| Journal helper | Journal tests. |
| Named quality module | Its focused suite; Git checks also select handoff tests. |
| Task CLI | Core task tests. |
| Common task format/artifact/gate/lint/migration module | Task, evidence and state tests. |
| Named task automation module | Its corresponding suite and core task tests. |
| A test file | That test file. |
| Other helper code | Validation, Git, task and journal smoke suites. |

The executable mapping is `quality_support/hooks.py`; multiple changes take the
union. Missing selected tests, zero executed tests, skipped tests, nonzero exits
and timeouts cannot pass. Test output is included when a selected suite fails.
Documentation-only changes still run common validation. Broad changes can select
a larger set; this is not a fixed latency guarantee.

```powershell
py -3.14 -B -m unittest discover -s harness/tests -v
```

`doctor` inspects the actual Python/Git and checker components, hook state and any
required assignment. It distinguishes `ready`, `not_configured`, `not_applicable`
and `unavailable`. An absent optional hook is visible without pretending it is
active. A configured but broken hook or required assignment prevents readiness.
Doctor does not install tools, run application checks or repair configuration.

Index snapshots support regular files only; symlinks and gitlinks are refused.
Status checks report conflicting default hooks and a missing staged entrypoint
instead of claiming that the configured checker is ready. These readiness probes
do not execute the selected tests or replace validation of their results.
Each selected test process has a 120-second timeout; the staged checker has a
300-second timeout. Abrupt termination or escaped descendants are not a guaranteed
cleanup boundary. Index/HEAD/configuration are compared around hook execution, but
these observations do not lock out arbitrary external writers.
Git itself may refresh internal index metadata while attempting a commit; the
preservation guarantee concerns staged content, HEAD on refusal and user files.
Direct `precommit` checks also preserve the observed index bytes.

Git permits bypassing pre-commit; it is assistance, not a security boundary. The
analyst's explicit handoff check remains required for assigned developer delivery.
Hook environment and worktree behavior follow the
[Git hook documentation](https://git-scm.com/docs/githooks) and
[repository layout](https://git-scm.com/docs/gitrepository-layout).
