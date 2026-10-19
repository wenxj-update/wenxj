"""报文流视图:实时数据包列表 + 顶部分类统计。"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                               QHeaderView, QAbstractItemView)

from ..table_models import GenericTableModel
from ..widgets import StatCard, BadgeDelegate, MonoDelegate, DataTableView
from ..labels import (packet_type_info, fmt_hex_16, utc_clock,
                      packet_summary, FORMAT_NAMES)
from ...models.packet import ParsedPacket
from ..theme import C

_COLUMNS = ["序号", "包类型", "仿真时刻", "关键内容", "长度", "原始帧(Hex)"]


class MessageView(QWidget):
    """报文实时流:统计卡片 + 彩色包类型徽章 + 等宽 hex。"""

    packet_selected = Signal(object)  # ParsedPacket

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._model = GenericTableModel(_COLUMNS)
        self._counter = 0
        self._counts = {0x0B01: 0, 0xA012: 0, 0xA002: 0}
        self._latest_secs: float | None = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(10)

        # ---- 统计卡片 ----
        cards = QHBoxLayout()
        cards.setSpacing(10)
        self.card_total = StatCard("接收报文总数", "0", C.ACCENT, mono=True)
        self.card_time = StatCard("星时数据包", "0", C.PKT_TIME, mono=True)
        self.card_elem = StatCard("轨道根数包", "0", C.PKT_ELEM, mono=True)
        self.card_data = StatCard("轨道数据包", "0", C.PKT_DATA, mono=True)
        self.card_clock = StatCard("最新仿真时刻", "--:--:--", C.OK)
        for c in (self.card_total, self.card_time, self.card_elem,
                  self.card_data, self.card_clock):
            cards.addWidget(c)
        lay.addLayout(cards)

        # ---- 表格 ----
        self._table = DataTableView(empty_text="等待 STK 报文… 启动 STK 或点击「注入测试报文」")
        self._table.setModel(self._model)
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.verticalHeader().setVisible(False)
        self._table.setShowGrid(False)
        self._table.setMinimumHeight(260)

        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.Fixed)
        self._table.setColumnWidth(0, 64)
        self._table.setColumnWidth(1, 132)
        self._table.setColumnWidth(2, 152)
        self._table.setColumnWidth(3, 320)
        self._table.setColumnWidth(4, 80)
        hdr.setSectionResizeMode(3, QHeaderView.Stretch)
        self._table.setColumnWidth(5, 260)

        self._badge = BadgeDelegate(self._table)
        self._table.setItemDelegateForColumn(1, self._badge)
        self._table.setItemDelegateForColumn(5, MonoDelegate(self._table))
        self._table.clicked.connect(self._on_click)
        lay.addWidget(self._table, 1)

        self._hint = QLabel("等待 STK 报文…  启动 STK 或点击「注入测试报文」")
        self._hint.setObjectName("HintLabel")
        lay.addWidget(self._hint)

    def on_parsed_packet(self, pkt: ParsedPacket) -> None:
        self._counter += 1
        ptype = int(pkt.fields.get("packet_type", 0))
        cn_name, color = packet_type_info(ptype)
        secs = (pkt.fields.get("time_seconds")
                or pkt.fields.get("epoch_seconds"))
        clock = utc_clock(secs) if secs else "—"

        if ptype in self._counts:
            self._counts[ptype] += 1
        if secs:
            self._latest_secs = float(secs)

        check_ok = pkt.checksum_ok
        row = {
            "序号": self._counter,
            "包类型": cn_name,
            "仿真时刻": clock,
            "关键内容": packet_summary(pkt.format_name, pkt.fields),
            "长度": f"{len(pkt.raw)} B",
            "原始帧(Hex)": fmt_hex_16(pkt.raw),
            "_pkt": pkt,
            "_badges": {"包类型": color},
            "_colors": {"仿真时刻": C.OK},
            "_tooltips": {"原始帧(Hex)": pkt.raw.hex(" ").upper(),
                          "包类型": f"0x{ptype:04X} · "
                                    f"{FORMAT_NAMES.get(pkt.format_name, pkt.format_name)}"},
        }
        if not check_ok:
            row["_row_bg"] = C.ERR_SOFT
            row["_colors"] = {"仿真时刻": C.ERR}
        self._model.append_row(row)
        self._table.scrollToBottom()
        self._hint.setText(f"最新报文:{cn_name}  校验:{'通过' if check_ok else '失败'}")
        self._refresh_cards()
        # 默认跟随最新包
        self.packet_selected.emit(pkt)

    def _refresh_cards(self) -> None:
        self.card_total.set_value(str(self._counter))
        self.card_time.set_value(str(self._counts[0x0B01]))
        self.card_elem.set_value(str(self._counts[0xA012]))
        self.card_data.set_value(str(self._counts[0xA002]))
        if self._latest_secs is not None:
            self.card_clock.set_value(utc_clock(self._latest_secs))

    def _on_click(self, index) -> None:
        row = self._model._rows[index.row()]  # noqa: SLF001
        pkt = row.get("_pkt")
        if pkt is not None:
            self.packet_selected.emit(pkt)
