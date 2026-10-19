"""可见性结果数据模型。"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class VisibilityWindow:
    """单个可见性窗口。"""
    target_id: str
    aos: datetime          # 进入可见(start)
    los: datetime          # 退出可见(end)
    max_el: float          # 最大仰角(deg)
    duration_sec: float = 0.0


@dataclass(frozen=True)
class VisibilityResult:
    """一个卫星对一组目标的可见性结果。"""
    satellite: str
    windows: tuple[VisibilityWindow, ...] = field(default_factory=tuple)
