"""真实 STK 数据 -> 统一二进制报文帧编码。

把从 STK COM 取到的物理量(UTC 时间、J2K/Fixed 位置速度、六根数、地面点)
按 config/formats 下的 FormatSpec 组帧为 0x0B01/0xA012/0xA002,
与 FrameParser.parse 严格对称(定点 scale 由 build 反向换算)。

产出帧可直接 publish(Topics.RAW_FRAME),后续解析/可见性/指令/比对链路
与 TCP 实推或 Mock 注入完全一致。
"""
from __future__ import annotations

import struct
from datetime import datetime, timedelta, timezone

from ..models.orbit import STK_EPOCH_2009
from ..parsing.parser import FrameParser
from ..parsing.registry import FormatRegistry

# UTCG 月份缩写
_MONTHS = {
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
    "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
}
_MONTH_INV = {v: k for k, v in _MONTHS.items()}


def parse_utcg(s: str) -> datetime:
    """解析 STK UTCG 字符串,如 '1 Oct 2026 02:00:00.000000000' -> datetime(UTC)。"""
    parts = s.strip().split()
    # 形如 ["1","Oct","2026","02:00:00.000000000"]
    day = int(parts[0])
    month = _MONTHS[parts[1][:3]]
    year = int(parts[2])
    hms = parts[3]
    hh, mm, rest = hms.split(":")
    if "." in rest:
        ss_str, frac = rest.split(".", 1)
        micro = int((frac + "000000")[:6])
    else:
        ss_str, micro = rest, 0
    return datetime(year, month, day, int(hh), int(mm), int(ss_str),
                    micro, tzinfo=timezone.utc)


def format_utcg(dt: datetime) -> str:
    """datetime -> STK UTCG 字符串(毫秒精度,DP 接受)。"""
    return (f"{dt.day} {_MONTH_INV[dt.month]} {dt.year} "
            f"{dt.hour:02d}:{dt.minute:02d}:{dt.second:02d}.{dt.microsecond // 1000:03d}")


def seconds_since_2009(dt: datetime) -> int:
    """datetime -> 自 2009-01-01 UTC 起的整秒(报文 epoch_seconds/time_seconds)。"""
    return int((dt - STK_EPOCH_2009).total_seconds())


class StkPacketBuilder:
    """按 STK 实测物理量组帧。线程安全要求:在单个 STK 工作线程内使用。"""

    def __init__(self, registry: FormatRegistry, parser: FrameParser) -> None:
        self._parser = parser
        self._spec_time = registry.get("stk_time")
        self._spec_elem = registry.get("stk_orbit_elements")
        self._spec_data = registry.get("stk_orbit_data")
        self._seq = 0

    def _next_seq(self) -> int:
        self._seq = (self._seq + 1) & 0xFFFF
        return self._seq

    def _header(self, total_len: int) -> dict:
        return {
            "total_packets": 1,
            "sequence_no": self._next_seq(),
            "cur_packet_no": 1,
            "cur_packet_len": total_len,
        }

    # ---------- 0x0B01 星时 ----------

    def time_frame(self, dt: datetime) -> bytes:
        """星时包:整秒 + 毫秒。"""
        values = self._header(self._spec_time.total_length)
        values.update({
            "time_seconds": seconds_since_2009(dt),
            "time_millis": dt.microsecond // 1000,
        })
        return self._parser.build(self._spec_time, values)

    # ---------- 0xA012 轨道根数 ----------

    def elements_frame(self, dt: datetime, semi_major_km: float,
                       eccentricity: float, inclination_deg: float,
                       raan_deg: float, arg_perigee_deg: float,
                       mean_anomaly_deg: float) -> bytes:
        """轨道根数包(角度 deg,半长轴 km)。保留字段填 0。"""
        values = self._header(self._spec_elem.total_length)
        values.update({
            "epoch_seconds": seconds_since_2009(dt),
            "semi_major_axis": semi_major_km,
            "eccentricity": eccentricity,
            "inclination": inclination_deg,
            "raan": raan_deg,
            "arg_perigee": arg_perigee_deg,
            "mean_anomaly": mean_anomaly_deg,
        })
        return self._parser.build(self._spec_elem, values)

    # ---------- 0xA002 轨道数据 ----------

    def orbit_data_frame(self, dt: datetime,
                         fixed_pos_km: tuple[float, float, float],
                         fixed_vel_km_s: tuple[float, float, float],
                         j2k_pos_km: tuple[float, float, float],
                         j2k_vel_km_s: tuple[float, float, float]) -> bytes:
        """轨道数据包:GCGS(Fixed/地固)+ J2000(ICRF)位置速度。

        STK DP 单位 km / km/s,报文物理量单位 m / m/s,这里换算;
        FormatSpec.scale 的反向缩放由 parser.build 完成。
        """
        fx, fy, fz = fixed_pos_km
        fvx, fvy, fvz = fixed_vel_km_s
        jx, jy, jz = j2k_pos_km
        jvx, jvy, jvz = j2k_vel_km_s
        values = self._header(self._spec_data.total_length)
        values.update({
            "epoch_seconds": seconds_since_2009(dt),
            # km -> m
            "gcgs_x": fx * 1000.0, "gcgs_y": fy * 1000.0, "gcgs_z": fz * 1000.0,
            "gcgs_vx": fvx * 1000.0, "gcgs_vy": fvy * 1000.0,
            "gcgs_vz": fvz * 1000.0,
            "j2k_x": jx * 1000.0, "j2k_y": jy * 1000.0, "j2k_z": jz * 1000.0,
            "j2k_vx": jvx * 1000.0, "j2k_vy": jvy * 1000.0,
            "j2k_vz": jvz * 1000.0,
        })
        return self._parser.build(self._spec_data, values)

    # ---------- 0x3101 目标输入(常规管控成像任务_点目标) ----------

    def target_input_frame(self, targets: list, *,
                           task_id: int = 142,
                           earliest: datetime | None = None,
                           latest: datetime | None = None,
                           priority: int = 20,
                           imaging_type: int = 11) -> bytes:
        """3101 目标输入包:将 STK 目标点填入报文。

        格式(与 Excel 数据包格式定义严格一致):
          10B 头 + 36B 任务固定区 + 87B*N 目标区
        每个目标记录 87B:
          元任务编号(4) + 元任务最早开始时间(4) + 元任务最晚结束时间(4)
          + 目标编号(3) + 目标类型属性(1) + 目标优先级(1) + 成像模式(1)
          + 角点有效个数(1) + 角点1-8 经纬度(8×2×4=64)
          + 前视俯仰角(1) + 后视俯仰角(1) + 成像时长(2)
        经纬度当量 1E-6°,有符号整型。
        点目标角点数=1,其余角点填 0。
        """
        n = len(targets)
        if n == 0:
            raise ValueError("至少需要 1 个目标")
        if earliest is None:
            earliest = STK_EPOCH_2009
        if latest is None:
            latest = earliest + timedelta(hours=2)
        t_earliest = int((earliest - STK_EPOCH_2009).total_seconds())
        t_latest = int((latest - STK_EPOCH_2009).total_seconds())
        # 实际公式: 46 + 87*N(Excel 备注里 "46+27*N" 系笔误)
        total_len = 46 + 87 * n

        buf = bytearray()
        # 统一报文头(10B)
        buf += struct.pack(">HHHHH", 0x3101, 1, self._next_seq(), 1, total_len)
        # 任务固定区(36B)
        buf += struct.pack(">I", task_id)           # 任务编号
        buf += struct.pack(">I", t_earliest)        # 任务最早开始时间
        buf += struct.pack(">I", t_latest)           # 任务最晚结束时间
        buf += struct.pack(">B", priority)           # 任务优先级
        buf += struct.pack(">B", 2)                  # 载荷数据回传优先级 II级
        buf += struct.pack(">B", imaging_type)       # 成像任务类型 11=点目标
        buf += struct.pack(">B", 4)                  # 成像数据压缩比 4:1
        buf += struct.pack(">B", 213)                # 数传任务类型(星上自主数传2)
        buf += struct.pack(">B", 2)                  # 回传数据类型
        buf += struct.pack(">B", 0xC1)               # 数传速率
        buf += struct.pack(">B", 1)                  # 明密状态
        buf += struct.pack(">B", 0)                  # 周期任务标识
        buf += struct.pack(">B", 0)                  # 周期任务成像次数
        buf += struct.pack(">I", 0)                  # 周期最小间隔
        buf += struct.pack(">I", 0)                  # 周期最大间隔
        buf += struct.pack(">B", 1)                  # 星上智能处理开关
        buf += struct.pack(">B", 5)                  # 切块大小 5km
        buf += struct.pack(">B", 8)                  # 切块压缩比_可见光
        buf += struct.pack(">B", 8)                  # 切块压缩比_红外
        buf += struct.pack(">B", 2)                  # 输出产品级别
        buf += struct.pack(">B", n)                  # 目标数量

        # 每个目标(87B): 与 Excel 字段定义一致
        for i, t in enumerate(targets):
            tid = self._target_id_int(t.id)
            lat_i = int(round(t.lat * 1e6))
            lon_i = int(round(t.lon * 1e6))
            # 元任务时间窗:
            #   最早开始时间 = 初始轨道时间(t_earliest)
            #   最晚结束时间 = 初始轨道时间 + 2小时(t_latest)
            # 每个目标的星下点时间在窗内均匀分布(模拟连续过境)
            if n > 1:
                subpoint = t_earliest + int(
                    i * (t_latest - t_earliest) / max(n - 1, 1))
            else:
                subpoint = t_earliest
            meta_early = t_earliest                 # 元任务最早开始时间 = 初始轨道时间
            meta_late = t_latest                    # 元任务最晚结束时间 = 初始轨道时间+2h
            buf += struct.pack(">I", 10 + i)          # 目标元任务编号
            buf += struct.pack(">I", meta_early)      # 元任务最早开始时间
            buf += struct.pack(">I", meta_late)        # 元任务最晚结束时间
            buf += tid.to_bytes(3, "big")               # 目标编号(3B)
            buf += struct.pack(">B", 0)                # 目标类型属性 0=点目标
            buf += struct.pack(">B", 10)               # 目标优先级
            buf += struct.pack(">B", 1)                # 成像模式 1=可见光
            buf += struct.pack(">B", 1)                # 角点有效个数(点目标=1)
            buf += struct.pack(">i", lon_i)            # 角点1_经度(scale 1E-6)
            buf += struct.pack(">i", lat_i)            # 角点1_纬度(scale 1E-6)
            # 角点2-8 经纬度(点目标默认填0,共14×4=56B)
            for _ in range(14):
                buf += struct.pack(">i", 0)
            buf += struct.pack(">B", 200)              # 前视俯仰角(当量0.1,默认200)
            buf += struct.pack(">B", 200)              # 后视俯仰角(当量0.1,默认200)
            buf += struct.pack(">H", 10)               # 成像时长(秒,点目标默认10s)

        return bytes(buf)

    @staticmethod
    def _target_id_int(tid: str) -> int:
        """目标编号字符串 -> 整数(如 '11-100' -> 11100, 'kashi_01' -> 1)。"""
        try:
            return int(tid.replace("-", "").replace("_", ""))
        except ValueError:
            return abs(hash(tid)) & 0xFFFFFF


def parse_3101(raw: bytes) -> dict:
    """解析 0x3101 目标输入包 -> dict(含目标列表,完整 87B/目标结构)。

    与 Excel 数据包格式定义严格一致:每个目标记录 87B,包含
    8 个角点经纬度、前/后视俯仰角、成像时长。
    """
    if len(raw) < 46:
        raise ValueError(f"3101 包长度不足: {len(raw)} < 46")
    ptype, total_pkts, seq, pkt_no, pkt_len = struct.unpack_from(
        ">HHHHH", raw, 0)
    if ptype != 0x3101:
        raise ValueError(f"非 3101 包: 0x{ptype:04X}")

    off = 10
    task_id, t_early, t_late = struct.unpack_from(">III", raw, off)
    off += 12
    (priority, payload_pri, img_type, compression, dt_type, ret_type,
     dt_rate, encryption, periodic, periodic_cnt) = struct.unpack_from(
        ">BBBBBBBBBB", raw, off)
    off += 10
    pmin, pmax = struct.unpack_from(">II", raw, off)
    off += 8
    (obp, cut_size, cut_vis, cut_ir, out_level, tgt_cnt) = struct.unpack_from(
        ">BBBBBB", raw, off)
    off += 6
    # 目标区:每个 87B
    targets = []
    for k in range(tgt_cnt):
        if off + 87 > len(raw):
            break
        meta_id, meta_e, meta_l = struct.unpack_from(">III", raw, off)
        off += 12
        tid_raw = raw[off:off + 3]
        off += 3
        tid_int = (tid_raw[0] << 16) | (tid_raw[1] << 8) | tid_raw[2]
        (ttype, tprio, tmode, corner_cnt) = struct.unpack_from(
            ">BBBB", raw, off)
        off += 4
        # 角点1-8 经纬度(16 个有符号整型,每个 4B)
        corners = []
        for ci in range(8):
            lon_i, lat_i = struct.unpack_from(">ii", raw, off)
            off += 8
            corners.append((lon_i / 1e6, lat_i / 1e6))
        # 前视俯仰角、后视俯仰角、成像时长
        fwd_pitch, aft_pitch, img_dur = struct.unpack_from(
            ">BBH", raw, off)
        off += 4
        targets.append({
            "meta_task_id": meta_id,
            "meta_earliest": meta_e,
            "meta_latest": meta_l,
            "target_id": tid_int,
            "target_type": ttype,
            "target_priority": tprio,
            "imaging_mode": tmode,
            "corner_count": corner_cnt,
            "corners": corners,          # [(lon, lat), ...] 8 个
            "lon": corners[0][0],         # 角点1 经度(向后兼容)
            "lat": corners[0][1],         # 角点1 纬度(向后兼容)
            "forward_pitch": fwd_pitch,
            "backward_pitch": aft_pitch,
            "imaging_duration": img_dur,
        })

    return {
        "_raw_bytes": raw,
        "packet_type": ptype,
        "total_packets": total_pkts,
        "sequence_no": seq,
        "cur_packet_no": pkt_no,
        "cur_packet_len": pkt_len,
        "task_id": task_id,
        "task_earliest": t_early,
        "task_latest": t_late,
        "priority": priority,
        "payload_priority": payload_pri,
        "imaging_type": img_type,
        "compression": compression,
        "datalink_type": dt_type,
        "return_data_type": ret_type,
        "datalink_rate": dt_rate,
        "encryption": encryption,
        "periodic_flag": periodic,
        "periodic_count": periodic_cnt,
        "periodic_min_interval": pmin,
        "periodic_max_interval": pmax,
        "onboard_processing": obp,
        "cut_size": cut_size,
        "cut_compression_vis": cut_vis,
        "cut_compression_ir": cut_ir,
        "output_product_level": out_level,
        "target_count": tgt_cnt,
        "targets": targets,
    }


def serialize_3101(info: dict) -> bytes:
    """将解析后的 dict 反向序列化为 0x3101 报文字节。

    与 parse_3101 互逆,用于表格编辑后重建报文。
    每个目标记录 87B(8 角点+前后视+时长),总长度 46+87*N。
    """
    targets = info.get("targets") or []
    n = len(targets)
    total_len = 46 + 87 * n

    buf = bytearray()
    # 统一报文头(10B)
    buf += struct.pack(">HHHHH",
                       int(info.get("packet_type", 0x3101)),
                       int(info.get("total_packets", 1)),
                       int(info.get("sequence_no", 1)),
                       int(info.get("cur_packet_no", 1)),
                       total_len)
    # 任务固定区(36B)
    buf += struct.pack(">I", int(info.get("task_id", 0)))
    buf += struct.pack(">I", int(info.get("task_earliest", 0)))
    buf += struct.pack(">I", int(info.get("task_latest", 0)))
    buf += struct.pack(">B", int(info.get("priority", 20)))
    buf += struct.pack(">B", int(info.get("payload_priority", 2)))
    buf += struct.pack(">B", int(info.get("imaging_type", 11)))
    buf += struct.pack(">B", int(info.get("compression", 4)))
    buf += struct.pack(">B", int(info.get("datalink_type", 213)))
    buf += struct.pack(">B", int(info.get("return_data_type", 2)))
    buf += struct.pack(">B", int(info.get("datalink_rate", 0xC1)))
    buf += struct.pack(">B", int(info.get("encryption", 1)))
    buf += struct.pack(">B", int(info.get("periodic_flag", 0)))
    buf += struct.pack(">B", int(info.get("periodic_count", 0)))
    buf += struct.pack(">I", int(info.get("periodic_min_interval", 0)))
    buf += struct.pack(">I", int(info.get("periodic_max_interval", 0)))
    buf += struct.pack(">B", int(info.get("onboard_processing", 1)))
    buf += struct.pack(">B", int(info.get("cut_size", 5)))
    buf += struct.pack(">B", int(info.get("cut_compression_vis", 8)))
    buf += struct.pack(">B", int(info.get("cut_compression_ir", 8)))
    buf += struct.pack(">B", int(info.get("output_product_level", 2)))
    buf += struct.pack(">B", n)  # 目标数量

    # 每个目标(87B)
    for t in targets:
        corners = t.get("corners") or [(0.0, 0.0)] * 8
        while len(corners) < 8:
            corners.append((0.0, 0.0))
        buf += struct.pack(">I", int(t.get("meta_task_id", 0)))
        buf += struct.pack(">I", int(t.get("meta_earliest", 0)))
        buf += struct.pack(">I", int(t.get("meta_latest", 0)))
        tid = int(t.get("target_id", 0))
        buf += tid.to_bytes(3, "big")
        buf += struct.pack(">B", int(t.get("target_type", 0)))
        buf += struct.pack(">B", int(t.get("target_priority", 0)))
        buf += struct.pack(">B", int(t.get("imaging_mode", 0)))
        buf += struct.pack(">B", int(t.get("corner_count", 1)))
        # 8 角点经纬度(scale 1E-6)
        for lon, lat in corners[:8]:
            buf += struct.pack(">i", int(round(float(lon) * 1e6)))
            buf += struct.pack(">i", int(round(float(lat) * 1e6)))
        buf += struct.pack(">B", int(t.get("forward_pitch", 200)))
        buf += struct.pack(">B", int(t.get("backward_pitch", 200)))
        buf += struct.pack(">H", int(t.get("imaging_duration", 10)))

    return bytes(buf)


# ==================== 0x0C12 数传链路资源 ====================
# 12B 头 + 41B×K 链路记录 + 4B 预留;当前包长度 = 12+41*K+4
# 每链路 41B: 链路编号(2)+链路类型(1)+链路目的地ID(2)+链路开始时间(4)
#   +链路结束时间(4)+明密状态(1)+数传速率(1)+链路专用任务号(4)
#   +数传站编号(2)+数传站经度(4,1E-6°)+数传站纬度(4,1E-6°)
#   +数传站可见仰角(1,0.1°)+周期链路标识(1)+周期秒数(4)
#   +回传数据类型(1)+预留(3)+预留(2)

def parse_0c12(raw: bytes) -> dict:
    """解析 0x0C12 数传链路资源包。"""
    if len(raw) < 16:
        raise ValueError(f"0C12 包长度不足: {len(raw)} < 16")
    (ptype, total, seq, pno, plen, link_cnt) = struct.unpack_from(
        ">HHHHHH", raw, 0)
    if ptype != 0x0C12:
        raise ValueError(f"非 0C12 包: 0x{ptype:04X}")
    result = {"_raw_bytes": raw}
    off = 12
    links = []
    for _ in range(link_cnt):
        if off + 41 > len(raw):
            break
        (link_id, link_type, dest_id, t_start, t_end, enc, rate,
         task_no, stn_id, lon_i, lat_i, elev, pflag, psec,
         ret_type) = struct.unpack_from(">HBHIIBBIHiibBIB", raw, off)
        off += 41
        links.append({
            "link_id": link_id,
            "link_type": link_type,
            "dest_id": dest_id,
            "link_start": t_start,
            "link_end": t_end,
            "encryption": enc,
            "datalink_rate": rate,
            "task_no": task_no,
            "station_id": stn_id,
            "station_lon": lon_i / 1e6,
            "station_lat": lat_i / 1e6,
            "station_elev_angle": elev / 10.0,
            "periodic_flag": pflag,
            "periodic_seconds": psec,
            "return_data_type": ret_type,
        })
    result.update({
        "packet_type": ptype, "total_packets": total, "sequence_no": seq,
        "cur_packet_no": pno, "cur_packet_len": plen,
        "link_count": link_cnt, "links": links,
    })
    return result


def serialize_0c12(info: dict) -> bytes:
    """将 dict 反向序列化为 0x0C12 报文(与 parse_0c12 互逆)。"""
    links = info.get("links") or []
    n = len(links)
    total_len = 12 + 41 * n + 4
    buf = bytearray()
    buf += struct.pack(">HHHHHH",
                       int(info.get("packet_type", 0x0C12)),
                       int(info.get("total_packets", 1)),
                       int(info.get("sequence_no", 1)),
                       int(info.get("cur_packet_no", 1)),
                       total_len, n)
    for lk in links:
        buf += struct.pack(
            ">HBHIIBBIHiibBIB3x2x",
            int(lk.get("link_id", 0)),
            int(lk.get("link_type", 1)),
            int(lk.get("dest_id", 0)),
            int(lk.get("link_start", 0)),
            int(lk.get("link_end", 0)),
            int(lk.get("encryption", 0)),
            int(lk.get("datalink_rate", 0xC1)),
            int(lk.get("task_no", 0)),
            int(lk.get("station_id", 0)),
            int(round(float(lk.get("station_lon", 0)) * 1e6)),
            int(round(float(lk.get("station_lat", 0)) * 1e6)),
            int(round(float(lk.get("station_elev_angle", 10.0)) * 10)),
            int(lk.get("periodic_flag", 0)),
            int(lk.get("periodic_seconds", 0)),
            int(lk.get("return_data_type", 0)))
    buf += b"\x00" * 4  # 尾部预留
    return bytes(buf)


def default_0c12_info() -> dict:
    """默认 0C12 数据(取自 Excel 数传链路资源 sheet 测试数据前两条)。"""
    return {
        "packet_type": 0x0C12, "total_packets": 1, "sequence_no": 1,
        "cur_packet_no": 1, "cur_packet_len": 98, "link_count": 2,
        "links": [
            {"link_id": 1, "link_type": 1, "dest_id": 56,
             "link_start": 557468169, "link_end": 557468469,
             "encryption": 0, "datalink_rate": 0xC1, "task_no": 156,
             "station_id": 1, "station_lon": 117.08, "station_lat": 24.1413,
             "station_elev_angle": 10.0, "periodic_flag": 0,
             "periodic_seconds": 0, "return_data_type": 0},
            {"link_id": 2, "link_type": 1, "dest_id": 1,
             "link_start": 557467800, "link_end": 557467950,
             "encryption": 0, "datalink_rate": 0xC1, "task_no": 0,
             "station_id": 2, "station_lon": 86.2902, "station_lat": 34.6325,
             "station_elev_angle": 10.0, "periodic_flag": 0,
             "periodic_seconds": 0, "return_data_type": 0},
        ],
    }


# ==================== 0x0C15 数传站址资源 ====================
# 12B 头 + 20B×N 站址记录;当前包长度 = 12+N*20
# 每站址 20B: 站址编号(2)+站址经度(4,1E-6°)+站址纬度(4,1E-6°)
#   +站址高程(2,0.1m)+遮蔽角(1,0.1°)+数传速率(1)
#   +接收方位角1(2,0.1°)+接收方位角2(2,0.1°)+站址类别(1)+明密状态(1)

def parse_0c15(raw: bytes) -> dict:
    """解析 0x0C15 数传站址资源包。"""
    if len(raw) < 12:
        raise ValueError(f"0C15 包长度不足: {len(raw)} < 12")
    (ptype, total, seq, pno, plen, st_cnt) = struct.unpack_from(
        ">HHHHHH", raw, 0)
    if ptype != 0x0C15:
        raise ValueError(f"非 0C15 包: 0x{ptype:04X}")
    result = {"_raw_bytes": raw}
    off = 12
    stations = []
    for _ in range(st_cnt):
        if off + 20 > len(raw):
            break
        (sid, lon_i, lat_i, alt_i, mask, rate, az1, az2, cat,
         enc) = struct.unpack_from(">HiihBBHHBB", raw, off)
        off += 20
        stations.append({
            "station_id": sid,
            "station_lon": lon_i / 1e6,
            "station_lat": lat_i / 1e6,
            "station_alt": alt_i / 10.0,
            "mask_angle": mask / 10.0,
            "datalink_rate": rate,
            "azimuth1": az1,      # 0.1° 单位原始值,65535=无效
            "azimuth2": az2,
            "category": cat,
            "encryption": enc,
        })
    result.update({
        "packet_type": ptype, "total_packets": total, "sequence_no": seq,
        "cur_packet_no": pno, "cur_packet_len": plen,
        "station_count": st_cnt, "stations": stations,
    })
    return result


def serialize_0c15(info: dict) -> bytes:
    """将 dict 反向序列化为 0x0C15 报文(与 parse_0c15 互逆)。"""
    stations = info.get("stations") or []
    n = len(stations)
    total_len = 12 + 20 * n
    buf = bytearray()
    buf += struct.pack(">HHHHHH",
                       int(info.get("packet_type", 0x0C15)),
                       int(info.get("total_packets", 1)),
                       int(info.get("sequence_no", 1)),
                       int(info.get("cur_packet_no", 1)),
                       total_len, n)
    for st in stations:
        buf += struct.pack(
            ">HiihBBHHBB",
            int(st.get("station_id", 0)),
            int(round(float(st.get("station_lon", 0)) * 1e6)),
            int(round(float(st.get("station_lat", 0)) * 1e6)),
            int(round(float(st.get("station_alt", 0)) * 10)),
            int(round(float(st.get("mask_angle", 10.0)) * 10)),
            int(st.get("datalink_rate", 0xC1)),
            int(st.get("azimuth1", 0)),
            int(st.get("azimuth2", 3600)),
            int(st.get("category", 1)),
            int(st.get("encryption", 0)))
    return bytes(buf)


def default_0c15_info() -> dict:
    """默认 0C15 数据(取自 Excel 数传站址资源 sheet 测试数据前两条)。"""
    return {
        "packet_type": 0x0C15, "total_packets": 1, "sequence_no": 1,
        "cur_packet_no": 1, "cur_packet_len": 52, "station_count": 2,
        "stations": [
            {"station_id": 1, "station_lon": 75.7014, "station_lat": 39.4689,
             "station_alt": 0.0, "mask_angle": 10.0, "datalink_rate": 0xC1,
             "azimuth1": 0, "azimuth2": 3600, "category": 2, "encryption": 0},
            {"station_id": 2, "station_lon": 103.064, "station_lat": 24.89,
             "station_alt": 1931.0, "mask_angle": 10.0, "datalink_rate": 0xC1,
             "azimuth1": 65535, "azimuth2": 65535, "category": 2,
             "encryption": 0},
        ],
    }


# ==================== 0x0802 固存状态信息包 ====================
# 12B 固定头 + 30B×N 文件记录
# 固定头: 包类型(2)+总包数量(2)+序列号(2)+当前包序号(2)+当前包长度(2)
#   +本包固存文件数量(2)
# 每条记录 30B:
#   文件ID(1)+固存任务号(2)+固存文件号(1)+文件大小块数(2)
#   +记录起始时间(4)+记录结束时间(4)+文件断点(2)+文件类型(1)
#   +文件回放状态(1)+结束页地址(1)+压缩比(1)+载荷回传优先级(1)
#   +成像任务编号(4)+目标优先级(1)+网格优先级(2)+保留(2)

_0802_REC_FMT = ">BH B H II H B B B B B I B H H"


def parse_0802(raw: bytes) -> dict:
    """解析 0x0802 固存状态信息包。"""
    if len(raw) < 12:
        raise ValueError(f"0802 包长度不足: {len(raw)} < 12")
    (ptype, total, seq, pno, plen, file_cnt) = struct.unpack_from(
        ">HHHHHH", raw, 0)
    if ptype != 0x0802:
        raise ValueError(f"非 0802 包: 0x{ptype:04X}")
    result = {"_raw_bytes": raw}
    off = 12
    files = []
    for _ in range(file_cnt):
        if off + 30 > len(raw):
            break
        (fid, task_no, file_no, size_blk, rec_start, rec_end,
         breakpoint, ftype, playback, end_page, comp_ratio,
         prio, img_task_no, tgt_prio, grid_prio, reserved) = \
            struct.unpack_from(_0802_REC_FMT, raw, off)
        off += 30
        files.append({
            "file_id": fid,
            "storage_task_no": task_no,
            "storage_file_no": file_no,
            "file_size_blocks": size_blk,
            "record_start": rec_start,
            "record_end": rec_end,
            "breakpoint": breakpoint,
            "file_type": ftype,
            "playback_status": playback,
            "end_page_addr": end_page,
            "compression_ratio": comp_ratio,
            "return_priority": prio,
            "imaging_task_no": img_task_no,
            "target_priority": tgt_prio,
            "grid_priority": grid_prio,
            "reserved": reserved,
        })
    result.update({
        "packet_type": ptype, "total_packets": total, "sequence_no": seq,
        "cur_packet_no": pno, "cur_packet_len": plen,
        "file_count": file_cnt, "files": files,
    })
    return result


def serialize_0802(info: dict) -> bytes:
    """将 dict 反向序列化为 0x0802 报文(与 parse_0802 互逆)。"""
    files = info.get("files") or []
    n = len(files)
    total_len = 12 + 30 * n
    buf = bytearray()
    buf += struct.pack(">HHHHHH",
                       int(info.get("packet_type", 0x0802)),
                       int(info.get("total_packets", 1)),
                       int(info.get("sequence_no", 1)),
                       int(info.get("cur_packet_no", 1)),
                       total_len, n)
    for f in files:
        buf += struct.pack(
            _0802_REC_FMT,
            int(f.get("file_id", 0)),
            int(f.get("storage_task_no", 0)),
            int(f.get("storage_file_no", 0)),
            int(f.get("file_size_blocks", 0)),
            int(f.get("record_start", 0)),
            int(f.get("record_end", 0)),
            int(f.get("breakpoint", 0)),
            int(f.get("file_type", 1)),
            int(f.get("playback_status", 0)),
            int(f.get("end_page_addr", 0)),
            int(f.get("compression_ratio", 4)),
            int(f.get("return_priority", 2)),
            int(f.get("imaging_task_no", 0)),
            int(f.get("target_priority", 0)),
            int(f.get("grid_priority", 0)),
            int(f.get("reserved", 0)),
        )
    return bytes(buf)


def default_0802_info() -> dict:
    """默认 0802 固存状态包数据(取自 Excel 固存状态信息 sheet 测试数据)。

    包含 2 条文件记录:一条原始图像(文件号 1)、一条处理数据(文件号 126),
    与 0F11 输出的固存文件号范围[1,125]/[126,255]对应。
    """
    return {
        "packet_type": 0x0802, "total_packets": 1, "sequence_no": 1,
        "cur_packet_no": 1, "cur_packet_len": 72, "file_count": 2,
        "files": [
            # 原始图像数据(文件号1, 类型0x01)
            {"file_id": 1, "storage_task_no": 61, "storage_file_no": 1,
             "file_size_blocks": 13578, "record_start": 557468169,
             "record_end": 557468469, "breakpoint": 0, "file_type": 0x01,
             "playback_status": 0x00, "end_page_addr": 0,
             "compression_ratio": 0x04, "return_priority": 0x02,
             "imaging_task_no": 0, "target_priority": 0,
             "grid_priority": 0, "reserved": 0},
            # 处理数据(文件号126, 类型0x02)
            {"file_id": 2, "storage_task_no": 61, "storage_file_no": 126,
             "file_size_blocks": 153, "record_start": 557468169,
             "record_end": 557468469, "breakpoint": 0, "file_type": 0x02,
             "playback_status": 0x00, "end_page_addr": 0,
             "compression_ratio": 0x04, "return_priority": 0x02,
             "imaging_task_no": 0, "target_priority": 0,
             "grid_priority": 0, "reserved": 0},
        ],
    }


def build_0c12_from_window(link_start: int, link_end: int,
                           station_id: int = 1,
                           station_lon: float = 117.08,
                           station_lat: float = 24.1413) -> bytes:
    """根据指定时间窗口构造 0C12 数传链路资源报文。"""
    info = {
        "packet_type": 0x0C12, "total_packets": 1, "sequence_no": 1,
        "cur_packet_no": 1,
        "links": [{
            "link_id": 1, "link_type": 1, "dest_id": 56,
            "link_start": link_start, "link_end": link_end,
            "encryption": 0, "datalink_rate": 0xC1, "task_no": 156,
            "station_id": station_id,
            "station_lon": station_lon, "station_lat": station_lat,
        }],
    }
    return serialize_0c12(info)


def build_0802_from_window(task_earliest: int, task_latest: int) -> bytes:
    """根据 3101 任务窗口动态构造 0802 固存状态信息报文。

    固存文件记录时间与成像窗口一致,文件号 1(原始)/126(处理)。
    """
    info = {
        "packet_type": 0x0802, "total_packets": 1, "sequence_no": 1,
        "cur_packet_no": 1, "cur_packet_len": 72, "file_count": 2,
        "files": [
            {"file_id": 1, "storage_task_no": 61, "storage_file_no": 1,
             "file_size_blocks": 13578,
             "record_start": task_earliest, "record_end": task_latest,
             "breakpoint": 0, "file_type": 0x01,
             "playback_status": 0x00, "end_page_addr": 0,
             "compression_ratio": 0x04, "return_priority": 0x02,
             "imaging_task_no": 0, "target_priority": 0,
             "grid_priority": 0, "reserved": 0},
            {"file_id": 2, "storage_task_no": 61, "storage_file_no": 126,
             "file_size_blocks": 153,
             "record_start": task_earliest, "record_end": task_latest,
             "breakpoint": 0, "file_type": 0x02,
             "playback_status": 0x00, "end_page_addr": 0,
             "compression_ratio": 0x04, "return_priority": 0x02,
             "imaging_task_no": 0, "target_priority": 0,
             "grid_priority": 0, "reserved": 0},
        ],
    }
    return serialize_0802(info)


# ==================== 0x0F11 待执行成像任务规划方案 ====================
# 10B 头(无计数字段) + 26B 任务区 + 77B×N 目标记录(V2 实测)
# 任务区: 元任务编号(2)+任务编号(4)+任务优先级(1)+载荷数据回传优先级(1)
#   +成像任务类型(1)+载荷模式(1)+成像数据压缩比(1)+固存任务号(2)
#   +数传任务类型(1)+回传数据类型(1)+数传速率(1)+明密状态(1)
#   +星上智能处理开关(1)+切块大小(1)+切块压缩比_可见光(1)
#   +切块压缩比_红外(1)+星上处理输出产品级别(1)+任务来源(1)
#   +记录标识(1)+下传标识(1)+目标数量(1)
# 目标记录 76B: 目标编号(3)+网格编号(8)+目标类型属性(1)+目标优先级(1)
#   +网格优先级(2)+目标经度(4,1E-6°)+目标纬度(4,1E-6°)+区域半径(2,1km)
#   +条带编号(1)+姿态机动开始时间(4+2)+姿态机动持续时间(2)
#   +成像开始时间(4+2)+成像结束时间(4+2)+偏航角(4)+俯仰角(4)+滚动角(4)
#   +离轴角(4,1E-6°)+太阳高度角(1,1°)+原始数据固存文件号(1)
#   +处理数据固存文件号(1)+原始数据固存文件大小(3,0.1MB)
#   +处理数据固存文件大小(3,0.1MB)+尾部(1B 0x00 + 5B 0xAA 保留)

_0F11_TASK_FMT = ">HIBBBBBHBBBBBBBBBBBBB"   # 26B: H I 5B H 13B
# V2 DLL 实测目标记录为 77B(尾部 = 1B(0x00) + 5B(0xAA) 共6B),
# 344=36+4×77;08版按76B,本软件对接 V2 以真实输出为准。
_0F11_RECORD_FMT = ">3s8sBBHiiHBIHHIHIHiiiIBBB3s3s6s"  # 77B
_0F11_RECORD_LEN = 77


def parse_0f11(raw: bytes) -> dict:
    """解析 0x0F11 待执行成像任务规划方案包。"""
    if len(raw) < 36:
        raise ValueError(f"0F11 包长度不足: {len(raw)} < 36")
    (ptype, total, seq, pno, plen) = struct.unpack_from(">HHHHH", raw, 0)
    if ptype != 0x0F11:
        raise ValueError(f"非 0F11 包: 0x{ptype:04X}")
    task = struct.unpack_from(_0F11_TASK_FMT, raw, 10)
    (meta_no, task_no, prio, ret_prio, img_type, payload_mode, comp,
     store_no, dl_type, ret_type, dl_rate, enc, smart, block, comp_vis,
     comp_ir, prod_lvl, source, rec_flag, dl_flag, tgt_cnt) = task
    off = 36
    targets = []
    for _ in range(tgt_cnt):
        if off + _0F11_RECORD_LEN > len(raw):
            break
        r = struct.unpack_from(_0F11_RECORD_FMT, raw, off)
        off += _0F11_RECORD_LEN
        (tid, grid, tattr, tprio, grid_prio, lon_i, lat_i, radius, strip,
         man_s, man_s_ms, man_dur, img_s, img_s_ms, img_e, img_e_ms,
         yaw, pitch, roll, off_axis, sun_el, f_raw, f_proc,
         sz_raw, sz_proc, _rsv) = r
        targets.append({
            "target_id": int.from_bytes(tid, "big"),
            "grid_no": grid.decode("ascii", "ignore").strip("\xff") or
            int.from_bytes(grid, "big"),
            "target_attr": tattr,
            "target_priority": tprio,
            "grid_priority": grid_prio,
            "lon": lon_i / 1e6, "lat": lat_i / 1e6,
            "radius_km": radius, "strip_no": strip,
            "maneuver_start": man_s, "maneuver_ms": man_s_ms,
            "maneuver_duration": man_dur,
            "imaging_start": img_s, "imaging_start_ms": img_s_ms,
            "imaging_end": img_e, "imaging_end_ms": img_e_ms,
            "yaw": yaw / 1e6, "pitch": pitch / 1e6, "roll": roll / 1e6,
            "off_axis": off_axis / 1e6, "sun_elev": sun_el,
            "raw_file_no": f_raw, "proc_file_no": f_proc,
            "raw_file_size": int.from_bytes(sz_raw, "big"),
            "proc_file_size": int.from_bytes(sz_proc, "big"),
        })
    return {
        "packet_type": ptype, "total_packets": total, "sequence_no": seq,
        "cur_packet_no": pno, "cur_packet_len": plen,
        "meta_task_no": meta_no, "task_no": task_no,
        "priority": prio, "ret_priority": ret_prio,
        "imaging_type": img_type, "payload_mode": payload_mode,
        "compression": comp, "storage_task_no": store_no,
        "datalink_type": dl_type, "return_data_type": ret_type,
        "datalink_rate": dl_rate, "encryption": enc,
        "smart_process": smart, "block_size": block,
        "block_comp_vis": comp_vis, "block_comp_ir": comp_ir,
        "product_level": prod_lvl, "task_source": source,
        "record_flag": rec_flag, "download_flag": dl_flag,
        "target_count": tgt_cnt, "targets": targets,
    }


def serialize_0f11(info: dict) -> bytes:
    """将 dict 反向序列化为 0x0F11 报文(与 parse_0f11 互逆)。"""
    targets = info.get("targets") or []
    n = len(targets)
    total_len = 36 + _0F11_RECORD_LEN * n
    buf = bytearray()
    buf += struct.pack(">HHHHH",
                       int(info.get("packet_type", 0x0F11)),
                       int(info.get("total_packets", 1)),
                       int(info.get("sequence_no", 1)),
                       int(info.get("cur_packet_no", 1)), total_len)
    buf += struct.pack(_0F11_TASK_FMT,
                       int(info.get("meta_task_no", 10)),
                       int(info.get("task_no", 245678)),
                       int(info.get("priority", 1)),
                       int(info.get("ret_priority", 2)),
                       int(info.get("imaging_type", 11)),
                       int(info.get("payload_mode", 1)),
                       int(info.get("compression", 1)),
                       int(info.get("storage_task_no", 61)),
                       int(info.get("datalink_type", 21)),
                       int(info.get("return_data_type", 0)),
                       int(info.get("datalink_rate", 0xC1)),
                       int(info.get("encryption", 0)),
                       int(info.get("smart_process", 1)),
                       int(info.get("block_size", 5)),
                       int(info.get("block_comp_vis", 8)),
                       int(info.get("block_comp_ir", 8)),
                       int(info.get("product_level", 2)),
                       int(info.get("task_source", 2)),
                       int(info.get("record_flag", 1)),
                       int(info.get("download_flag", 0)),
                       n)
    for t in targets:
        grid = t.get("grid_no", 0xFFFFFFFFFFFFFFFF)
        grid_bytes = (int(grid).to_bytes(8, "big")
                      if isinstance(grid, int) else
                      str(grid).encode("ascii")[:8].ljust(8, b"\xff"))
        yaw = int(round(float(t.get("yaw", 0)) * 1e6))
        pitch = int(round(float(t.get("pitch", 35.0)) * 1e6))
        roll = int(round(float(t.get("roll", 23.456789)) * 1e6))
        off_axis = int(round(float(t.get("off_axis", 0)) * 1e6))
        if not t.get("off_axis"):
            off_axis = int(round((pitch * pitch + roll * roll) ** 0.5))
        buf += struct.pack(
            _0F11_RECORD_FMT,
            int(t.get("target_id", 0)).to_bytes(3, "big"),
            grid_bytes,
            int(t.get("target_attr", 0)),
            int(t.get("target_priority", 1)),
            int(t.get("grid_priority", 0xFFFF)),
            int(round(float(t.get("lon", 0)) * 1e6)),
            int(round(float(t.get("lat", 0)) * 1e6)),
            int(t.get("radius_km", 0)),
            int(t.get("strip_no", 1)),
            int(t.get("maneuver_start", 0)),
            int(t.get("maneuver_ms", 0)),
            int(t.get("maneuver_duration", 219)),
            int(t.get("imaging_start", 0)),
            int(t.get("imaging_start_ms", 0)),
            int(t.get("imaging_end", 0)),
            int(t.get("imaging_end_ms", 0)),
            yaw, pitch, roll, off_axis,
            int(t.get("sun_elev", 35)),
            int(t.get("raw_file_no", 1)),
            int(t.get("proc_file_no", 126)),
            int(t.get("raw_file_size", 13578)).to_bytes(3, "big"),
            int(t.get("proc_file_size", 153)).to_bytes(3, "big"),
            b"\x00" + b"\xAA" * 5)   # V2 尾部 6B: 1B(0x00)+5B(0xAA)
    return bytes(buf)


# ==================== 0x0F22 待执行数传任务规划方案 ====================
# 10B 头 + 38B 任务区 + N×文件记录
# 任务区: 元任务编号(2)+数传任务类型(1)+链路编号(2)+链路类型(1)
#   +链路目的地ID(2)+回放速率(1)+明密状态(1)+数传站编号(2)
#   +数传站经度(4,1E-6°)+数传站纬度(4,1E-6°)+跟踪开始时间(4)
#   +跟踪结束时间(4)+数传开始时间(4)+数传结束时间(4)+回放文件数量(2)
# 文件记录定义 23B: 固存任务号(2)+固存文件号(1)+成像任务编号(4)
#   +载荷数据回传优先级(1)+目标优先级(1)+网格优先级(2)
#   +回放开始时间(4)+回放结束时间(4)+目标元任务编号(4)
# 实际DLL输出可能使用15B/23B/25B等不同记录长度,parse_0f22会自动检测

_0F22_TASK_FMT = ">HBHBHBBHiiIIIIH"   # 38B
_0F22_FILE_FMT = ">HBIBBHIII"          # 23B(完整定义)
_0F22_FILE_FMT_SHORT = ">HBIBBHII"     # 15B(无回放结束时间和目标元任务编号)
_0F22_TASK_AREA_LEN = 48              # 10B头 + 38B任务区


def parse_0f22(raw: bytes) -> dict:
    """解析 0x0F22 待执行数传任务规划方案包。

    自动检测文件记录长度:根据包长度和文件数量计算,
    支持15B(短格式)、23B(标准格式)、25B(带padding)等。
    """
    if len(raw) < _0F22_TASK_AREA_LEN:
        raise ValueError(f"0F22 包长度不足: {len(raw)} < "
                         f"{_0F22_TASK_AREA_LEN}")
    (ptype, total, seq, pno, plen) = struct.unpack_from(">HHHHH", raw, 0)
    if ptype != 0x0F22:
        raise ValueError(f"非 0F22 包: 0x{ptype:04X}")
    task = struct.unpack_from(_0F22_TASK_FMT, raw, 10)
    (meta_no, dl_type, link_id, link_type, dest_id, rate, enc, stn_id,
     lon_i, lat_i, trk_s, trk_e, dl_s, dl_e, file_cnt) = task

    # 自动检测记录长度
    rec_len = 23  # 默认标准格式
    if file_cnt > 0:
        remaining = len(raw) - _0F22_TASK_AREA_LEN
        detected = remaining / file_cnt
        if detected == int(detected) and 15 <= detected <= 32:
            rec_len = int(detected)

    off = _0F22_TASK_AREA_LEN
    files = []
    for _ in range(file_cnt):
        if off + rec_len > len(raw):
            break
        if rec_len == 23:
            f = struct.unpack_from(_0F22_FILE_FMT, raw, off)
            (store_no, file_no, img_no, ret_prio, t_prio, g_prio,
             pb_s, pb_e, t_meta) = f
        elif rec_len == 15:
            f = struct.unpack_from(_0F22_FILE_FMT_SHORT, raw, off)
            (store_no, file_no, img_no, ret_prio, t_prio, g_prio,
             pb_s) = f
            pb_e, t_meta = 0, 0
        else:
            # 其他长度:按23B解析,多余字节跳过
            f = struct.unpack_from(_0F22_FILE_FMT, raw, off)
            (store_no, file_no, img_no, ret_prio, t_prio, g_prio,
             pb_s, pb_e, t_meta) = f
        off += rec_len
        files.append({
            "storage_task_no": store_no, "file_no": file_no,
            "imaging_task_no": img_no, "ret_priority": ret_prio,
            "target_priority": t_prio, "grid_priority": g_prio,
            "playback_start": pb_s, "playback_end": pb_e,
            "target_meta_task": t_meta,
        })
    return {
        "packet_type": ptype, "total_packets": total, "sequence_no": seq,
        "cur_packet_no": pno, "cur_packet_len": plen,
        "meta_task_no": meta_no, "datalink_type": dl_type,
        "link_id": link_id, "link_type": link_type, "dest_id": dest_id,
        "playback_rate": rate, "encryption": enc,
        "station_id": stn_id, "station_lon": lon_i / 1e6,
        "station_lat": lat_i / 1e6,
        "track_start": trk_s, "track_end": trk_e,
        "datalink_start": dl_s, "datalink_end": dl_e,
        "file_count": file_cnt, "files": files,
    }


def serialize_0f22(info: dict) -> bytes:
    """将 dict 反向序列化为 0x0F22 报文(与 parse_0f22 互逆)。

    序列化时使用标准23B格式(与Excel数据包格式定义一致)。
    """
    files = info.get("files") or []
    n = len(files)
    total_len = _0F22_TASK_AREA_LEN + 23 * n
    buf = bytearray()
    buf += struct.pack(">HHHHH",
                       int(info.get("packet_type", 0x0F22)),
                       int(info.get("total_packets", 1)),
                       int(info.get("sequence_no", 1)),
                       int(info.get("cur_packet_no", 1)), total_len)
    buf += struct.pack(_0F22_TASK_FMT,
                       int(info.get("meta_task_no", 123)),
                       int(info.get("datalink_type", 211)),
                       int(info.get("link_id", 1)),
                       int(info.get("link_type", 1)),
                       int(info.get("dest_id", 56)),
                       int(info.get("playback_rate", 0xC1)),
                       int(info.get("encryption", 1)),
                       int(info.get("station_id", 1)),
                       int(round(float(info.get("station_lon", 0)) * 1e6)),
                       int(round(float(info.get("station_lat", 0)) * 1e6)),
                       int(info.get("track_start", 0)),
                       int(info.get("track_end", 0)),
                       int(info.get("datalink_start", 0)),
                       int(info.get("datalink_end", 0)),
                       n)
    for f in files:
        buf += struct.pack(_0F22_FILE_FMT,
                           int(f.get("storage_task_no", 61)),
                           int(f.get("file_no", 1)),
                           int(f.get("imaging_task_no", 123)),
                           int(f.get("ret_priority", 2)),
                           int(f.get("target_priority", 0xFF)),
                           int(f.get("grid_priority", 2)),
                           int(f.get("playback_start", 0)),
                           int(f.get("playback_end", 0)),
                           int(f.get("target_meta_task", 0)))
    return bytes(buf)


# ==================== 0x0F33 成像任务规划结果反馈 ====================
# 12B 头(含任务数量) + 70B×N 任务记录
# 任务记录 70B: 任务编号(4)+目标编号(8)+规划结果状态字(1)+目标点经度(4)
#   +目标点纬度(4)+可见时间窗口前沿(4)+可见窗口后沿(4)+机动开始时刻(4)
#   +机动结束时刻(4)+成像开始时刻(4)+成像结束时刻(4)+滚动角(4,1E-6°)
#   +俯仰角(4,1E-6°)+偏航角(4,1E-6°)+任务来源(1)+冲突的目标编号(8)+保留(4)

_0F33_TASK_FMT = ">IQBiiIIIIIIiiiBQI"   # 70B

# ---- 0F33 规划结果状态字语义(以《数据包》Excel 协议为准,并经 V2 DLL 实测核对)----
# 0F33 是“每个候选可见窗口一条”,同一目标可有多条。实测 33 条中:
#   0x00×21 成像规划成功(有成像时刻)→ 与 21 条 0F11 条带一一对应
#   0x09×1  成像结束晚于窗口结束(有成像时刻但落选,不出 0F11)
#   0x0A×10 计算机动时间失败(有可见窗、成像时刻为0,不出 0F11)
#   0x07×1  不可见(无可见窗)
F33_STATUS_IMAGING = frozenset({0x00})   # 仅 0x00 入选并产出 0F11
F33_STATUS_INVISIBLE = frozenset({0x07})  # 完全不可见(无窗)
F33_STATUS_TEXT = {
    0x00: "成像规划成功",
    0x01: "单圈成像时长不满足(7min)",
    0x02: "连续可见间隔不满足(360s)",
    0x03: "冲突消解失败",
    0x04: "电量约束判定失败",
    0x05: "固存约束判定失败",
    0x06: "未知原因",
    0x07: "不可见",
    0x08: "计算过顶时间失败",
    0x09: "成像结束晚于窗口结束",
    0x0A: "计算机动时间失败",
}


def f33_status_text(status: int) -> str:
    """0F33 状态字 → 中文文案(未知状态保守显示原值)。"""
    s = int(status)
    return F33_STATUS_TEXT.get(s, f"未知状态(0x{s:02X})")


def f33_window_visible(task: dict) -> bool:
    """该条 0F33 记录是否存在可见窗口(以可见窗时间非0为准)。"""
    return int(task.get("window_start", 0) or 0) > 0 or \
        int(task.get("window_end", 0) or 0) > 0

# ---- 0F44 数传规划结果状态字(沿用 0x00=成功)----
F44_STATUS_IMAGING = frozenset({0x00})
F44_STATUS_TEXT = {0x00: "可见·已规划", 0x07: "不可见"}


def f44_status_text(status: int) -> str:
    s = int(status)
    return F44_STATUS_TEXT.get(s, f"未知状态(0x{s:02X})")



def parse_0f33(raw: bytes) -> dict:
    """解析 0x0F33 成像任务规划结果反馈包。"""
    if len(raw) < 12:
        raise ValueError(f"0F33 包长度不足: {len(raw)} < 12")
    (ptype, total, seq, pno, plen, cnt) = struct.unpack_from(">HHHHHH",
                                                             raw, 0)
    if ptype != 0x0F33:
        raise ValueError(f"非 0F33 包: 0x{ptype:04X}")
    off = 12
    tasks = []
    for _ in range(cnt):
        if off + 70 > len(raw):
            break
        t = struct.unpack_from(_0F33_TASK_FMT, raw, off)
        off += 70
        (task_no, tgt_no, status, lon_i, lat_i, win_s, win_e, man_s,
         man_e, img_s, img_e, roll, pitch, yaw, source, conflict,
         _rsv) = t
        tasks.append({
            "task_no": task_no,
            "target_no": tgt_no,
            "status": status,
            "lon": lon_i / 1e6, "lat": lat_i / 1e6,
            "window_start": win_s, "window_end": win_e,
            "maneuver_start": man_s, "maneuver_end": man_e,
            "imaging_start": img_s, "imaging_end": img_e,
            "roll": roll / 1e6, "pitch": pitch / 1e6, "yaw": yaw / 1e6,
            "task_source": source, "conflict_target": conflict,
        })
    return {
        "packet_type": ptype, "total_packets": total, "sequence_no": seq,
        "cur_packet_no": pno, "cur_packet_len": plen,
        "task_count": cnt, "tasks": tasks,
    }


def serialize_0f33(info: dict) -> bytes:
    """将 dict 反向序列化为 0x0F33 报文(与 parse_0f33 互逆)。"""
    tasks = info.get("tasks") or []
    n = len(tasks)
    total_len = 12 + 70 * n
    buf = bytearray()
    buf += struct.pack(">HHHHHH",
                       int(info.get("packet_type", 0x0F33)),
                       int(info.get("total_packets", 1)),
                       int(info.get("sequence_no", 1)),
                       int(info.get("cur_packet_no", 1)), total_len, n)
    for t in tasks:
        buf += struct.pack(_0F33_TASK_FMT,
                           int(t.get("task_no", 0)),
                           int(t.get("target_no", 0)),
                           int(t.get("status", 0)),
                           int(round(float(t.get("lon", 0)) * 1e6)),
                           int(round(float(t.get("lat", 0)) * 1e6)),
                           int(t.get("window_start", 0)),
                           int(t.get("window_end", 0)),
                           int(t.get("maneuver_start", 0)),
                           int(t.get("maneuver_end", 0)),
                           int(t.get("imaging_start", 0)),
                           int(t.get("imaging_end", 0)),
                           int(round(float(t.get("roll", 0)) * 1e6)),
                           int(round(float(t.get("pitch", 0)) * 1e6)),
                           int(round(float(t.get("yaw", 0)) * 1e6)),
                           int(t.get("task_source", 2)),
                           int(t.get("conflict_target", 0)),
                           0)
    return bytes(buf)


# ==================== 0x0F44 数传任务规划结果反馈 ====================
# 12B 头(含任务数量) + 31B×N 任务记录
# 任务记录 31B: 任务编号(4)+元任务编号(2)+链路编号(2)+链路类型(1)
#   +链路目的地ID(2)+规划结果状态字(1)+数传开始时刻(4)+数传结束时刻(4)
#   +数传任务类型(1)+传输文件数量(2)+保留(8,全0)

_0F44_TASK_FMT = ">IHHBHBIIBH8s"   # 31B


def parse_0f44(raw: bytes) -> dict:
    """解析 0x0F44 数传任务规划结果反馈包。"""
    if len(raw) < 12:
        raise ValueError(f"0F44 包长度不足: {len(raw)} < 12")
    (ptype, total, seq, pno, plen, cnt) = struct.unpack_from(">HHHHHH",
                                                             raw, 0)
    if ptype != 0x0F44:
        raise ValueError(f"非 0F44 包: 0x{ptype:04X}")
    off = 12
    tasks = []
    for _ in range(cnt):
        if off + 31 > len(raw):
            break
        t = struct.unpack_from(_0F44_TASK_FMT, raw, off)
        off += 31
        (task_no, meta_no, link_id, link_type, dest_id, status,
         dl_s, dl_e, dl_type, file_cnt, _rsv) = t
        tasks.append({
            "task_no": task_no, "meta_task_no": meta_no,
            "link_id": link_id, "link_type": link_type,
            "dest_id": dest_id, "status": status,
            "datalink_start": dl_s, "datalink_end": dl_e,
            "datalink_type": dl_type, "file_count": file_cnt,
        })
    return {
        "packet_type": ptype, "total_packets": total, "sequence_no": seq,
        "cur_packet_no": pno, "cur_packet_len": plen,
        "task_count": cnt, "tasks": tasks,
    }


def serialize_0f44(info: dict) -> bytes:
    """将 dict 反向序列化为 0x0F44 报文(与 parse_0f44 互逆)。"""
    tasks = info.get("tasks") or []
    n = len(tasks)
    total_len = 12 + 31 * n
    buf = bytearray()
    buf += struct.pack(">HHHHHH",
                       int(info.get("packet_type", 0x0F44)),
                       int(info.get("total_packets", 1)),
                       int(info.get("sequence_no", 1)),
                       int(info.get("cur_packet_no", 1)), total_len, n)
    for t in tasks:
        buf += struct.pack(_0F44_TASK_FMT,
                           int(t.get("task_no", 0)),
                           int(t.get("meta_task_no", 0)),
                           int(t.get("link_id", 1)),
                           int(t.get("link_type", 1)),
                           int(t.get("dest_id", 0)),
                           int(t.get("status", 0)),
                           int(t.get("datalink_start", 0)),
                           int(t.get("datalink_end", 0)),
                           int(t.get("datalink_type", 11)),
                           int(t.get("file_count", 0)),
                           b"\x00" * 8)
    return bytes(buf)


# ==================== 0x0B01 星时数据包 ====================
# 16B: 统一头(10B) + time_seconds(4) + time_millis(2)

def parse_0b01(raw: bytes) -> dict:
    """解析 0x0B01 星时数据包(整秒+毫秒,2009 历元起)。"""
    if len(raw) < 16:
        raise ValueError(f"0B01 包长度不足: {len(raw)} < 16")
    (ptype, total, seq, pno, plen, tsec, tms) = struct.unpack_from(
        ">HHHHHIH", raw, 0)
    if ptype != 0x0B01:
        raise ValueError(f"非 0B01 包: 0x{ptype:04X}")
    return {
        "_raw_bytes": raw,
        "packet_type": ptype, "total_packets": total, "sequence_no": seq,
        "cur_packet_no": pno, "cur_packet_len": plen,
        "time_seconds": tsec, "time_millis": tms,
    }


def serialize_0b01(info: dict) -> bytes:
    """将 dict 反向序列化为 0x0B01 报文。"""
    return struct.pack(
        ">HHHHHIH",
        int(info.get("packet_type", 0x0B01)),
        int(info.get("total_packets", 1)),
        int(info.get("sequence_no", 1)),
        int(info.get("cur_packet_no", 1)),
        16,
        int(info.get("time_seconds", 0)) & 0xFFFFFFFF,
        int(info.get("time_millis", 0)) & 0xFFFF)


def default_0b01_info() -> dict:
    return {
        "packet_type": 0x0B01, "total_packets": 1, "sequence_no": 1,
        "cur_packet_no": 1, "cur_packet_len": 16,
        "time_seconds": 557467800, "time_millis": 0,  # 2026-09-01 12:10:00 北京
    }


# ==================== 0xA002 轨道数据包(位置速度) ====================
# 62B: 统一头(10B) + epoch_seconds(4) + gcgs(6×i32) + j2k(6×i32)
# 量纲: 位置 0.01m, 速度 0.0001m/s

def parse_a002(raw: bytes) -> dict:
    """解析 0xA002 轨道数据包(GCGS+J2000 位置速度)。"""
    if len(raw) < 62:
        raise ValueError(f"A002 包长度不足: {len(raw)} < 62")
    (ptype, total, seq, pno, plen, epoch) = struct.unpack_from(
        ">HHHHHI", raw, 0)
    if ptype != 0xA002:
        raise ValueError(f"非 A002 包: 0x{ptype:04X}")
    (gx, gy, gz, gvx, gvy, gvz,
     jx, jy, jz, jvx, jvy, jvz) = struct.unpack_from(">12i", raw, 14)
    return {
        "_raw_bytes": raw,
        "packet_type": ptype, "total_packets": total, "sequence_no": seq,
        "cur_packet_no": pno, "cur_packet_len": plen,
        "epoch_seconds": epoch,
        "gcgs_x": gx * 0.01, "gcgs_y": gy * 0.01, "gcgs_z": gz * 0.01,
        "gcgs_vx": gvx * 0.0001, "gcgs_vy": gvy * 0.0001, "gcgs_vz": gvz * 0.0001,
        "j2k_x": jx * 0.01, "j2k_y": jy * 0.01, "j2k_z": jz * 0.01,
        "j2k_vx": jvx * 0.0001, "j2k_vy": jvy * 0.0001, "j2k_vz": jvz * 0.0001,
    }


def serialize_a002(info: dict) -> bytes:
    """将 dict 反向序列化为 0xA002 报文(与 parse_a002 互逆)。"""
    buf = bytearray()
    buf += struct.pack(
        ">HHHHHI",
        int(info.get("packet_type", 0xA002)),
        int(info.get("total_packets", 1)),
        int(info.get("sequence_no", 1)),
        int(info.get("cur_packet_no", 1)), 62,
        int(info.get("epoch_seconds", 0)))
    buf += struct.pack(
        ">12i",
        int(round(float(info.get("gcgs_x", 0)) / 0.01)),
        int(round(float(info.get("gcgs_y", 0)) / 0.01)),
        int(round(float(info.get("gcgs_z", 0)) / 0.01)),
        int(round(float(info.get("gcgs_vx", 0)) / 0.0001)),
        int(round(float(info.get("gcgs_vy", 0)) / 0.0001)),
        int(round(float(info.get("gcgs_vz", 0)) / 0.0001)),
        int(round(float(info.get("j2k_x", 0)) / 0.01)),
        int(round(float(info.get("j2k_y", 0)) / 0.01)),
        int(round(float(info.get("j2k_z", 0)) / 0.01)),
        int(round(float(info.get("j2k_vx", 0)) / 0.0001)),
        int(round(float(info.get("j2k_vy", 0)) / 0.0001)),
        int(round(float(info.get("j2k_vz", 0)) / 0.0001)))
    return bytes(buf)


def default_a002_info() -> dict:
    return {
        "packet_type": 0xA002, "total_packets": 1, "sequence_no": 1,
        "cur_packet_no": 1, "cur_packet_len": 62, "epoch_seconds": 557467800,
        "gcgs_x": 0.0, "gcgs_y": 0.0, "gcgs_z": 0.0,
        "gcgs_vx": 0.0, "gcgs_vy": 0.0, "gcgs_vz": 0.0,
        "j2k_x": 0.0, "j2k_y": 0.0, "j2k_z": 0.0,
        "j2k_vx": 0.0, "j2k_vy": 0.0, "j2k_vz": 0.0,
    }


# ==================== 0xA012 轨道根数包 ====================
# 62B: 统一头(10B) + epoch_seconds(4) + 6 根数 + 6 reserved(4B each)
# 量纲: 半长轴 1e-5km, 偏心率 1e-6, 角度 1e-3deg

def parse_a012(raw: bytes) -> dict:
    """解析 0xA012 轨道根数包。"""
    if len(raw) < 62:
        raise ValueError(f"A012 包长度不足: {len(raw)} < 62")
    (ptype, total, seq, pno, plen, epoch) = struct.unpack_from(
        ">HHHHHI", raw, 0)
    if ptype != 0xA012:
        raise ValueError(f"非 A012 包: 0x{ptype:04X}")
    (a, e, inc, raan, argp, ma) = struct.unpack_from(">Ii4i", raw, 14)
    return {
        "_raw_bytes": raw,
        "packet_type": ptype, "total_packets": total, "sequence_no": seq,
        "cur_packet_no": pno, "cur_packet_len": plen,
        "epoch_seconds": epoch,
        "semi_major_axis": a * 1e-5,
        "eccentricity": e * 1e-6,
        "inclination": inc * 1e-3,
        "raan": raan * 1e-3,
        "arg_perigee": argp * 1e-3,
        "mean_anomaly": ma * 1e-3,
    }


def serialize_a012(info: dict) -> bytes:
    """将 dict 反向序列化为 0xA012 报文(与 parse_a012 互逆)。"""
    buf = bytearray()
    buf += struct.pack(
        ">HHHHHI",
        int(info.get("packet_type", 0xA012)),
        int(info.get("total_packets", 1)),
        int(info.get("sequence_no", 1)),
        int(info.get("cur_packet_no", 1)), 62,
        int(info.get("epoch_seconds", 0)))
    buf += struct.pack(
        ">Ii4i",
        int(round(float(info.get("semi_major_axis", 0)) / 1e-5)),
        int(round(float(info.get("eccentricity", 0)) / 1e-6)),
        int(round(float(info.get("inclination", 0)) / 1e-3)),
        int(round(float(info.get("raan", 0)) / 1e-3)),
        int(round(float(info.get("arg_perigee", 0)) / 1e-3)),
        int(round(float(info.get("mean_anomaly", 0)) / 1e-3)))
    buf += b"\x00" * 24   # reserved1~reserved6
    return bytes(buf)


def default_a012_info() -> dict:
    return {
        "packet_type": 0xA012, "total_packets": 1, "sequence_no": 1,
        "cur_packet_no": 1, "cur_packet_len": 62, "epoch_seconds": 557467800,
        "semi_major_axis": 6878.137, "eccentricity": 0.0011,
        "inclination": 97.5, "raan": 100.0, "arg_perigee": 45.0,
        "mean_anomaly": 0.0,
    }

