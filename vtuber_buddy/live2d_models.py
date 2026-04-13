from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(slots=True, frozen=True)
class Live2DModelCandidate:
    source: str
    source_root: Path
    model_path: Path
    runtime_root: Path

    @property
    def model_name(self) -> str:
        return self.model_path.name.removesuffix(".model3.json")

    @property
    def model_relative_path(self) -> Path:
        return self.model_path.relative_to(self.source_root)

    @property
    def runtime_relative_path(self) -> Path:
        return self.runtime_root.relative_to(self.source_root)


@dataclass(slots=True, frozen=True)
class Live2DExpression:
    name: str
    file: str
    asset_relative_path: str


@dataclass(slots=True, frozen=True)
class Live2DMotion:
    name: str
    file: str
    asset_relative_path: str
    group: str
    index: int
    definition: dict[str, Any]
