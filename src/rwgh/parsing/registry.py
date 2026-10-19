"""格式注册表:支持按 magic+length 自动识别格式,可插件式注册新格式。"""
from __future__ import annotations

from typing import Optional

from .spec import FormatSpec
from ..core.exceptions import ParseError


class FormatRegistry:
    """报文格式注册表。

    用法:
        reg = FormatRegistry()
        reg.register(stk_spec)
        reg.register(visibility_spec)
        spec = reg.detect(frame)   # 按 magic+length 自动识别
    """

    def __init__(self) -> None:
        self._by_name: dict[str, FormatSpec] = {}
        # (magic, total_length) -> spec,用于自动识别
        self._by_key: dict[tuple[bytes, int], FormatSpec] = {}
        # 无 magic 的格式按 length 兜底(可能多个,需手动指定)
        self._by_len: dict[int, list[FormatSpec]] = {}

    def register(self, spec: FormatSpec) -> None:
        if spec.name in self._by_name:
            raise ParseError(f"duplicate format name: {spec.name}")
        self._by_name[spec.name] = spec
        if spec.magic is not None:
            key = (spec.magic, spec.total_length)
            self._by_key[key] = spec
        else:
            self._by_len.setdefault(spec.total_length, []).append(spec)

    def get(self, name: str) -> FormatSpec:
        spec = self._by_name.get(name)
        if spec is None:
            raise ParseError(f"unknown format: {name}")
        return spec

    def all(self) -> list[FormatSpec]:
        return list(self._by_name.values())

    def detect(self, frame: bytes) -> Optional[FormatSpec]:
        """按 magic+length 自动识别。无法唯一识别时返回 None,由调用方指定。"""
        # 先按 (magic, length) 精确匹配
        for spec in self._by_name.values():
            if spec.magic is None:
                continue
            if len(frame) < spec.magic_offset + len(spec.magic):
                continue
            actual = frame[spec.magic_offset:spec.magic_offset + len(spec.magic)]
            if actual == spec.magic and len(frame) == spec.total_length:
                return spec
        # 无 magic 的格式按 length 兜底
        cands = self._by_len.get(len(frame), [])
        if len(cands) == 1:
            return cands[0]
        return None
