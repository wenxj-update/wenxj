"""星上指令码字构造模块(C 代码 app_image_data_block.c / app_ai_task_block.c /
app_datatrans_data_block.c 的 Python 移植)。

全部大端序 struct.pack,累加和 = sum(buf) & 0xFF(不含自身字节)。
时间基准: 2009-01-01 00:00:00 UTC。
"""
from __future__ import annotations

import struct
from typing import Any

# ============================================================================
# 常量定义(对应 C 头文件)
# ============================================================================

# ---- 主导头(app_image_data_block.h) ----
FWD_MASTER_SATSVC = 0x00       # 星务
FWD_MASTER_CAMERA = 0x14       # 相机
FWD_MASTER_ATTITUDE = 0x01     # 姿控
FWD_MASTER_ATT_IF = 0x19       # 姿控接口板
FWD_MASTER_TASKPLAN = 0x35    # 任务规划
FWD_MASTER_DATATRANS = 0x15    # 数传/AI/载综

# ---- 副导头 ----
FWD_SUB_INDIRECT_CMD = 0x20    # 间接指令
FWD_SUB_DATA_BLOCK = 0x01     # 下位机数据块

# ---- 外层发送帧常量 ----
SEND_SYNC_WORD = 0xEB90
SEND_BLOCK_TYPE_PROGCTRL = 1
SEND_BLOCK_TYPE_NORMAL = 2
SEND_ENV_OVERHEAD = 6  # 包头2+类型1+包长2+累加和1

# ---- 内层程控帧常量 ----
FWD_HDR_BYTES = 9  # 程控号1+时标4+主副导头2+长度2
FWD_CHECKSUM_BYTES = 1
FWD_FRAME_OVERHEAD = 10  # FWD_HDR_BYTES + FWD_CHECKSUM_BYTES

# ---- 数据域长度 ----
RECORD_TASK_PKG_BYTES = 18
STORAGE_RECORD_BYTES = 10
COMPRESS_PARAM_BYTES = 10
RECORD_STOP_CMD_BYTES = 4
ONEKEY_SHUTDOWN_BYTES = 2
MULTI_TASK_VALID_CMD_BYTES = 4
ATT_BLOCK_BYTES = 242
ATT_UNIT_BYTES = 40
CAM_BLOCK_BYTES = 57
STARMAP_CMD_BYTES = 4

# ---- AI 块常量 ----
AI_TASK_BLOCK_BYTES = 128
AI_TASK_PKT_PREFIX_BYTES = 9
AI_TASK_PKT_SUM_BYTES = 1
AI_TASK_PACKET_BYTES = 138  # 9+128+1
AI_PWR_ON_CMD_BYTES = 4
AI_PWR_OFF_CMD_BYTES = 5
AI_PWRMODE_CMD_BYTES = 8

# ---- 数传块常量 ----
DT_GROUND_PLAYBACK_PKG_BYTES = 46
DT_STORAGE_PLAYBACK_BYTES = 80
DT_PLAYBACK_STOP_CMD_BYTES = 4
DT_ONEKEY_SHUTDOWN_BYTES = 2
DT_ATT_CMD_BYTES = 4
DT_INTERSAT_W_PKG_BYTES = 17
DT_BROADCAST_PKG_BYTES = 16

# ---- SEQ_OFF_* 时间间隔(秒,相对 Ts/Te) ----
SEQ_OFF_RECORD_TASK = 310       # Ts-310 记录任务包
SEQ_OFF_CAMERA = 305            # Ts-305 相机数据块
SEQ_OFF_ATTITUDE = 210          # Ts-210 姿控数据块
SEQ_OFF_MULTITASK = 208         # Ts-208 多任务有效
SEQ_OFF_STORAGE = 100            # Ts-100 固存记录
SEQ_OFF_SMALL_STORAGE = 96      # Ts-96 小固存记录
SEQ_OFF_COMPRESS = 95           # Ts-95 压缩参数
SEQ_OFF_STARMAP_CLEAR = 2        # Ts-2 星图清零
SEQ_OFF_STARSENSOR_REC_ON = 1   # Ts-1 星敏记录开
SEQ_OFF_RECORD_STOP = 5         # Te+5 记录停止码
SEQ_OFF_STARSENSOR_REC_OFF = 1  # Te+1 星敏记录关
SEQ_OFF_STARSENSOR_DLINK = 2    # Te+2 星敏下传
SEQ_OFF_SMALL_STORAGE_STOP = 7 # Te+7 小固存停止
SEQ_OFF_ONEKEY = 12             # Te+12 一键关机
SEQ_OFF_SEG_CAMERA = 10         # Tsj-10 段间相机
SEQ_OFF_SEG_STORAGE = 5         # Tsj-5 段间固存
# AI 头部
SEQ_OFF_AI_POWER_ON = 115       # Ts-115 AI加电
SEQ_OFF_AI_HIGH_POWER = 110     # Ts-110 AI高功耗
SEQ_OFF_AI_TASK_BLOCK = 105     # Ts-105 AI任务块
# AI 尾部(切块)
SEQ_OFF_AI_PROC_STOP = 150      # Te+150 AI处理停止
SEQ_OFF_AI_LOW_POWER = 155      # Te+155 AI低功耗
SEQ_OFF_AI_POWER_OFF = 160      # Te+160 AI断电
SEQ_OFF_AI_ONEKEY = 165         # Te+165 AI一键关机
# AI 段间
SEQ_OFF_AI_SEG_BLOCK = 7        # Tsj-7 AI段块

# ---- 控制标志 ----
CTRL_START_MARKER = 0xEB90146F
CTRL_END_MARKER = 0xFFFFFFFF
CTRL_FLAG_BYTES = 5

# ---- 帧间延时(微秒) ----
EMIT_FRAME_GAP_US = 250000  # 250ms

# ---- 压缩比映射 ----
_COMPRESS_MAP = {0: 0x04, 1: 0x00, 2: 0x02, 4: 0x04, 8: 0x08}

# ---- 数传姿控指令码字 ----
DT_ATT_DISABLE_SWITCH = 0  # 不允许切换 01 B1 02 AA
DT_ATT_EARTH_MODE = 1     # 对地模式 01 80 04 AA
DT_ATT_ENABLE_SWITCH = 2  # 允许切换 01 B1 01 AA


def _checksum(data: bytes) -> int:
    """累加和 = 逐字节求和 & 0xFF。"""
    return sum(data) & 0xFF


# ============================================================================
# 内层程控帧 + 外层发送帧(基础设施)
# ============================================================================

def build_forward_frame(taskno: int, time_sec: int, master: int,
                        sub: int, field: bytes) -> bytes:
    """内层程控数据块(10 + len(field) 字节)。

    布局: 程控号1 + 时标4(大端) + 主导头1 + 副导头1 + 数据域长度2(大端)
          + 数据域n + 累加和1
    """
    field_len = len(field)
    buf = struct.pack(">BI", taskno & 0xFF, time_sec & 0xFFFFFFFF)
    buf += struct.pack(">BB", master & 0xFF, sub & 0xFF)
    buf += struct.pack(">H", field_len)
    buf += field
    buf += struct.pack(">B", _checksum(buf))
    return buf


def build_send_frame(block_type: int, block: bytes) -> bytes:
    """外层发送帧(6 + len(block) 字节)。

    布局: 包头0xEB90(2B大端) + 类型1 + 包长2(大端,全部长度) + 数据块n + 累加和1
    """
    total = SEND_ENV_OVERHEAD + len(block)
    buf = struct.pack(">H", SEND_SYNC_WORD)
    buf += struct.pack(">B", block_type & 0xFF)
    buf += struct.pack(">H", total)
    buf += block
    buf += struct.pack(">B", _checksum(buf))
    return buf


def build_wrapped_frame(taskno: int, time_sec: int, master: int,
                        sub: int, field: bytes) -> bytes:
    """emit_wrapped 等价: 构内层帧 + 套外层帧 = 完整发送帧。"""
    block = build_forward_frame(taskno, time_sec, master, sub, field)
    return build_send_frame(SEND_BLOCK_TYPE_PROGCTRL, block)


# 数据域在外层发送帧中的起始偏移: EB90(2)+type(1)+len(2)+程控号(1)+时标(4)+主导头(1)+副导头(1)+域长(2)=14
_DATA_FIELD_OFFSET = 14


def extract_data_field(wrapped_frame: bytes) -> bytes:
    """从完整发送帧中剥离 EB90 头/类型/包长/程控帧头,返回有效数据域。

    完整帧布局:
        [0..1]   0xEB90 包头
        [2]      数据块类型(1=程控/2=普通)
        [3..4]   全部长度
        [5]      程控任务号
        [6..9]   时标(4B 大端)
        [10]     主导头
        [11]     副导头
        [12..13] 数据域长度(2B 大端)
        [14..]   有效数据域 ← 本函数返回
        末两字节  内层累加和 + 外层累加和
    """
    if wrapped_frame is None or len(wrapped_frame) < _DATA_FIELD_OFFSET + 2:
        return b""
    field_len = int.from_bytes(wrapped_frame[12:14], 'big')
    if field_len == 0:
        return b""
    end = _DATA_FIELD_OFFSET + field_len
    if end > len(wrapped_frame):
        end = len(wrapped_frame) - 2  # 末两位为内外累加和
    return bytes(wrapped_frame[_DATA_FIELD_OFFSET:end])


def extract_inner_header(wrapped_frame: bytes) -> dict:
    """解析外层+程控帧头,返回头字段字典(主导头/副导头/时标/程控号/域长)。"""
    if wrapped_frame is None or len(wrapped_frame) < _DATA_FIELD_OFFSET:
        return {}
    return {
        "sync": wrapped_frame[0:2],
        "block_type": wrapped_frame[2],
        "total_len": int.from_bytes(wrapped_frame[3:5], 'big'),
        "taskno": wrapped_frame[5],
        "time_sec": int.from_bytes(wrapped_frame[6:10], 'big'),
        "master": wrapped_frame[10],
        "sub": wrapped_frame[11],
        "field_len": int.from_bytes(wrapped_frame[12:14], 'big'),
    }


def build_control_flag(marker: int) -> bytes:
    """控制开始/结束标志(5B 数据域: 0x00 + 4B 大端哨兵)。"""
    field = struct.pack(">BI", 0x00, marker & 0xFFFFFFFF)
    return field


# ============================================================================
# 成像指令码字(app_image_data_block.c)
# ============================================================================

def build_record_task_package() -> bytes:
    """18B 记录任务包(全固定值: 功能识别0x1140/工作时长1800s)。"""
    buf = bytearray(18)
    struct.pack_into(">H", buf, 0, 0x1140)   # 功能识别
    struct.pack_into(">H", buf, 9, 0x0708)   # 工作时长 1800s
    return bytes(buf)


def build_storage_record_package(is_proc: bool, storage_task_id: int,
                                file_id: int) -> bytes:
    """10B 固存记录(载荷): 原始1160/处理1161。"""
    buf = bytearray(10)
    fid = 0x1161 if is_proc else 0x1160
    struct.pack_into(">H", buf, 0, fid)
    buf[2] = 0x80 if is_proc else 0x01
    struct.pack_into(">H", buf, 3, storage_task_id & 0xFFFF)
    buf[5] = file_id & 0xFF
    return bytes(buf)


def build_small_storage_record_package(storage_task_id: int,
                                       raw_file_id: int,
                                       compression_ratio: int) -> bytes:
    """10B 小固存记录: 功能识别1162, 任务号=固存任务号+300。"""
    buf = bytearray(10)
    struct.pack_into(">H", buf, 0, 0x1162)
    buf[2] = 0x01
    struct.pack_into(">H", buf, 3, (storage_task_id + 300) & 0xFFFF)
    buf[5] = raw_file_id & 0xFF
    buf[6] = _COMPRESS_MAP.get(compression_ratio, 0x04)
    return bytes(buf)


def build_compress_param_package(compression_ratio: int) -> bytes:
    """10B 压缩参数设置。"""
    buf = bytearray(10)
    struct.pack_into(">H", buf, 0, 0x2001)
    buf[2] = 0x00  # 相机模式正常
    buf[3] = 0xFF if compression_ratio == 0 else 0x00  # 直通选择
    buf[4] = _COMPRESS_MAP.get(compression_ratio, 0x04)  # 压缩比字节
    buf[5] = 0xFF  # CMOS全通道直通
    return bytes(buf)


def build_record_stop_cmd(is_proc: bool) -> bytes:
    """4B 记录停止码: 原始 11 6F 00 00 / 处理 11 70 00 00。"""
    return bytes([0x11, 0x70 if is_proc else 0x6F, 0x00, 0x00])


def build_small_storage_stop_cmd() -> bytes:
    """4B 小固存停止码: 11 71 00 00。"""
    return bytes([0x11, 0x71, 0x00, 0x00])


def build_onekey_shutdown_cmd() -> bytes:
    """2B 一键关机(存储板/压缩板): 11 30。"""
    return bytes([0x11, 0x30])


def build_multi_task_valid_cmd() -> bytes:
    """4B 多任务有效裸码字: 01 AB 01 AA。"""
    return bytes([0x01, 0xAB, 0x01, 0xAA])


def build_starmap_clear_cmd() -> bytes:
    """4B 星图清零: 19 9A 55 00。"""
    return bytes([0x19, 0x9A, 0x55, 0x00])


def build_star_sensor_record_on_cmd() -> bytes:
    """4B 星敏记录开: 19 98 FF FF。"""
    return bytes([0x19, 0x98, 0xFF, 0xFF])


def build_star_sensor_record_off_cmd() -> bytes:
    """4B 星敏记录关: 19 98 00 00。"""
    return bytes([0x19, 0x98, 0x00, 0x00])


def build_star_sensor_downlink_cmd() -> bytes:
    """4B 星敏下传: 19 99 AA AA。"""
    return bytes([0x19, 0x99, 0xAA, 0xAA])


def build_attitude_block(plan: dict, first: int, count: int,
                         cfg: dict | None = None) -> bytes:
    """242B 姿控数据块(特征码66H + N×40B单元 + AA填充 + 累加和)。

    plan: parse_0f11 输出(含 targets 列表)
    first/count: 本块第一个窗口下标/窗口数(1~5)
    cfg: W35~W39 注入配置(可选,默认全0xAA)
    """
    buf = bytearray(b"\xAA" * ATT_BLOCK_BYTES)
    buf[0] = 0x66  # 特征码
    buf[1] = count & 0xFF
    targets = plan.get("targets") or []
    for i in range(count):
        idx = first + i
        t = targets[idx] if idx < len(targets) else {}
        base = 2 + i * ATT_UNIT_BYTES
        # W0: 任务号(1~5)
        buf[base] = (i + 1) & 0xFF
        # W1: 0x11(侧摆)
        buf[base + 1] = 0x11
        # W2~W5: img_start_sec(4B大端)
        img_start = int(t.get("imaging_start", t.get("img_start", 0)))
        struct.pack_into(">I", buf, base + 2, img_start & 0xFFFFFFFF)
        # W6~W9: img_end_sec(4B大端)
        img_end = int(t.get("imaging_end", t.get("img_end", 0)))
        struct.pack_into(">I", buf, base + 6, img_end & 0xFFFFFFFF)
        # W10~W13: roll(IEEE754大端)
        roll = float(t.get("roll", 0.0))
        struct.pack_into(">f", buf, base + 10, roll)
        # W14~W17: pitch
        pitch = float(t.get("pitch", 0.0))
        struct.pack_into(">f", buf, base + 14, pitch)
        # W18~W21: yaw
        yaw = float(t.get("yaw", 0.0))
        struct.pack_into(">f", buf, base + 18, yaw)
        # W35: 高四位保持A, 低四位按载荷模式(C: 方案A, 20260902)
        # 模式1可见/模式3可见+红外 → 0010b; 模式2红外 → 0001b
        payload_mode = _payload_mode_of(plan)
        mode_bit = 0x01 if payload_mode == 2 else 0x02
        buf[base + 35] = 0xA0 | mode_bit
        # W36~W37: keep_time_s(2B大端)
        struct.pack_into(">H", buf, base + 36, int(t.get("keep_time", 10)) & 0xFFFF)
        # W38: mode_flag
        buf[base + 38] = 0x00
        # W39: 0x55(固定)
        buf[base + 39] = 0x55
    # 累加和 [0..233]
    buf[234] = _checksum(bytes(buf[:234]))
    # off235~241 保持 0xAA
    return bytes(buf)


# 相机任务字常量(app_image_data_block.c 20260716 版表4)
CAM_SHIFT_MODE = 20          # b21-b20 成像模式
CAM_SHIFT_OBS_COUNT = 22     # b25-b22 观测次数(默认1)
CAM_SHIFT_STRIP = 26         # b28-b26 条带编号(默认1)
CAM_SHIFT_BATCH_FLAG = 29    # b29 网格合批(默认1=不合批)
CAM_SHIFT_TASK_SRC = 30      # b31-b30 任务来源映射
CAM_TARGET_ID_LOW20_MASK = 0xFFFFF
CAM_TARGET_ID_INVALID = 0xFFFFFF      # 3B 目标编号哨兵
CAM_GRID_ID_INVALID = 0xFFFFFFFFFFFFFFFF
# 任务来源: 1地面->00 / 4RLT->11 / 其他(2/3/5~8)->10
CAM_TASK_SRC_GROUND = 1
CAM_TASK_SRC_RLT = 4
# 成像任务类型: 11点目标/12立体/13多角度/14连续条带/15多条带
_TASK_TYPE_STEREO = 12
_TASK_TYPE_MULTI_ANGLE = 13
_TASK_TYPE_MULTI_STRIP = 15


def _payload_mode_of(plan: dict) -> int:
    """载荷模式(1=可见 2=红外 3=可见+红外), 兼容 payload_mode/payload_priority。"""
    try:
        return int(plan.get("payload_mode", plan.get("payload_priority", 2)))
    except (TypeError, ValueError):
        return 2


def _camera_task_word(plan: dict, t: dict, target_id: int) -> int:
    """任务编号 32 位逻辑字(C: cam_task_word, 数据块说明.docx 表4 20260716 版)。

    b31-b30 任务来源 | b29 合批(1) | b28-b26 条带 | b25-b22 观测次数(1)
    | b21-b20 成像模式 | b19-b0 目标编号(RLT/哨兵填0)
    """
    task_type = int(plan.get("imaging_type", 11))
    task_source = int(plan.get("task_source", 2))
    strip_no = int(t.get("strip_no", 1))
    # 条带位: 12/13/15 填条带编号字面(1起), 11/14 填默认1(判读K2)
    strip_bits = strip_no if task_type in (_TASK_TYPE_STEREO,
                                           _TASK_TYPE_MULTI_ANGLE,
                                           _TASK_TYPE_MULTI_STRIP) else 1
    # 任务来源映射: 1→00 / 4→11 / 其他→10
    if task_source == CAM_TASK_SRC_GROUND:
        src_bits = 0
    elif task_source == CAM_TASK_SRC_RLT:
        src_bits = 3
    else:
        src_bits = 2
    # 目标编号: RLT 或哨兵填 0, 其余取低20位(判读K3)
    if task_source != CAM_TASK_SRC_RLT and target_id != CAM_TARGET_ID_INVALID:
        target_low20 = target_id & CAM_TARGET_ID_LOW20_MASK
    else:
        target_low20 = 0
    # 成像模式位: 12立体→01 / 13多角度→10 / 15多条带→11 / 11/14→00
    if task_type == _TASK_TYPE_STEREO:
        mode_bits = 1
    elif task_type == _TASK_TYPE_MULTI_ANGLE:
        mode_bits = 2
    elif task_type == _TASK_TYPE_MULTI_STRIP:
        mode_bits = 3
    else:
        mode_bits = 0
    return ((src_bits << CAM_SHIFT_TASK_SRC)
            | (1 << CAM_SHIFT_BATCH_FLAG)
            | (strip_bits << CAM_SHIFT_STRIP)
            | (1 << CAM_SHIFT_OBS_COUNT)
            | (mode_bits << CAM_SHIFT_MODE)
            | target_low20)


def build_camera_block(plan: dict, idx: int, role: int) -> bytes:
    """57B 相机数据块(逐字段大端拼装, C: BuildCameraBlock)。

    plan: parse_0f11 输出
    idx: 窗口下标(0基)
    role: 0=单目标 1=首包 2=中间包 3=尾包
    """
    buf = bytearray(CAM_BLOCK_BYTES)
    targets = plan.get("targets") or []
    t = targets[idx] if idx < len(targets) else {}
    # 公共区
    payload_mode = _payload_mode_of(plan)  # 1=可见 2=红外 3=可见+红外
    target_id = int(t.get("target_id", 0))
    img_start = int(t.get("imaging_start", t.get("img_start", 0)))
    img_end = int(t.get("imaging_end", t.get("img_end", img_start)))
    img_start_msec = int(t.get("imaging_start_ms", t.get("img_start_ms", 0)))
    duration = img_end - img_start  # C: img_end_sec - img_start_sec
    off_axis = float(t.get("off_axis", 0.0))
    pitch = float(t.get("pitch", 0.0))
    roll = float(t.get("roll", 0.0))
    lon = float(t.get("lon", 0.0))
    lat = float(t.get("lat", 0.0))
    is_head = 1 if role in (0, 1) else 0
    # 指令1准备提前量: 红外(2)/可见+红外(3) 300s, 可见(1) 40s
    advance = 40 if payload_mode == 1 else 300
    # 指令1准备码 / 图像输出状态(按载荷模式, C: cam_mode_params)
    if payload_mode == 2:
        prep_code, out_state = 0x12, 0xA5
    elif payload_mode == 3:
        prep_code, out_state = 0x16, 0xAA
    else:
        prep_code, out_state = 0x14, 0x5A
    # 头
    buf[0] = 0xF0
    # task_word(32B 大端, C: cam_task_word 20260716 版)
    struct.pack_into(">I", buf, 1, _camera_task_word(plan, t, target_id))
    # cmd1_sec: 单/首 = T0-提前量(准备); 中/尾 = T0(执行)
    cmd1_sec = (img_start - advance) if is_head else img_start
    struct.pack_into(">I", buf, 5, cmd1_sec & 0xFFFFFFFF)
    # img_start_msec
    struct.pack_into(">H", buf, 9, img_start_msec & 0xFFFF)
    # cmd1_code: 单/首=准备码; 中=21(执行一次); 尾=22(执行并断电)
    if is_head:
        buf[11] = prep_code
    else:
        buf[11] = 0x21 if role == 2 else 0x22
    # cmd1_duration: 单/首固定0(准备无时长); 中/尾=成像时长
    struct.pack_into(">H", buf, 12, 0 if is_head else (duration & 0xFFFF))
    # 可见TDI / 红外TDI
    buf[14] = 0x00
    struct.pack_into(">H", buf, 15, 0x0140)
    # 可见算法开关: 仅可见单/红外单为 FF, 其余 F0(C: D6 终裁)
    buf[17] = 0xFF if (role == 0 and payload_mode != 3) else 0xF0
    buf[18] = 0xFF
    # VIS/IR PARAM
    buf[19] = 0xC3
    buf[20] = 0xFF
    buf[21] = 0xC3
    buf[22] = 0xFF
    # LINE_SRC_GNSS
    buf[23] = 0x01
    # 角度(C: (e6+500000)/1000000 整除, 即四舍五入; 俯仰/滚动取绝对值)
    buf[24] = int(off_axis + 0.5) & 0xFF
    buf[25] = int(abs(pitch) + 0.5) & 0xFF
    buf[26] = int(abs(roll) + 0.5) & 0xFF
    buf[27] = int(t.get("sun_elev", t.get("sun_elevation", 0))) & 0xFF
    # 经纬度(e6)
    struct.pack_into(">i", buf, 28, int(lon * 1e6))
    struct.pack_into(">i", buf, 32, int(lat * 1e6))
    # separator: 单/首 CC(后续还有指令2); 中/尾 EE
    buf[36] = 0xCC if is_head else 0xEE
    if is_head:
        # 单/首包: 指令2 = T0 执行一次成像
        struct.pack_into(">I", buf, 37, img_start & 0xFFFFFFFF)
        struct.pack_into(">H", buf, 41, img_start_msec & 0xFFFF)
        struct.pack_into(">H", buf, 44, duration & 0xFFFF)
    else:
        # 中/尾包: 指令2槽不用, 全 AA
        buf[37:43] = b"\xAA" * 6
        buf[44:46] = b"\xAA\xAA"
    # cmd2_code: 首/中=21; 单/尾=22
    buf[43] = 0x21 if role in (1, 2) else 0x22
    # img_out_cmd1/cmd2(按载荷模式)
    buf[46] = out_state
    buf[47] = out_state
    # aux_data 8B: RLT 任务且网格编号有效填网格编号, 否则全 0x00(用户定)
    if (int(plan.get("task_source", 2)) == CAM_TASK_SRC_RLT
            and int(t.get("grid_no", CAM_GRID_ID_INVALID) or CAM_GRID_ID_INVALID)
            != CAM_GRID_ID_INVALID):
        struct.pack_into(">Q", buf, 48, int(t.get("grid_no")) & 0xFFFFFFFFFFFFFFFF)
    else:
        buf[48:56] = b"\x00" * 8
    # 尾
    buf[56] = 0xEE
    return bytes(buf)


# ============================================================================
# AI 指令码字(app_ai_task_block.c)
# ============================================================================

def build_ai_power_on_cmd() -> bytes:
    """4B AI加电(星务): 00 01 01 D3。"""
    return bytes([0x00, 0x01, 0x01, 0xD3])


def build_ai_power_off_cmd() -> bytes:
    """5B AI断电(载综): 10 03 01 01 17。"""
    return bytes([0x10, 0x03, 0x01, 0x01, 0x17])


def build_ai_power_mode_cmd(high_power: bool) -> bytes:
    """8B AI高/低功耗(载综)。"""
    if high_power:
        return bytes([0x30, 0x01, 0x20, 0x15, 0x0A, 0x00, 0xAA, 0xE9])
    return bytes([0x30, 0x01, 0x20, 0x15, 0x0A, 0x00, 0x55, 0x94])


# AI 块常量(app_ai_task_block.c, 「AI任务指令数据块」sheet 20260811 版)
AI_MODE_REGION = 0x10       # 区域提取(切块/切片区域目标)
AI_MODE_OCEAN_SHIP = 0x20   # 远洋舰船检测识别
AI_MODE_PORT_SHIP = 0x30    # 港口舰船目标检测识别
AI_MODE_AIRPORT = 0x31      # 机场飞机目标检测识别
AI_MODE_VEHICLE = 0x32      # DDZD车辆目标检测
AI_BLK_OFF_REGION = 7       # 区域槽起点(区域1提取大小)
AI_BLK_OFF_FPGA = 98        # 加载FPGA程序
AI_BLK_OFF_TARGET_GRID_ID = 103  # 目标/网格编号(8B, 互斥)
AI_BLK_OFF_FAST_SW = 119    # 快速切换开关
AI_BLK_OFF_TASK_ID = 120    # 任务编号(4B大端, 0811新增)
AI_REGION_SIZE_SLICE = 0x06  # 切片模式区域提取大小恒06H
AI_REGION_SCALE_DIV = 25     # 坐标当量: 1E-6°/2.5E-5° = /25(C整除向零取整)
AI_COMP_CODE_MAP = {0: 0x00, 1: 0x01, 2: 0x02, 4: 0x03, 8: 0x04}
AI_COMP_IR_SHIFT = 5        # 红外压缩比 b7~b5
AI_COMP_VIS_SHIFT = 2       # 可见压缩比 b4~b2
AI_SRC_BIT_IR_INPUT = 0x40  # b6 红外图源输入(载荷模式非可见时置1)
AI_SRC_BIT_VIS_INPUT = 0x20  # b5 可见高分图源输入(载荷模式非红外置1)
AI_PROD_LEVEL_BITS = {0: 0x01, 1: 0x02, 2: 0x04}  # b2~b0: 0/1/2级→001/010/100
AI_CORR_VIS_L12 = 0xA0      # 可见1/2级校正组合
AI_CORR_IR_L12 = 0x58       # 红外1/2级
AI_CORR_VISIR_L12 = 0xF8    # 可见+红外1/2级
AI_FAST_SW_ON = 0x01
AI_FAST_SW_OFF = 0x00


def _ai_comp_code(ratio: int) -> int | None:
    """压缩比输入枚举{0,1,2,4,8} -> 3bit编码(000/001/010/011/100), 非法返回None。"""
    return AI_COMP_CODE_MAP.get(int(ratio) if ratio is not None else -1)


def build_ai_task_cmd_block(plan: dict, idx: int) -> bytes:
    """128B AI处理模式指令块(C: BuildAiTaskCmdBlock, 0811 版布局)。

    全0基线 → 写 FA/F3/工作模式/图源产品/校正/压缩比 → 区域槽0(主目标)
    → FPGA@98 → 目标/网格编号8B@103 → 快速切换@119 → 任务编号4B@120。
    聚合条目不再填充(方老师仲裁)。
    """
    buf = bytearray(AI_TASK_BLOCK_BYTES)
    targets = plan.get("targets") or []
    n = len(targets)
    t = targets[idx] if idx < n else {}
    payload_mode = _payload_mode_of(plan)  # 1=可见 2=红外 3=可见+红外
    block_size = int(plan.get("block_size", 0) or 0)  # 0=切片, 1~6=切块
    prod_lvl = int(plan.get("product_level", 0))  # 星上处理输出产品级别0/1/2
    target_type = int(t.get("target_type", t.get("target_attr", 1)))
    buf[0] = 0xFA  # SEQ_FLAG
    buf[1] = 0xF3  # WORK_FLAG
    # 序号3 工作模式: 切块恒区域提取; 切片按目标类型映射(C: ai_work_mode)
    if block_size == 0:
        buf[2] = {2: AI_MODE_OCEAN_SHIP, 3: AI_MODE_PORT_SHIP,
                  4: AI_MODE_AIRPORT, 5: AI_MODE_VEHICLE}.get(target_type,
                                                              AI_MODE_REGION)
    else:
        buf[2] = AI_MODE_REGION
    # 序号4~9 图源输入/产品级别位域(C: ai_src_prod_byte)
    field_byte = 0
    if payload_mode != 1:  # 载荷模式非可见 → 红外图源输入
        field_byte |= AI_SRC_BIT_IR_INPUT
    if payload_mode != 2:  # 载荷模式非红外 → 可见图源输入
        field_byte |= AI_SRC_BIT_VIS_INPUT
    field_byte |= AI_PROD_LEVEL_BITS.get(prod_lvl, 0x04)  # 2(超域)按2级兜底
    buf[3] = field_byte
    # 序号10~17 校正/融合开关(C: ai_correct_byte): 0级全关; 1/2级按载荷模式
    if prod_lvl >= 1:
        if payload_mode == 1:
            buf[4] = AI_CORR_VIS_L12
        elif payload_mode == 2:
            buf[4] = AI_CORR_IR_L12
        else:
            buf[4] = AI_CORR_VISIR_L12
    else:
        buf[4] = 0x00
    # 序号18~21 压缩比: 红外b7~b5 | 可见b4~b2(C: ir_code<<5 | vis_code<<2)
    ir_code = _ai_comp_code(plan.get("block_comp_ir", 8))
    vis_code = _ai_comp_code(plan.get("block_comp_vis", 8))
    if ir_code is None:
        ir_code = AI_COMP_CODE_MAP[8]  # 非法输入兜底默认8:1
    if vis_code is None:
        vis_code = AI_COMP_CODE_MAP[8]
    buf[5] = ((ir_code & 0x07) << AI_COMP_IR_SHIFT) | \
             ((vis_code & 0x07) << AI_COMP_VIS_SHIFT)
    # 序号23~52 区域槽0 = 主目标(聚合条目不再填充); 提取大小: 切块=切块大小,
    # 切片恒06H; 坐标/25(C整除向零取整, 与Python floor不同须用int除)
    size = block_size if block_size != 0 else AI_REGION_SIZE_SLICE
    buf[AI_BLK_OFF_REGION] = size & 0xFF
    lon_e6 = int(round(float(t.get("lon", 0.0)) * 1e6))
    lat_e6 = int(round(float(t.get("lat", 0.0)) * 1e6))
    struct.pack_into(">i", buf, AI_BLK_OFF_REGION + 1, int(lon_e6 / AI_REGION_SCALE_DIV))
    struct.pack_into(">i", buf, AI_BLK_OFF_REGION + 5, int(lat_e6 / AI_REGION_SCALE_DIV))
    # 序号54 加载FPGA程序
    buf[AI_BLK_OFF_FPGA] = 0x10
    # 序号86 目标/网格编号(8B大端右对齐, 互斥): 目标编号有效填目标, 否则填网格
    tid = int(t.get("target_id", CAM_TARGET_ID_INVALID))
    if tid != CAM_TARGET_ID_INVALID:
        struct.pack_into(">Q", buf, AI_BLK_OFF_TARGET_GRID_ID,
                         tid & 0xFFFFFFFFFFFFFFFF)
    else:
        grid = t.get("grid_no", 0)
        try:
            grid = int(grid)
        except (TypeError, ValueError):
            grid = 0
        struct.pack_into(">Q", buf, AI_BLK_OFF_TARGET_GRID_ID,
                         grid & 0xFFFFFFFFFFFFFFFF)
    # 序号89 快速切换: 一轮首发块(idx==0)恒关; 后续段块且目标数>=2填01
    buf[AI_BLK_OFF_FAST_SW] = AI_FAST_SW_ON if (idx >= 1 and n >= 2) \
        else AI_FAST_SW_OFF
    # 序号90 任务编号(4B大端): 取公共区任务编号
    struct.pack_into(">I", buf, AI_BLK_OFF_TASK_ID,
                     int(plan.get("task_no", plan.get("task_id", 0))) & 0xFFFFFFFF)
    return bytes(buf)


def build_ai_task_cmd_packet(plan: dict, idx: int) -> bytes:
    """138B AI任务指令完整发送包 = 9B前缀 + 128B块 + 1B累加和。"""
    prefix = bytes([0x30, 0x02, 0x58, 0x03, 0x00, 0x03, 0x00, 0x80, 0x01])
    block = build_ai_task_cmd_block(plan, idx)
    buf = prefix + block
    # 累加和: 偏移[2..136]共135B
    cs = sum(buf[2:137]) & 0xFF
    buf += struct.pack(">B", cs)
    return buf


# ============================================================================
# 数传指令码字(app_datatrans_data_block.c)
# ============================================================================

def build_ground_playback_task_package(rate_code: int, chan_mask: int,
                                       station_id: int, station_lon: float,
                                       station_lat: float) -> bytes:
    """46B 对地回放任务包(0x1141)。"""
    # 金标准模板
    tmpl = bytearray.fromhex("1141 0001 2000 0000 0000 0007 0800 0001 0200 0A00 0F00 B60B 6001 6C16 C100 0001 2C02 2222 2202 D82D 8200 0002 5800".replace(" ", ""))
    # 覆写速率选择
    rate_sel = {1: 0x20, 2: 0x30, 3: 0x40, 4: 0x50}.get(rate_code, 0x20)
    # 极性反转(C: map_playback_rate_sel): 输入某旋"有效位"为0(无效)时,
    # 输出置对应无效位; 双旋均有效则保持00。bit1=左旋 bit0=右旋
    rate_sel |= (0x08 if not (chan_mask & 2) else 0)  # 左旋无效
    rate_sel |= (0x04 if not (chan_mask & 1) else 0)  # 右旋无效
    tmpl[4] = rate_sel
    # 站址ID
    tmpl[15] = station_id & 0xFF
    # 机动站模式: 覆写站址经纬度
    tmpl[14] = 0xC0
    struct.pack_into(">i", tmpl, 21, int(station_lon * 1e6))
    struct.pack_into(">i", tmpl, 25, int(station_lat * 1e6))
    return bytes(tmpl)


def build_storage_playback_cmd(link_type: int, files: list, ts: int,
                               te: int) -> bytes:
    """80B 固存回放指令(16头 + 16×4回放参数)。"""
    buf = bytearray(DT_STORAGE_PLAYBACK_BYTES)
    # 功能识别
    func = {1: 0x1164, 5: 0x1164, 3: 0x1165, 2: 0x1166, 4: 0x1166, 6: 0x1166}
    struct.pack_into(">H", buf, 0, func.get(link_type, 0x1164))
    # 回放速率(星间恒62)
    rate = 62 if link_type in (2, 4, 6) else 0
    struct.pack_into(">H", buf, 3, rate)
    # 回放类型(任务号+文件号回放)
    buf[5] = 0x02
    # 文件数
    n = min(len(files), 16)
    struct.pack_into(">H", buf, 6, n)
    # 起止时间
    struct.pack_into(">I", buf, 8, ts & 0xFFFFFFFF)
    struct.pack_into(">I", buf, 12, te & 0xFFFFFFFF)
    # 每槽4B
    for i, f in enumerate(files[:16]):
        base = 16 + i * 4
        struct.pack_into(">H", buf, base, int(f.get("storage_task_id", 0)) & 0xFFFF)
        buf[base + 2] = int(f.get("file_id", 0)) & 0xFF
        buf[base + 3] = 0x00
    return bytes(buf)


def build_storage_playback_stop_cmd(link_type: int) -> bytes:
    """4B 固存回放停止。"""
    if link_type in (2, 4, 6):
        return bytes([0x11, 0x75, 0x00, 0x00])
    if link_type == 3:
        return bytes([0x11, 0x74, 0x00, 0x00])
    return bytes([0x11, 0x73, 0x00, 0x00])  # 对地1/5


def build_datatrans_onekey_shutdown_cmd() -> bytes:
    """2B 数传一键关机: 11 31。"""
    return bytes([0x11, 0x31])


def build_broadcast_onekey_shutdown_cmd() -> bytes:
    """2B 广播一键关机: 11 32。"""
    return bytes([0x11, 0x32])


def build_intersat_w_task_package(peer_scid: int) -> bytes:
    """17B 星间W分发任务包(0x1143)。"""
    buf = bytearray(DT_INTERSAT_W_PKG_BYTES)
    struct.pack_into(">H", buf, 0, 0x1143)
    struct.pack_into(">H", buf, 2, peer_scid & 0xFFFF)
    buf[4] = 0x03  # 工作模式固定
    # 有效起始/结束秒
    struct.pack_into(">I", buf, 5, 0x00000000)
    struct.pack_into(">I", buf, 9, 0xFFFFFFFF)
    struct.pack_into(">I", buf, 13, 0x00000708)  # 1800s
    return bytes(buf)


def build_broadcast_task_package(rate_code: int) -> bytes:
    """16B 广播分发任务包(0x1142)。"""
    tmpl = bytearray.fromhex("1142 0000 0100 0000 0000 0007 0800 0000".replace(" ", ""))
    # 速率映射: 7->01 8->02 9->03
    tmpl[4] = {7: 0x01, 8: 0x02, 9: 0x03}.get(rate_code, 0x01)
    return bytes(tmpl)


def build_datatrans_att_cmd(att_op: int) -> bytes:
    """4B 姿控间接指令(禁切/对地/允切)。"""
    if att_op == DT_ATT_DISABLE_SWITCH:
        return bytes([0x01, 0xB1, 0x02, 0xAA])
    if att_op == DT_ATT_EARTH_MODE:
        return bytes([0x01, 0x80, 0x04, 0xAA])
    return bytes([0x01, 0xB1, 0x01, 0xAA])  # 允切
