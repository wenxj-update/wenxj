"""反汇编 0x18012de60,看它是什么函数。"""
import sys
import pefile
from capstone import Cs, CS_ARCH_X86, CS_MODE_64

DLL = r"D:\wenxj\7-型号\zwxxx-3\1_文件\1_任务规划\4_测试相关文件\20260922星上测试DLL-2\20260922星上测试DLL-2\WeiNa2_star_win.dll"
ADDR = 0x18012de60

pe = pefile.PE(DLL, fast_load=True)
ib = pe.OPTIONAL_HEADER.ImageBase
md = Cs(CS_ARCH_X86, CS_MODE_64); md.detail = True

def read_va(va, n):
    rva = va - ib
    for s in pe.sections:
        if s.VirtualAddress <= rva < s.VirtualAddress + s.Misc_VirtualSize:
            return s.get_data()[rva - s.VirtualAddress: rva - s.VirtualAddress + n]
    return b""

def read_cstr(va, n=512):
    b = read_va(va, n)
    if b"\x00" in b: b = b[:b.index(b"\x00")]
    try: return b.decode("gbk")
    except: return b.decode("ascii", errors="replace")

code = read_va(ADDR, 0x500)
ins = list(md.disasm(code, ADDR))

print("# === 0x18012de60 ===")
for i, inst in enumerate(ins[:80]):
    if inst.mnemonic in ("int3", "nop"): continue
    marker = ""
    if inst.mnemonic == "lea" and "rip" in inst.op_str:
        import re
        m = re.search(r"\[rip\s*\+\s*(0x[0-9a-fA-F]+)\]", inst.op_str)
        if m:
            next_va = inst.address + inst.size
            target_va = next_va + int(m.group(1), 16)
            s = read_cstr(target_va)
            if s and len(s) > 1:
                marker = f"  STR={s!r}"
    if "0xfffffffe" in inst.op_str:
        marker += "  <== -2"
    if "0xffffffff" in inst.op_str:
        marker += "  <== -1"
    print(f"  [#{i:3d}] 0x{inst.address:x}:  {inst.mnemonic:8s} {inst.op_str}{marker}")
    if inst.mnemonic in ("ret", "retn"):
        break
