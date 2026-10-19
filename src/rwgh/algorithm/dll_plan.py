"""DLL 报文驱动器:按参考工程(RWGH_test)接口协议驱动算法库计算规划。

接口协议(tool.h):
  DllInit()                        初始化(仅一次)
  DllInput(Byte* Data, int iLen)   向 DLL 输入报文(字节流+长度)
  DllOutput(Byte* Data, int* iLen) 轮询读输出,返回 0 且 iLen>0 表示有数据
  输出缓冲 2KB(POW_2EN11)

关键运行模型(反解参考工程 tool.c OutputThreadProc 实测得出):
  参考工程在 DllInit 后立即启动一个**独立后台线程,每 100ms 持续轮询
  DllOutput**;主线程只负责 DllInput 注入报文。DLL 内部 ThreadSatProc
  异步处理任务报文,0F33/0F11 等结果并非在 DllInput 返回时同步产生,而是
  在随后的轮询中陆续吐出——尤其是 2KB 以上的大 3101(多条带)报文,
  若没有持续的 DllOutput 轮询(“输出泵”),结果包会滞留在 DLL 内部、
  界面表现为“点击计算可见性后 0F33 没有反馈”。

  因此本驱动器在 ensure_init() 后同样启动一个 daemon 输出泵线程,
  持续 DllOutput 并按报文边界切分后放入线程安全队列;上层通过
  drain_output() 非阻塞取走已缓存报文,或用 _wait_plan() 带超时等待
  规划结果到齐。

报文驱动时序(scenario_target.c RunTargetScenario):
  ① 0B01 初始星时 → ② A012/A002 初始轨道 → ③ 3101 任务 → ④ 0C12 链路
  → 后台泵陆续收到 0F33(可见性反馈)与 0F11(成像方案);数传还需
    0802 固存状态后由 0F44/0F22 反馈。
  实测:当任务时间窗落在 DLL 可预报范围内时,0F33+0F11 在注入完整
  输入后约 1~2 秒即异步产出,无需星时走到“成像前 6 分钟”。

两阶段:
  阶段1 compute_initial:发送全部输入 → 等待并收集 0F33/0F44/0F11/0F22
  阶段2 advance_star_time:星时走动时发 0B01,泵持续收集新增规划包。
"""
from __future__ import annotations

import ctypes
import logging
import struct
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone as _tz

from .loader import LoadedDll
from ..core.exceptions import DllLoadError
from ..stk.packets import (
    parse_3101, parse_0c12, F33_STATUS_IMAGING, F44_STATUS_IMAGING,
    build_0c12_from_window, build_0802_from_window,
)

_log = logging.getLogger("rwgh.algorithm.dll_plan")

DLL_BUF_SIZE = 8192          # DllOutput 缓冲。参考08版用2048,但 V2 版
#                            # 单个 0F33 可达 33记录×70B+12≈2322B,2048会
#                            # 截断/溢出(表现为丢0F33、堆损坏),故放大。
DEFAULT_STEP_SEC = 10        # 星时推进步长(秒)
ADVANCE_BEFORE = 900         # 任务窗前预推进(秒)
ADVANCE_AFTER = 7200         # 任务窗后预推进(秒,覆盖数传回放窗)
MAX_STEPS = 4000             # 推进步数上限(防失控)
IMAGING_LEAD_SEC = 360       # 0F11 成像方案提前生成时间(6分钟)
DATALINK_LEAD_SEC = 360      # 0F22 数传方案提前生成时间(6分钟)

# 输出泵轮询 / 等待参数
PUMP_IDLE_SLEEP = 0.05       # 泵无数据时的轮询间隔(50ms,比参考100ms更勤)
PUMP_BUSY_ROUNDS = 8         # 泵每轮连续 DllOutput 的最大次数
PLAN_WAIT_TIMEOUT = 8.0        # 阶段1等待规划结果的总超时(秒) — 从20s降至此
PLAN_SETTLE_SEC = 1.0        # 收到0F33后无新规划包的静默确认时间(秒) — 从2.0s降至此
#                           # V2实测0F11可能在0F33之后1~2秒才异步产出,
#                           # 0.5s太短会截断0F11,改为2.0s。
PHASE1_ADVANCE_STEPS = 2     # 阶段1若0F44未到,推进星时的步数 — 从5降至此
PHASE1_ADVANCE_WAIT = 1.5    # 每步星时推进后等待DLL产出的超时(秒) — 从3.0s降至此

# 已知报文类型(用于输出流切分)
KNOWN_PACKET_TYPES = {
    0x0F11, 0x0F22, 0x0F33, 0x0F44,          # 规划结果
    0x3101, 0x0C12, 0x0C15, 0x0C17, 0x0802,  # 任务/资源/固存
    0x0B01, 0xA012, 0xA002,                  # 星时/轨道
    0x0252, 0x0253, 0x0256,                  # 星间/建链
}

# DLL 输出的规划结果类型
PLAN_OUTPUT_TYPES = (0x0F11, 0x0F22, 0x0F33, 0x0F44)

# 2009 UTC 历元(仅用于日志打印北京时间)
_STK_EPOCH = datetime(2009, 1, 1, tzinfo=_tz.utc)


def _epoch_to_bj_str(sec: int) -> str:
    """2009 历元秒 → 北京时间字符串(仅日志用)。"""
    try:
        dt = _STK_EPOCH + timedelta(seconds=int(sec)) + timedelta(hours=8)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:  # noqa: BLE001
        return "—"


@dataclass
class DllPlanResult:
    """DLL 报文驱动的计算结果。"""

    packets: dict[int, list[bytes]] = field(default_factory=dict)
    n_inputs: int = 0            # 发送的输入报文总数
    n_steps: int = 0             # 星时推进步数
    advance_from: int = 0        # 推进起始(2009 历元秒)
    advance_to: int = 0          # 推进结束(2009 历元秒)

    def first(self, ptype: int) -> bytes | None:
        lst = self.packets.get(ptype) or []
        return lst[0] if lst else None

    def last(self, ptype: int) -> bytes | None:
        lst = self.packets.get(ptype) or []
        return lst[-1] if lst else None

    def all(self, ptype: int) -> list[bytes]:
        return self.packets.get(ptype) or []

    def count(self, ptype: int) -> int:
        return len(self.packets.get(ptype) or [])

    def merge(self, other: "DllPlanResult") -> None:
        for ptype, pkts in other.packets.items():
            self.packets.setdefault(ptype, []).extend(pkts)
        self.n_inputs += other.n_inputs
        self.n_steps += other.n_steps


def split_packets(buf: bytes) -> list[bytes]:
    """把 DLL 输出缓冲切分为单条完整报文(按包类型+包长字段)。"""
    out: list[bytes] = []
    off = 0
    n = len(buf)
    while off + 10 <= n:
        ptype = int.from_bytes(buf[off:off + 2], "big")
        if ptype not in KNOWN_PACKET_TYPES:
            break
        plen = int.from_bytes(buf[off + 8:off + 10], "big")
        if plen < 10 or off + plen > n:
            break
        out.append(bytes(buf[off:off + plen]))
        off += plen
    return out


class DllPlanDriver:
    """封装 DllInit/DllInput/DllOutput 的报文序列驱动。

    内含一个 daemon 输出泵线程持续 DllOutput(对齐参考工程),
    上层线程只做 DllInput,通过 drain_output()/wait 取结果。
    """

    def __init__(self, dll: LoadedDll) -> None:
        self._dll = dll
        self._inited = False
        self._seq = 0
        self._fn_init = dll.DllInit
        self._fn_input = dll.DllInput
        self._fn_output = dll.DllOutput
        # 输出泵:后台线程 + 线程安全队列
        self._queue: deque[bytes] = deque()
        self._qlock = threading.Lock()
        self._pump_on = False
        self._pump_thread: threading.Thread | None = None
        self._raw_unknown = 0       # 无法切分的残留字节计数(诊断)
        # 阶段2状态:已发送输入后的推进上下文
        self._phase2_active = False
        self._phase2_last_t = 0          # 上次推进到的星时
        self._phase2_key_times: list[int] = []  # 0F11 关键时间点
        self._phase2_triggered: set[int] = set()  # 已触发的关键时间点

    # ---------- 输出泵 ----------

    def _pump_loop(self) -> None:
        """后台线程:持续 DllOutput 并切分入队(对齐 OutputThreadProc)。"""
        buf = (ctypes.c_ubyte * DLL_BUF_SIZE)()
        while self._pump_on:
            got_any = False
            for _ in range(PUMP_BUSY_ROUNDS):
                ilen = ctypes.c_int(DLL_BUF_SIZE)
                try:
                    res = self._fn_output(buf, ctypes.byref(ilen))
                except Exception as e:  # noqa: BLE001
                    _log.warning("输出泵 DllOutput 异常: %s", e)
                    break
                if res != 0 or ilen.value <= 0:
                    break
                got_any = True
                raw = bytes(bytearray(buf)[:ilen.value])
                pkts = split_packets(raw)
                if pkts:
                    with self._qlock:
                        self._queue.extend(pkts)
                else:
                    self._raw_unknown += len(raw)
            if not got_any:
                time.sleep(PUMP_IDLE_SLEEP)

    def start_pump(self) -> None:
        if self._pump_thread is not None and self._pump_thread.is_alive():
            return
        self._pump_on = True
        self._pump_thread = threading.Thread(
            target=self._pump_loop, name="dll-output-pump", daemon=True)
        self._pump_thread.start()

    def stop_pump(self) -> None:
        self._pump_on = False
        t = self._pump_thread
        if t is not None and t.is_alive() and t is not threading.current_thread():
            t.join(timeout=1.0)
        self._pump_thread = None

    # ---------- 基础操作 ----------

    def ensure_init(self) -> None:
        if self._inited:
            return
        self._do_init()

    def reinit(self) -> None:
        """重新初始化 DLL(清除内部残留状态)。

        参考工程每次运行场景前都会调用 DllInit;本驱动器在
        compute_initial 开头也调一次,确保上一轮的残留状态不污染本轮。
        """
        self._do_init()

    def _do_init(self) -> None:
        # 先停泵,清队列,再重新 DllInit + 启泵
        self.stop_pump()
        with self._qlock:
            self._queue.clear()
        try:
            self._fn_init()
        except Exception as e:  # noqa: BLE001
            raise DllLoadError(f"DllInit 调用失败: {e}") from e
        self._inited = True
        self._seq = 0
        # 阶段2上下文清零
        self._phase2_active = False
        self._phase2_last_t = 0
        self._phase2_key_times = []
        self._phase2_triggered = set()
        self._phase2_dl_key_times = []
        self._phase2_dl_triggered = set()
        self._phase2_f33_seen = set()
        self._phase2_f44_seen = set()
        # DllInit 后立即启动输出泵(关键!与参考工程一致)
        self.start_pump()
        time.sleep(0.1)
        _log.info("DllInit ok, 输出泵已启动")

    def _next_seq(self) -> int:
        self._seq = (self._seq + 1) & 0xFFFF
        return self._seq

    def send_bytes(self, data: bytes) -> None:
        n = len(data)
        if n == 0:
            return
        arr = (ctypes.c_ubyte * n).from_buffer_copy(data)
        self._fn_input(arr, n)

    def drain_output(self, max_rounds: int = 128) -> list[bytes]:
        """非阻塞取走输出泵已缓存的全部报文(线程安全)。

        max_rounds 参数仅为兼容旧签名保留;真正的 DllOutput 由后台泵调用。
        """
        with self._qlock:
            if not self._queue:
                return []
            pkts = list(self._queue)
            self._queue.clear()
        return pkts

    def star_time_frame(self, sec: int, millis: int = 0) -> bytes:
        return struct.pack(">HHHHHIH", 0x0B01, 1, self._next_seq(), 1, 16,
                           int(sec) & 0xFFFFFFFF, int(millis) & 0xFFFF)

    # ---------- 阶段1:初始计算(异步收集 0F33/0F44/0F11/0F22) ----------

    def _wait_plan(self, timeout: float = PLAN_WAIT_TIMEOUT,
                   settle_sec: float = PLAN_SETTLE_SEC,
                   expect_f44: bool = False,
                   only_type: int | None = None) -> list[bytes]:
        """发送输入后等待规划结果到齐。

        判定:0F33(及 expect_f44 时的 0F44)反馈到齐后,若连续 settle_sec 内
        再无任何规划包(0Fxx)产出,则认为本轮规划完成;否则等到 timeout。

        only_type: 若指定,则只等待该类型报文到达即返回(不依赖0F33),
        用于星时推进循环中单独等待 0F44/0F11 产出。
        """
        collected: list[bytes] = []
        got_f33 = False
        got_f44 = False
        last_plan_ts = 0.0
        start = time.monotonic()
        while True:
            now = time.monotonic()
            new_pkts = self.drain_output()
            if new_pkts:
                new_plan = False
                for p in new_pkts:
                    collected.append(p)
                    if int.from_bytes(p[0:2], "big") in PLAN_OUTPUT_TYPES:
                        new_plan = True
                if new_plan:
                    last_plan_ts = now
                    for p in new_pkts:
                        pt = int.from_bytes(p[0:2], "big")
                        if pt == 0x0F33:
                            got_f33 = True
                        elif pt == 0x0F44:
                            got_f44 = True
            if only_type is not None:
                # 只等指定类型:到达即返回(不依赖0F33)
                if any(int.from_bytes(p[0:2], "big") == only_type
                       for p in collected):
                    break
            else:
                feedback_ready = got_f33 and (got_f44 or not expect_f44)
                if feedback_ready and last_plan_ts > 0 and \
                        (now - last_plan_ts) >= settle_sec:
                    break
            if (now - start) >= timeout:
                if only_type is not None:
                    _log.warning("等待0x%04X超时(%.1fs),DLL无输出",
                                 only_type, timeout)
                elif not got_f33:
                    _log.warning("等待0F33超时(%.1fs),DLL无可见性反馈",
                                 timeout)
                elif expect_f44 and not got_f44:
                    _log.warning("等待0F44超时(%.1fs),DLL无数传反馈",
                                 timeout)
                break
            time.sleep(0.03)
        return collected

    def compute_initial(self, task_bytes: bytes,
                        link_bytes: bytes | None = None,
                        station_bytes: bytes | None = None,
                        storage_bytes: bytes | None = None,
                        orbit_frames: tuple[bytes, ...] = (),
                        star_base_sec: int | None = None,
                        step_delay_ms: int = 20) -> DllPlanResult:
        """阶段1:发送全部输入报文 → 后台泵等待 → 返回规划结果。

        返回 DllPlanResult,通常含 0F33(可见性反馈)+ 0F11(成像方案);
        若已具备数传资源/固存,也可能含 0F44/0F22。

        同时初始化阶段2推进上下文。
        """
        # 每次计算前重新 DllInit,清除上一轮残留状态
        # (参考工程每次运行场景前都会 DllInit)
        self.reinit()
        result = DllPlanResult()

        # 解析 3101 任务窗(用于阶段2推进范围)
        t_earliest = t_latest = None
        try:
            info = parse_3101(task_bytes)
            times = [int(info.get("task_earliest") or 0),
                     int(info.get("task_latest") or 0)]
            for t in info.get("targets") or []:
                times.extend([int(t.get("meta_earliest") or 0),
                              int(t.get("meta_latest") or 0)])
            times = [t for t in times if t > 0]
            if times:
                t_earliest, t_latest = min(times), max(times)
        except Exception as e:  # noqa: BLE001
            _log.warning("3101 任务窗解析失败: %s", e)

        # 解析 0C12 数传链路窗口(仅用于阶段1推进范围,不覆盖3101任务窗)
        link_latest = 0
        if link_bytes:
            try:
                linfo = parse_0c12(link_bytes)
                for lk in linfo.get("links") or [linfo]:
                    link_latest = max(link_latest,
                                      int(lk.get("link_end", 0) or 0))
            except Exception as e:  # noqa: BLE001
                _log.warning("0C12 链路窗解析失败: %s", e)
        # 注意: 不用 link_latest 覆盖 t_latest, 因为 UI 0C12 可能有旧数据。
        # 动态构造的 0C12/0802 时间窗口用 3101 的 t_earliest/t_latest。

        # 清空泵队列中的历史残留
        self.drain_output()

        # 初始星时:一切以页面显示星时(star_base_sec)为准。
        if star_base_sec:
            adv_from = int(star_base_sec)
        elif t_earliest:
            adv_from = t_earliest - ADVANCE_BEFORE
        else:
            adv_from = 0
        _log.info("阶段1初始星时(0B01)=%d (%s)", adv_from,
                  _epoch_to_bj_str(adv_from))
        self.send_bytes(self.star_time_frame(adv_from))
        result.n_inputs += 1
        # 轨道帧
        for f in orbit_frames:
            self.send_bytes(f)
            result.n_inputs += 1
        # 轨道注入后再发一帧当前星时(参考子场景8在3101前会重复一次0B01,
        # 用于让 DLL 以当前星时+新轨道进入任务就绪态;实测缺此帧会漏0F33)
        time.sleep(0.1)
        self.send_bytes(self.star_time_frame(adv_from))
        result.n_inputs += 1
        # 任务报文(大 3101 由 DLL 异步处理)
        self.send_bytes(task_bytes)
        result.n_inputs += 1
        # 大任务报文(可达 2KB+)需给 DLL 足够消化时间,过早注入链路会令其
        # 内部规划状态错乱(实测间隔不足会丢失 0F33,甚至触发堆错误)。
        time.sleep(0.3)

        # ---- 动态构造 0C12/0802,确保时间窗口与 3101 目标实际成像窗口匹配 ----
        # UI 页面的默认 0C12/0802 可能有旧测试数据(时间差 43 天),
        # DLL 会因固存记录时间不在规划范围内而拒绝产出 0F44。
        # 用 3101 目标的 meta_earliest/meta_latest(元任务窗口)构造匹配的报文。
        dyn_link_bytes = link_bytes
        dyn_storage_bytes = storage_bytes
        if t_earliest and t_latest:
            # 0C12: 若 UI 报文链路时间与任务窗相差 >4 小时,动态构造
            need_rebuild_link = True
            if link_bytes:
                try:
                    linfo = parse_0c12(link_bytes)
                    for lk in linfo.get("links") or [linfo]:
                        ls = int(lk.get("link_start", 0) or 0)
                        le = int(lk.get("link_end", 0) or 0)
                        if ls > 0 and le > 0:
                            diff = abs(ls - t_latest)
                            if diff < 14400:  # 4 小时内,认为合理
                                need_rebuild_link = False
                            break
                except Exception:  # noqa: BLE001
                    pass
            if need_rebuild_link:
                # 链路窗口:元任务最早开始前4分钟 ~ 最晚结束后4分钟
                dyn_link_bytes = build_0c12_from_window(
                    t_earliest - 240, t_latest + 240)
                _log.info("动态构造 0C12: link_start=%d(%s) link_end=%d(%s)",
                          t_earliest - 240,
                          _epoch_to_bj_str(t_earliest - 240),
                          t_latest + 240,
                          _epoch_to_bj_str(t_latest + 240))

            # 0802: 固存记录时间 = 元任务窗口(与3101目标匹配)
            dyn_storage_bytes = build_0802_from_window(t_earliest, t_latest)
            _log.info("动态构造 0802: record_start=%d(%s) record_end=%d(%s)",
                      t_earliest, _epoch_to_bj_str(t_earliest),
                      t_latest, _epoch_to_bj_str(t_latest))

        # 重新解析动态构造的 0C12 获取数传窗口终点
        link_latest_dyn = 0
        if dyn_link_bytes:
            try:
                linfo = parse_0c12(dyn_link_bytes)
                for lk in linfo.get("links") or [linfo]:
                    link_latest_dyn = max(link_latest_dyn,
                                          int(lk.get("link_end", 0) or 0))
            except Exception:  # noqa: BLE001
                pass
        if link_latest_dyn > 0:
            link_latest = link_latest_dyn

        if dyn_link_bytes:
            self.send_bytes(dyn_link_bytes)
            result.n_inputs += 1
        if station_bytes:
            time.sleep(0.1)
            self.send_bytes(station_bytes)
            result.n_inputs += 1
        if dyn_storage_bytes:
            time.sleep(0.1)
            self.send_bytes(dyn_storage_bytes)
            result.n_inputs += 1

        # 后台泵等待 DLL 异步产出(0F33 通常在注入链路后 1~2 秒产出;
        # 0F44/0F22 在数传资源(0C12+0C15)注入后继续异步规划产出,
        # 须等其到齐,避免被静默窗口截断遗留到下一轮)
        expect_f44 = bool(link_bytes and station_bytes)
        for pkt in self._wait_plan(expect_f44=expect_f44):
            ptype = int.from_bytes(pkt[0:2], "big")
            result.packets.setdefault(ptype, []).append(pkt)
        _log.info("阶段1:输入%d帧, 收集 %s",
                  result.n_inputs,
                  {f"0x{k:04X}": len(v)
                   for k, v in result.packets.items()})

        # 若 expect_f44 但 0F44 仍未到,一次性推进星时到数传窗口内部触发 0F44。
        # 不再分步推进(分步每步等3s×5步=15s太慢),直接发一帧到 link窗口内部。
        if expect_f44 and result.count(0x0F44) == 0 and link_latest:
            target_t = max(adv_from, link_latest - 60)
            _log.info("阶段1:0F44未到,一次性推进星时到%d(%s)触发数传规划",
                      target_t, _epoch_to_bj_str(target_t))
            self.send_bytes(self.star_time_frame(target_t))
            result.n_inputs += 1
            self._phase2_last_t = target_t
            for pkt in self._wait_plan(
                    timeout=3.0,
                    only_type=0x0F44):
                ptype = int.from_bytes(pkt[0:2], "big")
                result.packets.setdefault(ptype, []).append(pkt)
            if result.count(0x0F44) == 0:
                # 再推进一步到 link_end 附近
                target_t2 = link_latest + 30
                _log.info("阶段1:0F44仍未到,推进到%d(%s)再试",
                          target_t2, _epoch_to_bj_str(target_t2))
                self.send_bytes(self.star_time_frame(target_t2))
                result.n_inputs += 1
                self._phase2_last_t = target_t2
                for pkt in self._wait_plan(
                        timeout=2.0,
                        only_type=0x0F44):
                    ptype = int.from_bytes(pkt[0:2], "big")
                    result.packets.setdefault(ptype, []).append(pkt)
            _log.info("阶段1(星时推进后):收集 %s",
                      {f"0x{k:04X}": len(v)
                       for k, v in result.packets.items()})

        # ---- 初始化阶段2上下文 ----
        self._phase2_active = True
        self._phase2_last_t = adv_from
        self._phase2_key_times = []
        self._phase2_triggered = set()
        self._phase2_dl_key_times: list[int] = []
        self._phase2_dl_triggered: set[int] = set()
        self._phase2_f33_seen: set[int] = set()
        self._phase2_f44_seen: set[int] = set()

        self._extract_f33_key_times(result)
        self._extract_f44_key_times(result)

        _log.info("阶段2就绪:推进起点=%d, 0F11关键点=%d个, 0F22关键点=%d个",
                  adv_from, len(self._phase2_key_times),
                  len(self._phase2_dl_key_times))

        result.advance_from = adv_from
        result.advance_to = (t_latest + ADVANCE_AFTER) if t_latest \
            else adv_from
        return result

    def _extract_f33_key_times(self, result: DllPlanResult,
                               current_t: int | None = None) -> None:
        """从 0F33 输出中提取成像规划成功(status=0x00)的成像开始时间,设0F11关键点。

        注:V2 实测 0F11 在阶段1即随 0F33 一并产出,关键点主要用于阶段2
        捕获可能的增量/迟到方案;其余状态(0x09 超时/0x0A 机动失败/0x07
        不可见等)均不产生 0F11,不设关键点。
        """
        try:
            from ..stk.packets import parse_0f33
            for f33_raw in result.all(0x0F33):
                seq = int.from_bytes(f33_raw[4:6], "big") if len(f33_raw) >= 6 else 0
                if seq in self._phase2_f33_seen:
                    continue
                self._phase2_f33_seen.add(seq)
                f33_info = parse_0f33(f33_raw)
                for t in f33_info.get("tasks") or []:
                    status = int(t.get("status", -1))
                    img_s = int(t.get("imaging_start", 0))
                    tgt_no = int(t.get("target_no", 0))
                    if status in F33_STATUS_IMAGING and img_s > 0:
                        kt = img_s - IMAGING_LEAD_SEC
                        if kt not in self._phase2_key_times:
                            self._phase2_key_times.append(kt)
                            _log.info("阶段2:目标%d 0F33可见(0x00), "
                                      "成像开始=%d(%s), 0F11关键点=%d(%s)",
                                      tgt_no, img_s, _epoch_to_bj_str(img_s),
                                      kt, _epoch_to_bj_str(kt))
                            if current_t is not None and kt <= current_t:
                                self._phase2_triggered.add(kt)
                    else:
                        _log.info("阶段2:目标%d 0F33 status=0x%02X,不生成0F11",
                                  tgt_no, status)
        except Exception as e:  # noqa: BLE001
            _log.warning("解析0F33失败: %s", e)

    def _extract_f44_key_times(self, result: DllPlanResult,
                               current_t: int | None = None) -> None:
        """从 0F44 输出中提取 status=0x00 的数传开始时间,设 0F22 关键点。"""
        try:
            from ..stk.packets import parse_0f44
            for f44_raw in result.all(0x0F44):
                seq = int.from_bytes(f44_raw[4:6], "big") if len(f44_raw) >= 6 else 0
                if seq in self._phase2_f44_seen:
                    continue
                self._phase2_f44_seen.add(seq)
                f44_info = parse_0f44(f44_raw)
                for t in f44_info.get("tasks") or f44_info.get("links") or []:
                    status = int(t.get("status", -1))
                    dl_s = int(t.get("datalink_start", 0))
                    if status in F44_STATUS_IMAGING and dl_s > 0:
                        kt = dl_s - DATALINK_LEAD_SEC
                        if kt not in self._phase2_dl_key_times:
                            self._phase2_dl_key_times.append(kt)
                            _log.info("阶段2:数传0F44可见(0x00), "
                                      "数传开始=%d(%s), 0F22关键点=%d(%s)",
                                      dl_s, _epoch_to_bj_str(dl_s),
                                      kt, _epoch_to_bj_str(kt))
                            if current_t is not None and kt <= current_t:
                                self._phase2_dl_triggered.add(kt)
        except Exception as e:  # noqa: BLE001
            _log.warning("解析0F44失败: %s", e)

    # ---------- 阶段2:星时推进(泵持续收集规划包) ----------

    def advance_star_time(self, current_sec: float,
                          step_delay_ms: int = 20) -> DllPlanResult:
        """阶段2:星时走动时把 DLL 星时推进到 current_sec,并取走泵新增的
        规划包(0F11/0F22/0F33/0F44)。

        输出泵在后台持续轮询,本方法只需:必要时补发关键时间点的 0B01、
        发送一帧 catch-up 到当前星时,然后从队列取走已到达的结果。
        大步跳变(修改时间/高倍速)也不会卡 UI。
        """
        result = DllPlanResult()
        if not self._phase2_active:
            return result

        t = int(current_sec)
        if t <= self._phase2_last_t:
            # 星时未前进,仍取走泵可能已缓存的包(如异步迟到的结果)
            for pkt in self.drain_output():
                result.packets.setdefault(
                    int.from_bytes(pkt[0:2], "big"), []).append(pkt)
            return result

        # 到达未触发的 0F11 关键点:补发该时刻星时帧 + 等待DLL产出
        for kt in sorted(self._phase2_key_times):
            if t >= kt and kt not in self._phase2_triggered \
                    and kt > self._phase2_last_t:
                _log.info("阶段2:触发0F11关键点 kt=%d(%s), 当前星时=%d(%s)",
                          kt, _epoch_to_bj_str(kt),
                          t, _epoch_to_bj_str(t))
                self.send_bytes(self.star_time_frame(kt))
                self._phase2_last_t = kt
                result.n_inputs += 1
                self._phase2_triggered.add(kt)
                # 等待 DLL 产出 0F11(最多2秒,DLL异步处理需要时间)
                self._wait_key_output(result, 0x0F11, 2.0)
                self._extract_f33_key_times(result, t)
                self._extract_f44_key_times(result, t)

        # 到达未触发的 0F22 关键点
        for kt in sorted(self._phase2_dl_key_times):
            if t >= kt and kt not in self._phase2_dl_triggered \
                    and kt > self._phase2_last_t:
                _log.info("阶段2:触发0F22关键点 kt=%d(%s)", kt,
                          _epoch_to_bj_str(kt))
                self.send_bytes(self.star_time_frame(kt))
                self._phase2_last_t = kt
                result.n_inputs += 1
                self._phase2_dl_triggered.add(kt)
                self._wait_key_output(result, 0x0F22, 2.0)
                self._extract_f33_key_times(result, t)
                self._extract_f44_key_times(result, t)

        # catch-up:发送当前星时帧让 DLL 跟上
        if t > self._phase2_last_t:
            self.send_bytes(self.star_time_frame(t))
            self._phase2_last_t = t
            result.n_inputs += 1
            time.sleep(min(step_delay_ms, 60) / 1000.0)
            self._collect_into(result)
            self._extract_f33_key_times(result, t)
            self._extract_f44_key_times(result, t)

        result.n_steps = len(self._phase2_triggered) + \
            len(self._phase2_dl_triggered)
        result.advance_from = 0
        result.advance_to = t
        if result.packets:
            _log.info("阶段2:星时=%d(%s), 新增输出 %s",
                      t, _epoch_to_bj_str(t),
                      {f"0x{k:04X}": len(v)
                       for k, v in result.packets.items()})
        return result

    def _wait_key_output(self, result: DllPlanResult,
                         target_type: int, timeout: float) -> None:
        """在关键点触发后等待DLL产出指定类型报文(阻塞轮询队列)。"""
        start = time.monotonic()
        while (time.monotonic() - start) < timeout:
            for pkt in self.drain_output():
                ptype = int.from_bytes(pkt[0:2], "big")
                result.packets.setdefault(ptype, []).append(pkt)
            if result.count(target_type) > 0:
                _log.info("阶段2:收到0x%04X ×%d条", target_type,
                          result.count(target_type))
                return
            time.sleep(0.05)
        _log.warning("阶段2:关键点等待0x%04X超时(%.1fs),无输出",
                     target_type, timeout)

    def _collect_into(self, result: DllPlanResult) -> None:
        for pkt in self.drain_output():
            result.packets.setdefault(
                int.from_bytes(pkt[0:2], "big"), []).append(pkt)

    def is_phase2_complete(self) -> bool:
        """阶段2是否所有关键时间点(0F11+0F22)都已触发。"""
        if not self._phase2_active:
            return True
        img_done = all(kt in self._phase2_triggered
                       for kt in self._phase2_key_times)
        dl_done = all(kt in self._phase2_dl_triggered
                      for kt in self._phase2_dl_key_times)
        return img_done and dl_done

    # ---------- 兼容旧接口:一次性计算 ----------

    def compute_plan(self, task_bytes: bytes,
                     link_bytes: bytes | None = None,
                     station_bytes: bytes | None = None,
                     orbit_frames: tuple[bytes, ...] = (),
                     star_base_sec: int | None = None,
                     advance_from: int | None = None,
                     advance_to: int | None = None,
                     step_sec: int = DEFAULT_STEP_SEC,
                     step_delay_ms: int = 20,
                     progress_cb=None) -> DllPlanResult:
        """兼容旧接口:一次性完成阶段1+阶段2。

        新代码应分别调用 compute_initial() + advance_star_time()。
        """
        result = self.compute_initial(
            task_bytes, link_bytes=link_bytes,
            station_bytes=station_bytes, orbit_frames=orbit_frames,
            star_base_sec=star_base_sec, step_delay_ms=step_delay_ms)

        if advance_from is not None:
            self._phase2_last_t = advance_from
        end_t = advance_to or result.advance_to
        step_result = self.advance_star_time(end_t, step_delay_ms=step_delay_ms)
        result.merge(step_result)
        _log.info("compute_plan(兼容) done: outputs=%s",
                  {f"0x{k:04X}": len(v) for k, v in result.packets.items()})
        return result
