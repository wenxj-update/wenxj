"""格式描述符:字段/校验/格式规格。

这些是纯数据描述,不含解析逻辑。解析器据此生成 struct 格式串。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class FieldSpec:
    """单个字段规格。"""
    name: str
    offset: int                 # 字节偏移
    type: str                   # "u16"/"i32"/"f64"/"char[N]"/"bytes[N]" 等
    endian: str = "<"           # "<" 小端 / ">" 大端 / "=" 原生
    scale: float = 1.0          # 定点缩放(解析后值 * scale)
    units: str = ""             # 单位标注(仅展示)
    enum: Optional[dict[int, str]] = None   # 枚举映射(原始值->名称)

    @property
    def is_scalar(self) -> bool:
        t = self.type.lower()
        return t in ("u8", "i8", "u16", "i16", "u32", "i32", "u64", "i64", "f32", "f64")


@dataclass(frozen=True)
class ChecksumSpec:
    """校验字段规格。"""
    algo: str               # "crc32" / "sum8" / "xor8" / "crc16"
    offset: int             # 校验计算起始偏移
    length: int             # 校验计算长度
    field_offset: int       # 校验值存放偏移
    field_bytes: int = 4    # 校验值字节数


@dataclass(frozen=True)
class FormatSpec:
    """一个完整报文格式规格。"""
    name: str
    total_length: int                       # 整帧总长(字节)
    magic: Optional[bytes] = None            # 帧头魔数(用于自动识别)
    magic_offset: int = 0
    fields: tuple[FieldSpec, ...] = field(default_factory=tuple)
    checksum: Optional[ChecksumSpec] = None
    description: str = ""
