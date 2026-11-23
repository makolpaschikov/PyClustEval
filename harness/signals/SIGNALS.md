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

<a id="sig-010"></a>
## SIG-010: Repair mechanical task gate gaps

- Date: 2026-11-15
- Origin: Human request and approved workflow in the harness state audit chat
- Owner: harness-maintainer
- Request: Fix parent-blocker propagation, epic Python-review independence and malformed item-kind diagnostics using one separate Terra/Sol high-reasoning worker per problem.
- Evidence: Read-only audit at 20843e5 traced the three defects in gates.py and lint.py; bounded in-memory probes reproduced accepted child gates with a nonmathematical parent blocker, epic acceptance of a child-only contributor as reviewer, and TypeError for kind=[]. These were not full filesystem-fixture reproductions.
- Status: resolved
- Decision: [DEC-012](DECISIONS.md#dec-012)
- Agreement: On 2026-11-15 the human explicitly confirmed the described three-fix workflow and new codex/harness-gate-fixes branch from experiments-series-runner, delegated concrete fixes without further approval, and waived commit-title approval. Harness-only scope and independent verification remain in force.
- Details: DEC-012 fixes all three reported defects and is independently accepted. The integrated suite passed 114 tests and independent CLI verification passed 58 probes. Plan, assignments, original and copied logs, integrity records and final verification are under .agent-work/tasks/harness-gate-fixes/.

<a id="sig-011"></a>
## SIG-011: Mechanize task snapshots, evidence and state operations

- Date: 2026-11-15
- Origin: Human request and approved four-mechanism plan in the harness maintenance chat
- Owner: harness-maintainer
- Request: Implement CLI snapshots/context, bounded check execution, immutable evidence packaging/import, and guarded checkpoint/completion with one separate Terra/Sol high worker per mechanism.
- Evidence: Existing task helper computes fingerprints and gates but agents manually invoke module snippets, collect check metadata, copy and bind reports, and save receipts/state. The human reviewed the four mechanisms, benefits, algorithms and limits and explicitly approved the entire plan and codex/harness-task-automation from experiments-series-runner.
- Status: resolved
- Decision: [DEC-013](DECISIONS.md#dec-013)
- Agreement: Human approval in this chat on 2026-11-15: Да, утверждаю весь план и новую ветку codex/harness-task-automation от experiments-series-runner. Приступай к реализации. Scoped commits/review fixes on the announced new branch need no repeated approval; bootstrap remains harness-only.
- Details: DEC-013 implements all four approved mechanisms and is independently accepted. Final full harness suite passed 160 tests; original failure/review evidence and corrected results are retained under .agent-work/tasks/harness-task-automation/.

<a id="sig-012"></a>
## SIG-012: Unify harness validation and Git delivery checks

- Date: 2026-11-15
- Origin: Human request in the harness quality checks chat
- Owner: harness-maintainer
- Request: Implement a common harness validator, assigned developer staged checks, an optional pre-commit hook, analyst commit-series checks and readiness diagnostics using five separate Terra/Sol high workers.
- Evidence: The current helper lacks these commands. Prior validation omitted heading fragments; Git assignment and full-index checks are prose obligations. Prior full suite took 167.749 seconds. The human approved the five-part plan and selected the existing branch with scoped commit authority.
- Status: resolved
- Decision: [DEC-014](DECISIONS.md#dec-014)
- Agreement: Human responses in this chat: 1. Да; 2. Работай в текущей ветке, можешь именовать и делать коммиты без моего подтверждения. Scope is the five-part plan and review fixes; actual hook activation in the working checkout remains a separate decision.
- Details: DEC-014 implements all five approved mechanisms and is independently accepted. Final affected suite and actual staged hook/assignment/handoff lifecycle passed after supported corrections; working-checkout hook activation remains excluded. Evidence: .agent-work/tasks/harness-quality-checks/verification.md.

<a id="sig-013"></a>
## SIG-013: Clarify maintainer planning and script delegation

- Date: 2026-11-16
- Origin: Human request in chat 01a1e0fe-4d6d-7cc0-94e1-116e730f62fc
- Owner: harness-maintainer
- Request: Incorporate agreed overview, planning, harness-script delegation and scoped technical-autonomy rules derived from two preceding maintenance chats.
- Evidence: Read all eleven human messages and approval context from chats 01a1de98-56ab-7e60-9292-6d3ba71f11fa and 01a1e0c6-f8b9-70c3-947d-6da77c14a6de. The current skill explicitly delegates investigation and verification but does not define the requested implementation-worker workflow. Human excluded historical Git permissions and urgency.
- Status: resolved
- Decision: [DEC-015](DECISIONS.md#dec-015)
- Agreement: After discussing all four groups, the human approved the complete five-file package and new codex/harness-maintainer-workflow from experiments-series-runner at d39609f with да on 2026-11-16. Caller-selected Terra/Sol medium/high/xhigh applies only to harness implementation workers; existing specialist profiles and Git rules remain.
- Details: DEC-015 implements the four approved groups and separate implementation-worker effort criteria. Common validation and nine independent textual scenarios plus two fresh correction scenarios passed; stock skill validation lacks PyYAML. Evidence and source mapping: .agent-work/tasks/harness-maintainer-workflow/verification.md and plan.md. Historical Git permissions and urgency were not generalized.

<a id="sig-014"></a>
## SIG-014: Register agent feedback with an analyst fallback

- Date: 2026-11-16
- Origin: Human request in the harness signal-routing chat
- Owner: harness-maintainer
- Request: Use the existing journal for analyst-first agent feedback, analyst triage and permitted local corrections/workarounds, immediate human escalation for blockers, session-end signal summaries, and exceptional worker registration after analyst refusal or leaving a report unprocessed. Review signals with the human and maintainer later.
- Evidence: Current worker instructions prohibit journal writes and all agent-origin registration depends on the analyst. The journal helper already supports an explicit directory and a writer lock. This is a preventive instruction change; no live suppressed signal was reproduced.
- Status: resolved
- Decision: [DEC-016](DECISIONS.md#dec-016)
- Agreement: The human proposed the journal-only workflow, answered 'Да, как исключение' to exceptional worker registration, then selected option 'А' for the presented implementation branch: codex/harness-signal-routing from experiments-series-runner with announced scoped automatic commits. No scheduled delivery, new service or automatic maintainer launch is included.
- Details: DEC-016 implements the agreed journal-only workflow and independent worker-registration exception. Common validation, independent nine-scenario trial, consistency review and isolated shared-directory/lock probe passed. Evidence: .agent-work/tasks/harness-signal-routing/verification.md. Stock skill validation remains unavailable without PyYAML; no environment changes or independent delivery guarantee.

<a id="sig-015"></a>
## SIG-015: Operate local experiment campaigns from outlined scenarios

- Date: 2026-11-24
- Origin: Human request and interview following delivery of the local experiment runner
- Owner: harness-maintainer
- Request: Create a project skill to refine an outlined comparison, obtain launch decisions, monitor the existing runner and deliver row-level results.
- Evidence: The series CLI supports planning, durable jobs, retries and verified archives. The human identified ambiguous DBSCAN settings and independent-job failures as concrete cases the operator should handle.
- Status: resolved
- Decision: [DEC-017](DECISIONS.md#dec-017)
