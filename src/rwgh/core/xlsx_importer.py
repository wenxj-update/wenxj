"""Excel 数据导入器(用户自定义格式)。

格式：单个 sheet，两列：
  第一列：报文标识(如 3101 / 0C12 / 0C15 / 0B01 / A002 / A012 / 0802)
  第二列：码字(十六进制字符串，不带空格)

每行一条报文，行顺序任意。报文标识不区分大小写。
"""
from __future__ import annotations

import logging
from typing import Optional

from openpyxl import load_workbook

from ..stk.packets import (
    parse_3101, parse_0c12, parse_0c15, parse_0b01,
    parse_a002, parse_a012, parse_0802,
)

_log = logging.getLogger("rwgh.core.xlsx_importer")

# 报文标识 → (解析函数, 面板属性名)
_PACKET_MAP = {
    "3101": (parse_3101, "panel_3101"),
    "0C12": (parse_0c12, "panel_0c12"),
    "0c12": (parse_0c12, "panel_0c12"),
    "0C15": (parse_0c15, "panel_0c15"),
    "0c15": (parse_0c15, "panel_0c15"),
    "0B01": (parse_0b01, "panel_0b01"),
    "0b01": (parse_0b01, "panel_0b01"),
    "A002": (parse_a002, "panel_a002"),
    "a002": (parse_a002, "panel_a002"),
    "A012": (parse_a012, "panel_a012"),
    "a012": (parse_a012, "panel_a012"),
    "0802": (parse_0802, "panel_0802"),
}


class XlsxImportError(Exception):
    """Excel 导入格式错误。"""


class XlsxImporter:
    """按用户定义格式解析 Excel 并填充界面。"""

    @staticmethod
    def validate(path: str) -> list[str]:
        """校验 Excel 格式，返回错误信息列表(空列表表示通过)。"""
        errors: list[str] = []
        try:
            wb = load_workbook(path, read_only=True, data_only=True)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"无法打开 Excel 文件：{exc}")
            return errors

        # 取第一个 sheet(忽略名称)
        ws = wb.worksheets[0]
        if ws.max_column < 2:
            errors.append("Excel 至少需要两列：第一列'报文标识'，第二列'码字'")
            wb.close()
            return errors

        # 校验表头(可选，但建议有)
        header = [str(ws.cell(1, c).value or "").strip() for c in range(1, 3)]
        if header[0] and header[0] not in ("报文标识", "标识"):
            _log.info("Excel 第一列表头非'报文标识'，按无表头处理")

        # 逐行校验
        for row in range(2, ws.max_row + 1):
            marker = str(ws.cell(row, 1).value or "").strip()
            code = str(ws.cell(row, 2).value or "").strip()
            if not marker and not code:
                continue  # 空行跳过
            if not marker:
                errors.append(f"第{row}行：报文标识为空")
                continue
            if not code:
                errors.append(f"第{row}行：码字为空")
                continue
            # 报文标识去空格/换行后匹配(只判断码字)
            marker_clean = marker.replace(" ", "").replace("\n", "").replace("\r", "")
            if marker_clean not in _PACKET_MAP:
                errors.append(
                    f"第{row}行：未知报文标识'{marker}'，"
                    f"支持：{', '.join(sorted(set(_PACKET_MAP.keys())))}")
                continue
            # 校验码字为有效十六进制(去空格/换行后)
            code_clean = code.replace(" ", "").replace("\n", "").replace("\r", "")
            try:
                bytes.fromhex(code_clean)
            except ValueError:
                errors.append(f"第{row}行：码字'{code[:20]}...'不是有效的十六进制字符串")
                continue

        wb.close()
        return errors

    @classmethod
    def import_file(cls, path: str, target_io_view) -> dict:
        """解析 Excel 并填充界面。

        返回统计信息：{"3101": n, "0C12": n, ...}
        """
        wb = load_workbook(path, read_only=True, data_only=True)
        ws = wb.worksheets[0]

        stats: dict[str, int] = {}
        parsed: dict[str, list] = {}

        for row in range(2, ws.max_row + 1):
            marker = str(ws.cell(row, 1).value or "").strip()
            code = str(ws.cell(row, 2).value or "").strip()
            if not marker and not code:
                continue
            # 报文标识去空格/换行后匹配(只判断码字)
            marker_clean = marker.replace(" ", "").replace("\n", "").replace("\r", "")
            if marker_clean not in _PACKET_MAP:
                continue

            parse_fn, panel_attr = _PACKET_MAP[marker_clean]
            hex_str = code.replace(" ", "").replace("\n", "").replace("\r", "")
            raw = bytes.fromhex(hex_str)

            try:
                info = parse_fn(raw)
            except Exception as exc:  # noqa: BLE001
                raise XlsxImportError(
                    f"第{row}行报文{marker_clean}解析失败：{exc}") from exc

            key = marker_clean.upper()
            parsed.setdefault(key, []).append(info)
            stats[key] = stats.get(key, 0) + 1

        wb.close()

        # ---- 填充界面 ----
        # 3101：目标列表 + Hex
        if "3101" in parsed:
            cls._fill_3101(target_io_view, parsed["3101"])

        # 0C12 / 0C15 / 0802：Hex + 记录表
        for key, panel_attr in (("0C12", "panel_0c12"),
                                ("0C15", "panel_0c15"),
                                ("0802", "panel_0802")):
            if key in parsed:
                cls._fill_hex_panel(target_io_view, panel_attr, parsed[key])

        # 0B01 / A002 / A012：Hex
        for key, panel_attr in (("0B01", "panel_0b01"),
                                ("A002", "panel_a002"),
                                ("A012", "panel_a012")):
            if key in parsed:
                cls._fill_hex_panel(target_io_view, panel_attr, parsed[key])

        return stats

    @staticmethod
    def _fill_3101(view, infos: list) -> None:
        """填充 3101 目标列表和 Hex。"""
        if not infos:
            return
        # 取最后一条 3101(通常只有一条)
        info = infos[-1]
        # 触发目标列表刷新
        from ..models.target import TargetPoint
        targets = []
        for t in info.get("targets", []):
            targets.append(TargetPoint(
                id=str(t.get("target_id", "")),
                lon=float(t.get("lon", 0.0)),
                lat=float(t.get("lat", 0.0)),
                alt=float(t.get("alt", 0.05)),
            ))
        if targets:
            view.on_targets_ready(targets)
        # 更新 Hex 显示
        raw = info.get("_raw_bytes", b"")
        if raw and hasattr(view, "panel_3101") and hasattr(view.panel_3101, "set_hex_bytes"):
            view.panel_3101.set_hex_bytes(raw)

    @staticmethod
    def _fill_hex_panel(view, panel_attr: str, infos: list) -> None:
        """填充通用 Hex 面板(0C12/0C15/0B01/A002/A012/0802)。"""
        if not infos:
            return
        panel = getattr(view, panel_attr, None)
        if panel is None:
            _log.warning("面板 %s 不存在", panel_attr)
            return
        info = infos[-1]  # 取最后一条
        raw = info.get("_raw_bytes", b"")
        if raw and hasattr(panel, "set_hex_bytes"):
            panel.set_hex_bytes(raw)
        # 如果有记录表，也刷新
        if hasattr(panel, "refresh_table"):
            panel.refresh_table(info)

    @staticmethod
    def packet_warnings(code: str, info: dict, raw: bytes) -> list[str]:
        """报文级合理性校验:检测"能解析但内容错位/长度不符"的异常。

        返回中文告警列表(空=正常)。覆盖:
        - 3101: 声明目标数 vs 实际解析数(记录结构错位)、尾部多余字节
          (记录长度与 87B 规范不符;声明包长交叉校验由
          packet_format_loader 的软提示承担,原模板声明值过时不弹窗)
        - 0B01/A002/A012: 定长报文长度校验(16B/62B/62B)
        """
        w: list[str] = []
        try:
            if code == "3101":
                n_decl = int(info.get("target_count") or 0)
                n_real = len(info.get("targets") or [])
                if n_decl != n_real:
                    w.append(f"声明目标数{n_decl}≠实际解析{n_real}"
                             "(记录结构与87B/目标规范不符,数据已错位)")
                expect = 46 + 87 * n_real
                if len(raw) > expect:
                    w.append(f"尾部{len(raw) - expect}B未解析"
                             f"(实际{len(raw)}B,规范46+87×{n_real}={expect}B)")
            elif code in ("0B01", "A002", "A012"):
                std = {"0B01": 16, "A002": 62, "A012": 62}[code]
                if len(raw) != std:
                    w.append(f"长度{len(raw)}B≠标准{std}B"
                             "(模板字段定义可能已变更)")
        except (TypeError, ValueError):
            pass
        return w

    @staticmethod
    def format_description() -> str:
        """返回 Excel 格式说明文本。"""
        return """\
【Excel 导入格式说明】

格式：单个 sheet，两列。

第一列：报文标识（不区分大小写）
  支持：3101、0C12、0C15、0B01、A002、A012、0802

第二列：码字
  十六进制字符串，不带空格（允许包含空格/换行，导入时会自动清除）
  长度必须与对应报文的"当前包长度"字段一致

示例：

  报文标识    码字
  3101        31010001000A...（完整3101报文十六进制）
  0C12        0C120001...（完整0C12报文十六进制）
  0B01        0B010001...（完整0B01报文十六进制）
  A012        A0120001...（完整A012报文十六进制）
  0802        08020001...（完整0802报文十六进制）

注意事项：
  1. 每行一条报文，行顺序任意
  2. 报文标识必须在支持列表中，否则该行被跳过
  3. 码字必须是有效十六进制，否则报错
  4. 解析失败时会给出具体行号和错误原因
  5. 同一种报文标识出现多次时，以最后一条为准
"""
