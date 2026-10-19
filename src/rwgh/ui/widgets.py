"""通用控件:状态指示灯、统计卡片、彩色徽章委托、分区标题。"""
from __future__ import annotations

from PySide6.QtCore import Qt, QSize, QRect
from PySide6.QtGui import QColor, QPainter, QPen, QFont
from PySide6.QtWidgets import (QWidget, QFrame, QLabel, QVBoxLayout,
                               QHBoxLayout, QStyledItemDelegate, QStyle,
                               QTableView, QHeaderView)

from .theme import C

# model 自定义角色:单元格徽章颜色(str hex)
BADGE_COLOR_ROLE = Qt.UserRole + 1
# model 自定义角色:行强调色(左侧色条/文字色)
ROW_ACCENT_ROLE = Qt.UserRole + 2


class LedDot(QWidget):
    """圆形状态指示灯:灰(空闲)/绿(运行)/红(故障)/橙(等待)。"""

    _COLORS = {
        "idle": (C.FG_FAINT, "#2a3448"),
        "run": (C.OK, "#15443a"),
        "error": (C.ERR, "#4a2230"),
        "wait": (C.WARN, "#45331a"),
    }

    def __init__(self, state: str = "idle", size: int = 12, parent=None) -> None:
        super().__init__(parent)
        self._state = state
        self._size = size
        self.setFixedSize(size + 6, size + 6)

    def set_state(self, state: str) -> None:
        self._state = state
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        core, halo = self._COLORS.get(self._state, self._COLORS["idle"])
        s = self._size
        x = (self.width() - s) / 2
        y = (self.height() - s) / 2
        # 外圈光晕
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(halo))
        p.drawEllipse(QRect(int(x) - 3, int(y) - 3, s + 6, s + 6))
        # 实心
        p.setBrush(QColor(core))
        p.drawEllipse(QRect(int(x), int(y), s, s))
        # 高光
        p.setBrush(QColor(255, 255, 255, 70))
        p.drawEllipse(QRect(int(x) + 2, int(y) + 2, max(s // 3, 2),
                            max(s // 3, 2)))


class StatCard(QFrame):
    """统计卡片:标题 + 大数值,左侧色条。"""

    def __init__(self, title: str, value: str = "0", accent: str = C.ACCENT,
                 mono: bool = False, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        self.setFixedHeight(54)
        self._accent = accent

        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 6, 12, 6)
        lay.setSpacing(8)

        self._bar = QFrame()
        self._bar.setFixedWidth(4)
        self._bar.setStyleSheet(
            f"background:{accent}; border-radius:2px;")
        lay.addWidget(self._bar)

        box = QVBoxLayout()
        box.setSpacing(2)
        self._title = QLabel(title)
        self._title.setObjectName("CardTitle")
        self._value = QLabel(value)
        self._value.setObjectName("CardValueMono" if mono else "CardValue")
        box.addWidget(self._title)
        box.addWidget(self._value)
        lay.addLayout(box)
        lay.addStretch()

    def set_value(self, value: str) -> None:
        self._value.setText(str(value))

    def set_accent(self, color: str) -> None:
        self._accent = color
        self._bar.setStyleSheet(f"background:{color}; border-radius:2px;")


class SectionTitle(QWidget):
    """分区标题:色点 + 文字 + 可选右侧附加标签。"""

    def __init__(self, text: str, accent: str = C.ACCENT,
                 right: QWidget | None = None, parent=None) -> None:
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(2, 0, 2, 2)
        lay.setSpacing(6)
        dot = QFrame()
        dot.setFixedSize(7, 7)
        dot.setStyleSheet(
            f"background:{accent}; border-radius:3px;")
        lbl = QLabel(text)
        lbl.setObjectName("SectionTitle")
        lbl.setStyleSheet(f"font-size:13px; font-weight:700; color:{C.FG};")
        lay.addWidget(dot)
        lay.addWidget(lbl)
        lay.addStretch()
        if right is not None:
            lay.addWidget(right)


class BadgeDelegate(QStyledItemDelegate):
    """徽章列委托:按 BADGE_COLOR_ROLE 返回的颜色绘制圆角胶囊。

    无颜色角色时按普通文本绘制。
    """

    def paint(self, painter: QPainter, option, index) -> None:
        color = index.data(BADGE_COLOR_ROLE)
        text = index.data(Qt.DisplayRole)
        if not color or text is None or text == "":
            super().paint(painter, option, index)
            return

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        # 选中行背景由 view 处理;这里仅画徽章
        rect = option.rect
        font = QFont(option.font)
        font.setBold(True)
        font.setPointSizeF(font.pointSizeF() - 0.5)
        painter.setFont(font)
        fm = painter.fontMetrics()
        tw = fm.horizontalAdvance(str(text))
        pad_x = 10
        bw = min(tw + pad_x * 2, rect.width() - 12)
        bh = 22
        bx = rect.left() + 6
        by = rect.top() + (rect.height() - bh) // 2
        badge = QRect(bx, by, bw, bh)

        base = QColor(color)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(base.red(), base.green(), base.blue(), 38))
        painter.drawRoundedRect(badge, 11, 11)
        pen = QPen(base, 1.2)
        painter.setPen(pen)
        painter.drawRoundedRect(badge, 11, 11)
        painter.setPen(base.lighter(135))
        painter.drawText(badge, Qt.AlignCenter, str(text))
        painter.restore()

    def sizeHint(self, option, index) -> QSize:
        return QSize(super().sizeHint(option, index).width(), 26)


class MonoDelegate(QStyledItemDelegate):
    """等宽字体委托(hex 列用)。"""

    def paint(self, painter: QPainter, option, index) -> None:
        painter.save()
        opt = option
        from PySide6.QtWidgets import QStyleOptionViewItem
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        opt.font.setFamily("Cascadia Mono, Consolas, monospace")
        opt.font.setPointSizeF(opt.font.pointSizeF() - 0.5)
        widget = opt.widget
        style = widget.style() if widget else None
        from PySide6.QtWidgets import QApplication
        (style or QApplication.style()).drawControl(
            QStyle.CE_ItemViewItem, opt, painter, widget)
        painter.restore()


class DataTableView(QTableView):
    """通用数据表:

    - 所有列均为 Interactive 模式时,窗口拉宽后列宽按比例自动填满视口,
      不会出现最后一列后面的灰色空白;视口窄于列宽总和时保留横向滚动条;
    - 若某列被外部设置为 Stretch/Fixed 模式,则不干预列宽;
    - 无数据时在视口中央绘制占位提示,避免大片空白。
    """

    def __init__(self, parent=None, empty_text: str = "暂无数据") -> None:
        super().__init__(parent)
        self._empty_text = empty_text
        self._base_widths: dict[int, int] = {}
        hh = self.horizontalHeader()
        hh.setStretchLastSection(False)
        hh.setSectionResizeMode(QHeaderView.Interactive)

    def set_empty_text(self, text: str) -> None:
        self._empty_text = text
        self.viewport().update()

    def setColumnWidth(self, column: int, width: int) -> None:
        # 记录外部设定的基准宽度,自适应填充时以此为比例依据
        self._base_widths[column] = int(width)
        super().setColumnWidth(column, width)

    # ---------- 列宽自适应 ----------

    def _all_sections_interactive(self) -> bool:
        hh = self.horizontalHeader()
        model = self.model()
        if model is None:
            return False
        for i in range(model.columnCount()):
            if hh.sectionResizeMode(i) != QHeaderView.Interactive:
                return False
        return True

    def _fit_columns(self) -> None:
        model = self.model()
        if model is None or model.columnCount() == 0:
            return
        if not self._all_sections_interactive():
            return
        hh = self.horizontalHeader()
        n = model.columnCount()
        viewport_w = self.viewport().width()
        min_w = hh.minimumSectionSize()
        bases = []
        for i in range(n):
            w = self._base_widths.get(i, 0)
            if w <= 0:
                w = max(hh.sectionSizeHint(i), min_w, 60)
            bases.append(w)
        total = sum(bases)
        if total >= viewport_w or total <= 0:
            widths = bases
        else:
            extra = viewport_w - total
            widths = list(bases)
            add = [extra * w // total for w in bases]
            for i, a in enumerate(add):
                widths[i] += a
            remain = extra - sum(add)
            i = 0
            while remain > 0:
                widths[i % n] += 1
                remain -= 1
                i += 1
        for i, w in enumerate(widths):
            super().setColumnWidth(i, w)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._fit_columns()

    # ---------- 空数据占位 ----------

    def setModel(self, model) -> None:
        super().setModel(model)
        if model is not None:
            # 结构重置/列数变化时重新分配列宽,保证数据装入已显示的面板后
            # 仍能填满视口;行变化只需重绘占位提示
            model.modelReset.connect(self._on_model_structure_changed)
            model.columnsInserted.connect(self._on_model_structure_changed)
            model.columnsRemoved.connect(self._on_model_structure_changed)
            model.rowsInserted.connect(self.viewport().update)
            model.rowsRemoved.connect(self.viewport().update)
        self._fit_columns()
        self.viewport().update()

    def _on_model_structure_changed(self, *args) -> None:
        self._fit_columns()
        self.viewport().update()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        model = self.model()
        if model is None or model.rowCount() > 0 or not self._empty_text:
            return
        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.Antialiasing)
        # 显式指定中文字体族:手动创建的 QPainter 不继承 QSS 字体,
        # 不指定会导致中文显示为豆腐块;QSS 用像素字号时 pointSizeF()
        # 为 -1,必须通过 fontInfo() 取实际渲染字号
        info = self.fontInfo()
        font = QFont("Microsoft YaHei UI")
        font.setStyleHint(QFont.SansSerif)
        if info.pixelSize() > 0:
            font.setPixelSize(info.pixelSize() + 4)
        else:
            font.setPointSizeF(max(info.pointSizeF(), 9.0) + 2)
        painter.setFont(font)
        painter.setPen(QColor(C.FG_DIM))
        rect = self.viewport().rect().adjusted(0, -30, 0, 0)
        painter.drawText(rect, Qt.AlignCenter, self._empty_text)
        painter.end()
