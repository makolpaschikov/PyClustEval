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
