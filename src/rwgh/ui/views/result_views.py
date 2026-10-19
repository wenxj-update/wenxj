"""0F11/0F22/0F33/0F44 结果面板配置(基于通用 PacketPanel)。

字段定义严格按《任务规划输入输出数据包-20260907.xlsx》对应 sheet。
"""
from __future__ import annotations

from ...stk.packets import (parse_0f11, serialize_0f11, parse_0f22,
                            serialize_0f22, parse_0f33, serialize_0f33,
                            parse_0f44, serialize_0f44)
from ...planning.result_builder import (build_0f11, build_0f22, build_0f33,
                                        build_0f44, META_TASK_NO, TASK_NO)
from ..theme import C
from .packet_panel import PacketPanel
from .resource_views import (_ENC, _LINK_TYPE, _PFLAG, _RET_TYPE,
                             _fmt_rate, _fmt_utc, _parse_enum, _parse_rate,
                             _parse_utc)

# 规划结果状态字(0F33)
_0F33_STATUS = {
    0x00: "00-成像规划成功",
    0x01: "01-单圈成像时长不满足(7min)",
    0x02: "02-连续可见间隔不满足(360s)",
    0x03: "03-冲突消解失败",
    0x04: "04-电量约束判定失败",
    0x05: "05-固存约束判定失败",
    0x06: "06-未知原因",
    0x07: "07-不可见",
    0x08: "08-计算过顶时间失败",
    0x09: "09-成像结束晚于窗口结束",
    0x0A: "0A-计算机动时间失败",
}
# 规划结果状态字(0F44)
_0F44_STATUS = {
    0x00: "00-数传规划成功",
    0x01: "01-成功,边记边放+回放",
    0x02: "02-成功,边记边放",
    0x03: "03-冲突消解失败",
    0x04: "04-电量约束判定失败",
    0x05: "05-固存约束判定失败",
    0x06: "06-未知原因",
    0x10: "10-无可用链路资源",
    0x11: "11-数传规划时段不可见",
    0x12: "12-链路可见时长过短",
}
_0F11_IMG_TYPE = {11: "11-点目标成像", 12: "12-多角度成像",
                  13: "13-多条带拼接成像", 14: "14-连续条带成像",
                  15: "15-立体成像"}
_0F11_PAYLOAD = {1: "1-可见光", 2: "2-红外", 3: "3-可见+红外"}
_COMP = {0: "0-直通", 1: "1-无损", 2: "2-2:1", 4: "4-4:1", 8: "8-8:1"}
_BLOCK = {0: "0-切片模式", 1: "1-1km", 2: "2-2km", 3: "3-3km",
          4: "4-4km", 5: "5-5km", 6: "6-6km"}
_PROD = {0: "0-0级产品", 1: "1-1级产品", 2: "2-2级产品"}
_SOURCE = {1: "1-地面集中管控", 2: "2-星地协同_成像", 3: "3-星地协同_数传",
           4: "4-RLT任务规划", 5: "5-自主维轨任务",
           6: "6-星间协同_查证", 7: "7-星间KXX传输", 8: "8-目标库任务规划"}
_0F22_DL_TYPE = {11: "11-常规对地回放", 12: "12-边记边放", 3: "3-广播分发",
                 4: "4-KXX回放", 5: "5-随遇数传", 6: "6-它星落地数传"}
_TARGET_ATTR = {0: "0-点目标", 1: "1-区域目标", 2: "2-远洋舰船",
                3: "3-港口舰船", 4: "4-机场飞机", 5: "5-DD阵地车辆",
                6: "6-其他自定义"}


def _fmt_fixed(key: str, val) -> str:
    if val is None:
        return "—"
    m = {
        "packet_type": lambda v: f"0x{int(v):04X}",
        "imaging_type": lambda v: _0F11_IMG_TYPE.get(int(v), str(v)),
        "payload_mode": lambda v: _0F11_PAYLOAD.get(int(v), str(v)),
        "compression": lambda v: _COMP.get(int(v), str(v)),
        "block_size": lambda v: _BLOCK.get(int(v), str(v)),
        "block_comp_vis": lambda v: _COMP.get(int(v), str(v)),
        "block_comp_ir": lambda v: _COMP.get(int(v), str(v)),
        "product_level": lambda v: _PROD.get(int(v), str(v)),
        "task_source": lambda v: _SOURCE.get(int(v), str(v)),
        "datalink_rate": _fmt_rate,
        "playback_rate": _fmt_rate,
        "encryption": lambda v: _ENC.get(int(v), str(v)),
        "record_flag": lambda v: {0: "0-未记录", 1: "1-已记录"}.get(
            int(v), str(v)),
        "download_flag": lambda v: {0: "0-未下传", 1: "1-已下传"}.get(
            int(v), str(v)),
        "datalink_type": lambda v: _0F22_DL_TYPE.get(int(v), str(v)),
        "link_type": lambda v: _LINK_TYPE.get(int(v), str(v)),
        "task_source_44": lambda v: _SOURCE.get(int(v), str(v)),
    }
    fn = m.get(key)
    return fn(val) if fn else str(val)


def _parse_fixed(key: str, text: str):
    text = str(text).strip()
    if text.lower().startswith("0x"):
        return int(text, 16)
    try:
        return int(text, 0)
    except ValueError:
        pass
    enum_maps = {
        "imaging_type": _0F11_IMG_TYPE, "payload_mode": _0F11_PAYLOAD,
        "compression": _COMP, "block_size": _BLOCK,
        "block_comp_vis": _COMP, "block_comp_ir": _COMP,
        "product_level": _PROD, "task_source": _SOURCE,
        "record_flag": {0: "0-未记录", 1: "1-已记录"},
        "download_flag": {0: "0-未下传", 1: "1-已下传"},
        "datalink_type": _0F22_DL_TYPE, "link_type": _LINK_TYPE,
    }
    mp = enum_maps.get(key)
    if mp:
        return _parse_enum(text, mp, 0)
    try:
        return int(float(text))
    except (ValueError, TypeError):
        return 0


# ==================== 0F11 待执行成像任务规划方案 ====================

_0F11_FIXED = [
    ("packet_type", "包类型", "", "0x0F11"),
    ("total_packets", "总包数量", "", "从1开始计"),
    ("sequence_no", "序列号", "", "全局递增"),
    ("cur_packet_no", "当前包序号", "", "从1开始"),
    ("cur_packet_len", "当前包长度", "字节", "36+76*N"),
    ("meta_task_no", "元任务编号", "", "任务规划算法模块生成"),
    ("task_no", "任务编号", "", "地面上注"),
    ("priority", "任务优先级", "", "[0,255],越小优先级越高"),
    ("ret_priority", "载荷数据回传优先级", "", "I级~V级"),
    ("imaging_type", "成像任务类型", "", "11d-点目标成像等"),
    ("payload_mode", "载荷模式", "", "1-可见光;2-红外;3-可见+红外"),
    ("compression", "成像数据压缩比", "", "0-直通;1-无损;2-2:1;4-4:1;8-8:1"),
    ("storage_task_no", "固存任务号", "", "程控[1,60] 目标库[61,130]"),
    ("datalink_type", "数传任务类型", "", "21-常规回放等"),
    ("return_data_type", "回传数据类型", "", "0-原始;1-处理;2-原始+处理"),
    ("datalink_rate", "数传速率", "", "b7b6通道选择;b5~b0速率"),
    ("encryption", "明密状态", "", "0-密态;1-明态"),
    ("smart_process", "星上智能处理开关", "", "1-开(默认);0-关"),
    ("block_size", "切块大小", "", "0-切片;1~6-1~6km切块"),
    ("block_comp_vis", "切块压缩比_可见光", "", "8-8:1(默认)"),
    ("block_comp_ir", "切块压缩比_红外", "", "8-8:1(默认)"),
    ("product_level", "星上处理输出产品级别", "", "0/1/2级产品"),
    ("task_source", "任务来源", "", "1~8"),
    ("record_flag", "记录标识", "", "0-未记录;1-已记录(默认)"),
    ("download_flag", "下传标识", "", "0-未下传(默认);1-已下传"),
    ("target_count", "目标数量", "", "当前元任务下点目标数量"),
]
_0F11_DERIVED = {"packet_type", "cur_packet_len", "target_count"}
_0F11_COLS = ["序号", "目标编号", "网格编号", "目标类型属性", "目标优先级",
              "网格优先级", "目标经度(°)", "目标纬度(°)", "区域半径(km)",
              "条带编号", "姿态机动开始时间", "姿态机动持续(s)",
              "成像开始时间", "成像结束时间", "偏航角(°)", "俯仰角(°)",
              "滚动角(°)", "离轴角(°)", "太阳高度角(°)", "原始固存文件号",
              "处理固存文件号", "原始文件大小(0.1MB)", "处理文件大小(0.1MB)"]
_0F11_EDIT = set(_0F11_COLS) - {"序号"}


def _fmt_0f11_row(i: int, t: dict) -> dict:
    grid = t.get("grid_no", "")
    grid_s = str(grid) if not isinstance(grid, int) else (
        f"0x{grid:016X}" if grid >= 0xFFFFFFFFFFFFFFFF - 8 else str(grid))
    return {
        "序号": i,
        "目标编号": int(t.get("target_id", 0)),
        "网格编号": grid_s,
        "目标类型属性": _TARGET_ATTR.get(int(t.get("target_attr", 0)),
                                         str(t.get("target_attr", ""))),
        "目标优先级": int(t.get("target_priority", 1)),
        "网格优先级": int(t.get("grid_priority", 0xFFFF)),
        "目标经度(°)": f"{float(t.get('lon', 0)):.6f}",
        "目标纬度(°)": f"{float(t.get('lat', 0)):.6f}",
        "区域半径(km)": int(t.get("radius_km", 0)),
        "条带编号": int(t.get("strip_no", 1)),
        "姿态机动开始时间": _fmt_utc(t.get("maneuver_start", 0)),
        "姿态机动持续(s)": int(t.get("maneuver_duration", 219)),
        "成像开始时间": _fmt_utc(t.get("imaging_start", 0)),
        "成像结束时间": _fmt_utc(t.get("imaging_end", 0)),
        "偏航角(°)": f"{float(t.get('yaw', 0)):.4f}",
        "俯仰角(°)": f"{float(t.get('pitch', 0)):.4f}",
        "滚动角(°)": f"{float(t.get('roll', 0)):.4f}",
        "离轴角(°)": f"{float(t.get('off_axis', 0)):.4f}",
        "太阳高度角(°)": int(t.get("sun_elev", 35)),
        "原始固存文件号": int(t.get("raw_file_no", 1)),
        "处理固存文件号": int(t.get("proc_file_no", 126)),
        "原始文件大小(0.1MB)": int(t.get("raw_file_size", 0)),
        "处理文件大小(0.1MB)": int(t.get("proc_file_size", 0)),
        "_colors": {"目标类型属性": C.TARGET, "成像开始时间": C.PKT_TIME},
    }


def _apply_0f11_edit(col: str, value: str, t: dict) -> bool:
    try:
        if col == "目标编号":
            t["target_id"] = int(value)
        elif col == "网格编号":
            t["grid_no"] = int(value, 0)
        elif col == "目标类型属性":
            t["target_attr"] = _parse_enum(value, _TARGET_ATTR, 0)
        elif col == "目标优先级":
            t["target_priority"] = int(value)
        elif col == "网格优先级":
            t["grid_priority"] = int(value)
        elif col == "目标经度(°)":
            t["lon"] = float(value)
        elif col == "目标纬度(°)":
            t["lat"] = float(value)
        elif col == "区域半径(km)":
            t["radius_km"] = int(value)
        elif col == "条带编号":
            t["strip_no"] = int(value)
        elif col == "姿态机动开始时间":
            t["maneuver_start"] = _parse_utc(value)
        elif col == "姿态机动持续(s)":
            t["maneuver_duration"] = int(value)
        elif col == "成像开始时间":
            t["imaging_start"] = _parse_utc(value)
        elif col == "成像结束时间":
            t["imaging_end"] = _parse_utc(value)
        elif col == "偏航角(°)":
            t["yaw"] = float(value)
        elif col == "俯仰角(°)":
            t["pitch"] = float(value)
        elif col == "滚动角(°)":
            t["roll"] = float(value)
        elif col == "离轴角(°)":
            t["off_axis"] = float(value)
        elif col == "太阳高度角(°)":
            t["sun_elev"] = int(value)
        elif col == "原始固存文件号":
            t["raw_file_no"] = int(value)
        elif col == "处理固存文件号":
            t["proc_file_no"] = int(value)
        elif col == "原始文件大小(0.1MB)":
            t["raw_file_size"] = int(value)
        elif col == "处理文件大小(0.1MB)":
            t["proc_file_size"] = int(value)
        else:
            return False
    except (ValueError, TypeError):
        return False
    return True


def create_0f11_panel() -> PacketPanel:
    return PacketPanel(
        hex_title="0F11 待执行成像任务规划方案报文",
        record_title="目标记录列表(每记录 77B,V2)",
        count_label="目标数",
        fixed_fields=_0F11_FIXED, fixed_derived=_0F11_DERIVED,
        record_columns=_0F11_COLS, record_editable=_0F11_EDIT,
        record_key="targets", count_key="target_count",
        parse_fn=parse_0f11, serialize_fn=serialize_0f11,
        default_info_fn=lambda: build_0f11([], []),
        fmt_fixed_value=_fmt_fixed, parse_fixed_edit=_parse_fixed,
        fmt_record_row=_fmt_0f11_row, apply_record_edit=_apply_0f11_edit,
        delete_label="删除选中目标")


# ==================== 0F22 待执行数传任务规划方案 ====================

_0F22_FIXED = [
    ("packet_type", "包类型", "", "0x0F22"),
    ("total_packets", "总包数量", "", "从1开始"),
    ("sequence_no", "序列号", "", "全局递增"),
    ("cur_packet_no", "当前包序号", "", "从1开始"),
    ("cur_packet_len", "当前包长度", "字节", "48+记录长×N(自动检测)"),
    ("meta_task_no", "元任务编号", "", "任务规划算法模块生成"),
    ("datalink_type", "数传任务类型", "", "11-常规对地回放等"),
    ("link_id", "链路编号", "", "数传链路资源唯一标识"),
    ("link_type", "链路类型", "", "1-X对地数传链路等"),
    ("dest_id", "链路目的地ID", "", "卫星SCID或地面站编号"),
    ("playback_rate", "回放速率", "", "b7b6通道;b5~b0速率"),
    ("encryption", "明密状态", "", "0-密态;1-明态"),
    ("station_id", "数传站编号", "", "链路类型1/3/5时有效"),
    ("station_lon", "数传站经度(°)", "", "当量1E-6°"),
    ("station_lat", "数传站纬度(°)", "", "当量1E-6°"),
    ("track_start", "跟踪开始时间", "", "UTC基准时"),
    ("track_end", "跟踪结束时间", "", "UTC基准时"),
    ("datalink_start", "数传开始时间", "", "UTC基准时"),
    ("datalink_end", "数传结束时间", "", "UTC基准时"),
    ("file_count", "回放文件数量", "", "根据数量循环N"),
]
_0F22_DERIVED = {"packet_type", "cur_packet_len", "file_count"}
_0F22_COLS = ["序号", "固存任务号", "固存文件号", "成像任务编号",
              "载荷数据回传优先级", "目标优先级", "网格优先级",
              "回放开始时间", "回放结束时间", "目标元任务编号"]
_0F22_EDIT = set(_0F22_COLS) - {"序号"}


def _fmt_0f22_row(i: int, f: dict) -> dict:
    return {
        "序号": i,
        "固存任务号": int(f.get("storage_task_no", 61)),
        "固存文件号": int(f.get("file_no", 1)),
        "成像任务编号": int(f.get("imaging_task_no", 0)),
        "载荷数据回传优先级": int(f.get("ret_priority", 2)),
        "目标优先级": int(f.get("target_priority", 0xFF)),
        "网格优先级": int(f.get("grid_priority", 2)),
        "回放开始时间": _fmt_utc(f.get("playback_start", 0)),
        "回放结束时间": _fmt_utc(f.get("playback_end", 0)),
        "目标元任务编号": int(f.get("target_meta_task", 0)),
        "_colors": {"固存文件号": C.PKT_DATA},
    }


def _apply_0f22_edit(col: str, value: str, f: dict) -> bool:
    try:
        if col == "固存任务号":
            f["storage_task_no"] = int(value)
        elif col == "固存文件号":
            f["file_no"] = int(value)
        elif col == "成像任务编号":
            f["imaging_task_no"] = int(value)
        elif col == "载荷数据回传优先级":
            f["ret_priority"] = int(value)
        elif col == "目标优先级":
            f["target_priority"] = int(value)
        elif col == "网格优先级":
            f["grid_priority"] = int(value)
        elif col == "回放开始时间":
            f["playback_start"] = _parse_utc(value)
        elif col == "回放结束时间":
            f["playback_end"] = _parse_utc(value)
        elif col == "目标元任务编号":
            f["target_meta_task"] = int(value)
        else:
            return False
    except (ValueError, TypeError):
        return False
    return True


def empty_0f22_info() -> dict:
    """无数传规划时的 0F22 空包(固定区默认值 + 0 条文件)。"""
    return {
        "packet_type": 0x0F22, "total_packets": 1, "sequence_no": 1,
        "cur_packet_no": 1, "cur_packet_len": 48, "meta_task_no": 123,
        "datalink_type": 211, "link_id": 1, "link_type": 1,
        "dest_id": 56, "playback_rate": 0xC1, "encryption": 1,
        "station_id": 1, "station_lon": 117.08, "station_lat": 24.1413,
        "track_start": 0, "track_end": 0, "datalink_start": 0,
        "datalink_end": 0, "file_count": 0, "files": []}


def create_0f22_panel() -> PacketPanel:
    return PacketPanel(
        hex_title="0F22 待执行数传任务规划方案报文",
        record_title="回放文件列表(每记录 23B)",
        count_label="文件数",
        fixed_fields=_0F22_FIXED, fixed_derived=_0F22_DERIVED,
        record_columns=_0F22_COLS, record_editable=_0F22_EDIT,
        record_key="files", count_key="file_count",
        parse_fn=parse_0f22, serialize_fn=serialize_0f22,
        default_info_fn=lambda: build_0f22([], [], None, None)
        or empty_0f22_info(),
        fmt_fixed_value=_fmt_fixed, parse_fixed_edit=_parse_fixed,
        fmt_record_row=_fmt_0f22_row, apply_record_edit=_apply_0f22_edit,
        delete_label="删除选中文件")


# ==================== 0F33 成像任务规划结果反馈 ====================

_0F33_FIXED = [
    ("packet_type", "包类型", "", "0x0F33"),
    ("total_packets", "总包数量", "", "从1开始计数"),
    ("sequence_no", "序列号", "", "全局递增"),
    ("cur_packet_no", "当前包序号", "", "从1开始计数"),
    ("cur_packet_len", "当前包长度", "字节", "12+70*N"),
    ("task_count", "任务数量", "", "N"),
]
_0F33_DERIVED = {"packet_type", "cur_packet_len", "task_count"}
_0F33_COLS = ["序号", "任务编号", "目标编号", "规划结果状态字",
              "目标点经度(°)", "目标点纬度(°)", "可见窗口前沿",
              "可见窗口后沿", "机动开始时刻", "机动结束时刻",
              "成像开始时刻", "成像结束时刻", "滚动角(°)", "俯仰角(°)",
              "偏航角(°)", "任务来源", "冲突的目标编号"]
_0F33_EDIT = set(_0F33_COLS) - {"序号"}


def _fmt_0f33_row(i: int, t: dict) -> dict:
    status = int(t.get("status", 0))
    st_text = _0F33_STATUS.get(status, str(status))
    st_color = C.OK if status == 0 else C.ERR
    return {
        "序号": i,
        "任务编号": int(t.get("task_no", 0)),
        "目标编号": int(t.get("target_no", 0)),
        "规划结果状态字": st_text,
        "目标点经度(°)": f"{float(t.get('lon', 0)):.6f}",
        "目标点纬度(°)": f"{float(t.get('lat', 0)):.6f}",
        "可见窗口前沿": _fmt_utc(t.get("window_start", 0)),
        "可见窗口后沿": _fmt_utc(t.get("window_end", 0)),
        "机动开始时刻": _fmt_utc(t.get("maneuver_start", 0)),
        "机动结束时刻": _fmt_utc(t.get("maneuver_end", 0)),
        "成像开始时刻": _fmt_utc(t.get("imaging_start", 0)),
        "成像结束时刻": _fmt_utc(t.get("imaging_end", 0)),
        "滚动角(°)": f"{float(t.get('roll', 0)):.4f}",
        "俯仰角(°)": f"{float(t.get('pitch', 0)):.4f}",
        "偏航角(°)": f"{float(t.get('yaw', 0)):.4f}",
        "任务来源": _SOURCE.get(int(t.get("task_source", 2)),
                                str(t.get("task_source", ""))),
        "冲突的目标编号": int(t.get("conflict_target", 0)),
        "_badges": {"规划结果状态字": st_color},
        "_colors": {"可见窗口前沿": C.PKT_TIME, "可见窗口后沿": C.PKT_TIME},
    }


def _apply_0f33_edit(col: str, value: str, t: dict) -> bool:
    try:
        if col == "任务编号":
            t["task_no"] = int(value)
        elif col == "目标编号":
            t["target_no"] = int(value)
        elif col == "规划结果状态字":
            t["status"] = _parse_enum(value, _0F33_STATUS, 0)
        elif col == "目标点经度(°)":
            t["lon"] = float(value)
        elif col == "目标点纬度(°)":
            t["lat"] = float(value)
        elif col == "可见窗口前沿":
            t["window_start"] = _parse_utc(value)
        elif col == "可见窗口后沿":
            t["window_end"] = _parse_utc(value)
        elif col == "机动开始时刻":
            t["maneuver_start"] = _parse_utc(value)
        elif col == "机动结束时刻":
            t["maneuver_end"] = _parse_utc(value)
        elif col == "成像开始时刻":
            t["imaging_start"] = _parse_utc(value)
        elif col == "成像结束时刻":
            t["imaging_end"] = _parse_utc(value)
        elif col == "滚动角(°)":
            t["roll"] = float(value)
        elif col == "俯仰角(°)":
            t["pitch"] = float(value)
        elif col == "偏航角(°)":
            t["yaw"] = float(value)
        elif col == "任务来源":
            t["task_source"] = _parse_enum(value, _SOURCE, 2)
        elif col == "冲突的目标编号":
            t["conflict_target"] = int(value)
        else:
            return False
    except (ValueError, TypeError):
        return False
    return True


def create_0f33_panel() -> PacketPanel:
    return PacketPanel(
        hex_title="0F33 成像任务规划结果反馈报文",
        record_title="任务反馈列表(每记录 70B)",
        count_label="任务数",
        fixed_fields=_0F33_FIXED, fixed_derived=_0F33_DERIVED,
        record_columns=_0F33_COLS, record_editable=_0F33_EDIT,
        record_key="tasks", count_key="task_count",
        parse_fn=parse_0f33, serialize_fn=serialize_0f33,
        default_info_fn=lambda: build_0f33([], []),
        fmt_fixed_value=_fmt_fixed, parse_fixed_edit=_parse_fixed,
        fmt_record_row=_fmt_0f33_row, apply_record_edit=_apply_0f33_edit,
        delete_label="删除选中反馈")


# ==================== 0F44 数传任务规划结果反馈 ====================

_0F44_FIXED = [
    ("packet_type", "包类型", "", "0x0F44"),
    ("total_packets", "总包数量", "", "从1开始"),
    ("sequence_no", "序列号", "", "全局递增"),
    ("cur_packet_no", "当前包序号", "", "从1开始"),
    ("cur_packet_len", "当前包长度", "字节", "12+31*N"),
    ("task_count", "任务数量", "", "N"),
]
_0F44_DERIVED = {"packet_type", "cur_packet_len", "task_count"}
_0F44_COLS = ["序号", "任务编号", "元任务编号", "链路编号", "链路类型",
              "链路目的地ID", "规划结果状态字", "数传开始时刻",
              "数传结束时刻", "数传任务类型", "传输文件数量"]
_0F44_EDIT = set(_0F44_COLS) - {"序号"}


def _fmt_0f44_row(i: int, t: dict) -> dict:
    status = int(t.get("status", 0))
    st_text = _0F44_STATUS.get(status, str(status))
    st_color = C.OK if status in (0, 1, 2) else C.ERR
    return {
        "序号": i,
        "任务编号": int(t.get("task_no", 0)),
        "元任务编号": int(t.get("meta_task_no", 0)),
        "链路编号": int(t.get("link_id", 1)),
        "链路类型": _LINK_TYPE.get(int(t.get("link_type", 1)),
                                   str(t.get("link_type", ""))),
        "链路目的地ID": int(t.get("dest_id", 0)),
        "规划结果状态字": st_text,
        "数传开始时刻": _fmt_utc(t.get("datalink_start", 0)),
        "数传结束时刻": _fmt_utc(t.get("datalink_end", 0)),
        "数传任务类型": _0F22_DL_TYPE.get(int(t.get("datalink_type", 11)),
                                         str(t.get("datalink_type", ""))),
        "传输文件数量": int(t.get("file_count", 0)),
        "_badges": {"规划结果状态字": st_color},
        "_colors": {"数传开始时刻": C.PKT_TIME, "数传结束时刻": C.PKT_TIME},
    }


def _apply_0f44_edit(col: str, value: str, t: dict) -> bool:
    try:
        if col == "任务编号":
            t["task_no"] = int(value)
        elif col == "元任务编号":
            t["meta_task_no"] = int(value)
        elif col == "链路编号":
            t["link_id"] = int(value)
        elif col == "链路类型":
            t["link_type"] = _parse_enum(value, _LINK_TYPE, 1)
        elif col == "链路目的地ID":
            t["dest_id"] = int(value)
        elif col == "规划结果状态字":
            t["status"] = _parse_enum(value, _0F44_STATUS, 0)
        elif col == "数传开始时刻":
            t["datalink_start"] = _parse_utc(value)
        elif col == "数传结束时刻":
            t["datalink_end"] = _parse_utc(value)
        elif col == "数传任务类型":
            t["datalink_type"] = _parse_enum(value, _0F22_DL_TYPE, 11)
        elif col == "传输文件数量":
            t["file_count"] = int(value)
        else:
            return False
    except (ValueError, TypeError):
        return False
    return True


def empty_0f44_info() -> dict:
    """无数传反馈时的 0F44 空包(固定区默认值 + 0 条任务)。"""
    return {
        "packet_type": 0x0F44, "total_packets": 1, "sequence_no": 1,
        "cur_packet_no": 1, "cur_packet_len": 12, "task_count": 0,
        "tasks": []}


def create_0f44_panel() -> PacketPanel:
    return PacketPanel(
        hex_title="0F44 数传任务规划结果反馈报文",
        record_title="任务反馈列表(每记录 31B)",
        count_label="任务数",
        fixed_fields=_0F44_FIXED, fixed_derived=_0F44_DERIVED,
        record_columns=_0F44_COLS, record_editable=_0F44_EDIT,
        record_key="tasks", count_key="task_count",
        parse_fn=parse_0f44, serialize_fn=serialize_0f44,
        default_info_fn=lambda: build_0f44(None) or empty_0f44_info(),
        fmt_fixed_value=_fmt_fixed, parse_fixed_edit=_parse_fixed,
        fmt_record_row=_fmt_0f44_row, apply_record_edit=_apply_0f44_edit,
        delete_label="删除选中反馈")
