"""ctypes 动态试探 WeiNa2_star_win.dll 的函数语义。

策略:
1. DllInit() 无参,先调用验证链路
2. ExitSystem() 无参,验证退出
3. calOpticsTimeWindow(target, t0, t1, out) 用全零 target 试探
   - 若返回 -1 "轨道预报失败" → target 校验失败,逐步填值
   - 若返回 0 → 成功,看 out_buf 写入内容
4. 用 faulthandler 捕获段错误,定位崩溃点

target 结构(推断):
  +0   8 bytes 未知(指针/vtable)
  +8   double  start_time  (已确认)
  +16+          未确认(可能经纬度等)

输出结构(推断):
  循环 7200 次,每项 64 字节,末尾 count (int32)
  实际 out_buf 至少 7200*64 + 4 = 460804 字节
"""
from __future__ import annotations

import ctypes
import faulthandler
import logging
import sys
import traceback
from pathlib import Path

# 启用段错误时打印 Python 栈
faulthandler.enable()

DLL_PATH = r"D:\wenxj\7-型号\zwxxx-3\1_文件\1_任务规划\4_测试相关文件\20260922星上测试DLL-2\20260922星上测试DLL-2\WeiNa2_star_win.dll"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("dll_probe")


def main() -> int:
    p = Path(DLL_PATH)
    if not p.is_file():
        print(f"[ERR] not found: {p}")
        return 1

    print(f"# loading dll: {p.name}")
    try:
        dll = ctypes.CDLL(DLL_PATH)
        print(f"  loaded OK: handle={dll._handle:#x}")
    except OSError as e:
        print(f"  load FAILED: {e}")
        return 1

    # 绑定函数签名
    # DllInit() -> int
    dll.DllInit.argtypes = []
    dll.DllInit.restype = ctypes.c_int

    # DllInput(void* data, int count) -> int
    dll.DllInput.argtypes = [ctypes.c_void_p, ctypes.c_int]
    dll.DllInput.restype = ctypes.c_int

    # DllOutput(void* out, void* ctx) -> int
    dll.DllOutput.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    dll.DllOutput.restype = ctypes.c_int

    # ExitSystem() -> int
    dll.ExitSystem.argtypes = []
    dll.ExitSystem.restype = ctypes.c_int

    # calOpticsTimeWindow(void* target, double t0, double t1, void* out) -> int
    dll.calOpticsTimeWindow.argtypes = [
        ctypes.c_void_p,    # rcx
        ctypes.c_double,    # xmm1
        ctypes.c_double,    # xmm2
        ctypes.c_void_p,    # r9
    ]
    dll.calOpticsTimeWindow.restype = ctypes.c_int

    # ===== Step 1: DllInit =====
    print("\n# === Step 1: DllInit() ===")
    try:
        rc = dll.DllInit()
        print(f"  DllInit returned: {rc} (0x{rc & 0xffffffff:x})")
    except Exception as e:
        print(f"  DllInit FAILED: {e}")
        traceback.print_exc()
        return 2

    # ===== Step 2: calOpticsTimeWindow with all-zero target =====
    print("\n# === Step 2: calOpticsTimeWindow(zero target) ===")

    # target 缓冲:128 字节(够覆盖 +8 start_time 和后续字段)
    TARGET_SIZE = 256
    target_buf = (ctypes.c_ubyte * TARGET_SIZE)()

    # 输出缓冲:预估 7200 * 64 + 64(余量) = 460864 字节
    OUT_SIZE = 7200 * 64 + 1024
    out_buf = (ctypes.c_ubyte * OUT_SIZE)()

    # 试探 1:全零 target,t0=0, t1=100
    def try_call(label: str, setup_target=None, t0: float = 0.0, t1: float = 100.0):
        print(f"\n  --- {label} ---")
        # 重置 target
        for i in range(TARGET_SIZE):
            target_buf[i] = 0
        if setup_target is not None:
            setup_target(target_buf)
        # 重置 out
        for i in range(OUT_SIZE):
            out_buf[i] = 0
        try:
            rc = dll.calOpticsTimeWindow(
                ctypes.cast(target_buf, ctypes.c_void_p),
                ctypes.c_double(t0),
                ctypes.c_double(t1),
                ctypes.cast(out_buf, ctypes.c_void_p),
            )
            print(f"    returned: {rc} (0x{rc & 0xffffffff:x})")
            # 看返回值语义
            if rc == -1 or rc == 0xffffffff:
                print("    -> '轨道预报失败' (target 校验未通过)")
            elif rc == 0:
                print("    -> 成功? 检查 out_buf 是否被写入")
                # 看 out_buf 前 256 字节
                nonzero = sum(1 for i in range(256) if out_buf[i] != 0)
                print(f"    out_buf first 256 bytes: {nonzero} non-zero")
                if nonzero > 0:
                    # dump 前 64 字节
                    head = bytes(out_buf[:64])
                    print(f"    out_buf[0:64] hex: {head.hex()}")
                    # 试着按 double 解读
                    import struct
                    for off in range(0, 64, 8):
                        try:
                            d = struct.unpack_from("<d", head, off)[0]
                            print(f"      +{off}: double={d}")
                        except Exception:
                            pass
            else:
                print(f"    -> 其他返回值,可能 count={rc}")
                nonzero = sum(1 for i in range(min(OUT_SIZE, 1024)) if out_buf[i] != 0)
                print(f"    out_buf first 1024 bytes: {nonzero} non-zero")
                if nonzero > 0:
                    head = bytes(out_buf[:64])
                    print(f"    out_buf[0:64] hex: {head.hex()}")
        except OSError as e:
            print(f"    CRASH: {e}")
            faulthandler.dump_traceback()
            return False
        return True

    # 试 1:全零
    if not try_call("test1: all-zero target, t0=0 t1=100"):
        return 3

    # 试 2:target[+8] = 1.0 (start_time 非0)
    def set_start_time(buf):
        import struct
        struct.pack_into("<d", buf, 8, 1.0)
    try_call("test2: target[+8]=1.0 (start_time=1)", set_start_time)

    # 试 3:target[+8] = 当前历元秒(模拟真实时间)
    import time
    def set_real_time(buf):
        import struct
        # 2009-01-01 UTC 的 Unix 时间戳
        stk_epoch = 1230768000  # 2009-01-01 00:00:00 UTC
        # 当前时间相对 STK epoch 的秒数
        now_secs = time.time() - stk_epoch
        struct.pack_into("<d", buf, 8, now_secs)
    try_call("test3: target[+8]=now (relative to 2009 epoch)", set_real_time,
             t0=0.0, t1=100.0)

    # 试 4:target[+8] = 小值,t0 = -100, t1 = 100 (t0 < target[+8])
    def set_small_start(buf):
        import struct
        struct.pack_into("<d", buf, 8, 50.0)
    try_call("test4: target[+8]=50, t0=-100, t1=100", set_small_start,
             t0=-100.0, t1=100.0)

    # ===== Step 3: DllInput 试探(注入数据) =====
    print("\n# === Step 3: DllInput probe ===")
    # 先给个空数据看返回值
    input_buf = (ctypes.c_ubyte * 4096)()
    try:
        rc = dll.DllInput(ctypes.cast(input_buf, ctypes.c_void_p), 0)
        print(f"  DllInput(buf, count=0) returned: {rc}")
    except Exception as e:
        print(f"  DllInput FAILED: {e}")

    # ===== Step 4: DllOutput 试探 =====
    print("\n# === Step 4: DllOutput probe ===")
    out2 = (ctypes.c_ubyte * 0x3000)()  # 12KB
    ctx = (ctypes.c_ubyte * 0x100)()
    try:
        rc = dll.DllOutput(ctypes.cast(out2, ctypes.c_void_p),
                          ctypes.cast(ctx, ctypes.c_void_p))
        print(f"  DllOutput returned: {rc}")
        nonzero = sum(1 for i in range(min(0x3000, 1024)) if out2[i] != 0)
        print(f"  out first 1024 bytes: {nonzero} non-zero")
        if nonzero > 0:
            print(f"  out[0:64] hex: {bytes(out2[:64]).hex()}")
    except Exception as e:
        print(f"  DllOutput FAILED: {e}")

    # ===== Step 5: ExitSystem =====
    print("\n# === Step 5: ExitSystem() ===")
    try:
        rc = dll.ExitSystem()
        print(f"  ExitSystem returned: {rc}")
    except Exception as e:
        print(f"  ExitSystem FAILED: {e}")

    print("\n# done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
