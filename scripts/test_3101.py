# -*- coding: utf-8 -*-
"""验证 3101 组帧+解析往返。"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from rwgh.stk.packets import StkPacketBuilder, parse_3101, parse_utcg
from rwgh.models.target import TargetPoint
from rwgh.parsing.parser import FrameParser
from rwgh.parsing.registry import FormatRegistry
from rwgh.parsing.loader import load_dir

reg = FormatRegistry()
load_dir("config/formats", reg)
parser = FrameParser()
b = StkPacketBuilder(reg, parser)
targets = [
    TargetPoint(id="11-100", lon=120.4, lat=23.44, alt=0),
    TargetPoint(id="13-10", lon=120.516, lat=24.288, alt=0),
    TargetPoint(id="kashi_01", lon=75.7, lat=39.468, alt=0),
]
frame = b.target_input_frame(targets, earliest=parse_utcg("1 Oct 2026 02:00:00.000"))
print(f"frame len={len(frame)} (expect 46+27*3={46+27*3})")
print("hex:", frame.hex(" ").upper()[:80])
d = parse_3101(frame)
print(f"target_count={d['target_count']}, targets:")
for t in d["targets"]:
    print(f"  id={t['target_id']}, lon={t['lon']:.6f}, lat={t['lat']:.6f}")
print("ROUNDTRIP OK" if d["target_count"] == 3 else "FAIL")
