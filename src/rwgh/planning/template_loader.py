"""从指令模板 xlsm 加载真实 CommandTemplate。

xlsm 结构(两类 sheet):
1. 任务序列模板:首列 "时间标定" 或 "星时",每行一条指令(Ts-310/0xEB90146F...)。
   列: 时间标定 | 参数名 | 说明 | 字节长度 | 指令码字 | 副导头 | 主导头
2. 数据块定义:首列 "参数名"/"参数名称"/"序号",含「十六进制码」列,
   定义各数据块内部字段。由 load_block_defs_from_xlsm() 解析为
   {sheet名: [(偏移, 长度, 字段名, 说明), ...]},供指令明细页/指令生成页展示。

时间表达式解析:
- "T0=Ts-360"   → 参考定义(T0 即 Ts-360),跳过(不作为独立指令行)
- "Ts-310"      → -310.0 (相对 Ts)
- "Ts-5"        → -5.0
- "Te+1"        → +1.0 (相对 Te,回放停止等)
- "0xEB90146F"  → 同步码字(控制开始),时间取上一行 T0 偏移
- 纯数字/"T0"   → 0.0 (Ts 时刻)

码字解析:
- 指令码字列值如 "00"/"01B102AA"/"018004AA" → bytes.fromhex
- "/" 或空 → 无直接码字(数据块引用,比对时按 name+sub_header 匹配)
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Optional

from ..models.command import Command, CommandTemplate

_log = logging.getLogger("rwgh.planning.template_loader")

# 任务序列 sheet 的首列标识(用于自动识别)
_SEQ_HEADER_MARKERS = ("时间标定", "星时")

# 时间表达式正则
_RE_TS_OFFSET = re.compile(r"^Ts([+-]\d+(?:\.\d+)?)$")
_RE_TE_OFFSET = re.compile(r"^Te([+-]\d+(?:\.\d+)?)$")
_RE_T0_DEF = re.compile(r"^T0\s*=\s*Ts([+-]\d+(?:\.\d+)?)$")
_RE_HEX = re.compile(r"^0[xX]([0-9A-Fa-f]+)$")
_RE_T0_REF = re.compile(r"^T0([+-]\d+(?:\.\d+)?)?$")


def _parse_time_tag(raw: str, t0_offset: float) -> tuple[Optional[float], Optional[str]]:
    """解析时间标定列,返回 (time_tag, sync_codeword)。

    sync_codeword 非 None 表示该行是同步码字行(如 0xEB90146F 控制开始)。
    """
    s = raw.strip()
    if not s or s == "/":
        return None, None

    # T0=Ts-360 参考定义
    m = _RE_T0_DEF.match(s)
    if m:
        return None, None  # 定义行,不产出指令

    # 同步码字(0xEB90146F)
    m = _RE_HEX.match(s)
    if m:
        return t0_offset, bytes.fromhex(m.group(1))

    # Ts-310
    m = _RE_TS_OFFSET.match(s)
    if m:
        return float(m.group(1)), None

    # Te+1
    m = _RE_TE_OFFSET.match(s)
    if m:
        return float(m.group(1)), None

    # T0 或 T0+xx
    m = _RE_T0_REF.match(s)
    if m:
        off = float(m.group(1)) if m.group(1) else 0.0
        return t0_offset + off, None

    # Ts(无偏移)
    if s == "Ts":
        return 0.0, None

    # 纯数字(秒)
    try:
        return float(s), None
    except ValueError:
        pass

    _log.debug("unparsed time tag: %s", s)
    return None, None


def _parse_codeword(raw) -> bytes:
    """解析指令码字列: hex 字符串 -> bytes; "/" 或空 -> b""。"""
    if raw is None:
        return b""
    s = str(raw).strip()
    if not s or s == "/":
        return b""
    # 去空格(如 "11 73 00 00")
    s_compact = s.replace(" ", "")
    try:
        return bytes.fromhex(s_compact)
    except ValueError:
        _log.debug("unparsed codeword: %s", s)
        return b""


def _cell_str(ws, row: int, col: int) -> str:
    v = ws.cell(row=row, column=col).value
    return str(v).strip() if v is not None else ""


def _is_seq_sheet(ws) -> bool:
    """判断是否为任务序列 sheet(首行首列含 时间标定/星时)。"""
    h = _cell_str(ws, 1, 1)
    return any(h.startswith(m) for m in _SEQ_HEADER_MARKERS)


def _parse_seq_sheet(ws, sheet_name: str) -> Optional[CommandTemplate]:
    """解析单个任务序列 sheet -> CommandTemplate。"""
    # 找列索引(首行表头)
    headers = {}
    for c in range(1, min(ws.max_column, 12) + 1):
        h = _cell_str(ws, 1, c)
        if h:
            headers[h] = c

    col_time = headers.get("时间标定") or headers.get("星时")
    col_name = headers.get("参数名")
    col_byte_len = headers.get("字节长度")
    col_code = headers.get("指令码字")
    col_sub = headers.get("副导头")
    col_main = headers.get("主导头")
    if col_time is None or col_name is None:
        return None

    # 第一条数据行通常是 T0 定义,提取 T0 偏移
    t0_offset = -360.0  # 默认 T0=Ts-360
    for r in range(2, min(ws.max_row, 5) + 1):
        raw_time = _cell_str(ws, r, col_time)
        m = _RE_T0_DEF.match(raw_time)
        if m:
            t0_offset = float(m.group(1))
            break

    commands: list[Command] = []
    for r in range(2, ws.max_row + 1):
        raw_time = _cell_str(ws, r, col_time)
        if not raw_time:
            continue
        time_tag, sync_cw = _parse_time_tag(raw_time, t0_offset)
        if time_tag is None and sync_cw is None:
            continue  # 定义行或无法解析,跳过

        name = _cell_str(ws, r, col_name)
        if not name:
            continue

        # 码字:同步码字优先,否则取指令码字列
        if sync_cw is not None:
            codeword = sync_cw
        else:
            cw_raw = ws.cell(row=r, column=col_code).value if col_code else None
            codeword = _parse_codeword(cw_raw)

        sub_header = _cell_str(ws, r, col_sub) if col_sub else ""
        main_header = _cell_str(ws, r, col_main) if col_main else ""

        # 字节长度(参考用,不参与比对)
        # byte_len = _cell_str(ws, r, col_byte_len) if col_byte_len else ""

        cmd = Command(
            time_tag=time_tag if time_tag is not None else t0_offset,
            codeword=codeword,
            name=name,
            sub_header=sub_header,
            main_header=main_header,
        )
        commands.append(cmd)

    if not commands:
        return None

    _log.info("loaded template '%s': %d commands", sheet_name, len(commands))
    return CommandTemplate(
        name=sheet_name,
        expected=tuple(commands),
        time_tolerance=0.5,
        code_exact=True,
    )


def load_templates_from_xlsm(path: str) -> dict[str, CommandTemplate]:
    """从 xlsm 加载所有任务序列模板。

    返回 {template_name: CommandTemplate}。
    仅解析任务序列 sheet(首列 时间标定/星时),数据块定义 sheet 跳过。
    """
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"command template not found: {p}")

    try:
        import openpyxl
    except ImportError as e:
        raise ImportError("openpyxl required: pip install openpyxl") from e

    wb = openpyxl.load_workbook(p, data_only=True, keep_vba=False)
    templates: dict[str, CommandTemplate] = {}
    for name in wb.sheetnames:
        ws = wb[name]
        if not _is_seq_sheet(ws):
            continue
        tmpl = _parse_seq_sheet(ws, name)
        if tmpl is not None:
            templates[name] = tmpl

    _log.info("loaded %d templates from %s", len(templates), p.name)
    return templates


# ==================== 数据块定义 sheet 解析 ====================

# 数据块定义 sheet 的列关键字(不同 sheet 表头略有差异)
_BLK_NAME_KEYS = ("参数名", "参数名称", "字段")
_BLK_LEN_KEYS = ("字节长度", "字节数")
_BLK_HEX_KEY = "十六进制码"
_BLK_DESC_KEYS = ("说明", "数据说明", "备注")

_RE_HEXCELL = re.compile(r"^[0-9A-Fa-f]+$")

# block_kind(指令块的类型名) -> 数据块定义 sheet 名
# 仅列出可与 command_block_spec.BLOCK_FIELDS 对应上的块
BLOCK_KIND_TO_SHEET: dict[str, str] = {
    # 单单元/单帧类数据块:模板 sheet 逐字段定义与指令块一一对应
    "记录任务包": "记录任务包",
    "姿控单元40B": "姿控242字节数据块",
    "AI任务块128B": "AI任务指令数据块",
    "相机数据块57B": "相机57字节数据块_可见单目标",
    "对地回放任务包": "对地回放任务包",
    "压缩参数": "压缩参数设置",
    "固存记录": "固存记录_记录停止",
    "固存回放指令80B": "固存回放指令_回放停止",
    "广播分发任务包": "广播分发任务包",
    "星间分发任务包": "星间W分发任务包",
}
# 说明:复合块(姿控数据块242B/AI任务包138B 等由多个单元/外层包装拼装)
# 其模板 sheet 只描述内部单元,与指令块整体布局不是一一对应,故不做映射,
# 由 command_block_spec 的代码定义兜底。


def _header_cols(ws, limit: int = 30) -> dict[str, int]:
    cols: dict[str, int] = {}
    for c in range(1, min(ws.max_column, limit) + 1):
        h = _cell_str(ws, 1, c)
        if h and h not in cols:
            cols[h] = c
    return cols


def _first_col(headers: dict[str, int], keys) -> Optional[int]:
    for k in keys:
        if k in headers:
            return headers[k]
    return None


def _is_block_sheet(ws) -> bool:
    """数据块定义 sheet:含「十六进制码」表头,且非任务序列 sheet。"""
    headers = _header_cols(ws)
    if _BLK_HEX_KEY not in headers:
        return False
    if any(m in headers for m in _SEQ_HEADER_MARKERS):
        return False
    return any(k in headers for k in _BLK_NAME_KEYS)


def parse_block_sheet(ws) -> list[tuple[int, int, str, str]]:
    """解析单个数据块定义 sheet -> [(偏移, 字节长度, 字段名, 说明)]。

    以「字节数/字节长度」列为主驱动:该列为正整数的行即一个字段(同一字节的
    位域细分行字节数为空,自动跳过);字节数缺失时回退到「十六进制码」长度。
    字段名为空时以 "(保留)" 占位,偏移按累计字节长度推进。
    """
    headers = _header_cols(ws)
    c_name = _first_col(headers, _BLK_NAME_KEYS)
    c_len = _first_col(headers, _BLK_LEN_KEYS)
    c_hex = _first_col(headers, (_BLK_HEX_KEY,))
    c_desc = _first_col(headers, _BLK_DESC_KEYS)

    fields: list[tuple[int, int, str, str]] = []
    offset = 0
    for r in range(2, ws.max_row + 1):
        raw_len = _cell_str(ws, r, c_len) if c_len else ""
        if raw_len:
            # 「字节数」列有值:必须是正整数,否则视为页脚/说明行(如
            # "回放1停止码 | 58 15 c0 00"),不纳入字段定义
            try:
                length = int(float(raw_len))
            except ValueError:
                continue
            if length <= 0:
                continue
        else:
            # 「字节数」为空(位域细分行):由「十六进制码」字节数回退推断
            hex_val = (_cell_str(ws, r, c_hex).replace(" ", "")
                       if c_hex else "")
            if not hex_val or len(hex_val) % 2 or not _RE_HEXCELL.match(hex_val):
                continue
            length = len(hex_val) // 2
        name = _cell_str(ws, r, c_name) if c_name else ""
        desc = _cell_str(ws, r, c_desc).replace("\n", " ") if c_desc else ""
        fields.append((offset, length, name or "(保留)", desc))
        offset += length
    return fields


def load_block_defs_from_xlsm(path: str) -> dict[str, list[tuple[int, int, str, str]]]:
    """解析 xlsm 中所有「数据块定义」sheet。

    返回 {sheet名: [(偏移, 字节长度, 字段名, 说明), ...]}。
    """
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"command template not found: {p}")

    try:
        import openpyxl
    except ImportError as e:
        raise ImportError("openpyxl required: pip install openpyxl") from e

    wb = openpyxl.load_workbook(p, data_only=True, keep_vba=False)
    try:
        out: dict[str, list[tuple[int, int, str, str]]] = {}
        for name in wb.sheetnames:
            ws = wb[name]
            if not _is_block_sheet(ws):
                continue
            fields = parse_block_sheet(ws)
            if fields:
                out[name] = fields
        _log.info("loaded %d block defs from %s", len(out), p.name)
        return out
    finally:
        wb.close()


def load_block_defs_by_kind(path: str) -> dict[str, list[tuple[int, int, str, str]]]:
    """按 block_kind 映射数据块定义,供指令明细页/指令生成页使用。

    只要模板 sheet 能解析出字段即采用(不做与硬编码定义的等价性校验),
    这样更换指令模板后,指令明细页的字段布局会随新模板自动同步变更;
    模板缺失/该 sheet 不可解析时,由调用方回退到 BLOCK_FIELDS 代码定义。
    """
    sheet_defs = load_block_defs_from_xlsm(path)
    out: dict[str, list[tuple[int, int, str, str]]] = {}
    for kind, sheet in BLOCK_KIND_TO_SHEET.items():
        tmpl = sheet_defs.get(sheet)
        if tmpl:
            out[kind] = tmpl
    return out
