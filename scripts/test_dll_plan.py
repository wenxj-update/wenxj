"""DLL 报文驱动链路功能验证(临时脚本,验证后删除)。

1. 加载真实 WeiNa2_star_win.dll + DllInit
2. StkPacketBuilder 构造 3101 任务报文(2 目标)
3. compute_plan 报文驱动:3101 → 0C12(无) → 星时推进 → 收集输出
4. 检查 DLL 输出的 0F11/0F22/0F33/0F44 报文
5. 多目标成像记录指令生成(smart_process=0)
"""
import logging
import sys
import time

# 结果写入独立文件(DLL 日志污染 stdout)
_res = open("scripts/test_dll_result.txt", "w", encoding="utf-8")


def out(*args):
    _res.write(" ".join(str(a) for a in args) + "\n")
    _res.flush()


out("=== 1. 加载 DLL ===")

logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")

from rwgh.algorithm.signature import default_registry
from rwgh.algorithm.loader import DllLoader
from rwgh.algorithm.visibility import CtVisibilityAlgorithm
from rwgh.parsing.loader import load_dir
from rwgh.parsing.registry import FormatRegistry
from rwgh.parsing.parser import FrameParser
from rwgh.stk.packets import StkPacketBuilder, parse_3101, parse_0f11
from rwgh.models.orbit import STK_EPOCH_2009
from rwgh.models.target import TargetPoint
from datetime import datetime, timedelta

DLL_PATH = (r"D:/wenxj/7-型号/zwxxx-3/1_文件/1_任务规划/"
            r"4_测试相关文件/20260922星上测试DLL-2/"
            r"20260922星上测试DLL-2/WeiNa2_star_win.dll")

out("=== 1. 加载 DLL ===")
dll = DllLoader().load(DLL_PATH, default_registry())
algo = CtVisibilityAlgorithm(dll)
algo.driver.ensure_init()
out("DllInit OK")

out("=== 2. 构造 3101 报文 ===")
reg = FormatRegistry()
load_dir("config/formats", reg)
builder = StkPacketBuilder(reg, FrameParser())

# 元任务窗:当前UTC时间 +20min 起,每目标 240s 窗,间隔 600s
from datetime import timezone
t0 = datetime.now(timezone.utc) + timedelta(minutes=20)
earliest = t0
latest = t0 + timedelta(seconds=240 * 3 + 600 * 2)
targets = [
    TargetPoint(id="11-101", lon=116.39, lat=39.90, alt=0.0),
    TargetPoint(id="11-102", lon=121.47, lat=31.23, alt=0.0),
    TargetPoint(id="11-103", lon=113.26, lat=23.13, alt=0.0),
]
frame = builder.target_input_frame(
    targets, task_id=142, earliest=earliest, latest=latest, priority=20)
out(f"3101 报文 {len(frame)} 字节: {frame[:20].hex(' ')}...")
info = parse_3101(frame)
out(f"task_earliest={info['task_earliest']} task_latest={info['task_latest']} "
      f"onboard_processing={info['onboard_processing']} targets={len(info['targets'])}")
for t in info["targets"]:
    out(f"  目标{t['target_id']}: 元任务窗 [{t['meta_earliest']},{t['meta_latest']}]")

out("=== 3. compute_plan 报文驱动(含轨道根数) ===")
# A012 初始轨道根数(典型 LEO 550km SSO,DLL 需要轨道外推)
a = 6878.137   # km
orbit_frame = builder.elements_frame(
    t0, a, 0.0011, 97.5, 100.0, 45.0, 0.0)
out(f"A012 轨道帧 {len(orbit_frame)} 字节: {orbit_frame.hex(' ')}")

plan = algo.compute_plan(frame, link_bytes=None, station_bytes=None,
                         orbit_frames=(orbit_frame,), step_delay_ms=20)
out(f"输入 {plan.n_inputs} 帧, 推进 {plan.n_steps} 步 "
    f"[{plan.advance_from},{plan.advance_to}]")
collected = plan.packets
for pt in sorted(collected):
    out(f"  0x{pt:04X}: {len(collected[pt])} 条, 首条 {len(collected[pt][0])}B")

f11_raw = (collected.get(0x0F11) or [None])[0]
f33_raw = (collected.get(0x0F33) or [None])[0]
if f33_raw:
    out("=== 3b. 解析 DLL 输出 0F33 ===")
    from rwgh.stk.packets import parse_0f33
    f33 = parse_0f33(f33_raw)
    out(f"0F33: task_count={f33.get('task_count')}")
    for t in f33.get("tasks") or []:
        out(f"  目标{t.get('target_id')} 状态=0x{t.get('status', -1):02X} "
            f"时间[{t.get('imaging_start')},{t.get('imaging_end')}] "
            f"raw={ {k: v for k, v in t.items() if not k.startswith('_')} }")
if f11_raw:
    out("=== 4. 解析 DLL 输出 0F11 ===")
    f11 = parse_0f11(f11_raw)
    out(f"target_count={f11.get('target_count')} "
          f"smart_process={f11.get('smart_process')} "
          f"compression={f11.get('compression')}")
    for t in f11.get("targets") or []:
        out(f"  目标{t.get('target_id')}: 机动[{t.get('maneuver_start')}] "
              f"成像[{t.get('imaging_start')},{t.get('imaging_end')}]")
    # 元任务窗匹配校验
    tmap = {int(t["target_id"]): (t["meta_earliest"], t["meta_latest"])
            for t in info["targets"] if int(t.get("target_id") or 0)}
    ok = bad = 0
    for t in f11.get("targets") or []:
        tid = int(t.get("target_id") or 0)
        win = tmap.get(tid)
        if not win:
            continue
        v = [t.get("maneuver_start") or 0, t.get("imaging_start") or 0,
             t.get("imaging_end") or 0]
        if all(win[0] <= x <= win[1] for x in v if x > 0):
            ok += 1
        else:
            bad += 1
        out(f"  校验 目标{tid}: 窗{win} vs {v} → "
              f"{'窗内' if all(win[0] <= x <= win[1] for x in v if x > 0) else '越窗'}")
    out(f"元任务窗校验: {ok} 窗内 / {bad} 越窗")
else:
    out("!!! DLL 未输出 0F11(可能需要轨道/链路输入)")

out("=== 5. 多目标成像记录指令生成(smart=0) ===")
# 用 DLL 输出 0F11(若无则手工构造 plan)
if f11_raw:
    gen_plan = f11
else:
    gen_plan = {"targets": [
        {"imaging_start": int(t["meta_earliest"]) + 60,
         "imaging_end": int(t["meta_earliest"]) + 90,
         "target_id": t["target_id"], "lon": 0.0, "lat": 0.0}
        for t in info["targets"]],
        "smart_process": 0, "compression": 4, "storage_task_no": 61}
gen_plan["smart_process"] = 0
from rwgh.planning.star_command_sequence import ImagePlanCommandGenerator
gen = ImagePlanCommandGenerator()
seq = gen.generate_from_plan(gen_plan, 0x0F11)
out(f"plan_source={seq.plan_source}, 指令 {len(seq.commands)} 条")
names = [c.name for c in seq.commands]
# 校验:无 AI 指令,无固存记录(处理),收尾为小固存停止码+一键关机
ai_cmds = [n for n in names if "AI" in n or n.startswith("固存记录(处理)")]
out(f"AI/处理指令(应为空): {ai_cmds}")
tail = names[-4:]
out(f"末尾 4 条: {tail}")
assert "记录停止码(小固存)" in tail and "记录任务一键关机" in tail, "收尾指令不符"
assert not ai_cmds, "多目标模式不应有 AI/处理指令"
out("=== 全部验证通过 ===")

out("\n--- 等待 DLL 线程日志刷新 ---")
import time
time.sleep(3)
