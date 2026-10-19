"""校验算法:支持扩展新算法。

新算法在此模块加函数并注册到 _ALGOS 即可,无需改动解析器。
"""
from __future__ import annotations

import struct
import zlib
from typing import Callable

ChecksumFn = Callable[[bytes, int, int], int]


def _crc32(data: bytes, offset: int, length: int) -> int:
    return zlib.crc32(data[offset:offset + length]) & 0xFFFFFFFF


def _sum8(data: bytes, offset: int, length: int) -> int:
    return sum(data[offset:offset + length]) & 0xFF


def _xor8(data: bytes, offset: int, length: int) -> int:
    x = 0
    for b in data[offset:offset + length]:
        x ^= b
    return x & 0xFF


def _crc16_ccitt(data: bytes, offset: int, length: int) -> int:
    crc = 0xFFFF
    for b in data[offset:offset + length]:
        crc ^= b << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return crc & 0xFFFF


_ALGOS: dict[str, ChecksumFn] = {
    "crc32": _crc32,
    "sum8": _sum8,
    "xor8": _xor8,
    "crc16": _crc16_ccitt,
    "crc16_ccitt": _crc16_ccitt,
}


def register_checksum(name: str, fn: ChecksumFn) -> None:
    _ALGOS[name.lower()] = fn


def compute_checksum(data: bytes, algo: str, offset: int, length: int) -> int:
    fn = _ALGOS.get(algo.lower())
    if fn is None:
        raise KeyError(f"unknown checksum algo: {algo}")
    return fn(data, offset, length)


def read_checksum_field(data: bytes, offset: int, n_bytes: int, endian: str = "<") -> int:
    """从帧字节读出校验值。"""
    chunk = data[offset:offset + n_bytes]
    return int.from_bytes(chunk, "little" if endian == "<" else "big", signed=False)


def encode_checksum(value: int, n_bytes: int, endian: str = "<") -> bytes:
    return value.to_bytes(n_bytes, "little" if endian == "<" else "big", signed=False)
