"""指令模板:stub 模板 + 真实 xlsm 模板加载入口。

真实模板常量(对应 xlsm sheet 名):
  TEMPLATE_MULTI_TARGET_IMAGING    = "多目标成像记录"
  TEMPLATE_FOCUS_IMAGING          = "调焦成像"
  TEMPLATE_IMAGING_WITH_PROCESSING = "成像记录+星上处理"
  TEMPLATE_GROUND_DATALINK_PLAYBACK = "对地数传任务_回放"
  TEMPLATE_GROUND_DATALINK_REC_PLAY = "对地数传任务_边记边放"
  TEMPLATE_BROADCAST_DISTRIBUTION  = "广播分发任务"
  TEMPLATE_INTER_SAT_LINK          = "星间建链计划任务"
  TEMPLATE_INTER_SAT_TRANSFER      = "星间传输任务"
  TEMPLATE_ORBIT_CONTROL           = "轨控任务"
  TEMPLATE_SOLID_ERASE            = "固存擦除"

【扩展点5】真实指令模板由用户提供(xlsm),通过 load_real_templates() 加载。
本模块同时提供 MVP 验证用的 stub 模板工厂,与 StubCommandGenerator 配对。
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from ...models.command import Command, CommandTemplate
from ...models.visibility import VisibilityResult
from ..command_gen import CODE_IMAGING_START, CODE_IMAGING_STOP
from ..template_loader import load_templates_from_xlsm
from ..visibility_report import to_relative_seconds

_log = logging.getLogger("rwgh.planning.templates")

# ---- stub 模板(MVP 用)----
TEMPLATE_STUB_IMAGING = "stub_imaging"


def make_stub_template(result: VisibilityResult) -> CommandTemplate:
    """根据可见性结果生成 stub 模板(期望时序,无偏差)。"""
    expected: list[Command] = []
    for w in result.windows:
        expected.append(Command(
            time_tag=to_relative_seconds(w.aos),
            code=CODE_IMAGING_START,
            params=(w.target_id,),
        ))
        expected.append(Command(
            time_tag=to_relative_seconds(w.los),
            code=CODE_IMAGING_STOP,
            params=(w.target_id,),
        ))
    return CommandTemplate(
        name=TEMPLATE_STUB_IMAGING,
        expected=tuple(expected),
        time_tolerance=0.1,
        code_exact=True,
    )

# ---- 真实模板常量(xlsm sheet 名)----
TEMPLATE_MULTI_TARGET_IMAGING = "多目标成像记录"
TEMPLATE_FOCUS_IMAGING = "调焦成像"
TEMPLATE_IMAGING_WITH_PROCESSING = "成像记录+星上处理"
TEMPLATE_IMAGING_WITH_PROCESSING_SLICE = "成像记录+星上处理（切块_保留）"
TEMPLATE_GROUND_DATALINK_PLAYBACK = "对地数传任务_回放"
TEMPLATE_GROUND_DATALINK_REC_PLAY = "对地数传任务_边记边放"
TEMPLATE_BROADCAST_DISTRIBUTION = "广播分发任务"
TEMPLATE_INTER_SAT_LINK = "星间建链计划任务"
TEMPLATE_INTER_SAT_TRANSFER = "星间传输任务"
TEMPLATE_ORBIT_CONTROL = "轨控任务"
TEMPLATE_SOLID_ERASE = "固存擦除"

# 成像类模板(用于成像链路默认模板选择)
IMAGING_TEMPLATES = (
    TEMPLATE_MULTI_TARGET_IMAGING,
    TEMPLATE_FOCUS_IMAGING,
    TEMPLATE_IMAGING_WITH_PROCESSING,
    TEMPLATE_IMAGING_WITH_PROCESSING_SLICE,
)

# 数传类模板(用于数传链路默认模板选择)
DATALINK_TEMPLATES = (
    TEMPLATE_GROUND_DATALINK_PLAYBACK,
    TEMPLATE_GROUND_DATALINK_REC_PLAY,
    TEMPLATE_BROADCAST_DISTRIBUTION,
    TEMPLATE_INTER_SAT_LINK,
    TEMPLATE_INTER_SAT_TRANSFER,
)


def load_real_templates(xlsm_path: str) -> dict[str, CommandTemplate]:
    """从 xlsm 加载真实指令模板。

    若文件不存在或 openpyxl 未安装,返回空 dict(回退到 stub)。
    """
    p = Path(xlsm_path)
    if not p.is_file():
        _log.warning("command template not found: %s (using stub fallback)", p)
        return {}
    try:
        return load_templates_from_xlsm(xlsm_path)
    except Exception as e:  # noqa: BLE001
        _log.error("load real templates failed: %s", e)
        return {}
