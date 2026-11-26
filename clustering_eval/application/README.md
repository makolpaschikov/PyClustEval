# Comparison requests and reports (clustering_eval/application)

## Summary

Follow a desktop comparison from the selected algorithms and dataset to individual run reports and saved history.

## References

- [dto.py](dto.py) — Fields accepted by RunRequest and returned in ComparisonReport.
- [comparison_service.py](comparison_service.py) — How the desktop comparison service coordinates multiple algorithms.
- [compute.py](compute.py) — How a campaign worker executes a single prepared job.
- [compute_report.py](compute_report.py) — How prepared jobs contribute diagnostics and native reports.
- [history_query_service.py](history_query_service.py) — Queries behind the desktop history view.
