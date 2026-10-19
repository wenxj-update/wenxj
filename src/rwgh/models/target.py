"""目标点数据模型:点目标/区域目标。"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class TargetPoint:
    """点目标。"""
    id: str
    lon: float           # 经度(deg)
    lat: float           # 纬度(deg)
    alt: float = 0.0     # 高度(km)

    def __post_init__(self) -> None:
        if not (-180.0 <= self.lon <= 180.0):
            raise ValueError(f"lon out of range: {self.lon}")
        if not (-90.0 <= self.lat <= 90.0):
            raise ValueError(f"lat out of range: {self.lat}")


@dataclass(frozen=True)
class AreaTarget:
    """区域目标:多边形顶点序列(经纬度)。"""
    id: str
    vertices: tuple[tuple[float, float], ...]   # [(lon, lat), ...]

    def __post_init__(self) -> None:
        if len(self.vertices) < 3:
            raise ValueError("area target needs >=3 vertices")


@dataclass(frozen=True)
class TargetSet:
    """一次报文携带的目标集合。"""
    points: tuple[TargetPoint, ...] = field(default_factory=tuple)
    areas: tuple[AreaTarget, ...] = field(default_factory=tuple)
