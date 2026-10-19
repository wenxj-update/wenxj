"""帧解析器:按 FormatSpec 把二进制定长帧解析为 ParsedPacket。

实现说明:
- 每字段预编译 struct.Struct(按 type+endian 缓存),用 unpack_from 在指定偏移取值,
  健壮支持任意布局(间隙/混合端序/字段不连续)。
- 校验:先校验 magic,再校验 checksum,最后解析字段。
- 组包(build)是解析的逆过程,供可见性报文回送复用同一 FormatSpec。
"""
from __future__ import annotations

import struct
from typing import Any

from .checksum import compute_checksum, read_checksum_field, encode_checksum
from .fields import parse_type, coerce_value, build_frame_struct
from .spec import FormatSpec, FieldSpec
from ..core.exceptions import ParseError
from ..models.packet import ParsedPacket


class FrameParser:
    """二进制定长帧解析/组包器。"""

    def __init__(self) -> None:
        # (type, endian) -> struct.Struct 缓存
        self._struct_cache: dict[tuple[str, str], struct.Struct] = {}

    def _get_struct(self, field: FieldSpec) -> struct.Struct:
        key = (field.type.lower(), field.endian)
        st = self._struct_cache.get(key)
        if st is None:
            st = build_frame_struct(field)
            self._struct_cache[key] = st
        return st

    # ---------- 解析 ----------

    def parse(self, frame: bytes, spec: FormatSpec) -> ParsedPacket:
        if len(frame) != spec.total_length:
            raise ParseError(
                f"[{spec.name}] frame length {len(frame)} != expected {spec.total_length}"
            )

        # magic 校验
        checksum_ok = True
        if spec.magic is not None:
            actual = frame[spec.magic_offset:spec.magic_offset + len(spec.magic)]
            if actual != spec.magic:
                raise ParseError(
                    f"[{spec.name}] magic mismatch: {actual.hex()} != {spec.magic.hex()}"
                )

        # checksum 校验
        if spec.checksum is not None:
            cs = spec.checksum
            expected = compute_checksum(frame, cs.algo, cs.offset, cs.length)
            stored = read_checksum_field(frame, cs.field_offset, cs.field_bytes)
            if expected != stored:
                checksum_ok = False

        # 字段解析
        values: dict[str, Any] = {}
        for f in spec.fields:
            st = self._get_struct(f)
            char, blen, _kind = parse_type(f.type)
            if f.offset + blen > len(frame):
                raise ParseError(
                    f"[{spec.name}] field '{f.name}' out of range: "
                    f"offset={f.offset} len={blen} frame={len(frame)}"
                )
            raw = st.unpack_from(frame, f.offset)[0]
            values[f.name] = coerce_value(f, raw)

        return ParsedPacket(
            format_name=spec.name,
            raw=bytes(frame),
            fields=values,
            checksum_ok=checksum_ok,
        )

    # ---------- 组包(解析的逆过程) ----------

    def build(self, spec: FormatSpec, values: dict[str, Any]) -> bytes:
        """按 FormatSpec 把字段值组帧。values 缺失字段填 0。

        注意:magic 与 checksum 由 spec 的 magic/checksum 配置写入,
        即使 values 未提供 magic_field/checksum 也能正确组帧。
        """
        buf = bytearray(spec.total_length)

        # 1) 字段(先写,magic/checksum 后写以避免被覆盖)
        for f in spec.fields:
            st = self._get_struct(f)
            char, blen, _kind = parse_type(f.type)
            val = values.get(f.name)
            if val is None:
                packed = b"\x00" * blen
            else:
                # coerce_value 对 char 做了去NUL,组包需反向编码
                _, _, kind = parse_type(f.type)
                if kind == "char":
                    s = str(val)
                    b = s.encode("ascii", errors="replace")[:blen]
                    packed = b.ljust(blen, b"\x00")
                elif kind == "bytes":
                    b = bytes(val)[:blen]
                    packed = b.ljust(blen, b"\x00")
                else:
                    # scalar: 反向 scale
                    raw_val = val
                    if f.scale != 1.0 and isinstance(val, (int, float)):
                        raw_val = val / f.scale
                    # 整型字段需 int(struct 要求);char 取末字符判类型
                    fmt_char = st.format[-1]
                    if fmt_char in "BbHhIiQq" and isinstance(raw_val, float):
                        raw_val = int(round(raw_val))
                    packed = st.pack(raw_val)
            buf[f.offset:f.offset + blen] = packed

        # 2) magic(覆盖字段值)
        if spec.magic is not None:
            buf[spec.magic_offset:spec.magic_offset + len(spec.magic)] = spec.magic

        # 3) checksum(最后计算,覆盖字段值)
        if spec.checksum is not None:
            cs = spec.checksum
            expected = compute_checksum(bytes(buf), cs.algo, cs.offset, cs.length)
            buf[cs.field_offset:cs.field_offset + cs.field_bytes] = encode_checksum(
                expected, cs.field_bytes
            )

        return bytes(buf)
