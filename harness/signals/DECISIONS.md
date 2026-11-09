# Harness decisions

Use stable decision IDs and link their signals. Record agreement separately
from implementation and verification. Preserve prior decisions; link any
later decision that supersedes them.

## DEC-001: Root project instructions and journal initialization

- Date: 2026-11-10.
- Signal: [SIG-001](SIGNALS.md#sig-001-root-project-instructions).
- Owner: harness maintainer.
- Resolution: introduce compact English root instructions, update the harness
  map, and initialize these two journals. Limit bootstrap work to the harness;
  keep application development, environment changes, and experiments deferred
  until explicit agreement changes that scope. Allow relevant in-project
  investigation without separate file-read permission.
- Shared rules: preserve scientific conditions and unrelated work, verify
  changed behavior, and distinguish evidence from assumptions and authority.
  Require human permission and a proposed title before commits by default;
  an applicable role skill may explicitly replace individual Git requirements.
  Keep `AGENTS.md` at most 32,000 UTF-8 bytes, with essential cross-session
  instructions and links to detailed procedures.
- Communication: adapt the human-supplied `CLAUDE.md` rules into English;
  omit the rejected passage about the agent's conversational persona. Use a
  dedicated questions subsection adapted without semantic loss from
  `F:/Python/UniversityResearch/AGENTS.md`, retaining optional sections,
  two to five options where applicable, justified recommendations, and
  localized Russian labels. Keep finding disposition as a general rule.
- Rationale and alternatives: compact shared rules avoid duplicating role
  procedures. The human chose harness-only bootstrap over autonomous
  application work or an improvised analyst workflow, and project/task access
  boundaries over the stricter skill-only file-reading boundary. Role-specific
  commit exceptions leave future role workflows configurable.
- Human agreement: in this chat on 2026-11-10, the human explicitly approved
  the complete four-file package with all discussed revisions. This agreement
  authorizes file changes, not a commit, push, or history rewrite.
- Affected files: [AGENTS.md](../../AGENTS.md), [harness map](../README.md),
  [signals](SIGNALS.md), and this decision journal. No application code,
  computational environment, role definitions, or skill files are changed.
- Implementation: all four agreed files have been created or updated and
  verified before the separately requested commit.
- Git follow-up: the human subsequently authorized a commit after checking
  the repository and branch. Git was paused in a reword rebase with HEAD and
  `experiments-series-runner` both at `34f03e0`. Exiting the rebase with
  `git rebase --quit` and switching to that branch restored attached HEAD
  without rewriting existing commits or discarding worktree changes.
- Proposal verification: an independent subagent exercised the proposed rules
  against eight scenarios covering bootstrap restrictions, project inspection,
  incomplete requirements, commit authorization and role overrides, existing
  permission, unsupported approval claims, and instructions in source material.
  Two ambiguities were clarified; a focused recheck of the affected scenarios
  found no remaining ambiguity.
- Final artifact verification: a separate independent subagent read the root
  instructions, harness map, journals, and existing maintainer skill. It
  exercised nine scenarios, including meaningful alternatives and open-ended
  naming questions in Russian, and found no actionable defects or semantic
  loss in the imported question rules. The excluded persona rule is absent.
  Maintainer checks confirmed strict UTF-8 decoding, working relative links
  and heading anchors, no trailing whitespace or conflict markers in all four
  files, and a passing `git diff --check`. The final root file is 7,374 bytes,
  below the 32,000-byte limit. The worktree contains only the four agreed
  file changes.
- Verification limits: behavioral checks exercised instructions through
  textual scenarios. No live application tasks, experiments, Git mutations,
  or automatic instruction-loading behavior were tested. The independent
  checker did not separately corroborate the human approval or earlier
  review history; those are recorded from this maintenance chat.
- Handoff: root instructions apply to the maintainer and future project roles.
  Pass the current file explicitly to already-active agents; editing it does
  not prove that their context has changed. Other roles and helpers remain
  planned, and journal entries do not launch agents.
