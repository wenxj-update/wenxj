"""反汇编 0x18002ab90,DllInput 的数据解析核心。

lea rdx, [rsp+0x40]    # local buf(包含复制的数据)
mov ecx, [rip+0x253bf6] # 某全局变量值作为参数#1(int32)
call 0x18002ab90        # 解析数据
"""
import sys
import pefile
from capstone import Cs, CS_ARCH_X86, CS_MODE_64

DLL = r"D:\wenxj\7-型号\zwxxx-3\1_文件\1_任务规划\4_测试相关文件\20260922星上测试DLL-2\20260922星上测试DLL-2\WeiNa2_star_win.dll"
ADDR = 0x18002ab90

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

code = read_va(ADDR, 0x1000)
ins = list(md.disasm(code, ADDR))

print("# === 0x18002ab90 first 80 instructions ===")
for i in range(min(80, len(ins))):
    inst = ins[i]
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
    if inst.mnemonic == "call":
        marker += "  <== CALL"
    # 标记 cmp(类型分发)
    if inst.mnemonic == "cmp":
        marker += "  <== CMP"
    print(f"  [#{i:3d}] 0x{inst.address:x}:  {inst.mnemonic:8s} {inst.op_str}{marker}")
    if inst.mnemonic in ("ret", "retn"):
        break

# 也看看那个全局变量值
print(f"\n# === global @ rip+0x253bf6 ===")
# 在 #51: mov ecx, dword ptr [rip + 0x253bf6]
# next ins = 0x180035bde, target = 0x180035bde + 0x253bf6 = 0x1802917d4
gva = 0x180035bde + 0x253bf6
print(f"global VA: 0x{gva:x}")
b = read_va(gva, 8)
if b:
    import struct
    i32 = struct.unpack_from("<i", b, 0)[0]
    u32 = struct.unpack_from("<I", b, 0)[0]
    print(f"  int32={i32}, uint32={u32}, hex={b.hex()}")
