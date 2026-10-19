"""dump WeiNa2_star_win.dll 的 PE 头与导出表。

输出:
- 机器/位数(32/64 位)
- 调用约定推断(由函数名修饰判断)
- 全部导出函数名(确认 Funinput/Funoutput/Funinit 被导出)
- 三个目标函数的名字修饰分析
"""
from __future__ import annotations

import sys
from pathlib import Path

import pefile

DLL = r"D:\wenxj\7-型号\zwxxx-3\1_文件\1_任务规划\4_测试相关文件\20260922星上测试DLL-2\20260922星上测试DLL-2\WeiNa2_star_win.dll"

TARGETS = ("Funinput", "Funoutput", "Funinit", "ExitSystem")


def main() -> int:
    p = Path(DLL)
    if not p.is_file():
        print(f"[ERR] not found: {p}")
        return 1

    pe = pefile.PE(str(p), fast_load=True)
    # 头信息
    machine = pe.FILE_HEADER.Machine
    # 0x14c = x86(32位), 0x8664 = x64(64位)
    arch = {0x14C: "x86(32-bit)", 0x8664: "x64(64-bit)"}.get(machine, f"unknown(0x{machine:x})")
    print(f"# PE: arch={arch} machine=0x{machine:x}")
    print(f"# Sections: {len(pe.sections)}")
    print(f"# TimeDateStamp: 0x{pe.FILE_HEADER.TimeDateStamp:x}")

    # 导出表
    pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_EXPORT']])
    exp = getattr(pe, "DIRECTORY_ENTRY_EXPORT", None)
    if exp is None:
        print("\n# No exports!")
        return 2

    symbols = [sym.name for sym in exp.symbols]
    # Python3 pefile 可能返回 bytes
    def _str(x):
        if isinstance(x, bytes):
            try:
                return x.decode("ascii")
            except UnicodeDecodeError:
                return x.hex()
        return str(x)

    symbols_str = [_str(s) for s in symbols]
    print(f"\n# Export count: {len(symbols_str)}")
    print("\n# All exports:")
    for i, s in enumerate(symbols_str):
        marker = "  <<< TARGET" if any(s == t or s.startswith(t) for t in TARGETS) else ""
        print(f"  [{i:3d}] {s}{marker}")

    print(f"\n# Target function analysis:")
    for tgt in TARGETS:
        # 精确匹配
        exact = [s for s in symbols_str if s == tgt]
        # 前缀匹配(可能是 _Funinit@8 或 _Funinit)
        prefix = [s for s in symbols_str if s.startswith(tgt) or s.lstrip("_").startswith(tgt)]
        print(f"\n  '{tgt}':")
        print(f"    exact match: {exact if exact else 'NOT FOUND'}")
        print(f"    prefix match: {prefix if prefix else 'none'}")
        # 调用约定推断
        if exact:
            name = exact[0]
            if name.startswith("_") and "@" in name:
                # _Funinit@8 → stdcall, 8 字节参数
                try:
                    nbytes = int(name.split("@")[1])
                    print(f"    convention: stdcall (__stdcall), arg bytes={nbytes}")
                except Exception:
                    pass
            elif name.startswith("_"):
                print(f"    convention: likely cdecl (underscore prefix)")
            else:
                print(f"    convention: likely cdecl (no decoration) -- 64位默认")
    return 0


if __name__ == "__main__":
    sys.exit(main())
