# Task artifacts: JSON v2, Markdown v1 and CLI

Read before creating or resuming a task. The helper needs Python 3.10+ and Git,
with no third-party packages. Use an already available interpreter; do not alter
the application environment for the harness. On this machine `py -3.14 -B` works
outside the restricted sandbox; request the existing tool permission if needed.

## Files and lifecycle

The tracked templates are [epic](../assets/epic.md),
[subtask](../assets/subtask.md) and [specification](../assets/specification.md).
Create instances with [task.py](../../../../harness/scripts/task/task.py).
All generated files, evidence and state belong under the repository's ignored
`.agent-work/tasks/<task-name>/`. Templates and helper code stay tracked. Never
force-add the local task directory. These files are local to the checkout;
preserve/locate them explicitly for authorized cross-worktree handoffs.

For a standalone task, initialize one `specification` item. For an epic, initialize
an `epic`, add `subtask` briefs with `--parent`, then add each subtask's detailed
`specification` using its existing ID when it is ready for elaboration. A brief's
acceptance IDs must survive in its detailed specification. Root items cannot be
subtasks; additional items must belong to the epic. Dependency IDs identify other
executable items, not the parent epic. Keep machine dependencies in `task.json`;
the prose explains their reasons and contracts. Fill the epic requirement/acceptance
coverage and integration-check plan before starting children; these parent fields
are part of every child approval, so postponing them would invalidate completed work.

Examples run from the repository root, after branch choice:

```powershell
py -3.14 -B harness/scripts/task/task.py init .agent-work/tasks/example --id EPIC-001 --kind epic --branch codex/example --scope harness
py -3.14 -B harness/scripts/task/task.py lint .agent-work/tasks/example
py -3.14 -B harness/scripts/task/task.py init .agent-work/tasks/example --id TASK-001 --kind subtask --parent EPIC-001 --branch codex/example --scope harness --expect-sha256 <manifest-hash-from-lint>
py -3.14 -B harness/scripts/task/task.py init .agent-work/tasks/example --id TASK-001 --kind specification --branch codex/example --scope harness --expect-sha256 <fresh-manifest-hash>
```

Use the actual selected branch/scope, not the example values. `--repo <root>`
before the command chooses an isolated repository for fixtures. Initialization
refuses overwrites, unsupported parent relationships, branch mismatch, non-ignored
destinations and stale manifest hashes. Its short-lived lock prevents cooperating
initializers from colliding. A crash may leave a lock or partial directory;
inspect and reconcile it instead of retrying with forced deletion. Creating a
document and updating its manifest are not crash-atomic as a pair.

The analyst is the sole writer of task state. Use the
[automation commands](task-automation.md) to register packaged evidence, save
checkpoints and complete tasks. Direct Markdown/JSON edits remain available for
requirements, permissions, review planning, contributors and finding dispositions;
preserve existing fields/evidence and run lint after such edits. Harness journal
edits must always use `journal.py`.
Do not edit a manifest concurrently with the helper or another agent. Keep old
evidence on disk when it becomes obsolete; current record fields point to the
evidence currently being claimed, not a fabricated history of success.

## Delegated worktrees and evidence

Keep one canonical manifest in the coordinator checkout on the selected task
branch. Its `branch` remains that primary branch; run analyst gates there. A
developer worktree is an execution workspace for an assignment, not a second
task-state owner. Do not rewrite the manifest branch to bypass a branch mismatch
or create independently editable manifest copies for parallel developers.

Use existing `handoff.permissions` for the actual delegated commit authority and
its human source. Store structured Git ownership in the analyst-owned
[assignment](../../../../harness/quality-checks.md#assigned-developer-git-checks);
`handoff.notes` refers to its path/hash plus evidence location, current head and
next action, rather than duplicating its ownership fields. No new manifest fields
are introduced. Keep paths and ownership explicit:
Git-ignored task files do not appear in a newly created worktree. Provide the
needed specification/contract copies or authorized read paths and an ignored task
directory for the developer's reports. These copies are inputs, not independent
approval or state records. Reconcile specification changes before resuming work.

The existing `snapshot` command requires a manifest. Use `source-snapshot` for a
worker checkout without copying canonical state:

```powershell
py -3.14 -B harness/scripts/task/task.py --repo <developer-worktree> source-snapshot
```

Use `context` with the canonical task repository/directory and explicit
`--source-repo <developer-worktree>` when a check or review also needs task and
specification bindings. See the [automation contract](task-automation.md).

This records the worker branch and the same source-content digest used by analyst
gates. It does not grant authority, record test execution or run a worker gate.

Before integration or completion, inspect the developer's committed changes,
remaining staged/uncommitted work and actual check reports. Run the
[commit-series check](../../../../harness/quality-checks.md#analyst-handoff-checks)
against the exact delivered range; its result does not establish review or
integration acceptance. Import packages
through `import-evidence`; use its explicit adoption operation only after assessing
their applicability. It verifies copied bytes and preserves original bindings.
Keep original raw reports and their source/specification identity. Record
branch/base/head and the tested working-tree content, not just a final commit ID.
Uncommitted or ignored inputs and runtime differences must remain visible.

Review the exact version being integrated. Perform integration only under the
existing task authority; receiving commits is not permission to merge, push or
rewrite history. Then snapshot the coordinator source and verify the integrated
result. Reuse a check only after assessing that its actual inputs and source are
applicable; on content changes follow the reassessment rule below and obtain
independent review of that reasoning, or rerun affected checks. Do not relabel a
developer's old log as an execution against the integrated tree. Keep acceptance
blockers open and run the completion gate only with current integrated evidence.

## Markdown contract

The first line records Markdown format version 1, document kind and item ID.
This is separate from JSON manifest version 2. Preserve the
template's single title and ordered level-two headings; use level-three headings
for detail. Prose may use the conversation's language. Each required section must
have substantive content before readiness; explain inapplicability where relevant.
The template header/heading strings remain stable English schema labels.

Requirements and acceptance entries use exact definition syntax outside fences:

```markdown
- REQ-001: Preserve previously completed outputs after interruption.
- AC-001: A resumed fixture preserves the completed output and executes only the pending job.
```

Define requirement IDs under `Requirements` and criteria under `Acceptance`.
IDs are local to an item; qualify cross-task prose references with the item ID.
Drafts may retain `[TODO: ...]` placeholders and incomplete maps. A specification
gate rejects empty sections, unfinished placeholders and missing coverage.
Lint checks declared document paths, item/dependency IDs and local Markdown file
links within the repository. It does not fetch external links, inspect external
projects or validate URL destinations or Markdown heading fragments.

## Manifest contract

`init` produces the complete JSON shape. Unknown fields, duplicate JSON keys,
unsupported versions and invalid types fail lint. Change a format deliberately
with corresponding templates/helper changes and explicit migration; never
silently reinterpret an older version.

Task-level fields:

| Field | Meaning |
| --- | --- |
| `format_version`, `root` | JSON version 2 and the single root item ID. |
| `branch`, `scope` | Selected branch and `harness` or `application`. |
| `coordinator` | Actual analyst identity used when distinguishing reviewers. |
| `application_authorization` | Null during bootstrap; for application execution, an object with `source` and `scope` recording explicit human expansion and task authority. Reuse valid prior authorization; verify its actual source. |
| `handoff` | `next_action`, `active_agents` (IDs), `permissions` (branch/commit scope and human source) and concise `notes` for recovery. These operational notes do not alter the specification digest. |
| `items` | Epic, subtask or standalone-specification records. |

Each item has `id`, `kind`, `parent` (ID/null), `depends_on` (IDs), `document`
(relative path) and `specification` (separate path only for a subtask, otherwise
null). States are `draft`, `ready`, `approved`, `in_progress`, `blocked`, `done`.
State is a recorded claim, not evidence; the appropriate gate must pass before
the analyst advances it. A selected subtask is not the whole epic.

Review planning uses `scale` (`small`, `large`, `risky`), `review_policy`
(`separate`, `combined`) and `review_rationale`. Combined readiness/alignment
review is allowed only for a small task with a reason. Large and risky tasks
always use different readiness/alignment reviewers.

`coverage` maps requirement IDs to nonempty lists of acceptance IDs.
`verification` maps acceptance IDs to nonempty lists of planned check IDs:

```json
{"coverage": {"REQ-001": ["AC-001"]}, "verification": {"AC-001": ["CHECK-001"]}}
```

Define these maps before approval. Prose explains the check's method, scope and
why it tests the risk; JSON does not repeat the requirement or acceptance text.

Evidence structures (SHA fields hold actual 64-character lowercase SHA-256):

- `approval`: null or `{ "source": "human decision reference and scope", "spec_sha256": "..." }`.
- `spec_reviews`: records with `kind` (`readiness`, `alignment` or `combined`),
  `reviewer`, `verdict` (`accepted`/`changes_requested`), `artifact` (task-relative
  report path), `sha256` (report content), and `spec_sha256`.
- `contributors`: actual implementation author/agent identities for this item.
  Epic Python-review independence also excludes contributors recorded on its
  included children; do not duplicate child authors merely to make that check work.
- `checks`: records with `id`, `command` (argument strings), `exit_code`
  (integer/null), `outcome` (`passed`, `failed`, `not_run`), `artifact`, `sha256`,
  `spec_sha256`, `source_sha256`. Record actual execution output and limitations.
  Missing execution may simply remain absent until it is run. Never invent a
  successful record to fill a required field.
- `code_review`: null or a record with `reviewer`, `verdict`, `artifact`, `sha256`,
  `spec_sha256`, `source_sha256`. Reviewer differs from coordinator and contributors.
- `findings`: records with `id`, `blocking` (Boolean), `disposition`
  (`open`, `resolved`, `deferred`, `unchanged`) and `reason`. Completion requires
  dispositions for all findings and resolution of every blocking finding.
- `checkpoint`, `completion`: null or `{ "spec_sha256": "...", "source_sha256": "..." }`.

Evidence files must be nonempty and remain inside the task directory. The automation
helper computes file hashes and v2 records for packaged results. Imported ZIP
artifacts contain metadata and raw payloads; their v2 SHA covers the whole archive.
Existing plain-file reports remain supported. Actor names and command text are
records, not authentication. Inspect the real agent output/execution trace.

## Mathematical review records

Every item includes `mathematics` with these fields:

```json
{"required": null, "rationale": "", "authors": [],
 "specification_review": null, "implementation_review": null}
```

The analyst sets `required` to true for substantive formula/algorithm/metric changes
or false for justified nonmathematical/meaning-preserving changes, with a nonempty
`rationale`. Null means unassessed and blocks readiness. Mathematical conditions
include numerical evaluation, approximation, weighting and stopping behavior where
they affect meaning. The helper cannot decide semantic relevance. Keep ancestor
contracts and actual integrated child behavior in this assessment.

`authors` records identities contributing to the mathematical formulation, including
adopted substantive correction proposals; the coordinator and applicable implementation
`contributors` are also excluded from independent mathematical review. Authorship is
provenance, not a new scientific requirement. Do not omit a proposer because another
actor edited the formula. The analyst verifies identities from actual assignments.

`specification_review` uses the existing review shape: `reviewer`, `verdict`
(`accepted`/`changes_requested`), `artifact`, `sha256`, `spec_sha256`, and
`scope_sha256`. `implementation_review` additionally has `source_sha256`.
The mathematical scope digest binds formulation reports to this item, ancestors
and declared transitive dependencies; implementation reports additionally cover
an epic's descendants and their dependencies. It includes impact classifications
and the specification digests of included mathematical items. Reapproving a changed
dependency/child does not silently make an old enclosing mathematical report current.
Formulation scope excludes later child elaboration so shared-contract review can
precede it; human approval retains its existing item/ancestor scope.

Compute and inspect the scope with `math-scope` in the coordinator task:

```powershell
py -3.14 -B harness/scripts/task/task.py math-scope .agent-work/tasks/example --id TASK-001 --stage specification
```

Use `context` with the same stage for the exact context-v1 input to review packaging;
capture it before review and compare a fresh context afterwards. `math-scope` also
lists included contracts for inspection; fingerprints do not replace reading them.

Record this digest in the original report as well as its manifest binding; obtain
it before and after review, with the actual scoped documents supplied to the worker.
Changing it requires affected reassessment, not relabeling the earlier report.
The implementation reviewer must
be a different actual agent from the formulation reviewer. Mathematical independence
also covers included ancestors, transitive dependencies and, for an epic, integrated
descendants and their dependencies. A child author or formulation reviewer cannot
become its independent implementation reviewer by reviewing the enclosing epic.

Reports require `required: true`. Keep incomplete or obsolete reports on disk and
in handoff/findings, clearing obsolete current record references rather than forging
accepted entries. Material gaps remain blocking. Only complete accepted reviews
satisfy the relevant gates. Scientific source versions, ignored inputs and derivations
belong in the reports/specification; the helper does not independently retrieve or
validate scientific sources. `required` and `rationale` participate in the specification
digest, including ancestor contracts; authors/reports are checked as provenance/evidence
without changing the scientific digest. Changing a classification requires explicit
reassessment, not an automatic exemption from existing findings.

## Explicit legacy migration

The helper rejects JSON v1 for ordinary operations. For one selected legacy task,
inspect its current branch/state and obtain its manifest hash, then run:

```powershell
Get-FileHash -Algorithm SHA256 .agent-work/tasks/example/task.json
py -3.14 -B harness/scripts/task/task.py migrate .agent-work/tasks/example --expect-sha256 <lowercase-current-hash>
```

Migration validates the strict v1 structure, selected branch and ignored task location,
then preserves the original bytes as `task.v1.backup.json`. It retains Markdown v1,
all evidence files, approvals, statuses and original hashes. New mathematical records
start unassessed with no reviews. Prior states and evidence do not establish v2 gate
acceptance: classify impact, inspect old evidence and explicitly revalidate applicable
bindings. Do not fabricate a new approval or mathematical review; reuse genuine human
approval only after verifying unchanged agreed scope under the existing policy.

The writer lock, expected hash and final source checks protect cooperating writers;
stop external writers too. A conflicting backup or stale manifest is rejected. An
identical backup can be reused after a failed replacement; a different one is never
overwritten. A failure may leave a preserved backup; inspect it before retrying.
Migration is selected explicitly, never run over unrelated local tasks automatically.

## Snapshots and gates

```powershell
py -3.14 -B harness/scripts/task/task.py snapshot .agent-work/tasks/example --id TASK-001
py -3.14 -B harness/scripts/task/task.py check .agent-work/tasks/example --id TASK-001 --gate specification
py -3.14 -B harness/scripts/task/task.py check .agent-work/tasks/example --id TASK-001 --gate start
py -3.14 -B harness/scripts/task/task.py check .agent-work/tasks/example --id TASK-001 --gate completion
py -3.14 -B harness/scripts/task/task.py check .agent-work/tasks/example --id TASK-001 --gate resumption
```

`lint`, `snapshot` and `check` are read-only. They print JSON on success and return
0; diagnosed invalid inputs/gate failures return 1 with a concrete error; invalid
CLI syntax returns 2. These inspection commands never execute a recorded command.
Only explicit `run-check` executes caller-supplied argv under existing authority;
the helper never launches agents, changes branches or installs packages. It is
workflow checking, not a tool-access control or tamper-proof approval system.

The specification digest covers the item brief/specification, ancestor contracts,
scope, mathematical impact/rationale and structural agreement/verification fields. A changed contract or check
plan invalidates old bindings. Reuse a real human approval after a mechanical
edit only after explicitly verifying unchanged meaning and recording that reason
with its source. Material changes require renewed approval. Never refresh hashes
as a substitute for that decision or redoing an affected review.

The source digest covers bytes of tracked and non-ignored untracked files,
including dirty modifications and deletions. Commit IDs alone are insufficient.
Ignored datasets, external environments and external resources are not included;
when relevant, bind their versions/hashes in the specification and actual check
reports. Source symlinks and submodules are rejected rather than silently read
outside the repository. Metadata/permissions and external runtime changes are not
content fingerprints. Take snapshots before and after checks/reviews and compare
them; never bind old evidence to code that changed in between.

The source digest is deliberately conservative: any covered file change makes
current source-bound evidence stale. Investigate the change and revalidate only
the affected behavior; if carrying forward an unaffected result, save a new
explicit reassessment report explaining the source change, prior execution and
why it remains applicable. Do not claim a rerun that did not happen. Independent
review must assess the coverage of such a reassessment.

| Gate | Required recorded evidence |
| --- | --- |
| `specification` | Complete brief/spec and parent context, explicit mathematical impact/rationale, requirement-to-acceptance and acceptance-to-check coverage. Semantic readiness still needs independent review. |
| `start` | Ready/approved/in-progress executable item, matching branch, current approval and independent specification reviews, applicable mathematical formulation reviews including ancestor contracts, no unresolved blockers on the item or its ancestor contracts regardless of mathematical classification, verified completed dependencies, application authority if relevant. |
| `completion` | Current specification/approval/reviews, successful required execution records and independent Python and applicable mathematical implementation reviews bound to current source, distinct mathematical stage agents, findings disposed and ancestor blockers resolved; for an epic, all children completed plus epic-level integration checks and Python-review independence from all included child contributors. |
| `resumption` | Checkpoint matching current spec/source/branch and intact current evidence including mathematical review bindings/independence; claimed active/done states also satisfy their applicable gates. Reconcile drift before changing state. |

Use `complete` to run the completion gate and atomically save its receipt, `done`
status and current checkpoint. Use `checkpoint` for a handoff without changing
status; replacing a differing checkpoint requires an explicit reconciliation reason
and intact current evidence. Both commands require the expected manifest hash and
preserve previous state. See [state operations](task-automation.md#state-operations).
Dependencies
are checked against their accepted completion source revision, since successor
implementation necessarily changes current source. Their specification and report
integrity still must hold. The analyst must inspect whether later changes broke
their contracts; epic integration checks cover the current combined result.

The helper proves structural consistency, integrity of referenced files and
agreement of recorded fingerprints. It cannot prove that a human actually
approved something, an independent actor is genuine, a claimed command ran, or
a passing check establishes the requested behavior. The analyst and independent
reviewers must verify those facts from original evidence.
