"""传输层抽象接口。新传输方式(串口/UDP/文件回放)实现此接口即可接入。"""
from __future__ import annotations

from typing import Callable, Optional

# 帧到达回调
FrameCallback = Callable[[bytes], None]


class ITransport:
    """传输层接口。

    实现者负责:启动监听/连接、收字节流喂入 Framer、完整帧回调 on_frame、
    可选回送 send()。生命周期:start/stop。
    """

    def __init__(self, on_frame: Optional[FrameCallback] = None) -> None:
        self.on_frame: Optional[FrameCallback] = on_frame

    def set_frame_callback(self, cb: FrameCallback) -> None:
        self.on_frame = cb

    def start(self) -> None:
        raise NotImplementedError

    def stop(self) -> None:
        raise NotImplementedError

    def send(self, data: bytes) -> None:
        """回送可见性报文等(可选)。"""
        raise NotImplementedError

    @property
    def is_running(self) -> bool:
        return False
