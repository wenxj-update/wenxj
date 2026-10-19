"""可见性计算结果页:4 个子页(0F11/0F22/0F33/0F44)规划结果报文。

点击「计算可见性」→ 算法库(pipeline 内可见性算法)输出可见性窗口 →
主窗口按《任务规划输入输出数据包》字段定义构建四类规划结果报文,
经 set_results() 装入对应子页。每个子页均为
"Hex(可手动输入) + 固定区解析表 + 记录表"结构,支持编辑回写与整行删除。

星时修改功能已移至主窗口 HeaderBar,与星时显示放在一起。
"""
from __future__ import annotations

from datetime import datetime

from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                               QTabWidget, QFrame)

from ..theme import C
from .packet_panel import PacketPanel
from .result_views import (create_0f11_panel, create_0f22_panel,
                           create_0f33_panel, create_0f44_panel,
                           empty_0f22_info, empty_0f44_info)

_SUMMARY_WAIT = ("等待可见性计算…点击「计算可见性」按钮,由算法库生成 "
                 "0F11/0F22/0F33/0F44 规划结果")


class VisibilityComputeView(QWidget):
    """可见性计算结果页:0F11/0F22/0F33/0F44 四个子页容器。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.panel_0f11 = create_0f11_panel()
        self.panel_0f22 = create_0f22_panel()
        self.panel_0f33 = create_0f33_panel()
        self.panel_0f44 = create_0f44_panel()

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # ---- 顶部批次摘要条 ----
        info = QFrame()
        info.setObjectName("Card")
        info.setFixedHeight(34)
        il = QHBoxLayout(info)
        il.setContentsMargins(14, 4, 14, 4)
        self._lbl_summary = QLabel(_SUMMARY_WAIT)
        self._lbl_summary.setStyleSheet(f"color:{C.FG_DIM}; font-size:12px;")
        il.addWidget(self._lbl_summary)
        il.addStretch()
        lay.addWidget(info)

        # ---- 4 个子页 ----
        self.sub_tabs = QTabWidget()
        self.sub_tabs.addTab(self.panel_0f11, "0F11 待执行成像")
        self.sub_tabs.addTab(self.panel_0f22, "0F22 待执行数传")
        self.sub_tabs.addTab(self.panel_0f33, "0F33 成像反馈结果")
        self.sub_tabs.addTab(self.panel_0f44, "0F44 数传反馈结果")
        lay.addWidget(self.sub_tabs, 1)

    # ---------- 数据接入 ----------

    def set_results(self, f11: dict, f22: dict | None,
                    f33: dict, f44: dict | None) -> None:
        """装入四类规划结果报文(f22/f44 为 None 时显示空包)。"""
        self.panel_0f11.load_info(f11)
        self.panel_0f22.load_info(f22 if f22 is not None
                                  else empty_0f22_info())
        self.panel_0f33.load_info(f33)
        self.panel_0f44.load_info(f44 if f44 is not None
                                  else empty_0f44_info())
        n_img = len(f11.get("targets") or [])
        n_file = len((f22 or {}).get("files") or [])
        tasks = f33.get("tasks") or []
        ok = sum(1 for t in tasks if int(t.get("status", -1)) == 0x00)
        # 0F44 数传反馈状态
        f44_tasks = (f44 or {}).get("tasks") or []
        f44_ok = sum(1 for t in f44_tasks
                     if int(t.get("status", -1)) == 0x00)
        ts = datetime.now().strftime("%H:%M:%S")
        self._lbl_summary.setText(
            f"规划结果已生成 [{ts}] · 0F11 成像目标 {n_img} · "
            f"0F22 回放文件 {n_file} · 0F33 反馈任务 {len(tasks)}"
            f"(规划成功 {ok}) · 0F44 数传反馈 {len(f44_tasks)}"
            f"(规划成功 {f44_ok})")

    # ---------- 导出/清除 ----------

    def export_data(self) -> tuple[str, list]:
        cur = self.sub_tabs.currentWidget()
        if isinstance(cur, PacketPanel):
            _, rows = cur.export_data()
            return (self.sub_tabs.tabText(self.sub_tabs.currentIndex()), rows)
        return ("可见性计算结果", [])

    def clear_data(self) -> None:
        self.panel_0f11.clear_data()
        self.panel_0f22.clear_data()
        self.panel_0f33.clear_data()
        self.panel_0f44.clear_data()
        self._lbl_summary.setText(_SUMMARY_WAIT)
