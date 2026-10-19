"""模板比对结果数据模型。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from .command import Command


@dataclass(frozen=True)
class Discrepancy:
    """单处差异。"""
    kind: str               # "time" | "code" | "missing" | "extra" | "param"
    detail: str
    expected: Any = None
    actual: Any = None
    index: int = -1          # 指令序号


@dataclass(frozen=True)
class ComparisonResult:
    """模板比对结果。"""
    template_name: str
    target_id: str
    matches: tuple[Command, ...] = field(default_factory=tuple)
    discrepancies: tuple[Discrepancy, ...] = field(default_factory=tuple)
    passed: bool = False

    @property
    def match_count(self) -> int:
        return len(self.matches)

    @property
    def discrepancy_count(self) -> int:
        return len(self.discrepancies)
