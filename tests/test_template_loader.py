"""指令模板加载测试:从真实 xlsm 解析任务序列模板。"""
import os

import pytest

from rwgh.planning.template_loader import load_templates_from_xlsm
from rwgh.planning.templates import (
    TEMPLATE_MULTI_TARGET_IMAGING,
    TEMPLATE_GROUND_DATALINK_PLAYBACK,
    load_real_templates,
)
from rwgh.planning.template_compare import TemplateComparator
from rwgh.models.command import Command, CommandSequence

XLSM = r"D:\wenxj\7-型号\zwxxx-3\1_文件\1_任务规划\4_测试相关文件\指令模板_20260918.xlsm"


@pytest.fixture(scope="module")
def templates():
    if not os.path.isfile(XLSM):
        pytest.skip(f"xlsm not found: {XLSM}")
    return load_templates_from_xlsm(XLSM)


def test_loads_multiple_templates(templates):
    """应加载多个任务序列模板。"""
    assert len(templates) >= 5, f"expected >=5 templates, got {len(templates)}"


def test_multi_target_imaging_template(templates):
    """多目标成像记录模板应存在且含控制开始+数据块指令。"""
    tmpl = templates.get(TEMPLATE_MULTI_TARGET_IMAGING)
    assert tmpl is not None, f"missing template: {TEMPLATE_MULTI_TARGET_IMAGING}"
    assert len(tmpl.expected) >= 4
    # 第一条应是控制开始(同步码字)
    first = tmpl.expected[0]
    assert first.codeword == bytes.fromhex("EB90146F")
    assert "控制开始" in first.name
    # 应有记录任务包(codeword 空,数据块引用)
    names = [c.name for c in tmpl.expected]
    assert any("记录任务包" in n for n in names)


def test_time_offsets(templates):
    """时间标定应解析为相对秒(Ts-310 → -310.0)。"""
    tmpl = templates[TEMPLATE_MULTI_TARGET_IMAGING]
    # 找记录任务包(Ts-310)
    rec = [c for c in tmpl.expected if "记录任务包" in c.name]
    assert len(rec) == 1
    assert rec[0].time_tag == -310.0
    # 找相机57字节数据块1(Ts-305)
    cam = [c for c in tmpl.expected if "相机57" in c.name]
    assert len(cam) >= 1
    assert cam[0].time_tag == -305.0


def test_sub_main_headers(templates):
    """副导头/主导头应正确提取。"""
    tmpl = templates[TEMPLATE_MULTI_TARGET_IMAGING]
    first = tmpl.expected[0]
    assert first.sub_header == "间接指令"
    assert first.main_header == "星务"
    # 记录任务包: 下位机数据块 / 载综
    rec = [c for c in tmpl.expected if "记录任务包" in c.name][0]
    assert rec.sub_header == "下位机数据块"
    assert rec.main_header == "载综"


def test_datalink_template(templates):
    """对地数传任务_回放模板应含数传开始/停止指令。"""
    tmpl = templates.get(TEMPLATE_GROUND_DATALINK_PLAYBACK)
    assert tmpl is not None
    assert len(tmpl.expected) >= 3
    # 应含姿控间接指令(018004AA 对地运行模式)
    codes = [c.codeword for c in tmpl.expected if c.codeword]
    assert bytes.fromhex("018004AA") in codes


def test_comparator_with_real_template(templates):
    """用真实模板做比对:生成匹配指令应 passed,缺指令应失败。"""
    tmpl = templates[TEMPLATE_MULTI_TARGET_IMAGING]
    comp = TemplateComparator()
    comp.register(tmpl)

    # 完全匹配
    matched = CommandSequence(
        target_id="T001",
        commands=tuple(Command(
            time_tag=c.time_tag,
            codeword=c.codeword,
            name=c.name,
            sub_header=c.sub_header,
            main_header=c.main_header,
        ) for c in tmpl.expected),
    )
    result = comp.compare(matched, TEMPLATE_MULTI_TARGET_IMAGING)
    assert result.passed is True
    assert result.discrepancy_count == 0

    # 缺一条
    missing = CommandSequence(
        target_id="T002",
        commands=tmpl.expected[1:],  # 去掉第一条
    )
    result2 = comp.compare(missing, TEMPLATE_MULTI_TARGET_IMAGING)
    assert result2.passed is False
    assert result2.discrepancy_count >= 1


def test_load_real_templates_fallback():
    """文件不存在时 load_real_templates 返回空 dict。"""
    result = load_real_templates("/nonexistent/path.xlsm")
    assert result == {}
