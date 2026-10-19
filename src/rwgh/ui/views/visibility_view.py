"""可见性结果视图:批次统计卡 + 目标徽章 + 仰角分档高亮。"""
from __future__ import annotations

from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                               QHeaderView, QFrame, QAbstractItemView)

from ..table_models import GenericTableModel
from ..widgets import StatCard, BadgeDelegate, DataTableView
from ...models.visibility import VisibilityResult
from ..theme import C

_COLUMNS = ["目标", "类型", "进站时刻 AOS", "出站时刻 LOS",
            "可见时长", "最大仰角"]


def _el_bucket(el: float) -> tuple[str, str]:
    """仰角分档 -> (文字, 颜色)。"""
    if el >= 60.0:
        return "高仰角 ≥60°", C.OK
    if el >= 30.0:
        return "良好 30~60°", C.ACCENT
    return "低仰角 <30°", C.PKT_TIME


def _is_facility(target_id: str) -> bool:
    """场景内设施命名形如 kashi_01;成像目标形如 11-100。"""
    return "_" in target_id


class VisibilityView(QWidget):
    """可见性窗口列表(最新批次)。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._model = GenericTableModel(_COLUMNS)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(10)

        # ---- 批次信息条 ----
        info = QFrame()
        info.setObjectName("Card")
        info.setFixedHeight(56)
        il = QHBoxLayout(info)
        il.setContentsMargins(16, 8, 16, 8)
        self._lbl_sat = QLabel("卫星:—")
        self._lbl_sat.setStyleSheet(f"color:{C.FG}; font-weight:700;")
        self._lbl_batch = QLabel("等待可见性结果…")
        self._lbl_batch.setStyleSheet(f"color:{C.FG_DIM};")
        il.addWidget(self._lbl_sat)
        il.addSpacing(24)
        il.addWidget(self._lbl_batch)
        il.addStretch()
        lay.addWidget(info)

        # ---- 统计卡 ----
        cards = QHBoxLayout()
        cards.setSpacing(10)
        self.card_windows = StatCard("可见窗口总数", "0", C.ACCENT, mono=True)
        self.card_targets = StatCard("可见目标数", "0", C.PKT_DATA, mono=True)
        self.card_maxel = StatCard("批次最高仰角", "—", C.OK)
        self.card_high = StatCard("高仰角窗口(≥60°)", "0", C.OK, mono=True)
        for c in (self.card_windows, self.card_targets,
                  self.card_maxel, self.card_high):
            cards.addWidget(c)
        lay.addLayout(cards)

        # ---- 窗口表 ----
        self._table = DataTableView(empty_text="暂无可见性窗口,请先计算可见性")
        self._table.setModel(self._model)
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.verticalHeader().setVisible(False)
        self._table.setShowGrid(False)
        hdr = self._table.horizontalHeader()
        self._table.setColumnWidth(0, 140)
        self._table.setColumnWidth(1, 130)
        self._table.setColumnWidth(2, 190)
        self._table.setColumnWidth(3, 190)
        self._table.setColumnWidth(4, 110)
        hdr.setSectionResizeMode(5, QHeaderView.Stretch)
        self._badge = BadgeDelegate(self._table)
        self._table.setItemDelegateForColumn(0, self._badge)
        self._table.setItemDelegateForColumn(5, self._badge)
        lay.addWidget(self._table, 1)

    def on_visibility(self, results) -> None:
        if not isinstance(results, list):
            results = [results]
        rows = []
        total = 0
        high = 0
        max_el = -1.0
        sat_name = "—"
        for r in results:
            sat_name = r.satellite
            for w in r.windows:
                total += 1
                max_el = max(max_el, w.max_el)
                el_text, el_color = _el_bucket(w.max_el)
                if w.max_el >= 60.0:
                    high += 1
                is_fac = _is_facility(w.target_id)
                ttype = "地面站(设施)" if is_fac else "成像目标"
                tcolor = C.FACILITY if is_fac else C.TARGET
                rows.append({
                    "目标": w.target_id,
                    "类型": ttype,
                    "进站时刻 AOS": w.aos.strftime("%Y-%m-%d %H:%M:%S"),
                    "出站时刻 LOS": w.los.strftime("%Y-%m-%d %H:%M:%S"),
                    "可见时长": f"{w.duration_sec:,.1f} s",
                    "最大仰角": f"{w.max_el:.2f}°  {el_text}",
                    "_badges": {"目标": tcolor, "最大仰角": el_color},
                    "_colors": {"类型": tcolor,
                                "可见时长": C.FG_DIM},
                })
        self._model.replace_rows(rows)

        self._lbl_sat.setText(f"卫星:{sat_name}")
        self._lbl_batch.setText(f"本批次共 {total} 个可见窗口")
        self.card_windows.set_value(str(total))
        self.card_targets.set_value(str(total))
        self.card_high.set_value(str(high))
        if max_el >= 0:
            self.card_maxel.set_value(f"{max_el:.2f}°")
