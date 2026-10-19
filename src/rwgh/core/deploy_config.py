"""DeployParameter.xml 配置解析。

解析发射场部署参数 XML,提供姿态机动时长计算等关键参数。
"""
from __future__ import annotations

import logging
import os
import xml.etree.ElementTree as ET
from dataclasses import dataclass

_log = logging.getLogger("rwgh.core.deploy_config")


@dataclass
class DeployConfig:
    """部署参数配置(从 DeployParameter.xml 解析)。"""

    # 姿态机动
    max_pose_transform_time: float = 120.0   # 最大姿态机动时长(秒)
    min_pose_transform_time: float = 15.0   # 最小姿态机动时长(秒)
    max_attitude_angular_vel: float = 5.7   # 最大角速度(度/秒)
    max_attitude_angular_accel: float = 1.4  # 最大角加速度(度/秒²)
    calc_trans_time_method: int = 2         # 计算姿态机动方式 0/1/2

    # 视场参数
    visible_angle: float = 2.1       # 可见光视场角(度)
    visible_width: float = 18.04     # 可见光幅宽(km)
    infrared_angle: float = 1.8      # 红外视场角(度)
    infrared_width: float = 15.0      # 红外幅宽(km)

    # 成像参数
    min_image_time: float = 10.0     # 最短成像时长(秒)
    max_image_single_circle: float = 420.0  # 单圈最大成像时间(秒)
    camera_continuous_time: float = 480.0   # 相机连续成像时长(秒)
    redundance_rate: float = 6.0     # 条带冗余度(%)
    image_continue_gap: float = 2.0  # 成像连续窗口最小间隔(秒)
    sun_avoid: float = 55.0          # 阳光规避角(度)

    # 角度限制
    max_roll: float = 60.0
    max_pitch: float = 60.0
    max_yaw: float = 180.0

    # 数传参数
    data_trans_turn_time: float = 1.0
    data_trans_max_angle: float = 70.0
    data_trans_min_angle: float = -70.0
    ground_station_min_angle: float = 5.0

    # 固存
    raw_file_id: int = 1
    deal_file_id: int = 126
    floor_storage_task_id: int = 1
    target_lib_storage_task_id: int = 61
    rlt_storage_task_id: int = 131
    inter_coord_storage_task_id: int = 201

    # 其他
    base_ymd: str = "2009-01-01 00:00:00"
    lead_time: float = 120.0  # 任务执行提前量(秒)


def load_deploy_config(xml_path: str | None = None) -> DeployConfig:
    """从 XML 文件加载部署参数。"""
    if xml_path is None:
        _root = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.abspath(__file__)))))
        xml_path = os.path.join(_root, "config", "DeployParameter.xml")
    if not os.path.exists(xml_path):
        _log.warning("DeployParameter.xml not found: %s, using defaults",
                     xml_path)
        return DeployConfig()

    tree = ET.parse(xml_path)
    root = tree.getroot()
    params = {}
    for elem in root.iter():
        tag = elem.tag.strip()
        text = (elem.text or "").strip()
        if tag and text:
            params[tag] = text

    def _f(key: str, default: float) -> float:
        v = params.get(key)
        if v is None:
            return default
        try:
            return float(v)
        except ValueError:
            return default

    def _i(key: str, default: int) -> int:
        v = params.get(key)
        if v is None:
            return default
        try:
            return int(float(v))
        except ValueError:
            return default

    cfg = DeployConfig(
        max_pose_transform_time=_f("MaxPoseTransformTime", 120.0),
        min_pose_transform_time=_f("MinPoseTransformTime", 15.0),
        max_attitude_angular_vel=_f("MaxAttitudeManAngularVelocity", 5.7),
        max_attitude_angular_accel=_f("MaxAttitudeManAngularAcceleration", 1.4),
        calc_trans_time_method=_i("CalcTransTimeMethod", 2),
        visible_angle=_f("VisibleAngle", 2.1),
        visible_width=_f("VisibleWidth", 18.04),
        infrared_angle=_f("InfraredAngle", 1.8),
        infrared_width=_f("InfraredWidth", 15.0),
        min_image_time=_f("MinImageTime", 10.0),
        max_image_single_circle=_f("MaxImageTimeOfSingleCircle", 420.0),
        camera_continuous_time=_f("CameraContinuousImgTime", 480.0) * 60,
        redundance_rate=_f("RedundanceRate", 6.0),
        image_continue_gap=_f("ImageContinueGap", 2.0),
        sun_avoid=_f("SunAvoid", 55.0),
        max_roll=_f("MaxRoll", 60.0),
        max_pitch=_f("MaxPitch", 60.0),
        max_yaw=_f("MaxYaw", 180.0),
        data_trans_turn_time=_f("DataTransTurnTime", 1.0),
        data_trans_max_angle=_f("DataTransMaxAngle", 70.0),
        data_trans_min_angle=_f("DataTransMinAngle", -70.0),
        ground_station_min_angle=_f("GroundStationMinAngle", 5.0),
        raw_file_id=_i("RawDataStorageFileId", 1),
        deal_file_id=_i("DealDataStorageFileId", 126),
        floor_storage_task_id=_i("FloorControlledStorageTaskId", 1),
        target_lib_storage_task_id=_i("TargetLibStorageTaskId", 61),
        rlt_storage_task_id=_i("RLTTaskStorageTaskId", 131),
        inter_coord_storage_task_id=_i("InterCoordStorageTaskId", 201),
        base_ymd=params.get("BaseOfYMD", "2009-01-01 00:00:00"),
        lead_time=_f("LeadTimeOfRun", 120.0),
    )
    _log.info("DeployParameter loaded: method=%d, max_pose=%.0f, "
              "min_pose=%.0f, ω_max=%.1f, α=%.1f",
              cfg.calc_trans_time_method,
              cfg.max_pose_transform_time,
              cfg.min_pose_transform_time,
              cfg.max_attitude_angular_vel,
              cfg.max_attitude_angular_accel)
    return cfg


def calc_maneuver_time(angle_deg: float, cfg: DeployConfig) -> float:
    """按梯形速度曲线计算姿态机动时长(秒)。

    1. 加速段: t1 = ω_max / α
    2. 过渡角: θ_trans = ω_max² / α (加速+减速覆盖的角度)
    3. angle >= θ_trans: t = 2*t1 + (angle - θ_trans) / ω_max (梯形)
    4. angle < θ_trans: t = 2 * sqrt(angle / α) (三角)
    5. clamp [min_pose, max_pose]
    """
    angle = abs(angle_deg)
    if angle < 0.01:
        return cfg.min_pose_transform_time
    omega = cfg.max_attitude_angular_vel
    alpha = cfg.max_attitude_angular_accel
    if omega <= 0 or alpha <= 0:
        return cfg.max_pose_transform_time
    t_accel = omega / alpha
    theta_trans = omega * omega / alpha  # = omega * t_accel
    if angle >= theta_trans:
        # 梯形: 加速 + 匀速 + 减速
        t_const = (angle - theta_trans) / omega
        total = 2 * t_accel + t_const
    else:
        # 三角: 加速 + 减速
        total = 2 * (angle / alpha) ** 0.5
    # clamp
    return max(cfg.min_pose_transform_time,
               min(cfg.max_pose_transform_time, total))
