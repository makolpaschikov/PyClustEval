# Experiment planning and campaign execution (clustering_eval/experiments)

## Summary

Trace how a YAML plan becomes a set of jobs, how inputs are shared and how a stopped campaign resumes.

## References

- [series_plan.py](series_plan.py) — Resolve a versioned plan into comparison groups and jobs.
- [prepared.py](prepared.py) — Build scientific inputs shared by algorithms in a comparison.
- [series_runner.py](series_runner.py) — Entry points for running, resuming, retrying and inspecting a campaign.
- [runner_queue.py](runner_queue.py) — Sequential scheduling, recovery decisions and retry policy.
- [runner_state.py](runner_state.py) — Campaign state persisted by the supervisor in SQLite.
- [source_capture.py](source_capture.py) — Capture the working source for a campaign.
- [plan_archive.py](plan_archive.py) — Import the supported historical paper archive as a plan.
- [planner.py](planner.py) — Expand a legacy configuration into experiment specifications for [runner.py](runner.py).
- [../results/README.md](../results/README.md) — Find the archive export and verification code used after execution.
