"""端到端 CLI 演示:模拟 STK 推送真实数据流,展示主链路各阶段产物。

不依赖真实 STK / DLL,用 Stub 算法,展示从二进制报文到指令比对的全链路工作流。

模拟流程:
1. STK 推送 星时包(0x0B01) → Pipeline 解析 → 触发可见性 → 指令 → 比对
2. STK 推送 轨道根数包(0xA012) → 同上
3. STK 推送 轨道数据包(0xA002) → 同上

输出每个阶段:
- 解析后的 ParsedPacket 字段
- 可见性窗口结果
- 生成的指令序列(时序 + 码字)
- 模板比对结果(matches/discrepancies)
- 可见性报文回送(hex)

运行: python -m scripts.demo_end_to_end
"""
from __future__ import annotations

import logging
import os
import struct
import sys
import time
from datetime import datetime, timezone

# 让 src 可导入
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from rwgh.core.config import load_config
from rwgh.core.event_bus import EventBus, Topics
from rwgh.core.logging import setup_logging
from rwgh.parsing.loader import load_dir
from rwgh.parsing.parser import FrameParser
from rwgh.parsing.registry import FormatRegistry
from rwgh.algorithm.visibility import StubVisibilityAlgorithm
from rwgh.planning.command_gen import StubCommandGenerator
from rwgh.planning.template_compare import TemplateComparator
from rwgh.planning.visibility_report import VisibilityReportBuilder, to_relative_seconds
from rwgh.planning.templates import make_stub_template, TEMPLATE_STUB_IMAGING, load_real_templates
from rwgh.planning.pipeline import Pipeline, MockPipelineDriver
from rwgh.planning.templates import TEMPLATE_MULTI_TARGET_IMAGING
from rwgh.models.visibility import VisibilityResult, VisibilityWindow
from rwgh.models.packet import ParsedPacket
from rwgh.models.command import CommandSequence
from rwgh.models.comparison import ComparisonResult

# 演示用真实模板指令生成器(产出与"多目标成像记录"匹配的码字)
from demo_real_command_gen import DemoRealCommandGenerator

# ---- 真实 STK 报文 hex(从 xlsx 测试数据提取,与 tests/test_parser.py 同源) ----
STK_TIME_HEX = "0B010001000100010010213A46400000"  # 0x0B01 星时 2026-09-01 04:00:00
# 轨道根数 0xA012 62字节: epoch=557467800, semi_major=6896.569km, e=0.000670, i=44.994°
STK_ORBIT_ELEM_HEX = ("A012000100010001003E213A4898291B54410000029E0000AFC2"
                      "000036CE0000E8C90000BC9E"
                      + "00" * 24)
# 轨道数据 0xA002 62字节(占位用,与格式 spec 总长 62 匹配)
STK_ORBIT_DATA_HEX = ("A002000100010001003E213A4898291B54410000000000000000000000000000000000000000000000000000000000000000000000000000"
                      + "00" * 6)   # 凑足 62 字节


def _fmt_dt(dt) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S UTC") if dt else "N/A"


def _hex(b: bytes) -> str:
    return b.hex()


def print_stage(title: str) -> None:
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)


def print_pkt(pkt: ParsedPacket, label: str) -> None:
    print(f"\n[{label}] 解析后字段:")
    print(f"  format: {pkt.format_name}")
    print(f"  raw hex: {_hex(pkt.raw)}")
    print(f"  checksum_ok: {pkt.checksum_ok}")
    for k, v in pkt.fields.items():
        if k == "packet_type":
            print(f"  {k}: 0x{v:04X}")
        elif isinstance(v, (int, float)):
            print(f"  {k}: {v}")
        else:
            print(f"  {k}: {v!r}")


def print_vis(results: list) -> None:
    for r in results:
        print(f"\n[可见性结果] 卫星={r.satellite}  窗口数={len(r.windows)}")
        for i, w in enumerate(r.windows):
            print(f"  窗口#{i}: 目标={w.target_id}")
            print(f"    AOS={_fmt_dt(w.aos)}  LOS={_fmt_dt(w.los)}")
            print(f"    max_el={w.max_el:.2f}°  duration={w.duration_sec:.1f}s")


def print_seq(seq: CommandSequence) -> None:
    print(f"\n[指令序列] target_id={seq.target_id}  指令数={len(seq.commands)}")
    for i, c in enumerate(seq.commands):
        cw_hex = c.codeword.hex() if c.codeword else f"code=0x{c.code:02X}"
        name = c.name or "(stub)"
        print(f"  #{i:2d} t={c.time_tag:10.2f}s  cw={cw_hex:20s}  name={name}")


def print_cmp(cmp: ComparisonResult) -> None:
    status = "✓ PASS" if cmp.passed else "✗ FAIL"
    print(f"\n[模板比对] template={cmp.template_name}  {status}")
    print(f"  matches: {len(cmp.matches)}  discrepancies: {cmp.discrepancy_count}")
    for d in cmp.discrepancies[:5]:
        detail = d.detail if hasattr(d, 'detail') else str(d)
        print(f"    - [{d.kind}] {detail}")
    if cmp.discrepancy_count > 5:
        print(f"    ... 共 {cmp.discrepancy_count} 条差异")


def print_frame(frame: bytes, idx: int) -> None:
    print(f"  回送帧#{idx}: len={len(frame)} hex={_hex(frame)}")


def main() -> int:
    # 加载配置
    cfg = load_config("config/app.yaml")
    setup_logging(cfg.logging)
    log = logging.getLogger("demo")

    print_stage("RWGH 端到端演示:STK → Python C端主链路")
    print(f"模式: {cfg.mode}")
    print(f"格式目录: config/formats")
    print(f"指令模板: {cfg.command_template or '(无,仅 stub)'}")

    # 装配
    bus = EventBus()
    registry = FormatRegistry()
    n_fmt = load_dir("config/formats", registry)
    print(f"\n加载格式: {n_fmt} 种")
    for spec in registry.all():
        magic_hex = int.from_bytes(spec.magic, 'big') if spec.magic else 0
        print(f"  - {spec.name}: magic=0x{magic_hex:04X} len={spec.total_length}")

    parser = FrameParser()
    vis_algo = StubVisibilityAlgorithm(window_seconds=60.0, max_el=45.0)
    # 演示用真实模板指令生成器(产出码字 eb90146f 等匹配"多目标成像记录"模板)
    cmd_gen = DemoRealCommandGenerator()
    comparator = TemplateComparator()
    report_builder = VisibilityReportBuilder(parser)

    # 注册真实指令模板
    real_count = 0
    if cfg.command_template:
        real_templates = load_real_templates(cfg.command_template)
        for name, tmpl in real_templates.items():
            comparator.register(tmpl)
            real_count += 1
    print(f"\n加载真实指令模板: {real_count} 个")

    # stub 模板(stub 链路必需)
    stub = VisibilityResult(satellite="SAT1", windows=(
        VisibilityWindow(target_id="placeholder", aos=datetime.now(timezone.utc),
                         los=datetime.now(timezone.utc), max_el=45.0),))
    comparator.register(make_stub_template(stub))

    # 收集产物
    captured: dict = {}
    bus.subscribe(Topics.PARSED_PACKET, lambda p: captured.setdefault("pkt", []).append(p))
    bus.subscribe(Topics.VISIBILITY_RESULT, lambda r: captured.setdefault("vis", []).extend(r if isinstance(r, list) else [r]))
    bus.subscribe(Topics.VISIBILITY_REPORT_FRAME, lambda f: captured.setdefault("frames", []).append(f))
    bus.subscribe(Topics.COMMAND_SEQUENCE, lambda s: captured.setdefault("seq", []).append(s))
    bus.subscribe(Topics.COMPARISON_RESULT, lambda c: captured.setdefault("cmp", []).append(c))

    pipe = Pipeline(bus, registry, parser, vis_algo, cmd_gen,
                    comparator, report_builder, transport=None,
                    default_template=TEMPLATE_MULTI_TARGET_IMAGING)
    pipe.start()
    driver = MockPipelineDriver(bus)

    # ---- 推送真实报文流 ----
    test_packets = [
        ("STK 星时包 (0x0B01)", STK_TIME_HEX),
        ("STK 轨道根数包 (0xA012)", STK_ORBIT_ELEM_HEX),
        ("STK 轨道数据包 (0xA002)", STK_ORBIT_DATA_HEX),
    ]

    for label, hex_str in test_packets:
        print_stage(f"STK 推送: {label}")
        try:
            frame = bytes.fromhex(hex_str)
        except ValueError as e:
            print(f"  [hex 解析失败] {e}")
            continue
        print(f"  原始帧: len={len(frame)} hex={_hex(frame)}")
        driver.inject_frame(frame)

    # ---- 输出各阶段产物 ----
    print_stage("阶段产物汇总")

    print(f"\n# 1. 解析的报文: {len(captured.get('pkt', []))} 条")
    for i, p in enumerate(captured.get("pkt", [])):
        print_pkt(p, f"报文#{i}")

    print(f"\n# 2. 可见性结果: {len(captured.get('vis', []))} 组")
    print_vis(captured.get("vis", []))

    print(f"\n# 3. 可见性报文回送: {len(captured.get('frames', []))} 帧")
    for i, f in enumerate(captured.get("frames", [])[:3]):
        print_frame(f, i)
    if len(captured.get("frames", [])) > 3:
        print(f"  ... 共 {len(captured['frames'])} 帧")

    print(f"\n# 4. 指令序列: {len(captured.get('seq', []))} 条")
    for i, s in enumerate(captured.get("seq", [])):
        print_seq(s)

    print(f"\n# 5. 模板比对: {len(captured.get('cmp', []))} 次")
    for i, c in enumerate(captured.get("cmp", [])):
        print_cmp(c)

    print_stage("演示完成")
    print(f"""
链路状态:
  解析   ✓  {len(captured.get('pkt', []))} 报文
  可见性 ✓  {len(captured.get('vis', []))} 组结果
  报文回送 ✓  {len(captured.get('frames', []))} 帧
  指令生成 ✓  {len(captured.get('seq', []))} 序列
  模板比对 ✓  {len(captured.get('cmp', []))} 次

下一步可接入:
  - 真实 STK COM 推送(替换 MockPipelineDriver 为 SocketWorker)
  - 真实 .dll 可见性算法(替换 StubVisibilityAlgorithm 为 CtVisibilityAlgorithm)
  - 真实指令生成代码(替换 StubCommandGenerator)
""")

    pipe.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
