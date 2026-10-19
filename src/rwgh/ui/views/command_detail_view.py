"""指令明细页:仅显示块详情(双击指令生成页行查看)。

从指令生成页双击行 → 主窗口切换到本页 → show_block_detail(cmd)
展示该指令块的逐字段反解和备注(HTML 高亮格式)。

码字解析: cmd.codeword 为完整发送帧(EB90+类型+包长+程控号+时标+主导头+副导头+域长+数据域+累加和×2),
本页剥离 EB90 头与程控帧头,只解析**有效数据域**(field),偏移从 0 起算。
"""
from __future__ import annotations

from datetime import timedelta

from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFrame,
                               QTextEdit, QLabel, QPushButton, QFileDialog,
                               QMessageBox)

from ..theme import C, FONT_MONO
from ...models.command import Command
from ...models.orbit import STK_EPOCH_2009
from ...planning.command_block_spec import (
    BLOCK_FIELDS, BLOCK_REMARK, MASTER_HDR_MAP, SUB_HDR_MAP,
)
from ...planning.star_command_builder import (
    extract_data_field, extract_inner_header,
)


class CommandDetailView(QWidget):
    """指令明细页:仅块详情区。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._current_cmd: Command | None = None
        # 模板解析出的块定义(block_kind -> [(偏移,长度,字段名,说明),...]),
        # 为空时回退到 command_block_spec.BLOCK_FIELDS 硬编码默认值
        self._block_defs: dict = {}

        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(10)

        # ---- 顶部按钮栏 ----
        btn_bar = QHBoxLayout()
        btn_bar.setContentsMargins(0, 0, 0, 0)
        btn_bar.setSpacing(8)
        btn_bar.addStretch()
        self.btn_export = QPushButton("导出到Excel")
        self.btn_export.setMinimumWidth(110)
        self.btn_export.setMaximumHeight(28)
        self.btn_export.setStyleSheet(
            f"QPushButton {{ background:{C.ACCENT_SOFT}; color:{C.ACCENT};"
            f" border:1px solid {C.ACCENT_DEEP}; border-radius:4px;"
            " padding:3px 12px; font-size:12px; font-weight:600; }"
            "QPushButton:hover { background:#1f2f5a; }"
            "QPushButton:disabled { color:#555; border-color:#333; }")
        self.btn_export.setEnabled(False)
        self.btn_export.clicked.connect(self._export_excel)
        btn_bar.addWidget(self.btn_export)
        lay.addLayout(btn_bar)

        # ---- 块详情区 ----
        detail_card = QFrame()
        detail_card.setObjectName("Card")
        dl = QVBoxLayout(detail_card)
        dl.setContentsMargins(12, 8, 12, 8)
        dl.setSpacing(6)
        self._lbl_detail_title = QLabel("块详情(双击指令生成页行查看)")
        self._lbl_detail_title.setStyleSheet(
            f"color:{C.FG_DIM}; font-size:13px; font-weight:600;")
        dl.addWidget(self._lbl_detail_title)
        self._detail_view = QTextEdit()
        self._detail_view.setReadOnly(True)
        self._detail_view.setStyleSheet(
            f"background:{C.BG_TABLE}; color:{C.FG};"
            f"font-family:{FONT_MONO}; font-size:12px;"
            f"border:1px solid {C.BORDER_SOFT}; border-radius:6px;")
        dl.addWidget(self._detail_view)
        lay.addWidget(detail_card, 1)

    # ---------- 数据接入 ----------

    def set_block_defs(self, defs: dict | None) -> None:
        """注入模板解析出的块定义 {block_kind: [(偏移,长度,字段名,说明)]}。

        为空/缺失时,块详情回退到 command_block_spec.BLOCK_FIELDS 硬编码默认值。
        """
        self._block_defs = dict(defs or {})

    def _fields_for(self, kind: str):
        """优先取模板解析出的块定义,缺失时回退硬编码默认值。"""
        return self._block_defs.get(kind) or BLOCK_FIELDS.get(kind, [])

    def on_command_sequence(self, seq) -> None:
        """兼容 bridge 信号:仅清空块详情等待用户双击。"""
        self._detail_view.clear()
        self._lbl_detail_title.setText("块详情(双击指令生成页行查看)")
        self._current_cmd = None
        self.btn_export.setEnabled(False)

    def show_block_detail(self, cmd: Command) -> None:
        """显示单个指令块的逐字段反解和备注(HTML高亮格式)。

        解析层次:
        1. 外层发送帧: EB90(2) + 类型(1) + 包长(2) + 程控帧(n) + 外累加和(1)
        2. 程控帧: 程控号(1) + 时标(4) + 主导头(1) + 副导头(1) + 域长(2) +
                   数据域(n) + 内累加和(1)
        3. 有效数据域: 数据域部分(剥离 EB90 头 + 程控帧头),BLOCK_FIELDS 偏移从此起算
        """
        kind = cmd.block_kind or "未知"
        cw = cmd.codeword or b""
        cw_hex = cw.hex(" ").upper() if cw else "—"
        # 提取有效数据域(剥离 EB90 头+程控帧头)
        field_data = extract_data_field(cw)
        field_hex = field_data.hex(" ").upper() if field_data else "—"
        # 解析外层+程控帧头
        hdr = extract_inner_header(cw)
        # 缓存当前指令供导出使用
        self._current_cmd = cmd
        self.btn_export.setEnabled(True)
        abs_sec = float(cmd.abs_time_sec)
        is_sentinel = abs_sec >= 3_000_000_000.0  # 哨兵值,非真实秒数
        if is_sentinel:
            utc_str = "—"
            beijing_str = "—"
            rel_str = "—"
        else:
            dt = STK_EPOCH_2009 + timedelta(seconds=abs_sec)
            utc_str = f"{abs_sec:.0f} ({dt.strftime('%Y-%m-%d %H:%M:%S')})"
            beijing_str = dt.strftime('%Y-%m-%d %H:%M:%S')
            rel = float(cmd.time_tag)
            rel_str = f"{rel:+.0f}s"
        remark = BLOCK_REMARK.get(kind, "—")
        fields = self._fields_for(kind)

        # 主导头/副导头释义
        master_byte = hdr.get("master", 0) if hdr else 0
        sub_byte = hdr.get("sub", 0) if hdr else 0
        master_disp = (MASTER_HDR_MAP.get(master_byte, cmd.main_header)
                       if hdr else cmd.main_header) or "—"
        sub_disp = (SUB_HDR_MAP.get(sub_byte, cmd.sub_header)
                    if hdr else cmd.sub_header) or "—"
        taskno = hdr.get("taskno", "—") if hdr else "—"
        field_len = hdr.get("field_len", "—") if hdr else "—"

        # 构建 HTML 格式的块详情
        lines = []
        lines.append("<table cellspacing='6' cellpadding='4' "
                     "style='color:#c8d3f5; font-family:Consolas,"
                     "\"Cascadia Mono\",monospace; font-size:12px; "
                     "width:100%;'>")
        # 标题行
        lines.append(
            f"<tr><td colspan='4' style='background:#1a2a5e; "
            f"font-size:14px; font-weight:bold; color:#5b9eff; "
            f"padding:8px;'>■ {kind} (数据域 {len(field_data)}B / "
            f"完整帧 {len(cw)}B)</td></tr>")
        # 基本信息区
        info_rows = [
            ("指令名称", cmd.name or "—", "主导头",
             f"0x{master_byte:02X} {master_disp}"),
            ("副导头", f"0x{sub_byte:02X} {sub_disp}",
             "程控号", str(taskno)),
            ("时标(UTC)", utc_str, "北京时间", beijing_str),
            ("相对时间", rel_str, "数据域长度", f"{field_len}B"),
        ]
        for label1, val1, label2, val2 in info_rows:
            lines.append(
                f"<tr>"
                f"<td style='color:#7a8aa8; font-weight:bold;'>{label1}</td>"
                f"<td style='color:#5dbb6f;'>{val1}</td>"
                f"<td style='color:#7a8aa8; font-weight:bold;'>{label2}</td>"
                f"<td style='color:#5dbb6f;'>{val2}</td>"
                f"</tr>")
        lines.append("</table>")

        # 完整码字区(高亮,显示完整发送帧)
        lines.append(
            f"<div style='margin:8px 0; padding:6px; "
            f"background:#0d1f3c; border:1px solid #2a3f6e; "
            f"border-radius:4px;'><span style='color:#7a8aa8; "
            f"font-weight:bold;'>完整发送帧({len(cw)}B):</span> "
            f"<span style='color:#ff9d4d; font-family:monospace;'>"
            f"{cw_hex}</span></div>")

        # 有效数据域区(剥离 EB90 头+程控帧头)
        if field_data:
            lines.append(
                f"<div style='margin:8px 0; padding:6px; "
                f"background:#101a30; border:1px solid #2a3f6e; "
                f"border-radius:4px;'><span style='color:#7a8aa8; "
                f"font-weight:bold;'>有效数据域({len(field_data)}B, "
                f"剥离EB90头+程控帧头):</span> "
                f"<span style='color:#5dbb6f; font-family:monospace;'>"
                f"{field_hex}</span></div>")

        # 备注
        lines.append(
            f"<div style='margin:6px 0; padding:6px; "
            f"background:#1a1a2e; border-left:3px solid #5b9eff; "
            f"color:#a8b2c8;'><b>备注:</b> {remark}</div>")

        # 逐字段解析表(偏移基于有效数据域)
        lines.append("<table cellspacing='2' cellpadding='3' "
                     "style='color:#c8d3f5; font-family:Consolas,"
                     "\"Cascadia Mono\",monospace; font-size:11px; "
                     "width:100%;'>")
        lines.append(
            "<tr style='background:#1a2a5e; font-weight:bold;'>"
            "<td style='padding:4px 8px;'>偏移</td>"
            "<td style='padding:4px 8px;'>长度</td>"
            "<td style='padding:4px 8px;'>字段名</td>"
            "<td style='padding:4px 8px;'>原始值(HEX)</td>"
            "<td style='padding:4px 8px;'>说明</td></tr>")
        if fields:
            for i, (off, length, fname, fdesc) in enumerate(fields):
                raw = field_data[off:off + length] if field_data else b""
                raw_hex = raw.hex(" ").upper() if raw else "—"
                bg = "#0d1526" if i % 2 == 0 else "#101a30"
                lines.append(
                    f"<tr style='background:{bg};'>"
                    f"<td style='padding:3px 8px; color:#7a8aa8;'>{off}</td>"
                    f"<td style='padding:3px 8px; color:#7a8aa8;'>{length}B</td>"
                    f"<td style='padding:3px 8px; color:#5dbb6f; "
                    f"font-weight:bold;'>{fname}</td>"
                    f"<td style='padding:3px 8px; color:#ff9d4d; "
                    f"font-family:monospace;'>{raw_hex}</td>"
                    f"<td style='padding:3px 8px; color:#a8b2c8;'>{fdesc}</td>"
                    f"</tr>")
        else:
            lines.append(
                "<tr><td colspan='5' style='padding:8px; "
                "color:#7a8aa8;'>(无字段定义)</td></tr>")
        lines.append("</table>")

        self._detail_view.setHtml("".join(lines))
        self._lbl_detail_title.setText(
            f"■ 块详情: {kind} (数据域 {len(field_data)}B)")

    def export_data(self) -> tuple[str, list]:
        return ("指令明细", [])

    def clear_data(self) -> None:
        self._detail_view.clear()
        self._lbl_detail_title.setText("块详情(双击指令生成页行查看)")
        self._current_cmd = None
        self.btn_export.setEnabled(False)

    # ---------- 导出 Excel ----------

    def _export_excel(self) -> None:
        """将当前块详情导出到 Excel,带格式(列宽/表头着色/合并标题)。"""
        cmd = self._current_cmd
        if cmd is None:
            QMessageBox.information(self, "提示", "请先双击指令生成页行查看块详情")
            return
        try:
            import openpyxl
            from openpyxl.styles import (Font, Alignment, PatternFill,
                                         Border, Side)
        except ImportError:
            QMessageBox.warning(self, "导出失败",
                                 "未安装 openpyxl,无法导出 Excel")
            return

        # 计算输出文件名
        default_name = f"指令明细_{cmd.block_kind or 'block'}.xlsx"
        path, _ = QFileDialog.getSaveFileName(
            self, "导出指令明细到 Excel", default_name,
            "Excel 文件 (*.xlsx)")
        if not path:
            return
        if not path.lower().endswith(".xlsx"):
            path += ".xlsx"

        # 复用 show_block_detail 的解析逻辑,构造导出数据
        kind = cmd.block_kind or "未知"
        cw = cmd.codeword or b""
        cw_hex = cw.hex(" ").upper() if cw else "—"
        field_data = extract_data_field(cw)
        field_hex = field_data.hex(" ").upper() if field_data else "—"
        hdr = extract_inner_header(cw)
        abs_sec = float(cmd.abs_time_sec)
        is_sentinel = abs_sec >= 3_000_000_000.0
        if is_sentinel:
            utc_str = "—"
            beijing_str = "—"
            rel_str = "—"
        else:
            dt = STK_EPOCH_2009 + timedelta(seconds=abs_sec)
            utc_str = f"{abs_sec:.0f} ({dt.strftime('%Y-%m-%d %H:%M:%S')})"
            beijing_str = dt.strftime('%Y-%m-%d %H:%M:%S')
            rel_str = f"{float(cmd.time_tag):+.0f}s"
        remark = BLOCK_REMARK.get(kind, "—")
        fields = self._fields_for(kind)
        master_byte = hdr.get("master", 0) if hdr else 0
        sub_byte = hdr.get("sub", 0) if hdr else 0
        master_disp = (MASTER_HDR_MAP.get(master_byte, cmd.main_header)
                       if hdr else cmd.main_header) or "—"
        sub_disp = (SUB_HDR_MAP.get(sub_byte, cmd.sub_header)
                    if hdr else cmd.sub_header) or "—"
        taskno = hdr.get("taskno", "—") if hdr else "—"
        field_len = hdr.get("field_len", "—") if hdr else "—"

        try:
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "指令明细"

            # 样式预定义
            thin = Side(border_style="thin", color="888888")
            border = Border(left=thin, right=thin, top=thin, bottom=thin)
            title_font = Font(name="微软雅黑", size=14, bold=True,
                              color="FFFFFF")
            title_fill = PatternFill("solid", fgColor="1A2A5E")
            hdr_font = Font(name="微软雅黑", size=11, bold=True,
                            color="FFFFFF")
            hdr_fill = PatternFill("solid", fgColor="2A3F6E")
            label_font = Font(name="微软雅黑", size=11, bold=True,
                             color="3A4A6A")
            val_font = Font(name="Consolas", size=11, color="1F6B3F")
            mono_font = Font(name="Consolas", size=11, color="CC6600")
            remark_font = Font(name="微软雅黑", size=10, color="555555",
                               italic=True)
            wrap = Alignment(horizontal="left", vertical="center",
                             wrap_text=True)
            center = Alignment(horizontal="center", vertical="center",
                              wrap_text=True)

            # 列宽(5 列:A 偏移 B 长度 C 字段名 D HEX E 说明)
            ws.column_dimensions["A"].width = 8
            ws.column_dimensions["B"].width = 10
            ws.column_dimensions["C"].width = 24
            ws.column_dimensions["D"].width = 60
            ws.column_dimensions["E"].width = 40

            # 第 1 行:标题(合并 A1:E1)
            ws.merge_cells("A1:E1")
            c = ws.cell(row=1, column=1,
                        value=f"指令明细 · {kind} "
                             f"(数据域 {len(field_data)}B / 完整帧 {len(cw)}B)")
            c.font = title_font
            c.fill = title_fill
            c.alignment = center
            ws.row_dimensions[1].height = 28

            # 第 2 行:空行
            ws.row_dimensions[2].height = 6

            # 第 3 行:基本信息(标签:值 标签:值)
            info_pairs = [
                ("指令块类型", kind, "指令名称", cmd.name or "—"),
                ("主导头", f"0x{master_byte:02X} {master_disp}",
                 "副导头", f"0x{sub_byte:02X} {sub_disp}"),
                ("程控号", str(taskno), "数据域长度", f"{field_len}B"),
                ("时标(UTC)", utc_str, "北京时间", beijing_str),
                ("相对时间", rel_str, "绝对秒", f"{abs_sec:.0f}"),
            ]
            r = 3
            for label1, val1, label2, val2 in info_pairs:
                ws.cell(row=r, column=1, value=label1).font = label_font
                ws.cell(row=r, column=1).alignment = wrap
                ws.cell(row=r, column=2, value=val1).font = val_font
                ws.cell(row=r, column=2).alignment = wrap
                ws.merge_cells(start_row=r, start_column=2,
                               end_row=r, end_column=2)
                ws.cell(row=r, column=3, value=label2).font = label_font
                ws.cell(row=r, column=3).alignment = wrap
                ws.cell(row=r, column=4, value=val2).font = val_font
                ws.cell(row=r, column=4).alignment = wrap
                ws.merge_cells(start_row=r, start_column=4,
                               end_row=r, end_column=5)
                r += 1

            # 完整码字行
            ws.cell(row=r, column=1,
                    value=f"完整码字({len(cw)}B)").font = label_font
            ws.cell(row=r, column=1).alignment = wrap
            ws.cell(row=r, column=2, value=cw_hex).font = mono_font
            ws.cell(row=r, column=2).alignment = wrap
            ws.merge_cells(start_row=r, start_column=2,
                           end_row=r, end_column=5)
            ws.row_dimensions[r].height = 22
            r += 1

            # 有效数据域行
            ws.cell(row=r, column=1,
                    value=f"有效数据域({len(field_data)}B)").font = label_font
            ws.cell(row=r, column=1).alignment = wrap
            ws.cell(row=r, column=2, value=field_hex).font = val_font
            ws.cell(row=r, column=2).alignment = wrap
            ws.merge_cells(start_row=r, start_column=2,
                           end_row=r, end_column=5)
            ws.row_dimensions[r].height = 22
            r += 1

            # 空行
            ws.row_dimensions[r].height = 6
            r += 1

            # 字段表头
            headers = ["偏移", "长度", "字段名", "原始值(HEX)", "说明"]
            for i, h in enumerate(headers, 1):
                c = ws.cell(row=r, column=i, value=h)
                c.font = hdr_font
                c.fill = hdr_fill
                c.alignment = center
                c.border = border
            ws.row_dimensions[r].height = 22
            r += 1

            # 字段明细
            if fields:
                for i, (off, length, fname, fdesc) in enumerate(fields):
                    raw = field_data[off:off + length] if field_data else b""
                    raw_hex = raw.hex(" ").upper() if raw else "—"
                    fill_color = "F2F5FA" if i % 2 == 0 else "FFFFFF"
                    row_fill = PatternFill("solid", fgColor=fill_color)
                    cells = [
                        (1, off, label_font),
                        (2, f"{length}B", label_font),
                        (3, fname, val_font),
                        (4, raw_hex, mono_font),
                        (5, fdesc, remark_font),
                    ]
                    for col, val, fnt in cells:
                        c = ws.cell(row=r, column=col, value=val)
                        c.font = fnt
                        c.alignment = wrap
                        c.fill = row_fill
                        c.border = border
                    ws.row_dimensions[r].height = 20
                    r += 1
            else:
                ws.merge_cells(start_row=r, start_column=1,
                               end_row=r, end_column=5)
                c = ws.cell(row=r, column=1, value="(无字段定义)")
                c.font = remark_font
                c.alignment = center
                r += 1

            # 空行
            ws.row_dimensions[r].height = 6
            r += 1

            # 备注行
            ws.cell(row=r, column=1, value="备注").font = label_font
            ws.cell(row=r, column=1).alignment = wrap
            ws.cell(row=r, column=2, value=remark).font = remark_font
            ws.cell(row=r, column=2).alignment = wrap
            ws.merge_cells(start_row=r, start_column=2,
                           end_row=r, end_column=5)
            ws.row_dimensions[r].height = 40

            wb.save(path)
            QMessageBox.information(self, "导出成功",
                                    f"指令明细已导出到:\n{path}")
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "导出失败", f"导出 Excel 失败:\n{e}")
