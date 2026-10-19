"""改进版 ctypes 试探:DllInit 后等待,再逐个调用。

发现:
- DllInit 内部启动 socket 线程,需要时间
- DeployComInfo.xml 配置了 UDP 端口监听
- 需要等内部线程就绪后再调用其他函数
"""
from __future__ import annotations

import ctypes
import faulthandler
import logging
import os
import struct
import sys
import time
import traceback
from pathlib import Path

faulthandler.enable()

DLL_PATH = r"D:\wenxj\7-型号\zwxxx-3\1_文件\1_任务规划\4_测试相关文件\20260922星上测试DLL-2\20260922星上测试DLL-2\WeiNa2_star_win.dll"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("dll_probe_v2")

# 切换工作目录到 dll 所在目录,确保能找到配置文件与日志
os.chdir(os.path.dirname(DLL_PATH))


def main() -> int:
    p = Path(DLL_PATH)
    print(f"# cwd: {os.getcwd()}")
    print(f"# loading dll: {p.name}")
    try:
        dll = ctypes.CDLL(DLL_PATH)
        print(f"  loaded OK: handle={dll._handle:#x}")
    except OSError as e:
        print(f"  load FAILED: {e}")
        return 1

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
    print("\n# === Step 1: DllInit() ===")
    try:
        rc = dll.DllInit()
        print(f"  DllInit returned: {rc}")
    except Exception as e:
        print(f"  DllInit EXCEPTION: {e}")
        faulthandler.dump_traceback()
        # 即便崩溃,也尝试 ExitSystem
        try:
            dll.ExitSystem()
        except Exception:
            pass
        return 2

    # 等待内部线程/socket 就绪
    print("  waiting 2s for internal threads to start...")
    time.sleep(2.0)

    # 如果 DllInit 返回非 0,可能仍能调其他函数(看错误码语义)
    # 测试 DllInput 用全零缓冲(但带长度信息)
    print("\n# === Step 2: DllInput probe ===")
    # 给个大缓冲,先填 0
    INPUT_SIZE = 0x10000  # 64KB
    input_buf = (ctypes.c_ubyte * INPUT_SIZE)()
    for sz in [0, 4, 64, 1024]:
        try:
            rc = dll.DllInput(ctypes.cast(input_buf, ctypes.c_void_p), sz)
            print(f"  DllInput(buf, len={sz}) returned: {rc}")
        except Exception as e:
            print(f"  DllInput(len={sz}) EXCEPTION: {e}")
            break

    # Step 3: calOpticsTimeWindow
    print("\n# === Step 3: calOpticsTimeWindow ===")
    TARGET_SIZE = 512
    target_buf = (ctypes.c_ubyte * TARGET_SIZE)()
    OUT_SIZE = 7200 * 64 + 1024
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
            print(f"    returned: {rc} (0x{rc & 0xffffffff:x})")
            if rc >= 0:
                print(f"    -> 可能成功, count={rc}")
                nonzero = sum(1 for i in range(min(OUT_SIZE, 1024)) if out_buf[i] != 0)
                print(f"    out non-zero: {nonzero} bytes")
                if nonzero > 0:
                    print(f"    out[0:64]: {bytes(out_buf[:64]).hex()}")
                    for off in range(0, 64, 8):
                        d = struct.unpack_from("<d", bytes(out_buf[:64]), off)[0]
                        print(f"      +{off}: double={d}")
            elif rc == -1:
                print("    -> 轨道预报失败")
            elif rc == -2:
                print("    -> -2 (未初始化或 target 校验失败)")
        except Exception as e:
            print(f"    EXCEPTION: {e}")
            faulthandler.dump_traceback()

    # 试 1: 全零
    try_call("test1: zero target, t0=0 t1=100")

    # 试 2: target[+8] = 当前时间(相对 2009 epoch)
    stk_epoch = 1230768000
    now_secs = time.time() - stk_epoch
    def set_real_time(buf):
        struct.pack_into("<d", buf, 8, float(now_secs))
    try_call(f"test2: target[+8]=now({now_secs:.0f}s)", t0=0.0, t1=100.0,
             setup=set_real_time)

    # 试 3: target[+8] = 1.0, t0=0, t1=10
    def set_1(buf): struct.pack_into("<d", buf, 8, 1.0)
    try_call("test3: target[+8]=1.0, t0=0 t1=10", t0=0.0, t1=10.0, setup=set_1)

    # Step 4: DllOutput
    print("\n# === Step 4: DllOutput ===")
    out2 = (ctypes.c_ubyte * 0x10000)()
    ctx = (ctypes.c_ubyte * 0x1000)()
    try:
        rc = dll.DllOutput(ctypes.cast(out2, ctypes.c_void_p),
                          ctypes.cast(ctx, ctypes.c_void_p))
        print(f"  DllOutput returned: {rc}")
        nonzero = sum(1 for i in range(1024) if out2[i] != 0)
        print(f"  out non-zero: {nonzero}")
    except Exception as e:
        print(f"  DllOutput EXCEPTION: {e}")

    # Step 5: ExitSystem
    print("\n# === Step 5: ExitSystem() ===")
    time.sleep(1)
    try:
        rc = dll.ExitSystem()
        print(f"  ExitSystem returned: {rc}")
    except Exception as e:
        print(f"  ExitSystem EXCEPTION: {e}")

    print("\n# done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
