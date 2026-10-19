"""TCP 服务端传输:Python 监听,STK 侧 Connect 推送连接并实时发送报文。

纯 Python(threading),不依赖 Qt。UI 层用 SocketWorker 包装为 QThread。
"""
from __future__ import annotations

import logging
import socket
import threading
from typing import Optional

from ..core.config import FrameConfig
from ..core.exceptions import TransportError
from .base import ITransport, FrameCallback
from .framer import Framer

_log = logging.getLogger("rwgh.transport.tcp")


class TcpServerTransport(ITransport):
    """TCP 监听服务端:接受 STK 推送连接,收字节流喂 Framer,完整帧回调。"""

    def __init__(self, host: str, port: int, frame_cfg: FrameConfig,
                 on_frame: Optional[FrameCallback] = None,
                 on_connect: Optional[FrameCallback] = None) -> None:
        super().__init__(on_frame)
        self._host = host
        self._port = port
        self._framer = Framer(frame_cfg)
        self._server: Optional[socket.socket] = None
        self._conn: Optional[socket.socket] = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._running = False
        self._lock = threading.Lock()
        self._on_connect = on_connect

    def start(self) -> None:
        if self._running:
            return
        self._stop.clear()
        self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server.bind((self._host, self._port))
        self._server.listen(1)
        self._server.settimeout(0.5)
        self._running = True
        self._thread = threading.Thread(target=self._serve, daemon=True,
                                       name="TcpServerTransport")
        self._thread.start()
        _log.info("TCP server listening %s:%d", self._host, self._port)

    def stop(self) -> None:
        self._stop.set()
        self._running = False
        if self._conn is not None:
            try:
                self._conn.close()
            except OSError:
                pass
            self._conn = None
        if self._server is not None:
            try:
                self._server.close()
            except OSError:
                pass
            self._server = None
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    @property
    def is_running(self) -> bool:
        return self._running

    def send(self, data: bytes) -> None:
        with self._lock:
            conn = self._conn
        if conn is None:
            raise TransportError("no active connection to send")
        try:
            conn.sendall(data)
        except OSError as e:
            raise TransportError(f"send failed: {e}") from e

    def _serve(self) -> None:
        while not self._stop.is_set():
            # 接受连接
            try:
                conn, addr = self._server.accept()  # type: ignore[union-attr]
            except socket.timeout:
                continue
            except OSError:
                break
            conn.settimeout(0.5)
            with self._lock:
                self._conn = conn
            _log.info("STK client connected from %s", addr)
            if self._on_connect:
                try:
                    self._on_connect(addr)  # type: ignore[misc]
                except Exception:  # noqa: BLE001
                    _log.exception("on_connect callback error")
            try:
                self._handle_conn(conn)
            finally:
                try:
                    conn.close()
                except OSError:
                    pass
                with self._lock:
                    self._conn = None
                _log.info("STK client disconnected")

    def _handle_conn(self, conn: socket.socket) -> None:
        while not self._stop.is_set():
            try:
                chunk = conn.recv(4096)
            except socket.timeout:
                continue
            except OSError:
                break
            if not chunk:
                break  # 对端关闭
            for frame in self._framer.feed(chunk):
                if self.on_frame is not None:
                    try:
                        self.on_frame(frame)
                    except Exception:  # noqa: BLE001
                        _log.exception("on_frame callback error")
