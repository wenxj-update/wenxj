"""通用报文解析面板:可编辑 Hex + 固定区表 + 记录表(供 0C12/0C15 等复用)。

核心交互:
- Hex 框可手动输入/粘贴(防抖 700ms),解析成功后自动刷新两张表;
  失败时红色提示,不清空已有数据
- 固定区表/记录表编辑 → 反向序列化 → 刷新 Hex,绿色提示
- 记录表支持整行删除(按钮 + 右键菜单),报文同步更新
- get_info() 实时解析当前 Hex 内容,供"计算可见性"取最新页面报文
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QKeySequence, QClipboard
from PySide6.QtWidgets import (QApplication, QWidget, QVBoxLayout,
                                QHBoxLayout, QLabel, QHeaderView, QFrame,
                                QTextEdit, QPushButton, QMenu,
                                QAbstractItemView)

from ..theme import C, FONT_MONO
from ..table_models import GenericTableModel
from ..widgets import SectionTitle, MonoDelegate, DataTableView
from ...models.orbit import STK_EPOCH_2009

_HEX_CHARS = re.compile(r"[0-9A-Fa-f]")

FIXED_COLUMNS = ["序号", "字段名", "字段值", "单位", "备注"]


def fmt_hex(raw: bytes) -> str:
    """原始帧 -> 单行 hex(空格分隔,大写)。"""
    return raw.hex(" ").upper()


def hex_text_to_bytes(text: str) -> bytes:
    """将用户输入的 hex 文本(允许空格/换行/0x 前缀)转为字节。"""
    cleaned = text.replace("0x", "").replace("0X", "")
    hexs = "".join(_HEX_CHARS.findall(cleaned))
    if not hexs:
        raise ValueError("Hex 内容为空")
    if len(hexs) % 2:
        hexs = hexs[:-1]
    return bytes.fromhex(hexs)


class PacketPanel(QWidget):
    """通用报文面板,通过参数注入字段定义与解析/序列化函数。"""

    def __init__(self, *, hex_title: str, record_title: str,
                 count_label: str,
                 fixed_fields: list, fixed_derived: set,
                 record_columns: list, record_editable: set,
                 record_key: str, count_key: str,
                 parse_fn, serialize_fn, default_info_fn,
                 fmt_fixed_value, parse_fixed_edit,
                 fmt_record_row, apply_record_edit,
                 delete_label: str = "删除选中行",
                 parsed_callback=None,
                 epoch_key: str | None = None,
                 parent=None) -> None:
        super().__init__(parent)
        self._parsed_callback = parsed_callback
        self._fixed_fields = fixed_fields          # [(key,label,unit,note)]
        self._fixed_derived = fixed_derived         # 派生字段(禁止编辑)
        self._record_columns = record_columns
        self._record_editable = record_editable
        self._record_key = record_key               # info 中记录列表键
        self._count_key = count_key                 # info 中数量字段键
        self._count_label = count_label             # 元信息中数量标签
        self._parse_fn = parse_fn
        self._serialize_fn = serialize_fn
        self._fmt_fixed_value = fmt_fixed_value     # (key,val)->str
        self._parse_fixed_edit = parse_fixed_edit   # (key,text)->val
        self._fmt_record_row = fmt_record_row       # (idx,rec)->row dict
        self._apply_record_edit = apply_record_edit  # (col,text,rec)->bool
        self._delete_label = delete_label
        self._epoch_key = epoch_key               # 历元时间字段键(底部显示)

        self._info: dict | None = None
        self._updating = False

        self._fixed_model = GenericTableModel(FIXED_COLUMNS)
        self._record_model = GenericTableModel(record_columns)

        # 修改提示自动清除
        self._notif_timer = QTimer(self)
        self._notif_timer.setSingleShot(True)
        self._notif_timer.setInterval(5000)
        self._notif_timer.timeout.connect(lambda: self._lbl_modify.setText(""))

        # Hex 手动输入防抖解析
        self._hex_timer = QTimer(self)
        self._hex_timer.setSingleShot(True)
        self._hex_timer.setInterval(700)
        self._hex_timer.timeout.connect(self._on_hex_edited)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 6, 8, 6)
        outer.setSpacing(4)
        outer.addWidget(self._build_hex_card(hex_title))
        outer.addWidget(self._build_fixed_card(), 2)
        outer.addWidget(self._build_record_card(record_title), 3)
        if epoch_key:
            outer.addWidget(self._build_epoch_card())

        # ---- 底部调试信息行(显示报文未触发原因等调试信息) ----
        self._lbl_debug = QLabel("")
        self._lbl_debug.setWordWrap(True)
        self._lbl_debug.setStyleSheet(
            f"color:{C.WARN}; background:{C.BG_PANEL_2};"
            f" padding:6px 10px; border-radius:4px;"
            f" font-size:11px; font-family:'Consolas','Microsoft YaHei';")
        self._lbl_debug.setVisible(False)
        outer.addWidget(self._lbl_debug)

        self._fixed_model.dataChanged.connect(self._on_table_edited)
        self._record_model.dataChanged.connect(self._on_table_edited)
        self._hex_edit.textChanged.connect(self._on_hex_text_changed)

        # 默认报文
        try:
            self.load_info(default_info_fn())
        except Exception:  # noqa: BLE001
            pass

    # ---------- UI 构建 ----------

    def _build_epoch_card(self) -> QFrame:
        """底部历元时间显示条:大星时 + 年月日时分秒。"""
        card = QFrame()
        card.setObjectName("Card")
        cl = QHBoxLayout(card)
        cl.setContentsMargins(12, 6, 12, 6)
        cl.setSpacing(10)
        lbl = QLabel("★ 历元时间")
        lbl.setStyleSheet(
            f"font-size:13px; font-weight:700; color:{C.ACCENT};")
        cl.addWidget(lbl)
        self._lbl_epoch_sec = QLabel("—")
        self._lbl_epoch_sec.setStyleSheet(
            f"font-size:15px; font-weight:700; color:{C.PKT_TIME};"
            f" font-family:{FONT_MONO};")
        cl.addWidget(self._lbl_epoch_sec)
        self._lbl_epoch_dt = QLabel("")
        self._lbl_epoch_dt.setStyleSheet(
            f"font-size:14px; font-weight:600; color:{C.OK};"
            f" font-family:{FONT_MONO};")
        cl.addWidget(self._lbl_epoch_dt)
        cl.addStretch()
        return card

    def _refresh_epoch(self) -> None:
        """刷新底部历元时间显示。"""
        if not self._epoch_key or not self._info:
            return
        sec = int(self._info.get(self._epoch_key, 0))
        try:
            dt = STK_EPOCH_2009 + timedelta(seconds=sec)
            self._lbl_epoch_sec.setText(f"星时:{sec}")
            self._lbl_epoch_dt.setText(
                f"  {dt.strftime('%Y-%m-%d %H:%M:%S')}")
        except (OverflowError, ValueError):
            self._lbl_epoch_sec.setText(f"星时:{sec}")
            self._lbl_epoch_dt.setText("(时间溢出)")

    def _build_hex_card(self, title: str) -> QFrame:
        card = QFrame()
        card.setObjectName("Card")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(10, 4, 10, 6)
        cl.setSpacing(3)

        lbl = QLabel(title)
        lbl.setStyleSheet(f"font-size:13px; font-weight:700; color:{C.FG};")
        cl.addWidget(lbl)

        meta_row = QHBoxLayout()
        meta_row.setSpacing(8)
        self._lbl_meta = QLabel("长度: — | 数量: — | 包序号: —")
        self._lbl_meta.setStyleSheet(f"color:{C.FG_DIM}; font-size:11px;")
        meta_row.addWidget(self._lbl_meta)
        meta_row.addStretch()
        hint = QLabel("Hex 可手动输入,自动解析")
        hint.setStyleSheet(f"color:{C.FG_DIM}; font-size:10px;")
        meta_row.addWidget(hint)
        self._lbl_modify = QLabel("")
        self._lbl_modify.setStyleSheet(
            f"color:{C.OK}; font-size:11px; font-weight:600;")
        meta_row.addWidget(self._lbl_modify)
        cl.addLayout(meta_row)

        self._hex_edit = QTextEdit()
        self._hex_edit.setReadOnly(False)   # 可手动输入
        self._hex_edit.setStyleSheet(
            f"background:{C.BG_TABLE}; color:{C.PKT_DATA};"
            f"font-family:{FONT_MONO}; font-size:12px;"
            f"border:1px solid {C.BORDER_SOFT}; border-radius:4px;"
            f"padding:4px;")
        self._hex_edit.setPlaceholderText(
            "可粘贴/输入十六进制报文(空格分隔),输入后自动解析…")
        self._hex_edit.setFixedHeight(80)
        self._hex_edit.setLineWrapMode(QTextEdit.WidgetWidth)
        cl.addWidget(self._hex_edit)
        return card

    def _build_fixed_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("Card")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(10, 4, 10, 6)
        cl.setSpacing(3)
        cl.addWidget(SectionTitle("报文解析结果(包头固定区)", accent=C.ACCENT))

        self._fixed_table = DataTableView(empty_text="暂无解析数据")
        self._fixed_table.setModel(self._fixed_model)
        self._fixed_table.setAlternatingRowColors(True)
        self._fixed_table.setSelectionBehavior(QAbstractItemView.SelectItems)
        self._fixed_table.verticalHeader().setVisible(False)
        self._fixed_table.verticalHeader().setDefaultSectionSize(22)
        self._fixed_table.setShowGrid(False)
        th = self._fixed_table.horizontalHeader()
        th.setFixedHeight(24)
        self._fixed_table.setColumnWidth(0, 36)
        self._fixed_table.setColumnWidth(1, 170)
        self._fixed_table.setColumnWidth(2, 240)
        self._fixed_table.setColumnWidth(3, 56)
        self._fixed_table.setColumnWidth(4, 200)
        th.setSectionResizeMode(QHeaderView.Interactive)
        th.setStretchLastSection(True)
        self._fixed_mono = MonoDelegate(self._fixed_table)
        self._fixed_table.setItemDelegateForColumn(2, self._fixed_mono)
        self._fixed_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self._fixed_table.customContextMenuRequested.connect(
            lambda pos: self._show_cell_menu(self._fixed_table, pos))
        cl.addWidget(self._fixed_table)
        return card

    def _build_record_card(self, title: str) -> QFrame:
        card = QFrame()
        card.setObjectName("Card")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(10, 4, 10, 6)
        cl.setSpacing(3)

        hdr = QHBoxLayout()
        hdr.setSpacing(10)
        hdr.addWidget(SectionTitle(title, accent=C.TARGET))
        hdr.addStretch()
        btn_del = QPushButton(self._delete_label)
        btn_del.setObjectName("Danger")
        btn_del.setStyleSheet(
            f"QPushButton#Danger {{ background:{C.ERR_SOFT};"
            f" border:1px solid #8a3346; color:#ff9db0;"
            f" border-radius:4px; padding:3px 10px; font-size:11px; }}"
            f"QPushButton#Danger:hover {{ background:#552433; }}")
        btn_del.clicked.connect(self._delete_selected_records)
        hdr.addWidget(btn_del)
        cl.addLayout(hdr)

        self._record_table = DataTableView(empty_text="暂无记录")
        self._record_table.setModel(self._record_model)
        self._record_table.setAlternatingRowColors(True)
        self._record_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._record_table.verticalHeader().setVisible(False)
        self._record_table.verticalHeader().setDefaultSectionSize(22)
        self._record_table.setShowGrid(False)
        self._record_table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._record_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self._record_table.customContextMenuRequested.connect(
            self._on_record_context_menu)
        hh = self._record_table.horizontalHeader()
        hh.setFixedHeight(24)
        hh.setSectionResizeMode(QHeaderView.Interactive)
        hh.setMinimumSectionSize(60)
        self._record_table.setColumnWidth(0, 40)
        for c in range(1, len(self._record_columns)):
            self._record_table.setColumnWidth(c, 110)
        self._record_mono = MonoDelegate(self._record_table)
        for c in range(1, len(self._record_columns)):
            self._record_table.setItemDelegateForColumn(c, self._record_mono)
        cl.addWidget(self._record_table)
        return card

    # ---------- 数据装载 ----------

    def load_info(self, info: dict) -> None:
        """装载解析结果:刷新 Hex + 元信息 + 两张表。"""
        self._info = info
        try:
            raw = self._serialize_fn(info)
            self._set_hex_text(fmt_hex(raw))
        except Exception:  # noqa: BLE001
            pass
        self._refresh_meta()
        self._populate_fixed()
        self._populate_records()
        self._refresh_epoch()

    def set_hex_bytes(self, raw: bytes) -> None:
        """用原始字节设置 Hex 并触发解析刷新(供会话缓存恢复用)。"""
        if not raw:
            return
        self._hex_timer.stop()
        self._updating = False
        self._set_hex_text(fmt_hex(raw))
        self._updating = False
        self._on_hex_edited()

    def _set_hex_text(self, text: str) -> None:
        self._updating = True
        self._hex_edit.setPlainText(text)
        self._updating = False

    def _refresh_meta(self) -> None:
        info = self._info or {}
        self._lbl_meta.setText(
            f"长度: {int(info.get('cur_packet_len', 0))}B | "
            f"{self._count_label}: {int(info.get(self._count_key, 0))} | "
            f"包序号: {int(info.get('sequence_no', 0))}")

    def _populate_fixed(self) -> None:
        """刷新固定区表。若行数不变则逐格更新,避免列宽被重置。"""
        self._updating = True
        info = self._info or {}
        rows = []
        for i, (key, label, unit, note) in enumerate(self._fixed_fields, 1):
            rows.append({
                "序号": i,
                "字段名": label,
                "字段值": self._fmt_fixed_value(key, info.get(key)),
                "单位": unit,
                "备注": note,
                "_editable": {"字段值"} if key not in self._fixed_derived
                else set(),
                "_colors": {"字段名": C.FG, "字段值": C.PKT_DATA,
                            "单位": C.FG_DIM, "备注": C.FG_DIM},
            })
        # 行数相同时逐格更新,避免 replace_rows 重置列宽
        if len(rows) == self._fixed_model.rowCount():
            for r, row in enumerate(rows):
                old = self._fixed_model._rows[r]
                for col in row:
                    if col.startswith("_"):
                        old[col] = row[col]
                    elif old.get(col) != row[col]:
                        old[col] = row[col]
                        c = FIXED_COLUMNS.index(col) if col in FIXED_COLUMNS else -1
                        if c >= 0:
                            idx = self._fixed_model.index(r, c)
                            self._fixed_model.dataChanged.emit(
                                idx, idx, [Qt.DisplayRole])
        else:
            self._fixed_model.replace_rows(rows)
        self._updating = False
        self._refresh_epoch()

    def _populate_records(self) -> None:
        """刷新记录表。若行数不变则逐格更新,保留列宽。"""
        self._updating = True
        records = (self._info or {}).get(self._record_key) or []
        rows = []
        for i, rec in enumerate(records, 1):
            row = self._fmt_record_row(i, rec)
            row["_editable"] = self._record_editable
            rows.append(row)
        if len(rows) == self._record_model.rowCount():
            for r, row in enumerate(rows):
                old = self._record_model._rows[r]
                for col in row:
                    if col.startswith("_"):
                        old[col] = row[col]
                    elif old.get(col) != row[col]:
                        old[col] = row[col]
                        c = (self._record_columns.index(col)
                             if col in self._record_columns else -1)
                        if c >= 0:
                            idx = self._record_model.index(r, c)
                            self._record_model.dataChanged.emit(
                                idx, idx, [Qt.DisplayRole])
        else:
            self._record_model.replace_rows(rows)
        self._updating = False

    # ---------- Hex 手动输入 → 解析 ----------

    def _on_hex_text_changed(self) -> None:
        if self._updating:
            return
        self._hex_timer.start()

    def _on_hex_edited(self) -> None:
        if self._updating:
            return
        text = self._hex_edit.toPlainText()
        try:
            raw = hex_text_to_bytes(text)
            info = self._parse_fn(raw)
        except Exception as e:  # noqa: BLE001
            self._lbl_modify.setText(f"✗ 报文解析失败:{e}")
            self._lbl_modify.setStyleSheet(
                f"color:{C.ERR}; font-size:11px; font-weight:600;")
            self._notif_timer.start(5000)
            return
        self._info = info
        self._refresh_meta()
        self._populate_fixed()
        self._populate_records()
        self._refresh_epoch()
        if self._parsed_callback:
            try:
                self._parsed_callback(info)
            except Exception:  # noqa: BLE001
                pass
        ts = datetime.now().strftime("%H:%M:%S")
        self._lbl_modify.setText(f"✓ 已从手动输入报文解析 [{ts}]")
        self._lbl_modify.setStyleSheet(
            f"color:{C.OK}; font-size:11px; font-weight:600;")
        self._notif_timer.start(5000)

    # ---------- 表格编辑 → 重建报文 ----------

    def _on_table_edited(self, top_left, bottom_right, roles) -> None:
        if self._updating or self._info is None:
            return
        sender = self.sender()
        if sender is self._fixed_model:
            self._sync_fixed_edit(top_left, bottom_right)
        elif sender is self._record_model:
            self._sync_record_edit(top_left, bottom_right)

    def _sync_fixed_edit(self, top_left, bottom_right) -> None:
        changed = []
        for r in range(top_left.row(), bottom_right.row() + 1):
            if r >= len(self._fixed_fields):
                continue
            key, label, _, _ = self._fixed_fields[r]
            if key in self._fixed_derived:
                continue
            val_str = self._fixed_model._rows[r].get("字段值", "")
            try:
                new_val = self._parse_fixed_edit(key, val_str)
            except (ValueError, TypeError):
                continue
            if self._info.get(key) != new_val:
                self._info[key] = new_val
                changed.append(label)
        if changed:
            self._rebuild_and_notify(f"已修改「{', '.join(changed)}」")

    def _sync_record_edit(self, top_left, bottom_right) -> None:
        records = self._info.get(self._record_key) or []
        changed = False
        for r in range(top_left.row(), min(bottom_right.row() + 1,
                                           len(records))):
            rec = records[r]
            for c in range(top_left.column(), bottom_right.column() + 1):
                if c <= 0 or c >= len(self._record_columns):
                    continue
                col = self._record_columns[c]
                val = self._record_model._rows[r].get(col, "")
                try:
                    if self._apply_record_edit(col, val, rec):
                        changed = True
                except (ValueError, TypeError):
                    pass
        if changed:
            self._rebuild_and_notify("已修改记录参数")

    def _rebuild_and_notify(self, msg: str) -> None:
        try:
            raw = self._serialize_fn(self._info)
        except Exception as e:  # noqa: BLE001
            self._lbl_modify.setText(f"✗ 重建报文失败:{e}")
            self._lbl_modify.setStyleSheet(
                f"color:{C.ERR}; font-size:11px; font-weight:600;")
            self._notif_timer.start(5000)
            return

        self._set_hex_text(fmt_hex(raw))
        # 更新派生字段(数量、长度)
        records = self._info.get(self._record_key) or []
        self._info[self._count_key] = len(records)
        self._info["cur_packet_len"] = len(raw)
        self._refresh_meta()

        self._updating = True
        for i, (key, _, _, _) in enumerate(self._fixed_fields):
            if key in self._fixed_derived:
                row = self._fixed_model._rows[i]
                row["字段值"] = self._fmt_fixed_value(key, self._info.get(key))
                idx = self._fixed_model.index(i, 2)
                self._fixed_model.dataChanged.emit(idx, idx, [Qt.DisplayRole])
        self._updating = False

        ts = datetime.now().strftime("%H:%M:%S")
        self._lbl_modify.setText(f"✓ {msg},报文已刷新 [{ts}]")
        self._lbl_modify.setStyleSheet(
            f"color:{C.OK}; font-size:11px; font-weight:600;")
        self._notif_timer.start(5000)

    # ---------- 记录删除 ----------

    def _delete_selected_records(self) -> None:
        sm = self._record_table.selectionModel()
        if sm is None:
            return
        rows = sorted(set(i.row() for i in sm.selectedRows()), reverse=True)
        if not rows:
            rows = sorted(set(i.row() for i in sm.selectedIndexes()),
                          reverse=True)
        if not rows or self._info is None:
            return
        count = len(rows)
        records = self._info.get(self._record_key) or []
        for r in rows:
            if 0 <= r < len(records):
                records.pop(r)
        self._info[self._record_key] = records
        self._record_model.remove_rows(rows)
        # 重新编号序号
        self._updating = True
        for i, row in enumerate(self._record_model._rows, 1):
            row["序号"] = i
        if self._record_model.rowCount() > 0:
            idx0 = self._record_model.index(0, 0)
            idx1 = self._record_model.index(
                self._record_model.rowCount() - 1, 0)
            self._record_model.dataChanged.emit(idx0, idx1, [Qt.DisplayRole])
        self._updating = False
        self._rebuild_and_notify(f"已删除 {count} 条记录")

    def _on_record_context_menu(self, pos) -> None:
        menu = QMenu(self)
        menu.setStyleSheet(
            f"QMenu {{ background:{C.BG_PANEL_2}; color:{C.FG};"
            f" border:1px solid {C.BORDER}; }}")
        # 复制/粘贴
        act_copy = menu.addAction("复制单元格")
        act_paste = menu.addAction("粘贴到单元格")
        menu.addSeparator()
        act_del = menu.addAction(self._delete_label)
        chosen = menu.exec(self._record_table.viewport().mapToGlobal(pos))
        if chosen == act_copy:
            self._copy_cell(self._record_table)
        elif chosen == act_paste:
            self._paste_cell(self._record_table)
        elif chosen == act_del:
            self._delete_selected_records()

    # ---------- 复制粘贴 ----------

    def _show_cell_menu(self, table, pos) -> None:
        """通用单元格右键菜单:复制/粘贴。"""
        idx = table.indexAt(pos)
        if not idx.isValid():
            return
        menu = QMenu(self)
        menu.setStyleSheet(
            f"QMenu {{ background:{C.BG_PANEL_2}; color:{C.FG};"
            f" border:1px solid {C.BORDER}; }}")
        act_copy = menu.addAction("复制单元格")
        act_paste = menu.addAction("粘贴到单元格")
        chosen = menu.exec(table.viewport().mapToGlobal(pos))
        if chosen == act_copy:
            self._copy_cell(table)
        elif chosen == act_paste:
            self._paste_cell(table)

    def _copy_cell(self, table) -> None:
        """复制当前单元格内容到剪贴板。"""
        sm = table.selectionModel()
        if sm is None:
            return
        idx = sm.currentIndex()
        if not idx.isValid():
            return
        val = idx.data(Qt.DisplayRole)
        if val is not None:
            QApplication.clipboard().setText(str(val))

    def _paste_cell(self, table) -> None:
        """从剪贴板粘贴到当前可编辑单元格(在原值基础上修改)。"""
        sm = table.selectionModel()
        if sm is None:
            return
        idx = sm.currentIndex()
        if not idx.isValid():
            return
        model = table.model()
        if not (model.flags(idx) & Qt.ItemIsEditable):
            return
        text = QApplication.clipboard().text()
        if not text:
            return
        model.setData(idx, text, Qt.EditRole)

    # ---------- 对外接口 ----------

    def get_info(self) -> dict | None:
        """实时解析当前 Hex 内容(失败则返回最近一次成功解析结果)。"""
        try:
            raw = hex_text_to_bytes(self._hex_edit.toPlainText())
            self._info = self._parse_fn(raw)
        except Exception:  # noqa: BLE001
            pass
        return self._info

    def get_raw(self) -> bytes | None:
        """获取当前 Hex 内容的原始报文字节(解析失败返回 None)。"""
        try:
            return hex_text_to_bytes(self._hex_edit.toPlainText())
        except Exception:  # noqa: BLE001
            return None

    def export_data(self) -> tuple[str, list]:
        rows = [{k: v for k, v in r.items() if not k.startswith("_")}
                for r in self._record_model._rows]
        return ("报文解析", rows)

    def clear_data(self) -> None:
        self._info = None
        self._fixed_model.clear()
        self._record_model.clear()
        self._updating = True
        self._hex_edit.setPlainText("")
        self._updating = False
        self._lbl_meta.setText("长度: — | 数量: — | 包序号: —")
        self._lbl_modify.setText("")
        if self._epoch_key:
            self._lbl_epoch_sec.setText("—")
            self._lbl_epoch_dt.setText("")
        self.clear_debug()

    def set_debug_message(self, msg: str) -> None:
        """设置底部调试信息行(msg 为空则隐藏)。"""
        if msg:
            self._lbl_debug.setText(f"[调试] {msg}")
            self._lbl_debug.setVisible(True)
        else:
            self._lbl_debug.setVisible(False)

    def clear_debug(self) -> None:
        """清空底部调试信息行。"""
        self._lbl_debug.setVisible(False)
