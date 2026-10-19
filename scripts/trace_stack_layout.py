"""重新审视 calOpticsTimeWindow 内部函数对 target[+8] 的解读。

从反汇编 v3 已知:
  [#11] mov rcx, [rsp+0x130]    # target* (参数#1,从 shadow space 取)
  [#29] cmp [rsp+0x130], 0      # target == NULL?
  [#31] mov rax, [rsp+0x130]    # rax = target
  [#32] movsd xmm0, [rax+8]     # 读 target[+8] 8字节
  [#33] comisd xmm0, [rsp+0x140]  # 与 [rsp+0x140] 比较
  [#34] jb 0x1800588ab           # 小于则继续,否则失败
  [#35] mov eax, -1; jmp END     # 失败返回 -1

[rsp+0x140] 是什么?在 calOpticsTimeWindow 调内部时:
  call 0x1800587f0
之前 setup 见反汇编 v3 calOpticsTimeWindow tail:
  [#62] movsd xmm1, [rsp+0xd0]    <-- arg2 (xmm1 double) → 内部 +0x140?
  
但 [rsp+0x140] 在内部函数帧里是新的位置,需要重新看堆栈布局:
  [#6] sub rsp, 0x118            # 新帧 0x118 = 280 字节
  入口时 rcx 保存在 [rsp+0x130] (因为 push rsi/rdi + sub 后,+0x130 对应原 [rsp+8])
  r9 (参数#4) 保存在 [rsp+0x150] (原 [rsp+0x20])
  xmm2 (参数#3, double) 保存在 [rsp+0x140] (原 [rsp+0x18])
  xmm1 (参数#2, double) 保存在 [rsp+0x138]? 看反汇编

让我重新反汇编,精确读 +0x130/+0x138/+0x140/+0x148/+0x150 的来源。
"""
from __future__ import annotations
import sys, struct
import pefile
from capstone import Cs, CS_ARCH_X86, CS_MODE_64

DLL = r"D:\wenxj\7-型号\zwxxx-3\1_文件\1_任务规划\4_测试相关文件\20260922星上测试DLL-2\20260922星上测试DLL-2\WeiNa2_star_win.dll"
ADDR_INTERNAL = 0x1800587f0


def main() -> int:
    pe = pefile.PE(DLL, fast_load=True)
    image_base = pe.OPTIONAL_HEADER.ImageBase
    md = Cs(CS_ARCH_X86, CS_MODE_64); md.detail = True

    def rva_to_sec(rva):
        for s in pe.sections:
            if s.VirtualAddress <= rva < s.VirtualAddress + s.Misc_VirtualSize:
                return s
        return None

    def read_va(va, n):
        rva = va - image_base
        sec = rva_to_sec(rva)
        if not sec: return b""
        d = sec.get_data()
        return d[rva - sec.VirtualAddress: rva - sec.VirtualAddress + n]

    code = read_va(ADDR_INTERNAL, 0x600)
    ins = list(md.disasm(code, ADDR_INTERNAL))

    # 打印前 50 条 + 重点关注 [rsp+0x130] [rsp+0x138] [rsp+0x140] [rsp+0x148] [rsp+0x150] 访问
    print("# === internal func first 50 instructions with stack layout ===")
    stack_source = {}  # 偏移 -> 来源(哪条 mov 指令)
    for i, ins in enumerate(ins[:50]):
        if ins.mnemonic in ("int3", "nop"): continue
        # 跟踪写入 [rsp+0x130] 等
        if ins.mnemonic == "mov" and "rsp" in ins.op_str:
            # mov [rsp+X], src 或 mov dst, [rsp+X]
            import re
            # 写入: mov qword ptr [rsp+X], REG
            m = re.match(r"qword ptr \[rsp \+ (0x[0-9a-fA-F]+)\], (\w+)", ins.op_str)
            if m:
                off = int(m.group(1), 16)
                src = m.group(2)
                stack_source[off] = src
                print(f"  [#{i:2d}] WRITE [rsp+0x{off:x}] <- {src}")
                continue
            # 读出: mov REG, qword ptr [rsp+X]
            m = re.match(r"(\w+), qword ptr \[rsp \+ (0x[0-9a-fA-F]+)\]", ins.op_str)
            if m:
                dst = m.group(1)
                off = int(m.group(2), 16)
                src = stack_source.get(off, "?")
                print(f"  [#{i:2d}] READ [rsp+0x{off:x}] (source={src}) -> {dst}  {ins.mnemonic} {ins.op_str}")
                continue
            # movsd
            if ins.mnemonic == "movsd":
                m = re.match(r"qword ptr \[rsp \+ (0x[0-9a-fA-F]+)\], (\w+)", ins.op_str)
                if m:
                    off = int(m.group(1), 16)
                    src = m.group(2)
                    stack_source[off] = f"xmm:{src}"
                    print(f"  [#{i:2d}] WRITE [rsp+0x{off:x}] <- {src} (double)  {ins.op_str}")
                    continue
                m = re.match(r"(\w+), qword ptr \[rsp \+ (0x[0-9a-fA-F]+)\]", ins.op_str)
                if m:
                    dst = m.group(1)
                    off = int(m.group(2), 16)
                    src = stack_source.get(off, "?")
                    print(f"  [#{i:2d}] READ [rsp+0x{off:x}] (source={src}) -> {dst}  {ins.op_str}")
                    continue
        print(f"  [#{i:2d}] 0x{ins.address:x}:  {ins.mnemonic:8s} {ins.op_str}")

    print("\n# === stack source map ===")
    for off in sorted(stack_source.keys()):
        print(f"  [rsp+0x{off:x}] <- {stack_source[off]}")

    return 0

if __name__ == "__main__":
    sys.exit(main())
