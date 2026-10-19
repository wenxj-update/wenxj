"""主链路编排:串联 解析 -> 可见性 -> 可见性报文 -> 指令 -> 模板比对。

订阅 EventBus 的 RAW_FRAME,产出 STK_MESSAGE/VISIBILITY_RESULT/
VISIBILITY_REPORT_FRAME/COMMAND_SEQUENCE/COMPARISON_RESULT。
是主链路总枢纽,各环节通过抽象接口注入,可独立替换(真实/Stub)。
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from ..core.event_bus import EventBus, Topics
from ..models.orbit import OrbitState, SatelliteClock
from ..models.target import TargetPoint
from ..models.packet import ParsedPacket
from ..models.command import CommandSequence
from ..models.comparison import ComparisonResult
from ..models.visibility import VisibilityResult
from ..algorithm.visibility import IVisibilityAlgorithm
from ..parsing.parser import FrameParser
from ..parsing.registry import FormatRegistry
from ..planning.command_gen import ICommandGenerator
from ..planning.template_compare import TemplateComparator
from ..planning.visibility_report import VisibilityReportBuilder, to_relative_seconds, EPOCH
from ..planning.templates import TEMPLATE_STUB_IMAGING
from ..stk.com_bridge import STK_EPOCH

_log = logging.getLogger("rwgh.planning.pipeline")

STK_MESSAGE_FORMAT = "stk_message"
VISIBILITY_REPORT_FORMAT = "visibility_report"


class Pipeline:
    """主链路编排器。"""

    def __init__(self, bus: EventBus,
                 registry: FormatRegistry,
                 parser: FrameParser,
                 visibility_algo: IVisibilityAlgorithm,
                 cmd_gen: ICommandGenerator,
                 comparator: TemplateComparator,
                 report_builder: VisibilityReportBuilder,
                 transport=None,
                 default_template: str = TEMPLATE_STUB_IMAGING) -> None:
        self.bus = bus
        self.registry = registry
        self.parser = parser
        self.visibility_algo = visibility_algo
        self.cmd_gen = cmd_gen
        self.comparator = comparator
        self.report_builder = report_builder
        self.transport = transport
        self.default_template = default_template
        self._vis_spec = registry.get(VISIBILITY_REPORT_FORMAT)
        # 真实场景目标(STK 加载后由 TARGET_SET 推送);空则用占位目标兜底
        self._targets: list[TargetPoint] = []
        # 时钟/轨道缓存:一个仿真节拍内 3 帧只触发一次可见性
        self._clock: Optional[SatelliteClock] = None
        self._orbit: list[OrbitState] = []
        self._orbit_packet_seen = False
        self._streaming = False   # 真实 STK 目标已下发,节拍以 A002 为准
        self._last_compute_secs: Optional[float] = None
        self._last_compute_had_orbit = False
        self._unsub: list = []

    def start(self) -> None:
        self._unsub.append(self.bus.subscribe(Topics.RAW_FRAME, self._on_frame))
        self._unsub.append(self.bus.subscribe(Topics.VISIBILITY_RESULT, self._on_visibility))
        self._unsub.append(self.bus.subscribe(Topics.TARGET_SET, self._on_target_set))
        _log.info("Pipeline started")

    def stop(self) -> None:
        for u in self._unsub:
            u()
        self._unsub.clear()

    def _on_target_set(self, targets: list) -> None:
        """接收 STK 场景真实地面目标(Target/Facility)。"""
        if isinstance(targets, (list, tuple)) and targets:
            self._targets = list(targets)
            self._streaming = True
            _log.info("pipeline: %d real targets cached (stream mode)",
                      len(self._targets))

    # ---------- RAW_FRAME -> 解析 -> 可见性 ----------

    def _on_frame(self, frame: bytes) -> None:
        spec = self.registry.detect(frame)
        if spec is None:
            _log.warning("no format detected for frame len=%d", len(frame))
            return
        try:
            pkt = self.parser.parse(frame, spec)
        except Exception as e:  # noqa: BLE001
            _log.error("parse frame failed: %s", e)
            return
        self.bus.publish(Topics.PARSED_PACKET, pkt)
        self.bus.publish(Topics.STK_MESSAGE, pkt)
        # 按真实包类型提取业务数据并驱动可见性
        self._dispatch_stk_packet(pkt)

    def _dispatch_stk_packet(self, pkt: ParsedPacket) -> None:
        """按包类型(packet_type)分发:星时/轨道根数/轨道数据。

        真实节拍顺序:0x0B01(星时) -> 0xA012(根数) -> 0xA002(轨道数据),
        三帧同一仿真整秒,只在该秒触发一次可见性(在 A002 帧触发,此时
        时钟+轨道齐备);单包/测试链路(无 A002)时由 0x0B01 兜底触发。
        """
        ptype = pkt.get("packet_type")
        if ptype is None:
            return
        # 统一:从包中提取时间(星时用 time_seconds,轨道用 epoch_seconds)
        secs = pkt.get("time_seconds") or pkt.get("epoch_seconds") or 0
        secs = float(secs)
        current = STK_EPOCH + timedelta(seconds=secs)
        clock = SatelliteClock(epoch=STK_EPOCH, current=current,
                               clock_count=int(secs))

        # 是否需要计算:
        # - 0x0B01:尚未建立节拍(无 A002 历史,如单包测试)时兜底;同秒不重复
        # - 0xA012:只刷新时钟
        # - 0xA002:节拍最后一帧;若该秒已由 B01 无轨道兜底算过,则带轨道重算一次
        should_compute = False
        if ptype == 0x0B01:
            self._clock = clock
            # 真实推流(目标已下发)等 A002;无目标单包测试时 B01 兜底
            if (not self._streaming and not self._orbit_packet_seen
                    and secs != self._last_compute_secs):
                should_compute = True
        elif ptype == 0xA012:
            self._clock = clock
        elif ptype == 0xA002:
            self._clock = clock
            self._orbit_packet_seen = True
            self._orbit = self._orbit_from_packet(pkt, current)
            should_compute = (secs != self._last_compute_secs
                              or not self._last_compute_had_orbit)

        if not should_compute:
            return
        self._last_compute_secs = secs
        self._last_compute_had_orbit = bool(self._orbit)

        targets = self._targets or [
            TargetPoint(id="placeholder", lon=0.0, lat=0.0)]
        results = self.visibility_algo.compute(
            targets, list(self._orbit), self._clock or clock)
        self.bus.publish(Topics.VISIBILITY_RESULT, results)

    @staticmethod
    def _orbit_from_packet(pkt: ParsedPacket,
                           current: datetime) -> list[OrbitState]:
        """从 0xA002 解析字段构造 J2000 轨道状态(报文 m/m/s -> km、km/s)。"""
        ox = pkt.get("j2k_x", 0.0)
        if not ox:
            return []
        return [OrbitState(
            time=current,
            x=float(pkt.get("j2k_x", 0.0)) / 1000.0,
            y=float(pkt.get("j2k_y", 0.0)) / 1000.0,
            z=float(pkt.get("j2k_z", 0.0)) / 1000.0,
            vx=float(pkt.get("j2k_vx", 0.0)) / 1000.0,
            vy=float(pkt.get("j2k_vy", 0.0)) / 1000.0,
            vz=float(pkt.get("j2k_vz", 0.0)) / 1000.0,
        )]

    # ---------- VISIBILITY_RESULT -> 报文/指令/比对 ----------

    def _on_visibility(self, results: list) -> None:
        if not isinstance(results, list):
            results = [results]
        for r in results:
            # 1) 可见性报文回送
            frames = self.report_builder.build_all(r, self._vis_spec)
            for fr in frames:
                self.bus.publish(Topics.VISIBILITY_REPORT_FRAME, fr)
                if self.transport is not None:
                    try:
                        self.transport.send(fr)
                    except Exception as e:  # noqa: BLE001
                        _log.error("transport.send failed: %s", e)
            # 2) 指令生成
            seq = self.cmd_gen.generate(r, template_hint=self.default_template)
            self.bus.publish(Topics.COMMAND_SEQUENCE, seq)
            # 3) 模板比对
            cmp = self.comparator.compare(seq, self.default_template)
            self.bus.publish(Topics.COMPARISON_RESULT, cmp)


class MockPipelineDriver:
    """MVP/测试用:直接注入原始帧到总线,跳过真实 TCP。"""

    def __init__(self, bus: EventBus) -> None:
        self.bus = bus

    def inject_frame(self, frame: bytes) -> None:
        self.bus.publish(Topics.RAW_FRAME, frame)

    def inject_bytes(self, data: bytes) -> None:
        """模拟粘包字节流注入(配合 Framer 测试)。"""
        self.bus.publish(Topics.RAW_FRAME, data)
