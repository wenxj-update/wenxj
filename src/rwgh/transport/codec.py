"""传输帧编解码辅助:长度字段读取、校验计算(基于 FrameConfig)。"""
from __future__ import annotations

import struct
from typing import Optional

from ..core.config import FrameConfig
from ..core.exceptions import FramerError
from ..parsing.checksum import compute_checksum, read_checksum_field


def read_length(buf: bytes, cfg: FrameConfig) -> Optional[int]:
    """从缓冲区读长度字段,字节数不足返回 None。"""
    need = cfg.length_offset + cfg.length_bytes
    if len(buf) < need:
        return None
    chunk = buf[cfg.length_offset:cfg.length_offset + cfg.length_bytes]
    # 长度字段按大端解读(报文为大端字节序)
    return int.from_bytes(chunk, "big", signed=False)


def total_frame_length(length_value: int, cfg: FrameConfig) -> int:
    """根据 length_includes 语义把长度字段值换算为整帧长度。"""
    if cfg.length_includes == "frame":
        return length_value
    if cfg.length_includes == "body":
        # body 长度 + 头(magic_offset+len(magic) 或 length_offset+length_bytes) + 校验
        header = max(cfg.magic_offset + len(cfg.magic),
                     cfg.length_offset + cfg.length_bytes)
        checksum_size = 0
        if cfg.checksum_field >= 0:
            checksum_size = 4
        return length_value + header + checksum_size
    raise FramerError(f"unknown length_includes: {cfg.length_includes}")


def find_magic(buf: bytes, cfg: FrameConfig) -> int:
    """在 buf 中查找 magic 起始偏移,找不到返回 -1。"""
    if not cfg.magic:
        return 0
    return buf.find(cfg.magic)


def frame_checksum_ok(frame: bytes, cfg: FrameConfig) -> bool:
    """按 FrameConfig 校验整帧 checksum(可选)。无校验配置返回 True。"""
    if cfg.checksum_field < 0:
        return True
    if cfg.checksum_field >= len(frame):
        return False
    expected = compute_checksum(frame, cfg.checksum_algo, cfg.checksum_offset,
                                cfg.checksum_field - cfg.checksum_offset)
    stored = read_checksum_field(frame, cfg.checksum_field, 4)
    return expected == stored
