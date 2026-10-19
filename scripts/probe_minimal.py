"""最小化定位 calOpticsTimeWindow 的崩溃点。"""
import ctypes, faulthandler, os, sys, time, struct
faulthandler.enable()
os.chdir(r'D:\wenxj\7-型号\zwxxx-3\1_文件\1_任务规划\4_测试相关文件\20260922星上测试DLL-2\20260922星上测试DLL-2')
dll = ctypes.CDLL(r'D:\wenxj\7-型号\zwxxx-3\1_文件\1_任务规划\4_测试相关文件\20260922星上测试DLL-2\20260922星上测试DLL-2\WeiNa2_star_win.dll')
dll.DllInit.argtypes=[]; dll.DllInit.restype=ctypes.c_int
dll.calOpticsTimeWindow.argtypes=[ctypes.c_void_p, ctypes.c_double, ctypes.c_double, ctypes.c_void_p]
dll.calOpticsTimeWindow.restype=ctypes.c_int
dll.ExitSystem.argtypes=[]; dll.ExitSystem.restype=ctypes.c_int

print("DllInit...", flush=True)
rc = dll.DllInit()
print(f"  rc={rc}", flush=True)
time.sleep(1.0)

# target 缓冲
tgt = (ctypes.c_ubyte * 512)()
out = (ctypes.c_ubyte * (7200*64+1024))()
print("call calOpticsTimeWindow(zero, 0.0, 100.0, out)...", flush=True)
try:
    rc2 = dll.calOpticsTimeWindow(ctypes.cast(tgt, ctypes.c_void_p), 0.0, 100.0, ctypes.cast(out, ctypes.c_void_p))
    print(f"  rc2={rc2}", flush=True)
except Exception as e:
    print(f"  EXC: {e}", flush=True)

print("ExitSystem...", flush=True)
dll.ExitSystem()
print("done", flush=True)
