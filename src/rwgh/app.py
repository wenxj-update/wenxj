"""应用入口:装配依赖、按 mode 选择真实/Stub 实现、启动 GUI。"""
from __future__ import annotations

import logging
import os
import sys

from .core.config import load_config
from .core.event_bus import EventBus
from .core.logging import setup_logging
from .parsing.loader import load_dir
from .parsing.parser import FrameParser
from .parsing.registry import FormatRegistry
from .algorithm.visibility import StubVisibilityAlgorithm, CtVisibilityAlgorithm
from .algorithm.loader import LibraryLoader
from .algorithm.signature import default_registry
from .planning.command_gen import StubCommandGenerator
from .planning.star_command_sequence import ImagePlanCommandGenerator
from .planning.template_compare import TemplateComparator
from .planning.visibility_report import VisibilityReportBuilder
from .planning.templates import make_stub_template, load_real_templates
from .planning.pipeline import Pipeline

_log = logging.getLogger("rwgh.app")

CONFIG_PATH = os.environ.get("RWGH_CONFIG", "config/app.yaml")
FORMATS_DIR = os.environ.get("RWGH_FORMATS", "config/formats")


def build_pipeline(cfg, bus, registry, parser) -> tuple[Pipeline, object]:
    """按 mode 装配可见性算法与指令生成器,返回 (pipeline, transport_or_None)。"""
    # 可见性算法:算法库支持 .dll(动态库)/.lib(静态库或导入库),自动适配
    if cfg.mode == "real" and cfg.algorithm.visibility_dll:
        reg = default_registry()   # 真实接口签名 DllInit/DllInput/DllOutput
        deps = [d.strip() for d in
                (cfg.algorithm.lib_extra_deps or "").split(";") if d.strip()]
        dll = LibraryLoader(extra_deps=deps).load(cfg.algorithm.visibility_dll, reg)
        _log.info("算法库已加载(%s): %s", dll.backend,
                  cfg.algorithm.visibility_dll)
        vis_algo = CtVisibilityAlgorithm(dll)
    else:
        vis_algo = StubVisibilityAlgorithm()

    cmd_gen = ImagePlanCommandGenerator()   # 星上指令生成(C代码移植)
    comparator = TemplateComparator()
    report_builder = VisibilityReportBuilder(parser)

    # 真实指令模板加载(扩展点5:xlsm 提供)
    if cfg.command_template:
        real_templates = load_real_templates(cfg.command_template)
        for name, tmpl in real_templates.items():
            comparator.register(tmpl)
        _log.info("registered %d real command templates", len(real_templates))

    # Stub 模板注册(真实模板由用户提供,扩展点5)
    # 用一个 stub 可见性结果预生成模板占位
    from .models.visibility import VisibilityResult, VisibilityWindow
    from datetime import datetime, timezone
    stub = VisibilityResult(satellite="SAT1", windows=(
        VisibilityWindow(target_id="stub", aos=datetime.now(timezone.utc),
                        los=datetime.now(timezone.utc), max_el=45.0),))
    comparator.register(make_stub_template(stub))

    transport = None  # 真实模式下注入 SocketWorker.transport
    pipe = Pipeline(bus, registry, parser, vis_algo, cmd_gen,
                    comparator, report_builder, transport)
    return pipe, transport


def main() -> int:
    cfg = load_config(CONFIG_PATH)
    log = setup_logging(cfg.logging)
    log.info("RWGH starting mode=%s", cfg.mode)

    bus = EventBus()
    registry = FormatRegistry()
    n = load_dir(FORMATS_DIR, registry)
    log.info("loaded %d formats", n)
    parser = FrameParser()

    pipe, _ = build_pipeline(cfg, bus, registry, parser)
    pipe.start()

    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QIcon, QPixmap
    from .ui.main_window import MainWindow
    from .ui.theme import APP_QSS

    app = QApplication(sys.argv)
    app.setStyleSheet(APP_QSS)
    # 全局应用图标(任务栏 + 标题栏)
    _ico = os.path.join(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))), "config", "app_icon.ico")
    _jpg = r"D:\wenxj\6-software\STK\微信图片_20260930175545_675_2.jpg"
    if os.path.exists(_ico):
        app.setWindowIcon(QIcon(_ico))
    elif os.path.exists(_jpg):
        app.setWindowIcon(QIcon(QPixmap(_jpg)))
    win = MainWindow(cfg, bus, registry, parser, pipe)
    win._config_path = CONFIG_PATH
    win.show()
    code = app.exec()
    pipe.stop()
    return code


if __name__ == "__main__":
    sys.exit(main())
