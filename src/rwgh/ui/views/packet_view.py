"""数据包明细视图:按分组展示单个数据包的全部字段(中文名/数值/单位)。"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                               QHeaderView, QFrame, QAbstractItemView)

from ..table_models import GenericTableModel
from ..widgets import BadgeDelegate, MonoDelegate, DataTableView
from ..labels import (packet_type_info, field_label, field_unit, field_group,
                      fmt_value, GROUP_ORDER, GROUP_COLORS, FORMAT_NAMES,
                      utc_from_2009)
from ...models.packet import ParsedPacket
from ..theme import C

_COLUMNS = ["#", "分组", "字段(中文)", "原始字段名", "解析值", "单位"]


class PacketView(QWidget):
    """单个数据包字段明细:分组着色 + 中英文对照 + 物理量值。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._model = GenericTableModel(_COLUMNS)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(10)

        # ---- 顶部包信息条 ----
        info = QFrame()
        info.setObjectName("Card")
        info.setFixedHeight(66)
        il = QHBoxLayout(info)
        il.setContentsMargins(16, 10, 16, 10)
        il.setSpacing(14)

        self._badge_name = QLabel("等待报文")
        self._badge_name.setStyleSheet(
            f"background:{C.BG_PANEL_2}; color:{C.FG_DIM};"
            "border-radius:11px; padding:4px 14px; font-weight:700;")
        self._badge_name.setFixedHeight(28)
        il.addWidget(self._badge_name)

        self._lbl_format = QLabel("格式:—")
        self._lbl_format.setStyleSheet(f"color:{C.FG_DIM};")
        il.addWidget(self._lbl_format)
        il.addSpacing(8)
        self._lbl_len = QLabel("长度:—")
        self._lbl_len.setStyleSheet(f"color:{C.FG_DIM};")
        il.addWidget(self._lbl_len)
        il.addSpacing(8)
        self._lbl_time = QLabel("历元:—")
        self._lbl_time.setStyleSheet(f"color:{C.OK};")
        il.addWidget(self._lbl_time)
        il.addStretch()
        self._lbl_check = QLabel("校验 —")
        self._lbl_check.setFixedHeight(28)
        self._lbl_check.setStyleSheet(
            f"color:{C.FG_FAINT}; background:{C.BG_PANEL_2};"
            "border-radius:11px; padding:4px 14px; font-weight:700;")
        il.addWidget(self._lbl_check)
        lay.addWidget(info)

        # ---- 字段表 ----
        self._table = DataTableView(empty_text="请在「报文流」中选择数据包")
        self._table.setModel(self._model)
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.verticalHeader().setVisible(False)
        self._table.setShowGrid(False)
        hdr = self._table.horizontalHeader()
        self._table.setColumnWidth(0, 44)
        self._table.setColumnWidth(1, 150)
        self._table.setColumnWidth(2, 160)
        self._table.setColumnWidth(3, 200)
        self._table.setColumnWidth(4, 260)
        hdr.setSectionResizeMode(4, QHeaderView.Stretch)
        self._table.setColumnWidth(5, 70)
        self._table.setItemDelegateForColumn(3, MonoDelegate(self._table))
        self._table.setItemDelegateForColumn(4, MonoDelegate(self._table))
        lay.addWidget(self._table, 1)

        self._hint = QLabel("在「报文流」中选择数据包后,此处显示字段明细")
        self._hint.setObjectName("HintLabel")
        lay.addWidget(self._hint)

    def show_packet(self, pkt: ParsedPacket) -> None:
        ptype = int(pkt.fields.get("packet_type", 0))
        cn_name, color = packet_type_info(ptype)

        # 顶部信息
        self._badge_name.setText(cn_name)
        self._badge_name.setStyleSheet(
            f"background:rgba(0,0,0,0.15); color:{color};"
            f"border:1.4px solid {color}; border-radius:11px;"
            "padding:3px 14px; font-weight:700;")
        self._lbl_format.setText(
            f"格式:{FORMAT_NAMES.get(pkt.format_name, pkt.format_name)}"
            f"  <span style='color:{C.FG_FAINT};font-family:Consolas;'>"
            f"({pkt.format_name})</span>")
        self._lbl_len.setText(f"长度:{len(pkt.raw)} 字节")
        secs = (pkt.fields.get("time_seconds")
                or pkt.fields.get("epoch_seconds"))
        if secs:
            self._lbl_time.setText(f"历元:{utc_from_2009(secs)} UTC")
        else:
            self._lbl_time.setText("历元:—")
        if pkt.checksum_ok:
            self._lbl_check.setText("校验通过")
            self._lbl_check.setStyleSheet(
                f"color:{C.OK}; background:{C.OK_SOFT};"
                "border-radius:11px; padding:4px 14px; font-weight:700;")
        else:
            self._lbl_check.setText("校验失败")
            self._lbl_check.setStyleSheet(
                f"color:{C.ERR}; background:{C.ERR_SOFT};"
                "border-radius:11px; padding:4px 14px; font-weight:700;")
        self._hint.setText("")

        # 字段行(按分组顺序)
        items = list(pkt.fields.items())
        items.sort(key=lambda kv: (self._group_index(kv[0]),))
        rows = []
        for i, (name, val) in enumerate(items, 1):
            grp = field_group(name)
            gcol = GROUP_COLORS.get(grp, C.FG_DIM)
            rows.append({
                "#": i,
                "分组": grp,
                "字段(中文)": field_label(name),
                "原始字段名": name,
                "解析值": fmt_value(name, val),
                "单位": field_unit(name),
                "_colors": {"分组": gcol,
                            "字段(中文)": C.FG,
                            "原始字段名": C.FG_FAINT,
                            "单位": C.FG_DIM},
            })
        self._model.replace_rows(rows)

    @staticmethod
    def _group_index(name: str) -> int:
        g = field_group(name)
        return GROUP_ORDER.index(g) if g in GROUP_ORDER else len(GROUP_ORDER)
