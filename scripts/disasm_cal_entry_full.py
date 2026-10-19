"""完整反汇编 calOpticsTimeWindow 入口 0x1800017a0。

找所有 ret 与负值返回点。
"""
import sys
import pefile
from capstone import Cs, CS_ARCH_X86, CS_MODE_64

DLL = r"D:\wenxj\7-型号\zwxxx-3\1_文件\1_任务规划\4_测试相关文件\20260922星上测试DLL-2\20260922星上测试DLL-2\WeiNa2_star_win.dll"
ADDR = 0x1800017a0

pe = pefile.PE(DLL, fast_load=True)
ib = pe.OPTIONAL_HEADER.ImageBase
md = Cs(CS_ARCH_X86, CS_MODE_64); md.detail = True

def read_va(va, n):
    rva = va - ib
    for s in pe.sections:
        if s.VirtualAddress <= rva < s.VirtualAddress + s.Misc_VirtualSize:
            return s.get_data()[rva - s.VirtualAddress: rva - s.VirtualAddress + n]
    return b""

code = read_va(ADDR, 0x200)
ins = list(md.disasm(code, ADDR))

print("# === calOpticsTimeWindow @0x1800017a0 ===")
for i, inst in enumerate(ins):
    if inst.mnemonic in ("int3", "nop"): continue
    marker = ""
    if "0xfffffffe" in inst.op_str or "0xfffffffd" in inst.op_str:
        marker = "  <== -2 / -3?"
    if "0xffffffff" in inst.op_str:
        marker = "  <== -1"
    if inst.mnemonic == "mov" and "eax" in inst.op_str.split(",")[0]:
        import re
        m = re.match(r"eax, (0x[0-9a-fA-F]+)", inst.op_str)
        if m:
            v = int(m.group(1), 16)
            sv = v - 0x100000000 if v >= 0x80000000 else v
            marker = f"  <== eax={sv}"
    print(f"  [#{i:3d}] 0x{inst.address:x}:  {inst.mnemonic:8s} {inst.op_str}{marker}")
    if inst.mnemonic in ("ret", "retn"):
        break
