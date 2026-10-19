"""指令生成抽象与 Stub 实现。

【扩展点4】用户提供真实指令生成代码:继承 ICommandGenerator 实现 generate(),
注入 Pipeline 即可,不动主链路。
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional

from ..models.command import Command, CommandSequence
from ..models.visibility import VisibilityResult, VisibilityWindow

_log = logging.getLogger("rwgh.planning.command_gen")

# 约定码字
CODE_IMAGING_START = 0x10
CODE_IMAGING_STOP = 0x11


class ICommandGenerator(ABC):
    """指令生成器抽象基类。"""

    @abstractmethod
    def generate(self, result: VisibilityResult,
                 template_hint: Optional[str] = None) -> CommandSequence:
        """根据可见性结果生成指令序列(时序 + 码字)。"""

    def generate_from_plan(self, plan: dict, packet_type: int,
                          template_hint: str = "") -> CommandSequence:
        """从 0F11/0F22 规划结果报文生成指令序列(可选实现)。"""
        raise NotImplementedError(
            f"{type(self).__name__} 未实现 generate_from_plan")


class StubCommandGenerator(ICommandGenerator):
    """MVP 桩:按可见性窗口生成成像开始/停止指令。

    故意在时序上引入小偏差,使模板比对能输出 Discrepancy,验证主链路。
    """

    def __init__(self, time_skew: float = 0.2) -> None:
        self._time_skew = time_skew

    def generate(self, result: VisibilityResult,
                 template_hint: Optional[str] = None) -> CommandSequence:
        cmds: list[Command] = []
        # 用 epoch 作为相对时序基准
        for w in result.windows:
            base = self._to_relative(w.aos)
            cmds.append(Command(
                time_tag=base + self._time_skew,   # 故意偏移制造差异
                code=CODE_IMAGING_START,
                params=(w.target_id,),
            ))
            stop_base = self._to_relative(w.los)
            cmds.append(Command(
                time_tag=stop_base,
                code=CODE_IMAGING_STOP,
                params=(w.target_id,),
            ))
        target_id = result.windows[0].target_id if result.windows else "unknown"
        _log.info("StubCommandGen: %d commands for target=%s",
                  len(cmds), target_id)
        return CommandSequence(target_id=target_id, commands=tuple(cmds))

    @staticmethod
    def _to_relative(dt: datetime, epoch: Optional[datetime] = None) -> float:
        # 以第一个窗口的 aos 为 0 基准(简单实现)
        # 真实实现用 SatelliteClock.epoch
        from datetime import datetime as _dt, timezone as _tz
        ref = epoch or _dt(2000, 1, 1, tzinfo=_tz.utc)
        return (dt - ref).total_seconds()
