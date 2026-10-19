# -*- coding: utf-8 -*-
"""离屏渲染新 UI 各 Tab 截图(仅开发期视觉检查用)。"""
import os
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFontDatabase
from PySide6.QtCore import QTimer

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
from rwgh.ui.theme import APP_QSS

ROOT = os.path.join(os.path.dirname(__file__), "..")
OUT = os.path.join(ROOT, "tmp_shots")
os.makedirs(OUT, exist_ok=True)

cfg = load_config(os.path.join(ROOT, "config", "app.yaml"))
bus = EventBus()
reg = FormatRegistry()
load_dir(os.path.join(ROOT, "config", "formats"), reg)
parser = FrameParser()
pipe = Pipeline(bus, reg, parser, StubVisibilityAlgorithm(),
                StubCommandGenerator(), TemplateComparator(),
                VisibilityReportBuilder(parser))
pipe.start()

app = QApplication([])
# offscreen 环境显式加载微软雅黑,真实桌面无需此步
QFontDatabase.addApplicationFont(r"C:\Windows\Fonts\msyh.ttc")
QFontDatabase.addApplicationFont(r"C:\Windows\Fonts\consola.ttf")
app.setStyleSheet(APP_QSS)
from rwgh.ui.main_window import MainWindow
win = MainWindow(cfg, bus, reg, parser, pipe)
win.resize(1320, 840)
win.show()

# 注入两拍(第二拍时刻 +60s),产生多条记录
win._inject_mock()
win._inject_mock()

for _ in range(30):
    app.processEvents()

names = ["01_message", "02_packet", "03_visibility", "04_comparison"]
for i, name in enumerate(names):
    win.tabs.setCurrentIndex(i)
    for _ in range(10):
        app.processEvents()
    win.grab().save(os.path.join(OUT, name + ".png"))
    print("saved", name)

win.close()
pipe.stop()
print("SHOTS DONE ->", OUT)
