# Task automation

These commands automate mechanical parts of the existing artifact contract. The
analyst retains canonical state, permission checks, review acceptance and integration.
Workers may capture context, run explicitly assigned checks and package reports in
their authorized ignored directories. They cannot adopt evidence or change task state.
The commands do not lift bootstrap, approve work, authenticate an actor or assess
whether passing tests establish the requested behavior.

## Snapshots and review context

`source-snapshot` works without a task manifest. It preserves existing source-digest
semantics and reports checkout provenance. `context` additionally binds a selected
canonical task/item to a source checkout; `math-scope` exposes the applicable stage's
included contracts and hash. An explicit source repository may be a worker worktree
whose branch differs from the task's primary branch. The canonical task remains on
its recorded branch. Ignored datasets and external environments remain outside source
fingerprints and need explicit scientific/version evidence where relevant.

Capture `context` before a check/review. For mathematics select the correct
specification/implementation stage. Supply actual scoped documents and sources to
the reviewer; the context is an input identity, not a substitute for that material.
Keep the original context until after the check/review. Do not generate a new
"before" context to make an old report appear current.

## Explicit check execution

`run-check` takes the canonical task, item and planned check ID, explicit source
checkout, a new ignored output path, a positive timeout and the command's argv.
It does not infer or execute commands stored in a manifest. The assignment must
already authorize the command, resources and side effects. Interactive input and
background services are outside this bounded execution workflow.

Each attempt retains raw output, invocation metadata, its actual exit and before/
after context. Only an ordinary exit 0 with stable applicable inputs is a successful
attempt. Failed launches, nonzero exits, timeouts, interruption and drift stay explicit.
The runner does not modify canonical task state. Inspect its report and termination
limitations; a wrapper is not a sandbox or rollback of command side effects.

## Evidence packages and adoption

An evidence bundle is a versioned ZIP containing `bundle.json` and raw payloads.
Its metadata preserves the original contexts and explicit check/review record.
The SHA stored in task.json covers the complete archive, including logs/report
bytes. Original raw outputs remain useful for inspection. `inspect-evidence`
validates a package and exposes its metadata/payload inventory without extracting it.
Its optional `--text-payload` returns one selected UTF-8 report/log as JSON text;
missing or binary payloads are refused. It never extracts files or changes the archive.

`package-review` takes the original captured context, raw report and explicit
review descriptor. The reviewer identity, verdict and assessment kind come from
the actual review, never inferred from prose. Packaging captures the after-context.
An incomplete assessment can be packaged for handoff but cannot be adopted as an
accepted v2 review. Missing inputs or scientific uncertainty remain blocking as
required by the role; packaging does not resolve findings.

The analyst inspects raw evidence, input applicability, actor independence and
authority before invoking `import-evidence`. Archive-only import copies verified
bytes while retaining original bindings. Explicit adoption additionally requires
the current expected manifest hash and compatible task/item, specification/source/
mathematical scope and role fields. Corrupt or inconsistent packages are refused.
Identical existing imports may be reused; differing files are never overwritten.

Adoption preserves previous reports/state and replaces only the selected current
check or review record. Register a new failed current attempt honestly; do not retain
the earlier success as if it represented the new execution. Review `changes_requested`
may replace an earlier accepted record; `incomplete` remains archived with outstanding
findings/handoff. All required acceptance/review gates still apply after registration.

A source/specification mismatch cannot be fixed by copying files or refreshing a
hash. Archive the old result and either rerun affected checks or retain a separately
reasoned reassessment with the required independent review under the existing
artifact policy. No automatic reassessment or human approval rebinding is performed.

## State operations

`checkpoint` preserves status and stores a current checkpoint only after the
existing resumption evidence/state checks pass on the candidate. Replacing a
differing saved checkpoint requires an explicit reconciliation reason. Inspect
actual branch/source/context changes and resolve stale evidence first; the reason
is a recorded explanation, not a way to bypass verification.

`complete` runs the existing completion gate and validates the resulting done state,
then records completion receipt, status and checkpoint in one manifest update.
Missing independent review, unresolved blockers, failed checks, stale inputs and
incomplete children still prevent completion.

Both operations use the expected manifest SHA, selected branch/ignored workspace,
a cooperating writer lock, validated candidate and rechecks of source/documents/
referenced evidence. Exact prior manifests and operation records are retained under
`.state-history/`. No-op/retry results are explicit. Import adoption uses the same
state writer. Direct edits remain appropriate for substantive specifications,
permissions, contributor identities and finding dispositions, followed by lint.

Only the single manifest replacement is atomic. A crash may leave a lock or
unreferenced output/history; inspect the state instead of deleting locks, overriding
hash conflicts or fabricating success. External editors do not honor the helper lock.
Do not write task state concurrently or assume these safeguards authenticate consent.

## Command reference and operational limits

Run the task helper with `--repo` naming the canonical task repository (or the
selected source repository for a manifest-free snapshot). Arguments below follow
the command name. The normal `lint` output supplies the expected manifest SHA.

| Command | Inputs |
| --- | --- |
| `source-snapshot` | No task directory or item is needed. |
| `context` | Task directory, `--id`; optional `--source-repo` and `--stage`. |
| `math-scope` | Task directory, `--id`, `--stage specification` or `implementation`. |
| `run-check` | Task directory, `--id`, `--check-id`, `--source-repo`, `--output`, `--timeout`, then `--` and explicit argv. |
| `package-review` | Task directory, `--id`, `--kind`, `--before`, `--descriptor`, `--report`, `--output`; optional `--source-repo`. |
| `inspect-evidence` | `--bundle`; optional `--text-payload` for one UTF-8 payload. |
| `import-evidence` | Task directory, `--bundle`; adoption additionally needs `--adopt --expect-sha256`. |
| `checkpoint` | Task directory, `--id`, `--expect-sha256`; `--reason` when reconciling a differing checkpoint. |
| `complete` | Task directory, `--id`, `--expect-sha256`. |

The review descriptor supplies `reviewer` and `verdict`; `spec_review` also supplies
assessment `kind` (readiness/alignment/combined). Package kinds are `spec_review`,
`code_review`, `math_specification` and `math_implementation`. Before-context stage
is null for ordinary review and the corresponding stage for mathematical review.
Keep source and destination paths explicit and authorized, including cross-worktree
reads. Output parents must exist and output names must be new.

ZIP limits are 16 payloads, 8 MiB per payload, 17 MiB total uncompressed content
including metadata, and 20 MiB archive size. Review bundles require nonempty
`report.bin`; check bundles require `stdout.bin` and `stderr.bin`, which can be empty.
Runner streams are capped at 8 MiB each. Exceeding the cap truncates captured output
and produces failed `output_limit` evidence, never success. Use a separate authorized
verification approach when its output cannot fit these limits.

Timeout/interruption attempts terminate the owned process tree using the supported
platform mechanism, with a direct-child fallback. Escaped/background descendants
and abrupt runner death cannot be guaranteed cleaned up. Unclosed output streams
prevent final archive publication and leave the raw attempt directory for inspection.
Publication uses an exclusive hard link; a filesystem that cannot support it returns
an error instead of replacing an existing destination.

An adoption refusal after a successful archive copy returns its archive path and
`adopted: false` with a nonzero exit. A lock-cleanup failure after a completed state
operation returns its actual `changed` flag, manifest hash and `cleanup_error`, also
with a nonzero exit. The manifest may already be committed in that case: inspect it
and the retained lock instead of assuming rollback or retrying blindly.

## Handoff

Supply the current helper and this reference to analysts and workers using these
operations. Existing skills' scientific, independence and authority boundaries
remain in force. Keep original bundles and reports available until the analyst has
verified transfer and integration. Use the [local cleanup procedure](../../../../harness/git-workflow.md#local-cleanup-after-a-verified-merge)
before releasing a worker's branch or worktree.
