# Importing the paper's historical campaign

Use this importer for the archived `pyclusteval.three-datasets-three-seeds.v1` release. Run these commands from a PyClustEval checkout with its project environment. Choose a destination outside the article archive.

```powershell
$cli = '.\.venv\Scripts\clustereval.exe'
& $cli series import-archive 'X:\study\experiments' --output '.\imported-plan.json'
& $cli series validate '.\imported-plan.json' --json
& $cli series plan '.\imported-plan.json' --output '.\resolved-plan.json'
```

The imported source document has the format `pyclusteval.plan.v1`. It contains an explicit list of datasets, ordered series and scenario templates, together with the archive reference under `historical.path`. The reference is relative to the source document's directory where possible. Dataset and evidence paths inside the historical profile are relative to the archive root. After moving the archive, update `historical.path`. Revalidation checks the linked evidence before returning any jobs. A change to an imported scientific field reports its location. Use an ordinary campaign source document for a different study design.

### Verified inputs

The importer discovers series and datasets through the manifest. It joins each planned run to its saved evidence using the series and external run ID. The file catalog for the supported release is pinned across the 56 inputs used by this profile:

- The manifest, the historical application snapshot and patch, and the preparation, worker, supervisor, export and environment evidence under `reproduce/`.
- The three original NPZ datasets, their verification records and the supplied auxiliary provenance files.
- Each series' protocol, experiment plan, partitions and series report.

The input pin is the SHA-256 of the sorted sequence of UTF-8 relative path, NUL, lowercase file SHA-256 and LF for each of these entries. Each consumed file is also compared with its recorded size and hash. A different scientific input catalog requires its own interpretation of the historical implementation. Verification here covers inputs used by the planner.

For each dataset, the importer checks the shapes, dtypes, row-order X/y hashes and class counts. All 54 client partitions are checked against their actual label vector, exact ordered indices, sizes and partition fingerprint. Each comparison checks the shared schedule and worker protocol; the planner copies the recorded effective K aliases, per-method parameters, backend, preprocessing and DP configuration. The certified matrix for this import contains 9 series, 207 comparisons and 1,620 planned jobs.

### Reading the resolved plan

The `source_id` identifies the current checkout for a prospective campaign. Historical computation provenance is under `historical.implementation`, with hashes of original scripts and inputs. Current execution readiness remains subject to the compute and backend checks. The historical preparation, fitting, runtime and metric code is read as evidence during planning.

- `comparisons[].protocol` records the common scientific conditions. Federated comparisons set `stopping_profile` to `historical_paper`, which binds that choice into scientific IDs. Each adapter's historical stopping rules apply. Local comparisons omit the federated setting.
- `protocol.partition` includes the original mode, alpha, sizes, per-client class counts, legacy fingerprint and SHA-256 of exact indices. `comparison.provenance.partition` identifies the archived JSON file and partition key holding the indices. Local comparisons have a null partition.
- `protocol.participation_schedule` holds the actual schedule once per comparison. For an original federated worker parameter set, combine that shared schedule with `jobs[].effective_params`. The latter includes the algorithm-specific `dp_aggregate` configuration, including budgeted rounds. The display name, historical backend and execution profile distinguish modified DP proxies and Flower workers.
- `jobs[].comparison_id` links to the comparison, and `(series, run_id)` identifies the original planned job. Output measurements and predictions stay in the archive. The planner neither trains methods nor regenerates private noise.
