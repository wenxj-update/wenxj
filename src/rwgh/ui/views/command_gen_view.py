"""指令生成页:双 Tab(成像指令 + 数传指令),自动生成。

布局:
  QTabWidget
    ├─ 成像指令生成(从0F11自动生成)
    │   ├─ 信息条(生成时间/来源/条数) + [导出][清除]按钮
    │   ├─ 指令序列表(含有效数据域码字 + 是否执行状态)
    │   └─ 分系统统计条
    └─ 数传指令生成(从0F22自动生成)
        ├─ 信息条 + [导出][清除]
        ├─ 指令序列表
        └─ 分系统统计条

双击行 → block_selected 信号 → 主窗口切到指令明细页。
0F11/0F22显示时自动生成对应页指令。
"是否执行"状态:星时走动定时器(100ms)比对当前星时与指令执行时间。
"""
from __future__ import annotations

import struct
from datetime import timedelta, timezone
from collections import Counter

from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                               QHeaderView, QFrame, QPushButton,
                               QFileDialog, QAbstractItemView, QTabWidget)

from ..table_models import GenericTableModel
from ..widgets import BadgeDelegate, MonoDelegate, DataTableView
from ..theme import C
from ...models.command import CommandSequence, Command
from ...models.orbit import STK_EPOCH_2009
from ...planning.star_command_sequence import ImagePlanCommandGenerator

_BEIJING_TZ = timezone(timedelta(hours=8))

# 列定义:新增"有效数据域码字"和"是否执行"
_COLUMNS = ["序号", "指令名称", "码字(HEX)", "分系统",
            "执行时间(北京时间)", "时间间隔(s)", "长度(B)",
            "相对时间(s)", "块类型", "有效数据域码字", "是否执行"]

_SUBSYS_COLORS = {
    "星务分系统": C.ACCENT,
    "相机分系统": C.OK,
    "姿控分系统": C.WARN,
    "姿控接口板": C.PKT_TIME,
    "载综/数传分系统": C.PKT_DATA,
    "其他": C.FG_DIM,
}

_BLOCK_BG = {
    "控制开始标志": C.ACCENT,
    "控制结束标志": C.ACCENT,
    "记录停止码": C.WARN,
    "小固存停止码": C.WARN,
    "成像一键关机": C.WARN,
    "数传一键关机": C.WARN,
    "相机首包(57B)": C.OK,
    "相机中间包": C.OK,
    "相机尾包": C.OK,
    "相机单目标包(57B)": C.OK,
    "相机数据块": C.OK,
}

# EB90 帧头(数据块标识)
_EB90 = b"\xEB\x90"

# EB90 程控数据块帧头偏移:
#   0-1: EB90包标识(2B)
#   2:   数据块类型(1B, 01=程控)
#   3-4: 包长(2B, 全部长度)
#   5:   程控任务号(1B)
#   6-9: 时间(4B, 整秒)
#   10:  主导头(1B, 相机=0x14)
#   11:  副导头(1B, 下位机=0x01)
#   12-13: 数据域长度(2B)
#   14+: 有效数据域
#   末字节: 累加和(1B)
_EB90_HEADER_LEN = 14  # 帧头到有效数据域前的长度

# 相机有效数据域内字段偏移(57B):
#   0:   数据头 0xF0
#   1-4: 任务编号(4B)
#   5-10: 指令1时刻(4B整秒+2B毫秒)
#   11:  指令1代号
#   12-13: 指令1持续时长
#   ...
#   36:  指令分隔符(CC=分隔, EE=结束)
#   37-42: 指令2时刻
#   43:  指令2代号
#   ...
#   56:  指令结束符 0xEE
_CAM_CMD1_CODE = 11      # 指令1代号偏移
_CAM_SEPARATOR = 36      # 分隔符偏移
_CAM_CMD2_CODE = 43      # 指令2代号偏移

# 相机指令代号
_CMD_PREPARE = {0x14, 0x15, 0x16, 0x17}  # 准备成像类
_CMD_EXECUTE = 0x21                       # 执行一次成像
_CMD_EXECUTE_PWR = 0x22                   # 执行成像并断电
_SEP_CC = 0xCC  # 指令分隔符
_SEP_EE = 0xEE  # 指令结束符


def _subsystem(main_header: str) -> str:
    h = (main_header or "").strip()
    if h in ("", "星务"):
        return "星务分系统"
    if h == "相机":
        return "相机分系统"
    if h == "姿控":
        return "姿控分系统"
    if h == "姿控接口板":
        return "姿控接口板"
    if h in ("载综", "数传"):
        return "载综/数传分系统"
    return "其他"


def _get_eb90_payload(codeword: bytes) -> bytes | None:
    """从EB90帧中提取有效数据域(剥离14B帧头和末字节累加和)。

    EB90帧结构:
      EB90(2B) + 类型(1B) + 包长(2B) + 任务号(1B) + 时间(4B)
      + 主导头(1B) + 副导头(1B) + 数据域长度(2B)
      + [有效数据域] + 累加和(1B)
    返回有效数据域字节,非EB90帧返回None。
    """
    if not codeword or len(codeword) < _EB90_HEADER_LEN + 1:
        return None
    if codeword[0:2] != _EB90:
        return None
    data_len = struct.unpack_from(">H", codeword, 12)[0]
    payload = codeword[_EB90_HEADER_LEN:_EB90_HEADER_LEN + data_len]
    return payload if payload else None


def _extract_payload(codeword: bytes) -> str:
    """提取有效数据域hex字符串(剥离EB90帧头+累加和)。

    EB90帧: 返回14B帧头之后、累加和之前的有效数据域。
    其他指令: 返回完整码字hex。
    """
    if not codeword:
        return "—"
    payload = _get_eb90_payload(codeword)
    if payload is not None:
        return payload.hex(" ").upper() if payload else "—"
    return codeword.hex(" ").upper()


def _classify_camera_packet(codeword: bytes, idx_in_group: int = 0,
                            group_size: int = 1) -> str:
    """相机数据包分类:基于有效数据域内的指令代号和分隔符。

    判别规则(按指令1代号+分隔符):
    - 首包: 指令1=准备类(14/15/16/17), 分隔符=CC
    - 中间包: 指令1=21H(执行成像), 分隔符=EE
    - 尾包: 指令1=22H(执行成像并断电), 分隔符=EE
    - 单目标: 指令1=准备类, 分隔符=CC, 指令2=22H
    """
    payload = _get_eb90_payload(codeword)
    if payload is None or len(payload) < _CAM_CMD2_CODE + 1:
        return "相机数据块"
    cmd1 = payload[_CAM_CMD1_CODE]
    sep = payload[_CAM_SEPARATOR]
    cmd2 = payload[_CAM_CMD2_CODE]
    is_prepare = cmd1 in _CMD_PREPARE
    if is_prepare and sep == _SEP_CC:
        if cmd2 == _CMD_EXECUTE_PWR and group_size <= 1:
            return "相机单目标包(57B)"
        return "相机首包(57B)"
    if cmd1 == _CMD_EXECUTE and sep == _SEP_EE:
        if cmd2 == _CMD_EXECUTE_PWR:
            return "相机尾包"
        return "相机中间包"
    if cmd1 == _CMD_EXECUTE_PWR and sep == _SEP_EE:
        return "相机尾包"
    return "相机数据块"


def _validate_codeword(codeword: bytes, block_kind: str) -> tuple[bool, str]:
    """校验码字正确性,返回(是否正确, 说明)。

    EB90帧校验:
    1. 包长字段与实际长度比对
    2. 数据域长度与有效数据域比对
    3. 累加和(sum(帧头+数据域) & 0xFF == 末字节)
    """
    if not codeword:
        return False, "码字为空"
    if len(codeword) >= 4 and codeword[0:2] == _EB90:
        if len(codeword) < _EB90_HEADER_LEN + 1:
            return False, f"EB90帧过短:{len(codeword)}B"
        # 包长(全部长度)在偏移3
        total_len = struct.unpack_from(">H", codeword, 3)[0]
        if len(codeword) != total_len:
            return False, (f"包长不符:字段{total_len},"
                           f"实际{len(codeword)}")
        # 数据域长度在偏移12
        data_len = struct.unpack_from(">H", codeword, 12)[0]
        expected_total = _EB90_HEADER_LEN + data_len + 1
        if len(codeword) != expected_total:
            return False, (f"数据域长度不符:期望{expected_total},"
                           f"实际{len(codeword)}")
        # 累加和校验:sum(从偏移0到倒数第2字节) & 0xFF
        check_bytes = codeword[:-1]
        expected_sum = sum(check_bytes) & 0xFF
        actual_sum = codeword[-1]
        if expected_sum != actual_sum:
            return False, (f"累加和错误:期望0x{expected_sum:02X},"
                           f"实际0x{actual_sum:02X}")
        return True, (f"EB90块 长度{len(codeword)}B "
                      f"数据域{data_len}B 累加和0x{actual_sum:02X}✓")
    # 非EB90指令:基本长度校验
    return True, f"长度{len(codeword)}B"


class _CommandSubPage(QWidget):
    """单个指令子页:信息条 + 表 + 统计条。"""

    def __init__(self, title: str, parent=None) -> None:
        super().__init__(parent)
        self._title = title
        self._model = GenericTableModel(_COLUMNS)
        self._cmds: list[Command] = []
        self._star_sec_provider = None  # 外部注入的星时获取函数
        # 模板解析出的块定义(block_kind -> 字段列表),用于"块类型"徽章着色
        self._block_defs: dict = {}

        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 6, 8, 6)
        lay.setSpacing(6)

        # ---- 信息条 + 按钮 ----
        info = QFrame()
        info.setObjectName("Card")
        info.setFixedHeight(40)
        il = QHBoxLayout(info)
        il.setContentsMargins(12, 6, 12, 6)
        il.setSpacing(10)
        self._lbl_gen = QLabel(f"尚未生成{title}")
        self._lbl_gen.setStyleSheet(f"color:{C.FG_DIM}; font-size:12px;")
        il.addWidget(self._lbl_gen)
        il.addStretch()
        self._btn_export = QPushButton("导出")
        self._btn_export.setStyleSheet(
            f"QPushButton{{background:{C.BG_PANEL_2};color:{C.ACCENT};"
            f"border:1px solid {C.BORDER_SOFT};border-radius:4px;"
            f"padding:3px 12px;font-size:12px;}}")
        self._btn_clear = QPushButton("清除")
        self._btn_clear.setStyleSheet(
            f"QPushButton{{background:{C.ERR_SOFT};color:#ff9db0;"
            f"border:1px solid #8a3346;border-radius:4px;"
            f"padding:3px 12px;font-size:12px;}}")
        il.addWidget(self._btn_export)
        il.addWidget(self._btn_clear)
        lay.addWidget(info)

        # ---- 指令表 ----
        self._table = DataTableView(
            empty_text=f"暂无{title}指令,0F1{'1' if '成像' in title else '2'}显示后自动生成")
        self._table.setModel(self._model)
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.verticalHeader().setVisible(False)
        self._table.setShowGrid(False)
        self._table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        hdr = self._table.horizontalHeader()
        hdr.setMinimumSectionSize(50)
        self._table.setColumnWidth(0, 40)      # 序号
        self._table.setColumnWidth(1, 130)     # 指令名称
        self._table.setColumnWidth(2, 220)     # 码字(HEX)
        self._table.setColumnWidth(3, 100)     # 分系统
        self._table.setColumnWidth(4, 170)     # 执行时间
        self._table.setColumnWidth(5, 80)      # 时间间隔
        self._table.setColumnWidth(6, 60)      # 长度
        self._table.setColumnWidth(7, 80)      # 相对时间
        self._table.setColumnWidth(8, 110)     # 块类型
        self._table.setColumnWidth(9, 200)     # 有效数据域码字
        self._table.setColumnWidth(10, 80)     # 是否执行
        self._badge = BadgeDelegate(self._table)
        self._mono = MonoDelegate(self._table)
        self._table.setItemDelegateForColumn(2, self._mono)
        self._table.setItemDelegateForColumn(3, self._badge)
        self._table.setItemDelegateForColumn(8, self._badge)
        self._table.setItemDelegateForColumn(9, self._mono)
        self._table.setItemDelegateForColumn(10, self._badge)
        lay.addWidget(self._table, 1)

        # ---- 分系统统计条 ----
        grp = QFrame()
        grp.setObjectName("Card")
        grp.setFixedHeight(36)
        gl = QHBoxLayout(grp)
        gl.setContentsMargins(12, 4, 12, 4)
        gl.setSpacing(8)
        t = QLabel("分系统统计")
        t.setStyleSheet(f"color:{C.FG_DIM}; font-weight:600; font-size:11px;")
        gl.addWidget(t)
        self._grp_container = QHBoxLayout()
        self._grp_container.setSpacing(8)
        gl.addLayout(self._grp_container)
        gl.addStretch()
        # 校验状态标签
        self._lbl_validate = QLabel("")
        self._lbl_validate.setStyleSheet(
            f"color:{C.FG_DIM}; font-size:11px;")
        gl.addWidget(self._lbl_validate)
        lay.addWidget(grp)
        self._grp_labels: dict[str, QLabel] = {}

        # ---- 星时定时器(100ms刷新"是否执行"状态) ----
        self._star_timer = QTimer(self)
        self._star_timer.setInterval(100)
        self._star_timer.timeout.connect(self._refresh_exec_status)
        self._star_timer.start()

    def set_star_sec_provider(self, provider) -> None:
        """注入星时获取函数(返回2009历元秒)。"""
        self._star_sec_provider = provider

    def set_block_defs(self, defs: dict | None) -> None:
        """注入模板解析出的块定义,使"块类型"徽章识别模板 sheet 派生的块名。"""
        self._block_defs = dict(defs or {})

    def _block_kind_color(self, kind: str) -> str:
        """块类型徽章色:模板块定义优先,缺失时回退硬编码 _BLOCK_BG。"""
        color = _BLOCK_BG.get(kind)
        if color is None and kind in self._block_defs:
            color = C.OK
        return color or C.FG_DIM

    def load_commands(self, seq: CommandSequence) -> None:
        """装载指令序列到表。"""
        self._cmds = list(seq.commands)
        rows = []
        counter: Counter = Counter()
        prev_time = 0.0

        # 先分组相机指令(用于首包/中间包/尾包分类)
        camera_groups: dict[int, list[int]] = {}
        for i, cmd in enumerate(self._cmds):
            if _subsystem(cmd.main_header) == "相机分系统":
                # 按连续分组
                if (i > 0 and _subsystem(self._cmds[i-1].main_header)
                        == "相机分系统"):
                    # 找到所属组
                    for g_id in sorted(camera_groups.keys(), reverse=True):
                        if i - 1 in camera_groups[g_id]:
                            camera_groups[g_id].append(i)
                            break
                else:
                    g_id = len(camera_groups)
                    camera_groups[g_id] = [i]

        for i, cmd in enumerate(self._cmds, 1):
            sub = _subsystem(cmd.main_header)
            counter[sub] += 1
            abs_sec = float(cmd.abs_time_sec)
            is_sentinel = abs_sec >= 3_000_000_000.0
            if is_sentinel:
                exec_str = "—"
                rel_str = "—"
            else:
                dt = STK_EPOCH_2009 + timedelta(seconds=abs_sec)
                exec_str = (f"{abs_sec:.0f} "
                            f"({dt.strftime('%Y-%m-%d %H:%M:%S')})")
                rel = float(cmd.time_tag)
                rel_str = f"{rel:+.0f}"
            interval = abs_sec - prev_time if i > 1 else 0.0
            prev_time = abs_sec
            cw_hex = cmd.codeword.hex(" ").upper() if cmd.codeword else "—"
            payload_hex = _extract_payload(cmd.codeword)

            # 相机分系统:首包/中间包/尾包分类
            block_kind = cmd.block_kind or "—"
            if sub == "相机分系统" and cmd.codeword:
                for g_id, indices in camera_groups.items():
                    if (i - 1) in indices:
                        idx_in_group = indices.index(i - 1)
                        group_size = len(indices)
                        block_kind = _classify_camera_packet(
                            cmd.codeword, idx_in_group, group_size)
                        break

            # 码字校验
            ok, msg = _validate_codeword(cmd.codeword, block_kind)

            rows.append({
                "序号": i,
                "指令名称": cmd.name or "—",
                "码字(HEX)": cw_hex,
                "分系统": sub,
                "执行时间(北京时间)": exec_str,
                "时间间隔(s)": f"{interval:.1f}",
                "长度(B)": len(cmd.codeword) if cmd.codeword else 0,
                "相对时间(s)": rel_str,
                "块类型": block_kind,
                "有效数据域码字": payload_hex,
                "是否执行": "未执行",
                "_badges": {"分系统": _SUBSYS_COLORS.get(sub, C.FG_DIM),
                            "块类型": self._block_kind_color(block_kind),
                            "是否执行": C.FG_DIM},
                "_colors": {"执行时间(北京时间)": C.OK,
                            "相对时间(s)": C.PKT_TIME,
                            "码字(HEX)": C.PKT_DATA,
                            "时间间隔(s)": C.FG_DIM,
                            "有效数据域码字": C.PKT_DATA},
            })
        self._model.replace_rows(rows)
        gen_time = seq.gen_local_time or "—"
        src = seq.plan_source or "—"
        self._lbl_gen.setText(
            f"生成时间:{gen_time}  ·  来源:{src}  ·  "
            f"指令条数:{len(self._cmds)}")
        self._refresh_group_stats(counter)
        # 立即刷新一次执行状态
        self._refresh_exec_status()

    def _refresh_exec_status(self) -> None:
        """根据当前星时刷新"是否执行"列。"""
        if not self._cmds or not self._star_sec_provider:
            return
        try:
            star_sec = float(self._star_sec_provider())
        except Exception:
            return
        if not hasattr(self._model, '_rows') or not self._model._rows:
            return
        col_idx = _COLUMNS.index("是否执行")
        updated = False
        for i, cmd in enumerate(self._cmds):
            if i >= len(self._model._rows):
                break
            abs_sec = float(cmd.abs_time_sec)
            is_sentinel = abs_sec >= 3_000_000_000.0
            if is_sentinel:
                continue
            row = self._model._rows[i]
            old_val = row.get("是否执行", "未执行")
            if star_sec >= abs_sec:
                new_val = "已执行"
                color = C.OK
            else:
                new_val = "未执行"
                color = C.FG_DIM
            if old_val != new_val:
                row["是否执行"] = new_val
                if "_badges" in row:
                    row["_badges"]["是否执行"] = color
                idx = self._model.index(i, col_idx)
                self._model.dataChanged.emit(idx, idx)
                updated = True
        if updated:
            self._table.viewport().update()

    def _refresh_group_stats(self, counter: Counter) -> None:
        while self._grp_container.count():
            item = self._grp_container.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._grp_labels.clear()
        # 码字校验统计
        n_ok = n_fail = 0
        for cmd in self._cmds:
            if cmd.codeword:
                ok, _ = _validate_codeword(cmd.codeword, cmd.block_kind or "")
                if ok:
                    n_ok += 1
                else:
                    n_fail += 1
        for sub, cnt in counter.items():
            color = _SUBSYS_COLORS.get(sub, C.FG_DIM)
            lbl = QLabel(f"{sub}: {cnt}条")
            lbl.setStyleSheet(
                f"color:{color}; background:{C.BG_PANEL_2};"
                "border-radius:10px; padding:2px 8px; font-weight:600;"
                " font-size:11px;")
            self._grp_container.addWidget(lbl)
            self._grp_labels[sub] = lbl
        # 显示校验结果
        if self._cmds:
            if n_fail:
                self._lbl_validate.setText(
                    f"码字校验: {n_ok}通过 / {n_fail}失败")
                self._lbl_validate.setStyleSheet(
                    f"color:{C.ERR}; font-size:11px; font-weight:600;")
            else:
                self._lbl_validate.setText(
                    f"码字校验: {n_ok}条全部通过 ✓")
                self._lbl_validate.setStyleSheet(
                    f"color:{C.OK}; font-size:11px; font-weight:600;")

    def clear(self) -> None:
        self._cmds.clear()
        self._model.clear()
        self._lbl_gen.setText(f"尚未生成{self._title}")
        self._lbl_validate.setText("")
        while self._grp_container.count():
            item = self._grp_container.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._grp_labels.clear()

    def export(self) -> None:
        rows = []
        for row in self._model._rows:
            clean = {k: v for k, v in row.items() if not k.startswith("_")}
            rows.append(clean)
        if not rows:
            self._lbl_gen.setText("无数据可导出")
            return
        path, ftype = QFileDialog.getSaveFileName(
            self, f"导出{self._title}", self._title,
            "Excel (*.xlsx);;文本 (*.txt);;JSON (*.json)")
        if not path:
            return
        ext = path.rsplit(".", 1)[-1].lower() if "." in path else "txt"
        try:
            if ext == "xlsx":
                import openpyxl
                wb = openpyxl.Workbook()
                ws = wb.active
                ws.title = self._title
                keys = list(rows[0].keys())
                ws.append(keys)
                for r in rows:
                    ws.append([r.get(k, "") for k in keys])
                wb.save(path)
            elif ext == "json":
                import json
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(rows, f, ensure_ascii=False, indent=2)
            else:
                with open(path, "w", encoding="utf-8") as f:
                    keys = list(rows[0].keys())
                    f.write("\t".join(keys) + "\n")
                    for r in rows:
                        f.write("\t".join(str(r.get(k, "")) for k in keys)
                                + "\n")
            self._lbl_gen.setText(f"已导出 {len(rows)} 条到 {path}")
        except Exception as e:
            self._lbl_gen.setText(f"导出失败: {e}")

    def get_selected_cmd(self, row: int) -> Command | None:
        if 0 <= row < len(self._cmds):
            return self._cmds[row]
        return None


class CommandGenView(QWidget):
    """指令生成页:双 Tab(成像+数传),0F11/0F22显示后自动生成。"""

    block_selected = Signal(object)  # Command
    command_generated = Signal(object)  # CommandSequence

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._gen = ImagePlanCommandGenerator()
        self._panel_0f11 = None
        self._panel_0f22 = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(4)

        # ---- 双 Tab ----
        self._tabs = QTabWidget()
        self._tabs.setObjectName("CmdTabs")
        self._page_img = _CommandSubPage("成像指令")
        self._page_dl = _CommandSubPage("数传指令")
        self._tabs.addTab(self._page_img, "成像指令生成")
        self._tabs.addTab(self._page_dl, "数传指令生成")
        lay.addWidget(self._tabs)

        # ---- 按钮事件 ----
        self._page_img._btn_export.clicked.connect(self._page_img.export)
        self._page_img._btn_clear.clicked.connect(self._page_img.clear)
        self._page_dl._btn_export.clicked.connect(self._page_dl.export)
        self._page_dl._btn_clear.clicked.connect(self._page_dl.clear)

        # ---- 双击跳转指令明细 ----
        self._page_img._table.doubleClicked.connect(
            lambda idx: self._on_row_clicked(self._page_img, idx))
        self._page_dl._table.doubleClicked.connect(
            lambda idx: self._on_row_clicked(self._page_dl, idx))

    def set_plan_source(self, panel_0f11, panel_0f22) -> None:
        """注入可见性结果页的 panel 引用(用于取当前报文)。"""
        self._panel_0f11 = panel_0f11
        self._panel_0f22 = panel_0f22

    def set_star_sec_provider(self, provider) -> None:
        """注入星时获取函数(返回2009历元秒float)。"""
        self._page_img.set_star_sec_provider(provider)
        self._page_dl.set_star_sec_provider(provider)

    def set_block_defs(self, defs: dict | None) -> None:
        """注入模板解析出的块定义(转发到两个子页,用于"块类型"徽章着色)。"""
        self._page_img.set_block_defs(defs)
        self._page_dl.set_block_defs(defs)

    def auto_generate(self, ptype: int) -> None:
        """0F11/0F22显示后自动生成对应指令。

        ptype: 0x0F11=成像指令, 0x0F22=数传指令
        """
        if ptype == 0x0F11:
            panel = self._panel_0f11
            page = self._page_img
            src_label = "0F11"
        elif ptype == 0x0F22:
            panel = self._panel_0f22
            page = self._page_dl
            src_label = "0F22"
        else:
            return
        if not panel:
            return
        info = panel.get_info() if hasattr(panel, 'get_info') else None
        if not info:
            return
        try:
            seq = self._gen.generate_from_plan(info, ptype)
            page.load_commands(seq)
            # 切换到对应Tab
            idx = 0 if ptype == 0x0F11 else 1
            self._tabs.setCurrentIndex(idx)
            # 通知外部(主窗口缓存指令序列)
            self.command_generated.emit(seq)
        except Exception:
            pass

    def _on_row_clicked(self, page: _CommandSubPage, idx) -> None:
        row = idx.row()
        cmd = page.get_selected_cmd(row)
        if cmd is not None:
            self.block_selected.emit(cmd)

    # ---- 兼容旧接口 ----

    def on_command_sequence(self, seq: CommandSequence) -> None:
        """兼容旧接口:接收指令序列,按来源分发到对应子页。"""
        src = (seq.plan_source or "").upper()
        if "0F22" in src or "数传" in src:
            self._page_dl.load_commands(seq)
            self._tabs.setCurrentIndex(1)
        else:
            self._page_img.load_commands(seq)
            self._tabs.setCurrentIndex(0)
        self.command_generated.emit(seq)

    def export_data(self) -> tuple[str, list]:
        page = self._tabs.currentWidget()
        rows = []
        for row in page._model._rows:
            clean = {k: v for k, v in row.items() if not k.startswith("_")}
            rows.append(clean)
        return (page._title, rows)

    def clear_data(self) -> None:
        self._page_img.clear()
        self._page_dl.clear()
