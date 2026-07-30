from __future__ import annotations
from pathlib import Path
import json
import pandas as pd

class ResultStore:
    def __init__(self, output_dir: str | Path) -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.rows: list[dict] = []

    def add(self, row: dict) -> None:
        self.rows.append(row)
        pd.DataFrame(self.rows).to_csv(self.output_dir / "metrics.csv", index=False)

    def write_jsonl(self, name: str, record: dict) -> None:
        with open(self.output_dir / name, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
