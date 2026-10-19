"""STK 工作线程封装。

- mock 模式:MockStkSource,主线程即时调用(无真实 STK)。
- real 模式:StkRealController 移入 QThread 执行:
    run(): CoInitialize -> 启动 STK -> 加载场景 -> 取目标
    stream 模式:QTimer 节拍循环自动推帧
    manual 模式:不启动定时器,等待 fetch_targets/fetch_snapshot 信号
  所有 COM 调用严格限定在该线程,Qt 信号跨线程自动排队。
"""
from __future__ import annotations

import logging
from datetime import timedelta

from PySide6.QtCore import QObject, QThread, QTimer, Signal, Slot

from ...core.config import StkConfig
from ...stk.com_bridge import StkComBridge, MockStkSource
from ...stk.packets import StkPacketBuilder, parse_utcg, format_utcg
from ...parsing.parser import FrameParser
from ...parsing.registry import FormatRegistry

_log = logging.getLogger("rwgh.ui.stk_worker")


class StkRealController(QObject):
    """运行在 STK 工作线程内的控制器(仅 real 模式)。"""

    status = Signal(str)
    error = Signal(str)
    targets_ready = Signal(object)   # list[TargetPoint]
    frame_ready = Signal(object)     # bytes
    finished = Signal()

    def __init__(self, cfg: StkConfig, scenario_path: str,
                 registry: FormatRegistry, host: str, port: int,
                 manual: bool = False, parent=None) -> None:
        super().__init__(parent)
        self._cfg = cfg
        self._scenario_path = scenario_path
        self._registry = registry
        self._host = host
        self._port = port
        self._manual = manual  # True=不启动定时器
        self._bridge: StkComBridge | None = None
        self._builder: StkPacketBuilder | None = None
        self._timer: QTimer | None = None
        self._cur = 0.0
        self._period = 0.0
        self._start_dt = None
        self._sat_name = ""
        self._loop = None

    @Slot()
    def run(self) -> None:
        try:
            self.status.emit("STK 启动中(首次约 30~60s)…")
            self._bridge = StkComBridge(self._cfg)
            self._bridge.start_application()
            self.status.emit(f"加载场景: {self._scenario_path}")
            self._bridge.load_scenario(self._scenario_path)

            start_str, stop_str = self._bridge.scenario_period()
            self._start_dt = parse_utcg(start_str)
            self._period = (parse_utcg(stop_str) - self._start_dt).total_seconds()

            sats = self._bridge.satellite_names()
            self._sat_name = sats[0] if sats else "Satellite1"

            self._builder = StkPacketBuilder(self._registry, FrameParser())

            # 取初始目标
            tset = self._bridge.list_targets()
            self.targets_ready.emit(list(tset.points))
            mode_text = "手动模式" if self._manual else f"推流中(每{self._cfg.tick_ms}ms推进{self._cfg.step_seconds:.0f}s)"
            self.status.emit(
                f"场景就绪: {len(tset.points)} 个目标, 卫星 {self._sat_name}, "
                f"周期 {self._period:.0f}s, {mode_text}")

            if not self._manual:
                # 推流模式:启动定时器
                self._bridge.set_current_time(0.0)
                self._cur = 0.0
                self._timer = QTimer()
                self._timer.timeout.connect(self._tick)
                self._timer.start(self._cfg.tick_ms)
            else:
                # 手动模式:不启动定时器,等待 fetch 信号
                self.status.emit("手动模式:点击「获取目标」或「计算可见性」按钮操作")

            from PySide6.QtCore import QEventLoop
            self._loop = QEventLoop()
            self._loop.exec()
        except Exception as e:  # noqa: BLE001
            _log.exception("STK real controller failed")
            self.error.emit(str(e))
            self.finished.emit()

    def _tick(self) -> None:
        try:
            self._cur += self._cfg.step_seconds
            if self._cur > self._period:
                self._cur = 0.0
            self._bridge.set_current_time(self._cur)
            self._emit_snapshot()
        except Exception as e:  # noqa: BLE001
            _log.exception("STK tick failed")
            self.error.emit(str(e))

    @Slot()
    def fetch_targets(self) -> None:
        """手动拉取 STK 场景当前目标列表。"""
        try:
            tset = self._bridge.list_targets()
            self.targets_ready.emit(list(tset.points))
            self.status.emit(
                f"已获取 {len(tset.points)} 个目标(手动拉取)")
        except Exception as e:  # noqa: BLE001
            _log.exception("fetch_targets failed")
            self.error.emit(f"获取目标失败: {e}")

    @Slot()
    def fetch_snapshot(self) -> None:
        """手动拉取 STK 当前时刻卫星状态,生成 3 帧报文。"""
        try:
            assert self._bridge and self._builder and self._start_dt
            # 用 STK 当前仿真时间
            cur_time = self._bridge.get_current_time()
            dt = self._start_dt + timedelta(seconds=cur_time)
            utc = format_utcg(dt)

            st = self._bridge.satellite_state(self._sat_name, utc)
            elems = st["elements"]
            self.frame_ready.emit(self._builder.time_frame(dt))
            self.frame_ready.emit(self._builder.elements_frame(
                dt, elems[0], elems[1], elems[2], elems[3], elems[4], elems[5]))
            self.frame_ready.emit(self._builder.orbit_data_frame(
                dt, st["fix_pos"], st["fix_vel"],
                st["j2k_pos"], st["j2k_vel"]))
            self.status.emit(
                f"已拉取卫星状态(手动): {utc[0:20]} ({cur_time:.0f}s)")
        except Exception as e:  # noqa: BLE001
            _log.exception("fetch_snapshot failed")
            self.error.emit(f"拉取卫星状态失败: {e}")

    @Slot()
    def shutdown(self) -> None:
        try:
            if self._timer is not None:
                self._timer.stop()
            if self._loop is not None:
                self._loop.quit()
            if self._bridge is not None:
                self._bridge.close()
            self.status.emit("STK 已停止")
        finally:
            self.finished.emit()


class StkWorker(QObject):
    """UI 侧包装:按 mode 选择 mock 即时源或真实 QThread 控制器。"""

    status = Signal(str)
    error = Signal(str)
    frame_ready = Signal(object)      # bytes(real 模式)
    targets_ready = Signal(object)    # list[TargetPoint](real 模式)
    stop_requested = Signal()         # 排队投递到工作线程的 shutdown
    fetch_targets_requested = Signal()
    fetch_snapshot_requested = Signal()

    def __init__(self, cfg: StkConfig, mode: str = "mock",
                 registry: FormatRegistry | None = None, parent=None) -> None:
        super().__init__(parent)
        self._mode = mode
        self._cfg = cfg
        self._registry = registry
        if mode == "real":
            self._bridge = None
        else:
            self._bridge = MockStkSource(cfg)
        self._thread: QThread | None = None
        self._controller: StkRealController | None = None
        self._running = False

    @property
    def running(self) -> bool:
        return self._running

    def start(self, scenario_path: str = "", host: str = "127.0.0.1",
              port: int = 8001, manual: bool = False) -> None:
        """启动 STK。manual=True 时不自动推流,等待手动触发。"""
        if self._mode != "real":
            try:
                self._bridge.start_application()
                if scenario_path:
                    self._bridge.load_scenario(scenario_path)
                self._bridge.enable_tcp_push(host, port)
                self.status.emit("STK started (mode=mock)")
            except Exception as e:  # noqa: BLE001
                _log.exception("STK start failed")
                self.error.emit(str(e))
            return

        if self._running:
            return
        path = scenario_path or self._cfg.scenario_path
        if not path:
            self.error.emit("real 模式需要 stk.scenario_path 场景路径")
            return
        if self._registry is None:
            self.error.emit("real 模式需要 FormatRegistry(组帧用)")
            return

        self._thread = QThread()
        self._controller = StkRealController(
            self._cfg, path, self._registry, host, port, manual=manual)
        self._controller.moveToThread(self._thread)
        self._thread.started.connect(self._controller.run)
        self._controller.status.connect(self.status)
        self._controller.error.connect(self.error)
        self._controller.targets_ready.connect(self.targets_ready)
        self._controller.frame_ready.connect(self.frame_ready)
        self._controller.finished.connect(self._on_finished)
        self.stop_requested.connect(self._controller.shutdown)
        self.fetch_targets_requested.connect(self._controller.fetch_targets)
        self.fetch_snapshot_requested.connect(self._controller.fetch_snapshot)
        self._thread.start()
        self._running = True

    def stop(self) -> None:
        if self._mode != "real":
            try:
                self._bridge.close()
            except Exception:  # noqa: BLE001
                pass
            return
        if not self._running or self._controller is None:
            return
        self.stop_requested.emit()

    def wait(self, timeout_ms: int = 10000) -> None:
        if self._thread is not None:
            self._thread.wait(timeout_ms)

    def force_kill(self) -> None:
        from ...stk.com_bridge import StkComBridge
        killed = StkComBridge.force_kill_stk()
        if self._running and self._controller is not None:
            self.stop_requested.emit()
        self._running = False
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait(3000)
            self._thread = None
        self._controller = None
        if killed:
            self.status.emit("STK 进程已强制终止")
        else:
            self.status.emit("未找到 STK 进程(可能已退出)")

    def reconnect(self, scenario_path: str = "",
                  host: str = "127.0.0.1", port: int = 8001,
                  manual: bool = False) -> None:
        if self._running:
            self.stop()
            self.wait(5000)
        self.start(scenario_path=scenario_path, host=host, port=port,
                   manual=manual)

    def bring_stk_foreground(self) -> bool:
        from ...stk.com_bridge import StkComBridge
        ok = StkComBridge.bring_stk_to_foreground()
        if ok:
            self.status.emit("STK 窗口已前置")
        else:
            self.status.emit("未找到 STK 窗口(可能未启动)")
        return ok

    def fetch_targets(self) -> None:
        """手动拉取目标(工作线程执行)。"""
        if self._running:
            self.fetch_targets_requested.emit()

    def fetch_snapshot(self) -> None:
        """手动拉取卫星状态快照(工作线程执行)。"""
        if self._running:
            self.fetch_snapshot_requested.emit()

    @Slot()
    def _on_finished(self) -> None:
        self._running = False
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait(5000)
            self._thread = None
        self._controller = None
