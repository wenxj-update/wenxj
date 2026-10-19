"""Socket 工作线程:拥有 TcpServerTransport,帧到达 emit Qt 信号。"""
from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Signal

from ...core.config import FrameConfig
from ...transport.tcp_server import TcpServerTransport

_log = logging.getLogger("rwgh.ui.socket_worker")


class SocketWorker(QObject):
    """TCP 收包 worker。

    TcpServerTransport 内部使用 threading.Thread 收包,本 worker 仅持有
    并把 on_frame 回调桥接为 Qt 信号(跨线程自动 queued 到主线程)。
    """

    frame_ready = Signal(bytes)
    connection_changed = Signal(str)

    def __init__(self, host: str, port: int, frame_cfg: FrameConfig,
                 parent=None) -> None:
        super().__init__(parent)
        self._transport = TcpServerTransport(
            host, port, frame_cfg,
            on_frame=self._on_frame,
            on_connect=lambda addr: self.connection_changed.emit(
                f"STK connected: {addr}"),
        )

    def _on_frame(self, frame: bytes) -> None:
        # 在 transport 线程中调用,emit 触发 queued 到主线程
        self.frame_ready.emit(frame)

    @property
    def transport(self):
        return self._transport

    def start(self) -> None:
        self._transport.start()

    def stop(self) -> None:
        self._transport.stop()
