"""看 internal func #37 之后(target[+8] 校验通过后)。

#37-#49:
  rax = target
  xmm0 = target[+8]        # 再次取
  [rsp+0x98] = xmm0        # 存到 +0x98
  rax = target + 0x10      # target[+16]
  r8d = 0x30                # 48 字节
  rdx = rax                  # src = target+0x10
  rcx = [rsp+0x48]          # dst
  call 0x18014af30           # memcpy? 48 字节从 target+16 复制到 +0x48
  r8d = 0x40                # 64 字节
  rdx = 0                    # val=0
  rcx = [rsp+0xb0]          # dst
  call 0x18014b380           # memset 0 (64 字节)
  ...

#37+ 之后是关键!继续反汇编看更多指令,找 -2 返回点。
"""
import sys, struct
import pefile
from capstone import Cs, CS_ARCH_X86, CS_MODE_64

DLL = r"D:\wenxj\7-型号\zwxxx-3\1_文件\1_任务规划\4_测试相关文件\20260922星上测试DLL-2\20260922星上测试DLL-2\WeiNa2_star_win.dll"
ADDR_INTERNAL = 0x1800587f0


def main():
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

    # 找所有 ret 与 -2 (0xfffffffe) 出现的位置
    print("# === find -2 / -1 return points ===")
    for i, inst in enumerate(ins):
        if inst.mnemonic in ("int3", "nop"): continue
        # 0xfffffffe = -2, 0xffffffff = -1
        if inst.mnemonic == "mov" and "eax" in inst.op_str.split(",")[0]:
            import re
            m = re.match(r"eax, (0x[0-9a-fA-F]+)", inst.op_str)
            if m:
                val = int(m.group(1), 16)
                if val in (0xfffffffe, 0xffffffff, 0, 1, 2, 3):
                    print(f"  [#{i:3d}] 0x{inst.address:x}: {inst.mnemonic} {inst.op_str}  <== RETURN {val - 0x100000000 if val >= 0x80000000 else val}")
        if inst.mnemonic in ("ret", "retn"):
            print(f"  [#{i:3d}] 0x{inst.address:x}: ret  <== END")
            break

    # 反汇编 50-100
    print("\n# === instructions 50-100 ===")
    for i in range(50, min(110, len(ins))):
        inst = ins[i]
        if inst.mnemonic in ("int3", "nop"): continue
        print(f"  [#{i:3d}] 0x{inst.address:x}:  {inst.mnemonic:8s} {inst.op_str}")

    # 看从 #37 到第一个 -2 返回点的完整流程
    print("\n# === flow from target+0x10 copy to -2 ===")
    in_block = False
    for i, inst in enumerate(ins):
        if i < 37: continue
        if inst.mnemonic in ("int3", "nop"): continue
        # 找 0xfffffffe 写入
        if "0xfffffffe" in inst.op_str:
            print(f"  [#{i:3d}] ** -2 RETURN **  0x{inst.address:x}: {inst.mnemonic} {inst.op_str}")
        elif "0xffffffff" in inst.op_str:
            print(f"  [#{i:3d}] ** -1 RETURN **  0x{inst.address:x}: {inst.mnemonic} {inst.op_str}")
        else:
            print(f"  [#{i:3d}] 0x{inst.address:x}:  {inst.mnemonic:8s} {inst.op_str}")
        if inst.mnemonic in ("ret", "retn"):
            break
    return 0


if __name__ == "__main__":
    sys.exit(main())
