"""反汇编 0x18002aeb0:按 type 找处理函数。

这是消息类型查找函数,看它如何遍历/查表。
同时扫描 .rdata 段找所有看起来像类型名的字符串。
"""
import sys, struct
import pefile
from capstone import Cs, CS_ARCH_X86, CS_MODE_64

DLL = r"D:\wenxj\7-型号\zwxxx-3\1_文件\1_任务规划\4_测试相关文件\20260922星上测试DLL-2\20260922星上测试DLL-2\WeiNa2_star_win.dll"
ADDR = 0x18002aeb0

pe = pefile.PE(DLL, fast_load=True)
ib = pe.OPTIONAL_HEADER.ImageBase
md = Cs(CS_ARCH_X86, CS_MODE_64); md.detail = True

def read_va(va, n):
    rva = va - ib
    for s in pe.sections:
        if s.VirtualAddress <= rva < s.VirtualAddress + s.Misc_VirtualSize:
            return s.get_data()[rva - s.VirtualAddress: rva - s.VirtualAddress + n]
    return b""

def read_cstr(va, n=256):
    b = read_va(va, n)
    if b"\x00" in b: b = b[:b.index(b"\x00")]
    try: return b.decode("gbk")
    except: return b.decode("ascii", errors="replace")

code = read_va(ADDR, 0x200)
ins = list(md.disasm(code, ADDR))

print("# === 0x18002aeb0 (type lookup) ===")
for i in range(min(40, len(ins))):
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
            else:
                # 看 8 字节(可能函数指针表)
                b = read_va(target_va, 32)
                marker = f"  [0x{target_va:x}] hex={b.hex()[:64]}"
    if inst.mnemonic == "call":
        marker += "  <== CALL"
    print(f"  [#{i:3d}] 0x{inst.address:x}:  {inst.mnemonic:8s} {inst.op_str}{marker}")
    if inst.mnemonic in ("ret", "retn"):
        break

# 扫描 .rdata 找 "目标" "轨道" "任务" 等关键字符串
print("\n# === strings containing keywords ===")
# 找 .rdata 段
for s in pe.sections:
    sec_name = s.Name.decode("ascii", errors="replace").rstrip("\x00")
    if ".rdata" not in sec_name and ".data" not in sec_name:
        continue
    print(f"\n--- section {sec_name} ---")
    data = s.get_data()
    # 找所有 GBK 中文字符串
    keywords = ["目标", "轨道", "任务", "数传", "成像", "可见", "卫星", "规划", "输入", "输出"]
    for kw in keywords:
        kw_b = kw.encode("gbk")
        idx = 0
        while True:
            j = data.find(kw_b, idx)
            if j < 0: break
            # 截取周围 64 字节
            chunk = data[j:j+64]
            if b"\x00" in chunk:
                chunk = chunk[:chunk.index(b"\x00")]
            try:
                s_str = chunk.decode("gbk", errors="replace")
            except:
                s_str = chunk.hex()
            va = ib + s.VirtualAddress + j
            print(f"  [{kw}] @0x{va:x}: {s_str!r}")
            idx = j + 1
            # 限制每个关键词前 5 个匹配
            count_match = data.count(kw_b)
            if idx > j + 1 and data.find(kw_b, idx) < 0: break
            if idx > len(data): break
