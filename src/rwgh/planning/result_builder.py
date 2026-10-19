"""规划结果生成:可见性窗口 → 0F11/0F22/0F33/0F44 报文数据。

调用链:计算可见性 → 算法库(加载的 .dll,未实现时回退几何桩)输出
可见性窗口 → 本模块按《任务规划输入输出数据包》0F11/0F22/0F33/0F44
sheet 的字段定义生成四类规划结果报文,供结果显示页使用。

姿态机动时长按 DeployParameter.xml 的梯形速度曲线模型计算,
非固定 300s/219s。
"""
from __future__ import annotations

import logging
import math
from datetime import timedelta

from ..core.deploy_config import DeployConfig, load_deploy_config, calc_maneuver_time
from ..models.orbit import STK_EPOCH_2009
from ..models.target import TargetPoint
from ..models.visibility import VisibilityWindow

_log = logging.getLogger("rwgh.planning.result_builder")

# 全局部署配置(首次使用时懒加载)
_deploy_cfg: DeployConfig | None = None


def _get_deploy_cfg() -> DeployConfig:
    global _deploy_cfg
    if _deploy_cfg is None:
        _deploy_cfg = load_deploy_config()
    return _deploy_cfg

# 元任务/任务编号(与 Excel 测试数据一致)
META_TASK_NO = 10
TASK_NO = 245678


def dt_to_sec2009(dt) -> int:
    """datetime → UTC 基准时(2009-01-01 起,整秒)。"""
    if dt.tzinfo is None:
        from datetime import timezone
        dt = dt.replace(tzinfo=timezone.utc)
    return int((dt - STK_EPOCH_2009).total_seconds())


def _is_facility(target_id: str) -> bool:
    return "_" in str(target_id)


def _safe_int(v, default: int = 0) -> int:
    """目标编号转 int;非数字编号(如占位目标)回退默认值。"""
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _target_attr(tp: TargetPoint) -> int:
    """TargetPoint.type → 0F11 目标类型属性。"""
    return int(getattr(tp, "type", 0) or 0)


def _angles_for(max_el: float) -> tuple[float, float, float]:
    """由最大仰角近似推算 (roll, pitch, yaw),单位度。

    俯仰角近似 = 90° - 仰角(星下点角),滚动角取仰角的 1/3 量级,
    偏航角 0;仅作规划结果显示用,真实值待算法库输出替换。
    """
    pitch = max(0.0, 90.0 - max_el)
    roll = max(0.0, max_el / 3.0)
    return roll, pitch, 0.0


def _maneuver_params(aos_s: int, roll: float, pitch: float) -> tuple[int, int]:
    """根据角度计算姿态机动开始时间和机动时长(秒)。

    返回 (maneuver_start, maneuver_duration)
    """
    cfg = _get_deploy_cfg()
    off_axis = math.sqrt(pitch * pitch + roll * roll)
    dur = calc_maneuver_time(off_axis, cfg)
    dur_int = int(round(dur))
    maneuver_start = max(0, aos_s - dur_int - int(cfg.lead_time))
    return maneuver_start, dur_int


def build_0f11(targets: list[TargetPoint],
               windows: list[VisibilityWindow],
               sequence_no: int = 1,
               plan_3101: dict | None = None) -> dict:
    """生成 0F11 待执行成像任务规划方案(仅含可见目标)。

    固定区参数(成像类型/压缩/星上智能处理/数传等)从 3101 报文继承,
    确保用户输入的配置(如星上智能处理开关)正确传递到 0F11 输出。
    plan_3101 为 None 时使用默认值(兼容旧调用)。
    """
    # 从 3101 报文继承固定区参数(用户输入 → 0F11 输出)
    p3101 = plan_3101 or {}
    priority = int(p3101.get("priority", 1))
    imaging_type = int(p3101.get("imaging_type", 11))
    compression = int(p3101.get("compression", 1))
    datalink_type = int(p3101.get("datalink_type", 21))
    return_data_type = int(p3101.get("return_data_type", 0))
    datalink_rate = int(p3101.get("datalink_rate", 0xC1))
    encryption = int(p3101.get("encryption", 0))
    # 星上智能处理开关(用户提到的关键参数)
    smart_process = int(p3101.get("onboard_processing", 1))
    block_size = int(p3101.get("cut_size", 5))
    block_comp_vis = int(p3101.get("cut_compression_vis", 8))
    block_comp_ir = int(p3101.get("cut_compression_ir", 8))
    product_level = int(p3101.get("output_product_level", 2))
    payload_mode = int(p3101.get("payload_mode", 1))
    storage_task_no = int(p3101.get("storage_task_no", 61))
    meta_task_no = int(p3101.get("meta_task_no", META_TASK_NO))
    task_no = int(p3101.get("task_no", TASK_NO))
    task_source = int(p3101.get("task_source", 2))
    record_flag = int(p3101.get("record_flag", 1))
    download_flag = int(p3101.get("download_flag", 0))

    tmap = {str(t.id): t for t in targets}
    planned: list[dict] = []
    for w in windows:
        if _is_facility(w.target_id):
            continue
        tp = tmap.get(str(w.target_id))
        roll, pitch, yaw = _angles_for(w.max_el)
        aos_s = dt_to_sec2009(w.aos)
        los_s = dt_to_sec2009(w.los)
        man_start, man_dur = _maneuver_params(aos_s, roll, pitch)
        # 从 3101 目标记录继承目标属性/优先级
        t_attr = 0
        t_prio = 1
        if tp is not None:
            t_attr = _target_attr(tp)
            t_prio = int(getattr(tp, "target_priority", 1) or 1)
        # 固存文件号(Excel《待执行成像任务规划方案》sheet 备注):
        # 原始数据固存文件号域 [1,125]、处理数据固存文件号域 [126,255],
        # 按目标顺序递增(目标1→1/126, 目标2→2/127, ...),
        # 每次重新计算均从 1/126 重新开始。
        fidx = len(planned)
        planned.append({
            "target_id": _safe_int(tp.id if tp else w.target_id),
            "grid_no": 0xFFFFFFFFFFFFFFFF,
            "target_attr": t_attr,
            "target_priority": t_prio,
            "grid_priority": 0xFFFF,
            "lon": tp.lon if tp else 0.0,
            "lat": tp.lat if tp else 0.0,
            "radius_km": 0,
            "strip_no": 1,
            "maneuver_start": man_start,
            "maneuver_ms": 0,
            "maneuver_duration": man_dur,
            "imaging_start": aos_s,
            "imaging_start_ms": 0,
            "imaging_end": los_s,
            "imaging_end_ms": 0,
            "yaw": yaw, "pitch": pitch, "roll": roll,
            "off_axis": 0,   # serialize 时按 sqrt(pitch²+roll²) 自动计算
            "sun_elev": 35,
            "raw_file_no": 1 + fidx, "proc_file_no": 126 + fidx,
            "raw_file_size": 13578, "proc_file_size": 153,
        })
    return {
        "packet_type": 0x0F11, "total_packets": 1,
        "sequence_no": sequence_no, "cur_packet_no": 1,
        "cur_packet_len": 36 + 76 * len(planned),
        "meta_task_no": meta_task_no, "task_no": task_no,
        "priority": priority, "ret_priority": 2,
        "imaging_type": imaging_type, "payload_mode": payload_mode,
        "compression": compression,
        "storage_task_no": storage_task_no, "datalink_type": datalink_type,
        "return_data_type": return_data_type,
        "datalink_rate": datalink_rate, "encryption": encryption,
        "smart_process": smart_process, "block_size": block_size,
        "block_comp_vis": block_comp_vis, "block_comp_ir": block_comp_ir,
        "product_level": product_level,
        "task_source": task_source,
        "record_flag": record_flag, "download_flag": download_flag,
        "target_count": len(planned), "targets": planned,
    }


def _pick_station(tp: TargetPoint | None,
                  stations: list[dict]) -> dict | None:
    """按目标经度就近选取数传站(0C15)。"""
    if not stations:
        return None
    if tp is None:
        return stations[0]
    return min(stations,
               key=lambda s: abs(float(s.get("station_lon", 0)) - tp.lon))


def _pick_link(station: dict | None, links: list[dict]) -> dict | None:
    """选取与站点匹配的数传链路(0C12)。"""
    if not links:
        return None
    if station is None:
        return links[0]
    sid = station.get("station_id")
    for lk in links:
        if lk.get("station_id") == sid:
            return lk
    return links[0]


def build_0f22(targets: list[TargetPoint],
               windows: list[VisibilityWindow],
               links: list[dict] | None,
               stations: list[dict] | None,
               sequence_no: int = 1) -> dict | None:
    """生成 0F22 待执行数传任务规划方案(单链路 + N 文件)。

    数传站按第一个成像目标就近选取;文件 = 每目标 原始+处理 各一条
    (与 Excel 示例 1/126/2/127 编号方式一致)。
    """
    img_windows = [w for w in windows if not _is_facility(w.target_id)]
    if not img_windows:
        return None
    tmap = {str(t.id): t for t in targets}
    station = _pick_station(tmap.get(str(img_windows[0].target_id)),
                            stations or [])
    link = _pick_link(station, links or [])

    dl_windows = [w for w in img_windows]
    trk_s = min(dt_to_sec2009(w.aos) for w in dl_windows) - 100
    trk_e = max(dt_to_sec2009(w.los) for w in dl_windows) + 100

    files: list[dict] = []
    for i, w in enumerate(dl_windows):
        tp = tmap.get(str(w.target_id))
        base_no = _safe_int(tp.id, i + 1) if tp else i + 1
        for k, (fno, sz) in enumerate(((i + 1, 13578),
                                       (126 + i, 153))):
            files.append({
                "storage_task_no": 61, "file_no": fno,
                "imaging_task_no": TASK_NO, "ret_priority": 2,
                "target_priority": 0xFF, "grid_priority": 2,
                "playback_start": dt_to_sec2009(w.aos),
                "playback_end": dt_to_sec2009(w.los),
                "target_meta_task": base_no if k == 0 else 0,
            })
            _ = sz
    return {
        "packet_type": 0x0F22, "total_packets": 1,
        "sequence_no": sequence_no, "cur_packet_no": 1,
        "cur_packet_len": 48 + 23 * len(files),
        "meta_task_no": META_TASK_NO + 113,   # 123,与 Excel 示例一致
        "datalink_type": 211,
        "link_id": int(link.get("link_id", 1)) if link else 1,
        "link_type": int(link.get("link_type", 1)) if link else 1,
        "dest_id": int(link.get("dest_id", 56)) if link else 56,
        "playback_rate": 0xC1, "encryption": 1,
        "station_id": int(station.get("station_id", 1)) if station else 1,
        "station_lon": float(station.get("station_lon", 117.08))
        if station else 117.08,
        "station_lat": float(station.get("station_lat", 24.1413))
        if station else 24.1413,
        "track_start": max(0, trk_s), "track_end": trk_e,
        "datalink_start": dt_to_sec2009(dl_windows[0].aos),
        "datalink_end": dt_to_sec2009(dl_windows[-1].los),
        "file_count": len(files), "files": files,
    }


def build_0f33(targets: list[TargetPoint],
               windows: list[VisibilityWindow],
               sequence_no: int = 1) -> dict:
    """生成 0F33 成像任务规划结果反馈(全部目标,含不可见)。"""
    tmap = {str(t.id): t for t in targets}
    wmap: dict[str, VisibilityWindow] = {}
    for w in windows:
        if not _is_facility(w.target_id):
            wmap.setdefault(str(w.target_id), w)

    tasks: list[dict] = []
    for tp in targets:
        if _is_facility(str(tp.id)):
            continue
        w = wmap.get(str(tp.id))
        if w is None:
            # 不可见:状态字 0x07,时间全 0
            tasks.append({
                "task_no": TASK_NO, "target_no": _safe_int(tp.id),
                "status": 0x07, "lon": tp.lon, "lat": tp.lat,
                "window_start": 0, "window_end": 0,
                "maneuver_start": 0, "maneuver_end": 0,
                "imaging_start": 0, "imaging_end": 0,
                "roll": 0.0, "pitch": 0.0, "yaw": 0.0,
                "task_source": 2, "conflict_target": 0,
            })
            continue
        roll, pitch, yaw = _angles_for(w.max_el)
        aos_s = dt_to_sec2009(w.aos)
        los_s = dt_to_sec2009(w.los)
        man_start, man_dur = _maneuver_params(aos_s, roll, pitch)
        tasks.append({
            "task_no": TASK_NO, "target_no": _safe_int(tp.id),
            "status": 0x00, "lon": tp.lon, "lat": tp.lat,
            "window_start": aos_s, "window_end": los_s,
            "maneuver_start": man_start,
            "maneuver_end": man_start + man_dur,
            "imaging_start": aos_s, "imaging_end": los_s,
            "roll": roll, "pitch": pitch, "yaw": yaw,
            "task_source": 2, "conflict_target": 0,
        })
    return {
        "packet_type": 0x0F33, "total_packets": 1,
        "sequence_no": sequence_no, "cur_packet_no": 1,
        "cur_packet_len": 12 + 70 * len(tasks),
        "task_count": len(tasks), "tasks": tasks,
    }


def build_0f44(plan_0f22: dict | None,
               sequence_no: int = 1) -> dict | None:
    """生成 0F44 数传任务规划结果反馈(与 0F22 方案一一对应)。"""
    if plan_0f22 is None:
        return None
    tasks = [{
        "task_no": TASK_NO,
        "meta_task_no": int(plan_0f22.get("meta_task_no", 123)),
        "link_id": int(plan_0f22.get("link_id", 1)),
        "link_type": int(plan_0f22.get("link_type", 1)),
        "dest_id": int(plan_0f22.get("dest_id", 56)),
        "status": 0x00,   # 数传规划成功
        "datalink_start": int(plan_0f22.get("datalink_start", 0)),
        "datalink_end": int(plan_0f22.get("datalink_end", 0)),
        "datalink_type": 11,
        "file_count": int(plan_0f22.get("file_count", 0)),
    }]
    return {
        "packet_type": 0x0F44, "total_packets": 1,
        "sequence_no": sequence_no, "cur_packet_no": 1,
        "cur_packet_len": 12 + 31 * len(tasks),
        "task_count": len(tasks), "tasks": tasks,
    }


def build_all_results(targets: list[TargetPoint],
                      windows: list[VisibilityWindow],
                      links: list[dict] | None = None,
                      stations: list[dict] | None = None,
                      sequence_no: int = 1,
                      plan_3101: dict | None = None) -> dict:
    """一次生成四类结果:返回 {'f11':…, 'f22':…, 'f33':…, 'f44':…}。

    f22/f44 在没有成像窗口时为 None(页面上显示空包)。
    plan_3101 为 3101 报文解析结果,其固定区参数(成像类型/压缩/星上
    智能处理/数传等)会被 0F11 继承,确保用户输入正确传递。
    """
    f11 = build_0f11(targets, windows, sequence_no, plan_3101)
    f22 = build_0f22(targets, windows, links, stations, sequence_no)
    f33 = build_0f33(targets, windows, sequence_no)
    f44 = build_0f44(f22, sequence_no)
    _log.info("built results: 0F11 %d targets, 0F22 %s, 0F33 %d tasks, "
              "0F44 %s", f11["target_count"],
              "1 plan" if f22 else "none",
              f33["task_count"], "1 task" if f44 else "none")
    return {"f11": f11, "f22": f22, "f33": f33, "f44": f44}
