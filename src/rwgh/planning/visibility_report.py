"""可见性报文生成:把 VisibilityResult 序列化为二进制定长帧(回送/展示)。

使用 visibility_report FormatSpec + FrameParser.build 组帧,与解析对称。
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from ..parsing.parser import FrameParser
from ..parsing.spec import FormatSpec
from ..models.visibility import VisibilityResult, VisibilityWindow

_log = logging.getLogger("rwgh.planning.visibility_report")

# 时间基准(相对秒):J2000 历元
EPOCH = datetime(2000, 1, 1, tzinfo=timezone.utc)


def to_relative_seconds(dt: datetime) -> float:
    """datetime -> 自 EPOCH 起的秒(浮点)。"""
    return (dt - EPOCH).total_seconds()


class VisibilityReportBuilder:
    """可见性报文组帧器。"""

    def __init__(self, parser: FrameParser,
                 sat_id_map: Optional[dict[str, int]] = None) -> None:
        self._parser = parser
        self._sat_id_map = sat_id_map or {}
        self._next_sat_id = 1

    def _sat_id(self, satellite: str) -> int:
        sid = self._sat_id_map.get(satellite)
        if sid is None:
            sid = self._next_sat_id
            self._sat_id_map[satellite] = sid
            self._next_sat_id += 1
        return sid

    def build_window(self, window: VisibilityWindow, satellite: str,
                     spec: FormatSpec) -> bytes:
        """单个可见性窗口 -> 一帧可见性报文。"""
        values = {
            "length": spec.total_length,
            "satellite_id": self._sat_id(satellite),
            "target_id": self._hash_target_id(window.target_id),
            "aos_time": to_relative_seconds(window.aos),
            "los_time": to_relative_seconds(window.los),
            "max_el": window.max_el,
        }
        return self._parser.build(spec, values)

    def build_all(self, result: VisibilityResult,
                  spec: FormatSpec) -> list[bytes]:
        frames = []
        for w in result.windows:
            frames.append(self.build_window(w, result.satellite, spec))
        _log.info("VisibilityReport: %d frames for sat=%s",
                  len(frames), result.satellite)
        return frames

    @staticmethod
    def _hash_target_id(tid: str) -> int:
        """目标字符串ID -> u32(简单哈希,真实格式按字段定义映射)。"""
        h = 0
        for ch in tid:
            h = (h * 31 + ord(ch)) & 0xFFFFFFFF
        return h
