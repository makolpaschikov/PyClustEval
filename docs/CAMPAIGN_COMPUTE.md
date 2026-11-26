# Computing a prepared comparison

Campaign execution takes one selected comparison from a resolved PLAN document. The dataset locator and source snapshot must agree with the bytes available to the running process. Callers can prepare the comparison once in a trusted directory and hand its descriptor to multiple workers.

```python
from pathlib import Path

from clustering_eval.application.compute import assemble_report, execute_one
from clustering_eval.experiments.prepared import prepare, reopen
from clustering_eval.experiments.series_plan import checkout_source_id

source_id = checkout_source_id()
descriptor = prepare(
    resolved_plan, comparison_id, Path("private-work") / comparison_id,
    source_id=source_id, base_dir=plan_directory,
)
prepared = reopen(descriptor, source_id=source_id, comparison_id=comparison_id)
execution = execute_one(prepared, prepared.jobs[0]["job_id"])
labels = execution.labels
adapter_state = execution.model_state
native_report = assemble_report(prepared, [execution])
```

`prepare` publishes a versioned descriptor and reserves its destination. Keep the adjacent reservation file when retaining a preparation for retries. A new process can reopen a complete bundle with its expected source and comparison IDs. It reads the stored release, including its actual matrix and fingerprint. A damaged or interrupted preparation raises an error. Creating another input-DP release is a separate preparation decision.

`execute_one` accepts an individual job ID, including distinct grid variants of the same algorithm. It returns the original labels, adapter state, round history in `execution.report.history`, UTC timestamps, a unique attempt ID and the enriched native algorithm report. The `execution.report.model_state["execution"]` block records individual timing, stopping, release scope and provenance. The clean evaluation matrix and fixed silhouette reference come from the shared scientific protocol. Legacy comparisons retain their own metrics, data parameters, partition and adapter defaults.

The worker call runs in the current process and applies the requested BLAS thread limit. The caller owns process isolation, concurrency, timeouts and durable attempts. Campaign Flower admission depends on the measured runtime and scientific mode. See the [Windows cold pilot](CAMPAIGN_PROFILE.md) for operator checks. Warm workers and archived persistent-worker identities require separate runtime verification. A numerical control of a historical stopping rule can use a new ordinary comparison with a supported backend and cold profile.

`JobExecutionError` retains the underlying exception as `__cause__` and its attempt metadata as `provenance`. After entry into an aggregate-DP adapter, a failure can leave an unknown release outcome. A retry represents a new attempt even for the same job and benchmark seed. Successful author-proxy runs report the mechanism stages actually used, including the prototype and histogram stages of the density proxy. Clipped controls record zero private queries. All full reports, prepared arrays, labels and diagnostics belong in the trusted study workspace.

`assemble_report` accepts only successes with compatible inputs, a common release and distinct job IDs. Report intervals cover the included jobs. Composition fields cover those successful attempts alone. A campaign supervisor must account for the rest of the attempts, including failures with uncertain releases. The caller can persist the returned native report using `HistoryStore.save`.

The GUI continues to use `ComparisonService.compare` for interactive validation, logging, partition notifications and history. Programmatic GUI comparisons can use `ComparisonService.prepare` and `ComparisonService.execute_one` to examine a single member over the same inputs. The GUI source fingerprint covers installed package Python files. Externally supplied registry implementations are identified by their class and require separate source evidence.
