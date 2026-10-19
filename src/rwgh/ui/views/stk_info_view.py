"""STK 报文信息页:目标列表统计 + 最新报文摘要。

地面站与成像目标拆分为两个独立卡片,便于分类查看。
列顺序:经度在前、纬度在后(符合数据包格式定义)。
"""
from __future__ import annotations

from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                               QHeaderView, QFrame, QAbstractItemView)

from ..table_models import GenericTableModel
from ..widgets import StatCard, BadgeDelegate, SectionTitle, DataTableView
from ..labels import utc_clock, packet_type_info
from ..theme import C
from ...models.packet import ParsedPacket
from ...models.target import TargetPoint

# 列顺序:经度在前,纬度在后(与数据包格式一致)
_COLUMNS = ["序号", "目标编号", "经度(°)", "纬度(°)", "高度(km)", "来源"]


def _is_facility(target_id: str) -> bool:
    """目标编号含下划线为地面站(数传)。"""
    return "_" in target_id


class _TargetTable(QFrame):
    """单类目标表格卡片:标题 + 表格。"""

    def __init__(self, title: str, accent: str, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        self._model = GenericTableModel(_COLUMNS)

        cl = QVBoxLayout(self)
        cl.setContentsMargins(10, 6, 10, 8)
        cl.setSpacing(4)

        cl.addWidget(SectionTitle(title, accent=accent))

        self._table = DataTableView(empty_text=f"暂无{title.split('(')[0].strip()}")
        self._table.setModel(self._model)
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.verticalHeader().setVisible(False)
        self._table.verticalHeader().setDefaultSectionSize(24)
        self._table.setShowGrid(False)
        hdr = self._table.horizontalHeader()
        hdr.setFixedHeight(24)
        self._table.setColumnWidth(0, 50)
        self._table.setColumnWidth(1, 140)
        self._table.setColumnWidth(2, 100)
        self._table.setColumnWidth(3, 100)
        self._table.setColumnWidth(4, 90)
        hdr.setSectionResizeMode(5, QHeaderView.Stretch)
        self._badge = BadgeDelegate(self._table)
        self._table.setItemDelegateForColumn(1, self._badge)
        cl.addWidget(self._table, 1)

        self._count_label = QLabel("0 个")
        self._count_label.setStyleSheet(
            f"color:{accent}; font-size:11px; font-weight:600;")
        cl.addWidget(self._count_label)

    def set_rows(self, rows: list[dict]) -> None:
        self._model.replace_rows(rows)
        self._count_label.setText(f"{len(rows)} 个")

    def clear_data(self) -> None:
        self._model.clear()
        self._count_label.setText("0 个")

    def export_rows(self) -> list[dict]:
        return [{k: v for k, v in r.items() if not k.startswith("_")}
                for r in self._model._rows]


class StkInfoView(QWidget):
    """STK 报文信息页:目标统计卡 + 成像目标表 + 地面站表 + 最新报文摘要。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(6)

        # ---- 顶部 4 张统计卡:蓝/紫/橙/绿 ----
        cards = QHBoxLayout()
        cards.setSpacing(6)
        self.card_total = StatCard("目标总数", "0", C.ACCENT, mono=True)
        self.card_imaging = StatCard("成像目标", "0", C.PKT_DATA, mono=True)
        self.card_facility = StatCard("地面站", "0", C.FACILITY, mono=True)
        self.card_clock = StatCard("最新仿真时刻", "--:--:--", C.OK)
        for c in (self.card_total, self.card_imaging,
                  self.card_facility, self.card_clock):
            cards.addWidget(c)
        lay.addLayout(cards)

        # ---- 成像目标表(独立卡片,占主要空间) ----
        self._imaging_view = _TargetTable("成像目标列表", C.TARGET)
        lay.addWidget(self._imaging_view, 1)

        # ---- 地面站表(独立卡片,占主要空间) ----
        self._facility_view = _TargetTable("地面站列表", C.FACILITY)
        lay.addWidget(self._facility_view, 1)

        # ---- 最新报文摘要区(QFrame#Card,压缩高度) ----
        summary = QFrame()
        summary.setObjectName("Card")
        summary.setFixedHeight(40)
        sl = QHBoxLayout(summary)
        sl.setContentsMargins(14, 4, 14, 4)
        sl.setSpacing(14)

        self._lbl_pkt_title = QLabel("最新报文:—")
        self._lbl_pkt_title.setStyleSheet(
            f"color:{C.FG}; font-weight:700; font-size:12px;")
        sl.addWidget(self._lbl_pkt_title)

        self._lbl_pkt_time = QLabel("仿真时刻:—")
        self._lbl_pkt_time.setStyleSheet(
            f"color:{C.OK}; font-size:12px;")
        sl.addWidget(self._lbl_pkt_time)

        self._lbl_pkt_pos = QLabel("J2000 位置:—")
        self._lbl_pkt_pos.setStyleSheet(
            f"font-family:Consolas,'Cascadia Mono',monospace;"
            f" color:{C.PKT_DATA}; font-size:11px;")
        sl.addWidget(self._lbl_pkt_pos)
        sl.addStretch()
        lay.addWidget(summary)

    # ---------- 数据接入 ----------

    def on_targets_ready(self, targets: list[TargetPoint]) -> None:
        """接收目标列表,按类型拆分到两个表格。"""
        img_rows = []
        fac_rows = []
        for i, t in enumerate(targets, 1):
            is_fac = _is_facility(t.id)
            source = "Facility" if is_fac else "Target"
            color = C.FACILITY if is_fac else C.TARGET
            row = {
                "序号": i,
                "目标编号": t.id,
                "经度(°)": f"{t.lon:.4f}",
                "纬度(°)": f"{t.lat:.4f}",
                "高度(km)": f"{t.alt:.3f}",
                "来源": source,
                "_badges": {"目标编号": color},
                "_colors": {"来源": C.FG_DIM},
            }
            (fac_rows if is_fac else img_rows).append(row)
        self._imaging_view.set_rows(img_rows)
        self._facility_view.set_rows(fac_rows)

        self.card_total.set_value(str(len(targets)))
        self.card_imaging.set_value(str(len(img_rows)))
        self.card_facility.set_value(str(len(fac_rows)))

    def on_parsed_packet(self, pkt: ParsedPacket) -> None:
        """接收最新报文,刷新仿真时刻与卫星位置摘要。"""
        ptype = int(pkt.fields.get("packet_type", 0))
        cn_name, _ = packet_type_info(ptype)
        self._lbl_pkt_title.setText(f"最新报文:{cn_name}")

        secs = (pkt.fields.get("time_seconds")
                or pkt.fields.get("epoch_seconds"))
        if secs is not None:
            try:
                s = float(secs)
                clock = utc_clock(s)
                self.card_clock.set_value(clock)
                self._lbl_pkt_time.setText(f"仿真时刻:{clock}")
            except (TypeError, ValueError):
                self._lbl_pkt_time.setText("仿真时刻:—")
        else:
            self._lbl_pkt_time.setText("仿真时刻:—")

        # J2000 卫星位置(轨道数据包)
        x = pkt.fields.get("j2k_x")
        y = pkt.fields.get("j2k_y")
        z = pkt.fields.get("j2k_z")
        if x is not None and y is not None and z is not None:
            try:
                self._lbl_pkt_pos.setText(
                    f"J2000 位置  X={float(x):,.1f}  "
                    f"Y={float(y):,.1f}  Z={float(z):,.1f} m")
            except (TypeError, ValueError):
                self._lbl_pkt_pos.setText("J2000 位置:—")
        else:
            self._lbl_pkt_pos.setText("J2000 位置:—")

    def export_data(self) -> tuple[str, list]:
        rows = self._imaging_view.export_rows() + self._facility_view.export_rows()
        return ("STK报文信息", rows)

    def clear_data(self) -> None:
        self._imaging_view.clear_data()
        self._facility_view.clear_data()
        self.card_total.set_value("0")
        self.card_imaging.set_value("0")
        self.card_facility.set_value("0")
        self.card_clock.set_value("--:--:--")
