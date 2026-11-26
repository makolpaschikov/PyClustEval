# PyClustEval agent harness

Use the [role table](#roles) to find the project skill for experiment design, campaign operation, application development, project navigation or harness maintenance.

## Current state and entry point

The harness uses project skills for human-facing workflows and delegated work.
See the [Git procedure](git-workflow.md) for task branches, local integration,
push or PR delivery and cleanup, the
[journal guide](signals/README.md) for signals and decisions, and the analyst's
[task guide](../.agents/skills/analyst-orchestrator/references/task-artifacts.md)
for templates and task state. The analyst delegates bounded work to ordinary
subagents using the [model profiles](subagent-profiles.md) where applicable.

Follow the temporary bootstrap scope in [AGENTS.md](../AGENTS.md#purpose-and-current-scope). The target application-development workflow below does not lift that restriction.

Open a Codex chat in the PyClustEval project and invoke `$harness-maintainer` with a request to develop or repair the harness. The maintainer interviews the human, proposes a concrete change, obtains agreement, implements it, and verifies the result.

Invoke `$analyst-orchestrator` to analyze and coordinate a project task or resume a
selected subtask. It proposes whole-task delivery or an epic with bounded,
dependent subtasks, obtains specification approval, and coordinates implementation
and independent review within the authorized scope. During bootstrap this remains
limited to harness investigation and isolated verification; application execution
still needs explicit human scope expansion. The analyst skill is an entry point
for the main chat, not a background service.

Use [experiment-design](../.agents/skills/experiment-design/SKILL.md) when a
researcher has a topic and needs to choose or justify the comparisons. It
produces an agreed Markdown design with one row per comparison for the operator.

Invoke [experiment-campaign](../.agents/skills/experiment-campaign/SKILL.md)
with an outlined comparison, a scenario table, a series plan or a saved campaign
directory. It helps refine and validate the plan, operate an authorized run
through the existing series CLI, and report verified coverage by source scenario.
For a live campaign, apply the project scope and launch decisions in the skill.

Python development is assigned by the analyst, which explicitly passes the
developer skill and a self-contained assignment to an ordinary subagent using
the [invocation contract](../.agents/skills/analyst-orchestrator/references/delegation.md#python-developer-invocation).
The developer implements and checks the assigned behavior, then returns evidence
and questions to the analyst. It has no standalone human-task entry point and
stages and commits assigned changes in its dedicated worktree under delegated
authority. The analyst owns worktree/branch allocation, integration, shared
task state and completion decisions. Advance commit-title messages are not
required for developer commits; see the [Git procedure](git-workflow.md#delegated-developer-worktrees).

Python review is assigned to a separate ordinary subagent using the reviewer
skill and [invocation contract](../.agents/skills/analyst-orchestrator/references/delegation.md#python-reviewer-invocation).
It checks code behavior, maintainability and evidence;
it may run authorized tests and create isolated reproductions, but cannot edit
the reviewed code or shared state. Findings, optional recommendations and
incomplete verification return through the analyst. Mathematical correctness is
assigned to the [mathematics reviewer](../.agents/skills/mathematics-reviewer/SKILL.md)
under [DEC-011](signals/DECISIONS.md#dec-011), available after isolated verification.
Every substantive formula, algorithm or metric change requires formulation review
before implementation and implementation review before completion by different
independent agents. The caller selects Astra with high/xhigh reasoning; missing
scientific sources go through the analyst to internet-scout. The specialist may
run authorized isolated probes and propose corrections, but cannot edit reviewed
material. Adopted mathematical suggestions count as authorship for independence.

The [code scout](../.agents/skills/code-scout/SKILL.md) and
[internet scout](../.agents/skills/internet-scout/SKILL.md) gather evidence for the
analyst or for authorized maintainer investigations. They do not propose solutions.
The [specification validator](../.agents/skills/specification-validator/SKILL.md)
checks readiness and material technical constraints; the
[specification auditor](../.agents/skills/specification-auditor/SKILL.md) checks
original-request/project alignment and disproportionate scope or complexity.
The analyst invokes these reviewers independently; both may suggest local wording
but leave specification edits and semantic/architecture decisions to the analyst.
Use the [invocation contracts](../.agents/skills/analyst-orchestrator/references/delegation.md)
and explicitly selected [model/effort profiles](subagent-profiles.md), with fresh
self-contained context when the host requires it. These profiles do not change
Python developer/reviewer settings or their existing assistance-routing rules.

Invoke [$project-map-maintainer](../.agents/skills/project-map-maintainer/SKILL.md)
to audit or maintain the English root README, project index and directory
READMEs. The analyst also assigns this skill to an ordinary subagent to update
the map for an integrated delivery.

## Roles

The first five skills are entry points for a project chat. The project map
maintainer also accepts analyst assignments. The remaining roles are delegated.

| Role | Input and responsibility | Output and boundary |
| --- | --- | --- |
| [Harness maintainer](../.agents/skills/harness-maintainer/SKILL.md) | Maintain root agent instructions, role definitions, harness skills, project agent settings, harness documentation and scripts, and signal/decision records. Review recorded signals at the human's request, directly or through the analyst. | An agreed harness change and its verification, or a researched proposal awaiting human agreement. Application features and the application's computational environment belong to the Python developer. |
| [Analyst-orchestrator](../.agents/skills/analyst-orchestrator/SKILL.md) | Understand the human's request, investigate the relevant context, and produce a self-contained specification. Delegate implementation tasks, request reviews, answer agents' questions from evidence, and coordinate corrections. | An implementation-ready specification, coordinated handoffs, and a delivery report with verification evidence and unresolved issues. Ask the human about decisions that cannot be resolved from the agreed task and available evidence. |
| [Experiment designer](../.agents/skills/experiment-design/SKILL.md) (`$experiment-design`) | Work with the researcher to turn a topic into questions and comparisons. Check controls, feasibility and budget. | An agreed Markdown design with one row per comparison, its rationale and open questions for the operator. |
| [Experiment campaign operator](../.agents/skills/experiment-campaign/SKILL.md) (`$experiment-campaign`) | Refine outlined comparisons or a design into an executable plan. Run, monitor or resume a campaign within its approved scope. | A validated plan for planning requests. After execution, report archive verification, actual coverage and any failures by source scenario. |
| [Project map maintainer](../.agents/skills/project-map-maintainer/SKILL.md) | Audit or update the English project map on request. Inspect the integrated diff of each unit delivered by the analyst. | Referenced findings, verified map edits or a reason the map is current. Uses the shared Git workflow for standalone edits. The analyst commits delegated edits. |
| [Python developer](../.agents/skills/python-developer/SKILL.md) | Implement assigned specification requirements in the application's Python code and project environment. Run checks appropriate to the change and report deviations or blockers. | Code and environment changes, verification results, and a concise handoff to the analyst. Do not silently redefine requirements to fit an implementation. |
| [Python reviewer](../.agents/skills/python-reviewer/SKILL.md) | Independently inspect code changes for defects, regressions, task compliance and maintainability; assess verification evidence. | Route mathematical questions to the specialist through the analyst; return supported findings, optional recommendations and verification gaps without implementing fixes. |
| [Mathematics reviewer](../.agents/skills/mathematics-reviewer/SKILL.md) | Independently assess mathematical formulations and implementations against scoped claims, assumptions and sources; perform authorized bounded checks. | Distinct stage reviewers; evidence-backed findings, reasoned correction proposals and incomplete assessments through the analyst. No reviewed-file edits; source research through internet-scout. |
| [Code scout](../.agents/skills/code-scout/SKILL.md) | Trace code paths, callers, interfaces, configuration and tests; run checks only with explicit effect/resource authority. | Referenced facts and separately labeled causal hypotheses/judgments; no solution proposals, source edits or environment changes. |
| [Internet scout](../.agents/skills/internet-scout/SKILL.md) | Investigate bounded programming/scientific questions using primary sources and applicable versions/conditions. | Supported evidence, contradictions, limits or a partial answer; no solution recommendations, mathematical certification or unassigned scope expansion. |
| [Specification validator](../.agents/skills/specification-validator/SKILL.md) | Check completeness, ambiguity, consistency, observable acceptance and material technical constraints against code/interfaces. | Independent readiness findings and verdict; local wording suggestions are allowed, while semantic/architecture decisions return to the analyst. |
| [Specification auditor](../.agents/skills/specification-auditor/SKILL.md) | Compare original requests/corrections and project facts with the spec; inspect omissions, unsupported assumptions and disproportionate scope/complexity. | Independent alignment findings and verdict with concrete evidence; no invented user intent, preference-based objections or spec edits. |

The harness maintainer, analyst and standalone project map maintainer integrate
any task-local branches into the agreed working branch. At completion they offer
the [Git delivery choices](git-workflow.md#delivery-at-completion); the human
reviews the proposed branches, title and body before publication. These roles
[clean up merged task branches and temporary worktrees](git-workflow.md#local-cleanup-after-a-verified-merge)
after checking the merge, worker handoff and preservation of required files.

All roles in the table are implemented as project skills. The mathematical role
and task gates have isolated verification under DEC-011.
Their checks include isolated helper execution, a developer fixture fix with
executed tests, and independent behavioral scenarios. These do not establish
live application delivery. The developer Git workflow also has isolated checks
of commits, review corrections, evidence transfer and integration gates under
DEC-008. Reviewer checks under DEC-009 include a formula-defect reproduction
despite passing developer tests and six independent textual scenarios covering
recommendation filtering, missing/stale evidence, scientific uncertainty,
disputed findings and reviewer independence. DEC-010 checks exercised the four
specialist roles through real isolated assignments, including a code probe and
bounded web research, plus an independent instruction review and six textual
coordination scenarios. A causal-qualification issue in the code scout was fixed
and rechecked by a fresh worker. These checks do not benchmark every allowed
model/effort pair or establish live application delivery. Native host registration
is not implemented. The task helper provides explicit worker snapshots, check
execution and report packaging; canonical evidence adoption and state changes
remain analyst-owned under the [automation contract](../.agents/skills/analyst-orchestrator/references/task-automation.md).

## Target development workflow

1. The analyst clarifies the request, obtains relevant evidence from scouts when needed, and prepares the specification.
2. For large/risky work, distinct validators and auditors check readiness and alignment with the original request/project facts. A small task may combine these two assessments in one independent agent with a recorded rationale. The analyst records mathematical impact and obtains required independent formulation review before approval/start. It resolves findings and records consequential clarifications; implementation review remains independent.
3. The analyst assigns bounded implementation tasks in dedicated developer worktrees, including the specification, permitted scope, base/branch, commit authority, dependencies and acceptance checks. Developers commit their assigned changes. Parallel assignments need clear ownership and analyst-led integration; local task evidence is transferred and revalidated before completion.
4. The Python reviewer checks code changes; a different mathematical stage agent reviews applicable mathematical implementation. The analyst routes fixes and obtains independent review of corrections, preserving authorship and scientific authority.
5. After integration and before closing each separately delivered unit, the analyst gives its complete diff to the project map maintainer, inspects its edits or no-change rationale, and checks final evidence against the resulting tree.
6. The analyst reports the integrated result, checks and remaining limitations, offers the applicable Git delivery choices and cleans up eligible local branches and worktrees.

The analyst owns communication between these roles. It answers questions from the agreed requirements and evidence; material gaps in user intent go back to the human. Repeated failures or unresolved disagreements require a revised approach or a clear blocker report, not an endless developer/reviewer loop.

## Harness maintenance and signals

Human requests for harness changes go directly to the maintainer. It confirms its
understanding before substantive work when the invocation adds concrete
instructions to the skill or material ambiguity remains, reusing confirmation within
scope. It investigates the affected area and clarifies consequential gaps; a broad
overview is performed on request. Substantial changes receive a proportionate plan
covering benefits, constraints, intended behavior and verification. Script summaries
for the human stay algorithmic; technical contracts belong in worker assignments.
Approval of the plan authorizes technical fixes within its boundaries, including
supported review corrections; material deviations require renewed agreement.

Under [DEC-015](signals/DECISIONS.md#dec-015), the maintainer delegates each
independent substantive harness-script fix or new mechanism to a separate ordinary
worker with the [harness implementation profile](subagent-profiles.md#harness-implementation-workers).
It selects Terra/Sol with medium/high/xhigh by task complexity, retains instruction
writing, shared design, coordination, integration and acceptance, and may perform
minor mechanical/integration edits directly. This does not add a registered role,
change specialist review profiles, or transfer application development to the
maintainer. The existing independent verification and Git rules remain applicable.

Agents follow the [feedback contract](signals/README.md#agent-feedback-and-fallback-registration):
report to the analyst first, then receive a registered signal ID and an authorized
local correction or workaround. Uncertain causes remain explicit. A blocking
signal pauses the task and goes to the human immediately. At session end the
analyst lists new signal IDs, actions/results and questions for maintainer review.
After an explicit refusal or an unprocessed report, workers may register through
the helper in the assigned shared journal and notify the analyst. This is a narrow
exception to journal-write limits, not permission to repair the harness or launch
the maintainer. Separate worktrees do not get separate signal destinations.

The human initiates later review with the maintainer. A local correction leaves
the signal open for that review. The maintainer investigates original evidence,
including worker-created records without analyst endorsement, and proposes a
disposition or change for human agreement. Neither journal entries nor session
summaries guarantee independent notification or automatically launch an agent.

All substantive requests to improve the harness, whether human- or agent-originated, belong in the signal and decision records. Ordinary questions without a proposed change do not need entries. Keep current status, decisions, and material evidence concise; omit automatic update history. Distinguish a reported issue, an agreed decision, an implemented change, and a verified outcome.

The analyst normally owns agent-origin registration and coordination, subject to
the worker exception above. The maintainer records human-led review, decisions
and implementation/verification outcomes. Agents use the
[journal helper](signals/README.md) for every create/update, validate human edits
and respect the writer lock. Failed registration remains explicitly pending in
task evidence; it is not replaced by a hand-edited or separate journal.

## Repository layout

Paths are relative to the PyClustEval repository root.

```text
AGENTS.md                                  available: shared project instructions
.agents/
  skills/
    harness-maintainer/
      SKILL.md                             available: maintainer workflow
    project-map-maintainer/
      SKILL.md                             available: standalone and delegated project map maintenance
    experiment-design/
      SKILL.md                             available: design comparisons from a research topic
    experiment-campaign/
      SKILL.md                             available: plan and operate outlined series
    analyst-orchestrator/
      SKILL.md                             available: analyst workflow
      references/                          available: artifacts and delegation
      assets/                              available: three versioned templates
    python-developer/
      SKILL.md                             available: analyst-assigned implementation
    python-reviewer/
      SKILL.md                             available: independent implementation review
    mathematics-reviewer/
      SKILL.md                             available: independent mathematical review
    code-scout/
      SKILL.md                             available: code evidence gathering
    internet-scout/
      SKILL.md                             available: external source investigation
    specification-validator/
      SKILL.md                             available: implementation readiness review
    specification-auditor/
      SKILL.md                             available: request/project alignment audit
harness/
  README.md                                available: harness map and role overview
  git-workflow.md                          available: task branches, integration, delivery and cleanup
  quality-checks.md                        available: validation, Git checks, hook and diagnostics guide
  subagent-profiles.md                      available: specialist and harness implementation profiles
  scripts/
    journal.py                             available: create, update, check, migrate
    quality.py                             available: validate, staged, handoff, hooks, precommit, doctor
    quality_support/                       available: quality CLI implementations
    task/
      task.py                              available: artifacts, gates and explicit automation commands
      task_support/                        available: formats, artifacts, lint, gates
  tests/                                   available: journal, task, mathematics, automation and Git quality checks
  signals/
    README.md                              available: format and helper usage
    SIGNALS.md                             available: requests, evidence, and progress
    DECISIONS.md                           available: linked decisions and outcomes
```

`.agent-work/tasks/` holds local task instances, manifests and verification
artifacts and is excluded from Git. Templates and helper code remain tracked.
The analyst helper checks format, specification readiness, implementation start,
completion and resumption. Its read-only gates check recorded evidence and content
fingerprints. Explicit automation commands capture worker context, execute supplied
check argv, package/import evidence and safely save checkpoints/completion. They
do not authenticate human consent or prove that passing tests establish the intended
behavior. See [task automation](../.agents/skills/analyst-orchestrator/references/task-automation.md).

Task JSON uses version 2 while Markdown remains version 1. The mathematical record
captures impact, scoped authors and distinct formulation/implementation reviews.
Required mathematical reviews are checked at start, completion and resumption,
including content bindings for relevant dependency/child mathematical contracts.
Use the [explicit migration procedure](../.agents/skills/analyst-orchestrator/references/task-artifacts.md#explicit-legacy-migration)
for a selected v1 task; it preserves original evidence and requires reassessment.

All delegated role definitions are project skills explicitly read by ordinary
subagents. Model selection is an explicit caller action, not automatic skill loading
or host agent registration. Native host configuration is not part of this package.

- `harness/scripts/` is for helpers with a concrete, repeatable purpose. Add scripts when needed rather than creating unused scaffolding.
- `harness/signals/SIGNALS.md` tracks the source, problem or desired improvement, evidence, owner, status, and related decisions for each substantive request.
- `harness/signals/DECISIONS.md` explains the selected resolution, its rationale, human agreement where applicable, affected scope, and actual implementation and verification results. Rejected or deferred proposals remain traceable.

The journals were initialized by [DEC-001](signals/DECISIONS.md#dec-001); their helper and compact format were introduced in [DEC-003](signals/DECISIONS.md#dec-003), with automatic history removed by [DEC-004](signals/DECISIONS.md#dec-004). The analyst skill, local task format and helper were introduced in [DEC-006](signals/DECISIONS.md#dec-006). The developer skill and its analyst invocation were introduced in [DEC-007](signals/DECISIONS.md#dec-007); [DEC-008](signals/DECISIONS.md#dec-008) retains that behavior while replacing Git ownership with delegated worktree commits. The reviewer skill, recommendation criteria and analyst invocation are defined by [DEC-009](signals/DECISIONS.md#dec-009). [DEC-016](signals/DECISIONS.md#dec-016) defines analyst-first signal registration with the worker fallback and human-led maintainer review. Journal entries do not launch work automatically.

## Verification of harness changes

Before committing or handing off a harness change, the maintainer
[checks the affected documentation](../.agents/skills/harness-maintainer/SKILL.md#check-affected-documentation)
against the roles or behavior it describes. The skill defines when an independent
subagent checks for discrepancies. The maintainer corrects and rechecks confirmed findings.

The [quality-check CLI](quality-checks.md) provides maintained-file validation,
assigned staged Git checks, per-commit analyst handoff checks, optional staged
pre-commit execution and readiness diagnostics under DEC-014. Assignment records
are separately versioned local inputs; task JSON v2 and Markdown v1 are unchanged.
The hook is installed explicitly and does not replace independent behavioral
verification. Use the command reference for actual activation and runtime limits.

The four specialist skills, selectable model profiles and caller integration are
recorded in [DEC-010](signals/DECISIONS.md#dec-010). The analyst and maintainer must
use the revised invocation instructions and pass current skills/policy explicitly
to new workers. Stock skill validation was unavailable without PyYAML; metadata,
local links and independent behavior were checked without adding dependencies.

[DEC-011](signals/DECISIONS.md#dec-011) adds the mathematics reviewer, transfers
mathematical correctness from Python review, and extends the task helper. Its
final suite passed 101 tests, including 50 mathematical-gate/migration cases.
Independent package review found stale enclosing mathematical reports after child
contract changes; separate scope bindings fixed this, and seven independent
correction scenarios passed. Role trials exercised faulty and valid formulations,
missing/conflicting definitions, an implementation defect despite passing developer
tests, refusal to independently accept an adopted own correction, and independent
acceptance of a corrected fixture with actual v2 bindings. These are bounded harness
checks, not live application delivery or a general guarantee of mathematical accuracy.
The analyst, Python reviewer, specification validator and maintainer must use the
revised routing/contracts; mathematical workers must read the current skill/profile.

Every change receives a self-check. Substantial changes to agent behavior, responsibilities, or coordination also receive an independent subagent check using realistic, bounded scenarios. Small editorial changes need only a proportionate self-check.

The maintainer can use an ordinary independent subagent with an explicit task and restricted scope for harness checks. It must distinguish checks actually run from checks merely proposed or unavailable. Changes to scripts require execution checks appropriate to their behavior, using isolated fixtures where needed.

After changing instructions, identify the affected roles and tell the analyst what must be passed to active agents. Editing a file alone is not evidence that an already running agent has adopted the new instructions.
