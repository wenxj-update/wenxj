"""STK 12 COM 桥接:场景加载/卫星状态 DP/地面点坐标/仿真时间步进。

comtypes 懒加载:仅真实模式 start_application 时才 import comtypes,
mock 模式或无 STK 环境下本模块可正常导入。

已验证接口(STK 12.2,实测):
- 场景时间:QI IAgScenario 的 StartTime/StopTime(UTCG 字符串)
- 仿真时刻:root.CurrentTime(float,自场景起算秒,可写)
- 卫星状态:DataProvider 组路径
    "Cartesian Position/ICRF"  "Cartesian Velocity/ICRF"  (J2000,km / km/s)
    "Cartesian Position/Fixed" "Cartesian Velocity/Fixed" (地固,km / km/s)
    "Classical Elements/J2000"                             (km / deg)
- 地面点:QI IAgTarget/IAgFacility 后 Position.QueryPlanetodetic()
    -> (lat_deg, lon_deg, alt_m)
- 对象通用成员(DataProviders/Children 等)直接在 Person2 返回的
  原始接口上可用,无需 QI;QI 仅用于场景时间与地面点 Position。

数据流向:Python 侧以 COM "拉取"方式按仿真节拍取数并组帧,等价于
STK 实时推送,无需在 STK 内安装额外推送插件。
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional

from ..core.config import StkConfig
from ..core.exceptions import StkError
from ..models.orbit import OrbitState, SatelliteClock, STK_EPOCH_2009
from ..models.target import AreaTarget, TargetPoint, TargetSet

_log = logging.getLogger("rwgh.stk")

# STK 报文时间历元:2009-01-01 UTC(报文整秒字段自此累计)
STK_EPOCH = STK_EPOCH_2009


class StkComBridge:
    """STK COM 封装。

    线程要求:所有 COM 调用必须在同一线程内先 CoInitialize 后执行。
    由 ui.workers.StkRealController(QThread)保证。
    """

    def __init__(self, cfg: StkConfig) -> None:
        self._cfg = cfg
        self._app = None           # STK Application COM 对象
        self._root = None          # IAgStkObjectRoot(原始接口,成员齐全)
        self._scenario = None      # IAgStkObject(通用对象接口)
        self._scenario_if = None   # IAgScenario(时间属性)
        self._stk_objects = None   # comtypes.gen.STKObjects 模块
        self._com_inited = False
        self._created_instance = False  # 附加已有实例时为 False,close 不退出 STK

    # ---------- 生命周期 ----------

    def start_application(self, visible: Optional[bool] = None) -> None:
        """启动(或附加)STK 应用。必须在工作线程内调用。"""
        try:
            import comtypes
            import comtypes.client as cc
        except ImportError as e:  # pragma: no cover
            raise StkError("comtypes not installed: pip install comtypes") from e

        try:
            comtypes.CoInitialize()
        except Exception:  # noqa: BLE001 已初始化也忽略
            pass
        self._com_inited = True

        self._ensure_stk_objects()

        visible = self._cfg.visible if visible is None else visible
        try:
            try:
                self._app = cc.GetActiveObject(self._cfg.progid)
                self._created_instance = False
                _log.info("STK: attached to running instance")
            except Exception:  # noqa: BLE001
                self._app = cc.CreateObject(self._cfg.progid)
                self._created_instance = True
                _log.info("STK: created new instance")
            try:
                self._app.Visible = visible
            except Exception:  # noqa: BLE001
                pass
            # Person2 返回 POINTER(_IAgStkObjectRoot),通用成员直接可用
            self._root = self._app.Personality2
        except Exception as e:  # pragma: no cover
            raise StkError(f"start STK failed: {e}") from e

    def _ensure_stk_objects(self) -> None:
        """生成 comtypes.gen.STKObjects 类型库包装(QI IAgScenario/IAgTarget 用)。"""
        try:
            import comtypes.client as cc
            tlb = os.path.join(self._cfg.install_dir, self._cfg.tlb_path)
            if os.path.isfile(tlb):
                cc.GetModule(tlb)
            else:
                cc.GetModule(self._cfg.progid)
            from comtypes.gen import STKObjects as mod  # noqa: WPS433
            self._stk_objects = mod
        except Exception as e:  # pragma: no cover
            raise StkError(f"STKObjects type library gen failed: {e}") from e

    def load_scenario(self, path: str) -> None:
        """加载 .sc 场景文件(已加载同名场景则直接复用)。"""
        if self._root is None:
            raise StkError("STK application not started")
        want_name = os.path.splitext(os.path.basename(path))[0]
        try:
            existing = self._root.CurrentScenario
            if existing is not None and existing.InstanceName == want_name:
                self._scenario = existing
                self._scenario_if = self._scenario.QueryInterface(
                    self._stk_objects.IAgScenario)
                _log.info("reuse already-open scenario: %s", want_name)
                return
        except Exception:  # noqa: BLE001  当前无场景,继续正常加载
            pass
        try:
            self._root.LoadScenario(path)
            self._scenario = self._root.CurrentScenario
            self._scenario_if = self._scenario.QueryInterface(
                self._stk_objects.IAgScenario)
            _log.info("scenario loaded: %s", self._scenario.InstanceName)
        except Exception as e:
            raise StkError(f"load scenario failed: {path}: {e}") from e

    # ---------- 场景信息 ----------

    def scenario_period(self) -> tuple[str, str]:
        """返回场景分析起止 UTCG 字符串。"""
        if self._scenario_if is None:
            raise StkError("no scenario loaded")
        return str(self._scenario_if.StartTime), str(self._scenario_if.StopTime)

    def satellite_names(self) -> list[str]:
        """场景内全部卫星对象名。"""
        if self._scenario is None:
            raise StkError("no scenario loaded")
        out: list[str] = []
        for i in range(self._scenario.Children.Count):
            obj = self._scenario.Children.Item(i)
            if obj.ClassName == "Satellite":
                out.append(obj.InstanceName)
        return out

    def list_targets(self) -> TargetSet:
        """地面对象(Target + Facility)经纬度。

        QueryPlanetodetic 返回 (lat°, lon°, alt m);alt m -> km。
        """
        if self._scenario is None:
            raise StkError("no scenario loaded")
        points: list[TargetPoint] = []
        areas: list[AreaTarget] = []
        ag = self._stk_objects
        for i in range(self._scenario.Children.Count):
            obj = self._scenario.Children.Item(i)
            cls, name = obj.ClassName, obj.InstanceName
            try:
                if cls == "Target":
                    pos = obj.QueryInterface(ag.IAgTarget).Position
                    lat, lon, alt_m = pos.QueryPlanetodetic()
                    points.append(TargetPoint(
                        id=name, lon=float(lon), lat=float(lat),
                        alt=float(alt_m) / 1000.0))
                elif cls == "Facility":
                    pos = obj.QueryInterface(ag.IAgFacility).Position
                    lat, lon, alt_m = pos.QueryPlanetodetic()
                    points.append(TargetPoint(
                        id=name, lon=float(lon), lat=float(lat),
                        alt=float(alt_m) / 1000.0))
                elif cls == "AreaTarget":
                    # 区域目标顶点提取按实际需要再扩展
                    pass
            except Exception as e:  # noqa: BLE001
                _log.warning("read ground object %s failed: %s", name, e)
        _log.info("list_targets: %d points, %d areas", len(points), len(areas))
        return TargetSet(points=tuple(points), areas=tuple(areas))

    # ---------- 卫星状态(DP 拉取) ----------

    def satellite_state(self, sat_name: str, utc_time: str) -> dict[str, Any]:
        """取指定 UTCG 时刻卫星状态。

        返回:
          {
            "j2k_pos": (x,y,z) km, "j2k_vel": (vx,vy,vz) km/s,
            "fix_pos": (x,y,z) km, "fix_vel": (vx,vy,vz) km/s,
            "elements": (sma_km, ecc, inc_deg, raan_deg, aop_deg, ma_deg),
          }
        """
        if self._scenario is None:
            raise StkError("no scenario loaded")
        sat = self._scenario.Children.Item(sat_name)
        dpp = sat.DataProviders

        def _xyz(path: str) -> dict[str, float]:
            dp = dpp.GetDataPrvTimeVarFromPath(path)
            res = dp.Exec(utc_time, utc_time, 60.0)
            row: dict[str, float] = {}
            for ds in res.DataSets:
                nm = ds.ElementName
                if nm in ("x", "y", "z", "speed"):
                    row[nm] = float(list(ds.GetValues())[0])
            return row

        jp = _xyz("Cartesian Position/ICRF")
        jv = _xyz("Cartesian Velocity/ICRF")
        fp = _xyz("Cartesian Position/Fixed")
        fv = _xyz("Cartesian Velocity/Fixed")

        dp = dpp.GetDataPrvTimeVarFromPath("Classical Elements/J2000")
        er = dp.Exec(utc_time, utc_time, 60.0)
        emap = {}
        for ds in er.DataSets:
            if ds.ElementName == "Time":
                continue
            emap[ds.ElementName] = float(list(ds.GetValues())[0])
        elements = (
            emap["Semi-major Axis"], emap["Eccentricity"],
            emap["Inclination"], emap["RAAN"],
            emap["Arg of Perigee"], emap["Mean Anomaly"],
        )
        return {
            "j2k_pos": (jp["x"], jp["y"], jp["z"]),
            "j2k_vel": (jv["x"], jv["y"], jv["z"]),
            "fix_pos": (fp["x"], fp["y"], fp["z"]),
            "fix_vel": (fv["x"], fv["y"], fv["z"]),
            "elements": elements,
        }

    def get_orbit(self, sat_name: str, t0: datetime, t1: datetime,
                  step: float = 60.0) -> list[OrbitState]:
        """保留接口:按时间区间采样轨道(当前按单时刻 DP 循环实现可按需扩展)。"""
        _log.info("get_orbit: sat=%s (use satellite_state for streaming)", sat_name)
        return []

    def get_satellite_clock(self, sat_name: str) -> SatelliteClock:
        now = datetime.now(tz=timezone.utc)
        return SatelliteClock(epoch=STK_EPOCH, current=now, clock_count=0)

    # ---------- 仿真时间 ----------

    def set_current_time(self, seconds_from_start: float) -> None:
        """设置仿真时刻(自场景起算秒,2D/3D 视图同步刷新)。"""
        if self._root is None:
            raise StkError("STK root not available")
        self._root.CurrentTime = float(seconds_from_start)

    def get_current_time(self) -> float:
        """获取 STK 当前仿真时刻(自场景起算秒)。"""
        if self._root is None:
            raise StkError("STK root not available")
        return float(self._root.CurrentTime)

    def enable_tcp_push(self, host: str, port: int,
                        msg_filter: Optional[list[str]] = None) -> None:
        """当前采用 Python COM 拉取模式,无需 STK 侧推送配置;保留接口。"""
        _log.info("pull mode active (COM polling); TCP push not required "
                  "for %s:%d", host, port)

    @staticmethod
    def force_kill_stk() -> bool:
        """强制终止 STK 进程(当 COM 无响应时)。

        在 UI 线程调用安全:只做 subprocess,不碰 COM 对象。
        返回 True 如果找到并杀死了进程。
        """
        import subprocess
        killed = False
        try:
            r = subprocess.run(
                ["taskkill", "/F", "/IM", "AgUiApplication.exe"],
                capture_output=True, text=True, timeout=10)
            killed = r.returncode == 0
        except Exception:  # noqa: BLE001
            pass
        return killed

    @staticmethod
    def bring_stk_to_foreground() -> bool:
        """将 STK 窗口提到前台(UI 线程调用,不依赖 COM)。

        用 ctypes 调 Win32 API 枚举窗口找 STK 主窗口并前置。
        """
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        SW_RESTORE = 9
        found = []

        @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
        def _enum_cb(hwnd, lparam):
            if user32.IsWindowVisible(hwnd):
                length = user32.GetWindowTextLengthW(hwnd)
                if length > 0:
                    buf = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, buf, length + 1)
                    if "STK" in buf.value:
                        found.append(hwnd)
            return True

        user32.EnumWindows(_enum_cb, 0)
        if found:
            hwnd = found[0]
            user32.ShowWindow(hwnd, SW_RESTORE)
            user32.SetForegroundWindow(hwnd)
            return True
        return False

    def close(self) -> None:
        # 仅退出由本桥创建的实例;附加的用户实例保持运行
        if self._app is not None and self._created_instance:
            try:
                self._app.Quit()
            except Exception:  # noqa: BLE001
                pass
        self._app = None
        self._root = None
        self._scenario = None
        self._scenario_if = None
        if self._com_inited:
            try:
                import comtypes
                comtypes.CoUninitialize()
            except Exception:  # noqa: BLE001
                pass
            self._com_inited = False


class MockStkSource:
    """MVP 用:不连真实 STK,提供桩数据。"""

    def __init__(self, cfg: StkConfig) -> None:
        self._cfg = cfg

    def start_application(self, visible: Optional[bool] = None) -> None:
        _log.info("MockStk: start_application (no real STK)")

    def load_scenario(self, path: str) -> None:
        _log.info("MockStk: load_scenario %s", path)

    def list_targets(self) -> TargetSet:
        return TargetSet(points=(
            TargetPoint(id="T001", lon=120.0, lat=30.0, alt=0.5),
            TargetPoint(id="T002", lon=110.0, lat=20.0, alt=0.5),
        ))

    def get_satellite_clock(self, sat_name: str) -> SatelliteClock:
        now = datetime.now(tz=timezone.utc)
        return SatelliteClock(epoch=STK_EPOCH, current=now, clock_count=0)

    def enable_tcp_push(self, host: str, port: int,
                        msg_filter: Optional[list[str]] = None) -> None:
        _log.info("MockStk: enable_tcp_push %s:%d", host, port)

    def close(self) -> None:
        pass
