"""星上指令序列生成器(C 代码 app_star_task_parser.c 的 Python 移植)。

把 0F11/0F22 规划结果报文转换为星上可执行指令序列(CommandSequence),
时序编排严格按 C 代码的 emit_single_target / emit_pre_imaging /
emit_post_imaging 顺序。
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from ..models.command import Command, CommandSequence
from ..models.visibility import VisibilityResult
from . import star_command_builder as B
from .command_gen import ICommandGenerator

_log = logging.getLogger("rwgh.planning.star_command_sequence")

# 主导头 -> 中文名
_MASTER_NAME = {
    B.FWD_MASTER_SATSVC: "星务",
    B.FWD_MASTER_CAMERA: "相机",
    B.FWD_MASTER_ATTITUDE: "姿控",
    B.FWD_MASTER_ATT_IF: "姿控接口板",
    B.FWD_MASTER_DATATRANS: "载综",
}

# 副导头 -> 中文名
_SUB_NAME = {
    B.FWD_SUB_INDIRECT_CMD: "间接指令",
    B.FWD_SUB_DATA_BLOCK: "下位机数据块",
}


class ImagePlanCommandGenerator(ICommandGenerator):
    """成像/数传规划结果 → 星上指令序列。

    移植 C 代码的 emit_single_target / emit_pre_imaging / emit_post_imaging
    时序编排逻辑,生成完整程控指令序列。
    """

    def __init__(self) -> None:
        self._taskno = 200  # 程控任务号从 200 开始

    def generate(self, result: VisibilityResult,
                 template_hint: Optional[str] = None) -> CommandSequence:
        """pipeline 兼容入口: 从可见性窗口构建简易 0F11 plan 再生成。"""
        # 简易 plan: 把窗口转成 target dict
        targets = []
        for w in result.windows:
            targets.append({
                "target_id": w.target_id,
                "img_start": int(w.aos.timestamp()),
                "img_end": int(w.los.timestamp()),
                "lon": 0.0, "lat": 0.0,
                "pitch": 0.0, "roll": 0.0, "yaw": 0.0,
                "imaging_mode": 1, "off_axis": 0.0,
                "duration": int(w.duration_sec),
                "keep_time": 10,
            })
        plan = {"targets": targets, "task_id": 0, "payload_priority": 2}
        return self.generate_from_plan(plan, 0x0F11)

    def generate_from_plan(self, plan: dict, packet_type: int,
                          template_hint: str = "") -> CommandSequence:
        """从 0F11/0F22 规划结果报文生成指令序列。"""
        smart_off = False
        if packet_type == 0x0F11:
            smart_off = self._smart_process(plan) == 0
            seq = self._generate_0f11(plan)
        elif packet_type == 0x0F22:
            seq = self._generate_0f22(plan)
        else:
            seq = CommandSequence(target_id="unknown", commands=())
        # 补充元信息
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if packet_type == 0x0F11:
            # 标注所用指令模板 sheet:星上处理开/关对应不同模板
            mode = "多目标成像记录" if smart_off else "成像记录+星上处理"
            src = f"0F11({mode})"
        else:
            src = f"0F{packet_type & 0xFF:02X}"
        return CommandSequence(
            target_id=src,
            commands=seq.commands,
            gen_local_time=now,
            plan_source=src,
        )

    @staticmethod
    def _smart_process(plan: dict) -> int:
        """星上智能处理开关(1=开,默认;0=关)。"""
        try:
            return int(plan.get("smart_process",
                                plan.get("onboard_processing", 1)))
        except (TypeError, ValueError):
            return 1

    @staticmethod
    def _cam_role(idx: int, n: int) -> int:
        """相机包型角色(C: ImgCamPacketRole)。

        单目标:0(单目标包); 多目标:第1个=1(首包,指令1准备码0x14/12/16),
        中间=2(中间包,指令1=0x21执行一次), 最后=3(尾包,指令1=0x22执行并断电)。
        """
        if n <= 1:
            return 0
        if idx == 0:
            return 1
        if idx == n - 1:
            return 3
        return 2

    @staticmethod
    def _att_span(plan: dict, first: int) -> tuple[int, int]:
        """姿控块窗口区间(first, count):count=剩余目标数,单块最多5个。"""
        n = len(plan.get("targets") or [])
        return first, max(1, min(n - first, 5))

    # ---- 0F11 成像指令序列 ----

    def _generate_0f11(self, plan: dict) -> CommandSequence:
        """0F11 成像计划 → 指令序列(按星上智能处理开关选择模板 sheet)。

        - 星上智能处理=1 → 模板"成像记录+星上处理"sheet(含 AI/星上处理指令)
        - 星上智能处理=0 → 模板"多目标成像记录"sheet(无 AI/无星上处理指令)

        两模板序列均为连续输出(非每目标重新开始):
        - 目标1(Ts1): 完整前置 + 后置
        - 目标2..N(TsN): 精简前置 + 后置
        - 每5个目标的后置完成后追加: 姿控1(242B) + 多任务有效
        - 最后一个目标的后置追加收尾指令
        - 序列首尾: 控制开始(0xEB90146F) / 控制结束(0xFFFFFFFF)
        """
        if self._smart_process(plan) == 0:
            return self._generate_0f11_multi(plan)
        targets = plan.get("targets") or []
        if not targets:
            return CommandSequence(target_id="0F11", commands=())
        cmds: list[Command] = []
        taskno = self._taskno

        # 1) 控制开始(哨兵,时标=哨兵值本身)
        self._emit_control_flag(cmds, B.CTRL_START_MARKER, "控制开始标志",
                                "序列起始哨兵 0xEB90146F")

        n = len(targets)
        for idx, t in enumerate(targets):
            ts = int(t.get("imaging_start", t.get("img_start", 0)))
            te = int(t.get("imaging_end", t.get("img_end", ts + 10)))
            if idx == 0:
                # 目标1: 完整前置
                self._emit_first_target_preamble(plan, taskno, idx, ts, cmds)
            else:
                # 目标2..N: 仅相机/AI块/固存/星图清零/星敏记录开
                self._emit_later_target_preamble(plan, taskno, idx, ts, cmds)
            # 后置(所有目标一致,base_ts=ts 以计算相对时间)
            self._emit_post_imaging(plan, taskno, idx, te, cmds, base_ts=ts)
            # 每5个目标追加姿控1+多任务有效(模板 Te5+3 / Te5+4)
            # 姿控块单块最多装5个目标,追加块装下一组 [idx+1, idx+1+5)
            if (idx + 1) % 5 == 0 and idx < n - 1:
                att_first, att_count = self._att_span(plan, idx + 1)
                self._emit(cmds, te + 3, taskno,
                           B.FWD_MASTER_ATTITUDE, B.FWD_SUB_DATA_BLOCK,
                           B.build_attitude_block(plan, att_first, att_count),
                           "姿控数据块", "姿控数据块242B",
                           "Te5+3 姿控下发, 242B 特征码66H+40B单元",
                           base_ts=ts)
                self._emit(cmds, te + 4, taskno,
                           B.FWD_MASTER_ATTITUDE, B.FWD_SUB_INDIRECT_CMD,
                           B.build_multi_task_valid_cmd(),
                           "多任务有效", "多任务有效",
                           "Te5+4 姿控间接指令, 4B 01AB01AA",
                           base_ts=ts)

        # 2) 最后一个目标的后置追加(AI低功耗/断电/一键关机)
        last_t = targets[-1] if targets else {}
        last_te = int(last_t.get("imaging_end", last_t.get("img_end", 0)))
        last_ts = int(last_t.get("imaging_start", last_t.get("img_start", 0)))
        self._emit(cmds, last_te + B.SEQ_OFF_AI_LOW_POWER, taskno,
                    B.FWD_MASTER_DATATRANS, B.FWD_SUB_DATA_BLOCK,
                    B.build_ai_power_mode_cmd(high_power=False),
                    "AI低功耗", "AI低功耗",
                    "TeN+155 载综, AI进入低功耗模式",
                    base_ts=last_ts)
        self._emit(cmds, last_te + B.SEQ_OFF_AI_POWER_OFF, taskno,
                    B.FWD_MASTER_DATATRANS, B.FWD_SUB_DATA_BLOCK,
                    B.build_ai_power_off_cmd(),
                    "AI断电", "AI断电",
                    "TeN+160 载综, AI断电",
                    base_ts=last_ts)
        self._emit(cmds, last_te + B.SEQ_OFF_AI_ONEKEY, taskno,
                    B.FWD_MASTER_DATATRANS, B.FWD_SUB_DATA_BLOCK,
                    B.build_onekey_shutdown_cmd(),
                    "成像一键关机", "成像一键关机",
                    "TeN+165 载综下发, 1130 存储板/压缩板关机",
                    base_ts=last_ts)

        # 3) 控制结束(哨兵)
        self._emit_control_flag(cmds, B.CTRL_END_MARKER, "控制结束标志",
                                "序列结束哨兵 0xFFFFFFFF")
        return CommandSequence(
            target_id="0F11",
            commands=tuple(cmds),
            gen_local_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            plan_source="0F11",
        )

    def _emit_first_target_preamble(self, plan: dict, taskno: int, idx: int,
                                     ts: int, cmds: list) -> None:
        """目标1 完整前置(Ts-310 到 Ts-1),按模板"成像记录+星上处理"sheet。"""
        t = (plan.get("targets") or [{}])[idx]
        storage_id = int(t.get("storage_task_id",
                               plan.get("storage_task_no", 61)))
        file_id = int(t.get("raw_file_no", idx + 1))
        proc_file_id = int(t.get("proc_file_no", 126 + idx))
        comp = int(plan.get("compression", 4))
        # Ts-310 记录任务包
        self._emit(cmds, ts - B.SEQ_OFF_RECORD_TASK, taskno,
                    B.FWD_MASTER_DATATRANS, B.FWD_SUB_DATA_BLOCK,
                    B.build_record_task_package(),
                    "记录任务包", "记录任务包",
                    "Ts-310 载综下发, 功能识别1140/工作时长1800s",
                    base_ts=ts)
        # Ts-305 相机数据块1(多目标时为首包)
        self._emit(cmds, ts - B.SEQ_OFF_CAMERA, taskno,
                    B.FWD_MASTER_CAMERA, B.FWD_SUB_DATA_BLOCK,
                    B.build_camera_block(
                        plan, idx, self._cam_role(
                            idx, len(plan.get("targets") or []))),
                    "相机数据块", "相机数据块57B",
                    "Ts-305 相机下发, 57B逐字段大端",
                    base_ts=ts)
        # Ts-210 姿控242字节数据块1(0F11有几个目标填几个,单块最多5个)
        att_first, att_count = self._att_span(plan, 0)
        self._emit(cmds, ts - B.SEQ_OFF_ATTITUDE, taskno,
                    B.FWD_MASTER_ATTITUDE, B.FWD_SUB_DATA_BLOCK,
                    B.build_attitude_block(plan, att_first, att_count),
                    "姿控数据块", "姿控数据块242B",
                    "Ts-210 姿控下发, 242B 特征码66H+40B单元",
                    base_ts=ts)
        # Ts-208 多任务有效
        self._emit(cmds, ts - B.SEQ_OFF_MULTITASK, taskno,
                    B.FWD_MASTER_ATTITUDE, B.FWD_SUB_INDIRECT_CMD,
                    B.build_multi_task_valid_cmd(),
                    "多任务有效", "多任务有效",
                    "Ts-208 姿控间接指令, 4B 01AB01AA",
                    base_ts=ts)
        # Ts-115 AI加电
        self._emit(cmds, ts - B.SEQ_OFF_AI_POWER_ON, taskno,
                    B.FWD_MASTER_SATSVC, B.FWD_SUB_INDIRECT_CMD,
                    B.build_ai_power_on_cmd(),
                    "AI加电", "AI加电",
                    "Ts-115 星务间接指令, 4B 000101D3, AI主备加电",
                    base_ts=ts)
        # Ts-110 AI高功耗
        self._emit(cmds, ts - B.SEQ_OFF_AI_HIGH_POWER, taskno,
                    B.FWD_MASTER_DATATRANS, B.FWD_SUB_DATA_BLOCK,
                    B.build_ai_power_mode_cmd(high_power=True),
                    "AI高功耗", "AI高功耗",
                    "Ts-110 载综, 8B, AI进入高功耗模式",
                    base_ts=ts)
        # Ts-105 AI处理模式指令块(138B)
        self._emit(cmds, ts - B.SEQ_OFF_AI_TASK_BLOCK, taskno,
                    B.FWD_MASTER_DATATRANS, B.FWD_SUB_DATA_BLOCK,
                    B.build_ai_task_cmd_packet(plan, idx),
                    "AI任务块", "AI任务包138B",
                    "Ts-105 载综下发, 138B=9前缀+128块+1累加和",
                    base_ts=ts)
        # Ts-100 固存记录(载荷数据)
        self._emit(cmds, ts - B.SEQ_OFF_STORAGE, taskno,
                    B.FWD_MASTER_DATATRANS, B.FWD_SUB_DATA_BLOCK,
                    B.build_storage_record_package(False, storage_id, file_id),
                    "固存记录", "固存记录",
                    "Ts-100 载综下发, 原始1160, 10B",
                    base_ts=ts)
        # Ts-98 固存记录(星上处理数据)
        self._emit(cmds, ts - 98, taskno,
                    B.FWD_MASTER_DATATRANS, B.FWD_SUB_DATA_BLOCK,
                    B.build_storage_record_package(True, storage_id, proc_file_id),
                    "固存记录(处理)", "固存记录",
                    "Ts-98 载综下发, 处理1161, 10B",
                    base_ts=ts)
        # Ts-96 固存记录(小固存数据)
        self._emit(cmds, ts - B.SEQ_OFF_SMALL_STORAGE, taskno,
                    B.FWD_MASTER_DATATRANS, B.FWD_SUB_DATA_BLOCK,
                    B.build_small_storage_record_package(storage_id, file_id, comp),
                    "小固存记录", "小固存记录",
                    "Ts-96 载综下发, 1162, 任务号+300",
                    base_ts=ts)
        # Ts-95 压缩参数设置1
        self._emit(cmds, ts - B.SEQ_OFF_COMPRESS, taskno,
                    B.FWD_MASTER_DATATRANS, B.FWD_SUB_DATA_BLOCK,
                    B.build_compress_param_package(comp),
                    "压缩参数", "压缩参数",
                    "Ts-95 载综下发, 2001, 10B",
                    base_ts=ts)
        # Ts-2 星图清零
        self._emit(cmds, ts - B.SEQ_OFF_STARMAP_CLEAR, taskno,
                    B.FWD_MASTER_ATT_IF, B.FWD_SUB_INDIRECT_CMD,
                    B.build_starmap_clear_cmd(),
                    "星图清零", "星图清零",
                    "Ts-2 姿控接口板, 199A5500",
                    base_ts=ts)
        # Ts-1 星敏记录开
        self._emit(cmds, ts - B.SEQ_OFF_STARSENSOR_REC_ON, taskno,
                    B.FWD_MASTER_ATT_IF, B.FWD_SUB_INDIRECT_CMD,
                    B.build_star_sensor_record_on_cmd(),
                    "星敏记录开", "星敏记录开",
                    "Ts-1 姿控接口板, 1998FFFF",
                    base_ts=ts)

    def _emit_later_target_preamble(self, plan: dict, taskno: int, idx: int,
                                     ts: int, cmds: list) -> None:
        """目标2..N 前置(仅相机/AI块/固存/星图清零/星敏记录开)。"""
        t = (plan.get("targets") or [{}])[idx] if idx < len(
            plan.get("targets") or []) else {}
        storage_id = int(t.get("storage_task_id",
                               plan.get("storage_task_no", 61)))
        file_id = int(t.get("raw_file_no", idx + 1))
        proc_file_id = int(t.get("proc_file_no", 126 + idx))
        # Ts{N}-10 相机57字节数据块N(中间包/尾包)
        self._emit(cmds, ts - B.SEQ_OFF_SEG_CAMERA, taskno,
                    B.FWD_MASTER_CAMERA, B.FWD_SUB_DATA_BLOCK,
                    B.build_camera_block(
                        plan, idx, self._cam_role(
                            idx, len(plan.get("targets") or []))),
                    f"相机数据块{idx + 1}", "相机数据块57B",
                    f"Ts{idx + 1}-10 相机下发, 57B",
                    base_ts=ts)
        # Ts{N}-7 AI处理模式指令块
        self._emit(cmds, ts - B.SEQ_OFF_AI_SEG_BLOCK, taskno,
                    B.FWD_MASTER_DATATRANS, B.FWD_SUB_DATA_BLOCK,
                    B.build_ai_task_cmd_packet(plan, idx),
                    "AI任务块", "AI任务包138B",
                    f"Ts{idx + 1}-7 载综下发, 138B",
                    base_ts=ts)
        # Ts{N}-5 固存记录(载荷数据)
        self._emit(cmds, ts - B.SEQ_OFF_SEG_STORAGE, taskno,
                    B.FWD_MASTER_DATATRANS, B.FWD_SUB_DATA_BLOCK,
                    B.build_storage_record_package(False, storage_id, file_id),
                    "固存记录", "固存记录",
                    f"Ts{idx + 1}-5 载综下发, 原始1160, 10B",
                    base_ts=ts)
        # Ts{N}-3 固存记录(星上处理数据)
        self._emit(cmds, ts - 3, taskno,
                    B.FWD_MASTER_DATATRANS, B.FWD_SUB_DATA_BLOCK,
                    B.build_storage_record_package(True, storage_id, proc_file_id),
                    "固存记录(处理)", "固存记录",
                    f"Ts{idx + 1}-3 载综下发, 处理1161, 10B",
                    base_ts=ts)
        # Ts{N}-2 星图清零
        self._emit(cmds, ts - B.SEQ_OFF_STARMAP_CLEAR, taskno,
                    B.FWD_MASTER_ATT_IF, B.FWD_SUB_INDIRECT_CMD,
                    B.build_starmap_clear_cmd(),
                    "星图清零", "星图清零",
                    f"Ts{idx + 1}-2 姿控接口板, 199A5500",
                    base_ts=ts)
        # Ts{N}-1 星敏记录开
        self._emit(cmds, ts - B.SEQ_OFF_STARSENSOR_REC_ON, taskno,
                    B.FWD_MASTER_ATT_IF, B.FWD_SUB_INDIRECT_CMD,
                    B.build_star_sensor_record_on_cmd(),
                    "星敏记录开", "星敏记录开",
                    f"Ts{idx + 1}-1 姿控接口板, 1998FFFF",
                    base_ts=ts)

    def _emit_post_imaging(self, plan: dict, taskno: int, idx: int,
                           te: int, cmds: list,
                           base_ts: int = 0) -> None:
        """成像后置指令(Te+1 到 Te+7),按模板"成像记录+星上处理"sheet。

        Te+1 星敏记录关 / Te+2 星敏下传 / Te+5 载荷停止码(116F) /
        Te+7 星上处理停止码(1170)。
        """
        # Te+1 星敏记录关
        self._emit(cmds, te + B.SEQ_OFF_STARSENSOR_REC_OFF, taskno,
                    B.FWD_MASTER_ATT_IF, B.FWD_SUB_INDIRECT_CMD,
                    B.build_star_sensor_record_off_cmd(),
                    "星敏记录关", "星敏记录关",
                    "Te+1 姿控接口板, 19980000",
                    base_ts=base_ts)
        # Te+2 星敏下传
        self._emit(cmds, te + B.SEQ_OFF_STARSENSOR_DLINK, taskno,
                    B.FWD_MASTER_ATT_IF, B.FWD_SUB_INDIRECT_CMD,
                    B.build_star_sensor_downlink_cmd(),
                    "星敏下传", "星敏下传",
                    "Te+2 姿控接口板, 1999AAAA",
                    base_ts=base_ts)
        # Te+5 记录停止码(载荷数据,原始 116F)
        self._emit(cmds, te + B.SEQ_OFF_RECORD_STOP, taskno,
                    B.FWD_MASTER_DATATRANS, B.FWD_SUB_DATA_BLOCK,
                    B.build_record_stop_cmd(False),
                    "记录停止码", "记录停止码",
                    "Te+5 载综下发, 原始116F, 4B",
                    base_ts=base_ts)
        # Te+7 记录停止码(星上处理数据,1170)
        self._emit(cmds, te + B.SEQ_OFF_SMALL_STORAGE_STOP, taskno,
                    B.FWD_MASTER_DATATRANS, B.FWD_SUB_DATA_BLOCK,
                    B.build_record_stop_cmd(True),
                    "记录停止码(处理)", "记录停止码",
                    "Te+7 载综下发, 处理1170, 4B",
                    base_ts=base_ts)

    # ---- 0F11 多目标成像记录模式(星上智能处理=0) ----

    def _generate_0f11_multi(self, plan: dict) -> CommandSequence:
        """0F11 成像计划 → 指令序列(模板"多目标成像记录"sheet)。

        星上智能处理=0:无 AI 加电/高功耗/AI任务块/AI低功耗/AI断电,
        无固存记录(星上处理数据 1161),后置无星上处理停止码(1170)。

        时序(模板"多目标成像记录"sheet,连续输出):
        - 目标1(Ts1): Ts-310记录任务包 / Ts-305相机1 / Ts-210姿控1 /
          Ts-208多任务有效 / Ts-100固存记录载荷(1160) / Ts-96小固存(1162) /
          Ts-95压缩参数 / Ts-2星图清零 / Ts-1星敏记录开
        - 目标2..N(TsN): TsN-10相机N / TsN-5固存记录载荷 / TsN-3压缩参数 /
          TsN-2星图清零 / TsN-1星敏记录开
        - 后置(每目标): Te+1星敏记录关 / Te+2星敏下传 / Te+5记录停止码(载荷)
        - 每5目标: Te5+3姿控1 / Te5+4多任务有效 / Te5+5记录停止码(载荷)
        - 收尾: TeN+7记录停止码(小固存 1171) / TeN+12记录任务一键关机(1130)
        """
        targets = plan.get("targets") or []
        if not targets:
            return CommandSequence(target_id="0F11", commands=())
        cmds: list[Command] = []
        taskno = self._taskno

        # 1) 控制开始(哨兵)
        self._emit_control_flag(cmds, B.CTRL_START_MARKER, "控制开始标志",
                                "序列起始哨兵 0xEB90146F")

        n = len(targets)
        for idx, t in enumerate(targets):
            ts = int(t.get("imaging_start", t.get("img_start", 0)))
            te = int(t.get("imaging_end", t.get("img_end", ts + 10)))
            if idx == 0:
                self._emit_multi_first_preamble(plan, taskno, idx, ts, cmds)
            else:
                self._emit_multi_later_preamble(plan, taskno, idx, ts, cmds)
            self._emit_multi_post(plan, taskno, idx, te, cmds, base_ts=ts)
            # 每5目标追加姿控1+多任务有效(模板 Te5+3/Te5+4/Te5+5)
            # 姿控块单块最多装5个目标,追加块装下一组 [idx+1, idx+1+5)
            if (idx + 1) % 5 == 0 and idx < n - 1:
                att_first, att_count = self._att_span(plan, idx + 1)
                self._emit(cmds, te + 3, taskno,
                           B.FWD_MASTER_ATTITUDE, B.FWD_SUB_DATA_BLOCK,
                           B.build_attitude_block(plan, att_first, att_count),
                           "姿控数据块", "姿控数据块242B",
                           "Te5+3 姿控下发, 242B 特征码66H+40B单元",
                           base_ts=ts)
                self._emit(cmds, te + 4, taskno,
                           B.FWD_MASTER_ATTITUDE, B.FWD_SUB_INDIRECT_CMD,
                           B.build_multi_task_valid_cmd(),
                           "多任务有效", "多任务有效",
                           "Te5+4 姿控间接指令, 4B 01AB01AA",
                           base_ts=ts)

        # 2) 收尾: TeN+7 小固存停止码(1171) + TeN+12 一键关机(1130)
        last_t = targets[-1]
        last_te = int(last_t.get("imaging_end", last_t.get("img_end", 0)))
        last_ts = int(last_t.get("imaging_start", last_t.get("img_start", 0)))
        self._emit(cmds, last_te + 7, taskno,
                   B.FWD_MASTER_DATATRANS, B.FWD_SUB_DATA_BLOCK,
                   B.build_small_storage_stop_cmd(),
                   "记录停止码(小固存)", "记录停止码",
                   "TeN+7 载综下发, 小固存数据记录停止码 1171, 4B",
                   base_ts=last_ts)
        self._emit(cmds, last_te + 12, taskno,
                   B.FWD_MASTER_DATATRANS, B.FWD_SUB_DATA_BLOCK,
                   B.build_onekey_shutdown_cmd(),
                   "记录任务一键关机", "记录任务一键关机",
                   "TeN+12 载综下发, 1130, 2B",
                   base_ts=last_ts)

        # 3) 控制结束(哨兵)
        self._emit_control_flag(cmds, B.CTRL_END_MARKER, "控制结束标志",
                                "序列结束哨兵 0xFFFFFFFF")
        return CommandSequence(
            target_id="0F11",
            commands=tuple(cmds),
            gen_local_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            plan_source="0F11",
        )

    def _emit_multi_first_preamble(self, plan: dict, taskno: int, idx: int,
                                   ts: int, cmds: list) -> None:
        """目标1 前置(Ts-310~Ts-1),模板"多目标成像记录"sheet(无 AI 指令)。"""
        t = (plan.get("targets") or [{}])[idx]
        storage_id = int(t.get("storage_task_id",
                               plan.get("storage_task_no", 61)))
        file_id = int(t.get("raw_file_no", idx + 1))
        comp = int(plan.get("compression", 4))
        # Ts-310 记录任务包
        self._emit(cmds, ts - B.SEQ_OFF_RECORD_TASK, taskno,
                    B.FWD_MASTER_DATATRANS, B.FWD_SUB_DATA_BLOCK,
                    B.build_record_task_package(),
                    "记录任务包", "记录任务包",
                    "Ts-310 载综下发, 功能识别1140/工作时长1800s",
                    base_ts=ts)
        # Ts-305 相机数据块1(多目标时为首包)
        self._emit(cmds, ts - B.SEQ_OFF_CAMERA, taskno,
                    B.FWD_MASTER_CAMERA, B.FWD_SUB_DATA_BLOCK,
                    B.build_camera_block(
                        plan, idx, self._cam_role(
                            idx, len(plan.get("targets") or []))),
                    "相机数据块", "相机数据块57B",
                    "Ts-305 相机下发, 57B逐字段大端",
                    base_ts=ts)
        # Ts-210 姿控242字节数据块1(0F11有几个目标填几个,单块最多5个)
        att_first, att_count = self._att_span(plan, 0)
        self._emit(cmds, ts - B.SEQ_OFF_ATTITUDE, taskno,
                    B.FWD_MASTER_ATTITUDE, B.FWD_SUB_DATA_BLOCK,
                    B.build_attitude_block(plan, att_first, att_count),
                    "姿控数据块", "姿控数据块242B",
                    "Ts-210 姿控下发, 242B 特征码66H+40B单元",
                    base_ts=ts)
        # Ts-208 多任务有效
        self._emit(cmds, ts - B.SEQ_OFF_MULTITASK, taskno,
                    B.FWD_MASTER_ATTITUDE, B.FWD_SUB_INDIRECT_CMD,
                    B.build_multi_task_valid_cmd(),
                    "多任务有效", "多任务有效",
                    "Ts-208 姿控间接指令, 4B 01AB01AA",
                    base_ts=ts)
        # Ts-100 固存记录(载荷数据,1160)
        self._emit(cmds, ts - B.SEQ_OFF_STORAGE, taskno,
                    B.FWD_MASTER_DATATRANS, B.FWD_SUB_DATA_BLOCK,
                    B.build_storage_record_package(False, storage_id, file_id),
                    "固存记录", "固存记录",
                    "Ts-100 载综下发, 原始1160, 10B",
                    base_ts=ts)
        # Ts-96 固存记录(小固存数据,1162)
        self._emit(cmds, ts - B.SEQ_OFF_SMALL_STORAGE, taskno,
                    B.FWD_MASTER_DATATRANS, B.FWD_SUB_DATA_BLOCK,
                    B.build_small_storage_record_package(storage_id, file_id, comp),
                    "小固存记录", "小固存记录",
                    "Ts-96 载综下发, 1162, 任务号+300",
                    base_ts=ts)
        # Ts-95 压缩参数设置1
        self._emit(cmds, ts - B.SEQ_OFF_COMPRESS, taskno,
                    B.FWD_MASTER_DATATRANS, B.FWD_SUB_DATA_BLOCK,
                    B.build_compress_param_package(comp),
                    "压缩参数", "压缩参数",
                    "Ts-95 载综下发, 2001, 10B",
                    base_ts=ts)
        # Ts-2 星图清零
        self._emit(cmds, ts - B.SEQ_OFF_STARMAP_CLEAR, taskno,
                    B.FWD_MASTER_ATT_IF, B.FWD_SUB_INDIRECT_CMD,
                    B.build_starmap_clear_cmd(),
                    "星图清零", "星图清零",
                    "Ts-2 姿控接口板, 199A5500",
                    base_ts=ts)
        # Ts-1 星敏记录开
        self._emit(cmds, ts - B.SEQ_OFF_STARSENSOR_REC_ON, taskno,
                    B.FWD_MASTER_ATT_IF, B.FWD_SUB_INDIRECT_CMD,
                    B.build_star_sensor_record_on_cmd(),
                    "星敏记录开", "星敏记录开",
                    "Ts-1 姿控接口板, 1998FFFF",
                    base_ts=ts)

    def _emit_multi_later_preamble(self, plan: dict, taskno: int, idx: int,
                                   ts: int, cmds: list) -> None:
        """目标2..N 前置(TsN-10~TsN-1),无 AI/无处理数据固存记录。"""
        t = (plan.get("targets") or [{}])[idx] if idx < len(
            plan.get("targets") or []) else {}
        storage_id = int(t.get("storage_task_id",
                               plan.get("storage_task_no", 61)))
        file_id = int(t.get("raw_file_no", idx + 1))
        comp = int(plan.get("compression", 4))
        # Ts{N}-10 相机57字节数据块N(中间包/尾包)
        self._emit(cmds, ts - B.SEQ_OFF_SEG_CAMERA, taskno,
                    B.FWD_MASTER_CAMERA, B.FWD_SUB_DATA_BLOCK,
                    B.build_camera_block(
                        plan, idx, self._cam_role(
                            idx, len(plan.get("targets") or []))),
                    f"相机数据块{idx + 1}", "相机数据块57B",
                    f"Ts{idx + 1}-10 相机下发, 57B",
                    base_ts=ts)
        # Ts{N}-5 固存记录(载荷数据,1160)
        self._emit(cmds, ts - B.SEQ_OFF_SEG_STORAGE, taskno,
                    B.FWD_MASTER_DATATRANS, B.FWD_SUB_DATA_BLOCK,
                    B.build_storage_record_package(False, storage_id, file_id),
                    "固存记录", "固存记录",
                    f"Ts{idx + 1}-5 载综下发, 原始1160, 10B",
                    base_ts=ts)
        # Ts{N}-3 压缩参数设置1
        self._emit(cmds, ts - 3, taskno,
                    B.FWD_MASTER_DATATRANS, B.FWD_SUB_DATA_BLOCK,
                    B.build_compress_param_package(comp),
                    "压缩参数", "压缩参数",
                    f"Ts{idx + 1}-3 载综下发, 2001, 10B",
                    base_ts=ts)
        # Ts{N}-2 星图清零
        self._emit(cmds, ts - B.SEQ_OFF_STARMAP_CLEAR, taskno,
                    B.FWD_MASTER_ATT_IF, B.FWD_SUB_INDIRECT_CMD,
                    B.build_starmap_clear_cmd(),
                    "星图清零", "星图清零",
                    f"Ts{idx + 1}-2 姿控接口板, 199A5500",
                    base_ts=ts)
        # Ts{N}-1 星敏记录开
        self._emit(cmds, ts - B.SEQ_OFF_STARSENSOR_REC_ON, taskno,
                    B.FWD_MASTER_ATT_IF, B.FWD_SUB_INDIRECT_CMD,
                    B.build_star_sensor_record_on_cmd(),
                    "星敏记录开", "星敏记录开",
                    f"Ts{idx + 1}-1 姿控接口板, 1998FFFF",
                    base_ts=ts)

    def _emit_multi_post(self, plan: dict, taskno: int, idx: int,
                         te: int, cmds: list, base_ts: int = 0) -> None:
        """成像后置指令(多目标成像记录模式):Te+1/Te+2/Te+5,无处理停止码。"""
        # Te+1 星敏记录关
        self._emit(cmds, te + B.SEQ_OFF_STARSENSOR_REC_OFF, taskno,
                    B.FWD_MASTER_ATT_IF, B.FWD_SUB_INDIRECT_CMD,
                    B.build_star_sensor_record_off_cmd(),
                    "星敏记录关", "星敏记录关",
                    "Te+1 姿控接口板, 19980000",
                    base_ts=base_ts)
        # Te+2 星敏下传
        self._emit(cmds, te + B.SEQ_OFF_STARSENSOR_DLINK, taskno,
                    B.FWD_MASTER_ATT_IF, B.FWD_SUB_INDIRECT_CMD,
                    B.build_star_sensor_downlink_cmd(),
                    "星敏下传", "星敏下传",
                    "Te+2 姿控接口板, 1999AAAA",
                    base_ts=base_ts)
        # Te+5 记录停止码(载荷数据,116F)
        self._emit(cmds, te + B.SEQ_OFF_RECORD_STOP, taskno,
                    B.FWD_MASTER_DATATRANS, B.FWD_SUB_DATA_BLOCK,
                    B.build_record_stop_cmd(False),
                    "记录停止码", "记录停止码",
                    "Te+5 载综下发, 原始116F, 4B",
                    base_ts=base_ts)

    # ---- 0F22 数传指令序列 ----

    def _generate_0f22(self, plan: dict) -> CommandSequence:
        """0F22 数传计划 → 指令序列(相对时间基准=数传开始时间 track_start)。"""
        files = plan.get("files") or []
        if not files:
            return CommandSequence(target_id="0F22", commands=())
        cmds: list[Command] = []
        # 数传开始/结束时间(相对时间基准)
        ts = int(plan.get("track_start", 0))
        te = int(plan.get("track_end", ts + 100))
        link_type = int(plan.get("link_type", 1))
        rate_code = int(plan.get("playback_rate", 1)) & 0x0F
        station_id = int(plan.get("station_id", 1))
        station_lon = float(plan.get("station_lon", 0.0))
        station_lat = float(plan.get("station_lat", 0.0))
        # 控制开始
        self._emit_control_flag(cmds, B.CTRL_START_MARKER, "控制开始标志",
                                "序列起始哨兵")
        # Ts-296 姿控禁切(仅回放)
        self._emit(cmds, ts - 296, self._taskno,
                    B.FWD_MASTER_ATTITUDE, B.FWD_SUB_INDIRECT_CMD,
                    B.build_datatrans_att_cmd(B.DT_ATT_DISABLE_SWITCH),
                    "姿控禁切", "数传姿控指令",
                    "Ts-296 姿控, 不允许对日/对地自主切换",
                    base_ts=ts)
        # Ts-295 姿控对地模式(仅回放)
        self._emit(cmds, ts - 295, self._taskno,
                    B.FWD_MASTER_ATTITUDE, B.FWD_SUB_INDIRECT_CMD,
                    B.build_datatrans_att_cmd(B.DT_ATT_EARTH_MODE),
                    "姿控对地模式", "数传姿控指令",
                    "Ts-295 姿控, 对地运行模式",
                    base_ts=ts)
        # Ts-95 记录任务包
        self._emit(cmds, ts - B.SEQ_OFF_COMPRESS, self._taskno,
                    B.FWD_MASTER_DATATRANS, B.FWD_SUB_DATA_BLOCK,
                    B.build_record_task_package(),
                    "记录任务包", "记录任务包",
                    "Ts-95 载综下发, 1140/1800s",
                    base_ts=ts)
        # Ts-95 对地回放任务包
        self._emit(cmds, ts - B.SEQ_OFF_COMPRESS, self._taskno,
                    B.FWD_MASTER_DATATRANS, B.FWD_SUB_DATA_BLOCK,
                    B.build_ground_playback_task_package(
                        rate_code, 0x03, station_id, station_lon, station_lat),
                    "对地回放任务包", "对地回放任务包",
                    "Ts-95 载综下发, 1141, 46B",
                    base_ts=ts)
        # 数传开始 固存回放指令
        self._emit(cmds, ts, self._taskno,
                    B.FWD_MASTER_DATATRANS, B.FWD_SUB_DATA_BLOCK,
                    B.build_storage_playback_cmd(link_type, files, ts, te),
                    "固存回放指令", "固存回放指令80B",
                    "数传开始时下发, 80B=16头+16×4回放参数",
                    base_ts=ts)
        # Te+1 固存回放停止(对地1173/广播1174/星间1175)
        self._emit(cmds, te + 1, self._taskno,
                    B.FWD_MASTER_DATATRANS, B.FWD_SUB_DATA_BLOCK,
                    B.build_storage_playback_stop_cmd(link_type),
                    "固存回放停止", "固存回放停止",
                    "Te+1 载综下发, 固存回放停止码4B",
                    base_ts=ts)
        # Te+2 数传一键关机
        self._emit(cmds, te + 2, self._taskno,
                    B.FWD_MASTER_DATATRANS, B.FWD_SUB_DATA_BLOCK,
                    B.build_datatrans_onekey_shutdown_cmd(),
                    "数传一键关机", "数传一键关机",
                    "Te+2 载综下发, 1131, 2B",
                    base_ts=ts)
        # Te+3 姿控允切
        self._emit(cmds, te + 3, self._taskno,
                    B.FWD_MASTER_ATTITUDE, B.FWD_SUB_INDIRECT_CMD,
                    B.build_datatrans_att_cmd(B.DT_ATT_ENABLE_SWITCH),
                    "姿控允切", "数传姿控指令",
                    "Te+3 姿控, 允许对日/对地自主切换",
                    base_ts=ts)
        # 控制结束
        self._emit_control_flag(cmds, B.CTRL_END_MARKER, "控制结束标志",
                                "序列结束哨兵")
        return CommandSequence(
            target_id="0F22",
            commands=tuple(cmds),
            gen_local_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            plan_source="0F22",
        )

    # ---- emit 基础设施 ----

    def _emit(self, cmds: list, time_sec: int, taskno: int,
              master: int, sub: int, field: bytes,
              name: str, block_kind: str, remark: str,
              base_ts: int = 0) -> None:
        """构帧并落成 Command。

        - codeword = 完整发送帧(含 EB90 头)
        - abs_time_sec = 绝对 2009 历元秒
        - time_tag = 相对时间(秒,相对 base_ts);base_ts=0 时退化为绝对秒
        """
        frame = B.build_wrapped_frame(taskno, time_sec, master, sub, field)
        main_hdr = _MASTER_NAME.get(master, "未知")
        sub_hdr = _SUB_NAME.get(sub, "未知")
        rel = float(time_sec - base_ts) if base_ts else float(time_sec)
        cmds.append(Command(
            time_tag=rel,
            codeword=frame,
            name=name,
            main_header=main_hdr,
            sub_header=sub_hdr,
            block_kind=block_kind,
            remark=remark,
            abs_time_sec=float(time_sec),
        ))

    def _emit_control_flag(self, cmds: list, marker: int, name: str,
                           remark: str) -> None:
        """控制开始/结束标志(星务+间接指令, 时标=哨兵值)。"""
        field = B.build_control_flag(marker)
        frame = B.build_wrapped_frame(
            0x00, marker, B.FWD_MASTER_SATSVC,
            B.FWD_SUB_INDIRECT_CMD, field)
        cmds.append(Command(
            time_tag=float(marker),
            codeword=frame,
            name=name,
            main_header="星务",
            sub_header="间接指令",
            block_kind=name,
            remark=remark,
            abs_time_sec=float(marker),
        ))
