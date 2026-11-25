# Git workflow for maintainers and analysts

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
For human-led review of agent-origin signals, obtain the choice and permission
directly from the human or through an analyst relaying the actual human decision.
For other agent-origin work, obtain the choice and permission through the analyst.

For a new branch, agree on its base and name, using the project's `codex/` prefix
by default. Before creation, explicitly tell the human that commits for the agreed
work and its review fixes on that new branch will not need further confirmation.
Once base/name are agreed and the notice is given, create the branch and commit
within that scope without repeated approval. The notice needs no separate
acknowledgment. If that branch already exists, resolve it as an existing-branch
choice; a proposed name does not make an existing branch new.

On an existing working branch, obtain explicit human permission for direct
commits there. When multiple commits are expected, ask for permission covering
the agreed work and review fixes. Reuse it within scope and honor narrower limits. Branch
selection alone does not authorize direct commits there.

Verify the checkout before writing or committing against the working branch
or the task-local assignment below. Resolve a mismatch first. A new unit of work
requires a fresh branch choice and applicable permission. Approval of the actual
change/specification remains necessary even when commits are automatic.

Present the intended title before committing. Review the staged diff and include
only intended changes. Preserve unrelated user work. Record the human decision's
scope and source when handing work between sessions; a record does not itself
establish authentic permission.

## Task-local branches

Once the human agrees the task and its working branch, the maintainer or analyst
may create local branches from it, commit the agreed work and review fixes there,
and merge them back into the working branch without another confirmation.
This includes a merge commit when the branches have diverged. Honor any narrower
human limits. Keep the working branch and, if newly created, its original base
in the handoff so the next session can distinguish these two merge destinations.

Use the project branch prefix and check existing branches and worktrees before
allocation. The coordinator may do the work or assign a branch and dedicated
worktree to an implementation worker. Give the worker the branch, base, permitted
changes and scoped commit authority from the agreed task. The coordinator owns
integration. Apply the delegated developer checks below for Python development.
Before integrating, inspect the delivered commits and any uncommitted work
and complete the applicable review. After merging, check the combined result.
Leave other people's work and task evidence intact. Merging the working branch into its
original base is a delivery choice for the human.

## Delivery at completion

After local integration and verification, offer the applicable choices using
actual branch names. With an existing working branch, offer to keep the result
local, push that branch to `origin`, or open a PR from it into a named target.
For a new working branch `B` based on `A`, also offer to merge `B` into local
`A`, merge and push `A`, or merge and open a PR from `A` into the chosen target.
Pushing `B` alone and opening a direct PR from `B` are separate choices.

Carry out the selected operations in order. If the human has already selected a
route and its branches, reuse that choice. Without a choice, leave the result on
the working branch. Before publishing, inspect what the selected branch will
send to the named remote branch. Surface unexpected commits or a material change
in scope for a decision. Push only the selected source branch to `origin` with
an ordinary push. If a step fails, report what succeeded and resume from there
after resolving the cause. These choices do not authorize a force-push, history
rewrite, publication of another branch, or merging the hosted PR.

### Pull request preview

Establish the source branch, the intended repository and its target branch.
Use the actual comparison against the hosted target to draft the PR. For a
local `B` into `A` merge followed by a PR from `A` into `main`, perform the
selected local merge, then describe the full `A` to `main` comparison, including
relevant changes that were already in `A`. If the intended target exists only
locally, ask how the human wants to proceed before publishing any extra branch.

- Give the PR a one-line title naming the concrete change.
- Usually one short paragraph suffices. Lead with what changes for the reader.
  Explain the reason when it adds context. Use bullets for independent changes.
- Tie claims to the diff or observed results. Mention relevant checks actually
  run and material limits. Omit stock introductions, unsupported benefits,
  commit-by-commit narration and repetition of the title.

Show the exact source and target, title and complete body before publication.
When the necessary details are known, include this preview with the delivery
choice. Incorporate requested edits. The human's confirmation of the preview
authorizes the necessary source-branch push and creation of the PR with that
text. If the branches, material diff or proposed text change, show the revised
preview for approval. On success, return the PR link. On retry, check for an
existing matching PR before creating one.

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
the agreed task and working branch supply the task-local authority described
above, subject to any narrower human limits.
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

For delegated developer work, the analyst supplies the canonical
[assignment and SHA-256](quality-checks.md#assigned-developer-git-checks).
Before each commit the developer runs the `staged` check for that assignment and
inspects the complete staged diff. Resolve a failed or unavailable check through
the analyst; do not substitute a fresh assignment hash or remove unrelated staged
work. Repeat after changes to checked inputs. The optional hook can invoke this
check, but its absence does not remove the developer's explicit obligation.

The analyst retains worktree/branch allocation and lifecycle, integration and
shared task state. The developer does not switch/create branches or worktrees,
integrate other branches, push, amend, rebase, reset or otherwise rewrite history
under this commit permission. The coordinator handles the delivery choice.
Keep working copies and evidence available until the analyst has verified the
handoff and their disposition. Neither task completion nor a commit authorizes
discarding uncommitted work or deleting evidence.

Return the assigned branch/worktree, base and final commit IDs, created commits,
check evidence and remaining changes in the developer handoff. The analyst
handles the [artifact transfer and integration checks](../.agents/skills/analyst-orchestrator/references/task-artifacts.md#delegated-worktrees-and-evidence).
It runs the [commit-series handoff check](quality-checks.md#analyst-handoff-checks)
against the exact delivered HEAD before accepting the series. This checks all
intermediate commits and does not grant integration or completion authority.
