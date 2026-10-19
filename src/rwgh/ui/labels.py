"""UI 显示层的中文标签、分组与数值格式化。

与解析层解耦:这里只决定"字段在界面上叫什么、怎么显示",
不改变 ParsedPacket 内的英文字段名。
"""
from __future__ import annotations

from datetime import timedelta

from ..models.orbit import STK_EPOCH_2009
from .theme import C

# ---------- 包类型 ----------

# packet_type -> (中文名, 徽章色)
PACKET_TYPES: dict[int, tuple[str, str]] = {
    0x0B01: ("星时数据包", C.PKT_TIME),
    0xA012: ("轨道根数包", C.PKT_ELEM),
    0xA002: ("轨道数据包", C.PKT_DATA),
    0x5B5B: ("可见性结果报文", C.PKT_REPORT),
}

# 格式名 -> 中文名
FORMAT_NAMES: dict[str, str] = {
    "stk_time": "星时数据包",
    "stk_orbit_elements": "轨道根数包",
    "stk_orbit_data": "轨道数据包",
    "visibility_report": "可见性结果报文",
}

# ---------- 字段分组与中文名 ----------
# group: 表头 / 时间 / 地固坐标系(GCGS) / J2000坐标系 / 轨道根数 / 可见性
FIELD_GROUPS: dict[str, str] = {}
FIELD_LABELS: dict[str, str] = {}
FIELD_UNITS: dict[str, str] = {}


def _reg(group: str, name: str, label: str, unit: str = "") -> None:
    FIELD_GROUPS[name] = group
    FIELD_LABELS[name] = label
    FIELD_UNITS[name] = unit


# 统一报文头
for _n, _l in (("packet_type", "包类型"),
               ("total_packets", "总包数"),
               ("sequence_no", "序列号"),
               ("cur_packet_no", "当前包号"),
               ("cur_packet_len", "当前包长")):
    _reg("统一报文头", _n, _l, "字节" if _n == "cur_packet_len" else "")

# 时间
_reg("时间", "time_seconds", "星时整秒", "s")
_reg("时间", "time_millis", "星时毫秒", "ms")
_reg("时间", "epoch_seconds", "历元整秒", "s")

# 轨道根数
_reg("轨道根数", "semi_major_axis", "半长轴", "km")
_reg("轨道根数", "eccentricity", "偏心率", "")
_reg("轨道根数", "inclination", "轨道倾角", "°")
_reg("轨道根数", "raan", "升交点赤经", "°")
_reg("轨道根数", "arg_perigee", "近地点幅角", "°")
_reg("轨道根数", "mean_anomaly", "平近点角", "°")
for i in range(1, 7):
    _reg("保留字段", f"reserved{i}", f"保留字 {i}", "")

# 地固坐标系 GCGS
for ax in ("x", "y", "z"):
    _reg("地固坐标系(GCGS)", f"gcgs_{ax}", f"地固位置 {ax.upper()}", "m")
for ax in ("x", "y", "z"):
    _reg("地固坐标系(GCGS)", f"gcgs_v{ax}", f"地固速度 V{ax.upper()}", "m/s")

# J2000 惯性系
for ax in ("x", "y", "z"):
    _reg("J2000惯性系", f"j2k_{ax}", f"J2000位置 {ax.upper()}", "m")
for ax in ("x", "y", "z"):
    _reg("J2000惯性系", f"j2k_v{ax}", f"J2000速度 V{ax.upper()}", "m/s")

# 可见性结果报文
_reg("可见性结果", "satellite_id", "卫星编号", "")
_reg("可见性结果", "target_id", "目标编号", "")
_reg("可见性结果", "aos_time", "进站时刻", "s")
_reg("可见性结果", "los_time", "出站时刻", "s")
_reg("可见性结果", "max_el", "最大仰角", "°")


# ---------- 数值显示 ----------

def field_label(name: str) -> str:
    """英文字段名 -> 中文(未知字段保留原名)。"""
    return FIELD_LABELS.get(name, name)


def field_unit(name: str) -> str:
    return FIELD_UNITS.get(name, "")


def field_group(name: str) -> str:
    return FIELD_GROUPS.get(name, "其他")


# 分组显示顺序与配色
GROUP_ORDER = ["统一报文头", "时间", "轨道根数", "地固坐标系(GCGS)",
               "J2000惯性系", "可见性结果", "保留字段", "其他"]
GROUP_COLORS = {
    "统一报文头": C.FG_FAINT,
    "时间": C.PKT_TIME,
    "轨道根数": C.PKT_ELEM,
    "地固坐标系(GCGS)": C.WARN,
    "J2000惯性系": C.PKT_DATA,
    "可见性结果": C.PKT_REPORT,
    "保留字段": C.FG_FAINT,
    "其他": C.FG_DIM,
}


def packet_type_info(ptype: int) -> tuple[str, str]:
    """包类型值 -> (中文名, 徽章色),未知类型返回灰色'未知包(0x....)'。"""
    info = PACKET_TYPES.get(int(ptype))
    if info:
        return info
    return (f"未知包 0x{int(ptype):04X}", C.PKT_UNKNOWN)


def fmt_hex_16(raw: bytes) -> str:
    """原始帧 -> 等宽 hex(前 16 字节)。"""
    text = raw[:16].hex(" ").upper()
    if len(raw) > 16:
        text += " …"
    return text


def utc_from_2009(seconds: float) -> str:
    """自 2009-01-01 UTC 起整秒 -> 'MM-DD HH:MM:SS' 展示串。"""
    dt = STK_EPOCH_2009 + timedelta(seconds=float(seconds))
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def utc_clock(seconds: float) -> str:
    """只取时分秒(表格紧凑列用)。"""
    dt = STK_EPOCH_2009 + timedelta(seconds=float(seconds))
    return dt.strftime("%m-%d %H:%M:%S")


def fmt_value(name: str, value) -> str:
    """按字段语义格式化展示值。"""
    if value is None:
        return "—"
    # 包类型:hex
    if name == "packet_type":
        return f"0x{int(value):04X}"
    # 时间秒:附加可读 UTC
    if name in ("time_seconds", "epoch_seconds"):
        try:
            return f"{int(value)}  ({utc_clock(value)})"
        except (TypeError, ValueError, OverflowError):
            return str(value)
    if name in ("time_millis",):
        return f"{int(value)}"
    # 角度
    if name in ("inclination", "raan", "arg_perigee", "mean_anomaly", "max_el"):
        return f"{float(value):.3f}"
    if name == "semi_major_axis":
        return f"{float(value):.3f}"
    if name == "eccentricity":
        return f"{float(value):.6f}"
    # 位置/速度
    if name.startswith(("gcgs_", "j2k_")):
        return f"{float(value):,.2f}"
    if name == "cur_packet_len":
        return f"{int(value)} B"
    return str(value)


def packet_summary(fmt_name: str, fields: dict) -> str:
    """报文流的'关键内容'摘要(中文,一行)。"""
    try:
        if fmt_name == "stk_time":
            secs = fields.get("time_seconds", 0)
            return f"星时 {utc_clock(secs)}"
        if fmt_name == "stk_orbit_elements":
            return ("半长轴 {sma:.2f} km · 倾角 {inc:.2f}° · 偏心率 {ecc:.4f}"
                    .format(sma=float(fields.get("semi_major_axis", 0)),
                            inc=float(fields.get("inclination", 0)),
                            ecc=float(fields.get("eccentricity", 0))))
        if fmt_name == "stk_orbit_data":
            return ("J2000 位置  X={x:,.1f}  Y={y:,.1f}  Z={z:,.1f} m"
                    .format(x=float(fields.get("j2k_x", 0)),
                            y=float(fields.get("j2k_y", 0)),
                            z=float(fields.get("j2k_z", 0))))
        if fmt_name == "visibility_report":
            return ("卫星 {sid} → 目标 {tid} · 最大仰角 {el:.2f}°"
                    .format(sid=fields.get("satellite_id", 0),
                            tid=fields.get("target_id", 0),
                            el=float(fields.get("max_el", 0))))
    except (TypeError, ValueError):
        pass
    return "、".join(f"{field_label(k)}={v}" for k, v in
                    list(fields.items())[:4])
