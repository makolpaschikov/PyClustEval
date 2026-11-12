# Harness signals

<!-- journal-format: 2 -->

<a id="sig-001"></a>
## SIG-001: Root project instructions

- Date: 2026-11-10
- Origin: Human request in the PyClustEval harness bootstrap chat
- Owner: harness-maintainer (analyst not implemented)
- Request: Introduce compact root AGENTS.md instructions for communication, scope, verification, commits, and maintenance.
- Evidence: Initially only the harness map and maintainer skill existed. The human chose harness-only bootstrap, explicit commit permission with role-skill overrides, a 32 KB ceiling, and communication rules adapted from CLAUDE.md and UniversityResearch AGENTS.md. The persona passage was excluded; the questions subsection was approved without semantic loss.
- Status: resolved
- Decision: [DEC-001](DECISIONS.md#dec-001)
- Agreement: Human approved the four-file package with discussed revisions in this chat on 2026-11-10.

<a id="sig-002"></a>
## SIG-002: Focused reading of project text and code

- Date: 2026-11-10
- Origin: Human proposal in the PyClustEval harness maintenance chat
- Owner: harness-maintainer
- Request: Prefer relevant portions of text and code over unnecessary whole-file reads, while retaining sufficient context.
- Evidence: Preventive proposal; no specific context-loss incident was established.
- Status: resolved
- Decision: [DEC-002](DECISIONS.md#dec-002)
- Agreement: Human accepted the exact reading rule in this chat on 2026-11-10: Правило ок.

<a id="sig-003"></a>
## SIG-003: Consistent signal and decision recording

- Date: 2026-11-10
- Origin: Human proposal in the PyClustEval harness maintenance chat
- Owner: harness-maintainer
- Request: Maintain journals through the helper with compact records, current status, and material evidence, without automatic update history.
- Evidence: Existing journals were maintained manually; no format-drift defect was established. DEC-001 had 65 lines and DEC-002 had 28, motivating removal of repeated instructions and process detail.
- Status: resolved
- Decision: [DEC-003](DECISIONS.md#dec-003), [DEC-004](DECISIONS.md#dec-004)
- Agreement: Human explicitly requested removal of automatic history from the script, instructions, and existing records in this chat on 2026-11-10; earlier choices are recorded in DEC-003.

<a id="sig-004"></a>
## SIG-004: Maintainer branch and commit rules

- Date: 2026-11-10
- Origin: Human request in the current PyClustEval maintenance chat
- Owner: harness-maintainer
- Request: Define branch selection before writes, scoped commit permissions for new/existing branches, and Harness-prefixed commit messages with a short body.
- Evidence: Human supplied the rules and selected the current experiments-series-runner branch; a session means one agreed change and its review fixes.
- Status: resolved
- Decision: [DEC-005](DECISIONS.md#dec-005)
- Agreement: Human requested this skill change and chose current branch plus per-change session scope in this chat on 2026-11-10.

<a id="sig-005"></a>
## SIG-005: Analyst-orchestrator for complex multi-session work

- Date: 2026-11-11
- Origin: Human request in the analyst-orchestrator harness development chat
- Owner: harness-maintainer
- Request: Develop an analyst-orchestrator capable of coordinating a complex project change to completion or proposing concrete, bounded subtasks under a persistent parent task for execution across separate human-led sessions.
- Evidence: The human selected future local experiment-series support as a capability benchmark and authorized a brief review of F:\Python\UniversityResearch\tmp\pyclusteval-local-experiments-agent-plan.md. Its historical claims were not independently rechecked. The human reports prior loss of requirements across sessions, excessive change scope, formalistic tests and premature completion claims; no individual historical incident was investigated. At registration the analyst role was planned only.
- Status: resolved
- Decision: [DEC-006](DECISIONS.md#dec-006)
- Agreement: The human accepted an in-depth interview and new branch codex/analyst-orchestrator from experiments-series-runner. Agreed requirements: approve specifications before implementation, then coordinate autonomously within scope; store Git-excluded local task artifacts, with an epic and bounded subtasks for large tasks and one document for small tasks; define all subtask goals, boundaries, dependencies, shared contracts and acceptance criteria upfront, refining technical specifications before implementation. The analyst owns architecture and contracts; developers own implementation details. Use ordinary subagents for missing specialists, separate specification validation and alignment audit for large/risky tasks, a justified combined independent specification check for small tasks, and implementation review. Apply maintainer-style branch and commit permissions without granting push, merge or history rewriting. Escalate when meaningful progress stops, supported approaches are exhausted or scope/authority must change, without a fixed retry count. The human subsequently accepted the analyst gates, templates and modular helper, with scripts grouped under harness/scripts/task/.
- Details: DEC-006 implements the agreed role, local templates, format linting and analyst gates with script grouping under harness/scripts/task/. Other-role gates remain deferred. Additional requirements can be handled as later maintenance changes.

<a id="sig-006"></a>
## SIG-006: Python developer role

- Date: 2026-11-12
- Origin: Human request in the Python developer harness development chat
- Owner: harness-maintainer
- Request: Define and implement the Python developer role and its integration with the analyst workflow after an in-depth interview and agreement on the concrete design.
- Evidence: At registration the developer role was planned in the harness map and the analyst supplied a fallback assignment contract. The human chose role development as the next step and challenged using one pilot to infer general role requirements; broader behavioral improvements should draw on varied task experience.
- Status: resolved
- Decision: [DEC-007](DECISIONS.md#dec-007), [DEC-008](DECISIONS.md#dec-008)
- Agreement: The human approved the original role under DEC-007, then separately discussed Git ownership and approved the complete DEC-008 replacement with да in this chat on 2026-11-12. This continues the same maintenance work and review corrections on codex/python-developer with scoped automatic commits. Harness-only bootstrap is unchanged.
- Details: The interviewed non-Git role requirements remain implemented from DEC-007. DEC-008 supersedes its Git boundary: analyst-allocated worktrees, developer-owned scoped commits without advance title messages, new commits for review corrections, and analyst-owned integration/state. Independent instruction, actual Git/worktree, evidence-transfer and textual checks completed; the worker-fingerprint documentation finding was resolved. Broader refinement should use experience from varied real tasks.

<a id="sig-007"></a>
## SIG-007: Python reviewer role

- Date: 2026-11-13
- Origin: Human request in the Python reviewer harness development chat
- Owner: harness-maintainer
- Request: Define the Python reviewer role, its analyst invocation and independent behavioral verification after an in-depth interview and agreement on the concrete design.
- Evidence: At registration the harness map listed the reviewer as planned and analyst delegation used a brief fallback contract. The human requested role development after a read-only roadmap discussion; no project reviewer failure was reported or investigated. The implemented role and its isolated verification are recorded in DEC-009.
- Status: resolved
- Decision: [DEC-009](DECISIONS.md#dec-009)
- Agreement: On 2026-11-13 the human accepted the complete DEC-009 package and six optional-recommendation criteria with Да, согласен after the detailed interview. The agreed behavior covers correctness, requirements, testing, maintainability and affected mathematics/algorithms; isolated reproductions; evidence-backed blockers; narrowly filtered optional recommendations; risk-based checks and justified reuse of developer evidence. The chosen codex/python-reviewer branch from experiments-series-runner retains announced scoped automatic commits. Harness-only bootstrap remains unchanged; the separate mathematics specialist is deferred.
- Details: Deferred human proposal from the first interview block: later introduce a separate subagent for mathematical correctness of formula and algorithm implementations, using astra-6 with high reasoning as named by the human. This is a future capability request, not a currently available role or permission to configure or invoke it during reviewer development. Confirm the host model identifier when that future work is undertaken.

<a id="sig-008"></a>
## SIG-008: Remaining harness specialist subagents

- Date: 2026-11-13
- Origin: Human request in the harness-subagents maintenance chat
- Owner: harness-maintainer
- Request: Develop the planned code scout, internet scout, specification validator and specification auditor roles, their invocation contracts and independent behavioral verification after an in-depth interview and concrete design agreement.
- Evidence: At registration all four roles remain planned in harness/README.md and use fallback assignment contracts. The analyst, Python developer and Python reviewer skills already exist. No specific specialist-role failure was reported.
- Status: resolved
- Decision: [DEC-010](DECISIONS.md#dec-010)
- Agreement: On 2026-11-13 the human approved the entire DEC-010 proposal with: Да, согласен. Реализуй весь пакет. The earlier four-role interview, branch choice and announced automatic commits remain in scope.
- Details: DEC-010 implements and independently verifies the four requested roles, shared profile policy and caller integration. A code-scout diagnostic-label issue was corrected within scope and rechecked. The analyst and maintainer must read the revised contracts and pass current skills/policy explicitly to new workers. Stock skill validation remains unavailable without PyYAML; alternate metadata/link checks and independent behavior checks passed. The mathematics specialist remains deferred and harness-only bootstrap remains in force.

<a id="sig-009"></a>
## SIG-009: Mathematics reviewer subagent

- Date: 2026-11-13
- Origin: Human request in the mathematics-reviewer harness maintenance chat
- Owner: harness-maintainer
- Request: Develop the deferred mathematics specialist to check formulas, assumptions and algorithms in specifications before implementation, and their implementation, after an in-depth interview and agreement on the concrete design.
- Evidence: At registration Python reviewer performed affected mathematical checks and no dedicated mathematics specialist existed. The human resumed the deferred proposal in SIG-007; no specific project mathematical failure was reported. DEC-011 now implements the specialist, ownership transfer and independent checks.
- Status: resolved
- Decision: [DEC-011](DECISIONS.md#dec-011)
- Agreement: The human approved the complete DEC-011 package with да after the detailed interview and linked concrete proposal, including distinct stage agents, Astra high/xhigh, isolated checks, analyst/internet-scout source routing, correction proposals, mandatory helper gates and explicit migration. The chosen codex/mathematics-reviewer branch from 7b1cd23e6d4af1bdbf1beb87fcf8d32bd94db441 retains announced scoped automatic commits.
- Details: DEC-011 is implemented and independently verified. The mathematical scope-binding defect found by package review was fixed and rechecked. Final evidence is .agent-work/tasks/harness-mathematics-reviewer/verification.md. Analysts and maintainers must load current invocation/artifact instructions; Python reviewer and validator must use revised mathematical routing. New mathematical workers read current skill/profile. Stock validation lacks PyYAML; alternative checks passed. Bootstrap remains harness-only; existing v1 tasks need explicit selected migration and reassessment.
