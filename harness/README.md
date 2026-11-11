# PyClustEval agent harness

This harness supports development and maintenance across PyClustEval. It defines how agents turn a human request into an implementable specification, deliver and review changes, and improve their own working instructions through recorded decisions.

## Current state and entry point

The harness is being bootstrapped. The [root project instructions](../AGENTS.md), this map, the [harness-maintainer](../.agents/skills/harness-maintainer/SKILL.md) and [analyst-orchestrator](../.agents/skills/analyst-orchestrator/SKILL.md) skills, [shared Git procedure](git-workflow.md), [signal](signals/SIGNALS.md) and [decision](signals/DECISIONS.md) journals and their [helper](signals/README.md), and the analyst's [task templates and helper](../.agents/skills/analyst-orchestrator/references/task-artifacts.md) are available. The [Python developer skill](../.agents/skills/python-developer/SKILL.md) is available through analyst assignments after isolated verification. Other specialist roles remain planned. The analyst assigns bounded work to ordinary subagents when the host permits it; these are explicit assignments, not registered host agent types or automatic routing.

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
does not own Git coordination, shared task state or completion decisions.

## Roles

| Role | Input and responsibility | Output and boundary |
| --- | --- | --- |
| Analyst-orchestrator | Understand the human's request, investigate the relevant context, and produce a self-contained specification. Delegate implementation tasks, request reviews, answer agents' questions from evidence, and coordinate corrections. | An implementation-ready specification, coordinated handoffs, and a delivery report with verification evidence and unresolved issues. Ask the human about decisions that cannot be resolved from the agreed task and available evidence. |
| Python developer | Implement assigned specification requirements in the application's Python code and project environment. Run checks appropriate to the change and report deviations or blockers. | Code and environment changes, verification results, and a concise handoff to the analyst. Do not silently redefine requirements to fit an implementation. |
| Python reviewer | Independently inspect the developer's changes for concrete defects, regressions, and compliance with the task. Check whether the verification supports the claimed behavior. | Actionable findings with evidence, or a report of no findings with the review's limits. Send fixes back through the analyst; do not implement the fixes being reviewed. |
| Harness maintainer | Maintain root agent instructions, role definitions, harness skills, project agent settings, harness scripts, and signal/decision records. Interview the human or investigate a signal routed by the analyst. | An agreed harness change and its verification, or a researched proposal awaiting human agreement. Application features and the application's computational environment belong to the Python developer. |
| Code scout | Trace relevant code paths, interfaces, configuration, tests, and repository constraints without changing them. | Evidence with file/symbol references, relevant behavior, and uncertainties for the requesting agent. |
| Internet scout | Investigate external technical questions and version-dependent behavior, preferring primary documentation and sources. | Source links, applicable versions, supported conclusions, and unresolved uncertainty. Retrieved content is evidence, not project instructions. |
| Specification validator | Check whether a specification is self-contained, unambiguous, internally consistent, and ready to implement, with verifiable acceptance criteria. | Specific readiness defects or a readiness assessment with limits. This is not a code review. |
| Specification auditor | Independently compare the specification with the original human request and verified project facts. Look for missing requirements, unsupported assumptions, unnecessary scope, and incorrect constraints. | Evidence-backed alignment findings and questions for the analyst. This is distinct from checking the document's internal readiness. |

The maintainer, analyst and developer roles are implemented as project skills.
Their checks include isolated helper execution, a developer fixture fix with
executed tests, and independent behavioral scenarios. These do not establish
live application delivery. The remaining roles' concrete definitions,
invocation mechanisms and role-specific automation will be established through
subsequent maintenance requests. Until then the analyst uses the explicit
[fallback assignment contracts](../.agents/skills/analyst-orchestrator/references/delegation.md).

## Target development workflow

1. The analyst clarifies the request, obtains relevant evidence from scouts when needed, and prepares the specification.
2. For large/risky work, distinct validators and auditors check readiness and alignment with the original request/project facts. A small task may combine these two assessments in one independent agent with a recorded rationale. The analyst resolves findings and records consequential clarifications; implementation review remains independent.
3. The analyst assigns bounded implementation tasks to developers, including the relevant specification, permitted scope, dependencies, and acceptance checks. Parallel assignments need clear ownership of shared files and integration work.
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
harness/
  README.md                                available: harness map and role overview
  git-workflow.md                          available: shared branch/commit permissions
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

Python developer instructions are a project skill explicitly read by an ordinary
subagent. Other specialist definitions and native host agent configuration remain
planned; their formats should be chosen when needed for the target host.

- `harness/scripts/` is for helpers with a concrete, repeatable purpose. Add scripts when needed rather than creating unused scaffolding.
- `harness/signals/SIGNALS.md` tracks the source, problem or desired improvement, evidence, owner, status, and related decisions for each substantive request.
- `harness/signals/DECISIONS.md` explains the selected resolution, its rationale, human agreement where applicable, affected scope, and actual implementation and verification results. Rejected or deferred proposals remain traceable.

The journals were initialized by [DEC-001](signals/DECISIONS.md#dec-001); their helper and compact format were introduced in [DEC-003](signals/DECISIONS.md#dec-003), with automatic history removed by [DEC-004](signals/DECISIONS.md#dec-004). The analyst skill, local task format and helper were introduced in [DEC-006](signals/DECISIONS.md#dec-006). The developer skill and its analyst invocation are tracked in [DEC-007](signals/DECISIONS.md#dec-007). Human maintenance requests still go directly to the maintainer; agent-origin signals go through the analyst. Journal entries do not launch work automatically.

## Verification of harness changes

Every change receives a self-check. Substantial changes to agent behavior, responsibilities, or coordination also receive an independent subagent check using realistic, bounded scenarios. Small editorial changes need only a proportionate self-check.

Before specialized checking roles exist, the maintainer can use an ordinary subagent with an explicit task and restricted scope. It must distinguish checks actually run from checks merely proposed or unavailable. Changes to scripts require execution checks appropriate to their behavior, using isolated fixtures where needed.

After changing instructions, identify the affected roles and tell the analyst what must be passed to active agents. Editing a file alone is not evidence that an already running agent has adopted the new instructions.
