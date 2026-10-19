"""轨道与星时数据模型。"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

# STK 报文时间起点:格林威治 2009-01-01 00:00:00 UTC
# 报文中"整秒"字段为自此历元起的 UTC 累计秒
STK_EPOCH_2009 = datetime(2009, 1, 1, tzinfo=timezone.utc)


def stk_seconds_to_datetime(seconds: int, millis: int = 0) -> datetime:
    """STK 报文时间(整秒+毫秒,自 2009 历元) -> datetime。"""
    from datetime import timedelta
    return STK_EPOCH_2009 + timedelta(seconds=seconds, milliseconds=millis)


@dataclass(frozen=True)
class OrbitState:
    """某一时刻的轨道状态(惯性系位置速度)。"""
    time: datetime
    x: float   # km
    y: float
    z: float
    vx: float  # km/s
    vy: float
    vz: float


@dataclass(frozen=True)
class SatelliteClock:
    """星上时钟/星时。"""
    epoch: datetime        # 起始历元
    current: datetime      # 当前仿真时刻
    clock_count: int       # 星时计数(自 epoch 起的秒或刻)


@dataclass(frozen=True)
class OrbitSegment:
    """一段轨道采样序列。"""
    satellite: str
    states: tuple[OrbitState, ...] = field(default_factory=tuple)
