"""主链路端到端测试:注入真实 STK 星时报文 -> 解析 -> 可见性 -> 报文 -> 指令 -> 比对。"""
import os

import pytest

from rwgh.core.event_bus import EventBus, Topics
from rwgh.parsing.parser import FrameParser
from rwgh.parsing.registry import FormatRegistry
from rwgh.parsing.loader import load_dir
from rwgh.algorithm.visibility import StubVisibilityAlgorithm
from rwgh.planning.command_gen import StubCommandGenerator
from rwgh.planning.template_compare import TemplateComparator
from rwgh.planning.visibility_report import VisibilityReportBuilder
from rwgh.planning.templates import make_stub_template, TEMPLATE_STUB_IMAGING
from rwgh.planning.pipeline import Pipeline, MockPipelineDriver

FORMATS = os.path.join(os.path.dirname(__file__), "..", "config", "formats")

# 真实星时报文
TIME_HEX = "0B010001000100010010213A46400000"


@pytest.fixture
def pipeline():
    bus = EventBus()
    reg = FormatRegistry()
    load_dir(FORMATS, reg)
    parser = FrameParser()
    vis = StubVisibilityAlgorithm()
    cmd_gen = StubCommandGenerator()
    comp = TemplateComparator()
    repb = VisibilityReportBuilder(parser)
    pipe = Pipeline(bus, reg, parser, vis, cmd_gen, comp, repb)
    pipe.start()
    from rwgh.models.visibility import VisibilityResult, VisibilityWindow
    from datetime import datetime, timezone
    stub_res = VisibilityResult(satellite="SAT1", windows=(
        VisibilityWindow(target_id="x", aos=datetime.now(timezone.utc),
                        los=datetime.now(timezone.utc), max_el=45.0),))
    comp.register(make_stub_template(stub_res))
    return bus, pipe, reg, parser, comp


def test_main_chain_with_real_stk_time(pipeline):
    bus, pipe, reg, parser, comp = pipeline
    captured: dict = {}
    bus.subscribe(Topics.VISIBILITY_RESULT, lambda r: captured.setdefault("vis", r))
    bus.subscribe(Topics.VISIBILITY_REPORT_FRAME,
                  lambda f: captured.setdefault("frames", []).append(f))
    bus.subscribe(Topics.COMMAND_SEQUENCE, lambda s: captured.setdefault("seq", s))
    bus.subscribe(Topics.COMPARISON_RESULT, lambda c: captured.setdefault("cmp", c))
    bus.subscribe(Topics.PARSED_PACKET, lambda p: captured.setdefault("pkt", p))

    MockPipelineDriver(bus).inject_frame(bytes.fromhex(TIME_HEX))

    assert "pkt" in captured
    assert captured["pkt"].fields["packet_type"] == 0x0B01
    assert "vis" in captured
    assert len(captured["frames"]) == 1
    assert len(captured["seq"].commands) == 2
    assert captured["cmp"].passed is False
    assert captured["cmp"].discrepancy_count >= 1
