"""演示用真实模板指令生成器。

不是真实业务代码,只是为了演示端到端链路:
根据可见性窗口,生成与"多目标成像记录"模板期望完全一致的指令序列,
让模板比对能产出 matches(PASS)。

【扩展点4】真实指令生成代码由用户提供,替换本类即可。
"""
from __future__ import annotations

from typing import Optional

from rwgh.models.command import Command, CommandSequence
from rwgh.models.visibility import VisibilityResult
from rwgh.planning.command_gen import ICommandGenerator


class DemoRealCommandGenerator(ICommandGenerator):
    """演示用:产出与"多目标成像记录"模板期望完全一致的指令。

    实际业务中,指令生成器会根据可见性窗口、目标信息、资源情况
    动态计算每条指令的时序与码字。这里简化为直接复用模板期望,
    用于演示端到端链路能跑通(比对 PASS)。
    """

    # 与"多目标成像记录"模板 15 条指令完全一致
    TEMPLATE_COMMANDS = [
        # (time_offset, codeword_hex, name, sub_header, main_header)
        (-360.0, "EB90146F",  "控制开始",                "间接指令",     "星务"),
        (-310.0, "",           "记录任务包",              "下位机数据块", "载综"),
        (-305.0, "",           "相机57字节数据块1",       "下位机数据块", "相机"),
        (-210.0, "",           "姿控242字节数据块1",      "下位机数据块", "姿控"),
        (-208.0, "01AB01AA",   "多任务有效",              "间接指令",     "姿控"),
        (-100.0, "",           "固存记录(载荷数据）",     "下位机数据块", "载综"),
        (-96.0,  "",           "固存记录(小固存数据）",   "下位机数据块", "载综"),
        (-95.0,  "",           "压缩参数设置1",           "下位机数据块", "载综"),
        (-2.0,   "199A5500",   "所有星图数据清零",        "间接指令",     "姿控接口板"),
        (-1.0,   "1998FFFF",   "星敏123星图记录开",       "间接指令",     "姿控接口板"),
        (0.0,    "",           "相机数据块1成像开始时刻",  "/",            "/"),
        (1.0,    "19980000",   "星敏123星图记录关",       "间接指令",     "姿控接口板"),
        (2.0,    "1999AAAA",   "星敏123星图一起下传一次", "间接指令",     "姿控接口板"),
        (5.0,    "",           "记录停止码（载荷数据）",  "下位机数据块", "载综"),
        (-360.0, "FFFFFFFF",   "控制结束",                "间接指令",     "星务"),
    ]

    def generate(self, result: VisibilityResult,
                 template_hint: Optional[str] = None) -> CommandSequence:
        cmds: list[Command] = []
        if not result.windows:
            return CommandSequence(target_id="unknown", commands=())
        # 与模板相同的时间基准(相对 Ts 的偏移)
        for t_off, cw_hex, name, sub, main in self.TEMPLATE_COMMANDS:
            cw = bytes.fromhex(cw_hex) if cw_hex else b""
            cmds.append(Command(
                time_tag=float(t_off),
                codeword=cw,
                name=name,
                sub_header=sub,
                main_header=main,
            ))
        target_id = result.windows[0].target_id
        return CommandSequence(target_id=target_id, commands=tuple(cmds))
