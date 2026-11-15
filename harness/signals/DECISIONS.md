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
- Status: superseded
- Decision: Add an English python-developer project skill for bounded implementation assignments from the analyst. Include the interviewed code-quality, documentation, testing, dependency-escalation and delegation rules, entry checks, review-fix handling and an evidence-bearing handoff. The analyst starts an ordinary subagent with the skill and a self-contained authorized assignment; update analyst instructions, delegation guidance and the harness map to describe this invocation accurately. Keep task-state, Git coordination and completion decisions with the analyst and retain harness-only bootstrap.
- Why: Provide consistent implementation behavior under the existing analyst workflow, with minimal maintainable code and checks tied to actual task behavior.
- Agreement: The human approved the complete DEC-007 package in this chat on 2026-11-12 with Да after the final proposal covering the developer skill, analyst integration, interviewed requirements, evidence handoff and independent isolated verification. Earlier answers chose a new codex/python-developer branch from experiments-series-runner with scoped automatic commits announced before creation. Approval covers the agreed harness change and review fixes, not application execution.
- Result: Added .agents/skills/python-developer/SKILL.md with the agreed implementation, documentation, typing/error-handling, testing, autonomy and handoff rules. Updated analyst skill, delegation invocation contract and harness map. Developer work uses an ordinary analyst-assigned subagent explicitly reading the skill; Git, task state and completion remain with the analyst. Existing helpers and manifest formats are unchanged; no application or environment change was made.
- Check: Independent instruction review found no actionable issues. An independent developer completed a stdlib fixture fix, reproduced two zero-score failures before implementation, and passed all five summary tests; the six-test full fixture suite retained one intentionally unrelated legacy failure reproduced on the original and left unchanged. Five independent textual scenarios exercised direct invocation, dependency scope, missing bootstrap authority, disputed/supported review findings and failed acceptance alongside an unrelated failure. Maintainer inspected actual fixture changes and raw records, verified source hashes, metadata and 31 local links/fragments, and validated journals/diff. These checks do not establish live application delivery, long-term reliability, host enforcement or authenticity of recorded evidence.
- Details: Local verification evidence is under .agent-work/tasks/python-developer/instruction-review/, behavior-code/, behavior-boundaries/ and verification/ and is Git-ignored. The analyst must load its revised skill and delegation guidance; new developer assignments explicitly load the developer skill. Test agents read current instructions; no automatic adoption by already active agents is assumed.

<a id="dec-008"></a>
## DEC-008: Developer commits in analyst-allocated worktrees

- Date: 2026-11-12
- Signal: [SIG-006](SIGNALS.md#sig-006)
- Status: verified
- Decision: Retain DEC-007 developer behavior except Git ownership. Within an already agreed task, let the analyst choose and record subordinate branch names, base commits and dedicated worktree paths and pass scoped commit authority to the assigned developer. Permit developer staging and logically focused commits only in that assigned worktree/branch, including review fixes, without per-commit approval or advance title notification. Use concise English imperative titles and optional explanatory bodies; return base/head, commit hashes, check evidence and remaining changes in the handoff. Analyst retains workspace allocation, integration and shared state. Preserve existing authority limits for push, history rewriting and integration.
- Why: The separate Git interview established that developers should own commits in isolated working copies while the analyst coordinates branches and integration. Advance title notification adds no decision when task-scoped commits are already authorized.
- Agreement: The human explicitly approved the final DEC-008 Git workflow in this chat on 2026-11-12 with да, including removal of advance commit-title messages, analyst-allocated subordinate branches/worktrees, task-scoped developer commits and review fixes, optional commit bodies, analyst integration and verification on isolated Git fixtures. This is a review correction to the same developer-role work on codex/python-developer, retaining its scoped automatic maintainer-commit permission.
- Result: Updated developer and analyst skills, shared Git procedure, delegation and artifact references, harness map and journals. Developers now stage and commit assigned work in analyst-allocated isolated worktrees under task-scoped human authority, without per-commit approval or advance title messages. Review fixes use new commits; analyst allocation, integration and shared state remain intact. Documented canonical evidence transfer and manifest-free worker fingerprints using the existing helper module; helper code and schema are unchanged.
- Check: Independent instruction review found no actionable defects. An independent developer held a commit for an unrelated staged file, then created two real fixture commits for implementation and a simulated analyst-approved review correction without rewriting history or touching the unrelated note. Four affected tests passed at both revisions. Maintainer verified the append-only graph and preserved evidence, copied 11 reports with matching hashes, fast-forwarded only the isolated coordinator fixture and executed four passing integrated tests. Independent contract fixtures verified one canonical manifest, worker-branch and corrupt/stale-evidence rejection, and an intentionally failing combined result remaining blocked; four textual authority/review scenarios matched the agreed rules. Finding C-01 about manifest-free fingerprints was resolved by documentation and independent execution of the exact snippet. Metadata, 41 local links/fragments and journal/diff checks passed. No live application delivery, full epic lifecycle, concurrent-writer safety, host enforcement or authenticity of synthetic gate approvals/reviews is claimed.
- Supersedes: [DEC-007](DECISIONS.md#dec-007)
- Details: Evidence is Git-ignored under .agent-work/tasks/python-developer/git-revision/: instruction-review/, execution/, contract-check/, integration-result.json and assessment.md. Existing analysts/developers need the revised role, Git and artifact instructions; test agents reread them. One independent fixture setup failed on newline handling before gate checks; the checker corrected only its owned fixture and retained both traces. DEC-008 preserves DEC-007 outside the revised Git boundary.

<a id="dec-009"></a>
## DEC-009: Python reviewer skill and analyst integration

- Date: 2026-11-13
- Signal: [SIG-007](SIGNALS.md#sig-007)
- Status: verified
- Decision: Add a python-reviewer project skill invoked by analyst-assigned independent subagents; update analyst instructions, delegation guidance and harness availability. Review actual source/specification versions, correctness, affected mathematics/algorithms, maintainability and verification evidence; allow assigned isolated reproductions without changing reviewed source. Report concrete blocking findings, narrowly filtered optional recommendations and incomplete verification distinctly. Optional recommendations must identify current in-scope evidence and practical benefit from reduced duplication/change points, simpler unnecessary mechanisms, clearer ambiguous interfaces/contracts, better error diagnostics, meaningful test coverage, or demonstrated wasted computation/resources, with proportionate cost and without treating defects or mandatory requirements as optional. Analyst retains shared state, coordination and acceptance. No new helper, schema, host model configuration or mathematics specialist is included.
- Why: Replace the brief reviewer fallback contract with interviewed review behavior and evidence-bearing handoffs while controlling speculative recommendations, false acceptance and unapproved fixes.
- Agreement: The human explicitly accepted the complete proposed package and six concrete optional-recommendation criteria with Да, согласен in this chat on 2026-11-13. Earlier interview answers and the chosen codex/python-reviewer branch from experiments-series-runner remain in force, with scoped automatic maintainer commits announced before creation. Approval covers reviewer instructions, analyst integration, map/journal updates and independent isolated verification, not application execution or the deferred mathematics specialist.
- Result: Created .agents/skills/python-reviewer/SKILL.md with the agreed review scope, six optional-recommendation criteria, isolated reproductions, version-bound evidence, distinct accepted/changes_requested/incomplete reports and correction handoffs. Updated analyst skill, delegation invocation and harness map. Existing helpers, manifest schema, developer instructions, model configuration and application/environment are unchanged.
- Check: Independent instruction and final-map reviews found no defects. Six independent textual scenarios exercised recommendation filtering, missing/stale evidence, scientific uncertainty, withdrawal of an unsupported finding and reviewer independence. On a real stdlib fixture, the reviewer found a normalization defect despite four passing developer tests: three of six independent checks failed before correction, then all six passed after a separate fixture fix and R1 was resolved. Source snapshots stayed unchanged during reviews and 18 original evidence artifacts were preserved. Maintainer inspected raw code/results and preservation records. Stdlib metadata, 65 local links/fragments, journal and diff checks passed. The stock skill validator could not start without PyYAML; no packages were installed. Live application delivery, full epic lifecycle, host loader/enforcement and general mathematical reliability are not established.
- Details: Git-ignored evidence is under .agent-work/tasks/python-reviewer/: assessment.md, instruction-review/, behavior/, execution/ and verification/. The fixture builder initially hashed LF text before Windows wrote CRLF; reviewer detected the mismatch, the normalization explanation was independently checked and saved separately, and original logs were retained. Analysts must load the revised analyst/delegation instructions; new reviewers explicitly load their skill. Test agents loaded them; automatic adoption by existing agents is not assumed.

<a id="dec-010"></a>
## DEC-010: Four specialist skills and selectable model profiles

- Date: 2026-11-13
- Signal: [SIG-008](SIGNALS.md#sig-008)
- Status: verified
- Decision: Add code-scout, internet-scout, specification-validator and specification-auditor skills, one shared model-profile reference, explicit caller integration and isolated independent verification. Scouts collect evidence without proposing solutions; causal code diagnoses remain labeled judgments/hypotheses. Validator checks readiness and technical constraints; auditor checks request/fact alignment and disproportionate scope/complexity. Both may suggest local wording but return semantic/architectural changes to the analyst. Preserve existing task-state ownership, review independence and bootstrap boundaries.
- Why: Complete the four remaining planned evidence-gathering and specification-review roles with interviewed responsibilities and explicit selectable model/effort sets.
- Agreement: On 2026-11-13 the human approved the complete linked proposal and exact model identifiers in this maintenance chat with: Да, согласен. Реализуй весь пакет. Approval includes four specialist skills, shared selectable model profiles, caller/map integration and independent isolated verification. Earlier interview answers define each role and allow all listed model/effort combinations, chosen by the caller for scouts and the analyst for specification roles. The agreed codex/harness-subagents branch from experiments-series-runner retains announced scoped automatic commits for this package and review fixes. Harness-only bootstrap remains in force.
- Result: Added four English specialist skills and harness/subagent-profiles.md with the approved exact model/effort sets. Updated analyst entry and delegation contracts, maintainer scout invocation and harness availability. Scouts provide evidence without solution proposals; specification roles preserve independent readiness/alignment review and existing manifest ownership. The code-scout causal-label issue found in verification was corrected and rechecked by a fresh worker. No application code, dependency, helper schema/script or native host configuration changed.
- Check: Independent role assignments exercised code tracing/probe and read-only follow-up, live versioned Python documentation and fictional scientific-source limits, two readiness cases and three alignment cases. Successful launches requested Terra/high, Sol/medium, Sol/high and Astra/high; effective runtime metadata and every allowed combination were not verified. A fresh Terra/high worker passed the affected code-scout recheck. Independent package review and six textual coordination scenarios found no remaining issues. Stdlib metadata checks covered six skills and 85 local links across nine files; journal and whitespace checks passed. Stock quick_validate.py could not run because PyYAML is unavailable; no dependency was installed. Evidence is in .agent-work/tasks/harness-subagents/verification.md and reports/. No live application delivery or real experiment was tested.
- Details: Proposed identifiers are gpt-6.1-terra, gpt-6.1-sol and gpt-6-astra. Caller selects and records a permitted pair with a brief complexity rationale; no fixed pairing, silent inheritance or unapproved model substitution. Use self-contained assignments, ordinary subagents and existing manifest formats; no native host configuration or new scripts are planned. Prepare four skills, harness/subagent-profiles.md, analyst/delegation and maintainer invocation updates, map and journals. Model performance comparisons and the mathematics specialist are outside this package.

<a id="dec-011"></a>
## DEC-011: Mathematics reviewer and mandatory review gates

- Date: 2026-11-13
- Signal: [SIG-009](SIGNALS.md#sig-009)
- Status: verified
- Decision: Add an analyst-assigned mathematics-reviewer skill using gpt-6-astra/high or xhigh and transfer independent mathematical correctness from Python reviewer. Require distinct specification and implementation reviewers for substantive mathematical changes; allow bounded isolated probes and correction proposals, with missing-source research routed through analyst/internet-scout. Extend task.py with manifest v2 mathematical-impact assessment, independent current review evidence and start/completion/resumption checks; retain Markdown v1 and add explicit preservation-first migration of selected legacy tasks.
- Why: Provide the requested mathematical specialist and enforce its mandatory review stages in the existing task workflow, while preserving source evidence, scientific decisions and reviewer independence.
- Agreement: The human explicitly approved the complete DEC-011 package with да in this chat after the linked proposal and six-point summary, including the new role, distinct stage reviewers, Astra high/xhigh, bounded probes, source routing, mathematical ownership, manifest v2 gates, explicit migration and independent isolated verification. Interview decisions and the selected codex/mathematics-reviewer branch with announced scoped automatic commits remain in force.
- Result: Added mathematics-reviewer with fixed Astra and caller-selected high/xhigh, separate independent formulation/implementation stages, bounded probes, source routing and correction authorship. Updated analyst, Python reviewer, validator, maintainer, profiles, map and artifact guidance. Task JSON v2 keeps Markdown v1, adds mandatory mathematical records/gates and explicit preservation-first v1 migration. Mathematical scope hashes prevent stale dependency/child evidence reuse; no application, environment or real task migration occurred.
- Check: Final full harness suite: 101 tests passed (50 focused mathematical/migration cases). Independent package review reproduced PR-001 (stale enclosing mathematical reports); the correction passed seven independent scenarios with no remaining findings. Three distinct Astra agents exercised formulation defects/validity, missing/conflicting definitions, faulty implementation despite passing developer tests, own-correction independence refusal and acceptance of a corrected fixture with real v2 bindings. Raw reports/hashes were inspected and preserved. Stdlib metadata/links passed; stock validator could not import PyYAML, no package installed. Live application delivery, general mathematical reliability, actor/approval authenticity and all model capabilities are not established. Evidence: .agent-work/tasks/harness-mathematics-reviewer/verification.md.
- Details: Proposal covers the new skill, analyst/delegation/artifact integration, Python reviewer and validator responsibility routing, profiles/map, task helper/schema/migration and isolated verification. It changes the mathematical ownership defined in DEC-009 going forward while retaining other reviewer duties and the historical record; it extends DEC-010 profiles. No application/environment changes or experiments; do not mass-migrate unrelated task artifacts.

<a id="dec-012"></a>
## DEC-012: Close three mechanical task-check gaps

- Date: 2026-11-15
- Signal: [SIG-010](SIGNALS.md#sig-010)
- Status: verified
- Decision: Apply ancestor blocking findings independently of mathematical classification; exclude included child contributors from independent epic Python review; reject malformed item kinds with normal format diagnostics. Use three separate Terra/Sol high workers, focused regressions and independent integrated review, preserving existing schema, approval and mathematical contracts.
- Why: The existing gates can permit child work despite a shared-contract blocker or accept review of an author's integrated contribution; malformed kinds produce an avoidable traceback.
- Agreement: The human authorized concrete fix choices and separate workers, then confirmed the workflow and codex/harness-gate-fixes from experiments-series-runner on 2026-11-15, with no further commit-title approval. The local plan is .agent-work/tasks/harness-gate-fixes/plan.md; no application, environment or general automation changes are authorized.
- Result: Fixed ancestor-blocker enforcement independently of mathematical classification, included child contributors in epic Python-review exclusions, and diagnosed malformed item kinds before dictionary lookup. Added three focused regression files and clarified the analyst artifact contract. Three separate workers used requested Terra/high, Terra/high and Sol/high profiles; the maintainer integrated their isolated changes on codex/harness-gate-fixes. No schema, application, environment or general automation changes.
- Check: Baseline: 101 tests passed. Each defect reproduced against base code; final integrated suite passed 114 tests, including 13 new methods. A separate independent reviewer accepted the combined change after 58 original CLI probes, with no fixture mutations or remaining findings. Six integrated input hashes and 13 evidence transfers were verified; simple metadata/local-file checks passed for 9 skills and 148 links. Evidence: .agent-work/tasks/harness-gate-fixes/verification.md. Checks use isolated harness fixtures, not live application delivery or actor/approval authentication.
- Details: Analysts need the updated task helper and artifact reference; maintainers need the corrected gate contract. Finished workers' detached worktrees and original logs are retained as evidence. Existing v1 migration policy and unrelated deferred harness proposals remain unchanged.

<a id="dec-013"></a>
## DEC-013: Automate task evidence and lifecycle mechanics

- Date: 2026-11-15
- Signal: [SIG-011](SIGNALS.md#sig-011)
- Status: verified
- Decision: Add four task-helper mechanisms for snapshots/context, explicit check execution, immutable evidence packaging/import, and guarded state transitions. Preserve task JSON v2, Markdown v1, analyst-only canonical state, original evidence bindings, existing gates and human/scientific authority. Use separate Sol/high and Terra/high workers, independent verification and isolated fixtures.
- Why: Reduce repeated manual hashing, metadata transcription, evidence transfer and state edits without converting stale or incomplete evidence into acceptance.
- Agreement: The human approved the complete four-part proposal and new codex/harness-task-automation from experiments-series-runner on 2026-11-15. The implementation contract is .agent-work/tasks/harness-task-automation/plan.md; routine implementation choices remain within that approved behavior.
- Result: Added read-only snapshot/context/math-scope CLI, bounded explicit check execution, validated ZIP evidence packaging/inspection/import/adoption, and guarded checkpoint/completion with preserved state history. Updated analyst/delegation/artifact documentation and harness availability. Separate Sol/high and Terra/high workers implemented the four mechanisms; task JSON v2 and Markdown v1 remain unchanged. No application, environment or global agent configuration changes.
- Check: Final integrated suite passed 160 tests on Python 3.14 (exit 0); two end-to-end lifecycle tests and independent CLI/failure probes covered cross-checkout transfer, stale/corrupt/failed evidence, missing reviews, partial outcomes and state integrity. Independent review accepted after four supported P2 fixes and correction checks; four instruction-use scenarios passed. Metadata/local links passed for 9 skills and 156 targets. The initial full run's Windows fixture rename failure was corrected and retained separately. Evidence: .agent-work/tasks/harness-task-automation/verification.md. Runtime 3.10, arbitrary external writers/power loss and live application delivery are not established.
- Details: Analysts adopt current helper and automation/artifact references; workers receive context/check/report operations through current delegation instructions. Output/process limits and actual partial-result reporting are documented. Original worker evidence and independent reproductions remain preserved; no approval or stale report was silently rebound.
