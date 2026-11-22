# Export and verify a campaign

Run these commands in the PyClustEval environment. Use a saved campaign directory as the input to export. The second command accepts a transferred archive without the original campaign, inputs or checkout.

```powershell
clustereval series export 'F:\runs\iris-pilot' --json
clustereval series verify 'E:\transfer\iris-pilot\archive' --json
```

Both operations are also available via `python -m clustering_eval.cli series`. The output directory is `archive` inside the campaign. To import the exported comparisons into a desktop history directory, run the included script.

```powershell
python 'E:\transfer\iris-pilot\archive\merge_history.py' --into 'F:\runs\history'
```

## Exit codes

| Code | JSON result | Meaning |
| --- | --- | --- |
| 0 | `complete` | The complete archive passed verification. |
| 2 | `invalid_input` | The supplied directory or format is unsupported. Argument parser errors also return 2. |
| 3 | `partial` | The archive passed verification with fewer accepted results than planned. Inspect the job statuses, reasons and availability of each dataset. |
| 3 | `busy`, `operation_failed` | Another publisher owns the campaign or an operating-system failure prevented the operation. For a temporary sharing violation, release the file lock and retry. |
| 4 | `invalid` | The recognized campaign or archive contains inconsistent or damaged evidence. |

Each JSON response names the action, result and path. Successful export sets `published` to true. Verification reads the archive and returns fresh checks, counts, errors and unavailable observations. Intact partial archives preserve the planned comparisons, available results and reasons for gaps. Damaged accepted files cause a failed export even when some jobs are still pending.

## Publication and recovery

The publisher uses a separate OS lock and can read a running campaign. Its manifest records which committed jobs and attempts were visible when the queue was read. An unfinished job can therefore appear as running. Export preserves the original workers, time intervals, metrics, labels and source snapshot.

The publisher verifies the staging directory, writes the prepublication report to `verification.json`, computes SHA-256 for every final file except `checksums.json`, and independently verifies the sealed directory. It then replaces the campaign's previous verified generation. This two-rename operation on Windows briefly moves the previous version out of the public path. Run `series export` again after interruption. Under its publisher lock the command restores the previous generation if installation stopped in the gap, or checks the replacement after installation. A read-only `verify` never repairs a campaign. Operational cleanup warnings include the affected workspace path. Preserve the campaign's `state` directory during recovery.

The general archive format is `pyclusteval.campaign-archive.v1`. `series verify` also recognizes the historical `pyclusteval.three-datasets-three-seeds.v1` format. Its report distinguishes actual checks from evidence unavailable in the older schema. Keep the original research archive read-only. For details of a specific export, see its `README.md`, `manifest.json`, and `reproduce/README.md`.
