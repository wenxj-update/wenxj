"""字段类型 -> struct 字符映射。

约定类型字符串:
  标量: u8 i8 u16 i16 u32 i32 u64 i64 f32 f64
  字节串: bytes[N]  -> 原始 N 字节(bytes)
  字符串: char[N]   -> ASCII 解码后的 str

每种字段在 struct.unpack 结果中恰好产出 1 个元素,保证字段<->值 1:1 映射。
"""
from __future__ import annotations

import struct
from typing import Any

from .spec import FieldSpec
from ..core.exceptions import ParseError

_SCALAR: dict[str, str] = {
    "u8": "B", "i8": "b",
    "u16": "H", "i16": "h",
    "u32": "I", "i32": "i",
    "u64": "Q", "i64": "q",
    "f32": "f", "f64": "d",
}


def parse_type(type_str: str) -> tuple[str, int, str]:
    """解析类型字符串 -> (struct_char, byte_len, kind)。

    kind: "scalar" | "bytes" | "char"
    """
    t = type_str.strip().lower()
    if t in _SCALAR:
        c = _SCALAR[t]
        return c, struct.calcsize(c), "scalar"
    if t.startswith("char[") and t.endswith("]"):
        n = int(t[5:-1])
        if n <= 0:
            raise ParseError(f"invalid char length: {type_str}")
        return f"{n}s", n, "char"
    if t.startswith("bytes[") and t.endswith("]"):
        n = int(t[6:-1])
        if n <= 0:
            raise ParseError(f"invalid bytes length: {type_str}")
        return f"{n}s", n, "bytes"
    raise ParseError(f"unknown field type: {type_str}")


def coerce_value(field: FieldSpec, raw: Any) -> Any:
    """将 struct 产出的原始值按字段规格转换为业务值。"""
    _, _, kind = parse_type(field.type)

    if kind == "char":
        # ASCII 字符串,去尾部 NUL/空白
        if isinstance(raw, (bytes, bytearray)):
            text = raw.split(b"\x00", 1)[0].decode("ascii", errors="replace").rstrip()
        else:
            text = str(raw)
        return text

    if kind == "bytes":
        return bytes(raw) if not isinstance(raw, bytes) else raw

    # scalar: 应用 scale
    val = raw
    if field.scale != 1.0:
        val = val * field.scale
    # 应用 enum
    if field.enum is not None:
        # 优先返回枚举名,但保留原值便于展示
        name = field.enum.get(int(raw))
        if name is not None:
            return name
    return val


def build_frame_struct(field: FieldSpec) -> struct.Struct:
    """为单字段构造 struct(仅该字段)。"""
    char, _blen, _kind = parse_type(field.type)
    return struct.Struct(f"{field.endian}{char}")
