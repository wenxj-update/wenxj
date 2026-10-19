"""事件桥接:把进程内 EventBus 事件转为主线程 Qt 信号(跨线程自动 queued)。"""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import QObject, Signal

from ..core.event_bus import EventBus, Topics


class QtEventBridge(QObject):
    """EventBus -> Qt 信号桥接。

    订阅各主题,在回调中 emit 对应 Qt 信号。由于订阅回调在工作线程执行,
    Qt 跨线程信号自动 queued 到主线程,UI 安全刷新。
    """

    raw_frame = Signal(bytes)
    stk_message = Signal(object)      # ParsedPacket
    parsed_packet = Signal(object)    # ParsedPacket
    visibility_result = Signal(object)  # list[VisibilityResult]
    visibility_report_frame = Signal(bytes)
    command_sequence = Signal(object)   # CommandSequence
    comparison_result = Signal(object)  # ComparisonResult

    def __init__(self, bus: EventBus, parent=None) -> None:
        super().__init__(parent)
        self._bus = bus
        self._unsub: list = []

    def start(self) -> None:
        b = self._bus
        self._unsub.append(b.subscribe(Topics.RAW_FRAME, self.raw_frame.emit))
        self._unsub.append(b.subscribe(Topics.STK_MESSAGE, self.stk_message.emit))
        self._unsub.append(b.subscribe(Topics.PARSED_PACKET, self.parsed_packet.emit))
        self._unsub.append(b.subscribe(Topics.VISIBILITY_RESULT, self.visibility_result.emit))
        self._unsub.append(b.subscribe(Topics.VISIBILITY_REPORT_FRAME,
                                       self.visibility_report_frame.emit))
        self._unsub.append(b.subscribe(Topics.COMMAND_SEQUENCE, self.command_sequence.emit))
        self._unsub.append(b.subscribe(Topics.COMPARISON_RESULT,
                                       self.comparison_result.emit))

    def stop(self) -> None:
        for u in self._unsub:
            u()
        self._unsub.clear()
