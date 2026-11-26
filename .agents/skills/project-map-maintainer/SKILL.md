---
name: project-map-maintainer
description: Audit, create or update the English PyClustEval project map on direct request, or maintain affected entries and package READMEs for the analyst before task delivery.
---

# Project map maintainer

Help a reader find a project capability by name and reach the files that own it.
Maintain the root README, the root INDEX.md and the directory overviews described
below. Read the project's AGENTS.md and respect the user's requested scope.

## Direct requests

Let the request set the action and area. For an audit, inspect the documents,
follow their links and compare claims with the current repository. Return concrete
findings with document and source paths. Leave the files untouched. For a request
to write, translate or update, make and verify the requested edits. A request for
one document can be completed independently of a full map build. Preserve accurate
content and existing user changes. If evidence leaves a material question about
purpose or scope, ask the human before writing the disputed claim.

For standalone edits, use the maintainer's [shared Git workflow](../../../harness/git-workflow.md),
including its branch and commit permissions in place of the root defaults. The unit
of work is the agreed map request and its review fixes. Obtain the branch choice
before the first write, present the intended concise English imperative commit
title before committing, inspect the staged diff, and offer the applicable
delivery choices. Follow the shared PR approval and cleanup procedure.

## Analyst assignments

Work in the checkout and branch assigned by the analyst. Use the integrated
diff for the delivered unit, including old and new paths. Read relevant
definitions, callers, configuration or tests to establish what changed for a
reader. Inspect the root README and affected map entries, including references
from outside a changed directory. For moves and deletions, search map documents
for obsolete paths, names and descriptions.

Update affected entries and references. Create a README for a new first-party
package and make it discoverable from the index. Preserve documents that still
describe the current project accurately. Keep edits within the assigned map scope.
Return changed paths, the reason for each change, checks performed and any
unresolved question to the analyst. If the map is current, briefly explain why
the diff leaves it accurate. The analyst owns staging, commits, integration and
task state. Route questions about intent or permissions through the analyst.

## The three documents

Write all authored map text in English, including index keywords. Translate
search intents expressed in another language into natural English terms. If a
request requires a verbatim non-English search phrase, explain the conflict and
ask the requester which requirement takes priority before editing that entry.
Keep real filenames, paths and code identifiers exact. Use Markdown links
relative to the containing document.

- **Root README.md.** Help someone decide whether PyClustEval serves their needs
  and how to install and run it. Update affected capabilities, supported methods,
  requirements, commands or links when the integrated change alters what the
  reader needs to know. Keep internal implementation detail in directory READMEs.
- **Root INDEX.md.** Start with `# Project Index` and a short paragraph on its
  purpose, how to search it and how to keep it current. Give each main package,
  useful independent directory and important root file a product-language heading
  and a sentence explaining its purpose. Choose concrete English search terms,
  including common task phrases and code names when useful. Link a directory to
  its README and a root file directly to the file. Include routes to `tests/`,
  `tools/`, `configs/` and the existing harness overview. One harness entry leads
  readers to its own map.
- **Directory README.md.** Cover the first-party packages under `clustering_eval/`,
  the top-level package itself, and `tests/`, `tools/` and `configs/`.
  Give `clustering_eval/third_party/` one English overview of the included methods
  and where their adapters and existing documentation live. Preserve the nested
  third-party documents. The harness maintainer owns the existing harness overview
  and role instructions. Send any needed corrections there through the caller.

Use this index entry shape:

```markdown
## <Capability or reader-facing name>
<One sentence on what the reader will find.>

**Keywords:** <search term>; <task phrase>; <code name>

**Coordinates:** [<repository path>](<relative link>)
```

Use this shape for a directory overview. Keep the summary short. Mention a
neighboring responsibility when the distinction helps a reader choose a path.
Select the most useful files and entry points. Explain what to open each one for.

```markdown
# <Reader-facing name> (<package or directory name>)

## Summary

<What this directory owns.>

## References

- [<file>](<relative link>) — <what to look for here>.
```

## Verify the result

Inspect the final diff against the requested scope. Resolve the local links and
anchors you add or change, check the mapped names and descriptions against their
owning sources, and follow the route from the index to the intended directory
or file when that route changes. Report the checks you actually performed and
any remaining uncertainty. Map maintenance grants authority for documentation
only; code, experiments and the computational environment retain their owners.
