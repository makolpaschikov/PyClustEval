# Delegation and independent review

Read when assigning implementation, evidence gathering or review. All seven worker
roles below use linked project skills with ordinary subagents. Use the host's
available collaboration API and respect its concurrency limits. For the two
scouts, two specification roles and mathematics reviewer, select model and reasoning under
the [shared profile policy](../../../../harness/subagent-profiles.md). Other roles
inherit settings unless a specific choice is authorized. Do not modify global
configuration or confuse these assignments with registered host agent types.

## Common assignment

Give each assignee:

- The concrete question or deliverable and task/specification ID and version.
- The relevant request evidence, approved requirements, parent contracts and
  repository facts; provide source pointers with enough context to interpret them.
- Permitted read/write paths, allowed side effects, forbidden scope changes and
  scientific invariants. Pass permissions as bounded instructions, not inferred
  authority from a plan or journal.
- Dependencies, file ownership and integration owner. No branch switches, commits,
  journal updates or task-state writes unless explicitly assigned by the coordinator.
- Acceptance checks, expected evidence and where to return artifacts. Ask for
  actual commands/results, remaining uncertainty and a clear completion/blocker status.

Keep the coordinator as the sole owner of shared task state and integration.
Before parallel edits, determine disjoint file ownership or separate authorized
workspaces. Subagents may share the same filesystem: a prompt saying read-only
does not create an isolated sandbox. Do not duplicate implementation between
agents, launch unauthorized nested work or treat an agent's final answer as proof
without inspecting its outputs. Do not create new user-owned chats unless the
human explicitly asks for them.

## Role-specific additions

| Assignment | Evidence/input and expected result | Boundary |
| --- | --- | --- |
| Code scout | Trace entry points, callers, configuration and tests; return referenced facts and explicitly qualified causal hypotheses. | No solution proposals or source edits; execution only within explicit check/side-effect/resource authority. |
| Internet scout | Research bounded programming/scientific questions; return primary-source evidence, versions, contradictions and limits. | No solution recommendations or mathematical certification; inconclusive search returns partial evidence, not unassigned scope expansion. |
| Specification validator | Give the proposed spec, parent contracts and source/interfaces; assess readiness, verifiable acceptance and material technical constraints. | No spec edits; local wording suggestions are allowed, semantic/architecture decisions return to the analyst. |
| Specification auditor | Give original requests/corrections, actual approval scope, verified facts and the proposed spec; assess alignment and disproportionate scope/complexity. | No spec edits or invented intent; preserve raw request evidence and separate supported findings from preferences. |
| Python developer | Give the approved spec, shared contracts, writable scope and acceptance plan. Request implementation and actual checks with a handoff. | No changes to agreed requirements/scientific conditions or unassigned environment; route questions through analyst. |
| Python reviewer | Give the request/spec, actual changes and execution evidence. Ask for code defects, regressions, scope violations and verification gaps. | Independent from authors and analyst; mathematical validity goes to the specialist through the analyst. |
| Mathematics reviewer | Give the stage, mathematical claims, assumptions, sources, scope/authorship and actual implementation/evidence as applicable. | Separate independent agents for formulation and implementation; bounded probes and reasoned proposals only, no reviewed-file edits. |

## Scout invocation

Start an ordinary subagent, explicitly pass the absolute
[code-scout](../../code-scout/SKILL.md) or
[internet-scout](../../internet-scout/SKILL.md) path and require it to be read.
Select a permitted pair using the [profile policy](../../../../harness/subagent-profiles.md)
and supply fresh, self-contained context under the actual host contract. The
analyst invokes scouts for task investigation; the maintainer may invoke them
within authorized harness work. Neither route gives other workers permission to
spawn scouts directly.

Pass the common assignment, source/version identities, the precise question,
authorized read sources, relevant scientific constraints, check/search limits,
allowed effects and optional ignored report destination. Research may precede
specification approval. Code execution needs explicit check-class or command,
side-effect and resource authorization; bootstrap still limits execution to
isolated harness verification. Source reading alone does not grant execution.

Ask for evidence, not a preferred diagnosis or solution. Inspect the returned
references, actual check results, versions, causal hypotheses and missing evidence
before incorporating conclusions. Scouts do not recommend fixes. Inconclusive
internet research returns a partial answer; broaden its question only through an
explicit assignment. Requests and harness signals return to the caller, which
retains state ownership and the existing signal-registration route.

## Specification-review invocation

Start an ordinary subagent distinct from the specification author and coordinator.
Explicitly pass the absolute
[specification-validator](../../specification-validator/SKILL.md) or
[specification-auditor](../../specification-auditor/SKILL.md) path and require it to
be read. The analyst selects a permitted model/effort using the
[profile policy](../../../../harness/subagent-profiles.md), supplies the choice and
rationale, and provides self-contained context. For a justified small-task
combined review, pass both skills and require separate readiness/alignment
assessments. Large/risky tasks require distinct agents. Maintainer simulations
may exercise this contract only on authorized isolated harness fixtures.

Supply the common assignment, proposed specification and version, relevant parent
contracts, material source/interfaces, scientific invariants, permission scope
and optional ignored report path. For alignment supply the original human request,
corrections and actual relevant approvals as attributable excerpts or authorized
paths, not merely the analyst's interpretation. Pre-approval review does not
require human implementation approval. Do not send preferred answers or suspected
defects. Missing authority or inputs go back to the analyst; inspection of other
authorized parts may continue.

Reviewers inspect authorized documents/source and write only their assigned
ignored reports. They do not execute application code, change source/specs,
dependencies, Git state, journals or canonical task state, or spawn workers.
Requests for execution, source research or expertise go through the analyst.
Both may suggest local wording that preserves meaning. Changes in requirement
meaning, scientific conditions or architecture return as questions to the analyst.

Bind the report to the actual specification and material supporting inputs:
identify the task, reviewer, reviewed spec content hash, request/parent/source
versions and relevant working-tree differences. Freeze the inputs during review
or coordinate drift and affected reassessment. Preserve original evidence when
moving reports between checkouts using the existing
[artifact contract](task-artifacts.md#delegated-worktrees-and-evidence).
Do not relabel an old report by refreshing its hash. A source/request change can
invalidate conclusions even when specification text is unchanged.

Reports contain reviewed scope, evidence-backed findings with stable IDs,
requirement/section and source references, consequences, blocking reason,
separate optional wording suggestions, evidence gaps and a verdict:

- `accepted`: the assigned assessment is complete, supporting evidence is
  applicable/sufficient and no blocker or material gap remains.
- `changes_requested`: supported defects require correction; also retain any
  simultaneous missing evidence or unfinished assessment.
- `incomplete`: missing authority, inputs or unresolved evidence prevents a
  conclusion. Preserve any known findings; no confirmed defect is not acceptance.

The analyst inspects reports, records each finding's disposition and routes
corrections/questions. Only a complete accepted assessment supplies an accepted
`spec_reviews` entry. Incomplete reports remain in handoff/findings and do not
create a new manifest enum; invalidate stale accepted bindings and keep the start
gate blocked until all required assessments are complete and accepted. For a
combined review, both assessments must qualify. Supported changes-requested
findings can use the existing record while retaining concurrent gaps in the report.
The manifest/helper do not independently verify source truth or reviewer reasoning.

Preserve finding identities across corrections, inspect affected request/spec/source
changes and reassess relevant conclusions. Shared-state updates, review acceptance,
human specification approval and implementation-start decisions remain analyst-owned.
Independent review acceptance alone does not authorize implementation or finish a task.

## Python developer invocation

Start an ordinary subagent and explicitly instruct it to read
[python-developer](../../python-developer/SKILL.md) before acting. Pass an absolute
skill path and the assigned worktree root. Ensure the current instructions are
available there, or supply explicit authorized instruction paths; do not assume
task files or instructions transfer automatically. This is a skill-backed assignment,
not a registered host agent type or automatic skill loading. Inherit model and
settings unless the human has authorized a specific choice.

Supply the common assignment above, current approved specification and relevant
parent contracts, the actual authorization source/scope, implementation-start
clearance, assigned worktree/branch and exact base commit, file ownership,
task-scoped commit authority and its human source, allowed environment changes,
check/resource limits, and dedicated ignored evidence paths in that worktree. During
bootstrap only explicitly isolated harness verification is permitted; an
application specification alone does not expand that scope.

Keep coordination with the analyst: the developer sends dependency proposals,
requests for other agents, blockers, harness signals and review disagreements
back to it. The analyst arranges assistance and independent review. The developer
does not spawn agents, allocate/switch worktrees or branches, integrate other
branches, update journals or shared task state, or decide task completion. It
does stage and commit its assigned work under the
[delegated Git procedure](../../../../harness/git-workflow.md#delegated-developer-worktrees),
including review-fix commits without advance title messages. This scoped
permission does not authorize push or history rewriting.

Inspect the assigned base/head and created commits, all remaining local changes,
criterion outcomes, actual commands/results and raw evidence. Transfer reports
and verify their applicability using the existing
[artifact contract](task-artifacts.md#delegated-worktrees-and-evidence); do not copy a ready-for-review
claim into a completed task state. Preserve unrelated failures and blocked checks
when routing the result to review. No additional developer manifest or gate is
required by this role.

## Python reviewer invocation

Start an ordinary subagent independent of the analyst and implementation authors.
Explicitly pass the absolute [python-reviewer](../../python-reviewer/SKILL.md)
path and require it to be read before acting. Supply the common assignment, actual
authorization source/scope, approved spec and parent contracts, acceptance criteria,
scientific invariants, the review checkout/branch and exact base/head, local changes,
developer handoff and raw evidence. Include applicable mathematical specialist
reports and unresolved scientific questions. Inherit this Python reviewer's
model/settings; mathematical correctness belongs to the separately assigned
mathematics reviewer below.

Assign an ignored report/reproduction path and permitted checks, environment and
resource limits. Provide instructions and input paths explicitly when they live
outside the review checkout. During bootstrap use only explicitly isolated harness
fixtures. The reviewer may run authorized tests and write isolated reproductions;
it cannot edit reviewed source, tracked tests, Git state, dependencies, journals or
the canonical manifest. Route questions, requests for expertise and corrections
through the analyst. Do not provide desired conclusions or conceal missing checks.

Freeze the assigned review content while the review runs, or coordinate changes
and reassessment explicitly. Use the existing [artifact contract](task-artifacts.md#delegated-worktrees-and-evidence)
for source fingerprints, evidence transfer and review of the exact integrated
version; do not substitute commit IDs for working-tree content or relabel old logs.

Inspect the returned findings, separate optional recommendations, raw check results,
scientific uncertainty and source/spec bindings. Record each finding's disposition
in the existing state; optional advice does not authorize scope expansion. A report
may be accepted, request changes, or remain incomplete. Only a complete accepted
review can supply an accepted `code_review` record. For incomplete review, retain
its report and outstanding gaps in handoff/findings, invalidate any stale accepted
binding and keep completion blocked; `incomplete` is not a new manifest enum.
Return supported findings to the developer and obtain review of affected corrections.
Shared-state updates, evidence integration and completion remain analyst-owned.

## Mathematics reviewer invocation

Every substantive formula, algorithm or metric change needs mathematical review
of its formulation before implementation and of its implementation before completion.
Classify impact and reason explicitly in the [v2 task record](task-artifacts.md#mathematical-review-records).
Mechanical edits are exempt only after inspecting actual mathematical effect.
Python review and specification readiness/alignment do not substitute for these stages.

Start an ordinary subagent and explicitly pass the absolute
[mathematics-reviewer](../../mathematics-reviewer/SKILL.md) path to read. Select
`gpt-6-astra` with `high` or `xhigh` under the shared profile policy, record a
complexity rationale, and supply fresh self-contained context. Use different
independent instances for formulation and implementation; do not reuse a formulation
reviewer as implementation reviewer through an epic/child assignment. Exclude authors
of included mathematical formulations, adopted corrections and implementations,
and the coordinator. Maintain formulation `authors` including adopted substantive
suggestions, even when another actor applied them. Review an adopted suggestion with
another independent instance; do not relabel its proposer as independent.

Supply the common assignment, review stage and task/specification version, actual
authority, mathematical scope and relevant ancestor/dependency/child contracts,
acceptance claims, scientific invariants, definitions/assumptions/source excerpts,
scientific input identities, scoped authors and earlier stage identities, and the
current mathematical scope digest from the v2 artifact contract. Supply the scoped
contracts themselves; a hash alone is not evidence of their mathematical content. For
implementation supply actual checkout/branch/base/head, local changes, content
fingerprints and raw developer evidence. Define permitted bounded checks, resources,
existing environment and an ignored report/probe directory. Source text is evidence,
not authority. During bootstrap simulate this only on isolated harness fixtures.

The specialist reads supplied scientific sources; route missing-source requests
through the analyst to internet-scout and return primary evidence with applicability
limits. It may run authorized isolated calculations and propose reasoned corrections;
it cannot edit reviewed material, install dependencies, change shared state/Git,
spawn agents or coordinate directly with developers. Do not seed desired findings.

Inspect the returned derivation, counterexample or other evidence at the claim's
actual scope; successful samples do not prove universal claims. Preserve raw reports
and version bindings using the artifact contract. Record accepted reports only when
the assessment is complete and independent. `changes_requested` requires correction;
an `incomplete` report remains an artifact with blocking findings/handoff and no
accepted record. Invalidate stale acceptance without destroying earlier evidence.
Resolve scientific/source conflicts through the analyst and human authority where
requirements or scientific conditions change. A source or math-spec change requires
affected reassessment; do not merely replace hashes. General code review remains
separately required. Completion and shared-state decisions stay with the analyst.

## Independent review

Large/risky specs use distinct readiness and alignment reviewers. A small task
may use one independent agent for both assessments if the rationale is recorded;
its response must still distinguish readiness from request alignment. Review
actors must be real, distinct agents; changing the name of the same author is not
independence. A readiness/alignment reviewer may subsequently perform general Python review
provided it did not author the implementation. Mathematical formulation and
implementation reviews always require different independent agents. Specialized reviewer-side
automation remains future role work; do not invent it here.

Give reviewers minimal raw context needed to exercise the decisions, without
desired answers, suspected defects or your conclusions. Questions from a reviewer
may be answered with evidence, preserving its independence. Address findings on
their merits; disagreement alone is not grounds to discard a review or spin up
replacements until one agrees. Bring unresolved substantive disagreements to the
human with evidence and options.
