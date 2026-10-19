"""目标输入报文(0x3101)解析视图:Hex 横排 + 可编辑解析表。

严格按 Excel 数据包格式定义(常规管控成像任务_点目标 sheet)解析,
每个目标记录 87B,包含 8 个角点经纬度、前/后视俯仰角、成像时长。

核心交互:
- 编辑任务表/目标表任意值 → 自动重建 3101 报文并刷新 Hex,带修改提示
- 目标列表支持整行删除(按钮+右键菜单),报文同步更新
- 表格占满页面空间,QTableView 内置滚动
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                               QHeaderView, QFrame, QTextEdit,
                               QPushButton, QMenu, QTabWidget, QComboBox,
                               QAbstractItemView)

from ..theme import C, FONT_MONO
from ..table_models import GenericTableModel
from ..widgets import SectionTitle, BadgeDelegate, MonoDelegate, DataTableView
from ...models.target import TargetPoint
from ...stk.packets import (StkPacketBuilder, parse_3101, parse_utcg,
                            serialize_3101)
from ...models.orbit import STK_EPOCH_2009
from .packet_panel import hex_text_to_bytes

_log = logging.getLogger(__name__)

# 任务固定区字段:(字段名, 中文标签, 单位, 备注)
_TASK_FIELDS = [
    ("packet_type", "包类型", "", "0x3101"),
    ("total_packets", "总包数量", "", "从1开始计"),
    ("sequence_no", "序列号", "", "全局递增,每发送一帧加1"),
    ("cur_packet_no", "当前包序号", "", "从1开始计"),
    ("cur_packet_len", "当前包长度", "字节", "46+87*N"),
    ("task_id", "任务编号", "", "地面上注"),
    ("task_earliest", "任务最早开始时间", "UTC秒", "自2009-01-01起的整秒"),
    ("task_latest", "任务最晚结束时间", "UTC秒", "自2009-01-01起的整秒"),
    ("priority", "任务优先级", "", "[0,255],数值越小优先级越高"),
    ("payload_priority", "载荷数据回传优先级", "", "01:I级;02:II级(默认);03:III级;04:IV级;05:V级"),
    ("imaging_type", "成像任务类型", "", "11-点目标;12-多角度;13-多条带拼接;14-连续条带;15-立体"),
    ("compression", "成像数据压缩比", "", "0-直通;1-无损;2-2:1;4-4:1(默认);8-8:1"),
    ("datalink_type", "数传任务类型", "", "21-常规回放;212-指定回传;213-星上自主数传1;214-自主数传2;215-地面插件"),
    ("return_data_type", "回传数据类型", "", "0-原始;1-处理数据(默认);2-原始+处理"),
    ("datalink_rate", "数传速率", "", "b7/b6:左右旋通道;b5~b0:速率(1=450M,2=300M,3=150M,4=75M,5=60M,6=50M)"),
    ("encryption", "明密状态", "", "0-密态;1-明态"),
    ("periodic_flag", "周期任务标识", "", "0:否(默认);1:是"),
    ("periodic_count", "周期任务成像次数", "", "255-逢过必拍;其他=成像次数,默认0"),
    ("periodic_min_interval", "周期任务最小间隔时间", "s", "默认0"),
    ("periodic_max_interval", "周期任务最大间隔时间", "s", "默认0"),
    ("onboard_processing", "星上智能处理开关", "", "1:开(默认);0:关"),
    ("cut_size", "切块大小", "", "01-1km;02-2km;03-3km;04-4km;05-5km(默认);06-6km"),
    ("cut_compression_vis", "切块压缩比_可见光", "", "0-直通;1-无损;2-2:1;4-4:1;8-8:1(默认)"),
    ("cut_compression_ir", "切块压缩比_红外", "", "0-直通;1-无损;2-2:1;4-4:1;8-8:1(默认)"),
    ("output_product_level", "星上处理输出产品级别", "", "0-0级;1-1级(辐射校正);2-2级(辐射+几何校正)"),
    ("target_count", "目标数量", "", "点/区域目标循环,11/13/14/15d 时填写"),
]

_TIME_FIELDS = {"task_earliest", "task_latest"}
# 派生字段(由系统计算,不允许用户直接改)
_DERIVED_FIELDS = {"packet_type", "cur_packet_len", "target_count"}

_TARGET_TYPE_MAP = {0: "点目标", 1: "区域目标", 2: "远洋舰船",
                    3: "港口舰船", 4: "机场飞机", 5: "DD阵地车辆",
                    6: "其他自定义"}
_TARGET_TYPE_REV = {v: k for k, v in _TARGET_TYPE_MAP.items()}

_IMAGING_MODE_MAP = {1: "可见光", 2: "红外", 3: "可见+红外"}
_IMAGING_MODE_REV = {v: k for k, v in _IMAGING_MODE_MAP.items()}

_CORNER_RE = re.compile(r"角点(\d+)(经度|纬度)")

_TASK_COLUMNS = ["序号", "字段名", "字段值", "单位", "备注"]
_TARGET_COLUMNS = ["序号", "元任务编号",
                   "元任务最早开始时间", "元任务最晚结束时间",
                   "目标编号",
                   "角点1经度(°)", "角点1纬度(°)",
                   "角点2经度(°)", "角点2纬度(°)",
                   "角点3经度(°)", "角点3纬度(°)",
                   "角点4经度(°)", "角点4纬度(°)",
                   "角点5经度(°)", "角点5纬度(°)",
                   "角点6经度(°)", "角点6纬度(°)",
                   "角点7经度(°)", "角点7纬度(°)",
                   "角点8经度(°)", "角点8纬度(°)",
                   "前视俯仰角", "后视俯仰角", "成像时长(s)",
                   "目标类型", "优先级", "成像模式", "角点有效个数"]

# 可编辑列(目标表 - 所有数据列均可编辑)
_TARGET_EDIT_COLS = {"元任务编号",
                     "元任务最早开始时间", "元任务最晚结束时间",
                     "目标编号",
                     "角点1经度(°)", "角点1纬度(°)",
                     "角点2经度(°)", "角点2纬度(°)",
                     "角点3经度(°)", "角点3纬度(°)",
                     "角点4经度(°)", "角点4纬度(°)",
                     "角点5经度(°)", "角点5纬度(°)",
                     "角点6经度(°)", "角点6纬度(°)",
                     "角点7经度(°)", "角点7纬度(°)",
                     "角点8经度(°)", "角点8纬度(°)",
                     "前视俯仰角", "后视俯仰角", "成像时长(s)",
                     "目标类型", "优先级", "成像模式", "角点有效个数"}
_TASK_EDIT_COLS = {"字段值"}


def _format_hex_inline(raw: bytes) -> str:
    """原始帧 -> 单行 hex(空格分隔,大写)。"""
    return raw.hex(" ").upper()


def _fmt_task_value(name: str, val) -> str:
    if val is None:
        return "—"
    if name == "packet_type":
        return f"0x{int(val):04X}"
    if name in _TIME_FIELDS:
        try:
            dt = STK_EPOCH_2009 + timedelta(seconds=int(val))
            return f"{int(val)} ({dt.strftime('%Y-%m-%d %H:%M:%S')})"
        except (TypeError, ValueError, OverflowError):
            return str(val)
    return str(val)


def _parse_task_edit(key: str, text: str):
    """将用户在任务表编辑的字符串解析回原始值。"""
    text = text.strip()
    if key == "packet_type":
        if text.lower().startswith("0x"):
            return int(text, 16)
        try:
            return int(text)
        except ValueError:
            return 0x3101
    if key in _TIME_FIELDS:
        parts = text.split()
        if parts:
            try:
                return int(parts[0])
            except ValueError:
                pass
        return 0
    try:
        return int(text)
    except ValueError:
        try:
            return float(text)
        except ValueError:
            return text


def _update_target_from_edit(col_name: str, value: str, target: dict) -> None:
    """根据列名将编辑值写入目标 dict(含角点、类型反查)。"""
    if col_name == "元任务编号":
        target["meta_task_id"] = int(value)
    elif col_name == "元任务最早开始时间":
        parts = value.split()
        target["meta_earliest"] = int(parts[0]) if parts else 0
    elif col_name == "元任务最晚结束时间":
        parts = value.split()
        target["meta_latest"] = int(parts[0]) if parts else 0
    elif col_name == "目标编号":
        target["target_id"] = int(value)
    elif col_name == "前视俯仰角":
        target["forward_pitch"] = int(value)
    elif col_name == "后视俯仰角":
        target["backward_pitch"] = int(value)
    elif col_name == "成像时长(s)":
        target["imaging_duration"] = int(value)
    elif col_name == "目标类型":
        target["target_type"] = _TARGET_TYPE_REV.get(value.strip(), 0)
    elif col_name == "优先级":
        target["target_priority"] = int(value)
    elif col_name == "成像模式":
        target["imaging_mode"] = _IMAGING_MODE_REV.get(value.strip(), 0)
    elif col_name == "角点有效个数":
        target["corner_count"] = int(value)
    else:
        m = _CORNER_RE.match(col_name)
        if m:
            idx = int(m.group(1)) - 1
            is_lon = m.group(2) == "经度"
            corners = list(target.get("corners") or [(0.0, 0.0)] * 8)
            while len(corners) < 8:
                corners.append((0.0, 0.0))
            lon, lat = corners[idx]
            if is_lon:
                lon = float(value)
            else:
                lat = float(value)
            corners[idx] = (lon, lat)
            target["corners"] = corners
            target["lon"] = corners[0][0]
            target["lat"] = corners[0][1]


def _target_type_text(t: int) -> str:
    return _TARGET_TYPE_MAP.get(int(t), f"自定义({t})")


def _imaging_mode_text(m: int) -> str:
    return _IMAGING_MODE_MAP.get(int(m), str(m))


def _fmt_lonlat(v: float) -> str:
    try:
        return f"{float(v):.6f}"
    except (TypeError, ValueError):
        return "0.000000"


def _fmt_utc_seconds(sec: int) -> str:
    """UTC 秒(自 2009-01-01)→ '秒 (YYYY-MM-DD HH:MM:SS)'。"""
    try:
        s = int(sec)
        dt = STK_EPOCH_2009 + timedelta(seconds=s)
        return f"{s} ({dt.strftime('%Y-%m-%d %H:%M:%S')})"
    except (TypeError, ValueError, OverflowError):
        return str(sec)


class Target3101Panel(QWidget):
    """3101 目标输入报文:Hex 可编辑 + 可编辑解析表。

    编辑任意表格值 → 自动重建 3101 报文并刷新 Hex;
    Hex 框可手动输入/粘贴,防抖 700ms 自动解析刷新表格;
    目标列表支持整行删除,报文同步更新;
    表格占满页面空间,内置滚动。
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._builder: StkPacketBuilder | None = None
        self._task_model = GenericTableModel(_TASK_COLUMNS)
        self._target_model = GenericTableModel(_TARGET_COLUMNS)
        self._info: dict | None = None       # 当前解析的 3101 dict
        self._updating = False                # 防止重建时信号回环

        # 修改提示自动清除定时器
        self._notif_timer = QTimer(self)
        self._notif_timer.setSingleShot(True)
        self._notif_timer.setInterval(5000)
        self._notif_timer.timeout.connect(lambda: self._lbl_modify.setText(""))

        # Hex 手动输入防抖解析
        self._hex_timer = QTimer(self)
        self._hex_timer.setSingleShot(True)
        self._hex_timer.setInterval(700)
        self._hex_timer.timeout.connect(self._on_hex_edited)

        # ---- 布局:无外层 ScrollArea,表格占满页面 ----
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 6, 8, 6)
        outer.setSpacing(4)

        outer.addWidget(self._build_hex_card())
        outer.addWidget(self._build_task_card(), 2)     # 任务表 stretch=2
        outer.addWidget(self._build_target_card(), 3)   # 目标表 stretch=3

        # ---- 信号:编辑表格 → 重建报文;编辑 Hex → 解析 ----
        self._task_model.dataChanged.connect(self._on_table_edited)
        self._target_model.dataChanged.connect(self._on_table_edited)
        self._hex_edit.textChanged.connect(self._on_hex_text_changed)

    # ---------- UI 构建 ----------

    def _build_hex_card(self) -> QFrame:
        """Hex 报文卡:标题行 + 元信息/提示行 + Hex 横排。

        标题独占一行,避免被右侧元素挤压截断。
        """
        card = QFrame()
        card.setObjectName("Card")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(10, 4, 10, 6)
        cl.setSpacing(3)

        # 第一行:标题(独占一行,确保显示完整)
        title = QLabel("3101 目标输入报文")
        title.setObjectName("SectionTitle")
        title.setStyleSheet(f"font-size:13px; font-weight:700; color:{C.FG};")
        cl.addWidget(title)

        # 第二行:元信息 + 修改提示(横排,可被压缩)
        meta_row = QHBoxLayout()
        meta_row.setSpacing(8)
        self._lbl_meta = QLabel("长度: — | 目标数: — | 包序号: —")
        self._lbl_meta.setStyleSheet(f"color:{C.FG_DIM}; font-size:11px;")
        meta_row.addWidget(self._lbl_meta)
        meta_row.addStretch()
        # 修改提示标签(绿色闪烁)
        self._lbl_modify = QLabel("")
        self._lbl_modify.setStyleSheet(
            f"color:{C.OK}; font-size:11px; font-weight:600;")
        meta_row.addWidget(self._lbl_modify)
        cl.addLayout(meta_row)

        self._hex_edit = QTextEdit()
        self._hex_edit.setReadOnly(False)   # 支持手动输入/粘贴报文
        self._hex_edit.setStyleSheet(
            f"background:{C.BG_TABLE}; color:{C.PKT_DATA};"
            f"font-family:{FONT_MONO}; font-size:12px;"
            f"border:1px solid {C.BORDER_SOFT}; border-radius:4px;"
            f"padding:4px;")
        self._hex_edit.setPlaceholderText(
            "可粘贴/输入十六进制报文(空格分隔),输入后自动解析…")
        self._hex_edit.setFixedHeight(80)
        # 允许换行:长 hex 字符串自动折行显示,避免被截断不可见
        self._hex_edit.setLineWrapMode(QTextEdit.WidgetWidth)
        cl.addWidget(self._hex_edit)
        return card

    def _build_task_card(self) -> QFrame:
        """任务固定区信息表(字段值可编辑)。"""
        card = QFrame()
        card.setObjectName("Card")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(10, 4, 10, 6)
        cl.setSpacing(3)

        cl.addWidget(SectionTitle("报文解析结果(任务固定区 36B)", accent=C.ACCENT))

        self._task_table = DataTableView(empty_text="暂无解析数据")
        self._task_table.setModel(self._task_model)
        self._task_table.setAlternatingRowColors(True)
        self._task_table.setSelectionBehavior(QAbstractItemView.SelectItems)
        self._task_table.verticalHeader().setVisible(False)
        self._task_table.verticalHeader().setDefaultSectionSize(22)
        self._task_table.setShowGrid(False)
        th = self._task_table.horizontalHeader()
        th.setFixedHeight(24)
        self._task_table.setColumnWidth(0, 36)
        self._task_table.setColumnWidth(1, 170)
        self._task_table.setColumnWidth(2, 240)
        self._task_table.setColumnWidth(3, 56)
        th.setSectionResizeMode(4, QHeaderView.Stretch)
        self._task_mono = MonoDelegate(self._task_table)
        self._task_table.setItemDelegateForColumn(2, self._task_mono)
        cl.addWidget(self._task_table)
        return card

    def _build_target_card(self) -> QFrame:
        """目标列表卡:标题+删除按钮 + 表格。"""
        card = QFrame()
        card.setObjectName("Card")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(10, 4, 10, 6)
        cl.setSpacing(3)

        # 标题行 + 删除按钮
        hdr = QHBoxLayout()
        hdr.setSpacing(10)
        hdr.addWidget(SectionTitle(
            "目标列表(每记录 87B,含 8 角点+前后视+时长)", accent=C.TARGET))
        hdr.addStretch()
        btn_del = QPushButton("删除选中目标")
        btn_del.setObjectName("Danger")
        btn_del.setStyleSheet(
            f"QPushButton#Danger {{ background:{C.ERR_SOFT};"
            f" border:1px solid #8a3346; color:#ff9db0;"
            f" border-radius:4px; padding:3px 10px; font-size:11px; }}"
            f"QPushButton#Danger:hover {{ background:#552433; }}")
        btn_del.clicked.connect(self._delete_selected_targets)
        hdr.addWidget(btn_del)
        cl.addLayout(hdr)

        self._target_table = DataTableView(empty_text="暂无目标,请从 STK 获取或手动输入报文")
        self._target_table.setModel(self._target_model)
        self._target_table.setAlternatingRowColors(True)
        self._target_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._target_table.verticalHeader().setVisible(False)
        self._target_table.verticalHeader().setDefaultSectionSize(22)
        self._target_table.setShowGrid(False)
        # 启用横向滚动条:28 列宽度和超过窗口宽度时自动出现
        self._target_table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        # 右键菜单
        self._target_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self._target_table.customContextMenuRequested.connect(
            self._on_target_context_menu)
        hh = self._target_table.horizontalHeader()
        hh.setFixedHeight(24)
        # 全部列设为 Interactive(可手动拖拽调整宽度),不用 Stretch 避免遮挡
        hh.setSectionResizeMode(QHeaderView.Interactive)
        hh.setMinimumSectionSize(60)
        self._target_table.setColumnWidth(0, 40)    # 序号
        self._target_table.setColumnWidth(1, 90)    # 元任务编号
        self._target_table.setColumnWidth(2, 180)   # 元任务最早开始时间
        self._target_table.setColumnWidth(3, 180)   # 元任务最晚结束时间
        self._target_table.setColumnWidth(4, 80)    # 目标编号
        for c in range(5, 21):                        # 角点1-8 经纬度
            self._target_table.setColumnWidth(c, 100)
        self._target_table.setColumnWidth(21, 80)   # 前视
        self._target_table.setColumnWidth(22, 80)   # 后视
        self._target_table.setColumnWidth(23, 90)   # 成像时长
        self._target_table.setColumnWidth(24, 100)   # 目标类型
        self._target_table.setColumnWidth(25, 60)   # 优先级
        self._target_table.setColumnWidth(26, 90)   # 成像模式
        self._target_table.setColumnWidth(27, 100)  # 角点有效个数
        self._target_badge = BadgeDelegate(self._target_table)
        self._target_table.setItemDelegateForColumn(4, self._target_badge)
        self._target_mono = MonoDelegate(self._target_table)
        for c in range(5, 21):
            self._target_table.setItemDelegateForColumn(c, self._target_mono)
        # 元任务时间列用等宽字体
        self._target_table.setItemDelegateForColumn(2, self._target_mono)
        self._target_table.setItemDelegateForColumn(3, self._target_mono)
        cl.addWidget(self._target_table)
        return card

    # ---------- 数据接入 ----------

    def set_builder(self, builder: StkPacketBuilder) -> None:
        self._builder = builder
        # 注入 builder 后立即生成默认 3101 报文(供用户查看和修改)
        self._load_default_targets()

    def _load_default_targets(self) -> None:
        """生成默认 mock 目标点,构造 3101 报文显示。

        启动时即给出默认输出,用户修改表格后实时刷新。
        """
        if self._builder is None:
            return
        default_targets = [
            TargetPoint(id="11", lon=116.4074, lat=39.9042, alt=0.05),
            TargetPoint(id="13", lon=87.6123, lat=43.8256, alt=0.05),
            TargetPoint(id="16", lon=108.9398, lat=34.3416, alt=0.05),
            TargetPoint(id="15", lon=121.4737, lat=31.2304, alt=0.05),
            TargetPoint(id="19", lon=103.8343, lat=36.0611, alt=0.05),
        ]
        self.on_targets_ready(default_targets)

    def on_targets_ready(self, targets: list[TargetPoint],
                         star_sec: int = 0) -> None:
        """STK 目标列表 → 3101 报文。

        时间规则:
          - 元任务最早开始时间 = 初始轨道时间(star_sec)
          - 元任务最晚结束时间 = 初始轨道时间 + 2小时
          - 任务最早/最晚时间同元任务设置
          - star_sec=0 时回退到默认(2026-10-01 02:00:00)
        """
        if self._builder is None:
            self._lbl_meta.setText("未注入 builder | 目标数: — | 包序号: —")
            return
        try:
            if star_sec > 0:
                # 用 0B01 星时作为初始轨道时间
                from datetime import timedelta
                from ...models.orbit import STK_EPOCH_2009
                earliest = STK_EPOCH_2009 + timedelta(seconds=star_sec)
            else:
                earliest = parse_utcg("1 Oct 2026 02:00:00.000")
            raw = self._builder.target_input_frame(targets, earliest=earliest)
        except Exception as e:  # noqa: BLE001
            self._hex_edit.setPlainText(f"构造 3101 帧失败:{e}")
            self._lbl_meta.setText(f"目标数: {len(targets)} | 包序号: —")
            return

        try:
            info = parse_3101(raw)
        except Exception as e:  # noqa: BLE001
            self._lbl_meta.setText(f"解析失败:{e} | 目标数: {len(targets)}")
            return

        self._info = info
        # 刷新 Hex 文本框(显示完整 hex 字节流,防回环)
        self._updating = True
        self._hex_edit.setPlainText(_format_hex_inline(raw))
        self._updating = False
        self._refresh_hex_display()
        self._populate_task_table()
        self._populate_target_table()

    def on_parsed_packet(self, pkt) -> None:
        return

    # ---------- 内部:填充表格 ----------

    def _populate_task_table(self) -> None:
        """根据 self._info 填充任务固定区表。"""
        self._updating = True
        info = self._info or {}
        task_rows: list[dict] = []
        for i, (key, label, unit, note) in enumerate(_TASK_FIELDS, 1):
            val = info.get(key)
            task_rows.append({
                "序号": i,
                "字段名": label,
                "字段值": _fmt_task_value(key, val),
                "单位": unit,
                "备注": note,
                "_editable": _TASK_EDIT_COLS if key not in _DERIVED_FIELDS else set(),
                "_colors": {"字段名": C.FG,
                            "字段值": C.PKT_DATA,
                            "单位": C.FG_DIM,
                            "备注": C.FG_DIM},
            })
        self._task_model.replace_rows(task_rows)
        self._updating = False

    def _populate_target_table(self) -> None:
        """根据 self._info 填充目标列表表。"""
        self._updating = True
        info = self._info or {}
        target_rows: list[dict] = []
        for i, t in enumerate(info.get("targets", []), 1):
            corners = t.get("corners") or [(0.0, 0.0)] * 8
            while len(corners) < 8:
                corners.append((0.0, 0.0))
            row = {
                "序号": i,
                "元任务编号": int(t.get("meta_task_id", 0)),
                "元任务最早开始时间": _fmt_utc_seconds(t.get("meta_earliest", 0)),
                "元任务最晚结束时间": _fmt_utc_seconds(t.get("meta_latest", 0)),
                "目标编号": int(t.get("target_id", 0)),
                "角点1经度(°)": _fmt_lonlat(corners[0][0]),
                "角点1纬度(°)": _fmt_lonlat(corners[0][1]),
                "角点2经度(°)": _fmt_lonlat(corners[1][0]),
                "角点2纬度(°)": _fmt_lonlat(corners[1][1]),
                "角点3经度(°)": _fmt_lonlat(corners[2][0]),
                "角点3纬度(°)": _fmt_lonlat(corners[2][1]),
                "角点4经度(°)": _fmt_lonlat(corners[3][0]),
                "角点4纬度(°)": _fmt_lonlat(corners[3][1]),
                "角点5经度(°)": _fmt_lonlat(corners[4][0]),
                "角点5纬度(°)": _fmt_lonlat(corners[4][1]),
                "角点6经度(°)": _fmt_lonlat(corners[5][0]),
                "角点6纬度(°)": _fmt_lonlat(corners[5][1]),
                "角点7经度(°)": _fmt_lonlat(corners[6][0]),
                "角点7纬度(°)": _fmt_lonlat(corners[6][1]),
                "角点8经度(°)": _fmt_lonlat(corners[7][0]),
                "角点8纬度(°)": _fmt_lonlat(corners[7][1]),
                "前视俯仰角": int(t.get("forward_pitch", 200)),
                "后视俯仰角": int(t.get("backward_pitch", 200)),
                "成像时长(s)": int(t.get("imaging_duration", 10)),
                "目标类型": _target_type_text(int(t.get("target_type", 0))),
                "优先级": int(t.get("target_priority", 0)),
                "成像模式": _imaging_mode_text(int(t.get("imaging_mode", 0))),
                "角点有效个数": int(t.get("corner_count", 0)),
                "_editable": _TARGET_EDIT_COLS,
                "_badges": {"目标编号": C.TARGET},
                "_colors": {"目标类型": C.TARGET,
                            "优先级": C.FG_DIM,
                            "成像模式": C.FG_DIM},
            }
            target_rows.append(row)
        self._target_model.replace_rows(target_rows)
        self._updating = False

    # ---------- 编辑 → 重建报文 ----------

    def _on_table_edited(self, top_left, bottom_right, roles) -> None:
        """表格编辑后:同步值到 self._info,重建 Hex,显示提示。"""
        if self._updating or self._info is None:
            return
        if Qt.EditRole not in roles and not roles:
            return

        # 判断是哪个表被编辑
        sender = self.sender()
        if sender is self._task_model:
            self._sync_task_edit(top_left, bottom_right)
        elif sender is self._target_model:
            self._sync_target_edit(top_left, bottom_right)

    def _sync_task_edit(self, top_left, bottom_right) -> None:
        """任务表编辑:将字段值解析回 self._info。"""
        changed_labels = []
        for r in range(top_left.row(), bottom_right.row() + 1):
            if r >= len(_TASK_FIELDS):
                continue
            key, label, _, _ = _TASK_FIELDS[r]
            if key in _DERIVED_FIELDS:
                continue
            val_str = self._task_model._rows[r].get("字段值", "")
            try:
                new_val = _parse_task_edit(key, val_str)
            except (ValueError, TypeError):
                continue
            old_val = self._info.get(key)
            self._info[key] = new_val
            if old_val != new_val:
                changed_labels.append(label)
        if changed_labels:
            self._rebuild_and_notify(f"已修改「{', '.join(changed_labels)}」")

    def _sync_target_edit(self, top_left, bottom_right) -> None:
        """目标表编辑:将单元格值写入对应目标 dict。"""
        targets = self._info.get("targets") or []
        changed = False
        for r in range(top_left.row(), min(bottom_right.row() + 1, len(targets))):
            target = targets[r]
            for c in range(top_left.column(), bottom_right.column() + 1):
                if c < 0 or c >= len(_TARGET_COLUMNS):
                    continue
                col_name = _TARGET_COLUMNS[c]
                if col_name == "序号":
                    continue
                val_str = self._target_model._rows[r].get(col_name, "")
                try:
                    _update_target_from_edit(col_name, val_str, target)
                    changed = True
                except (ValueError, TypeError):
                    pass
        if changed:
            self._rebuild_and_notify("已修改目标参数")

    def _rebuild_and_notify(self, msg: str) -> None:
        """从 self._info 重建 3101 报文,刷新 Hex 显示,显示修改提示。"""
        try:
            raw = serialize_3101(self._info)
        except Exception as e:  # noqa: BLE001
            self._lbl_modify.setText(f"✗ 重建报文失败:{e}")
            self._lbl_modify.setStyleSheet(
                f"color:{C.ERR}; font-size:12px; font-weight:600;")
            self._notif_timer.start(5000)
            return

        # 刷新 Hex(防回环)
        self._updating = True
        self._hex_edit.setPlainText(_format_hex_inline(raw))
        self._updating = False

        # 更新派生字段(target_count, cur_packet_len)
        self._info["target_count"] = len(self._info.get("targets") or [])
        self._info["cur_packet_len"] = len(raw)
        self._refresh_hex_display()

        # 更新任务表中的派生字段(目标数量、当前包长度)显示
        self._updating = True
        for i, (key, _, _, _) in enumerate(_TASK_FIELDS):
            if key in _DERIVED_FIELDS:
                row = self._task_model._rows[i]
                row["字段值"] = _fmt_task_value(key, self._info.get(key))
                idx = self._task_model.index(i, 2)
                self._task_model.dataChanged.emit(idx, idx, [Qt.DisplayRole])
        self._updating = False

        # 显示修改提示
        ts = datetime.now().strftime("%H:%M:%S")
        self._lbl_modify.setText(f"✓ {msg},报文已刷新 [{ts}]")
        self._lbl_modify.setStyleSheet(
            f"color:{C.OK}; font-size:12px; font-weight:600;")
        self._notif_timer.start(5000)

    def _refresh_hex_display(self) -> None:
        """刷新 Hex 卡片元信息(长度/目标数/包序号)。"""
        info = self._info or {}
        pkt_len = int(info.get("cur_packet_len", 0))
        seq = int(info.get("sequence_no", 0))
        tgt_cnt = int(info.get("target_count", 0))
        self._lbl_meta.setText(
            f"长度: {pkt_len}B | 目标数: {tgt_cnt} | 包序号: {seq}")

    # ---------- 目标删除 ----------

    def _delete_selected_targets(self) -> None:
        """删除目标表中选中的行,同步更新报文。"""
        sm = self._target_table.selectionModel()
        if sm is None:
            return
        rows = sorted(set(i.row() for i in sm.selectedRows()), reverse=True)
        if not rows:
            # 尝试选中行(SelectItems 模式下)
            rows = sorted(set(i.row() for i in sm.selectedIndexes()), reverse=True)
        if not rows:
            return

        count = len(rows)
        # 从 info["targets"] 删除(降序)
        targets = self._info.get("targets") or []
        for r in rows:
            if 0 <= r < len(targets):
                targets.pop(r)
        self._info["targets"] = targets

        # 从表格模型删除
        self._target_model.remove_rows(rows)

        # 重新编号序号
        self._updating = True
        for i, row in enumerate(self._target_model._rows, 1):
            row["序号"] = i
        if self._target_model.rowCount() > 0:
            idx0 = self._target_model.index(0, 0)
            idx1 = self._target_model.index(
                self._target_model.rowCount() - 1, 0)
            self._target_model.dataChanged.emit(idx0, idx1, [Qt.DisplayRole])
        self._updating = False

        # 重建报文
        self._rebuild_and_notify(f"已删除 {count} 个目标")

    def _on_target_context_menu(self, pos) -> None:
        """右键菜单:删除选中目标。"""
        menu = QMenu(self)
        menu.setStyleSheet(
            f"QMenu {{ background:{C.BG_PANEL_2}; color:{C.FG};"
            f" border:1px solid {C.BORDER}; }}")
        act = menu.addAction("删除选中目标")
        chosen = menu.exec(self._target_table.viewport().mapToGlobal(pos))
        if chosen == act:
            self._delete_selected_targets()

    # ---------- Hex 手动输入 → 解析 ----------

    def _on_hex_text_changed(self) -> None:
        if self._updating:
            return
        self._hex_timer.start()

    def _on_hex_edited(self) -> None:
        """Hex 手动输入防抖解析:成功后刷新表格与元信息。"""
        if self._updating:
            return
        text = self._hex_edit.toPlainText()
        try:
            raw = hex_text_to_bytes(text)
            info = parse_3101(raw)
        except Exception as e:  # noqa: BLE001
            self._lbl_modify.setText(f"✗ 报文解析失败:{e}")
            self._lbl_modify.setStyleSheet(
                f"color:{C.ERR}; font-size:11px; font-weight:600;")
            self._notif_timer.start(5000)
            return
        self._info = info
        self._refresh_hex_display()
        self._populate_task_table()
        self._populate_target_table()
        ts = datetime.now().strftime("%H:%M:%S")
        self._lbl_modify.setText(f"✓ 已从手动输入报文解析 [{ts}]")
        self._lbl_modify.setStyleSheet(
            f"color:{C.OK}; font-size:11px; font-weight:600;")
        self._notif_timer.start(5000)

    # ---------- 导出 ----------

    def export_data(self) -> tuple[str, list]:
        rows = [{k: v for k, v in r.items() if not k.startswith("_")}
                for r in self._target_model._rows]
        return ("目标输入解析", rows)

    def clear_data(self) -> None:
        self._info = None
        self._task_model.clear()
        self._target_model.clear()
        self._updating = True
        self._hex_edit.setPlainText("")
        self._updating = False
        self._lbl_meta.setText("长度: — | 目标数: — | 包序号: —")
        self._lbl_modify.setText("")

    def get_current_targets(self) -> list[TargetPoint]:
        """实时解析当前页面 Hex 报文,返回目标点列表(供计算可见性用)。

        以页面当前 Hex 内容为准(用户可能刚手动改过),
        解析失败则回退到最近一次成功解析的 self._info。
        """
        try:
            raw = hex_text_to_bytes(self._hex_edit.toPlainText())
            self._info = parse_3101(raw)
        except Exception:  # noqa: BLE001
            pass
        info = self._info or {}
        points: list[TargetPoint] = []
        for t in info.get("targets") or []:
            points.append(TargetPoint(
                id=str(t.get("target_id", 0)),
                lon=float(t.get("lon", 0.0)),
                lat=float(t.get("lat", 0.0)),
                alt=0.0))
        return points

    def get_info(self) -> dict | None:
        """实时解析当前 Hex 内容,返回完整 3101 报文解析结果。

        包含固定区参数(onboard_processing/compression/imaging_type 等),
        供 build_0f11 继承使用。解析失败则返回最近一次成功结果。
        """
        try:
            raw = hex_text_to_bytes(self._hex_edit.toPlainText())
            self._info = parse_3101(raw)
        except Exception:  # noqa: BLE001
            pass
        return self._info

    def get_raw(self) -> bytes | None:
        """获取当前 Hex 内容的原始 3101 报文字节(供 DLL 报文驱动输入)。"""
        try:
            return hex_text_to_bytes(self._hex_edit.toPlainText())
        except Exception:  # noqa: BLE001
            return None

    def set_hex_bytes(self, raw: bytes) -> None:
        """用原始字节设置 3101 页面 Hex 并触发解析刷新。"""
        if not raw:
            return
        self._updating = True
        self._hex_edit.setPlainText(_format_hex_inline(raw))
        self._updating = False
        try:
            self._info = parse_3101(raw)
        except Exception:  # noqa: BLE001
            self._info = None
        self._refresh_hex_display()
        self._populate_task_table()
        self._populate_target_table()


class TargetIoView(QWidget):
    """目标输入结果和解析:六个子页(3101/0C12/0C15/0B01/A002/A012)。

    每个页面均为"Hex(可手动输入) + 固定区解析表 + 记录表"结构。
    轨道源下拉框选择 A002(位置速度) 或 A012(轨道根数) 参与可见性计算。
    """

    # 0B01 星时解析成功时发射(历元秒),供主窗口同步星时显示
    star_time_parsed = Signal(float)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        from .resource_views import (create_0c12_panel, create_0c15_panel,
                                     create_0b01_panel, create_a002_panel,
                                     create_a012_panel, create_0802_panel)

        self.panel_3101 = Target3101Panel()
        self.panel_0c12 = create_0c12_panel()
        self.panel_0c15 = create_0c15_panel()
        self.panel_0b01 = create_0b01_panel(
            parsed_callback=self._on_0b01_parsed)
        self.panel_a002 = create_a002_panel()
        self.panel_a012 = create_a012_panel()
        self.panel_0802 = create_0802_panel()

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # ---- 顶部轨道源选择条 ----
        sel_bar = QFrame()
        sel_bar.setObjectName("Card")
        sel_bar.setFixedHeight(38)
        sbl = QHBoxLayout(sel_bar)
        sbl.setContentsMargins(14, 4, 14, 4)
        sbl.setSpacing(8)
        lbl_orbit = QLabel("轨道数据源:")
        lbl_orbit.setStyleSheet(f"color:{C.FG}; font-size:12px; font-weight:600;")
        sbl.addWidget(lbl_orbit)
        self.cmb_orbit_source = QComboBox()
        self.cmb_orbit_source.addItem("A012 轨道根数", "A012")
        self.cmb_orbit_source.addItem("A002 位置速度", "A002")
        self.cmb_orbit_source.setFixedWidth(150)
        self.cmb_orbit_source.setStyleSheet(
            f"QComboBox {{ background:{C.BG_PANEL_2}; color:{C.FG};"
            f" border:1px solid {C.BORDER}; border-radius:4px; padding:3px 8px;"
            " font-size:12px;}}"
            f"QComboBox::drop-down {{ border:none; width:20px; }}"
            f"QComboBox QAbstractItemView {{ background:{C.BG_PANEL};"
            f" color:{C.FG}; }}")
        sbl.addWidget(self.cmb_orbit_source)
        hint = QLabel("(选中的轨道帧参与可见性计算)")
        hint.setStyleSheet(f"color:{C.FG_DIM}; font-size:11px;")
        sbl.addWidget(hint)
        sbl.addStretch()
        lay.addWidget(sel_bar)

        self.sub_tabs = QTabWidget()
        self.sub_tabs.addTab(self.panel_3101, "3101 目标输入报文")
        self.sub_tabs.addTab(self.panel_0c12, "0C12 数传链路资源")
        self.sub_tabs.addTab(self.panel_0c15, "0C15 数传站址资源")
        self.sub_tabs.addTab(self.panel_0b01, "0B01 星时")
        self.sub_tabs.addTab(self.panel_a002, "A002 位置速度")
        self.sub_tabs.addTab(self.panel_a012, "A012 轨道六根数")
        self.sub_tabs.addTab(self.panel_0802, "0802 固存状态信息")
        lay.addWidget(self.sub_tabs)

    @property
    def orbit_source(self) -> str:
        """当前选中的轨道数据源:'A012' 或 'A002'。"""
        return self.cmb_orbit_source.currentData()

    # ---------- 兼容主窗口调用(委托给 3101 面板) ----------

    def set_builder(self, builder: StkPacketBuilder) -> None:
        self.panel_3101.set_builder(builder)

    def on_targets_ready(self, targets: list[TargetPoint]) -> None:
        """STK 成像目标 → 3101 目标输入报文页。

        元任务最早开始时间 = STK 初始轨道时间(0B01 页星时)
        元任务最晚结束时间 = 初始轨道时间 + 2小时
        任务最早/最晚时间同元任务设置。
        """
        # 从 0B01 页获取当前星时作为初始轨道时间
        star_sec = self._get_0b01_seconds()
        self.panel_3101.on_targets_ready(targets, star_sec=star_sec)

    def on_parsed_packet(self, pkt) -> None:
        return

    def get_current_targets(self) -> list[TargetPoint]:
        """获取 3101 页面当前最新报文中的目标点列表。"""
        return self.panel_3101.get_current_targets()

    def get_3101_info(self) -> dict | None:
        """获取 3101 页面当前最新报文完整解析结果(含固定区参数)。"""
        return self.panel_3101.get_info()

    def get_3101_raw(self) -> bytes | None:
        """获取 3101 页面当前最新报文原始字节(供 DLL 报文驱动)。"""
        return self.panel_3101.get_raw()

    def get_0c12_raw(self) -> bytes | None:
        """获取 0C12 页面当前报文原始字节(供 DLL 报文驱动)。"""
        return self.panel_0c12.get_raw()

    def get_0c15_raw(self) -> bytes | None:
        """获取 0C15 页面当前报文原始字节(供 DLL 报文驱动)。"""
        return self.panel_0c15.get_raw()

    def get_0802_raw(self) -> bytes | None:
        """获取 0802 页面当前报文原始字节(供 DLL 报文驱动)。"""
        return self.panel_0802.get_raw()

    def get_0c12_info(self) -> dict | None:
        """获取 0C12 页面当前最新报文解析结果(数传链路资源)。"""
        return self.panel_0c12.get_info()

    def get_0c15_info(self) -> dict | None:
        """获取 0C15 页面当前最新报文解析结果(数传站址资源)。"""
        return self.panel_0c15.get_info()

    # ---------- 星时/轨道帧获取(供 DLL 报文驱动) ----------

    def _get_0b01_seconds(self) -> int:
        """从 0B01 页获取当前星时(历元秒),为空返回 0。"""
        info = self.panel_0b01.get_info()
        if not info:
            return 0
        try:
            return int(info.get("time_seconds", 0))
        except (TypeError, ValueError):
            return 0

    def get_0b01_raw(self) -> bytes | None:
        """获取 0B01 星时页面当前报文原始字节。"""
        return self.panel_0b01.get_raw()

    def get_0b01_info(self) -> dict | None:
        """获取 0B01 星时页面解析结果。"""
        return self.panel_0b01.get_info()

    def _on_0b01_parsed(self, info: dict) -> None:
        """0B01 报文解析成功回调:发射星时信号供主窗口同步。"""
        tsec = info.get("time_seconds") or 0
        try:
            tsec = int(tsec)
        except (TypeError, ValueError):
            tsec = 0
        if tsec > 0:
            tms = info.get("time_millis") or 0
            try:
                tms = int(tms)
            except (TypeError, ValueError):
                tms = 0
            self.star_time_parsed.emit(float(tsec) + tms / 1000.0)

    def get_a002_raw(self) -> bytes | None:
        """获取 A002 位置速度页面当前报文原始字节。"""
        return self.panel_a002.get_raw()

    def get_a012_raw(self) -> bytes | None:
        """获取 A012 轨道根数页面当前报文原始字节。"""
        return self.panel_a012.get_raw()

    def get_selected_orbit_raw(self) -> bytes | None:
        """获取轨道源下拉框选中的轨道帧(A002 或 A012)。"""
        if self.orbit_source == "A002":
            return self.get_a002_raw()
        return self.get_a012_raw()

    def set_0b01_raw(self, raw: bytes) -> None:
        """用原始字节设置 0B01 页面的 Hex 并触发解析刷新。"""
        self.panel_0b01.set_hex_bytes(raw)

    def set_a012_raw(self, raw: bytes) -> None:
        """用原始字节设置 A012 页面的 Hex 并触发解析刷新。"""
        self.panel_a012.set_hex_bytes(raw)

    def set_a002_raw(self, raw: bytes) -> None:
        """用原始字节设置 A002 页面的 Hex 并触发解析刷新。"""
        self.panel_a002.set_hex_bytes(raw)

    def get_all_hex(self) -> dict:
        """获取全部 6 页 hex 字符串(供会话缓存)。"""
        out = {}
        for name, panel in [("3101", self.panel_3101),
                            ("0C12", self.panel_0c12),
                            ("0C15", self.panel_0c15),
                            ("0B01", self.panel_0b01),
                            ("A002", self.panel_a002),
                            ("A012", self.panel_a012),
                            ("0802", self.panel_0802)]:
            raw = panel.get_raw()
            out[name] = raw.hex().upper() if raw else ""
        out["orbit_source"] = self.orbit_source
        return out

    def set_all_hex(self, data: dict) -> None:
        """从会话缓存恢复全部页 hex 数据。"""
        panels = {"3101": self.panel_3101, "0C12": self.panel_0c12,
                  "0C15": self.panel_0c15, "0B01": self.panel_0b01,
                  "A002": self.panel_a002, "A012": self.panel_a012,
                  "0802": self.panel_0802}
        for name, panel in panels.items():
            hex_str = data.get(name, "")
            if hex_str:
                try:
                    raw = bytes.fromhex(hex_str)
                    panel.set_hex_bytes(raw)
                except Exception:  # noqa: BLE001
                    pass
        src = data.get("orbit_source")
        if src:
            idx = self.cmb_orbit_source.findData(src)
            if idx >= 0:
                self.cmb_orbit_source.setCurrentIndex(idx)

    def on_ground_stations_ready(self, stations: list) -> None:
        """地面站列表 → 0C15 数传站址资源页 + 0C12 数传链路资源页。

        将 STK 地面站坐标序列化为 0C15 报文并写入 Hex 框触发解析;
        同时基于地面站过顶时刻(以当前星时为基准)生成 0C12 链路资源,
        链路开始 = 过顶 - 240s,链路结束 = 过顶 + 240s。
        """
        if not stations:
            return
        try:
            from ...stk.packets import serialize_0c15, default_0c15_info
            info = default_0c15_info()
            st_list = []
            for i, st in enumerate(stations, 1):
                st_list.append({
                    "station_id": i,
                    "station_lon": float(getattr(st, "lon", 0) or 0),
                    "station_lat": float(getattr(st, "lat", 0) or 0),
                    "station_alt": float(getattr(st, "alt", 0) or 0),
                    "mask_angle": 10.0,
                    "datalink_rate": 0xC1,
                    "azimuth1": 0,
                    "azimuth2": 3600,
                    "category": 2,
                    "encryption": 0,
                })
            info["stations"] = st_list
            info["station_count"] = len(st_list)
            info["cur_packet_len"] = 12 + 20 * len(st_list)
            raw = serialize_0c15(info)
            self.panel_0c15.set_hex_bytes(raw)
        except Exception as e:  # noqa: BLE001
            # 旧实现用 except: pass 静默吞没错误,导致 clear+STK输出后
            # 0C15 不填充却无任何提示。这里改为告警,便于定位根因。
            _log.warning("地面站 0C15 报文生成失败: %s", e)

        # 同时生成 0C12 数传链路资源(链路开始=过顶-4min,结束=过顶+4min)
        self._generate_0c12_from_stations(stations)

    def _generate_0c12_from_stations(self, stations: list) -> None:
        """根据地面站过顶时刻生成 0C12 链路资源。

        链路开始时间 = 过顶时刻 - 4min(240s)
        链路结束时间 = 过顶时刻 + 4min(240s)
        过顶时刻以 0B01 页当前星时为基准(实际过顶时刻应由算法库计算,
        此处用星时 + 站序号×10min 作为占位,保证链路时间落在合理区间)。
        其他参数按 DeployParameter.xml 默认值填写。
        """
        try:
            from ...stk.packets import serialize_0c12, default_0c12_info
            # 获取当前星时作为过顶时刻基准(2009 历元秒)
            star_sec = 0
            info_0b01 = self.panel_0b01.get_info()
            if info_0b01:
                try:
                    star_sec = int(info_0b01.get("time_seconds", 0) or 0)
                except (TypeError, ValueError):
                    star_sec = 0
            # 若 0B01 页无星时,回退到当前 UTC 对应的 2009 历元秒
            if star_sec <= 0:
                from datetime import timezone
                star_sec = int((datetime.now(timezone.utc) - STK_EPOCH_2009)
                               .total_seconds())

            tmpl = default_0c12_info()
            links = []
            for i, st in enumerate(stations, 1):
                # 过顶时刻 = 当前星时 + i*600(每隔 10 分钟一个站过顶,占位)
                # 实际应用中应由算法库基于轨道预报计算,此处仅保证时间合理。
                overpass = star_sec + i * 600
                links.append({
                    "link_id": i,
                    "link_type": 1,        # 1-X 对地数传链路
                    "dest_id": i,          # 目的地 ID 取站序号
                    "link_start": overpass - 240,  # 过顶 - 4min
                    "link_end": overpass + 240,    # 过顶 + 4min
                    "encryption": 0,       # 0-加密
                    "datalink_rate": 0xC1, # 默认数传速率
                    "task_no": 0,
                    "station_id": i,
                    "station_lon": float(getattr(st, "lon", 0) or 0),
                    "station_lat": float(getattr(st, "lat", 0) or 0),
                    "station_elev_angle": 10.0,  # 默认仰角 10°
                    "periodic_flag": 0,    # 0-非周期
                    "periodic_seconds": 0,
                    "return_data_type": 0,  # 0-原始数据
                })
            tmpl["links"] = links
            tmpl["link_count"] = len(links)
            tmpl["cur_packet_len"] = 12 + 41 * len(links) + 4
            raw = serialize_0c12(tmpl)
            self.panel_0c12.set_hex_bytes(raw)
        except Exception as e:  # noqa: BLE001
            _log.warning("0C12 链路资源生成失败: %s", e)

    def export_data(self) -> tuple[str, list]:
        # 导出当前选中子页的记录数据
        cur = self.sub_tabs.currentWidget()
        if hasattr(cur, "export_data"):
            name, rows = cur.export_data()
            return (self.sub_tabs.tabText(self.sub_tabs.currentIndex()), rows)
        return ("目标输入解析", [])

    def clear_data(self) -> None:
        self.panel_3101.clear_data()
        self.panel_0c12.clear_data()
        self.panel_0c15.clear_data()
        self.panel_0b01.clear_data()
        self.panel_a002.clear_data()
        self.panel_a012.clear_data()
        self.panel_0802.clear_data()
