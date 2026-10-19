"""组帧状态机:从字节流中按 magic+length 切出完整二进制定长帧。

处理粘包/拆包。仅做基于长度的重组,不做校验(校验由解析器 FormatSpec 完成)。
"""
from __future__ import annotations

from typing import Iterator

from ..core.config import FrameConfig
from ..core.exceptions import FramerError
from . import codec


class Framer:
    """字节流 -> 完整帧 切分器。

    支持单 magic(FrameConfig.magic)或多 magic 集合(magic_list 参数):
    STK 推送多种包类型,各包以"包类型"(2字节)开头,magic 集合即所有合法包类型。
    """

    def __init__(self, cfg: FrameConfig,
                 magic_list: list[bytes] | None = None) -> None:
        self.cfg = cfg
        self._buf = bytearray()
        # 优先用 magic_list,否则用 cfg.magic
        if magic_list:
            self._magics = [bytes(m) for m in magic_list if m]
        elif cfg.magic:
            self._magics = [cfg.magic]
        else:
            self._magics = []
        # 单 magic 长度(假设等长,取第一个)
        self._magic_len = len(self._magics[0]) if self._magics else 0
        self._partial_magic_keep = max(0, self._magic_len - 1)

    def feed(self, data: bytes) -> Iterator[bytes]:
        """喂入一段字节,产出 0 个或多个完整帧。"""
        self._buf.extend(data)
        while True:
            frame = self._extract_one()
            if frame is None:
                break
            yield frame

    def _extract_one(self) -> bytes | None:
        cfg = self.cfg
        if not self._buf:
            return None

        # 1) magic 对齐(假设 magic_offset=0,帧以 magic 开头)
        #    支持多 magic 集合:任一匹配即认为帧开始
        if self._magics:
            idx = -1
            for m in self._magics:
                j = self._buf.find(m)
                if j >= 0 and (idx < 0 or j < idx):
                    idx = j
            if idx < 0:
                # 保留尾部若干字节,避免跨段 magic 被丢
                if len(self._buf) > self._partial_magic_keep:
                    del self._buf[:len(self._buf) - self._partial_magic_keep]
                return None
            if idx > 0:
                # 丢弃 magic 之前的杂字节
                del self._buf[:idx]
        # 现在 buf 开头即 magic(若配置了 magic)

        # 2) 读长度字段
        length_val = codec.read_length(self._buf, cfg)
        if length_val is None:
            return None  # 等更多字节

        total = codec.total_frame_length(length_val, cfg)
        if total <= 0 or total > cfg.max_frame:
            # 长度非法,丢弃当前 magic 重新同步
            drop = self._magic_len if self._magic_len else 1
            del self._buf[:drop]
            return None

        # 3) 等待整帧完整
        if len(self._buf) < total:
            return None

        frame = bytes(self._buf[:total])
        del self._buf[:total]
        return frame

    def build(self, payload: bytes) -> bytes:
        """组包:对可见性报文回送等场景,直接透传(payload 已是完整帧)。

        若传输层需要额外封装(如加头/尾),在此扩展。
        """
        return payload
