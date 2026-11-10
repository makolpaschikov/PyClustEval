# Shared branch and commit permissions

The maintainer and analyst skills explicitly adopt these permission rules in place
of the corresponding root commit-permission defaults. Each role defines its unit
of work and commit-message convention. All other root Git rules remain in force.

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
