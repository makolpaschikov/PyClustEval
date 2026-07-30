from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Any
import yaml

@dataclass(frozen=True)
class RawConfig:
    data: dict[str, Any]

    @classmethod
    def from_yaml(cls, path: str | Path) -> "RawConfig":
        with open(path, "r", encoding="utf-8") as f:
            return cls(yaml.safe_load(f))
