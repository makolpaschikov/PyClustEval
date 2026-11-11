# Shared branch and commit permissions

The maintainer and analyst skills explicitly adopt these permission rules in place
of the corresponding root commit-permission defaults. Each role defines its unit
of work and commit-message convention. The developer skill adopts the delegated
worktree section below, which also governs analyst allocation of that work.
All other root Git rules remain in force.

## Task branch and maintainer commits

Before the first file change for a unit of work, ask the human whether to use the
current branch, another existing branch or a new branch. This includes ignored
task files, journal records and temporary inputs. Read-only investigation may
precede the choice; keep pending records in chat until writing is allowed.
Reuse the choice for subsequent edits and resumption of the same unit and fixes.
For agent-origin work, obtain the choice and permission through the analyst.

For a new branch, agree on its base and name, using the project's `codex/` prefix
by default. Before creation, explicitly tell the human that commits for the agreed
work and its review fixes on that new branch will not need further confirmation.
Once base/name are agreed and the notice is given, create the branch and commit
within that scope without repeated approval. The notice needs no separate
acknowledgment. If that branch already exists, resolve it as an existing-branch
choice; a proposed name does not make an existing branch new.

On an existing branch, obtain explicit human permission before committing. When
multiple commits are expected, ask for permission covering the agreed work and
review fixes. Reuse that permission within scope and honor narrower limits. Branch
selection alone does not authorize commits.

Verify the checkout before writing or committing. If it differs, resolve the
branch choice; do not transfer permission to another branch. A new unit of work
requires a fresh branch choice and applicable permission. Approval of the actual
change/specification remains necessary even when commits are automatic.

Present the intended title before committing. Review the staged diff and include
only intended changes. Permission to commit does not authorize push, merge or
history rewriting. Preserve unrelated user work. Record the human decision's
scope and source when handing work between sessions; a record does not itself
establish authentic permission.

## Delegated developer worktrees

After the human has agreed the task and its primary branch, the analyst may
choose subordinate branch names, exact base commits and dedicated worktree paths
within that task without asking for each allocation. Use the `codex/` prefix and
record the assignment. This exception does not authorize another task, a new
primary delivery branch or reuse of a branch/worktree owned by someone else.
Inspect existing worktrees and ownership before allocation; do not reset an
existing branch or overwrite work to make an allocation succeed.

The analyst passes the developer the assigned worktree/branch, base commit,
permitted files, evidence paths and commit permission with its actual human
source and scope. Permission can cover the assigned work and its review fixes;
it must come from the task's human-approved commit authority and respect any
narrower limits. Creating a subordinate branch does not create that authority.
Missing authority goes back through the analyst; an assignment label or manifest
claim is not a substitute for the underlying decision.

The developer may stage and commit the assigned work in that worktree without
per-commit approval or advance title notification. This explicitly replaces the
root requirement to present a title beforehand for these developer commits only.
Use a concise English imperative title; add a body when the reason or material
consequences need explanation. No developer-specific prefix is required. Group
logically complete changes; make review corrections as new commits.

Before writing or committing, verify the repository root, worktree and current
branch against the assignment. A mismatch or detached HEAD requires resolution
with the analyst. Use the assigned worktree explicitly for commands. Inspect the
whole staged diff and index, not only a selected file diff, and commit only the
intended task changes. Leave unrelated work intact; if another change is already
staged, hold the commit and ask the analyst instead of including or unstaging it.
Never force-add ignored task/evidence files. Report any remaining uncommitted
changes and do not treat a clean worktree or a commit as proof of acceptance.

The analyst retains worktree/branch allocation and lifecycle, integration and
shared task state. The developer does not switch/create branches or worktrees,
integrate other branches, push, amend, rebase, reset or otherwise rewrite history
under this commit permission. Existing human limits still govern integration,
push and history changes; this procedure grants no additional authority for them.
Keep working copies and evidence available until the analyst has verified the
handoff and their disposition. Neither task completion nor a commit authorizes
discarding uncommitted work or deleting evidence.

Return the assigned branch/worktree, base and final commit IDs, created commits,
check evidence and remaining changes in the developer handoff. The analyst
handles the [artifact transfer and integration checks](../.agents/skills/analyst-orchestrator/references/task-artifacts.md#delegated-worktrees-and-evidence).
