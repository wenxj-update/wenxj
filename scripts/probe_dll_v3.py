"""DllInit + calOpticsTimeWindow 试探(已修:os.chdir 到 dll 目录)。

关键经验:
- 必须先 os.chdir 到 dll 所在目录(否则找不到 xml,内部线程崩溃)
- DllInit 成功返回 0,需要等待内部线程就绪
- 内部用 SQLite(DB 文件,自动创建),并启动 ThreadSatProc
"""
from __future__ import annotations

import ctypes
import faulthandler
import os
import struct
import sys
import time

faulthandler.enable()

DLL_PATH = r"D:\wenxj\7-型号\zwxxx-3\1_文件\1_任务规划\4_测试相关文件\20260922星上测试DLL-2\20260922星上测试DLL-2\WeiNa2_star_win.dll"
DLL_DIR = os.path.dirname(DLL_PATH)
os.chdir(DLL_DIR)


def main() -> int:
    print(f"# cwd: {os.getcwd()}")
    print(f"# loading dll")
    dll = ctypes.CDLL(DLL_PATH)

    # 签名
    dll.DllInit.argtypes = []
    dll.DllInit.restype = ctypes.c_int
    dll.DllInput.argtypes = [ctypes.c_void_p, ctypes.c_int]
    dll.DllInput.restype = ctypes.c_int
    dll.DllOutput.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    dll.DllOutput.restype = ctypes.c_int
    dll.ExitSystem.argtypes = []
    dll.ExitSystem.restype = ctypes.c_int
    dll.calOpticsTimeWindow.argtypes = [
        ctypes.c_void_p, ctypes.c_double, ctypes.c_double, ctypes.c_void_p,
    ]
    dll.calOpticsTimeWindow.restype = ctypes.c_int

    # Step 1: DllInit
    print("\n# === DllInit ===")
    rc = dll.DllInit()
    print(f"  rc={rc}")
    if rc != 0:
        print("  DllInit failed, abort")
        dll.ExitSystem()
        return 1

    # 等内部线程就绪
    print("  wait 1s for internal threads...")
    time.sleep(1.0)

    # Step 2: calOpticsTimeWindow 试探
    print("\n# === calOpticsTimeWindow probe ===")
    TARGET_SIZE = 512
    OUT_SIZE = 7200 * 64 + 1024
    target_buf = (ctypes.c_ubyte * TARGET_SIZE)()
    out_buf = (ctypes.c_ubyte * OUT_SIZE)()

    def reset():
        for i in range(TARGET_SIZE):
            target_buf[i] = 0
        for i in range(OUT_SIZE):
            out_buf[i] = 0

    def try_call(label, t0=0.0, t1=100.0, setup=None):
        print(f"\n  --- {label} ---")
        reset()
        if setup:
            setup(target_buf)
        try:
            rc = dll.calOpticsTimeWindow(
                ctypes.cast(target_buf, ctypes.c_void_p),
                ctypes.c_double(t0), ctypes.c_double(t1),
                ctypes.cast(out_buf, ctypes.c_void_p),
            )
            print(f"    rc={rc} (0x{rc & 0xffffffff:x})")
            if rc >= 0:
                print(f"    -> SUCCESS? count={rc}")
                nonzero = sum(1 for i in range(min(OUT_SIZE, 2048)) if out_buf[i] != 0)
                print(f"    out non-zero: {nonzero} bytes")
                if nonzero > 0:
                    head = bytes(out_buf[:128])
                    print(f"    out[0:128]: {head.hex()}")
                    # 按 64 字节项解读
                    for off in range(0, 128, 8):
                        d = struct.unpack_from("<d", head, off)[0]
                        i32 = struct.unpack_from("<i", head, off)[0]
                        print(f"      +{off:3d}: double={d:.6g}  int32={i32}")
            elif rc == -1:
                print("    -> 轨道预报失败(target 校验失败,缺轨道数据?)")
            elif rc == -2:
                print("    -> -2 (target 字段缺失/不合法)")
        except Exception as e:
            print(f"    EXCEPTION: {e}")
            faulthandler.dump_traceback()

    # 试 1: 全零 target
    try_call("test1: zero target, t0=0 t1=100")

    # 试 2: target[+8] = 100.0 (与 t1 匹配)
    def set_100(buf):
        struct.pack_into("<d", buf, 8, 100.0)
    try_call("test2: target[+8]=100, t0=0 t1=100", setup=set_100)

    # 试 3: target[+8] = 当前时间(相对 2009 epoch)
    stk_epoch = 1230768000
    now_secs = time.time() - stk_epoch
    def set_now(buf):
        struct.pack_into("<d", buf, 8, float(now_secs))
    try_call(f"test3: target[+8]=now({now_secs:.0f}s)", t0=0.0, t1=100.0,
             setup=set_now)

    # 试 4: target[+8] = now, t0/t1 也用相对值
    try_call(f"test4: target[+8]=now, t0=now, t1=now+100",
             t0=now_secs, t1=now_secs + 100.0, setup=set_now)

    # 试 5: target[+8] = 0, t0=0, t1=10
    try_call("test5: zero target, t0=0 t1=10", t0=0.0, t1=10.0)

    # Step 3: DllInput 用全零缓冲(可能要先用 DllInput 注入轨道数据)
    print("\n# === DllInput probe ===")
    input_buf = (ctypes.c_ubyte * 0x10000)()
    for sz in [0, 4, 16, 64, 256]:
        try:
            rc = dll.DllInput(ctypes.cast(input_buf, ctypes.c_void_p), sz)
            print(f"  DllInput(len={sz}) rc={rc}")
        except Exception as e:
            print(f"  DllInput(len={sz}) EXCEPTION: {e}")
            break

    # 重试 calOpticsTimeWindow(DllInput 后)
    print("\n# === calOpticsTimeWindow after DllInput ===")
    try_call("post-input test: zero target, t0=0 t1=100")

    # Step 4: DllOutput
    print("\n# === DllOutput ===")
    out2 = (ctypes.c_ubyte * 0x10000)()
    ctx = (ctypes.c_ubyte * 0x1000)()
    try:
        rc = dll.DllOutput(ctypes.cast(out2, ctypes.c_void_p),
                          ctypes.cast(ctx, ctypes.c_void_p))
        print(f"  DllOutput rc={rc}")
        nonzero = sum(1 for i in range(1024) if out2[i] != 0)
        print(f"  out non-zero: {nonzero}")
        if nonzero > 0:
            print(f"  out[0:64]: {bytes(out2[:64]).hex()}")
    except Exception as e:
        print(f"  DllOutput EXCEPTION: {e}")

    # Exit
    print("\n# === ExitSystem ===")
    time.sleep(0.5)
    rc = dll.ExitSystem()
    print(f"  ExitSystem rc={rc}")

    print("\n# done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
