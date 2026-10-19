"""反汇编 WeiNa2_star_win.dll 三个入口,推断参数个数。

使用 pefile 解析 + capstone 反汇编。
策略:
- x64 cdecl 调用约定前 4 参数走 RCX/RDX/R8/R9,第 5+ 走栈
- 函数入口 prolog 后第一条 mov/cmp/add 等指令若使用 RCX/RDX/R8/R9,说明有对应参数
- 看 push 计数与 sub rsp,N(N>0x20 说明至少 5 个参数,因为前 4 走寄存器)
"""
from __future__ import annotations

import sys
from pathlib import Path

import pefile
from capstone import Cs, CS_ARCH_X86, CS_MODE_64, CS_OP_REG

DLL = r"D:\wenxj\7-型号\zwxxx-3\1_文件\1_任务规划\4_测试相关文件\20260922星上测试DLL-2\20260922星上测试DLL-2\WeiNa2_star_win.dll"

TARGETS = ["DllInit", "DllInput", "DllOutput", "ExitSystem", "calOpticsTimeWindow"]
# x64 调用约定: 前四个参数用寄存器
ARG_REGS = ["rcx", "rdx", "r8", "r9"]
SHADOW_REGS = ["rsp", "rbp", "rdi", "rsi", "rbx", "r12", "r13", "r14", "r15"]  # callee-saved


def analyze_args(disasm_lines: list) -> dict:
    """根据前若干条指令,推断参数寄存器使用。

    返回 {reg_name: first_use_offset}。
    """
    used: dict[str, int] = {}
    for i, ins in enumerate(disasm_lines):
        # 若指令操作数含 RCX/RDX/R8/R9,记为参数使用
        for reg_name in ARG_REGS:
            # 注意 capstone 输出 reg 名可能是 rcx/R CX,统一小写
            if reg_name in ins.op_str.lower() or reg_name.upper() in ins.op_str:
                if reg_name not in used:
                    used[reg_name] = i
    return used


def main() -> int:
    p = Path(DLL)
    pe = pefile.PE(str(p), fast_load=True)
    pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_EXPORT']])
    exp = getattr(pe, "DIRECTORY_ENTRY_EXPORT", None)
    if exp is None:
        print("no exports")
        return 1

    md = Cs(CS_ARCH_X86, CS_MODE_64)
    md.detail = True

    # 找 ImageBase 与 sections
    image_base = pe.OPTIONAL_HEADER.ImageBase
    print(f"# ImageBase: 0x{image_base:x}")

    for sym in exp.symbols:
        # 名字可能是 bytes
        name = sym.name if isinstance(sym.name, str) else sym.name.decode("ascii", errors="replace")
        if name not in TARGETS:
            continue
        rva = sym.address
        # 找 section
        sec = None
        for s in pe.sections:
            sec_rva = s.VirtualAddress
            sec_end = sec_rva + s.Misc_VirtualSize
            if sec_rva <= rva < sec_end:
                sec = s
                break
        if sec is None:
            print(f"\n[{name}] RVA=0x{rva:x} -> no section")
            continue
        offset = rva - sec.VirtualAddress
        # 读代码字节(80 字节够看入口)
        sec_data = sec.get_data()
        code = sec_data[offset:offset + 200]
        va = image_base + rva
        print(f"\n=== {name} ===")
        print(f"  RVA=0x{rva:x}  VA=0x{va:x}  section={sec.Name.decode('ascii', errors='replace').rstrip(chr(0))}")

        ins_list = list(md.disasm(code, va))[:30]
        for ins in ins_list:
            print(f"  0x{ins.address:x}:  {ins.mnemonic:8s} {ins.op_str}")

        # 参数推断
        used = analyze_args(ins_list[:15])
        print(f"  arg regs used (first 15 ins): {used}")
        if used:
            max_reg = max(used.values())
            for r in ARG_REGS:
                if r in used:
                    print(f"    {r}: first used at ins#{used[r]} -> param #{ARG_REGS.index(r)+1}")
                else:
                    print(f"    {r}: not used in first 15 ins (param #{ARG_REGS.index(r)+1} 可能不存在)")
        # 看 sub rsp / push 估计局部栈
        rsp_subs = [(i, ins) for i, ins in enumerate(ins_list) if ins.mnemonic == "sub" and "rsp" in ins.op_str]
        for i, ins in rsp_subs:
            print(f"  stack alloc: ins#{i} {ins.mnemonic} {ins.op_str}")
        # ret 看
        for i, ins in enumerate(ins_list):
            if ins.mnemonic in ("ret", "retn"):
                print(f"  return: ins#{i} {ins.mnemonic} {ins.op_str}")
                break

    return 0


if __name__ == "__main__":
    sys.exit(main())
