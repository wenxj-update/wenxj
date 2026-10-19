"""GUI 冒烟测试:offscreen 模式启动 MainWindow,注入 mock 报文,断言视图收到数据。

不依赖真实 STK/TCP/dll 与 pytest-qt,用 QApplication 直接驱动事件队列。
"""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from rwgh.core.config import load_config
from rwgh.core.event_bus import EventBus, Topics
from rwgh.parsing.parser import FrameParser
from rwgh.parsing.registry import FormatRegistry
from rwgh.parsing.loader import load_dir
from rwgh.algorithm.visibility import StubVisibilityAlgorithm
from rwgh.planning.command_gen import StubCommandGenerator
from rwgh.planning.template_compare import TemplateComparator
from rwgh.planning.visibility_report import VisibilityReportBuilder
from rwgh.planning.pipeline import Pipeline


FORMATS = os.path.join(os.path.dirname(__file__), "..", "config", "formats")
CONFIG = os.path.join(os.path.dirname(__file__), "..", "config", "app.yaml")


def _make_app():
    cfg = load_config(CONFIG)
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
    return cfg, bus, reg, parser, pipe, comp


def test_main_window_smoke():
    app = QApplication.instance() or QApplication([])
    cfg, bus, reg, parser, pipe, comp = _make_app()

    from rwgh.ui.main_window import MainWindow
    win = MainWindow(cfg, bus, reg, parser, pipe)
    win.show()

    spec = reg.get("stk_time")
    frame = parser.build(spec, {
        "packet_type": 0x0B01, "total_packets": 1, "sequence_no": 1,
        "cur_packet_no": 1, "cur_packet_len": spec.total_length,
        "time_seconds": 557467200, "time_millis": 0,
    })
    bus.publish(Topics.RAW_FRAME, frame)

    # 处理 Qt 事件队列,让 queued 信号送达视图
    for _ in range(20):
        app.processEvents()

    assert win.msg_view._model.rowCount() >= 1, "message view empty"
    assert win.pkt_view._model.rowCount() >= 1, "packet detail view empty"
    # 可见性结果页:0F11 成像方案与 0F33 反馈应装入记录(占位目标可见)
    assert (win.vis_compute_view.panel_0f11._record_model.rowCount() >= 1 or
            win.vis_compute_view.panel_0f33._record_model.rowCount() >= 1
            ), "visibility result view empty"
    assert win.cmp_result_view._hist_model.rowCount() >= 1, "comparison history empty"
    assert win.cmp_result_view._detail_model.rowCount() >= 1, "comparison detail empty"

    win.close()
    pipe.stop()
