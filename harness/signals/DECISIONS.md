# Harness decisions

<!-- journal-format: 2 -->

<a id="dec-001"></a>
## DEC-001: Root instructions and journal initialization

- Date: 2026-11-10
- Signal: [SIG-001](SIGNALS.md#sig-001)
- Status: verified
- Decision: Adopt compact English AGENTS.md (at most 32,000 UTF-8 bytes), harness-only bootstrap, shared communication and verification rules, and explicit commit permission with role-skill overrides. Initialize the signal and decision journals.
- Why: Avoid duplicate role procedures; preserve human control and scientific conditions. Allow relevant project reads instead of the stricter skill-only access boundary.
- Agreement: Human approved the four-file package after removing the persona passage and revising the questions subsection (this chat, 2026-11-10: Вноси весь пакет из четырёх файлов).
- Result: Created AGENTS.md and both journals; updated harness/README.md. No application, environment, or other role implementation changes.
- Check: Independent scenario reviews and static checks passed; no live application or instruction-loading checks. Agreement and prior-review history came from this chat, without independent corroboration.
- Details: A later explicit request authorized commit eb6f665. Recovery from the paused reword rebase restored experiments-series-runner without rewriting earlier history. Existing active agents must receive revised instructions explicitly.

<a id="dec-002"></a>
## DEC-002: Focused reading

- Date: 2026-11-10
- Signal: [SIG-002](SIGNALS.md#sig-002)
- Status: verified
- Decision: Prefer targeted, context-aware reading; allow justified whole-file reads and require complete applicable instructions unless already current in context. Recheck changed or incomplete sources.
- Why: Reduce irrelevant context without losing dependencies or constraints; avoid fixed line caps.
- Agreement: Human accepted the exact proposed rule in this chat on 2026-11-10: Правило ок.
- Result: Added [Reading files](../../AGENTS.md#reading-files) and related journal records; no script or skill change in this decision.
- Check: Seven independent textual scenarios and static checks passed; root file was 8,156 bytes. Runtime improvements and context savings were not measured.

<a id="dec-003"></a>
## DEC-003: Journal helper and compact decisions

- Date: 2026-11-10
- Signal: [SIG-003](SIGNALS.md#sig-003)
- Status: superseded
- Decision: Use a standard-library Python helper for agent creation, updating, validation, and reviewed migration of Markdown journals. Keep compact decisions and short inline history; supersede agreed substantive decisions instead of rewriting them.
- Why: Control format drift and record changes without repeating instructions, review transcripts, or complete old/new field texts.
- Agreement: Human chose create/update/check, mandatory agent use and inline history, then approved the compact schema/history and rewriting existing DEC-001 through DEC-003 in this chat on 2026-11-10: Да, согласен.
- Result: Added journal.py, isolated tests, the format guide, and mandatory-helper instructions; migrated all six existing records to the compact Markdown format with stable IDs.
- Check: 18 isolated unittest checks, independent code/migration/instruction reviews, live journal migration/check, and static link/format checks passed. Power-loss recovery and evidence authenticity are not established by these checks.

<a id="dec-004"></a>
## DEC-004: Current-state records without automatic history

- Date: 2026-11-10
- Signal: [SIG-003](SIGNALS.md#sig-003)
- Status: verified
- Decision: Remove automatic update history from the helper, instructions, and existing journals. Preserve current status, approval, result, checks, and substantive decision links; record exceptional facts only when material.
- Why: Routine status transitions duplicate current fields and add little value; substantive revisions remain traceable through superseding decisions.
- Agreement: Human explicitly authorized this change in the current chat on 2026-11-10: Обнови скрипт, инструкции и существующие записи.
- Result: Removed automatic history and actor/reason arguments; updated helper, instructions, tests, and all seven records to format v2. Current fields and substantive decision links are preserved.
- Check: 22 fixture tests, independent code/instruction review, static checks, and live migration/check passed. Exact comparison preserved all current fields in seven records. Power-loss recovery was not tested.
- Supersedes: [DEC-003](DECISIONS.md#dec-003)

<a id="dec-005"></a>
## DEC-005: Maintainer branch and commit workflow

- Date: 2026-11-10
- Signal: [SIG-004](SIGNALS.md#sig-004)
- Status: verified
- Decision: Ask for branch choice before the first write of each agreed harness change. Confirm base/name and announce automatic commits before creating a new branch; existing branches require explicit commit permission, reusable across the agreed change and review fixes. Require a Harness-prefixed title and a body of one to three lines.
- Why: Make branch ownership and commit authorization explicit without repeated confirmations within the same work.
- Agreement: Human supplied these rules, chose experiments-series-runner, and defined session scope as one agreed change plus review fixes (current chat, 2026-11-10).
- Result: Added Branches and commits to the harness-maintainer skill; root Git defaults remain effective except for the explicit role overrides.
- Check: Twelve independent textual scenarios and static metadata/link/format checks passed. No live branch creation or commit workflow was executed.

<a id="dec-006"></a>
## DEC-006: Analyst-orchestrator and persistent task workflow

- Date: 2026-11-11
- Signal: [SIG-005](SIGNALS.md#sig-005)
- Status: verified
- Decision: Add a project analyst-orchestrator skill with task-artifact/delegation references and versioned epic, subtask and specification templates. Support approved end-to-end delivery or bounded subtask sessions, progressive specifications, evidence-based review and resumption. Add a task.py helper with format linting and specification/start/completion/resumption gates backed by a small task.json manifest. Store generated task artifacts under Git-ignored .agent-work/tasks/. Share branch and commit-permission procedures with the maintainer, retain role-specific messages, update entry points and preserve harness-only bootstrap.
- Why: Support complex future project changes without losing requirements across sessions, expanding scope silently, relying on formalistic tests or declaring completion prematurely.
- Agreement: The human accepted the interviewed role behavior, analyst gates, versioned templates and linting, and accepted the modular implementation with the task script group under harness/scripts/task/ (current chat: В целом норм, только я бы группы скриптов в отдельные каталоги все же выделял бы — harness/scripts/task, в котором уже предложенная тобой структура). Work remains on the agreed codex/analyst-orchestrator branch, with scoped automatic commits announced before creation.
- Result: Added the analyst skill, artifact/delegation references and three versioned templates; modular init/lint/snapshot/gates under harness/scripts/task/ with isolated tests; Git-ignored local task state; shared Git permission procedure with retained maintainer messages; updated AGENTS.md and harness availability/routing. Bootstrap is unchanged and other-role gates remain deferred. No application code, environment or experiments changed.
- Check: 51 harness unittest checks passed (29 task, 22 journal). Independent script and instruction reviews reproduced and rechecked corrections for blockers, Markdown comments/code spans, upfront parent verification and deletion fingerprints across staging; no open findings. Five independent analyst scenarios exercised decomposition with 11 briefs, source drift, inadequate py_compile evidence, stalled fixes and scope/scientific creep. Static metadata, local links, Git ignore and diff checks passed; AGENTS.md is 8471 bytes. The stock skill validator could not run without PyYAML; stdlib and independent metadata checks were used without installing dependencies. Live application delivery, actual developer/reviewer delegation, authenticity of approval/evidence records, power-loss recovery and cross-worktree handoff were not established.
- Details: The analyst and maintainer must load the revised skills/shared Git procedure; root entry-point instructions were independently reread after editing. Local review evidence is under .agent-work/tasks/script-review-fixtures/, instruction-review/ and analyst-behavior/ and is intentionally not committed.

<a id="dec-007"></a>
## DEC-007: Python developer skill and analyst integration

- Date: 2026-11-12
- Signal: [SIG-006](SIGNALS.md#sig-006)
- Status: verified
- Decision: Add an English python-developer project skill for bounded implementation assignments from the analyst. Include the interviewed code-quality, documentation, testing, dependency-escalation and delegation rules, entry checks, review-fix handling and an evidence-bearing handoff. The analyst starts an ordinary subagent with the skill and a self-contained authorized assignment; update analyst instructions, delegation guidance and the harness map to describe this invocation accurately. Keep task-state, Git coordination and completion decisions with the analyst and retain harness-only bootstrap.
- Why: Provide consistent implementation behavior under the existing analyst workflow, with minimal maintainable code and checks tied to actual task behavior.
- Agreement: The human approved the complete DEC-007 package in this chat on 2026-11-12 with Да after the final proposal covering the developer skill, analyst integration, interviewed requirements, evidence handoff and independent isolated verification. Earlier answers chose a new codex/python-developer branch from experiments-series-runner with scoped automatic commits announced before creation. Approval covers the agreed harness change and review fixes, not application execution.
- Result: Added .agents/skills/python-developer/SKILL.md with the agreed implementation, documentation, typing/error-handling, testing, autonomy and handoff rules. Updated analyst skill, delegation invocation contract and harness map. Developer work uses an ordinary analyst-assigned subagent explicitly reading the skill; Git, task state and completion remain with the analyst. Existing helpers and manifest formats are unchanged; no application or environment change was made.
- Check: Independent instruction review found no actionable issues. An independent developer completed a stdlib fixture fix, reproduced two zero-score failures before implementation, and passed all five summary tests; the six-test full fixture suite retained one intentionally unrelated legacy failure reproduced on the original and left unchanged. Five independent textual scenarios exercised direct invocation, dependency scope, missing bootstrap authority, disputed/supported review findings and failed acceptance alongside an unrelated failure. Maintainer inspected actual fixture changes and raw records, verified source hashes, metadata and 31 local links/fragments, and validated journals/diff. These checks do not establish live application delivery, long-term reliability, host enforcement or authenticity of recorded evidence.
- Details: Local verification evidence is under .agent-work/tasks/python-developer/instruction-review/, behavior-code/, behavior-boundaries/ and verification/ and is Git-ignored. The analyst must load its revised skill and delegation guidance; new developer assignments explicitly load the developer skill. Test agents read current instructions; no automatic adoption by already active agents is assumed.
