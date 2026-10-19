"""0C12 数传链路资源 / 0C15 数传站址资源 视图配置。

基于通用 PacketPanel,按 Excel 数据包格式定义(数传链路资源 /
数传站址资源 sheet)配置字段、列、格式化与编辑回写逻辑。
"""
from __future__ import annotations

from datetime import timedelta

from ...models.orbit import STK_EPOCH_2009
from ...stk.packets import (parse_0c12, serialize_0c12, default_0c12_info,
                            parse_0c15, serialize_0c15, default_0c15_info,
                            parse_0b01, serialize_0b01, default_0b01_info,
                            parse_a002, serialize_a002, default_a002_info,
                            parse_a012, serialize_a012, default_a012_info,
                            parse_0802, serialize_0802, default_0802_info)
from ..theme import C
from .packet_panel import PacketPanel

# ---------- 枚举映射 ----------

_LINK_TYPE = {1: "1-X对地数传链路", 2: "2-W星间微波链路", 3: "3-广播分发链路",
              4: "4-KXX链路", 5: "5-随遇数传", 6: "6-它星落地数传"}
_ENC = {0: "0-加密", 1: "1-明传"}
_PFLAG = {0: "0-否", 255: "255-是"}
_RET_TYPE = {0: "0-原始数据", 1: "1-处理数据", 2: "2-原始+处理"}
_ST_CATEGORY = {1: "1-常规数传站", 2: "2-SY数传站"}


def _parse_enum(text: str, mapping: dict, default: int = 0) -> int:
    """编辑回写:接受纯数字或 'N-描述' 形式。"""
    text = str(text).strip()
    try:
        return int(text, 0)
    except ValueError:
        pass
    for k, v in mapping.items():
        if text == v or text.startswith(f"{k}-") or text.startswith(f"{k}-"):
            return k
    # 尝试取前导数字
    head = text.split("-")[0].strip()
    if head.isdigit():
        return int(head)
    return default


def _fmt_utc(sec) -> str:
    try:
        s = int(sec)
        dt = STK_EPOCH_2009 + timedelta(seconds=s)
        return f"{s} ({dt.strftime('%Y-%m-%d %H:%M:%S')})"
    except (TypeError, ValueError, OverflowError):
        return str(sec)


def _parse_utc(text: str) -> int:
    parts = str(text).strip().split()
    return int(parts[0]) if parts else 0


def _fmt_rate(v) -> str:
    try:
        return f"0x{int(v):02X}"
    except (TypeError, ValueError):
        return str(v)


def _parse_rate(text: str) -> int:
    text = str(text).strip()
    if text.lower().startswith("0x"):
        return int(text, 16)
    return int(text)


def _fmt_fixed_common(key: str, val) -> str:
    if val is None:
        return "—"
    if key == "packet_type":
        return f"0x{int(val):04X}"
    return str(val)


def _parse_fixed_common(key: str, text: str):
    text = str(text).strip()
    if key == "packet_type":
        if text.lower().startswith("0x"):
            return int(text, 16)
        return int(text)
    return int(text)


# ==================== 0C12 数传链路资源 ====================

_0C12_FIXED_FIELDS = [
    ("packet_type", "包类型", "", "0x0C12"),
    ("total_packets", "总包数量", "", "从1开始计"),
    ("sequence_no", "序列号", "", "全局递增,设备上电/复位初始化,每发送一帧加1"),
    ("cur_packet_no", "当前包序号", "", "从1开始计"),
    ("cur_packet_len", "当前包长度", "字节", "从1开始计,12+41*K+4"),
    ("link_count", "传输链路数量", "", "根据数量循环"),
]
_0C12_DERIVED = {"packet_type", "cur_packet_len", "link_count"}

_0C12_COLUMNS = ["序号", "链路编号", "链路类型", "链路目的地ID",
                 "链路开始时间", "链路结束时间", "明密状态", "数传速率",
                 "链路专用任务号", "数传站编号", "数传站经度(°)",
                 "数传站纬度(°)", "数传站可见仰角(°)", "周期链路标识",
                 "周期秒数", "回传数据类型"]
_0C12_EDIT_COLS = set(_0C12_COLUMNS) - {"序号"}


def _fmt_link_row(i: int, lk: dict) -> dict:
    return {
        "序号": i,
        "链路编号": int(lk.get("link_id", 0)),
        "链路类型": _LINK_TYPE.get(int(lk.get("link_type", 1)),
                                   str(lk.get("link_type", ""))),
        "链路目的地ID": int(lk.get("dest_id", 0)),
        "链路开始时间": _fmt_utc(lk.get("link_start", 0)),
        "链路结束时间": _fmt_utc(lk.get("link_end", 0)),
        "明密状态": _ENC.get(int(lk.get("encryption", 0)),
                             str(lk.get("encryption", ""))),
        "数传速率": _fmt_rate(lk.get("datalink_rate", 0xC1)),
        "链路专用任务号": int(lk.get("task_no", 0)),
        "数传站编号": int(lk.get("station_id", 0)),
        "数传站经度(°)": f"{float(lk.get('station_lon', 0)):.6f}",
        "数传站纬度(°)": f"{float(lk.get('station_lat', 0)):.6f}",
        "数传站可见仰角(°)": f"{float(lk.get('station_elev_angle', 10.0)):.1f}",
        "周期链路标识": _PFLAG.get(int(lk.get("periodic_flag", 0)),
                                   str(lk.get("periodic_flag", ""))),
        "周期秒数": int(lk.get("periodic_seconds", 0)),
        "回传数据类型": _RET_TYPE.get(int(lk.get("return_data_type", 0)),
                                      str(lk.get("return_data_type", ""))),
        "_colors": {"链路类型": C.TARGET, "明密状态": C.FG_DIM},
    }


def _apply_link_edit(col: str, value: str, lk: dict) -> bool:
    if col == "链路编号":
        lk["link_id"] = int(value)
    elif col == "链路类型":
        lk["link_type"] = _parse_enum(value, _LINK_TYPE, 1)
    elif col == "链路目的地ID":
        lk["dest_id"] = int(value)
    elif col == "链路开始时间":
        lk["link_start"] = _parse_utc(value)
    elif col == "链路结束时间":
        lk["link_end"] = _parse_utc(value)
    elif col == "明密状态":
        lk["encryption"] = _parse_enum(value, _ENC, 0)
    elif col == "数传速率":
        lk["datalink_rate"] = _parse_rate(value)
    elif col == "链路专用任务号":
        lk["task_no"] = int(value)
    elif col == "数传站编号":
        lk["station_id"] = int(value)
    elif col == "数传站经度(°)":
        lk["station_lon"] = float(value)
    elif col == "数传站纬度(°)":
        lk["station_lat"] = float(value)
    elif col == "数传站可见仰角(°)":
        lk["station_elev_angle"] = float(value)
    elif col == "周期链路标识":
        lk["periodic_flag"] = _parse_enum(value, _PFLAG, 0)
    elif col == "周期秒数":
        lk["periodic_seconds"] = int(value)
    elif col == "回传数据类型":
        lk["return_data_type"] = _parse_enum(value, _RET_TYPE, 0)
    else:
        return False
    return True


def create_0c12_panel() -> PacketPanel:
    return PacketPanel(
        hex_title="0C12 数传链路资源报文",
        record_title="链路列表(每记录 41B)",
        count_label="链路数",
        fixed_fields=_0C12_FIXED_FIELDS,
        fixed_derived=_0C12_DERIVED,
        record_columns=_0C12_COLUMNS,
        record_editable=_0C12_EDIT_COLS,
        record_key="links", count_key="link_count",
        parse_fn=parse_0c12, serialize_fn=serialize_0c12,
        default_info_fn=default_0c12_info,
        fmt_fixed_value=_fmt_fixed_common,
        parse_fixed_edit=_parse_fixed_common,
        fmt_record_row=_fmt_link_row,
        apply_record_edit=_apply_link_edit,
        delete_label="删除选中链路")


# ==================== 0C15 数传站址资源 ====================

_0C15_FIXED_FIELDS = [
    ("packet_type", "包类型", "", "0x0C15"),
    ("total_packets", "总包数量", "", "从1开始计"),
    ("sequence_no", "序列号", "", "全局递增,设备上电/复位初始化,每发送一帧加1"),
    ("cur_packet_no", "当前包序号", "", "从1开始计"),
    ("cur_packet_len", "当前包长度", "字节", "从1开始计,12+N*20"),
    ("station_count", "站址资源数量", "", "N,根据数量循环"),
]
_0C15_DERIVED = {"packet_type", "cur_packet_len", "station_count"}

_0C15_COLUMNS = ["序号", "站址编号", "站址经度(°)", "站址纬度(°)",
                 "站址高程(m)", "遮蔽角(°)", "数传速率",
                 "接收方位角1(°)", "接收方位角2(°)", "站址类别", "明密状态"]
_0C15_EDIT_COLS = set(_0C15_COLUMNS) - {"序号"}


def _fmt_azimuth(raw) -> str:
    """接收方位角:原始值 0.1° 单位,65535 表示无效。"""
    try:
        v = int(raw)
    except (TypeError, ValueError):
        return str(raw)
    if v == 65535:
        return "无效(0xFFFF)"
    return f"{v / 10.0:.1f}"


def _parse_azimuth(text: str) -> int:
    text = str(text).strip()
    if "无效" in text or text.upper() in ("0XFFFF", "FFFF"):
        return 65535
    if text.lower().startswith("0x"):
        return int(text, 16)
    return int(round(float(text) * 10))


def _fmt_station_row(i: int, st: dict) -> dict:
    return {
        "序号": i,
        "站址编号": int(st.get("station_id", 0)),
        "站址经度(°)": f"{float(st.get('station_lon', 0)):.6f}",
        "站址纬度(°)": f"{float(st.get('station_lat', 0)):.6f}",
        "站址高程(m)": f"{float(st.get('station_alt', 0)):.1f}",
        "遮蔽角(°)": f"{float(st.get('mask_angle', 10.0)):.1f}",
        "数传速率": _fmt_rate(st.get("datalink_rate", 0xC1)),
        "接收方位角1(°)": _fmt_azimuth(st.get("azimuth1", 0)),
        "接收方位角2(°)": _fmt_azimuth(st.get("azimuth2", 3600)),
        "站址类别": _ST_CATEGORY.get(int(st.get("category", 1)),
                                     str(st.get("category", ""))),
        "明密状态": _ENC.get(int(st.get("encryption", 0)),
                             str(st.get("encryption", ""))),
        "_colors": {"站址类别": C.TARGET, "明密状态": C.FG_DIM},
    }


def _apply_station_edit(col: str, value: str, st: dict) -> bool:
    if col == "站址编号":
        st["station_id"] = int(value)
    elif col == "站址经度(°)":
        st["station_lon"] = float(value)
    elif col == "站址纬度(°)":
        st["station_lat"] = float(value)
    elif col == "站址高程(m)":
        st["station_alt"] = float(value)
    elif col == "遮蔽角(°)":
        st["mask_angle"] = float(value)
    elif col == "数传速率":
        st["datalink_rate"] = _parse_rate(value)
    elif col == "接收方位角1(°)":
        st["azimuth1"] = _parse_azimuth(value)
    elif col == "接收方位角2(°)":
        st["azimuth2"] = _parse_azimuth(value)
    elif col == "站址类别":
        st["category"] = _parse_enum(value, _ST_CATEGORY, 1)
    elif col == "明密状态":
        st["encryption"] = _parse_enum(value, _ENC, 0)
    else:
        return False
    return True


def create_0c15_panel() -> PacketPanel:
    return PacketPanel(
        hex_title="0C15 数传站址资源报文",
        record_title="站址列表(每记录 20B)",
        count_label="站址数",
        fixed_fields=_0C15_FIXED_FIELDS,
        fixed_derived=_0C15_DERIVED,
        record_columns=_0C15_COLUMNS,
        record_editable=_0C15_EDIT_COLS,
        record_key="stations", count_key="station_count",
        parse_fn=parse_0c15, serialize_fn=serialize_0c15,
        default_info_fn=default_0c15_info,
        fmt_fixed_value=_fmt_fixed_common,
        parse_fixed_edit=_parse_fixed_common,
        fmt_record_row=_fmt_station_row,
        apply_record_edit=_apply_station_edit,
        delete_label="删除选中站址")


# ==================== 0B01 星时数据包 ====================

_0B01_FIXED_FIELDS = [
    ("packet_type", "包类型", "", "0x0B01"),
    ("total_packets", "总包数量", "", "从1开始计"),
    ("sequence_no", "序列号", "", "全局递增"),
    ("cur_packet_no", "当前包序号", "", "从1开始计"),
    ("cur_packet_len", "当前包长度", "字节", "16"),
]
_0B01_DERIVED = {"packet_type", "cur_packet_len"}
_0B01_COLUMNS = ["时间整秒(s)", "毫秒(ms)", "对应UTC时间", "对应北京时间"]
_0B01_EDIT_COLS = {"时间整秒(s)", "毫秒(ms)"}


def _wrap_0b01_parse(raw: bytes) -> dict:
    info = parse_0b01(raw)
    ts = int(info.get("time_seconds", 0))
    ms = int(info.get("time_millis", 0))
    info["records"] = [{
        "time_seconds": ts, "time_millis": ms,
        "utc": STK_EPOCH_2009 + timedelta(seconds=ts, milliseconds=ms),
    }]
    info["record_count"] = len(info["records"])
    return info


def _wrap_0b01_serialize(info: dict) -> bytes:
    rec = (info.get("records") or [{}])[0]
    flat = {k: info.get(k) for k in
            ("packet_type", "total_packets", "sequence_no",
             "cur_packet_no", "cur_packet_len")}
    flat["time_seconds"] = rec.get("time_seconds", 0)
    flat["time_millis"] = rec.get("time_millis", 0)
    return serialize_0b01(flat)


def _fmt_0b01_row(i: int, rec: dict) -> dict:
    ts = int(rec.get("time_seconds", 0))
    ms = int(rec.get("time_millis", 0))
    utc = STK_EPOCH_2009 + timedelta(seconds=ts, milliseconds=ms)
    bj = utc + timedelta(hours=8)
    return {
        "时间整秒(s)": ts,
        "毫秒(ms)": ms,
        "对应UTC时间": utc.strftime("%Y-%m-%d %H:%M:%S"),
        "对应北京时间": bj.strftime("%Y-%m-%d %H:%M:%S"),
        "_colors": {"对应北京时间": C.OK, "对应UTC时间": C.FG_DIM},
    }


def _apply_0b01_edit(col: str, value: str, rec: dict) -> bool:
    if col == "时间整秒(s)":
        rec["time_seconds"] = int(value)
    elif col == "毫秒(ms)":
        rec["time_millis"] = int(value)
    else:
        return False
    return True


def create_0b01_panel(parsed_callback=None) -> PacketPanel:
    return PacketPanel(
        hex_title="0B01 星时报文",
        record_title="星时数据(16B)",
        count_label="记录数",
        fixed_fields=_0B01_FIXED_FIELDS,
        fixed_derived=_0B01_DERIVED,
        record_columns=_0B01_COLUMNS,
        record_editable=_0B01_EDIT_COLS,
        record_key="records", count_key="record_count",
        parse_fn=_wrap_0b01_parse, serialize_fn=_wrap_0b01_serialize,
        default_info_fn=lambda: _wrap_0b01_parse(serialize_0b01(default_0b01_info())),
        fmt_fixed_value=_fmt_fixed_common,
        parse_fixed_edit=_parse_fixed_common,
        fmt_record_row=_fmt_0b01_row,
        apply_record_edit=_apply_0b01_edit,
        delete_label="删除记录",
        parsed_callback=parsed_callback)


# ==================== A002 轨道数据包(位置速度) ====================

_A002_FIXED_FIELDS = [
    ("packet_type", "包类型", "", "0xA002"),
    ("total_packets", "总包数量", "", "从1开始计"),
    ("sequence_no", "序列号", "", "全局递增"),
    ("cur_packet_no", "当前包序号", "", "从1开始计"),
    ("cur_packet_len", "当前包长度", "字节", "62"),
]
_A002_DERIVED = {"packet_type", "cur_packet_len", "epoch_seconds"}
_A002_COLUMNS = ["GCGS_X(m)", "GCGS_Y(m)", "GCGS_Z(m)",
                 "GCGS_Vx(m/s)", "GCGS_Vy(m/s)", "GCGS_Vz(m/s)",
                 "J2K_X(m)", "J2K_Y(m)", "J2K_Z(m)",
                 "J2K_Vx(m/s)", "J2K_Vy(m/s)", "J2K_Vz(m/s)"]
_A002_EDIT_COLS = set(_A002_COLUMNS)


def _wrap_a002_parse(raw: bytes) -> dict:
    info = parse_a002(raw)
    info["records"] = [{k: info.get(k) for k in
                        ("gcgs_x", "gcgs_y", "gcgs_z",
                         "gcgs_vx", "gcgs_vy", "gcgs_vz",
                         "j2k_x", "j2k_y", "j2k_z",
                         "j2k_vx", "j2k_vy", "j2k_vz")}]
    info["record_count"] = len(info["records"])
    return info


def _wrap_a002_serialize(info: dict) -> bytes:
    rec = (info.get("records") or [{}])[0]
    flat = {k: info.get(k) for k in
            ("packet_type", "total_packets", "sequence_no",
             "cur_packet_no", "cur_packet_len", "epoch_seconds")}
    for k in ("gcgs_x", "gcgs_y", "gcgs_z",
              "gcgs_vx", "gcgs_vy", "gcgs_vz",
              "j2k_x", "j2k_y", "j2k_z",
              "j2k_vx", "j2k_vy", "j2k_vz"):
        flat[k] = rec.get(k, 0.0)
    return serialize_a002(flat)


def _fmt_a002_row(i: int, rec: dict) -> dict:
    return {
        "GCGS_X(m)": f"{float(rec.get('gcgs_x', 0)):.3f}",
        "GCGS_Y(m)": f"{float(rec.get('gcgs_y', 0)):.3f}",
        "GCGS_Z(m)": f"{float(rec.get('gcgs_z', 0)):.3f}",
        "GCGS_Vx(m/s)": f"{float(rec.get('gcgs_vx', 0)):.3f}",
        "GCGS_Vy(m/s)": f"{float(rec.get('gcgs_vy', 0)):.3f}",
        "GCGS_Vz(m/s)": f"{float(rec.get('gcgs_vz', 0)):.3f}",
        "J2K_X(m)": f"{float(rec.get('j2k_x', 0)):.3f}",
        "J2K_Y(m)": f"{float(rec.get('j2k_y', 0)):.3f}",
        "J2K_Z(m)": f"{float(rec.get('j2k_z', 0)):.3f}",
        "J2K_Vx(m/s)": f"{float(rec.get('j2k_vx', 0)):.3f}",
        "J2K_Vy(m/s)": f"{float(rec.get('j2k_vy', 0)):.3f}",
        "J2K_Vz(m/s)": f"{float(rec.get('j2k_vz', 0)):.3f}",
        "_colors": {"GCGS_X(m)": C.TARGET, "J2K_X(m)": C.TARGET},
    }


def _apply_a002_edit(col: str, value: str, rec: dict) -> bool:
    key_map = {
        "GCGS_X(m)": "gcgs_x", "GCGS_Y(m)": "gcgs_y", "GCGS_Z(m)": "gcgs_z",
        "GCGS_Vx(m/s)": "gcgs_vx", "GCGS_Vy(m/s)": "gcgs_vy",
        "GCGS_Vz(m/s)": "gcgs_vz",
        "J2K_X(m)": "j2k_x", "J2K_Y(m)": "j2k_y", "J2K_Z(m)": "j2k_z",
        "J2K_Vx(m/s)": "j2k_vx", "J2K_Vy(m/s)": "j2k_vy",
        "J2K_Vz(m/s)": "j2k_vz",
    }
    if col in key_map:
        rec[key_map[col]] = float(value)
        return True
    return False


def create_a002_panel() -> PacketPanel:
    return PacketPanel(
        hex_title="A002 轨道数据报文(位置速度)",
        record_title="位置速度数据(62B)",
        count_label="记录数",
        fixed_fields=_A002_FIXED_FIELDS,
        fixed_derived=_A002_DERIVED,
        record_columns=_A002_COLUMNS,
        record_editable=_A002_EDIT_COLS,
        record_key="records", count_key="record_count",
        parse_fn=_wrap_a002_parse, serialize_fn=_wrap_a002_serialize,
        default_info_fn=lambda: _wrap_a002_parse(serialize_a002(default_a002_info())),
        fmt_fixed_value=_fmt_fixed_common,
        parse_fixed_edit=_parse_fixed_common,
        fmt_record_row=_fmt_a002_row,
        apply_record_edit=_apply_a002_edit,
        delete_label="删除记录",
        epoch_key="epoch_seconds")


# ==================== A012 轨道根数包 ====================

_A012_FIXED_FIELDS = [
    ("packet_type", "包类型", "", "0xA012"),
    ("total_packets", "总包数量", "", "从1开始计"),
    ("sequence_no", "序列号", "", "全局递增"),
    ("cur_packet_no", "当前包序号", "", "从1开始计"),
    ("cur_packet_len", "当前包长度", "字节", "62"),
]
_A012_DERIVED = {"packet_type", "cur_packet_len", "epoch_seconds"}
_A012_COLUMNS = ["半长轴(km)", "偏心率", "倾角(°)", "升交点赤经(°)",
                 "近地点幅角(°)", "平近点角(°)"]
_A012_EDIT_COLS = set(_A012_COLUMNS)


def _wrap_a012_parse(raw: bytes) -> dict:
    info = parse_a012(raw)
    info["records"] = [{k: info.get(k) for k in
                        ("semi_major_axis", "eccentricity", "inclination",
                         "raan", "arg_perigee", "mean_anomaly")}]
    info["record_count"] = len(info["records"])
    return info


def _wrap_a012_serialize(info: dict) -> bytes:
    rec = (info.get("records") or [{}])[0]
    flat = {k: info.get(k) for k in
            ("packet_type", "total_packets", "sequence_no",
             "cur_packet_no", "cur_packet_len", "epoch_seconds")}
    for k in ("semi_major_axis", "eccentricity", "inclination",
              "raan", "arg_perigee", "mean_anomaly"):
        flat[k] = rec.get(k, 0.0)
    return serialize_a012(flat)


def _fmt_a012_row(i: int, rec: dict) -> dict:
    return {
        "半长轴(km)": f"{float(rec.get('semi_major_axis', 0)):.3f}",
        "偏心率": f"{float(rec.get('eccentricity', 0)):.6f}",
        "倾角(°)": f"{float(rec.get('inclination', 0)):.3f}",
        "升交点赤经(°)": f"{float(rec.get('raan', 0)):.3f}",
        "近地点幅角(°)": f"{float(rec.get('arg_perigee', 0)):.3f}",
        "平近点角(°)": f"{float(rec.get('mean_anomaly', 0)):.3f}",
        "_colors": {"半长轴(km)": C.TARGET, "倾角(°)": C.TARGET},
    }


def _apply_a012_edit(col: str, value: str, rec: dict) -> bool:
    key_map = {
        "半长轴(km)": "semi_major_axis", "偏心率": "eccentricity",
        "倾角(°)": "inclination", "升交点赤经(°)": "raan",
        "近地点幅角(°)": "arg_perigee", "平近点角(°)": "mean_anomaly",
    }
    if col in key_map:
        rec[key_map[col]] = float(value)
        return True
    return False


def create_a012_panel() -> PacketPanel:
    return PacketPanel(
        hex_title="A012 轨道根数报文",
        record_title="轨道六根数(62B)",
        count_label="记录数",
        fixed_fields=_A012_FIXED_FIELDS,
        fixed_derived=_A012_DERIVED,
        record_columns=_A012_COLUMNS,
        record_editable=_A012_EDIT_COLS,
        record_key="records", count_key="record_count",
        parse_fn=_wrap_a012_parse, serialize_fn=_wrap_a012_serialize,
        default_info_fn=lambda: _wrap_a012_parse(serialize_a012(default_a012_info())),
        fmt_fixed_value=_fmt_fixed_common,
        parse_fixed_edit=_parse_fixed_common,
        fmt_record_row=_fmt_a012_row,
        apply_record_edit=_apply_a012_edit,
        delete_label="删除记录",
        epoch_key="epoch_seconds")


# ==================== 0802 固存状态信息包 ====================

_0802_FIXED_FIELDS = [
    ("packet_type", "包类型", "", "0x0802"),
    ("total_packets", "总包数量", "", "最大900个文件,按16文件/包分片"),
    ("sequence_no", "序列号", "", "全局递增"),
    ("cur_packet_no", "当前包序号", "", "从1开始计"),
    ("cur_packet_len", "当前包长度", "字节", "12+N*30"),
    ("file_count", "本包固存文件数量", "", "N,每包最多16"),
]
_0802_DERIVED = {"packet_type", "cur_packet_len", "file_count"}

_0802_COLUMNS = ["序号", "文件ID", "固存任务号", "固存文件号", "文件大小(块)",
                 "记录起始时间", "记录结束时间", "文件断点", "文件类型",
                 "回放状态", "结束页地址", "压缩比", "回传优先级",
                 "成像任务编号", "目标优先级", "网格优先级"]
_0802_EDIT_COLS = set(_0802_COLUMNS) - {"序号"}

_FILE_TYPE = {0x01: "载荷原始图像", 0x02: "处理后数据",
              0x03: "小固存数据", 0x04: "星间数据"}
_PLAYBACK_STATUS = {0x00: "未回放", 0xFF: "已全部回放", 0xAA: "部分回放"}
_COMP_RATIO = {0x00: "无损", 0x02: "2:1", 0x04: "4:1", 0x08: "8:1"}
_RETURN_PRIO = {0x01: "I级", 0x02: "II级", 0x03: "III级",
                0x04: "IV级", 0x05: "V级"}


def _fmt_0802_row(i: int, f: dict) -> dict:
    from datetime import datetime, timedelta, timezone as _tz
    _epoch = datetime(2009, 1, 1, tzinfo=_tz.utc)

    def _sec_to_bj(sec: int) -> str:
        if sec <= 0:
            return "—"
        try:
            dt = _epoch + timedelta(seconds=sec) + timedelta(hours=8)
            return f"{sec} ({dt.strftime('%Y-%m-%d %H:%M:%S')})"
        except Exception:
            return str(sec)

    return {
        "序号": i,
        "文件ID": int(f.get("file_id", 0)),
        "固存任务号": int(f.get("storage_task_no", 0)),
        "固存文件号": int(f.get("storage_file_no", 0)),
        "文件大小(块)": int(f.get("file_size_blocks", 0)),
        "记录起始时间": _sec_to_bj(int(f.get("record_start", 0))),
        "记录结束时间": _sec_to_bj(int(f.get("record_end", 0))),
        "文件断点": int(f.get("breakpoint", 0)),
        "文件类型": _FILE_TYPE.get(int(f.get("file_type", 1)),
                                   f"0x{int(f.get('file_type',0)):02X}"),
        "回放状态": _PLAYBACK_STATUS.get(int(f.get("playback_status", 0)),
                                         f"0x{int(f.get('playback_status',0)):02X}"),
        "结束页地址": int(f.get("end_page_addr", 0)),
        "压缩比": _COMP_RATIO.get(int(f.get("compression_ratio", 4)),
                                  f"0x{int(f.get('compression_ratio',0)):02X}"),
        "回传优先级": _RETURN_PRIO.get(int(f.get("return_priority", 2)),
                                       f"0x{int(f.get('return_priority',0)):02X}"),
        "成像任务编号": int(f.get("imaging_task_no", 0)),
        "目标优先级": int(f.get("target_priority", 0)),
        "网格优先级": int(f.get("grid_priority", 0)),
        "_colors": {"文件类型": C.TARGET, "回放状态": C.FG_DIM,
                    "记录起始时间": C.ACCENT, "记录结束时间": C.ACCENT},
    }


def _apply_0802_edit(col: str, value: str, f: dict) -> bool:
    from datetime import datetime, timedelta, timezone as _tz
    _epoch = datetime(2009, 1, 1, tzinfo=_tz.utc)

    def _bj_to_sec(s: str) -> int:
        """北京时间字符串或秒数 → 2009历元秒。"""
        s = s.strip()
        # 格式: "561164400 (2026-10-14 07:00:00)" → 提取秒数部分
        if "(" in s:
            s = s.split("(")[0].strip()
        try:
            # 纯数字直接转
            return int(s)
        except ValueError:
            pass
        try:
            dt = datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
            dt = dt.replace(tzinfo=_tz(timedelta(hours=8)))
            return int((dt - _epoch).total_seconds())
        except Exception:
            return 0

    key_map = {
        "文件ID": ("file_id", int),
        "固存任务号": ("storage_task_no", int),
        "固存文件号": ("storage_file_no", int),
        "文件大小(块)": ("file_size_blocks", int),
        "记录起始时间": ("record_start", _bj_to_sec),
        "记录结束时间": ("record_end", _bj_to_sec),
        "文件断点": ("breakpoint", int),
        "结束页地址": ("end_page_addr", int),
        "成像任务编号": ("imaging_task_no", int),
        "目标优先级": ("target_priority", int),
        "网格优先级": ("grid_priority", int),
    }
    if col in key_map:
        k, conv = key_map[col]
        f[k] = conv(value)
        return True
    if col == "文件类型":
        f["file_type"] = _parse_enum(value, _FILE_TYPE, 1)
        return True
    if col == "回放状态":
        f["playback_status"] = _parse_enum(value, _PLAYBACK_STATUS, 0)
        return True
    if col == "压缩比":
        f["compression_ratio"] = _parse_enum(value, _COMP_RATIO, 4)
        return True
    if col == "回传优先级":
        f["return_priority"] = _parse_enum(value, _RETURN_PRIO, 2)
        return True
    return False


def create_0802_panel() -> PacketPanel:
    return PacketPanel(
        hex_title="0802 固存状态信息报文",
        record_title="固存文件列表(每记录 30B)",
        count_label="文件数",
        fixed_fields=_0802_FIXED_FIELDS,
        fixed_derived=_0802_DERIVED,
        record_columns=_0802_COLUMNS,
        record_editable=_0802_EDIT_COLS,
        record_key="files", count_key="file_count",
        parse_fn=parse_0802, serialize_fn=serialize_0802,
        default_info_fn=default_0802_info,
        fmt_fixed_value=_fmt_fixed_common,
        parse_fixed_edit=_parse_fixed_common,
        fmt_record_row=_fmt_0802_row,
        apply_record_edit=_apply_0802_edit,
        delete_label="删除选中文件")
