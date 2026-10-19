"""数传算法接口(后续实现,与成像链路同构)。

【扩展点7】数传链路:输入链路资源 + 站址资源 -> 调 .dll 规划数传结果 ->
        生成数传报文 -> 指令生成 -> 模板比对。流程同成像,这里先留接口。
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class IDatalinkAlgorithm(Protocol):
    """数传规划算法接口(后续实现)。"""

    def plan(self, link_resources: list, ground_stations: list, **kwargs) -> list:
        ...
