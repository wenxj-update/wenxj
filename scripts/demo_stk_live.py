# -*- coding: utf-8 -*-
"""真实 STK 12 -> Python C端 实时链路 CLI 验证(无 GUI)。

附加已运行的 STK(或新启),加载 zw.sc,按节拍:
  STK COM 取数 -> 组 0x0B01/0xA012/0xA002 真实帧 -> 总线
  -> 解析 -> 可见性(真实 9 个地面目标) -> 报文 -> 指令 -> 模板比对
用法: python scripts/demo_stk_live.py [节拍数, 默认3]
"""
from __future__ import annotations

import logging
import os
import sys
from datetime import timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from rwgh.core.config import load_config
from rwgh.core.event_bus import EventBus, Topics
from rwgh.parsing.loader import load_dir
from rwgh.parsing.parser import FrameParser
from rwgh.parsing.registry import FormatRegistry
from rwgh.algorithm.visibility import StubVisibilityAlgorithm
from rwgh.planning.command_gen import StubCommandGenerator
from rwgh.planning.template_compare import TemplateComparator
from rwgh.planning.visibility_report import VisibilityReportBuilder
from rwgh.planning.pipeline import Pipeline
from rwgh.stk.com_bridge import StkComBridge
from rwgh.stk.packets import StkPacketBuilder, parse_utcg, format_utcg

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")

ROOT = os.path.join(os.path.dirname(__file__), "..")


def main(ticks: int = 3) -> int:
    cfg = load_config(os.path.join(ROOT, "config", "app.yaml"))
    bus = EventBus()
    reg = FormatRegistry()
    load_dir(os.path.join(ROOT, "config", "formats"), reg)
    parser = FrameParser()
    pipe = Pipeline(bus, reg, parser, StubVisibilityAlgorithm(),
                    StubCommandGenerator(), TemplateComparator(),
                    VisibilityReportBuilder(parser))
    pipe.start()

    evidence: dict = {"packets": [], "vis": [], "frames": 0, "seq": 0}
    bus.subscribe(Topics.PARSED_PACKET,
                  lambda p: evidence["packets"].append(p))
    def _collect_vis(r):
        evidence["vis"].append(r if isinstance(r, list) else [r])
    bus.subscribe(Topics.VISIBILITY_RESULT, _collect_vis)
    bus.subscribe(Topics.VISIBILITY_REPORT_FRAME,
                  lambda f: evidence.__setitem__("frames", evidence["frames"] + 1))
    bus.subscribe(Topics.COMMAND_SEQUENCE,
                  lambda s: evidence.__setitem__("seq", evidence["seq"] + 1))

    bridge = StkComBridge(cfg.stk)
    bridge.start_application(visible=True)
    bridge.load_scenario(cfg.stk.scenario_path)

    start_str, stop_str = bridge.scenario_period()
    start_dt = parse_utcg(start_str)
    period = (parse_utcg(stop_str) - start_dt).total_seconds()
    sats = bridge.satellite_names()
    sat_name = sats[0]
    tset = bridge.list_targets()
    bus.publish(Topics.TARGET_SET, list(tset.points))
    print(f"\n[场景] {sat_name} | 目标 {len(tset.points)} 个:")
    for t in tset.points:
        print(f"   {t.id:10s} lon={t.lon:9.4f} lat={t.lat:9.4f} alt={t.alt*1000:.1f}m")

    builder = StkPacketBuilder(reg, FrameParser())
    step = cfg.stk.step_seconds

    print(f"\n[推流] {ticks} 个节拍, 每拍 {step:.0f}s 仿真时间")
    for i in range(ticks):
        cur = (i + 1) * step
        bridge.set_current_time(cur)
        dt = start_dt + timedelta(seconds=cur)
        utc = format_utcg(dt)
        st = bridge.satellite_state(sat_name, utc)
        e = st["elements"]
        for fr in (
            builder.time_frame(dt),
            builder.elements_frame(dt, e[0], e[1], e[2], e[3], e[4], e[5]),
            builder.orbit_data_frame(dt, st["fix_pos"], st["fix_vel"],
                                     st["j2k_pos"], st["j2k_vel"]),
        ):
            bus.publish(Topics.RAW_FRAME, fr)
        print(f"  tick {i+1}: {utc[0:20]} J2K=({st['j2k_pos'][0]:.1f},"
              f"{st['j2k_pos'][1]:.1f},{st['j2k_pos'][2]:.1f}) km "
              f"sma={e[0]:.3f}km inc={e[2]:.3f}°")

    # 附加的是用户已打开的 STK,演示结束不关闭它(进程退出自动 CoUninitialize)
    # bridge.close()

    print("\n========== 链路证据 ==========")
    print(f"解析数据包: {len(evidence['packets'])}")
    ptypes = {}
    for p in evidence["packets"]:
        k = f"0x{p.fields['packet_type']:04X}"
        ptypes[k] = ptypes.get(k, 0) + 1
    print("  包类型分布:", ptypes)
    print(f"可见性结果批次: {len(evidence['vis'])}")
    if evidence["vis"]:
        last_result = evidence["vis"][-1][0]
        wins = last_result.windows
        print(f"  末批窗口数: {len(wins)} (真实目标数 {len(tset.points)})")
        print("  窗口目标:", [w.target_id for w in wins])
    print(f"可见性报文帧: {evidence['frames']}")
    print(f"指令序列批次: {evidence['seq']}")

    ok = (len(evidence["packets"]) == ticks * 3
          and evidence["vis"]
          and len(evidence["vis"][-1][0].windows) == len(tset.points)
          and evidence["frames"] > 0 and evidence["seq"] > 0)
    print("\nLIVE STK E2E:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    sys.exit(main(n))
