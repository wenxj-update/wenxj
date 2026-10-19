"""探测 DllInput/DllOutput 的实际行为,并尝试让 calOpticsTimeWindow 成功。

策略:
1. DllInit
2. DllInput 各种缓冲试探(看返回值和日志)
3. DllOutput 看输出内容
4. calOpticsTimeWindow 用各种 target 字段组合试探

关键:DllInit 创建了 SQLite DB 表 Target,推测:
- DllInput 把目标数据写入 DB
- calOpticsTimeWindow 根据 target[+8] 时间戳从 DB 查目标,做可见性计算
"""
import ctypes, faulthandler, os, sys, time, struct, logging
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
if rc != 0:
    dll.ExitSystem(); sys.exit(1)
time.sleep(1.0)

# 看 dll 目录里有什么文件被生成
print("\n=== files in dll dir ===", flush=True)
for f in os.listdir('.'):
    if os.path.isfile(f):
        sz = os.path.getsize(f)
        print(f"  {f}  ({sz} bytes)", flush=True)

# DllInput 试探
print("\n=== DllInput ===", flush=True)
inp = (ctypes.c_ubyte * 0x10000)()
# 全零缓冲,不同长度
for sz in [0, 4, 16, 32, 64, 128, 256, 512, 1024, 4096]:
    try:
        rc = dll.DllInput(ctypes.cast(inp, ctypes.c_void_p), sz)
        print(f"  DllInput(buf, len={sz}) rc={rc}", flush=True)
    except Exception as e:
        print(f"  DllInput(len={sz}) EXC: {e}", flush=True)
        faulthandler.dump_traceback()
        # 严重错误就跳出
        break
    time.sleep(0.1)

# DllOutput 试探
print("\n=== DllOutput ===", flush=True)
out = (ctypes.c_ubyte * 0x10000)()
ctx = (ctypes.c_ubyte * 0x1000)()
for off in [None]:
    try:
        rc = dll.DllOutput(ctypes.cast(out, ctypes.c_void_p), ctypes.cast(ctx, ctypes.c_void_p))
        print(f"  DllOutput rc={rc}", flush=True)
        nz = sum(1 for i in range(1024) if out[i] != 0)
        print(f"  out non-zero: {nz}", flush=True)
        if nz > 0:
            print(f"  out[0:64]: {bytes(out[:64]).hex()}", flush=True)
    except Exception as e:
        print(f"  EXC: {e}", flush=True)

# 再看目录,看 DB 文件
print("\n=== files after DllInput/Output ===", flush=True)
for f in os.listdir('.'):
    if os.path.isfile(f):
        sz = os.path.getsize(f)
        print(f"  {f}  ({sz} bytes)", flush=True)

# calOpticsTimeWindow 各种 target 字段
print("\n=== calOpticsTimeWindow ===", flush=True)
tgt = (ctypes.c_ubyte * 512)()
out2 = (ctypes.c_ubyte * (7200*64+1024))()

def reset():
    for i in range(512): tgt[i] = 0
    for i in range(len(out2)): out2[i] = 0

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
                for off in range(0, 128, 8):
                    d = struct.unpack_from('<d', bytes(out2[:128]), off)[0]
                    print(f"      +{off}: double={d}", flush=True)
    except Exception as e:
        print(f"    EXC: {e}", flush=True)

# 现在 target[+8] 各种时间
stk_epoch = 1230768000
now_secs = time.time() - stk_epoch
print(f"\n# now_secs since 2009 epoch: {now_secs:.0f}", flush=True)

call("c1: zero target, t0=0 t1=100")
call("c2: target[+8]=100, t0=0 t1=100", setup=lambda b: struct.pack_into('<d', b, 8, 100.0))
call("c3: target[+8]=now, t0=0 t1=100", setup=lambda b: struct.pack_into('<d', b, 8, float(now_secs)))
call(f"c4: target[+8]=now, t0=now, t1=now+100",
     t0=now_secs, t1=now_secs+100,
     setup=lambda b: struct.pack_into('<d', b, 8, float(now_secs)))
# 试试 target[+0]=某指针(可能需要 callback 或 ctx)
def set_vtable(b):
    # 用一个 cfuncptr 作为 vtable?可能危险,先用整数地址
    struct.pack_into('<Q', b, 0, 0)  # 0
    struct.pack_into('<d', b, 8, float(now_secs))
call("c5: target[+0]=0, target[+8]=now", t0=now_secs, t1=now_secs+100, setup=set_vtable)

print("\n=== ExitSystem ===", flush=True)
time.sleep(0.5)
dll.ExitSystem()
print("done", flush=True)
