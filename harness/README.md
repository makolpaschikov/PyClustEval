# PyClustEval agent harness

This harness supports development and maintenance across PyClustEval. It defines how agents turn a human request into an implementable specification, deliver and review changes, and improve their own working instructions through recorded decisions.

## Current state and entry point

The harness is being bootstrapped. The [root project instructions](../AGENTS.md), this map, the [harness-maintainer](../.agents/skills/harness-maintainer/SKILL.md) and [analyst-orchestrator](../.agents/skills/analyst-orchestrator/SKILL.md) skills, [shared Git procedure](git-workflow.md), [signal](signals/SIGNALS.md) and [decision](signals/DECISIONS.md) journals and their [helper](signals/README.md), and the analyst's [task templates and helper](../.agents/skills/analyst-orchestrator/references/task-artifacts.md) are available. The [Python developer](../.agents/skills/python-developer/SKILL.md) and [Python reviewer](../.agents/skills/python-reviewer/SKILL.md) skills are available through analyst assignments after isolated verification. The four specialist skills below and their [model profiles](subagent-profiles.md) are available after independent isolated verification under [DEC-010](signals/DECISIONS.md#dec-010). The analyst assigns bounded work to ordinary subagents when the host permits it; these are explicit assignments, not registered host agent types or automatic routing.

Follow the temporary bootstrap scope in [AGENTS.md](../AGENTS.md#purpose-and-current-scope). The target application-development workflow below does not lift that restriction.

Open a Codex chat in the PyClustEval project and invoke `$harness-maintainer` with a request to develop or repair the harness. The maintainer interviews the human, proposes a concrete change, obtains agreement, implements it, and verifies the result. It can be used before the other roles exist.

Invoke `$analyst-orchestrator` to analyze and coordinate a project task or resume a
selected subtask. It proposes whole-task delivery or an epic with bounded,
dependent subtasks, obtains specification approval, and coordinates implementation
and independent review within the authorized scope. During bootstrap this remains
limited to harness investigation and isolated verification; application execution
still needs explicit human scope expansion. The analyst skill is an entry point
for the main chat, not a background service.

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
It checks implementation, affected mathematics, maintainability and evidence;
it may run authorized tests and create isolated reproductions, but cannot edit
the reviewed code or shared state. Findings, optional recommendations and
incomplete verification return through the analyst. A separate mathematics
specialist remains a deferred proposal in [SIG-007](signals/SIGNALS.md#sig-007).

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
developer/reviewer settings or their existing assistance-routing rules.

## Roles

| Role | Input and responsibility | Output and boundary |
| --- | --- | --- |
| Analyst-orchestrator | Understand the human's request, investigate the relevant context, and produce a self-contained specification. Delegate implementation tasks, request reviews, answer agents' questions from evidence, and coordinate corrections. | An implementation-ready specification, coordinated handoffs, and a delivery report with verification evidence and unresolved issues. Ask the human about decisions that cannot be resolved from the agreed task and available evidence. |
| Python developer | Implement assigned specification requirements in the application's Python code and project environment. Run checks appropriate to the change and report deviations or blockers. | Code and environment changes, verification results, and a concise handoff to the analyst. Do not silently redefine requirements to fit an implementation. |
| Python reviewer | Independently inspect changes for defects, regressions, task compliance, affected mathematical correctness and maintainability; assess verification evidence. | Evidence-backed blocking findings, narrowly filtered optional recommendations and an explicit verdict or incomplete-review report. Route corrections through the analyst; do not implement fixes or update shared state. |
| Harness maintainer | Maintain root agent instructions, role definitions, harness skills, project agent settings, harness scripts, and signal/decision records. Interview the human or investigate a signal routed by the analyst. | An agreed harness change and its verification, or a researched proposal awaiting human agreement. Application features and the application's computational environment belong to the Python developer. |
| Code scout | Trace code paths, callers, interfaces, configuration and tests; run checks only with explicit effect/resource authority. | Referenced facts and separately labeled causal hypotheses/judgments; no solution proposals, source edits or environment changes. |
| Internet scout | Investigate bounded programming/scientific questions using primary sources and applicable versions/conditions. | Supported evidence, contradictions, limits or a partial answer; no solution recommendations, mathematical certification or unassigned scope expansion. |
| Specification validator | Check completeness, ambiguity, consistency, observable acceptance and material technical constraints against code/interfaces. | Independent readiness findings and verdict; local wording suggestions are allowed, while semantic/architecture decisions return to the analyst. |
| Specification auditor | Compare original requests/corrections and project facts with the spec; inspect omissions, unsupported assumptions and disproportionate scope/complexity. | Independent alignment findings and verdict with concrete evidence; no invented user intent, preference-based objections or spec edits. |

All roles in the table are implemented as project skills.
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
and role-specific automation are not implemented; the task helper remains analyst-owned.

## Target development workflow

1. The analyst clarifies the request, obtains relevant evidence from scouts when needed, and prepares the specification.
2. For large/risky work, distinct validators and auditors check readiness and alignment with the original request/project facts. A small task may combine these two assessments in one independent agent with a recorded rationale. The analyst resolves findings and records consequential clarifications; implementation review remains independent.
3. The analyst assigns bounded implementation tasks in dedicated developer worktrees, including the specification, permitted scope, base/branch, commit authority, dependencies and acceptance checks. Developers commit their assigned changes. Parallel assignments need clear ownership and analyst-led integration; local task evidence is transferred and revalidated before completion.
4. The reviewer checks the resulting changes against the task and reports findings to the analyst. The analyst routes necessary fixes to a developer and arranges review of the corrections.
5. The analyst reports what was delivered, what was actually verified, and any remaining limitations. Unresolved requirements are not silently treated as completed work.

The analyst owns communication between these roles. It answers questions from the agreed requirements and evidence; material gaps in user intent go back to the human. Repeated failures or unresolved disagreements require a revised approach or a clear blocker report, not an endless developer/reviewer loop.

## Harness maintenance and signals

Human requests for harness changes go directly to the maintainer. A detailed interview establishes the problem, expected behavior, constraints, and tradeoffs. The maintainer then presents the proposed changes, affected files, consequences, and verification approach for human agreement before implementation. Existing answers and approvals remain valid within their agreed scope.

An agent reports a harness problem or improvement opportunity to the analyst. The analyst registers the signal, checks for duplicates, supplies the task context, and decides whether to invoke the maintainer for investigation. A signal can describe a need or a proposed improvement; it does not have to be a confirmed defect.

The maintainer may investigate, ask the analyst for more evidence, and prepare a proposal without further human involvement. The analyst presents the proposal to the human. Agent-origin signals do not authorize the maintainer to change the harness without human agreement. Writing a signal in a file does not automatically launch an agent.

All substantive requests to improve the harness, whether human- or agent-originated, belong in the signal and decision records. Ordinary questions without a proposed change do not need entries. Keep current status, decisions, and material evidence concise; omit automatic update history. Distinguish a reported issue, an agreed decision, an implemented change, and a verified outcome.

The analyst owns agent-origin signal registration and coordination. The maintainer records its investigation, the human's decision, and implementation/verification outcomes, coordinating journal edits with the analyst. Agents use the [journal helper](signals/README.md) for every create/update and validate human edits before continuing. Avoid concurrent writes to the same journal; the helper does not grant approval or launch agents.

## Repository layout

Paths are relative to the PyClustEval repository root.

```text
AGENTS.md                                  available: shared project instructions
.agents/
  skills/
    harness-maintainer/
      SKILL.md                             available: maintainer workflow
    analyst-orchestrator/
      SKILL.md                             available: analyst workflow
      references/                          available: artifacts and delegation
      assets/                              available: three versioned templates
    python-developer/
      SKILL.md                             available: analyst-assigned implementation
    python-reviewer/
      SKILL.md                             available: independent implementation review
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
  git-workflow.md                          available: shared branch/commit permissions
  subagent-profiles.md                      available: permitted specialist model/effort choices
  scripts/
    journal.py                             available: create, update, check, migrate
    task/
      task.py                              available: init, lint, snapshot, check
      task_support/                        available: formats, artifacts, lint, gates
  tests/
    test_journal.py                         available: isolated helper checks
    test_task.py                            available: isolated task lifecycle checks
  signals/
    README.md                              available: format and helper usage
    SIGNALS.md                             available: requests, evidence, and progress
    DECISIONS.md                           available: linked decisions and outcomes
```

`.agent-work/tasks/` holds local task instances, manifests and verification
artifacts and is excluded from Git. Templates and helper code remain tracked.
The analyst helper checks format, specification readiness, implementation start,
completion and resumption. It checks recorded evidence and content fingerprints;
it does not authenticate human consent, execute recorded test commands or prove
that tests establish the intended behavior.

All six worker definitions are project skills explicitly read by ordinary
subagents. Model selection is an explicit caller action, not automatic skill loading
or host agent registration. Native host configuration is not part of this package.

- `harness/scripts/` is for helpers with a concrete, repeatable purpose. Add scripts when needed rather than creating unused scaffolding.
- `harness/signals/SIGNALS.md` tracks the source, problem or desired improvement, evidence, owner, status, and related decisions for each substantive request.
- `harness/signals/DECISIONS.md` explains the selected resolution, its rationale, human agreement where applicable, affected scope, and actual implementation and verification results. Rejected or deferred proposals remain traceable.

The journals were initialized by [DEC-001](signals/DECISIONS.md#dec-001); their helper and compact format were introduced in [DEC-003](signals/DECISIONS.md#dec-003), with automatic history removed by [DEC-004](signals/DECISIONS.md#dec-004). The analyst skill, local task format and helper were introduced in [DEC-006](signals/DECISIONS.md#dec-006). The developer skill and its analyst invocation were introduced in [DEC-007](signals/DECISIONS.md#dec-007); [DEC-008](signals/DECISIONS.md#dec-008) retains that behavior while replacing Git ownership with delegated worktree commits. The reviewer skill, recommendation criteria and analyst invocation are defined by [DEC-009](signals/DECISIONS.md#dec-009). Human maintenance requests still go directly to the maintainer; agent-origin signals go through the analyst. Journal entries do not launch work automatically.

## Verification of harness changes

The four specialist skills, selectable model profiles and caller integration are
recorded in [DEC-010](signals/DECISIONS.md#dec-010). The analyst and maintainer must
use the revised invocation instructions and pass current skills/policy explicitly
to new workers. Stock skill validation was unavailable without PyYAML; metadata,
local links and independent behavior were checked without adding dependencies.

Every change receives a self-check. Substantial changes to agent behavior, responsibilities, or coordination also receive an independent subagent check using realistic, bounded scenarios. Small editorial changes need only a proportionate self-check.

The maintainer can use an ordinary independent subagent with an explicit task and restricted scope for harness checks. It must distinguish checks actually run from checks merely proposed or unavailable. Changes to scripts require execution checks appropriate to their behavior, using isolated fixtures where needed.

After changing instructions, identify the affected roles and tell the analyst what must be passed to active agents. Editing a file alone is not evidence that an already running agent has adopted the new instructions.
