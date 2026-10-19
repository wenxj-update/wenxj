"""可见性算法:抽象接口 + ctypes 实现(扩展点) + Stub(MVP)。

【扩展点3】CtVisibilityAlgorithm.compute 待用户提供 .dll 真实函数签名后补全:
           构造 ctypes 结构/指针、调用 dll、回收结果转 dataclass。
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Protocol, runtime_checkable

from .loader import LoadedDll
from .dll_plan import (DllPlanDriver, DllPlanResult, DEFAULT_STEP_SEC)
from ..models.orbit import OrbitState, SatelliteClock
from ..models.target import TargetPoint
from ..models.visibility import VisibilityResult, VisibilityWindow

_log = logging.getLogger("rwgh.algorithm.visibility")


@runtime_checkable
class IVisibilityAlgorithm(Protocol):
    """可见性计算算法接口。"""

    def compute(self, targets: list[TargetPoint],
                orbit: list[OrbitState],
                clock: SatelliteClock) -> list[VisibilityResult]:
        ...


class CtVisibilityAlgorithm:
    """通过 ctypes 调用真实 .dll(报文驱动协议,见 algorithm/dll_plan.py)。

    真实接口(参考工程 RWGH_test/tool.h):
      DllInit / DllInput(Byte*,int) / DllOutput(Byte*,int*)
    规划计算走 compute_plan():按 scenario_target.c 时序
    (3101 → 0C12 → 0C15 → 0B01 星时推进)驱动 DLL,收集
    0F11/0F22/0F33/0F44 输出报文。
    compute() 保留为 pipeline 兼容入口(Stub 回退,仅内部节拍用)。
    """

    def __init__(self, dll: LoadedDll) -> None:
        self._dll = dll
        # 报文驱动器(懒加载,首次 compute_plan 时 DllInit)
        self._driver = DllPlanDriver(dll)
        # pipeline 兼容入口回退 Stub(仅 mock 节拍用,主链路走 compute_plan)
        self._stub_fallback = StubVisibilityAlgorithm()
        _log.info("CtVisibilityAlgorithm 就绪(报文驱动协议 DllInput/DllOutput)")

    @property
    def driver(self) -> DllPlanDriver:
        return self._driver

    def compute_plan(self, task_bytes: bytes,
                     link_bytes: bytes | None = None,
                     station_bytes: bytes | None = None,
                     orbit_frames: tuple[bytes, ...] = (),
                     star_base_sec: int | None = None,
                     advance_from: int | None = None,
                     advance_to: int | None = None,
                     step_sec: int = DEFAULT_STEP_SEC,
                     step_delay_ms: int = 20,
                     progress_cb=None) -> DllPlanResult:
        """报文驱动规划计算(兼容旧接口,一次性完成阶段1+2)。"""
        return self._driver.compute_plan(
            task_bytes, link_bytes=link_bytes,
            station_bytes=station_bytes, orbit_frames=orbit_frames,
            star_base_sec=star_base_sec,
            advance_from=advance_from, advance_to=advance_to,
            step_sec=step_sec, step_delay_ms=step_delay_ms,
            progress_cb=progress_cb)

    def compute_initial(self, task_bytes: bytes,
                        link_bytes: bytes | None = None,
                        station_bytes: bytes | None = None,
                        storage_bytes: bytes | None = None,
                        orbit_frames: tuple[bytes, ...] = (),
                        star_base_sec: int | None = None,
                        step_delay_ms: int = 20) -> DllPlanResult:
        """阶段1:发送输入 → 立即输出 0F33/0F44。"""
        return self._driver.compute_initial(
            task_bytes, link_bytes=link_bytes,
            station_bytes=station_bytes, storage_bytes=storage_bytes,
            orbit_frames=orbit_frames,
            star_base_sec=star_base_sec, step_delay_ms=step_delay_ms)

    def advance_star_time(self, current_sec: float,
                          step_delay_ms: int = 20) -> DllPlanResult:
        """阶段2:推进星时 → 到达关键时间点时输出 0F11/0F22。"""
        return self._driver.advance_star_time(
            current_sec, step_delay_ms=step_delay_ms)

    def is_phase2_complete(self) -> bool:
        """阶段2是否所有 0F11 关键时间点都已触发。"""
        return self._driver.is_phase2_complete()

    def compute(self, targets: list[TargetPoint],
                orbit: list[OrbitState],
                clock: SatelliteClock) -> list[VisibilityResult]:
        # pipeline mock 节拍兼容入口:真实规划请走 compute_plan()
        return self._stub_fallback.compute(targets, orbit, clock)


class StubVisibilityAlgorithm:
    """MVP 用桩实现:不调 dll,基于 targets/clock 伪造可见性窗口。

    生成规则:每个目标一个窗口,aos=当前星时,los=+60s,max_el=45°。
    可重复,便于测试。
    """

    def __init__(self, window_seconds: float = 60.0, max_el: float = 45.0,
                 satellite: str = "SAT1") -> None:
        self._window_seconds = window_seconds
        self._max_el = max_el
        self._satellite = satellite

    def compute(self, targets: list[TargetPoint],
                orbit: list[OrbitState],
                clock: SatelliteClock) -> list[VisibilityResult]:
        t0 = clock.current
        windows = []
        for i, tp in enumerate(targets):
            # 错开每个目标的 aos,模拟连续过境
            aos = t0 + timedelta(seconds=i * 10.0)
            los = aos + timedelta(seconds=self._window_seconds)
            windows.append(VisibilityWindow(
                target_id=tp.id,
                aos=aos,
                los=los,
                max_el=self._max_el - (i % 3) * 5.0,
                duration_sec=self._window_seconds,
            ))
        _log.info("StubVisibility computed %d windows for %d targets",
                  len(windows), len(targets))
        return [VisibilityResult(satellite=self._satellite,
                                 windows=tuple(windows))]
