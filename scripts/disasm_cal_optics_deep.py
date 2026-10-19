"""深入分析 calOpticsTimeWindow 与其调用的内部函数 0x1800587f0。

目标:
1. 看成功路径(0x18000183d 之后)是否写到 out_buf
2. 提取相关字符串(错误信息/日志标识)理解函数语义
3. 反汇编内部函数 0x1800587f0,看 target 结构访问与 out_buf 写入
4. 提取常量 const1/const2,推测时间转换(可能 86400=天 或 1e9=纳秒)
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

import pefile
from capstone import Cs, CS_ARCH_X86, CS_MODE_64

DLL = r"D:\wenxj\7-型号\zwxxx-3\1_文件\1_任务规划\4_测试相关文件\20260922星上测试DLL-2\20260922星上测试DLL-2\WeiNa2_star_win.dll"

# 从上次反汇编得到的关键地址(VA)
ADDR_CAL_OPTICS = 0x1800017a0
ADDR_INTERNAL_5_8_7f0 = 0x1800587f0   # calOpticsTimeWindow 调用的内部函数
ADDR_LOG_ERR_1980 = 0x180001980       # 错误日志函数

# 字符串地址(rip 相对,需计算)
# 0x180001827: lea rcx, [rip + 0x27a7d2]   -- next ins = 0x18000182e
STR_ERR_1 = 0x18000182e + 0x27a7d2  # = 0x18002bf00
# 0x1800017f3: lea rax, [rip + 0x291f5e]   -- next ins = 0x1800017fa
STR_LOG_TAG = 0x1800017fa + 0x291f5e  # = 0x180043758
# 0x1800017ff: lea r9, [rip + 0x291f42]    -- next ins = 0x180001806
STR_LOG_FN = 0x180001806 + 0x291f42  # = 0x180043748

# 常量地址(xmm 加载)
# 0x1800017e3: addsd xmm0, [rip + 0x205ec5]  -- next ins = 0x1800017eb
ADDR_CONST1 = 0x1800017eb + 0x205ec5  # = 0x1802076b0
# 0x1800017eb: subsd xmm0, [rip + 0x205ead]  -- next ins = 0x1800017f3
ADDR_CONST2 = 0x1800017f3 + 0x205ead  # = 0x1802076a0


def main() -> int:
    p = Path(DLL)
    pe = pefile.PE(str(p), fast_load=True)
    image_base = pe.OPTIONAL_HEADER.ImageBase
    print(f"# ImageBase: 0x{image_base:x}")

    md = Cs(CS_ARCH_X86, CS_MODE_64)
    md.detail = True

    def rva_to_section_offset(rva: int):
        for s in pe.sections:
            if s.VirtualAddress <= rva < s.VirtualAddress + s.Misc_VirtualSize:
                return s, rva - s.VirtualAddress
        return None, None

    def read_at_va(va: int, n: int) -> bytes:
        rva = va - image_base
        sec, off = rva_to_section_offset(rva)
        if sec is None:
            return b""
        data = sec.get_data()
        return data[off:off + n]

    def read_double(va: int):
        b = read_at_va(va, 8)
        if len(b) < 8:
            return None
        return struct.unpack("<d", b)[0]

    def read_cstr(va: int, max_len: int = 256) -> str:
        b = read_at_va(va, max_len)
        # 在 0 字节处截断
        if b"\x00" in b:
            b = b[:b.index(b"\x00")]
        try:
            return b.decode("gbk", errors="replace")
        except Exception:
            return b.decode("ascii", errors="replace")

    # 1) 常量
    print("\n# === constants (double) ===")
    c1 = read_double(ADDR_CONST1)
    c2 = read_double(ADDR_CONST2)
    print(f"  const1 (addsd) @0x{ADDR_CONST1:x}: {c1}")
    print(f"  const2 (subsd) @0x{ADDR_CONST2:x}: {c2}")
    if c1 is not None and c2 is not None:
        delta = c1 - c2
        print(f"  delta (c1 - c2): {delta}")
        # 推测时间含义
        if abs(delta - 86400.0) < 1: print("  -> 接近 86400 (一天的秒数)")
        if abs(delta - 1e9) < 1e3: print("  -> 接近 1e9 (秒->纳秒 或 毫秒换算)")
        if abs(delta - 1000.0) < 1: print("  -> 接近 1000 (毫秒换算)")

    # 2) 字符串
    print("\n# === strings ===")
    for label, va in [("err_str", STR_ERR_1), ("log_tag", STR_LOG_TAG), ("log_fn", STR_LOG_FN)]:
        s = read_cstr(va)
        print(f"  {label} @0x{va:x}: {s!r}")

    # 3) calOpticsTimeWindow 完整反汇编(扩展到 600 字节)
    print("\n# === calOpticsTimeWindow full disasm ===")
    code = read_at_va(ADDR_CAL_OPTICS, 600)
    ins_list = list(md.disasm(code, ADDR_CAL_OPTICS))
    for ins in ins_list:
        if ins.mnemonic in ("int3", "nop"):
            continue
        # 标记 out_buf 写入
        marker = ""
        op_low = ins.op_str.lower()
        if "rsp + 0xd8" in op_low or "rsp+0xd8" in op_low:
            marker = "  <<< OUT_BUF access"
        if ins.mnemonic == "call":
            marker += "  <== CALL"
        print(f"  0x{ins.address:x}:  {ins.mnemonic:8s} {ins.op_str}{marker}")
        # 遇到 ret 终止
        if ins.mnemonic in ("ret", "retn"):
            break

    # 4) 内部函数 0x1800587f0 反汇编(看 target 访问与 out_buf 写入)
    print(f"\n# === internal func @0x{ADDR_INTERNAL_5_8_7f0:x} ===")
    code2 = read_at_va(ADDR_INTERNAL_5_8_7f0, 800)
    ins_list2 = list(md.disasm(code2, ADDR_INTERNAL_5_8_7f0))
    # 找 target 结构访问([rax + N] 或 [rcx + N])
    target_offsets = set()
    out_writes = []
    for i, ins in enumerate(ins_list2):
        if ins.mnemonic in ("int3", "nop"):
            continue
        # 找 [reg + offset] 访问
        op = ins.op_str
        # 简单提取 +N 模式
        import re
        for m in re.finditer(r"\[(?:r(?:ax|cx|dx|[0-9]+)|rcx),?\s*\+?\s*0x([0-9a-fA-F]+)\]", op):
            off = int(m.group(1), 16)
            target_offsets.add(off)
        marker = ""
        # 写操作:mov [mem], reg
        if ins.mnemonic.startswith("mov") and "[" in op and op.startswith("["):
            marker = "  <<< WRITE"
            out_writes.append((i, ins.mnemonic, op))
        if ins.mnemonic == "call":
            marker += "  <== CALL"
        if ins.mnemonic in ("ret", "retn"):
            print(f"  [ins#{i}] {ins.mnemonic} {op}  <== END")
            break
    print(f"  ins count: {len(ins_list2)}")
    print(f"  target/out struct offsets accessed: {sorted(target_offsets)}")
    print(f"  writes count: {len(out_writes)}")
    # 打印前 40 条
    print("\n  --- first 40 instructions ---")
    for i, ins in enumerate(ins_list2[:40]):
        if ins.mnemonic in ("int3", "nop"):
            continue
        print(f"  [#{i:2d}] 0x{ins.address:x}:  {ins.mnemonic:8s} {ins.op_str}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
