"""深挖 calOpticsTimeWindow 链路:
1. 反汇编内部函数 0x1800587f0 全部指令,提取所有 target 偏移访问
2. 反汇编日志函数 0x18012de60 入口,从格式串反推字段语义
3. 扫描 0x1800587f0 中所有 lea rcx/r8 [rip+...] 提取字符串参数
4. 扫描 calOpticsTimeWindow 末尾 0x18012de60 调用前的参数
"""
from __future__ import annotations

import re
import struct
import sys
from pathlib import Path

import pefile
from capstone import Cs, CS_ARCH_X86, CS_MODE_64

DLL = r"D:\wenxj\7-型号\zwxxx-3\1_文件\1_任务规划\4_测试相关文件\20260922星上测试DLL-2\20260922星上测试DLL-2\WeiNa2_star_win.dll"

# 关键地址
ADDR_CAL_OPTICS = 0x1800017a0
ADDR_INTERNAL = 0x1800587f0       # calOpticsTimeWindow 调用的核心函数
ADDR_FINAL_CALL = 0x18012de60     # calOpticsTimeWindow 末尾调用(疑似日志/回调)
ADDR_LOG_HELPER = 0x180001980     # 错误日志函数
ADDR_CHK_STACK = 0x1801480c0      # __chkstk


def main() -> int:
    p = Path(DLL)
    pe = pefile.PE(str(p), fast_load=True)
    image_base = pe.OPTIONAL_HEADER.ImageBase
    print(f"# ImageBase: 0x{image_base:x}")

    md = Cs(CS_ARCH_X86, CS_MODE_64)
    md.detail = True

    def rva_to_section(rva: int):
        for s in pe.sections:
            if s.VirtualAddress <= rva < s.VirtualAddress + s.Misc_VirtualSize:
                return s
        return None

    def read_at_va(va: int, n: int) -> bytes:
        rva = va - image_base
        sec = rva_to_section(rva)
        if sec is None:
            return b""
        data = sec.get_data()
        off = rva - sec.VirtualAddress
        return data[off:off + n]

    def read_cstr(va: int, max_len: int = 512) -> str:
        b = read_at_va(va, max_len)
        if b"\x00" in b:
            b = b[:b.index(b"\x00")]
        try:
            return b.decode("gbk", errors="replace")
        except Exception:
            return b.decode("ascii", errors="replace")

    def read_double(va: int):
        b = read_at_va(va, 8)
        if len(b) < 8:
            return None
        return struct.unpack("<d", b)[0]

    def read_int32(va: int):
        b = read_at_va(va, 4)
        if len(b) < 4:
            return None
        return struct.unpack("<i", b)[0]

    # 1) 内部函数 0x1800587f0 完整反汇编,提取所有 target 结构访问
    print(f"\n# === internal func @0x{ADDR_INTERNAL:x} FULL disasm ===")
    code = read_at_va(ADDR_INTERNAL, 0x600)
    ins_list = list(md.disasm(code, ADDR_INTERNAL))

    # 收集所有结构访问 [reg + offset]
    struct_access = {}  # offset -> [(ins_idx, mnemonic, op_str)]
    lea_strings = []    # (ins_idx, addr, str)
    call_targets = []   # (ins_idx, target_addr)

    # rip 相对地址计算需要下一条指令地址
    for i, ins in enumerate(ins_list):
        if ins.mnemonic in ("int3", "nop"):
            continue
        # 找 [reg + 0xNN] 或 [reg + 0xNNN] 模式
        for m in re.finditer(
            r"\[\s*(?:r[a-z0-9]+)\s*\+\s*(0x[0-9a-fA-F]+)\s*\]",
            ins.op_str
        ):
            off = int(m.group(1), 16)
            struct_access.setdefault(off, []).append((i, ins.mnemonic, ins.op_str))
        # lea reg, [rip + offset] -> 提取字符串地址
        if ins.mnemonic == "lea" and "rip" in ins.op_str:
            # rip 指向 next ins 地址
            next_addr = ins.address + ins.size
            m = re.search(r"\[rip\s*\+\s*(0x[0-9a-fA-F]+)\]", ins.op_str)
            if m:
                target_va = next_addr + int(m.group(1), 16)
                s = read_cstr(target_va)
                if s and len(s) > 1:
                    lea_strings.append((i, target_va, s))
                else:
                    # 可能是 double/int32 常量
                    d = read_double(target_va)
                    n32 = read_int32(target_va)
                    lea_strings.append((i, target_va, f"<double={d} int32={n32}>"))
        if ins.mnemonic == "call":
            m = re.match(r"^0x([0-9a-fA-F]+)$", ins.op_str.strip())
            if m:
                call_targets.append((i, int(m.group(1), 16)))

    # 打印全部指令
    for i, ins in enumerate(ins_list):
        if ins.mnemonic in ("int3", "nop"):
            continue
        if ins.mnemonic in ("ret", "retn"):
            print(f"  [#{i:3d}] 0x{ins.address:x}:  {ins.mnemonic:8s} {ins.op_str}  <== END")
            break
        print(f"  [#{i:3d}] 0x{ins.address:x}:  {ins.mnemonic:8s} {ins.op_str}")

    print(f"\n# === target struct offsets accessed in internal func ===")
    for off in sorted(struct_access.keys()):
        accesses = struct_access[off]
        print(f"  +0x{off:x} ({off}): {len(accesses)} accesses")
        for idx, mn, op in accesses[:3]:
            print(f"    [#{idx}] {mn} {op}")

    print(f"\n# === lea rip strings in internal func ===")
    for idx, va, s in lea_strings:
        print(f"  [#{idx}] @0x{va:x}: {s!r}")

    print(f"\n# === call targets in internal func ===")
    for idx, addr in call_targets:
        print(f"  [#{idx}] -> 0x{addr:x}")

    # 2) 反汇编日志函数 0x18012de60 入口
    print(f"\n# === final-call func @0x{ADDR_FINAL_CALL:x} (suspected logger/callback) ===")
    code2 = read_at_va(ADDR_FINAL_CALL, 0x300)
    ins_list2 = list(md.disasm(code2, ADDR_FINAL_CALL))
    lea_strs2 = []
    for i, ins in enumerate(ins_list2[:60]):
        if ins.mnemonic in ("int3", "nop"):
            continue
        if ins.mnemonic == "lea" and "rip" in ins.op_str:
            next_addr = ins.address + ins.size
            m = re.search(r"\[rip\s*\+\s*(0x[0-9a-fA-F]+)\]", ins.op_str)
            if m:
                target_va = next_addr + int(m.group(1), 16)
                s = read_cstr(target_va)
                if s and len(s) > 1:
                    lea_strs2.append((i, target_va, s))
        print(f"  [#{i:2d}] 0x{ins.address:x}:  {ins.mnemonic:8s} {ins.op_str}")
        if ins.mnemonic in ("ret", "retn"):
            break

    print(f"\n# === lea rip strings in final-call func (FORMAT STRINGS!) ===")
    for idx, va, s in lea_strs2:
        print(f"  [#{idx}] @0x{va:x}: {s!r}")

    # 3) 扫描 calOpticsTimeWindow 末尾调用 0x18012de60 前的参数准备
    print(f"\n# === calOpticsTimeWindow tail (call 0x18012de60 setup) ===")
    # 重新反汇编 calOpticsTimeWindow
    code3 = read_at_va(ADDR_CAL_OPTICS, 0x200)
    ins_list3 = list(md.disasm(code3, ADDR_CAL_OPTICS))
    # 找到 call 0x18012de60 这条
    call_idx = None
    for i, ins in enumerate(ins_list3):
        if ins.mnemonic == "call" and "0x18012de60" in ins.op_str:
            call_idx = i
            break
    if call_idx is not None:
        # 打印 call 前 20 条指令
        start = max(0, call_idx - 20)
        for i in range(start, call_idx + 1):
            ins = ins_list3[i]
            # 标记参数准备
            marker = ""
            if ins.mnemonic == "lea" and "rcx" in ins.op_str: marker = "  <-- arg1 (rcx)"
            if ins.mnemonic == "lea" and "rdx" in ins.op_str: marker = "  <-- arg2 (rdx)"
            if ins.mnemonic == "lea" and "r8" in ins.op_str: marker = "  <-- arg3 (r8)"
            if ins.mnemonic == "mov" and "rcx" in ins.op_str.split(",")[0]: marker = "  <-- arg1 (rcx)"
            if ins.mnemonic == "mov" and "rdx" in ins.op_str.split(",")[0]: marker = "  <-- arg2 (rdx)"
            if ins.mnemonic == "mov" and "r8d" in ins.op_str.split(",")[0] or ins.mnemonic == "lea" and "r8" in ins.op_str.split(",")[0]: marker = "  <-- arg3 (r8)"
            if ins.mnemonic == "mov" and "r9d" in ins.op_str.split(",")[0] or ins.mnemonic == "lea" and "r9" in ins.op_str.split(",")[0]: marker = "  <-- arg4 (r9)"
            if ins.mnemonic == "movsd" and "xmm1" in ins.op_str.split(",")[0]: marker = "  <-- arg2 (xmm1 double)"
            if ins.mnemonic == "movsd" and "xmm2" in ins.op_str.split(",")[0]: marker = "  <-- arg3 (xmm2 double)"
            if ins.mnemonic == "movsd" and "xmm3" in ins.op_str.split(",")[0]: marker = "  <-- arg4 (xmm3 double)"
            if ins.mnemonic == "lea" and "rip" in ins.op_str:
                next_addr = ins.address + ins.size
                m = re.search(r"\[rip\s*\+\s*(0x[0-9a-fA-F]+)\]", ins.op_str)
                if m:
                    target_va = next_addr + int(m.group(1), 16)
                    s = read_cstr(target_va)
                    if s:
                        marker += f"  STR={s!r}"
            print(f"  [#{i:2d}] 0x{ins.address:x}:  {ins.mnemonic:8s} {ins.op_str}{marker}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
