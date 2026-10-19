"""指令序列与模板数据模型。

Command 支持两种码字表达:
- code (int):  简单码字(stub 用,如 0x10/0x11)
- codeword (bytes): 真实多字节码字(从指令模板 xlsm 解析,如 b'\xEB\x90\x14\x6F')
真实模板比对优先用 codeword;stub 链路用 code。两者通过默认值向后兼容。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Command:
    """单条指令:时序标签 + 码字 + 参数 + 分类信息。"""
    time_tag: float          # 相对时序(秒,相对 Ts=任务开始时刻)
    code: int = 0            # 简单码字(int,stub 链路用)
    params: tuple[Any, ...] = field(default_factory=tuple)
    codeword: bytes = b""   # 真实多字节码字(从 xlsm 指令码字列解析)
    name: str = ""          # 指令名称(参数名,如"控制开始"/"记录任务包")
    sub_header: str = ""    # 副导头(间接指令/下位机数据块)
    main_header: str = ""   # 主导头(星务/载综/姿控/相机)
    block_kind: str = ""    # 块类型(控制开始/记录任务包/相机57B/姿控242B等)
    remark: str = ""        # 备注(块用途/时序说明)
    abs_time_sec: float = 0.0  # 2009历元绝对秒(供 UTC 显示)


@dataclass(frozen=True)
class CommandSequence:
    """一个目标/卫星的指令序列。"""
    target_id: str
    commands: tuple[Command, ...] = field(default_factory=tuple)
    gen_local_time: str = ""   # 生成本地时间
    plan_source: str = ""      # 规划来源(0F11/0F22)


@dataclass(frozen=True)
class CommandTemplate:
    """指令模板:期望的时序与码字 + 容差。"""
    name: str
    expected: tuple[Command, ...] = field(default_factory=tuple)
    time_tolerance: float = 0.5     # 时序容差(秒)
    code_exact: bool = True         # 码字是否要求精确匹配
