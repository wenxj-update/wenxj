"""表格模型:QAbstractTableModel 子类,供各视图复用。

行 dict 支持的特殊键(均不对应真实列):
- _ok:       bool,False 时整行用失败色(向后兼容旧视图)
- _badges:   {列名: 颜色hex} 该列以彩色徽章绘制(配合 BadgeDelegate)
- _colors:   {列名: 颜色hex} 该列文字颜色
- _tooltips: {列名: 文本}     悬停提示
- _row_bg:   颜色hex          整行底色
- _editable: bool/set         True=全行可编辑,set=指定列名可编辑
"""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, QAbstractTableModel, QModelIndex
from PySide6.QtGui import QBrush, QColor

from .widgets import BADGE_COLOR_ROLE, ROW_ACCENT_ROLE


class GenericTableModel(QAbstractTableModel):
    """通用键值表格模型:行=记录,列=字段。"""

    def __init__(self, columns: list[str], parent=None) -> None:
        super().__init__(parent)
        self._columns = columns
        self._rows: list[dict[str, Any]] = []

    def append_row(self, row: dict[str, Any]) -> None:
        self.beginInsertRows(QModelIndex(), len(self._rows), len(self._rows))
        self._rows.append(row)
        self.endInsertRows()

    def replace_rows(self, rows: list[dict[str, Any]]) -> None:
        self.beginResetModel()
        self._rows = list(rows)
        self.endResetModel()

    def clear(self) -> None:
        self.replace_rows([])

    def remove_row(self, row: int) -> None:
        """删除指定行(带 beginRemoveRows/endRemoveRows 信号)。"""
        if 0 <= row < len(self._rows):
            self.beginRemoveRows(QModelIndex(), row, row)
            self._rows.pop(row)
            self.endRemoveRows()

    def remove_rows(self, rows: list[int]) -> None:
        """删除多行(降序删除避免索引错位)。"""
        for r in sorted(set(rows), reverse=True):
            if 0 <= r < len(self._rows):
                self.beginRemoveRows(QModelIndex(), r, r)
                self._rows.pop(r)
                self.endRemoveRows()

    def rowCount(self, parent=QModelIndex()) -> int:
        return len(self._rows)

    def columnCount(self, parent=QModelIndex()) -> int:
        return len(self._columns)

    def headerData(self, section: int, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return self._columns[section]
        return None

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        col = self._columns[index.column()]
        val = row.get(col, "")

        if role == Qt.DisplayRole or role == Qt.EditRole:
            return str(val)

        if role == Qt.ToolTipRole:
            tips = row.get("_tooltips") or {}
            tip = tips.get(col)
            return str(tip) if tip else None

        if role == BADGE_COLOR_ROLE:
            badges = row.get("_badges") or {}
            return badges.get(col)

        if role == ROW_ACCENT_ROLE:
            return row.get("_accent")

        if role == Qt.BackgroundRole:
            bg = row.get("_row_bg")
            if bg:
                return QBrush(QColor(bg))

        if role == Qt.ForegroundRole:
            colors = row.get("_colors") or {}
            cval = colors.get(col)
            if cval:
                return QBrush(QColor(cval))
            if not row.get("_ok", True):
                return QBrush(QColor(242, 96, 124))
        return None

    def flags(self, index):
        """支持编辑:行有 _editable 标记的列返回 ItemIsEditable。"""
        flags = super().flags(index)
        if not index.isValid():
            return flags
        row = self._rows[index.row()]
        col = self._columns[index.column()]
        editable = row.get("_editable", False)
        if editable is True or (isinstance(editable, set) and col in editable):
            flags |= Qt.ItemIsEditable
        return flags

    def setData(self, index, value, role=Qt.EditRole):
        """编辑单元格:更新行 dict 并发出 dataChanged 信号。

        若用户双击但未修改(值为空字符串),保留原值,避免误清空。
        """
        if role != Qt.EditRole or not index.isValid():
            return False
        row = self._rows[index.row()]
        col = self._columns[index.column()]
        # 空输入视为取消编辑,保留原值
        if value is None or (isinstance(value, str) and value.strip() == ""):
            return False
        row[col] = value
        self.dataChanged.emit(index, index, [role])
        return True
