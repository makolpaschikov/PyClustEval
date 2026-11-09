# Signal and decision journals

Use [journal.py](../scripts/journal.py) for all agent changes to
[SIGNALS.md](SIGNALS.md) and [DECISIONS.md](DECISIONS.md). The Markdown files
are the source of record; JSON files are temporary command inputs, not a
second database. Humans may edit the journals directly. Agents must run
`check` before further work and may not bypass the helper when it fails.

Register a signal once a concrete harness problem or improvement can be
identified, before deciding whether to implement it. Add clarifications to
the existing signal and link duplicates. Informational questions do not need
records. The analyst owns agent-origin registration; until implemented,
follow the human-led route in the [harness map](../README.md).

## Runtime and commands

The helper requires Python 3.10+ and only its standard library. Use an
available interpreter; do not install packages or alter the application
environment for this helper. These commands were checked with Python 3.14
through the Windows launcher. In PowerShell, run from the repository root:

```powershell
py -3.14 -B harness/scripts/journal.py check
py -3.14 -B harness/scripts/journal.py create signal --input signal.json
py -3.14 -B harness/scripts/journal.py create decision --input decision.json
py -3.14 -B harness/scripts/journal.py update SIG-003 --input patch.json --expect-sha256 <hash-from-check>
```

Replace `<hash-from-check>` with the actual SHA-256 of the target journal
printed by `check` (a signal uses `SIGNALS.md`; a decision uses `DECISIONS.md`).
On a stale hash, reread the affected record and reconcile the patch rather
than simply substituting a new hash. A successful mutation validates both
journals; `check` performs no writes. Errors exit with code 1 and a diagnostic.

`--journal-dir PATH`, before the command name, selects a different pair of
journals for isolated fixtures. Production commands default to this directory,
independent of the current working directory. Writes do not commit or push.

## Fields and compactness

Each record has a stable ID and title in its heading. Links use the explicit
stable anchors `#sig-001` and `#dec-001`, so renaming a title does not break them.
IDs are allocated under the writer lock and cannot be supplied to `create`.

| Kind | Required fields (JSON keys) | Optional fields |
| --- | --- | --- |
| Signal | `title`, `date`, `origin`, `owner`, `request`, `evidence`, `status`, `decisions` | `agreement`, `duplicate_of`, `details` |
| Decision | `title`, `date`, `signals`, `status`, `decision`, `why`, `agreement`, `result`, `check` | `supersedes`, `details` |

Reference fields (`signals`, `decisions`, `duplicate_of`, `supersedes`) are
arrays of IDs; the helper renders their Markdown links. All other input fields
are nonempty prose strings. Multiline prose is collapsed to single spaces;
code blocks and paragraph layout do not belong in these records. Unknown
fields, duplicate JSON keys, invalid dates/statuses, and broken references fail.
JSON must use UTF-8; a BOM is accepted.

On creation, `date` defaults to the runtime's local date (supply it explicitly
if the task date differs); status defaults to `open` or `proposed`. Signal
`decisions` defaults to `[]`. Decision `agreement`, `result`, and `check`
default to `pending`. A decision must name at least one existing signal.

Aim for about 10–15 lines per ordinary decision. Keep `decision` and `why`
short. In `agreement`, identify the actual
human decision and its scope. `result` identifies the change or affected files;
`check` states the useful outcome and remaining limitation. Do not repeat
instructions, complete review transcripts, or routine work chronology.
Use `details` only for facts that materially affect later decisions.
There is no arbitrary length cap that would force loss of necessary evidence.

Example signal input:

```json
{
  "title": "Focused reading",
  "date": "2026-11-10",
  "origin": "Human proposal in the maintenance chat",
  "owner": "harness-maintainer",
  "request": "Prefer relevant excerpts when reading large files",
  "evidence": "Preventive proposal; no specific failure reproduced"
}
```

Example decision input (use the actual signal ID returned by `create`):

```json
{
  "title": "Focused reading rule",
  "signals": ["SIG-002"],
  "decision": "Add context-aware reading guidance to AGENTS.md",
  "why": "Reduce irrelevant context without omitting dependencies"
}
```

`update` is a sparse patch: omitted fields remain unchanged. Optional fields
may be removed with `null`; required fields may not. A no-op leaves files
unchanged. Records contain current state and useful evidence only: updates
do not append timestamps, actors, status-transition events, or copies of earlier
values. There are no `--actor` or `--reason` command arguments. If an unusual
event matters to future work, state it briefly in the appropriate field or
`details`; do not maintain a routine change log. IDs and creation dates are
immutable. Substantive revisions remain linked through separate decisions.

## States and agreement boundaries

Signal statuses: `open`, `investigating`, `awaiting_agreement`, `in_progress`,
`resolved`, `deferred`, `rejected`, `duplicate`.

Decision statuses: `proposed`, `agreed`, `implemented`, `verified`, `deferred`,
`rejected`, `superseded`.

- Registration and investigation do not authorize implementation.
- `agreed` requires human-agreement evidence; rejection and deferment also
  record the relevant human decision. `implemented` requires a result;
  `verified` also requires checking evidence and limits. Recognized placeholder
  values such as `pending` do not satisfy those gates.
- The helper checks structure and evidence presence, not truth or authority.
  The agent must trace approval to the human and apply the maintainer workflow.
- Signal links are explicit. Creating a decision does not modify its signal;
  update the signal's `decisions` list through the helper. Every listed decision
  must refer back to the signal. A signal cannot become `resolved` while linked
  active decisions are unfinished, or without a verified decision.
- A duplicate signal names exactly one existing original in `duplicate_of`.
  Reference cycles and self-links are invalid.
- After a decision is agreed, implemented, verified, rejected, or superseded,
  its signal links, substance, rationale, approval, and replacement links are
  locked. Corrections to its outcome/check can still be recorded. A substantive
  revision uses a new decision with `supersedes: ["DEC-..."]` and new agreement.
  A resolved signal must be reopened before adding an unfinished decision.
  Mark the old decision `superseded` after its replacement is agreed. Later
  replacements may form a chain; old decisions remain readable.

## Migration

`migrate` accepts an explicitly reviewed JSON plan with `expected_sha256`
(keys `SIGNALS.md` and `DECISIONS.md`) and `signals`/`decisions` arrays using
the fields above plus each original `id`. It preserves all existing IDs and
their order. The operation refuses stale source hashes and already migrated
journals. It cannot replace records in already versioned journals.

```powershell
py -3.14 -B harness/scripts/journal.py migrate --input migration.json
```

Review the plan against the legacy records before running it. The helper
cannot judge whether a prose summary retained all important meaning.
It preserves the reviewed current fields without creating automatic history.
Remove temporary input files after use.

For version 1 journals that already use the structured format, remove only
their automatic `History` blocks with:

```powershell
py -3.14 -B harness/scripts/journal.py migrate --remove-history
```

This upgrades the format marker to version 2 and preserves all current fields,
IDs, status values, approval evidence, outcomes, and decision links. Review
the old events first and retain any otherwise missing material fact in a
current field. Repeating the command on version 2 is a no-op; normal commands
reject version 1 until upgraded. A partially upgraded pair is supported.

## Writes, failures, and checks

The helper uses a shared writer lock, expected hashes for updates, a final
snapshot comparison, and an atomic replacement of each changed file. It
validates the entire proposed state before writing. Ordinary migration write
errors attempt rollback of earlier file replacements.

Do not edit concurrently with a helper command. External editors do not honor
its lock; an edit after the final comparison cannot be reliably detected.
Two-file migration is not crash-atomic. A process termination or failed rollback
may leave a lock or mixed formats. Stop and report the state to the maintainer;
do not remove locks or manually rewrite journals as an automatic fallback.
These are local file safeguards, not a transactional database or an audit-proof
record of human consent.

Run the fixture suite without touching the application or real journals:

```powershell
py -3.14 -B -m unittest discover -s harness/tests -p test_journal.py -v
```

The tests cover current-state updates without event history, preservation of
fields during upgrades, lifecycle and supersession, stale/conflicting writes,
evidence gates, format drift, migration, and injected write failures. They do not model
power loss or establish the truth of a record's evidence.
