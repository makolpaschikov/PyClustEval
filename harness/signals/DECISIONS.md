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
