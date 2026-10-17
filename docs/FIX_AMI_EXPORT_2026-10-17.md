# Fix: AMI missing in exported/copied results (2026-10-17)

## Root causes

1. `HistoryQueryService._to_algorithm_result()` did not deserialize `ami` from stored `report.json`. Live comparisons correctly computed AMI, but reopening an experiment from History replaced its AMI with `None`, so the History table and **Copy Results** produced `—` for AMI.
2. The XLSX `Results` worksheet exported AMI after 32 unrelated columns (AH), far from ARI and NMI. AMI was not included in the explicit formatted numeric-column set.

## Fixes

- Read `ami` when restoring `AlgorithmRunReport` from `report.json`; legacy history without `ami` still loads and retains undefined AMI as `None` rather than manufacturing a value.
- Put ARI / AMI / NMI next to one another in the main XLSX `Results` worksheet (columns F / G / H), format AMI as a number, and update color-scale reference for the shifted Davies–Bouldin column.
- Replace brittle hardcoded numeric-format column offsets with header names and check header/value alignment.
- Add regression tests covering a **real Iris execution**, history round-trip, XLSX cell values/types, and live/history Tk clipboard copies.

## Verification

Run from the project root:

```bash
python -m pytest -q tests/test_ami_export_roundtrip.py
python -m pytest -q
```

Tk interface tests need a graphical display. In headless Linux, run `xvfb-run -a python -m pytest -q` if Xvfb is available.

The patch does **not** retroactively calculate AMI for old saved runs that never contained this metric; those remain blank until recomputed with real predictions.
