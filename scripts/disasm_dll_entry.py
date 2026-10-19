"""反汇编 WeiNa2_star_win.dll 三个入口函数,推断参数个数。

策略:
1. 用 lief 加载 dll,定位 DllInit/DllInput/DllOutput 的虚拟地址
2. 反汇编入口前若干条指令,看寄存器使用:
   - x64 cdecl 调用约定前 4 参数走 RCX/RDX/R8/R9,第 5+ 走栈
   - 入口 prolog 后若立即使用 RCX/RDX/R8/R9,说明有对应参数
3. 同时尝试 ctypes 加载 dll 验证可加载性
"""
from __future__ import annotations

import ctypes
import sys
import logging
from pathlib import Path

DLL = r"D:\wenxj\7-型号\zwxxx-3\1_文件\1_任务规划\4_测试相关文件\20260922星上测试DLL-2\20260922星上测试DLL-2\WeiNa2_star_win.dll"

TARGETS = ["DllInit", "DllInput", "DllOutput", "ExitSystem", "calOpticsTimeWindow"]


def try_ctypes_load() -> bool:
    """用 ctypes 尝试加载 dll。"""
    print("\n# === ctypes load test ===")
    try:
        h = ctypes.CDLL(DLL)
        print(f"  load OK: {h}")
        # 尝试拿每个函数
        for name in TARGETS:
            try:
                f = getattr(h, name)
                print(f"  found: {name} -> {f}")
            except AttributeError as e:
                print(f"  NOT FOUND: {name} ({e})")
        return True
    except OSError as e:
        print(f"  load FAILED: {e}")
        return False


def disasm_with_lief() -> int:
    """用 lief 反汇编入口点。"""
    print("\n# === lief disasm ===")
    try:
        import lief
        # 0.12 版本 API
        binary = lief.PE.parse(DLL)
        if binary is None:
            print("  parse failed")
            return 1
        print(f"  parsed OK: {binary}")
        # 导出表
        exports = list(binary.get_export().entries) if binary.has_exports else []
        print(f"  exports: {len(exports)}")
        for e in exports:
            print(f"    name={e.name} addr=0x{e.address:x} ordinal={e.ordinal}")

        # 反汇编每个目标函数入口前 N 字节
        # lief 0.12 反汇编 API: 逐条反汇编
        print("\n  --- disasm first 64 bytes of each target ---")
        # 找函数地址(导出 RVA -> file offset)
        for e in exports:
            name = e.name
            if not name or name not in TARGETS:
                continue
            rva = e.address  # relative virtual address
            # 从对应 section 读出代码字节
            section = binary.section_from_rva(rva)
            if section is None:
                print(f"  [{name}] no section for RVA 0x{rva:x}")
                continue
            offset = rva - section.virtual_address
            content = bytes(section.content)[offset:offset + 80]
            print(f"\n  [{name}] RVA=0x{rva:x} section={section.name} bytes={content.hex()[:128]}...")

            # 尝试用 capstone 反汇编
            try:
                from capstone import Cs, CS_ARCH_X86, CS_MODE_64
                md = Cs(CS_ARCH_X86, CS_MODE_64)
                count = 0
                for ins in md.disasm(content, rva + 0x10000000):
                    print(f"    0x{ins.address:x}:  {ins.mnemonic} {ins.op_str}")
                    count += 1
                    if count >= 15:
                        break
            except ImportError:
                print("    [capstone not installed, raw hex shown above]")
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"  lief error: {e}")
        return 1
    return 0


def main() -> int:
    p = Path(DLL)
    if not p.is_file():
        print(f"[ERR] not found: {p}")
        return 1
    try_ctypes_load()
    return disasm_with_lief()


if __name__ == "__main__":
    sys.exit(main())
