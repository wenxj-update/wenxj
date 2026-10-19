"""反汇编 DllInput 入口,看参数#2 (type code) 的分支。"""
import sys
import pefile
from capstone import Cs, CS_ARCH_X86, CS_MODE_64

DLL = r"D:\wenxj\7-型号\zwxxx-3\1_文件\1_任务规划\4_测试相关文件\20260922星上测试DLL-2\20260922星上测试DLL-2\WeiNa2_star_win.dll"

# 先找 DllInput 的地址
pe = pefile.PE(DLL, fast_load=True)
pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_EXPORT']])
exp = pe.DIRECTORY_ENTRY_EXPORT
addr_input = None
for sym in exp.symbols:
    name = sym.name if isinstance(sym.name, str) else sym.name.decode()
    if name == "DllInput":
        addr_input = pe.OPTIONAL_HEADER.ImageBase + sym.address
        break
print(f"DllInput @ 0x{addr_input:x}")

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

code = read_va(addr_input, 0x400)
ins = list(md.disasm(code, addr_input))

print("# === DllInput full disasm ===")
for i, inst in enumerate(ins[:60]):
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
    print(f"  [#{i:3d}] 0x{inst.address:x}:  {inst.mnemonic:8s} {inst.op_str}{marker}")
    if inst.mnemonic in ("ret", "retn"):
        break

# 顺带看 0x180035ae0(DllInput 调用的核心函数)
print(f"\n# === 0x180035ae0 (DllInput calls this) ===")
code2 = read_va(0x180035ae0, 0x400)
ins2 = list(md.disasm(code2, 0x180035ae0))
for i, inst in enumerate(ins2[:50]):
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
    print(f"  [#{i:3d}] 0x{inst.address:x}:  {inst.mnemonic:8s} {inst.op_str}{marker}")
    if inst.mnemonic in ("ret", "retn"):
        break
