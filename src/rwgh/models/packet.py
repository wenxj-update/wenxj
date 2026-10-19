"""解析后的数据包基类。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ParsedPacket:
    """解析后的数据包:字段名->值映射。

    所有格式解析器产出此对象,业务层按 format_name 分发处理。
    """
    format_name: str
    raw: bytes = b""                        # 原始帧字节
    fields: dict[str, Any] = field(default_factory=dict)
    checksum_ok: bool = True

    def get(self, name: str, default: Any = None) -> Any:
        return self.fields.get(name, default)

    def __getitem__(self, name: str) -> Any:
        return self.fields[name]

    def __contains__(self, name: str) -> bool:
        return name in self.fields
