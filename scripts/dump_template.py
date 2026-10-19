"""打印真实模板"多目标成像记录"的所有指令。"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from rwgh.planning.template_loader import load_templates_from_xlsm

t = load_templates_from_xlsm(r"D:\wenxj\7-型号\zwxxx-3\1_文件\1_任务规划\4_测试相关文件\指令模板_20260918.xlsm")
tmpl = t["多目标成像记录"]
print(f"# 模板: {tmpl.name}, {len(tmpl.expected)} 条指令")
for i, c in enumerate(tmpl.expected):
    cw = c.codeword.hex() if c.codeword else "(无)"
    print(f"  #{i:2d} t={c.time_tag:8.1f}  cw={cw:20s}  name={c.name!r}  sub={c.sub_header!r}  main={c.main_header!r}")
