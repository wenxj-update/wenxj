"""DllInput 安全试探:不传 NULL/len=0,改用类型码模式。

从反汇编看,DllInput 参数#2 是 int(可能是数据类型枚举),
参数#1 是数据指针。
不传数据(只看 DllOutput 和 calOpticsTimeWindow)。
"""
import ctypes, faulthandler, os, sys, time, struct
faulthandler.enable()
os.chdir(r'D:\wenxj\7-型号\zwxxx-3\1_文件\1_任务规划\4_测试相关文件\20260922星上测试DLL-2\20260922星上测试DLL-2')

dll = ctypes.CDLL(r'D:\wenxj\7-型号\zwxxx-3\1_文件\1_任务规划\4_测试相关文件\20260922星上测试DLL-2\20260922星上测试DLL-2\WeiNa2_star_win.dll')
dll.DllInit.argtypes=[]; dll.DllInit.restype=ctypes.c_int
dll.DllInput.argtypes=[ctypes.c_void_p, ctypes.c_int]; dll.DllInput.restype=ctypes.c_int
dll.DllOutput.argtypes=[ctypes.c_void_p, ctypes.c_void_p]; dll.DllOutput.restype=ctypes.c_int
dll.calOpticsTimeWindow.argtypes=[ctypes.c_void_p, ctypes.c_double, ctypes.c_double, ctypes.c_void_p]
dll.calOpticsTimeWindow.restype=ctypes.c_int
dll.ExitSystem.argtypes=[]; dll.ExitSystem.restype=ctypes.c_int

print("=== DllInit ===", flush=True)
rc = dll.DllInit()
print(f"  rc={rc}", flush=True)
time.sleep(1.0)

# DllOutput 先(应该不需要前置 DllInput)
print("\n=== DllOutput ===", flush=True)
out = (ctypes.c_ubyte * 0x10000)()
ctx = (ctypes.c_ubyte * 0x1000)()
# 试不同 ctx 类型码
for ctx_val in [0, 1, 2, 3]:
    for i in range(len(ctx)): ctx[i] = 0
    struct.pack_into('<i', ctx, 0, ctx_val)  # 第一字段设为类型码?
    try:
        rc = dll.DllOutput(ctypes.cast(out, ctypes.c_void_p), ctypes.cast(ctx, ctypes.c_void_p))
        print(f"  DllOutput(ctx[0]={ctx_val}) rc={rc}", flush=True)
        nz = sum(1 for i in range(1024) if out[i] != 0)
        print(f"    out non-zero: {nz}", flush=True)
        if nz > 0:
            print(f"    out[0:64]: {bytes(out[:64]).hex()}", flush=True)
            break
    except Exception as e:
        print(f"  DllOutput(ctx[0]={ctx_val}) EXC: {e}", flush=True)
        break
    time.sleep(0.1)

# calOpticsTimeWindow 各种 target
print("\n=== calOpticsTimeWindow ===", flush=True)
tgt = (ctypes.c_ubyte * 512)()
out2 = (ctypes.c_ubyte * (7200*64+1024))()

def reset():
    for i in range(512): tgt[i] = 0
    for i in range(len(out2)): out2[i] = 0

stk_epoch = 1230768000
now_secs = time.time() - stk_epoch
print(f"# now_secs={now_secs:.0f}", flush=True)

def call(label, t0=0.0, t1=100.0, setup=None):
    print(f"\n  --- {label} ---", flush=True)
    reset()
    if setup: setup(tgt)
    try:
        rc = dll.calOpticsTimeWindow(
            ctypes.cast(tgt, ctypes.c_void_p),
            ctypes.c_double(t0), ctypes.c_double(t1),
            ctypes.cast(out2, ctypes.c_void_p))
        print(f"    rc={rc} (0x{rc & 0xffffffff:x})", flush=True)
        if rc >= 0:
            nz = sum(1 for i in range(2048) if out2[i] != 0)
            print(f"    out non-zero: {nz}", flush=True)
            if nz > 0:
                print(f"    out[0:128]: {bytes(out2[:128]).hex()}", flush=True)
    except Exception as e:
        print(f"    EXC: {e}", flush=True)

call("c1: zero target, t0=0 t1=100")
call("c2: target[+8]=100, t0=0 t1=100",
     setup=lambda b: struct.pack_into('<d', b, 8, 100.0))
call("c3: target[+8]=now, t0=0 t1=100",
     setup=lambda b: struct.pack_into('<d', b, 8, float(now_secs)))
call(f"c4: target[+8]=now, t0=now, t1=now+100",
     t0=now_secs, t1=now_secs+100.0,
     setup=lambda b: struct.pack_into('<d', b, 8, float(now_secs)))

# 试 target[+0]=某指针/对象地址(用 out2 自己地址?很危险)
# 改成 target[+0]=1 看看
call("c5: target[+0]=1, target[+8]=now",
     t0=now_secs, t1=now_secs+100.0,
     setup=lambda b: (struct.pack_into('<Q', b, 0, 1),
                      struct.pack_into('<d', b, 8, float(now_secs))))

# target[+16] 是另一个 double(可能 lon 经度)
call("c6: target[+8]=now, +16=120.0, +24=30.0",
     t0=now_secs, t1=now_secs+100.0,
     setup=lambda b: (struct.pack_into('<d', b, 8, float(now_secs)),
                      struct.pack_into('<d', b, 16, 120.0),
                      struct.pack_into('<d', b, 24, 30.0)))

print("\n=== ExitSystem ===", flush=True)
time.sleep(0.3)
dll.ExitSystem()
print("done", flush=True)
