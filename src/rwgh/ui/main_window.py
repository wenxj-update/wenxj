"""主窗口:深色航天风布局,6 页 Tab + DLL/模板加载/强关 STK/重连/导出。

布局自上而下:
  HeaderBar   系统标题 + STK 状态灯 + 模式徽章 + 算法库/模板路径
  ControlBar  启动STK / 强关STK / 重连 / 加载算法库 / 加载指令模板 / TCP / 注入报文 / 导出
  Tabs        报文信息 · 目标输入解析 · 可见性计算 · 指令反解 · 指令明细 · 比对结果
  StatusBar   运行日志
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

from PySide6.QtCore import Qt, QPoint, QRect, QSize
from PySide6.QtGui import QIcon, QPixmap, QImage
from PySide6.QtWidgets import QApplication
from PySide6.QtWidgets import (QMainWindow, QTabWidget, QVBoxLayout, QWidget,
                               QPushButton, QHBoxLayout, QLabel, QStatusBar,
                               QMessageBox, QFileDialog, QFrame, QComboBox,
                               QSizePolicy, QLayout, QToolButton, QMenu,
                               QDateTimeEdit, QStackedWidget)

from ..core.config import AppConfig, save_config
from ..core.event_bus import EventBus, Topics
from ..parsing.parser import FrameParser
from ..parsing.registry import FormatRegistry
from ..planning.pipeline import Pipeline
from ..planning.result_builder import build_all_results
from ..models.orbit import SatelliteClock, STK_EPOCH_2009
from .qt_event_bridge import QtEventBridge
from .theme import C
from .widgets import LedDot
from .views.stk_info_view import StkInfoView
from .views.target_io_view import TargetIoView
from .views.visibility_compute_view import VisibilityComputeView
from .views.command_gen_view import CommandGenView
from .views.command_detail_view import CommandDetailView
from .views.comparison_view import ComparisonResultView
from .views.message_view import MessageView
from .views.packet_view import PacketView
from .export_utils import ExportUtils
from .workers.socket_worker import SocketWorker
from .workers.stk_worker import StkWorker

_log = logging.getLogger("rwgh.ui.main_window")

_BTN_START_REAL = "启动 STK 真实场景"
_BTN_START_MOCK = "启动 STK(模拟)"
_BTN_STOP = "停止 STK"

# 默认星时(北京时间)2026-09-01 12:10:00
DEFAULT_STAR_BJ = datetime(2026, 9, 1, 12, 10, 0)


def _default_star_sec() -> float:
    """默认星时 2026-09-01 12:10:00(北京) → 2009 历元秒。"""
    dt_utc = (DEFAULT_STAR_BJ - timedelta(hours=8)).replace(
        tzinfo=timezone.utc)
    return float((dt_utc - STK_EPOCH_2009).total_seconds())



class FlowLayout(QLayout):
    """流式布局:控件自动换行,窗口缩小时不遮挡。"""

    def __init__(self, parent=None, spacing=6):
        super().__init__(parent)
        self._items: list = []
        self._spacing = spacing

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index):
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do_layout(QRect(0, 0, width, 0), test=True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, test=False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        w = 0
        h = 0
        for item in self._items:
            hint = item.sizeHint()
            w = max(w, hint.width())
            h = max(h, hint.height())
        return QSize(w + self._spacing, h + self._spacing)

    def _do_layout(self, rect, test):
        from PySide6.QtCore import QSize
        x = rect.x()
        y = rect.y()
        line_h = 0
        spacing = self._spacing
        for item in self._items:
            hint = item.sizeHint()
            next_x = x + hint.width() + spacing
            if next_x - spacing > rect.right() and line_h > 0:
                x = rect.x()
                y = y + line_h + spacing
                next_x = x + hint.width() + spacing
                line_h = 0
            if not test:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x = next_x
            line_h = max(line_h, hint.height())
        return y + line_h - rect.y()


class MainWindow(QMainWindow):
    def __init__(self, cfg: AppConfig, bus: EventBus, registry: FormatRegistry,
                 parser: FrameParser, pipeline: Pipeline) -> None:
        super().__init__()
        # 立刻设置窗口图标(左上角标题栏 + 任务栏)
        # 优先用 ico,失败则回退 jpg->QPixmap
        _root = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.abspath(__file__)))))
        _ico = os.path.join(_root, "config", "app_icon.ico")
        _jpg = r"D:\wenxj\6-software\STK\微信图片_20260930175545_675_2.jpg"
        if os.path.exists(_ico):
            self.setWindowIcon(QIcon(_ico))
        elif os.path.exists(_jpg):
            self.setWindowIcon(QIcon(QPixmap(_jpg)))

        self.cfg = cfg
        self.bus = bus
        self.registry = registry
        self.parser = parser
        self.pipeline = pipeline
        self._config_path = ""  # 由 app.py 设置,用于持久化

        self.setWindowTitle("卫星成像与数传任务规划仿真系统  ·  STK + Python C端")
        self.resize(1440, 860)

        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ---- 卫星类型 ----
        self._satellite_type = "optical"  # "optical"(光星) or "sar"(SAR星)

        # ---- 6 个视图(光星) ----
        self.stk_info_view = StkInfoView()
        self.target_io_view = TargetIoView()
        self.vis_compute_view = VisibilityComputeView()
        self.cmd_gen_view = CommandGenView()
        self.cmd_detail_view = CommandDetailView()
        self.cmp_result_view = ComparisonResultView()
        # ---- 6 个视图(SAR星) ----
        self.stk_info_view_sar = StkInfoView()
        self.target_io_view_sar = TargetIoView()
        self.vis_compute_view_sar = VisibilityComputeView()
        self.cmd_gen_view_sar = CommandGenView()
        self.cmd_detail_view_sar = CommandDetailView()
        self.cmp_result_view_sar = ComparisonResultView()
        # 保留旧视图(接收报文但不显示为 Tab,用于数据中转)
        self.msg_view = MessageView()
        self.pkt_view = PacketView()

        root.addWidget(self._build_header())
        root.addWidget(self._build_controlbar())

        # 每个主 tab 用 QStackedWidget 容纳两套页面(光星=index 0, SAR=index 1)
        self.tabs = QTabWidget()
        self._stack_stk_info = QStackedWidget()
        self._stack_stk_info.addWidget(self.stk_info_view)
        self._stack_stk_info.addWidget(self.stk_info_view_sar)
        self.tabs.addTab(self._stack_stk_info, "STK 报文信息")

        self._stack_target_io = QStackedWidget()
        self._stack_target_io.addWidget(self.target_io_view)
        self._stack_target_io.addWidget(self.target_io_view_sar)
        self.tabs.addTab(self._stack_target_io, "目标输入结果和解析")

        self._stack_vis_compute = QStackedWidget()
        self._stack_vis_compute.addWidget(self.vis_compute_view)
        self._stack_vis_compute.addWidget(self.vis_compute_view_sar)
        self.tabs.addTab(self._stack_vis_compute, "可见性计算结果")

        self._stack_cmd_gen = QStackedWidget()
        self._stack_cmd_gen.addWidget(self.cmd_gen_view)
        self._stack_cmd_gen.addWidget(self.cmd_gen_view_sar)
        self.tabs.addTab(self._stack_cmd_gen, "指令生成")

        self._stack_cmd_detail = QStackedWidget()
        self._stack_cmd_detail.addWidget(self.cmd_detail_view)
        self._stack_cmd_detail.addWidget(self.cmd_detail_view_sar)
        self.tabs.addTab(self._stack_cmd_detail, "指令明细")

        self._stack_cmp_result = QStackedWidget()
        self._stack_cmp_result.addWidget(self.cmp_result_view)
        self._stack_cmp_result.addWidget(self.cmp_result_view_sar)
        self.tabs.addTab(self._stack_cmp_result, "模板比对结果")

        root.addWidget(self.tabs, 1)
        self.setCentralWidget(central)

        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("系统就绪")

        # ---- 事件桥接 ----
        self.bridge = QtEventBridge(bus, self)
        # 报文 -> STK信息页(两套) + 报文流(隐藏,保留数据中转)
        self.bridge.parsed_packet.connect(self.stk_info_view.on_parsed_packet)
        self.bridge.parsed_packet.connect(self.stk_info_view_sar.on_parsed_packet)
        self.bridge.parsed_packet.connect(self.msg_view.on_parsed_packet)
        self.msg_view.packet_selected.connect(self.pkt_view.show_packet)
        # 可见性 -> 主窗口:算法库结果 → 构建 0F11/0F22/0F33/0F44 → 结果页
        self.bridge.visibility_result.connect(self._on_visibility_result)
        # 指令序列 -> 指令生成页 + 指令明细页(两套)
        self.bridge.command_sequence.connect(self.cmd_gen_view.on_command_sequence)
        self.bridge.command_sequence.connect(self.cmd_gen_view_sar.on_command_sequence)
        self.bridge.command_sequence.connect(self.cmd_detail_view.on_command_sequence)
        self.bridge.command_sequence.connect(self.cmd_detail_view_sar.on_command_sequence)
        # 缓存最新指令序列,供「开始比对」按钮触发重算
        self._last_cmd_seq = None
        self.bridge.command_sequence.connect(self._on_command_sequence)
        # 双击指令生成页行 -> 跳转指令明细页(两套都连接)
        self.cmd_gen_view.block_selected.connect(self._on_block_selected)
        self.cmd_gen_view_sar.block_selected.connect(self._on_block_selected)
        # 比对结果 -> 比对结果页(两套)
        self.bridge.comparison_result.connect(self.cmp_result_view.on_comparison)
        self.bridge.comparison_result.connect(self.cmp_result_view_sar.on_comparison)
        # 「开始比对」按钮 -> 手动重算模板比对(两套)
        self.cmp_result_view.compare_requested.connect(self._on_compare_requested)
        self.cmp_result_view_sar.compare_requested.connect(self._on_compare_requested)
        self.bridge.start()

        # ---- workers ----
        self.socket_worker = SocketWorker(
            cfg.transport.host, cfg.transport.port, cfg.transport.frame, self)
        self.socket_worker.frame_ready.connect(
            lambda fr: bus.publish(Topics.RAW_FRAME, fr))
        self.socket_worker.connection_changed.connect(self.statusBar().showMessage)
        self.stk_worker = StkWorker(cfg.stk, cfg.mode, registry, self)
        self.stk_worker.status.connect(self.statusBar().showMessage)
        self.stk_worker.error.connect(self._on_error)
        self.stk_worker.targets_ready.connect(self._on_targets_ready)
        self.stk_worker.targets_ready.connect(
            self.stk_info_view.on_targets_ready)
        self.stk_worker.targets_ready.connect(
            self.stk_info_view_sar.on_targets_ready)
        # 目标输入解析页只接收成像目标(不含地面站 _)(两套)
        self.stk_worker.targets_ready.connect(
            lambda ts: self.target_io_view.on_targets_ready(
                [t for t in ts if "_" not in t.id]))
        self.stk_worker.targets_ready.connect(
            lambda ts: self.target_io_view_sar.on_targets_ready(
                [t for t in ts if "_" not in t.id]))
        # 地面站 → 0C15 数传站址资源页(两套)
        self.stk_worker.targets_ready.connect(
            lambda ts: self.target_io_view.on_ground_stations_ready(
                [t for t in ts if "_" in t.id]))
        self.stk_worker.targets_ready.connect(
            lambda ts: self.target_io_view_sar.on_ground_stations_ready(
                [t for t in ts if "_" in t.id]))
        self.stk_worker.frame_ready.connect(self._on_first_frame)
        self.stk_worker.frame_ready.connect(
            lambda fr: bus.publish(Topics.RAW_FRAME, fr))
        # 缓存 STK 轨道帧(A012/A002),供「计算可见性」DLL 报文驱动输入
        self._orbit_frames: list[bytes] = []
        self.stk_worker.frame_ready.connect(self._cache_orbit_frame)
        self.stk_worker.targets_ready.connect(
            lambda ts: bus.publish(Topics.TARGET_SET, ts))

        # ---- 算法库路径初始化(显示实际加载后端:.dll/.lib) ----
        dll_path = cfg.algorithm.visibility_dll
        if dll_path:
            backend = "dll"
            algo = getattr(self.pipeline, "visibility_algo", None)
            dll_obj = getattr(algo, "_dll", None)
            if dll_obj is not None:
                backend = getattr(dll_obj, "backend", "dll")
            self._update_dll_label(dll_path, backend)

        # ---- 指令模板路径初始化 ----
        self._template_path = cfg.command_template or ""
        if self._template_path:
            self._update_template_label(self._template_path)

        # ---- 数据包格式 xlsx 初始化 ----
        self._xlsx_path = cfg.packet_format_xlsx or ""
        if self._xlsx_path:
            self._update_xlsx_label(self._xlsx_path)
        # 上一次成功加载的数据包模板快照(用于模板差异识别报告)
        self._last_fmt_packets: dict[str, bytes] = {}

        # ---- 目标输入视图注入 builder(两套) ----
        from ..stk.packets import StkPacketBuilder
        self._pkt_builder = StkPacketBuilder(self.registry, self.parser)
        self.target_io_view.set_builder(self._pkt_builder)
        self.target_io_view_sar.set_builder(self._pkt_builder)
        # ---- 指令生成页注入可见性结果页 panel + 星时获取(两套) ----
        self.cmd_gen_view.set_plan_source(
            self.vis_compute_view.panel_0f11,
            self.vis_compute_view.panel_0f22)
        self.cmd_gen_view_sar.set_plan_source(
            self.vis_compute_view_sar.panel_0f11,
            self.vis_compute_view_sar.panel_0f22)
        self.cmd_gen_view.set_star_sec_provider(
            lambda: self._star_sec)
        self.cmd_gen_view_sar.set_star_sec_provider(
            lambda: self._star_sec)
        # 指令生成 → 缓存序列(供模板比对用)(两套)
        self.cmd_gen_view.command_generated.connect(self._on_command_sequence)
        self.cmd_gen_view_sar.command_generated.connect(self._on_command_sequence)
        # ---- 启动即按配置模板驱动指令生成页/指令明细页(两套) ----
        if self._template_path:
            self._push_block_defs(self._template_path)

        # ---- 加载上次会话缓存(6 页报文 hex) ----
        self._session_cache_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.dirname(os.path.abspath(__file__))))),
            "config", "last_session.json")
        self._load_session_cache()

        # ---- 星时状态(全局) ----
        from PySide6.QtCore import QTimer
        self._star_sec: float = 0.0          # 2009 历元秒
        self._star_mode: str = "local"       # "stk"(实时) 或 "local"(本地)
        self._star_running: bool = False     # 本地模式是否在走动
        self._speed: float = 1.0             # 时间倍数
        self._star_last_wall: float = 0.0    # 上一次 tick 的墙钟时间
        self._star_timer = QTimer(self)
        self._star_timer.setInterval(100)    # 100ms 一次
        self._star_timer.timeout.connect(self._on_star_tick)
        self._star_timer.start()
        # 0B01 页解析成功 → 同步主窗口星时并启动走动(两套)
        self.target_io_view.star_time_parsed.connect(
            self._on_0b01_star_time)
        self.target_io_view_sar.star_time_parsed.connect(
            self._on_0b01_star_time)
        # 初始星时:优先从 0B01 页面取(会话缓存已加载),为空则用默认
        star_base = self._get_local_star_base()
        self._star_sec = star_base
        self._refresh_star_displays()
        # 同步修改时间编辑框为当前星时(北京时间)
        try:
            bj_dt = STK_EPOCH_2009.replace(tzinfo=None) \
                + timedelta(seconds=float(star_base)) \
                + timedelta(hours=8)
            self._edit_star_time.setDateTime(bj_dt)
        except Exception:  # noqa: BLE001
            pass

        # ---- 两阶段规划上下文 ----
        # 阶段1(compute_initial)完成后设置,供 _on_star_tick 阶段2推进使用
        self._phase2_algo = None        # CtVisibilityAlgorithm 实例
        self._phase2_targets = None     # 目标列表
        self._phase2_algo_name = ""     # 算法类名(状态栏显示用)
        # DLL 规划输出累积缓存:类型 -> {(ptype,seq,pno): raw}。
        # 同一任务的 0F11 等会被 DLL 拆成多个包下发(每包一个目标的多条带),
        # 阶段1/阶段2统一在此去重累积,再合并到结果面板展示。
        self._dll_pkts: dict[int, dict[tuple, bytes]] = {}
        # 0F11/0F22 延迟显示控制:阶段1缓存但不在界面显示,
        # 星时走到成像前6分钟/数传前6分钟时才刷新到面板
        self._held_0f11_displayed = False
        self._held_0f22_displayed = False
        self._phase2_0f11_keys: list[int] = []   # 0F11关键点(成像开始-360s)
        self._phase2_0f22_keys: list[int] = []   # 0F22关键点(数传开始-360s)

    # ---------- 卫星类型切换 ----------

    @property
    def current_satellite_type(self) -> str:
        """当前卫星类型:'optical'(光星) 或 'sar'(SAR星)。"""
        return self._satellite_type

    @property
    def current_stk_info_view(self):
        return (self.stk_info_view if self._satellite_type == "optical"
                else self.stk_info_view_sar)

    @property
    def current_target_io_view(self):
        return (self.target_io_view if self._satellite_type == "optical"
                else self.target_io_view_sar)

    @property
    def current_vis_compute_view(self):
        return (self.vis_compute_view if self._satellite_type == "optical"
                else self.vis_compute_view_sar)

    @property
    def current_cmd_gen_view(self):
        return (self.cmd_gen_view if self._satellite_type == "optical"
                else self.cmd_gen_view_sar)

    @property
    def current_cmd_detail_view(self):
        return (self.cmd_detail_view if self._satellite_type == "optical"
                else self.cmd_detail_view_sar)

    @property
    def current_cmp_result_view(self):
        return (self.cmp_result_view if self._satellite_type == "optical"
                else self.cmp_result_view_sar)

    def _on_satellite_type_changed(self, idx: int) -> None:
        """切换卫星类型:光星(idx=0) / SAR星(idx=1),同步切换所有 QStackedWidget。"""
        self._satellite_type = "sar" if idx == 1 else "optical"
        for stack in (self._stack_stk_info, self._stack_target_io,
                      self._stack_vis_compute, self._stack_cmd_gen,
                      self._stack_cmd_detail, self._stack_cmp_result):
            stack.setCurrentIndex(idx)
        name = "SAR星" if self._satellite_type == "sar" else "光星"
        self.statusBar().showMessage(f"已切换到{name}")
        self._apply_sat_badge_color(idx)

    def _apply_sat_badge_color(self, idx: int) -> None:
        """根据卫星类型切换胶囊徽章配色:光星=金, SAR=银。"""
        if idx == 1:
            fg, bg = C.SILVER, C.SILVER_SOFT
        else:
            fg, bg = C.GOLD, C.GOLD_SOFT
        self._sat_badge.setStyleSheet(
            f"#SatBadge {{ background:{bg}; border:1px solid {fg};"
            f" border-radius:14px; }}"
            f"#SatBadge QComboBox {{ background:transparent; border:none;"
            f" color:{fg}; padding:2px 8px 2px 12px; font-size:12px;"
            f" font-weight:600; }}")

    def _on_import_data(self) -> None:
        """导入数据：选择 .xlsx/.xls 文件，按"报文标识+码字"格式解析填充。"""
        from ..core.xlsx_importer import XlsxImporter, XlsxImportError
        path, _ = QFileDialog.getOpenFileName(
            self, "导入数据", "",
            "Excel 文件 (*.xlsx *.xls);;所有文件 (*.*)")
        if not path:
            return

        # 1) 格式校验
        errors = XlsxImporter.validate(path)
        if errors:
            msg = "Excel 格式校验未通过:\n\n" + "\n".join(
                f"  {e}" for e in errors[:10])
            if len(errors) > 10:
                msg += f"\n  ... 共{len(errors)}处错误"
            QMessageBox.warning(self, "导入数据", msg)
            return

        # 2) 解析并填充
        try:
            stats = XlsxImporter.import_file(
                path, self.current_target_io_view)
        except XlsxImportError as exc:
            QMessageBox.critical(self, "导入数据", f"解析失败:{exc}")
            return

        # 3) 成功提示
        sat_name = "SAR星" if self._satellite_type == "sar" else "光星"
        fname = os.path.basename(path)
        lines = [f"导入{sat_name}数据成功:{fname}", ""]
        for k, v in sorted(stats.items()):
            lines.append(f"  {k}: {v}条报文")
        lines.append("")
        lines.append("是否查看格式说明?")
        ret = QMessageBox.question(
            self, "导入数据", "\n".join(lines),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if ret == QMessageBox.StandardButton.Yes:
            QMessageBox.information(
                self, "Excel 格式说明", XlsxImporter.format_description())

    # ---------- 星时管理 ----------

    def _bj_from_epoch(self, sec: float) -> str:
        """2009 历元秒 → 北京时间字符串。"""
        from datetime import timedelta
        try:
            dt = STK_EPOCH_2009.replace(tzinfo=None) \
                + timedelta(seconds=float(sec)) + timedelta(hours=8)
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:  # noqa: BLE001
            return "—"

    def _set_star_time(self, sec: float, mode: str = "local",
                       start_running: bool = False) -> None:
        """设置星时基准。mode='stk' 表示来自 STK 实时推流。"""
        self._star_sec = float(sec)
        self._star_mode = mode
        if mode == "stk":
            # STK 实时:由 STK 帧驱动,不启动本地自走
            self._star_running = False
        else:
            self._star_running = start_running
        self._star_last_wall = self._wall_now()
        self._refresh_star_displays()

    def _wall_now(self) -> float:
        """墙钟时间(秒,monotonic)。"""
        import time
        return time.monotonic()

    def _on_star_tick(self) -> None:
        """星时定时器:本地模式按倍数自走 + 阶段2延迟显示0F11/0F22。

        V2 DLL 在阶段1已将0F33/0F44/0F11/0F22全部产出。
        0F33/0F44在阶段1立即显示;0F11/0F22缓存,星时走到
        "成像开始前6分钟"/"数传开始前6分钟"时才刷新到面板。
        """
        if self._star_mode == "local" and self._star_running:
            now = self._wall_now()
            dt = now - self._star_last_wall
            self._star_sec += dt * self._speed
            self._star_last_wall = now
            self._refresh_star_displays()

            # 阶段2:检查星时是否到达0F11关键点(成像前6min)
            if not self._held_0f11_displayed and self._phase2_0f11_keys:
                t = int(self._star_sec)
                # 任一关键点到达即显示全部缓存的0F11
                if any(t >= kt for kt in self._phase2_0f11_keys):
                    # 推进DLL星时到关键点,触发其异步产出0F11
                    self._advance_dll_to_key(min(self._phase2_0f11_keys), t)
                    self._display_held_packets(0x0F11)
                    self._held_0f11_displayed = True
                    _log.info("阶段2:星时=%d(%s)到达0F11关键点,显示0F11",
                              t, self._bj_from_epoch(t))
                    # 自动生成成像指令
                    try:
                        self.current_cmd_gen_view.auto_generate(0x0F11)
                    except Exception:
                        pass

            # 阶段2:检查星时是否到达0F22关键点(数传前6min)
            if not self._held_0f22_displayed and self._phase2_0f22_keys:
                t = int(self._star_sec)
                if any(t >= kt for kt in self._phase2_0f22_keys):
                    # 推进DLL星时到关键点,触发其异步产出0F22
                    self._advance_dll_to_key(min(self._phase2_0f22_keys), t)
                    self._display_held_packets(0x0F22)
                    self._held_0f22_displayed = True
                    _log.info("阶段2:星时=%d(%s)到达0F22关键点,显示0F22",
                              t, self._bj_from_epoch(t))
                    # 自动生成数传指令
                    try:
                        self.current_cmd_gen_view.auto_generate(0x0F22)
                    except Exception:
                        pass

            # 全部显示完成 → 清除阶段2上下文
            if (self._held_0f11_displayed and
                    self._held_0f22_displayed and
                    self._phase2_algo is not None):
                self._phase2_algo = None
                self.statusBar().showMessage(
                    "阶段2完成:0F11/0F22已全部显示", 8000)

            # 仅有0F11关键点(无数传规划)时,0F11显示完即可清除
            if (self._held_0f11_displayed and
                    not self._phase2_0f22_keys and
                    self._phase2_algo is not None):
                self._phase2_algo = None
                self.statusBar().showMessage(
                    "阶段2完成:0F11已显示(无数传规划)", 8000)

    def _display_held_packets(self, ptype: int) -> None:
        """把阶段1缓存的0F11或0F22报文刷新到对应面板。"""
        from ..stk.packets import (parse_0f11, parse_0f22)
        parse_map = {0x0F11: parse_0f11, 0x0F22: parse_0f22}
        panel_map = {0x0F11: self.current_vis_compute_view.panel_0f11,
                     0x0F22: self.current_vis_compute_view.panel_0f22}
        list_key_map = {0x0F11: "targets", 0x0F22: "files"}
        count_key_map = {0x0F11: "target_count", 0x0F22: "file_count"}
        parse_fn = parse_map[ptype]
        panel = panel_map[ptype]
        list_key = list_key_map[ptype]
        count_key = count_key_map[ptype]
        info, n_pkt, n_rec = self._merge_dll_info(
            ptype, parse_fn, list_key, count_key)
        if info is not None:
            panel.load_info(info)
            names = {0x0F11: "0F11成像方案", 0x0F22: "0F22数传方案"}
            star_str = self._bj_from_epoch(self._star_sec)
            self.statusBar().showMessage(
                f"阶段2:{names[ptype]}已显示({n_pkt}包/{n_rec}条),"
                f"星时 {star_str}", 8000)

    def _advance_dll_to_key(self, key_time: int, current_t: int) -> None:
        """推进DLL星时到关键点,触发其异步产出0F11/0F22并并入缓存。

        0F11/0F22 由DLL在内部星时到达"成像/数传开始前6分钟"时异步产出。
        若阶段1未产出(初始星时离窗较远),需在阶段2主动推进DLL星时到
        关键点,产出的报文通过 _accumulate_dll 并入缓存,随后
        _display_held_packets 才能显示。
        """
        if self._phase2_algo is None:
            return
        try:
            push_to = max(key_time, current_t)
            _log.info("阶段2:推进DLL星时到%d(%s)触发规划包产出",
                      push_to, self._bj_from_epoch(push_to))
            step_result = self._phase2_algo.advance_star_time(push_to)
            if step_result.packets:
                self._accumulate_dll(step_result)
                _log.info("阶段2:DLL星时推进后新增 %s",
                          {f"0x{k:04X}": len(v)
                           for k, v in step_result.packets.items()})
        except Exception as e:  # noqa: BLE001
            _log.exception("阶段2推进DLL星时失败: %s", e)

    def _refresh_star_displays(self) -> None:
        """刷新全局星时显示(主窗口顶部)。"""
        text = self._bj_from_epoch(self._star_sec)
        self.lbl_star_time.setText(f"星时 {text}")

    def _on_speed_changed(self) -> None:
        """倍速下拉框变化。"""
        self._speed = float(self.cmb_speed.currentData() or 1)
        self.statusBar().showMessage(f"星时倍速: {self._speed:.0f}x", 3000)

    def _on_modify_star_time(self) -> None:
        """HeaderBar「修改时间」按钮:用编辑框时间覆盖星时并继续走。

        同时同步更新 0B01 页面的码字,使主窗口星时、0B01 页面显示、
        以及后续计算可见性使用的星时基准三者保持一致。
        """
        # 从 HeaderBar 的 QDateTimeEdit 取北京时间 → 2009 历元秒
        try:
            qdt = self._edit_star_time.dateTime()
            dt_bj = datetime(qdt.date().year(), qdt.date().month(),
                             qdt.date().day(), qdt.time().hour(),
                             qdt.time().minute(), qdt.time().second())
            dt_utc = dt_bj - timedelta(hours=8)
            dt_utc = dt_utc.replace(tzinfo=timezone.utc)
            sec = float((dt_utc - STK_EPOCH_2009).total_seconds())
        except Exception:  # noqa: BLE001
            self.statusBar().showMessage("时间格式无效", 3000)
            return
        # 先同步更新 0B01 页面码字(会触发回调更新 _star_sec 和显示)
        try:
            from ..stk.packets import serialize_0b01
            tsec = int(sec) & 0xFFFFFFFF
            tms = int(round((sec - int(sec)) * 1000)) & 0xFFFF
            raw = serialize_0b01({
                "packet_type": 0x0B01, "total_packets": 1,
                "sequence_no": 1, "cur_packet_no": 1,
                "cur_packet_len": 16,
                "time_seconds": tsec, "time_millis": tms,
            })
            self.current_target_io_view.set_0b01_raw(raw)
        except Exception:  # noqa: BLE001
            _log.warning("同步更新 0B01 页面码字失败")
        # 再设置主窗口星时并启动走动(覆盖回调里的 stop)
        self._set_star_time(sec, mode="local", start_running=True)
        self.statusBar().showMessage(
            f"星时已修改为 {self._bj_from_epoch(sec)} "
            f"(0B01 码字已同步更新)", 4000)

    def _on_0b01_star_time(self, sec: float) -> None:
        """0B01 页报文解析成功:同步主窗口星时并启动走动。"""
        self._star_sec = float(sec)
        self._star_mode = "local"
        self._star_running = True
        self._star_last_wall = self._wall_now()
        self._refresh_star_displays()

    def _get_local_star_base(self) -> float:
        """从 0B01 页面取星时基准(2009 历元秒)。

        若 0B01 页为空或 time_seconds 为 0,回退到默认星时
        2026-09-01 12:10:00(北京)。
        """
        info = self.current_target_io_view.get_0b01_info() or {}
        tsec = info.get("time_seconds")
        try:
            tsec = int(tsec or 0)
        except (TypeError, ValueError):
            tsec = 0
        if tsec > 0:
            tms = info.get("time_millis") or 0
            try:
                tms = int(tms)
            except (TypeError, ValueError):
                tms = 0
            return float(tsec) + tms / 1000.0
        # 回退:默认星时 2026-09-01 12:10:00(北京)
        return _default_star_sec()

    # ---------- 会话缓存 ----------

    def _load_session_cache(self) -> None:
        """从 config/last_session.json 加载上次会话的 6 页报文 hex。"""
        import json
        if not os.path.exists(self._session_cache_path):
            return
        try:
            with open(self._session_cache_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.target_io_view.set_all_hex(data)
            _log.info("会话缓存已加载: %s", self._session_cache_path)
        except Exception as e:  # noqa: BLE001
            _log.warning("加载会话缓存失败: %s", e)

    def _save_session_cache(self) -> None:
        """保存当前 6 页报文 hex 到 config/last_session.json。"""
        import json
        try:
            data = self.target_io_view.get_all_hex()
            with open(self._session_cache_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            _log.info("会话缓存已保存: %s", self._session_cache_path)
        except Exception as e:  # noqa: BLE001
            _log.warning("保存会话缓存失败: %s", e)

    # ---------- UI 构建 ----------

    def _build_header(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("HeaderBar")
        bar.setFixedHeight(56)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(16, 6, 16, 6)
        lay.setSpacing(10)

        # 卫星类型切换(胶囊徽章:光星金 / SAR银)
        self._sat_badge = QFrame()
        self._sat_badge.setObjectName("SatBadge")
        self._sat_badge.setFixedWidth(90)
        sat_lay = QHBoxLayout(self._sat_badge)
        sat_lay.setContentsMargins(0, 0, 0, 0)
        sat_lay.setSpacing(0)
        self.cmb_satellite_type = QComboBox()
        self.cmb_satellite_type.addItem("光星", "optical")
        self.cmb_satellite_type.addItem("SAR星", "sar")
        self.cmb_satellite_type.setCurrentIndex(0)
        self.cmb_satellite_type.currentIndexChanged.connect(
            self._on_satellite_type_changed)
        sat_lay.addWidget(self.cmb_satellite_type)
        lay.addWidget(self._sat_badge)
        self._apply_sat_badge_color(0)

        box = QVBoxLayout()
        box.setSpacing(0)
        title = QLabel("卫星成像与数传任务规划仿真系统")
        title.setObjectName("AppTitle")
        scenario = os.path.splitext(
            os.path.basename(self.cfg.stk.scenario_path))[0] or "未配置场景"
        subtitle = QLabel(
            f"STK 12 实时链路  ·  场景:{scenario}  ·  "
            f"节拍 {self.cfg.stk.step_seconds:.0f}s")
        subtitle.setObjectName("AppSubtitle")
        box.addWidget(title)
        box.addWidget(subtitle)
        lay.addLayout(box)
        lay.addStretch()

        # 算法库路径徽章
        self.lbl_dll = QLabel("算法库:未加载")
        self.lbl_dll.setObjectName("InfoChip")
        lay.addWidget(self.lbl_dll)

        # 指令模板路径徽章
        self.lbl_template = QLabel("指令模板:未加载")
        self.lbl_template.setObjectName("InfoChip")
        lay.addWidget(self.lbl_template)

        # 数据包格式徽章
        self.lbl_xlsx = QLabel("数据包格式:未加载")
        self.lbl_xlsx.setObjectName("InfoChip")
        lay.addWidget(self.lbl_xlsx)

        # STK 运行状态
        self.led = LedDot("idle")
        self.lbl_stk_state = QLabel("STK 未连接")
        self.lbl_stk_state.setStyleSheet(f"color:{C.FG_DIM}; font-size:11px;")
        lay.addWidget(self.led)
        lay.addWidget(self.lbl_stk_state)

        mode_text = "真实模式" if self.cfg.mode == "real" else "模拟模式"
        badge = QLabel(mode_text)
        badge.setObjectName("ModeBadge")
        badge.setStyleSheet(
            f"background:{C.ACCENT_SOFT if self.cfg.mode == 'real' else C.BG_PANEL_2};"
            f"color:{C.ACCENT if self.cfg.mode == 'real' else C.FG_DIM};"
            f"border:1px solid "
            f"{C.ACCENT_DEEP if self.cfg.mode == 'real' else C.BORDER};"
            "border-radius:10px; padding:2px 12px; font-size:11px; font-weight:600;")
        lay.addWidget(badge)

        # ---- 全局星时显示(蓝色高亮胶囊) ----
        self.lbl_star_time = QLabel("星时 —")
        self.lbl_star_time.setStyleSheet(
            f"color:#0a1428; background:{C.ACCENT};"
            f"font-size:15px; font-weight:800; font-family:Consolas, monospace;"
            f"padding:4px 14px; border-radius:8px; border:1px solid {C.ACCENT_DEEP};")
        self.lbl_star_time.setToolTip("当前星时(北京时间)")
        lay.addWidget(self.lbl_star_time)

        # 星时修改(北京时间)
        self._edit_star_time = QDateTimeEdit()
        self._edit_star_time.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        self._edit_star_time.setCalendarPopup(True)
        self._edit_star_time.setDateTime(DEFAULT_STAR_BJ)
        self._edit_star_time.setFixedWidth(162)
        lay.addWidget(self._edit_star_time)

        self.btn_modify_star_time = QPushButton("修改时间")
        self.btn_modify_star_time.setStyleSheet(
            f"QPushButton {{ background:{C.ACCENT}; color:#0a1428;"
            f" border:none; border-radius:6px; padding:4px 12px;"
            " font-size:11px; font-weight:600;}}"
            f"QPushButton:hover {{ background:{C.ACCENT_DEEP}; color:#fff; }}")
        self.btn_modify_star_time.setToolTip("修改后星时从该时刻起按倍速走动,并同步0B01页面")
        self.btn_modify_star_time.clicked.connect(self._on_modify_star_time)
        lay.addWidget(self.btn_modify_star_time)

        # 倍速下拉框
        self.cmb_speed = QComboBox()
        self.cmb_speed.setFixedWidth(78)
        for v in [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 15, 20, 25, 30, 40, 50, 60, 80, 100]:
            self.cmb_speed.addItem(f"{v}x", v)
        self.cmb_speed.setCurrentIndex(0)
        self.cmb_speed.currentIndexChanged.connect(self._on_speed_changed)
        lay.addWidget(self.cmb_speed)
        return bar

    def _build_controlbar(self) -> QWidget:
        """控制栏:流式布局,按钮自动换行,按功能分组。"""
        bar = QWidget()
        bar.setObjectName("ControlBar")
        lay = FlowLayout(bar, spacing=6)
        lay.setContentsMargins(16, 8, 16, 8)

        def _sep(text: str) -> QLabel:
            lbl = QLabel(text)
            lbl.setObjectName("GroupSep")
            return lbl

        def _gap() -> QWidget:
            w = QWidget()
            w.setFixedWidth(6)
            return w

        def _btn(text: str, tip: str = "", obj: str = "",
                 min_w: int = 60) -> QPushButton:
            b = QPushButton(text)
            b.setMinimumWidth(min_w)
            b.setFixedHeight(28)
            if tip:
                b.setToolTip(tip)
            if obj:
                b.setObjectName(obj)
            return b

        # ---- STK 控制组 ----
        lay.addWidget(_sep("STK 控制"))
        stk_text = (_BTN_START_REAL if self.cfg.mode == "real"
                    else _BTN_START_MOCK)
        self.btn_start_stk = _btn(stk_text, obj="Primary", min_w=140)
        self.btn_start_stk.clicked.connect(self._start_stk)
        lay.addWidget(self.btn_start_stk)

        self.btn_kill_stk = _btn("强制关闭", obj="Danger", min_w=80)
        self.btn_kill_stk.clicked.connect(self._force_kill_stk)
        lay.addWidget(self.btn_kill_stk)

        self.btn_reconnect = _btn("重连", min_w=60)
        self.btn_reconnect.clicked.connect(self._reconnect)
        lay.addWidget(self.btn_reconnect)

        self.btn_stk_output = _btn("STK 输出", min_w=80)
        self.btn_stk_output.clicked.connect(self._stk_output)
        lay.addWidget(self.btn_stk_output)

        lay.addWidget(_gap())

        # ---- 模式切换 ----
        lay.addWidget(_sep("模式"))
        self.cmb_mode = QComboBox()
        self.cmb_mode.addItem("手动操作", "manual")
        self.cmb_mode.addItem("自动推流", "stream")
        self.cmb_mode.setCurrentIndex(0)
        self.cmb_mode.setFixedWidth(104)
        self.cmb_mode.setFixedHeight(28)
        lay.addWidget(self.cmb_mode)

        lay.addWidget(_gap())

        # ---- 数据操作组 ----
        lay.addWidget(_sep("数据操作"))
        self.btn_fetch_targets = _btn("获取目标", min_w=80)
        self.btn_fetch_targets.clicked.connect(self._fetch_targets)
        lay.addWidget(self.btn_fetch_targets)

        self.btn_compute = _btn("计算可见性", obj="Primary", min_w=90)
        self.btn_compute.clicked.connect(self._compute_visibility)
        lay.addWidget(self.btn_compute)

        self.btn_import_data = _btn("导入数据", obj="SecondaryBtn", min_w=80)
        self.btn_import_data.clicked.connect(self._on_import_data)
        lay.addWidget(self.btn_import_data)

        self.cmb_clear = QComboBox()
        self.cmb_clear.addItem("清除数据 ▼")
        self.cmb_clear.addItem("全部清除")
        self.cmb_clear.addItem("当前页面清除")
        self.cmb_clear.setFixedWidth(120)
        self.cmb_clear.setFixedHeight(28)
        self.cmb_clear.currentIndexChanged.connect(self._on_clear_selected)
        lay.addWidget(self.cmb_clear)

        lay.addWidget(_gap())

        # ---- 配置组 ----
        lay.addWidget(_sep("配置"))
        self.btn_load_dll = _btn("算法库", min_w=70)
        self.btn_load_dll.clicked.connect(self._load_dll)
        lay.addWidget(self.btn_load_dll)

        self.btn_load_template = _btn("指令模板", min_w=80)
        self.btn_load_template.clicked.connect(self._load_template)
        lay.addWidget(self.btn_load_template)

        self.btn_load_xlsx = _btn("数据包格式", min_w=90)
        self.btn_load_xlsx.clicked.connect(self._load_xlsx)
        lay.addWidget(self.btn_load_xlsx)

        lay.addWidget(_gap())

        # ---- 工具组 ----
        lay.addWidget(_sep("工具"))
        self.btn_start_tcp = _btn("TCP", min_w=60)
        self.btn_start_tcp.clicked.connect(self._start_tcp)
        lay.addWidget(self.btn_start_tcp)

        self.btn_inject = _btn("注入测试", min_w=80)
        self.btn_inject.clicked.connect(self._inject_mock)
        lay.addWidget(self.btn_inject)

        # 导出下拉菜单
        self.btn_export = QToolButton()
        self.btn_export.setText("导出")
        self.btn_export.setMinimumWidth(70)
        self.btn_export.setFixedHeight(28)
        self.btn_export.setPopupMode(QToolButton.InstantPopup)
        export_menu = QMenu(self.btn_export)
        export_menu.setStyleSheet(
            f"QMenu {{ background:{C.BG_PANEL}; color:{C.FG};"
            f" border:1px solid {C.BORDER}; }}"
            f"QMenu::item:selected {{ background:{C.BG_TABLE_SEL}; }}")
        act_all = export_menu.addAction("全部导出(多Sheet)")
        act_current = export_menu.addAction("导出当前页")
        act_all.triggered.connect(self._export_all)
        act_current.triggered.connect(self._export_current)
        self.btn_export.setMenu(export_menu)
        lay.addWidget(self.btn_export)

        return bar

    # ---------- STK 状态灯 ----------

    def _set_stk_state(self, state: str, text: str) -> None:
        self.led.set_state(state)
        self.lbl_stk_state.setText(text)
        color = {"idle": C.FG_DIM, "wait": C.WARN,
                 "run": C.OK, "error": C.ERR}.get(state, C.FG_DIM)
        self.lbl_stk_state.setStyleSheet(
            f"color:{color}; font-size:11px; font-weight:600;")

    def _on_targets_ready(self, targets) -> None:
        self._set_stk_state("run", f"STK 推流中 · {len(targets)} 个地面目标")

    def _on_first_frame(self, _frame) -> None:
        if self.stk_worker.running:
            self._set_stk_state("run", "STK 推流中 · 实时数据")

    # ---------- 动作 ----------

    def _start_tcp(self) -> None:
        try:
            self.socket_worker.start()
            self.statusBar().showMessage(
                f"TCP 监听 {self.cfg.transport.host}:{self.cfg.transport.port}")
            self.btn_start_tcp.setEnabled(False)
            self.btn_start_tcp.setText("监听中…")
        except Exception as e:  # noqa: BLE001
            self._on_error(str(e))

    def _start_stk(self) -> None:
        if self.cfg.mode == "real":
            if self.stk_worker.running:
                self.btn_start_stk.setEnabled(False)
                self.stk_worker.stop()
                self.stk_worker.wait(10000)
                self._reset_start_button()
                self._set_stk_state("idle", "STK 已停止")
                return
            manual = self.cmb_mode.currentData() == "manual"
            self.stk_worker.start(
                scenario_path=self.cfg.stk.scenario_path,
                host=self.cfg.transport.host, port=self.cfg.transport.port,
                manual=manual)
            self.btn_start_stk.setText(_BTN_STOP)
            self.btn_start_stk.setObjectName("Danger")
            self._repolish(self.btn_start_stk)
            self._set_stk_state("wait", "STK 启动中,正在加载场景…")
        else:
            self.stk_worker.start(
                host=self.cfg.transport.host, port=self.cfg.transport.port)

    def _force_kill_stk(self) -> None:
        """强制关闭 STK 进程。"""
        reply = QMessageBox.question(
            self, "确认", "确定要强制关闭 STK 进程吗?\n"
            "未保存的场景数据可能丢失。",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        self.stk_worker.force_kill()
        self._reset_start_button()
        self._set_stk_state("idle", "STK 已强制关闭")
        self.statusBar().showMessage("STK 进程已强制终止")

    def _stk_output(self) -> None:
        """STK 输出:拉取 STK 场景目标+卫星快照,分发到各页面。

        1. 成像目标 → 3101 目标输入报文页
        2. 地面站 → 0C15 数传站址资源页
        3. 初始轨道时间 → 0B01 星时页(解析+星时标签走动)
        4. 位置速度 → A002 页
        5. 轨道六根数 → A012 页
        """
        if not self.stk_worker.running:
            self.statusBar().showMessage("请先启动 STK")
            return
        self.statusBar().showMessage("正在从 STK 输出目标+轨道数据…")
        self.stk_worker.fetch_targets()
        self.stk_worker.fetch_snapshot()

    def _fetch_targets(self) -> None:
        """手动拉取 STK 场景目标,更新报文信息和目标输入页。"""
        if not self.stk_worker.running:
            self.statusBar().showMessage("请先启动 STK")
            return
        self.statusBar().showMessage("正在从 STK 获取目标…")
        self.stk_worker.fetch_targets()

    def _compute_visibility(self) -> None:
        """计算可见性 — 两阶段报文驱动。

        每次点击完全重新初始化:清空所有结果面板、阶段2上下文、
        DLL重新DllInit、星时从0B01页面重新读取。
        """
        targets = self.current_target_io_view.get_current_targets()
        if not targets:
            self.statusBar().showMessage(
                "3101 页无目标,无法计算可见性(请在目标输入页加载/编辑目标)")
            return

        from ..algorithm.visibility import CtVisibilityAlgorithm
        algo = self.pipeline.visibility_algo
        algo_name = type(algo).__name__

        # ---- 真实 DLL 报文驱动路径 ----
        if isinstance(algo, CtVisibilityAlgorithm):
            task_raw = self.current_target_io_view.get_3101_raw()
            if not task_raw:
                self.statusBar().showMessage(
                    "3101 页报文为空,无法进行算法库规划计算")
                return
            link_raw = self.current_target_io_view.get_0c12_raw()
            station_raw = self.current_target_io_view.get_0c15_raw()
            storage_raw = self.current_target_io_view.get_0802_raw()
            # 保存会话缓存(报文hex),供下次重启加载
            self._save_session_cache()

            # ===== 完全重新初始化(不受上一次影响) =====
            # 1. 清空4个结果面板
            for panel in [self.current_vis_compute_view.panel_0f11,
                          self.current_vis_compute_view.panel_0f22,
                          self.current_vis_compute_view.panel_0f33,
                          self.current_vis_compute_view.panel_0f44]:
                panel.clear_data()
            # 2. 清空DLL累积缓存和阶段2上下文
            self._dll_pkts = {}
            self._held_0f11_displayed = False
            self._held_0f22_displayed = False
            self._phase2_0f11_keys = []
            self._phase2_0f22_keys = []
            self._phase2_algo = None
            self._phase2_targets = None
            # 3. 星时从0B01页面重新读取(不受上次修改影响)
            star_base = self._get_local_star_base()
            self._star_sec = star_base
            self._refresh_star_displays()
            try:
                bj_dt = STK_EPOCH_2009.replace(tzinfo=None) \
                    + timedelta(seconds=float(star_base)) \
                    + timedelta(hours=8)
                self._edit_star_time.setDateTime(bj_dt)
            except Exception:
                pass
            # 4. 轨道帧从页面重新读取
            sel_orbit = self.current_target_io_view.get_selected_orbit_raw()
            orbit_frames = (sel_orbit,) if sel_orbit else tuple(self._orbit_frames)

            # 启动星时走动(本地模式,倍速)
            self._set_star_time(star_base, mode="local", start_running=True)

            self.statusBar().showMessage(
                f"正在调用算法库({algo_name})阶段1:发送报文…")
            QApplication.processEvents()

            try:
                # 阶段1:发送输入 → 立即输出 0F33/0F44
                # compute_initial内部会reinit()重新DllInit
                plan = algo.compute_initial(
                    task_raw, link_bytes=link_raw,
                    station_bytes=station_raw,
                    storage_bytes=storage_raw,
                    orbit_frames=orbit_frames,
                    star_base_sec=int(star_base), step_delay_ms=20)
            except Exception as e:  # noqa: BLE001
                _log.exception("算法库阶段1失败")
                self.statusBar().showMessage(
                    f"算法库阶段1失败:{e}")
                return

            # 应用阶段1结果(0F33/0F44立即显示,0F11/0F22缓存待阶段2)
            self._apply_dll_phase1(plan, targets, algo_name)

            # 阶段2:星时走动时在 _on_star_tick 中推进(增量结果实时并入)
            self._phase2_algo = algo
            self._phase2_targets = targets
            self._phase2_algo_name = algo_name
            return

        # ---- Stub 回退路径(未加载 DLL):本地模拟 ----
        self.statusBar().showMessage(
            f"未加载算法库,使用本地模拟({algo_name})计算 {len(targets)} 个目标…")
        try:
            now_utc = datetime.now(timezone.utc)
            clock_count = int((now_utc - STK_EPOCH_2009).total_seconds())
            clock = SatelliteClock(epoch=STK_EPOCH_2009, current=now_utc,
                                   clock_count=clock_count)
            results = algo.compute(targets, [], clock)
        except Exception as e:  # noqa: BLE001
            _log.exception("本地模拟可见性计算失败")
            self.statusBar().showMessage(f"可见性计算失败:{e}")
            return
        self._on_visibility_result(results)
        self.statusBar().showMessage(
            f"可见性计算完成(本地模拟 {algo_name},未加载算法库,"
            f"{len(targets)} 个目标),结果已更新至「可见性计算结果」页",
            10000)

    def _on_plan_progress(self, step: int, total: int) -> None:
        """DLL 星时推进进度回调:刷新状态栏并保持 UI 响应。"""
        self.statusBar().showMessage(
            f"算法库报文驱动规划中…星时推进 {step}/{total} 步")
        QApplication.processEvents()

    def _apply_dll_plan(self, plan, targets, algo_name: str) -> None:
        """算法库报文驱动结果 → 0F11/0F22/0F33/0F44 子页 + 元任务窗校验。

        DLL 输出的原始报文直接解析装入对应子页——0F11 的全部参数
        (星上智能处理/压缩比/成像类型等)与输入 3101 报文保持一致,
        成像/机动时间由算法库在元任务时间窗内规划得出。
        """
        from ..algorithm.dll_plan import PLAN_OUTPUT_TYPES
        from ..stk.packets import (parse_0f11, parse_0f22,
                                   parse_0f33, parse_0f44)
        from .views.result_views import empty_0f22_info, empty_0f44_info
        from ..planning.result_builder import build_0f11, build_0f33
        try:
            info3101 = self.current_target_io_view.get_3101_info() or {}
            # 0F33/0F44 取第一条(输入后立即输出的反馈)
            # 0F11/0F22 取最后一条(星时推进到关键时间点后的最终方案)
            f33_raw = plan.first(0x0F33)
            f44_raw = plan.first(0x0F44)
            f11_raw = plan.last(0x0F11)
            f22_raw = plan.last(0x0F22)
            f11 = (parse_0f11(f11_raw) if f11_raw
                   else build_0f11(targets, [], plan_3101=info3101))
            f22 = (parse_0f22(f22_raw) if f22_raw
                   else empty_0f22_info())
            f33 = (parse_0f33(f33_raw) if f33_raw
                   else build_0f33(targets, [], sequence_no=1))
            f44 = (parse_0f44(f44_raw) if f44_raw
                   else empty_0f44_info())
            self.current_vis_compute_view.set_results(f11, f22, f33, f44)

            # 元任务时间窗匹配校验
            ok, bad = self._check_meta_window(f11, info3101)
            out_stat = " · ".join(
                f"0F{pt & 0xFF:02X}×{plan.count(pt)}"
                for pt in PLAN_OUTPUT_TYPES)
            base = (f"算法库({algo_name})报文驱动规划完成:"
                    f"{plan.n_inputs} 帧输入,星时推进 {plan.n_steps} 步,"
                    f"输出 {out_stat}")
            if ok + bad == 0:
                tail = ""
            else:
                tail = (f";成像/机动时间窗校验:{ok} 个目标在元任务窗内"
                        + (f",{bad} 个越窗!" if bad else " ✓"))
            self.statusBar().showMessage(base + tail, 20000)
            _log.info("DLL plan applied: %s%s", base, tail)
        except Exception as e:  # noqa: BLE001
            _log.exception("DLL 规划结果装配失败")
            self.statusBar().showMessage(f"规划结果装配失败:{e}")

    # ---- DLL 规划报文累积 / 合并 / 刷新(阶段1、阶段2共用)----

    @staticmethod
    def _pkt_dedup_key(raw: bytes) -> tuple:
        """报文去重键:(类型, 序列号, 当前包序号)。"""
        ptype = int.from_bytes(raw[0:2], "big")
        seq = int.from_bytes(raw[4:6], "big") if len(raw) >= 6 else 0
        pno = int.from_bytes(raw[6:8], "big") if len(raw) >= 8 else 1
        return (ptype, seq, pno)

    def _dll_panels_cfg(self) -> tuple:
        """(类型, 解析函数, 记录列表键, 计数字段, 面板)。"""
        from ..stk.packets import (parse_0f11, parse_0f22,
                                   parse_0f33, parse_0f44)
        v = self.current_vis_compute_view
        return (
            (0x0F11, parse_0f11, "targets", "target_count", v.panel_0f11),
            (0x0F22, parse_0f22, "files", "file_count", v.panel_0f22),
            (0x0F33, parse_0f33, "tasks", "task_count", v.panel_0f33),
            (0x0F44, parse_0f44, "tasks", "task_count", v.panel_0f44),
        )

    def _accumulate_dll(self, plan) -> set:
        """把 plan 中规划报文去重累积进缓存,返回本次新增的报文类型集合。"""
        new_types: set = set()
        for ptype in (0x0F11, 0x0F22, 0x0F33, 0x0F44):
            raws = (plan.packets or {}).get(ptype)
            if not raws:
                continue
            bucket = self._dll_pkts.setdefault(ptype, {})
            for raw in raws:
                key = self._pkt_dedup_key(raw)
                if key not in bucket:
                    bucket[key] = raw
                    new_types.add(ptype)
        return new_types

    def _merge_dll_info(self, ptype: int, parse_fn, list_key: str,
                        count_key: str):
        """合并缓存中某类型全部包为单个 info(固定区取首包,记录累加)。

        返回 (info, 包数, 记录数);无数据返回 (None, 0, 0)。
        """
        bucket = self._dll_pkts.get(ptype)
        if not bucket:
            return None, 0, 0
        base = None
        records: list = []
        for raw in bucket.values():
            info = parse_fn(raw)
            if base is None:
                base = dict(info)
            records.extend(info.get(list_key) or [])
        if base is None:
            return None, 0, 0
        base[list_key] = records
        if count_key:
            base[count_key] = len(records)
        return base, len(bucket), len(records)

    def _refresh_dll_panels(self, only: set | None = None) -> dict:
        """依据累积缓存合并刷新面板。

        only: 只刷新指定类型(如 {0x0F33, 0x0F44});None=刷新全部。
        """
        stats: dict[int, tuple] = {}
        for ptype, parse_fn, list_key, count_key, panel in self._dll_panels_cfg():
            if only is not None and ptype not in only:
                stats[ptype] = (0, 0)
                continue
            info, n_pkt, n_rec = self._merge_dll_info(
                ptype, parse_fn, list_key, count_key)
            if info is not None:
                panel.load_info(info)
            else:
                panel.clear_data()
            stats[ptype] = (n_pkt, n_rec)
        return stats

    def _apply_dll_phase1(self, plan, targets, algo_name: str) -> None:
        """阶段1:装入 DLL 真实输出。

        V2 DLL 实测:注入完整输入(0B01+轨道+3101+0C12)后 1~2 秒内,
        0F33、0F44、0F11、0F22 全部在阶段1一并异步产出。

        显示策略(按用户要求):
        - 0F33(成像反馈)、0F44(数传反馈) → 立即显示
        - 0F11(待执行成像) → 缓存,星时走到"成像开始前6分钟"时才显示
        - 0F22(待执行数传) → 缓存,星时走到"数传开始前6分钟"时才显示
        """
        from ..stk.packets import (parse_0f33, parse_0f44,
                                    F33_STATUS_IMAGING, F44_STATUS_IMAGING)
        try:
            self._dll_pkts = {}
            self._held_0f11_displayed = False
            self._held_0f22_displayed = False
            self._phase2_0f11_keys = []
            self._phase2_0f22_keys = []
            # 累积全部报文(含0F11/0F22)进缓存
            self._accumulate_dll(plan)

            # 只刷新0F33/0F44面板,0F11/0F22暂不显示
            for ptype, parse_fn, list_key, count_key, panel in \
                    self._dll_panels_cfg():
                if ptype in (0x0F33, 0x0F44):
                    info, n_pkt, n_rec = self._merge_dll_info(
                        ptype, parse_fn, list_key, count_key)
                    if info is not None:
                        panel.load_info(info)
                    else:
                        panel.clear_data()
                else:
                    # 0F11/0F22:清空面板(等阶段2再显示)
                    panel.clear_data()

            # 只取0F33/0F44的统计,不刷新0F11/0F22面板
            stats = self._refresh_dll_panels(only={0x0F33, 0x0F44})
            n33p, n33r = stats[0x0F33]
            n44p, n44r = stats[0x0F44]

            # 从0F33提取0F11关键点(成像开始前6分钟,仅status=0x00的目标)
            ok33 = vis33 = 0
            for raw in (self._dll_pkts.get(0x0F33) or {}).values():
                for t in (parse_0f33(raw).get("tasks") or []):
                    if int(t.get("window_start", 0) or 0) > 0 or \
                            int(t.get("window_end", 0) or 0) > 0:
                        vis33 += 1
                    if int(t.get("status", -1)) in F33_STATUS_IMAGING:
                        ok33 += 1
                        img_s = int(t.get("imaging_start", 0) or 0)
                        if img_s > 0:
                            kt = img_s - 360  # 成像前6分钟
                            self._phase2_0f11_keys.append(kt)
                            _log.info(
                                "阶段2:0F11关键点=%d(%s),"
                                "成像开始=%d(%s)",
                                kt, self._bj_from_epoch(kt),
                                img_s, self._bj_from_epoch(img_s))

            # 从0F44提取0F22关键点(数传开始前6分钟,仅status=0x00)
            ok44 = 0
            for raw in (self._dll_pkts.get(0x0F44) or {}).values():
                for t in (parse_0f44(raw).get("tasks") or []):
                    if int(t.get("status", -1)) in F44_STATUS_IMAGING:
                        ok44 += 1
                        dl_s = int(t.get("datalink_start", 0) or 0)
                        if dl_s > 0:
                            kt = dl_s - 360  # 数传前6分钟
                            self._phase2_0f22_keys.append(kt)
                            _log.info(
                                "阶段2:0F22关键点=%d(%s),"
                                "数传开始=%d(%s)",
                                kt, self._bj_from_epoch(kt),
                                dl_s, self._bj_from_epoch(dl_s))

            held_0f11 = len(self._dll_pkts.get(0x0F11, {}))
            held_0f22 = len(self._dll_pkts.get(0x0F22, {}))
            ts = datetime.now().strftime("%H:%M:%S")
            f33_msg = (f"0F33 反馈{n33r}条(规划成功{ok33})"
                       if n33r else "0F33 暂无反馈")
            f44_msg = (f"0F44 反馈{n44r}条(规划成功{ok44})"
                       if n44r else "0F44 暂无反馈")

            # ---- 4个页面底部调试信息行 ----
            self._set_panel_debug_msgs(n33r, ok33, n44r, ok44,
                                       held_0f11, held_0f22,
                                       vis33,
                                       len(self._phase2_0f11_keys),
                                       len(self._phase2_0f22_keys))

            self.current_vis_compute_view._lbl_summary.setText(
                f"阶段1完成 [{ts}] · {f33_msg} · {f44_msg} · "
                f"0F11待显示{held_0f11}包(星时到成像前6min) · "
                f"0F22待显示{held_0f22}包(星时到数传前6min)")
            self.statusBar().showMessage(
                f"算法库({algo_name})阶段1完成:{f33_msg};{f44_msg};"
                f"0F11/0F22将在星时走到关键时间点时显示", 12000)
            _log.info("阶段1应用:0F33 %d包/%d条(有窗%d,成功%d); "
                      "0F44 %d包/%d条(成功%d); "
                      "0F11缓存%d包(待阶段2显示); 0F22缓存%d包(待阶段2显示); "
                      "0F11关键点%d个, 0F22关键点%d个",
                      n33p, n33r, vis33, ok33,
                      n44p, n44r, ok44,
                      held_0f11, held_0f22,
                      len(self._phase2_0f11_keys),
                      len(self._phase2_0f22_keys))
        except Exception as e:  # noqa: BLE001
            _log.exception("DLL 阶段1结果装配失败")
            self.statusBar().showMessage(f"阶段1结果装配失败:{e}")

    def _set_panel_debug_msgs(self, n33r, ok33, n44r, ok44,
                              held_0f11, held_0f22,
                              vis33, n11_keys, n22_keys) -> None:
        """为4个结果页底部设置调试信息行,说明报文未出现的具体原因。"""
        v = self.current_vis_compute_view
        # 0F33 成像反馈
        if n33r == 0:
            v.panel_0f33.set_debug_message(
                "未收到0F33: DLL未返回成像反馈报文。可能原因:①3101任务报文未"
                "正确注入;②轨道帧(A012/A002)缺失;③DLL内部规划异常。"
            )
        elif ok33 == 0:
            v.panel_0f33.set_debug_message(
                f"收到0F33共{n33r}条,但全部规划失败(status≠0x00)。"
                f"有可见窗目标{vis33}个。需检查:目标时间窗是否在轨道覆盖范围内、"
                f"仰角是否满足、目标坐标是否正确。"
            )
        else:
            v.panel_0f33.set_debug_message(
                f"0F33正常:{n33r}条反馈,{ok33}条规划成功(status=0x00)。")

        # 0F44 数传反馈
        if n44r == 0:
            v.panel_0f44.set_debug_message(
                "未收到0F44: DLL未返回数传反馈报文。可能原因:①0C12链路/0C15站址"
                "报文未注入;②0802固存状态报文缺失或格式错误;③数传窗口时间与"
                "星时不匹配(DLL需星时进入数传窗口才产出0F44);④固存中无数传文件。"
            )
        elif ok44 == 0:
            v.panel_0f44.set_debug_message(
                f"收到0F44共{n44r}条,但全部规划失败(status≠0x00)。"
                f"需检查数传链路参数、站址坐标、固存文件号是否有效。"
            )
        else:
            v.panel_0f44.set_debug_message(
                f"0F44正常:{n44r}条反馈,{ok44}条规划成功(status=0x00)。")

        # 0F11 待执行成像
        if held_0f11 == 0:
            if ok33 == 0:
                v.panel_0f11.set_debug_message(
                    f"无0F11: 0F33中无规划成功目标(成功{ok33}条),DLL不生成0F11。"
                    f"0F11仅在目标成像规划成功(status=0x00)时产出。"
                )
            else:
                v.panel_0f11.set_debug_message(
                    f"0F11已缓存{held_0f11}包,待星时走到成像开始前6分钟时显示。"
                    f"0F11关键点{n11_keys}个。"
                )
        else:
            v.panel_0f11.set_debug_message(
                f"0F11已缓存{held_0f11}包,待星时走到成像开始前6分钟时显示。")

        # 0F22 待执行数传
        if held_0f22 == 0:
            if n44r == 0:
                v.panel_0f22.set_debug_message(
                    "无0F22: 0F44数传反馈未产出,DLL无法生成0F22数传方案。"
                    "0F22依赖0F44规划成功后,在星时走到数传开始前6分钟时产出。"
                )
            elif ok44 == 0:
                v.panel_0f22.set_debug_message(
                    f"无0F22: 0F44共{n44r}条但全部规划失败(成功{ok44}条),"
                    f"DLL不生成0F22。需检查数传链路/站址/固存参数。"
                )
            else:
                v.panel_0f22.set_debug_message(
                    f"0F22已缓存{held_0f22}包,待星时走到数传开始前6分钟时显示。"
                    f"0F22关键点{n22_keys}个。"
                )
        else:
            v.panel_0f22.set_debug_message(
                f"0F22已缓存{held_0f22}包,待星时走到数传开始前6分钟时显示。")

    def _apply_dll_phase2(self, plan) -> None:
        """阶段2:累积星时推进中 DLL 新增的规划包,去重后合并刷新各面板。"""
        names = {0x0F11: "0F11成像方案", 0x0F22: "0F22数传方案",
                 0x0F33: "0F33成像反馈", 0x0F44: "0F44数传反馈"}
        try:
            new_types = self._accumulate_dll(plan)
            if not new_types:
                return
            stats = self._refresh_dll_panels()
            parts = [f"{names[t]} 累计{stats[t][0]}包/{stats[t][1]}条"
                     for t in (0x0F11, 0x0F22, 0x0F33, 0x0F44)
                     if t in new_types]
            star_str = self._bj_from_epoch(self._star_sec)
            self.statusBar().showMessage(
                f"阶段2更新:{' · '.join(parts)},星时 {star_str}", 6000)
            _log.info("阶段2更新 %s, 星时=%s", parts, star_str)
        except Exception as e:  # noqa: BLE001
            _log.exception("阶段2结果应用失败")
            self.statusBar().showMessage(f"阶段2结果应用失败:{e}")

    @staticmethod
    def _check_meta_window(f11: dict, info3101: dict) -> tuple[int, int]:
        """校验 0F11 各目标机动/成像时间是否落在 3101 元任务时间窗内。

        返回 (窗内目标数, 越窗目标数)。
        """
        tmap: dict[int, tuple[int, int]] = {}
        for t in info3101.get("targets") or []:
            try:
                tid = int(t.get("target_id") or 0)
            except (TypeError, ValueError):
                tid = 0
            tmap[tid] = (int(t.get("meta_earliest") or 0),
                         int(t.get("meta_latest") or 0))
        ok = bad = 0
        for t in f11.get("targets") or []:
            try:
                tid = int(t.get("target_id") or 0)
            except (TypeError, ValueError):
                tid = 0
            win = tmap.get(tid)
            if not win or win[0] <= 0 or win[1] <= 0:
                continue
            lo, hi = win
            checks = [int(t.get("maneuver_start") or 0),
                      int(t.get("imaging_start") or 0),
                      int(t.get("imaging_end") or 0)]
            if all(lo <= v <= hi for v in checks if v > 0) \
                    and any(v > 0 for v in checks):
                ok += 1
            else:
                bad += 1
        return ok, bad

    def _cache_orbit_frame(self, frame) -> None:
        """缓存最近的 STK 轨道报文帧(A012 根数/A002 位置速度),供 DLL 规划输入。

        同时处理 0B01 星时帧:若 STK 在推流,切换到本地星时模式并启动走动,
        将 0B01/A012/A002 报文同步写入对应解析页面。
        """
        if not isinstance(frame, (bytes, bytearray)) or len(frame) < 10:
            return
        frame = bytes(frame)
        ptype = int.from_bytes(frame[0:2], "big")
        if ptype in (0xA012, 0xA002):
            self._orbit_frames = [
                f for f in self._orbit_frames
                if int.from_bytes(f[0:2], "big") != ptype]
            self._orbit_frames.append(frame)
            # 同步写入对应解析页面(两套)
            try:
                if ptype == 0xA012:
                    self.target_io_view.set_a012_raw(frame)
                    self.target_io_view_sar.set_a012_raw(frame)
                elif ptype == 0xA002:
                    self.target_io_view.set_a002_raw(frame)
                    self.target_io_view_sar.set_a002_raw(frame)
            except Exception:  # noqa: BLE001
                _log.warning("写入轨道解析页面失败")
        elif ptype == 0x0B01:
            from ..stk.packets import parse_0b01
            try:
                info = parse_0b01(frame)
                sec = float(info.get("time_seconds", 0)) \
                    + int(info.get("time_millis", 0)) / 1000.0
                # 写入 0B01 页面(触发解析+星时同步)(两套)
                self.target_io_view.set_0b01_raw(frame)
                self.target_io_view_sar.set_0b01_raw(frame)
                # STK 星时:切换到 local 模式并启动走动(一秒一秒走)
                self._set_star_time(sec, mode="local", start_running=True)
            except Exception:  # noqa: BLE001
                pass

    def _on_command_sequence(self, seq) -> None:
        """缓存最新指令序列,供「开始比对」按钮手动触发重算。"""
        self._last_cmd_seq = seq

    def _on_compare_requested(self) -> None:
        """「开始比对」按钮:用最新指令序列与默认模板重新比对。

        比对维度:码字格式、位置/偏移、解析数据合理性、指令条数、时间间隔。
        比对结果通过 on_comparison 刷新比对结果页。
        """
        seq = self._last_cmd_seq
        if seq is None:
            self.statusBar().showMessage("暂无指令序列,请先生成指令", 4000)
            return
        try:
            tmpl_name = self.pipeline.default_template
            cmp = self.pipeline.comparator.compare(seq, tmpl_name)
            self.current_cmp_result_view.on_comparison(cmp)
            self.statusBar().showMessage(
                f"模板比对完成:{cmp.target_id} · 模板 {tmpl_name} "
                f"· 匹配 {cmp.match_count} · 差异 {cmp.discrepancy_count}",
                5000)
        except Exception as e:  # noqa: BLE001
            _log.exception("手动模板比对失败")
            self.statusBar().showMessage(f"模板比对失败:{e}", 5000)

    def _on_visibility_result(self, results) -> None:
        """算法库可见性结果到达:取三页最新报文构建 0F11/0F22/0F33/0F44。

        目标取自 3101 页当前报文,链路/站址取自 0C12/0C15 页当前报文,
        窗口来自算法库(pipeline 中可见性算法)输出。
        """
        try:
            targets = self.current_target_io_view.get_current_targets()
            # 获取 3101 完整报文信息(固定区参数供 0F11 继承)
            plan_3101 = self.current_target_io_view.get_3101_info()
            links = ((self.current_target_io_view.get_0c12_info() or {})
                     .get("links")) or []
            stations = ((self.current_target_io_view.get_0c15_info() or {})
                        .get("stations")) or []
            if not isinstance(results, list):
                results = [results]
            windows = []
            for r in results:
                windows.extend(r.windows)
            res = build_all_results(targets, windows,
                                    links=links, stations=stations,
                                    plan_3101=plan_3101)
            self.current_vis_compute_view.set_results(
                res["f11"], res["f22"], res["f33"], res["f44"])
            img = sum(1 for w in windows if "_" not in str(w.target_id))
            self.statusBar().showMessage(
                f"可见性计算完成:可见窗口 {len(windows)} 个(成像 {img}),"
                f"0F11 规划 {res['f11']['target_count']} 个目标 · "
                f"0F33 反馈 {res['f33']['task_count']} 条,"
                f"结果已更新至「可见性计算结果」页", 10000)
        except Exception as e:  # noqa: BLE001
            _log.exception("构建规划结果失败")
            self.statusBar().showMessage(f"规划结果生成失败:{e}")

    def _on_block_selected(self, cmd) -> None:
        """指令生成页双击行 → 切到指令明细页 + 显示块详情。"""
        # 确保指令明细栈显示当前卫星对应的 view
        sar_idx = 1 if self._satellite_type == "sar" else 0
        self._stack_cmd_detail.setCurrentIndex(sar_idx)
        self.tabs.setCurrentWidget(self._stack_cmd_detail)
        self.current_cmd_detail_view.show_block_detail(cmd)

    def _reconnect(self) -> None:
        """重新连接 STK:停止当前连接后重新启动。"""
        if self.cfg.mode != "real":
            self.statusBar().showMessage("模拟模式无需重连")
            return
        self.statusBar().showMessage("正在重新连接 STK…")
        self._set_stk_state("wait", "重新连接中…")
        try:
            manual = self.cmb_mode.currentData() == "manual"
            self.stk_worker.reconnect(
                scenario_path=self.cfg.stk.scenario_path,
                host=self.cfg.transport.host, port=self.cfg.transport.port,
                manual=manual)
            self.btn_start_stk.setText(_BTN_STOP)
            self.btn_start_stk.setObjectName("Danger")
            self._repolish(self.btn_start_stk)
        except Exception as e:  # noqa: BLE001
            self._on_error(str(e))

    def _load_dll(self) -> None:
        """加载/切换算法库,即时替换 pipeline.visibility_algo。

        支持 .dll(动态库)与 .lib(静态库/导入库),按扩展名自动适配:
        - .dll            直接 ctypes 加载
        - .lib(导入库)    自动定位同目录配套 .dll
        - .lib(纯静态库)   用 MSVC 现场封装为转发 DLL 后加载(需 VS C++ 工具链)

        加载成功后,无论是 STK 启动还是本地计算,「计算可见性」都会走
        新加载的算法库;失败则保留旧算法实例并报错。
        """
        start_dir = self.cfg.algorithm.visibility_dll or os.getcwd()
        path, _ = QFileDialog.getOpenFileName(
            self, "选择算法库(.dll 或 .lib)", start_dir,
            "算法库 (*.dll *.lib);;动态库 (*.dll);;静态库 (*.lib);;所有文件 (*.*)")
        if not path:
            return
        try:
            from ..algorithm.loader import LibraryLoader
            from ..algorithm.signature import default_registry
            from ..algorithm.visibility import CtVisibilityAlgorithm
            reg = default_registry()   # DllInit/DllInput/DllOutput 真实签名
            deps = [d.strip() for d in
                    (self.cfg.algorithm.lib_extra_deps or "").split(";")
                    if d.strip()]
            dll = LibraryLoader(extra_deps=deps).load(path, reg)
            new_algo = CtVisibilityAlgorithm(dll)
            self.pipeline.visibility_algo = new_algo
        except Exception as e:  # noqa: BLE001
            _log.exception("加载算法库失败")
            self.statusBar().showMessage(f"算法库加载失败,保留旧实例:{e}")
            QMessageBox.critical(self, "加载失败",
                                 f"算法库加载失败:\n{e}\n\n已保留旧算法实例。")
            return
        self.cfg.algorithm.visibility_dll = path
        backend = getattr(dll, "backend", "dll")
        self._update_dll_label(path, backend)
        self._save_config()
        algo_name = type(self.pipeline.visibility_algo).__name__
        self.statusBar().showMessage(
            f"算法库已加载并即时生效({algo_name}, 来源:{LibraryLoader.backend_label(backend)})"
            f",可点击「计算可见性」")
        _log.info("algorithm library loaded and active: %s (%s, backend=%s)",
                  path, algo_name, backend)

    def _update_dll_label(self, path: str, backend: str = "dll") -> None:
        name = os.path.basename(path)
        tag = {"dll": "DLL", "import-lib": "LIB->DLL",
               "static-bridge": "LIB->DLL(封装)"}.get(backend, backend)
        self.lbl_dll.setText(f"算法库:[{tag}] {name}")
        self.lbl_dll.setProperty("loaded", True)
        self.lbl_dll.setToolTip(f"{path}\n加载方式:{tag}")
        self._repolish(self.lbl_dll)

    def _load_template(self) -> None:
        """加载指令模板 xlsm 文件。"""
        start_dir = self._template_path or os.getcwd()
        path, _ = QFileDialog.getOpenFileName(
            self, "选择指令模板", start_dir,
            "Excel 文件 (*.xlsm *.xlsx);;所有文件 (*.*)")
        if not path:
            return
        self._template_path = path
        self.cfg.command_template = path
        self._update_template_label(path)
        self._save_config()
        # 重新加载模板到 comparator
        try:
            from ..planning.templates import load_real_templates
            templates = load_real_templates(path)
            # 清空旧模板后重新注册
            self.pipeline._comparator._templates.clear()  # noqa: SLF001
            for name, tmpl in templates.items():
                self.pipeline._comparator.register(tmpl)  # noqa: SLF001
            # 解析数据块定义 -> 推送给指令生成页/指令明细页(两套)
            n_defs = self._push_block_defs(path)
            self.statusBar().showMessage(
                f"已加载指令模板:{os.path.basename(path)} "
                f"({len(templates)} 个模板, {n_defs} 个块定义)")
            _log.info("loaded %d templates from %s", len(templates), path)
        except Exception as e:  # noqa: BLE001
            self.statusBar().showMessage(f"模板加载失败: {e}")
            QMessageBox.warning(self, "模板加载失败", str(e))

    def _update_template_label(self, path: str) -> None:
        name = os.path.basename(path)
        self.lbl_template.setText(f"指令模板:{name}")
        self.lbl_template.setProperty("loaded", True)
        self._repolish(self.lbl_template)

    def _push_block_defs(self, path: str) -> int:
        """解析指令模板的数据块定义,推送给两套指令生成页/指令明细页。

        返回已推送的块类型数量;解析失败返回 0(相关页面回退代码定义)。
        """
        try:
            from ..planning.template_loader import load_block_defs_by_kind
            block_defs = load_block_defs_by_kind(path)
        except Exception as e:  # noqa: BLE001
            _log.warning("block defs load failed: %s", e)
            return 0
        for view in (self.cmd_gen_view, self.cmd_gen_view_sar):
            view.set_block_defs(block_defs)
        for view in (self.cmd_detail_view, self.cmd_detail_view_sar):
            view.set_block_defs(block_defs)
        _log.info("pushed %d block defs from %s", len(block_defs), path)
        return len(block_defs)

    def _load_xlsx(self) -> None:
        """加载数据包格式 xlsx 文件,并驱动当前卫星类型的输入解析页。"""
        start_dir = self._xlsx_path or os.getcwd()
        path, _ = QFileDialog.getOpenFileName(
            self, "选择数据包格式文件", start_dir,
            "Excel 文件 (*.xlsx *.xlsm);;所有文件 (*.*)")
        if not path:
            return
        self._xlsx_path = path
        self.cfg.packet_format_xlsx = path
        self._update_xlsx_label(path)
        self._save_config()
        self.statusBar().showMessage(
            f"已加载数据包格式:{os.path.basename(path)}")
        self._apply_packet_format(path)

    def _apply_packet_format(self, path: str) -> None:
        """解析数据包格式 xlsx,按 sheet 构造各报文 hex 并填充输入解析页。

        复用 xlsx_importer 的解析/填充路径(与手动导入一致),填充到当前
        卫星类型的「目标输入结果和解析」页。校验体系:
        - 构造期诊断(缺sheet/构造失败/字段缺hex/记录不齐)→ 弹窗告警
        - 报文级 sanity(3101目标数错位/包长不符/定长报文长度)→ 弹窗告警
        - 声明包长不符等软提示 → 状态栏
        - 与上一模板的逐报文内容差异对比 → 状态栏明确报告
        """
        try:
            from ..core.packet_format_loader import load_packets_with_diag
            packets, hard_warns, soft_warns = load_packets_with_diag(path)
        except Exception as e:  # noqa: BLE001
            _log.exception("packet format load failed")
            self.statusBar().showMessage(f"数据包格式加载失败:{e}")
            QMessageBox.warning(self, "数据包格式加载失败", str(e))
            return
        if not packets:
            msg = ("该文件未包含任何已知报文 sheet(星时/轨道数据/轨道根数/"
                   "常规管控成像任务_点目标/数传链路资源/数传站址资源/固存状态信息)")
            if hard_warns:
                msg = "全部sheet构造失败:\n" + "\n".join(hard_warns)
            self.statusBar().showMessage("数据包格式加载失败:未解析出任何已知报文")
            QMessageBox.warning(self, "数据包格式加载失败", msg)
            return

        from ..core.xlsx_importer import XlsxImporter, _PACKET_MAP
        view = self.current_target_io_view
        parsed: dict[str, list] = {}
        errors: list[str] = []
        for code, raw in packets.items():
            entry = _PACKET_MAP.get(code)
            if entry is None:
                continue
            parse_fn = entry[0]
            try:
                parsed.setdefault(code, []).append(parse_fn(raw))
            except Exception as e:  # noqa: BLE001
                errors.append(f"{code} 解析失败({e})")
        # 丢弃未成功解析的空条目(仅 setdefault 建键但未 append 的情况)
        parsed = {k: v for k, v in parsed.items() if v}
        hard_warns.extend(errors)

        # ---- 报文级 sanity 校验(能解析但内容错位/长度不符) ----
        for code, infos in parsed.items():
            info = infos[-1]
            raw = packets.get(code, b"")
            hard_warns.extend(
                f"{code}: {x}" for x in XlsxImporter.packet_warnings(code, info, raw))

        # ---- 模板差异识别(与上一次加载的数据包模板逐报文对比) ----
        prev = getattr(self, "_last_fmt_packets", None)
        diff_parts: list[str] = []
        if prev is not None:
            changed, added, removed = [], [], []
            for code in sorted(set(prev) | set(packets)):
                old, new = prev.get(code), packets.get(code)
                if old is not None and new is not None and old != new:
                    n_new = self._fmt_3101_brief(new, code)
                    changed.append(
                        f"{code} {len(old)}B→{len(new)}B{n_new}")
                elif old is None and new is not None:
                    added.append(f"{code}新增({len(new)}B)")
                elif old is not None and new is None:
                    removed.append(f"{code}移除")
            if changed:
                diff_parts.append("内容变化: " + "、".join(changed))
            if added:
                diff_parts.append("新增: " + "、".join(added))
            if removed:
                diff_parts.append("移除: " + "、".join(removed))
            if not diff_parts:
                diff_parts.append("与上一模板内容完全一致")
        self._last_fmt_packets = dict(packets)

        if not parsed:
            msg = "所有报文均解析失败:" + ";".join(errors)
            self.statusBar().showMessage(msg)
            QMessageBox.warning(self, "数据包格式加载失败", msg)
            return

        # 与 xlsx_importer 相同的填充路径(3101 目标列表 + 其余 Hex 面板)
        if parsed.get("3101"):
            XlsxImporter._fill_3101(view, parsed["3101"])
        for key, panel_attr in (("0C12", "panel_0c12"),
                                ("0C15", "panel_0c15"),
                                ("0802", "panel_0802"),
                                ("0B01", "panel_0b01"),
                                ("A002", "panel_a002"),
                                ("A012", "panel_a012")):
            if parsed.get(key):
                XlsxImporter._fill_hex_panel(view, panel_attr, parsed[key])

        codes = "、".join(sorted(parsed.keys()))
        sat = "光星" if self._satellite_type == "optical" else "SAR星"
        msg = (f"数据包格式已驱动 {sat} 输入解析页:{codes}"
               f"({len(parsed)} 类报文)")
        if diff_parts:
            msg += ";" + ";".join(diff_parts)
        if soft_warns:
            msg += ";提示:" + ";".join(soft_warns)
        self.statusBar().showMessage(msg)
        _log.info("applied packet format to %s view: %s (diff: %s)",
                  sat, codes, ";".join(diff_parts) or "首次加载")

        # ---- 硬异常集中弹窗(影响数据正确性,必须让用户知道) ----
        if hard_warns:
            failed = [c for c in packets if c not in parsed]
            head = (f"数据包格式已加载,但发现 {len(hard_warns)} 处异常"
                    f"(未填充报文:{'、'.join(failed) if failed else '无'}):")
            QMessageBox.warning(self, "报文格式校验告警",
                                head + "\n\n" + "\n".join(hard_warns))

    @staticmethod
    def _fmt_3101_brief(raw: bytes, code: str) -> str:
        """差异报告用的 3101 简要信息(目标数)。"""
        if code != "3101" or len(raw) < 46:
            return ""
        try:
            from ..stk.packets import parse_3101
            return f"(目标数{parse_3101(raw).get('target_count')})"
        except Exception:  # noqa: BLE001
            return ""

    def _update_xlsx_label(self, path: str) -> None:
        name = os.path.basename(path)
        self.lbl_xlsx.setText(f"数据包格式:{name}")
        self.lbl_xlsx.setProperty("loaded", True)
        self._repolish(self.lbl_xlsx)

    def _save_config(self) -> None:
        """将配置持久化到 YAML 文件。"""
        if not self._config_path:
            return
        try:
            save_config(self.cfg, self._config_path)
            _log.info("config saved to %s", self._config_path)
        except Exception as e:  # noqa: BLE001
            _log.warning("save config failed: %s", e)

    def _export_current(self) -> None:
        """导出当前 Tab 的数据(excel/txt/json)。"""
        idx = self.tabs.currentIndex()
        stack = self.tabs.widget(idx)
        name = self.tabs.tabText(idx)
        widget = stack.currentWidget() if isinstance(stack, QStackedWidget) else stack
        if not hasattr(widget, "export_data"):
            self.statusBar().showMessage(f"'{name}' 页无数据可导出")
            return
        result = widget.export_data()
        if not result:
            self.statusBar().showMessage(f"'{name}' 页无数据可导出")
            return
        label, rows = result
        if not rows:
            self.statusBar().showMessage(f"'{name}' 页无数据")
            return
        columns = list(rows[0].keys())
        ok = ExportUtils.export_dialog(self, rows, columns, f"{name}_导出")
        if ok:
            self.statusBar().showMessage(f"'{name}' 导出成功")
        else:
            self.statusBar().showMessage(f"'{name}' 导出失败或已取消")

    def _export_all(self) -> None:
        """全部导出:每个 Tab 一个 Sheet。"""
        pages = []
        for i in range(self.tabs.count()):
            stack = self.tabs.widget(i)
            name = self.tabs.tabText(i)
            widget = stack.currentWidget() if isinstance(stack, QStackedWidget) else stack
            if hasattr(widget, "export_data"):
                result = widget.export_data()
                if result and result[1]:
                    pages.append((name, result[1]))
        if not pages:
            self.statusBar().showMessage("所有页面均无数据")
            return
        ok = ExportUtils.export_all_dialog(self, pages, "全部导出")
        if ok:
            self.statusBar().showMessage(
                f"全部导出成功:{len(pages)} 个 Sheet")
        else:
            self.statusBar().showMessage("全部导出失败或已取消")

    def _clear_all(self) -> None:
        """清除所有页面数据(两套 view 都清除)。"""
        reply = QMessageBox.question(
            self, "确认清除", "确定要清除所有页面的数据吗?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        for i in range(self.tabs.count()):
            stack = self.tabs.widget(i)
            if isinstance(stack, QStackedWidget):
                for j in range(stack.count()):
                    w = stack.widget(j)
                    if hasattr(w, "clear_data"):
                        w.clear_data()
            elif hasattr(stack, "clear_data"):
                stack.clear_data()
        self.statusBar().showMessage("所有页面数据已清除")

    def _on_clear_selected(self, idx: int) -> None:
        """清除数据下拉框选择处理。

        idx=0 为标题项(占位),idx=1 全部清除,idx=2 当前页面清除。
        执行后重置回标题项,避免重复触发。
        """
        if idx == 0:
            return  # 标题项
        if idx == 1:
            self._clear_all()
        elif idx == 2:
            self._clear_current_page()
        # 重置回标题项(blockSignals 防止递归触发)
        self.cmb_clear.blockSignals(True)
        self.cmb_clear.setCurrentIndex(0)
        self.cmb_clear.blockSignals(False)

    def _clear_current_page(self) -> None:
        """清除当前页面数据。"""
        stack = self.tabs.currentWidget()
        widget = stack.currentWidget() if isinstance(stack, QStackedWidget) else stack
        if hasattr(widget, "clear_data"):
            reply = QMessageBox.question(
                self, "确认清除",
                f"确定要清除当前页面「{self.tabs.tabText(self.tabs.currentIndex())}」的数据吗?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply == QMessageBox.Yes:
                widget.clear_data()
                self.statusBar().showMessage("当前页面数据已清除")
        else:
            self.statusBar().showMessage("当前页面不支持清除")

    def _reset_start_button(self) -> None:
        self.btn_start_stk.setEnabled(True)
        self.btn_start_stk.setText(
            _BTN_START_REAL if self.cfg.mode == "real" else _BTN_START_MOCK)
        self.btn_start_stk.setObjectName("Primary")
        self._repolish(self.btn_start_stk)

    @staticmethod
    def _repolish(btn: QPushButton) -> None:
        btn.style().unpolish(btn)
        btn.style().polish(btn)

    def _inject_mock(self) -> None:
        """注入场景起始时刻 3 帧真实数据自检链路。"""
        try:
            from ..stk.packets import StkPacketBuilder, parse_utcg
            builder = StkPacketBuilder(self.registry, self.parser)
            t0 = parse_utcg("1 Oct 2026 02:00:00.000")
            frames = [
                builder.time_frame(t0),
                builder.elements_frame(
                    t0, 6896.56897, 0.0067, 45.0, 14.03, 59.593, 48.286),
                builder.orbit_data_frame(
                    t0,
                    (7.1893, 5099.96, 4596.98),
                    (0.0, 0.0, 0.0),
                    (-3225.15863166686,
                     3940.9931295641304,
                     4605.30397169509),
                    (0.0, 0.0, 0.0)),
            ]
            for f in frames:
                self.bus.publish(Topics.RAW_FRAME, f)
            self.statusBar().showMessage(
                f"已注入 {len(frames)} 帧测试报文(场景起始时刻真实数据)")
        except Exception as e:  # noqa: BLE001
            self._on_error(str(e))

    def _on_error(self, msg: str) -> None:
        _log.error("UI error: %s", msg)
        self.statusBar().showMessage(f"错误: {msg}")
        if self.cfg.mode == "real":
            self._set_stk_state("error", "STK 异常")
            if not self.stk_worker.running:
                self._reset_start_button()
        QMessageBox.warning(self, "错误", msg)

    def closeEvent(self, event) -> None:
        try:
            self.pipeline.stop()
            self.bridge.stop()
            self.socket_worker.stop()
            self.stk_worker.stop()
            self.stk_worker.wait(15000)
        finally:
            super().closeEvent(event)
