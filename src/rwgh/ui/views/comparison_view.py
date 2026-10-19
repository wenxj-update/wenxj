"""模板比对结果视图:结论卡 + 匹配率进度条 + 比对明细表 + 历史记录。

行背景:匹配行用 C.OK_SOFT(淡绿),差异行用 C.ERR_SOFT(淡红)。
比对结果列用 BadgeDelegate:匹配=绿,差异类型=红。
"""
from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                               QHeaderView, QFrame, QPushButton,
                               QProgressBar, QAbstractItemView)

from ..table_models import GenericTableModel
from ..widgets import BadgeDelegate, DataTableView
from ...models.comparison import ComparisonResult, Discrepancy
from ..theme import C

# 比对明细表列
_DETAIL_COLUMNS = ["序号", "指令名称", "期望码字", "实际码字",
                   "期望时间(s)", "实际时间(s)", "时间间隔(s)",
                   "比对结果", "差异说明"]
# 历史记录表列
_HIST_COLUMNS = ["时间", "目标", "模板", "结论", "匹配", "差异"]

# Discrepancy.kind -> 中文名
_KIND_CN = {
    "time": "时刻偏差",
    "code": "码字不符",
    "missing": "缺失指令",
    "extra": "多余指令",
    "param": "参数不符",
}


def _is_command(obj) -> bool:
    """鸭子类型判断对象是否为 Command(含 time_tag/codeword/name)。"""
    return (obj is not None
            and hasattr(obj, "time_tag")
            and hasattr(obj, "codeword")
            and hasattr(obj, "name"))


def _cmd_codeword_hex(cmd) -> str:
    """Command -> 码字 hex 串(codeword 优先,否则 code)。"""
    if cmd is None:
        return "—"
    cw = getattr(cmd, "codeword", b"")
    if cw:
        return cw.hex(" ").upper()
    return f"{int(getattr(cmd, 'code', 0)) & 0xFF:02X}"


def _cmd_time_tag(cmd) -> float | None:
    """Command -> time_tag(float),非 Command 返回 None。"""
    if cmd is None:
        return None
    tt = getattr(cmd, "time_tag", None)
    if tt is None:
        return None
    try:
        return float(tt)
    except (TypeError, ValueError):
        return None


def _val_str(v) -> str:
    """非 Command 值 -> 展示串(bytes 显示 hex)。"""
    if v is None:
        return "—"
    if isinstance(v, (bytes, bytearray)):
        return v.hex(" ").upper()
    return str(v)


def _short(v, n: int = 80) -> str:
    """截断过长字符串。"""
    s = "" if v is None else str(v)
    return s if len(s) <= n else s[:n] + "…"


class ComparisonResultView(QWidget):
    """指令模板比对结果页:结论卡 + 比对明细 + 历史记录。"""

    compare_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._detail_model = GenericTableModel(_DETAIL_COLUMNS)
        self._hist_model = GenericTableModel(_HIST_COLUMNS)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(10)

        # ---- 操作栏:开始比对按钮 ----
        btn_bar = QHBoxLayout()
        btn_bar.setContentsMargins(0, 0, 0, 0)
        self._btn_compare = QPushButton("开始比对")
        self._btn_compare.setFixedSize(120, 34)
        self._btn_compare.setCursor(Qt.PointingHandCursor)
        self._btn_compare.setStyleSheet(
            f"QPushButton{{background:{C.OK}; color:white;"
            f"border:none; border-radius:6px; font-size:14px; font-weight:700;}}"
            f"QPushButton:hover{{background:{C.BG_PANEL_2}; color:{C.OK};"
            f" border:1.5px solid {C.OK};}}"
            f"QPushButton:pressed{{background:{C.OK_SOFT};}}")
        self._btn_compare.clicked.connect(self.compare_requested.emit)
        btn_bar.addWidget(self._btn_compare)
        btn_bar.addStretch()
        lay.addLayout(btn_bar)

        # ---- 结论卡(QFrame#Card, fixedHeight=100) ----
        card = QFrame()
        card.setObjectName("Card")
        card.setFixedHeight(100)
        cl = QHBoxLayout(card)
        cl.setContentsMargins(18, 12, 18, 12)
        cl.setSpacing(18)

        self._verdict = QLabel("等待比对")
        self._verdict.setFixedSize(120, 72)
        self._verdict.setAlignment(Qt.AlignCenter)
        self._verdict.setStyleSheet(
            f"background:{C.BG_PANEL_2}; color:{C.FG_FAINT};"
            "border-radius:10px; font-size:20px; font-weight:800;")
        cl.addWidget(self._verdict)

        mid = QVBoxLayout()
        mid.setSpacing(6)
        self._lbl_info = QLabel("指令模板:—  ·  目标:—")
        self._lbl_info.setStyleSheet(
            f"font-size:14px; font-weight:700; color:{C.FG};")

        prog_row = QHBoxLayout()
        self._prog = QProgressBar()
        self._prog.setRange(0, 100)
        self._prog.setValue(0)
        self._prog.setFixedWidth(380)
        self._prog.setFormat("匹配率 %p%")
        self._lbl_counts = QLabel("匹配 0  ·  差异 0")
        self._lbl_counts.setStyleSheet(
            f"font-family:Consolas; color:{C.FG_DIM};")
        prog_row.addWidget(self._prog)
        prog_row.addWidget(self._lbl_counts)
        prog_row.addStretch()

        mid.addWidget(self._lbl_info)
        mid.addLayout(prog_row)
        cl.addLayout(mid)
        cl.addStretch()
        lay.addWidget(card)

        # ---- 比对明细表 ----
        self._detail_table = DataTableView(empty_text="暂无比对记录")
        self._detail_table.setModel(self._detail_model)
        self._detail_table.setAlternatingRowColors(True)
        self._detail_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._detail_table.verticalHeader().setVisible(False)
        self._detail_table.setShowGrid(False)
        dh = self._detail_table.horizontalHeader()
        self._detail_table.setColumnWidth(0, 50)
        self._detail_table.setColumnWidth(1, 180)
        self._detail_table.setColumnWidth(2, 200)
        self._detail_table.setColumnWidth(3, 200)
        self._detail_table.setColumnWidth(4, 110)
        self._detail_table.setColumnWidth(5, 110)
        self._detail_table.setColumnWidth(6, 110)
        self._detail_table.setColumnWidth(7, 100)
        dh.setSectionResizeMode(8, QHeaderView.Stretch)
        self._detail_badge = BadgeDelegate(self._detail_table)
        self._detail_table.setItemDelegateForColumn(7, self._detail_badge)
        lay.addWidget(self._detail_table, 3)

        # ---- 历史比对记录(最大高度 190) ----
        t_hist = QLabel("历史比对记录")
        t_hist.setObjectName("SectionTitle")
        lay.addWidget(t_hist)
        self._hist_table = DataTableView(empty_text="暂无历史比对记录")
        self._hist_table.setModel(self._hist_model)
        self._hist_table.setAlternatingRowColors(True)
        self._hist_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._hist_table.verticalHeader().setVisible(False)
        self._hist_table.setShowGrid(False)
        self._hist_table.setMaximumHeight(190)
        hh = self._hist_table.horizontalHeader()
        self._hist_table.setColumnWidth(0, 140)
        self._hist_table.setColumnWidth(1, 130)
        self._hist_table.setColumnWidth(2, 220)
        self._hist_table.setColumnWidth(3, 90)
        self._hist_table.setColumnWidth(4, 80)
        hh.setSectionResizeMode(5, QHeaderView.Stretch)
        self._hist_badge = BadgeDelegate(self._hist_table)
        self._hist_table.setItemDelegateForColumn(3, self._hist_badge)
        lay.addWidget(self._hist_table, 2)

    # ---------- 数据接入 ----------

    def on_comparison(self, cmp: ComparisonResult) -> None:
        """接收比对结果,刷新结论卡、明细表与历史记录。"""
        passed = cmp.passed
        total = cmp.match_count + cmp.discrepancy_count
        rate = int(round(100.0 * cmp.match_count / total)) if total else 0

        # ---- 结论卡 ----
        if passed:
            self._verdict.setText("通过")
            self._verdict.setStyleSheet(
                f"background:{C.OK_SOFT}; color:{C.OK};"
                f" border:1.5px solid {C.OK};"
                "border-radius:10px; font-size:20px; font-weight:800;")
        else:
            self._verdict.setText("未通过")
            self._verdict.setStyleSheet(
                f"background:{C.ERR_SOFT}; color:{C.ERR};"
                f" border:1.5px solid {C.ERR};"
                "border-radius:10px; font-size:20px; font-weight:800;")
        self._prog.setValue(100 if passed else rate)
        self._lbl_info.setText(
            f"指令模板:{cmp.template_name}  ·  目标:{cmp.target_id}")
        self._lbl_counts.setText(
            f"匹配 {cmp.match_count}  ·  差异 {cmp.discrepancy_count}"
            f"  (检查项 {total})")

        # ---- 比对明细表 ----
        rows = self._build_detail_rows(cmp)
        self._detail_model.replace_rows(rows)

        # ---- 历史记录 ----
        ts = datetime.now().strftime("%H:%M:%S")
        self._hist_model.append_row({
            "时间": ts,
            "目标": cmp.target_id,
            "模板": cmp.template_name,
            "结论": "通过" if passed else "未通过",
            "匹配": cmp.match_count,
            "差异": cmp.discrepancy_count,
            "_badges": {"结论": C.OK if passed else C.ERR},
            "_colors": {"差异": C.OK if passed else C.ERR},
        })
        self._hist_table.scrollToBottom()

    def _build_detail_rows(self, cmp: ComparisonResult) -> list[dict]:
        """从 ComparisonResult 生成比对明细行。"""
        rows: list[dict] = []
        seq_no = 0

        # 匹配项:期望=实际,时间间隔=0
        for cmd in cmp.matches:
            seq_no += 1
            cw = _cmd_codeword_hex(cmd)
            tt = _cmd_time_tag(cmd)
            tt_str = f"{tt:.3f}" if tt is not None else "—"
            rows.append({
                "序号": seq_no,
                "指令名称": getattr(cmd, "name", "") or "—",
                "期望码字": cw,
                "实际码字": cw,
                "期望时间(s)": tt_str,
                "实际时间(s)": tt_str,
                "时间间隔(s)": "0.000",
                "比对结果": "匹配",
                "差异说明": "",
                "_badges": {"比对结果": C.OK},
                "_row_bg": C.OK_SOFT,
                "_colors": {"期望码字": C.PKT_DATA,
                            "实际码字": C.PKT_DATA},
            })

        # 差异项:按 kind 映射中文名
        for d in cmp.discrepancies:
            seq_no += 1
            kind_cn = _KIND_CN.get(d.kind, d.kind)
            exp_cmd = d.expected
            act_cmd = d.actual
            exp_is_cmd = _is_command(exp_cmd)
            act_is_cmd = _is_command(act_cmd)

            # 期望/实际码字与时间
            if exp_is_cmd:
                exp_cw = _cmd_codeword_hex(exp_cmd)
                exp_tt = _cmd_time_tag(exp_cmd)
            else:
                exp_cw = _val_str(exp_cmd)
                exp_tt = None
            if act_is_cmd:
                act_cw = _cmd_codeword_hex(act_cmd)
                act_tt = _cmd_time_tag(act_cmd)
            else:
                act_cw = _val_str(act_cmd)
                act_tt = None

            exp_tt_str = f"{exp_tt:.3f}" if exp_tt is not None else "—"
            act_tt_str = f"{act_tt:.3f}" if act_tt is not None else "—"
            if exp_tt is not None and act_tt is not None:
                interval = f"{act_tt - exp_tt:.3f}"
            else:
                interval = "—"

            # 指令名称:优先取 expected/actual 的 name,否则取序号
            if exp_is_cmd and getattr(exp_cmd, "name", ""):
                name = exp_cmd.name
            elif act_is_cmd and getattr(act_cmd, "name", ""):
                name = act_cmd.name
            elif d.index >= 0:
                name = f"指令 #{d.index + 1}"
            else:
                name = "—"

            rows.append({
                "序号": seq_no,
                "指令名称": name,
                "期望码字": _short(exp_cw),
                "实际码字": _short(act_cw),
                "期望时间(s)": exp_tt_str,
                "实际时间(s)": act_tt_str,
                "时间间隔(s)": interval,
                "比对结果": kind_cn,
                "差异说明": d.detail,
                "_badges": {"比对结果": C.ERR},
                "_row_bg": C.ERR_SOFT,
                "_colors": {"期望码字": C.PKT_DATA,
                            "实际码字": C.ERR},
                "_tooltips": {"期望码字": "" if exp_cmd is None else str(exp_cmd),
                              "实际码字": "" if act_cmd is None else str(act_cmd),
                              "差异说明": d.detail},
            })
        return rows

    def export_data(self) -> tuple[str, list]:
        rows = []
        for row in self._detail_model._rows:
            clean = {k: v for k, v in row.items() if not k.startswith("_")}
            clean["来源"] = "比对明细"
            rows.append(clean)
        for row in self._hist_model._rows:
            clean = {k: v for k, v in row.items() if not k.startswith("_")}
            clean["来源"] = "历史记录"
            rows.append(clean)
        return ("模板比对结果", rows)

    def clear_data(self) -> None:
        self._detail_model.clear()
        self._hist_model.clear()
