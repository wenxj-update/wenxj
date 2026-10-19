"""按字符串提示构造目标库批量数据,调 DllInput 注入,然后 calOpticsTimeWindow。

字符串证据(目标库批量导入格式):
  目标数量[%d] 目标编号[%d] 目标经度[%f] 目标纬度[%f] 目标高程[%f] 目标优先级[%d]

但 DllInput 校验和: data[0..1] = checksum(LE), data[2..] = payload
长度参数包含 2 字节 checksum

试探格式:
  [2B checksum][int32 count]
  [int64 target_id][double lon][double lat][double alt][int32 priority][int32 property]...
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
if rc != 0:
    dll.ExitSystem(); sys.exit(1)
time.sleep(1.0)

# 构造目标库数据
# 格式推测:[2B checksum LE][int32 count]
#          每个:[int64 id][double lon][double lat][double alt][int32 priority][int32 property]
# 单个目标 = 8 + 8*3 + 4 + 4 = 36 字节
# 两个字节 checksum + 4 字节 count + 36*N

def make_target_data(targets):
    """生成目标库批量数据。
    targets: [(id, lon, lat, alt, priority, property), ...]
    """
    # payload 部分(不含 checksum)
    payload = struct.pack("<i", len(targets))
    for tid, lon, lat, alt, pri, prop in targets:
        payload += struct.pack("<q", tid)
        payload += struct.pack("<d", lon)
        payload += struct.pack("<d", lat)
        payload += struct.pack("<d", alt)
        payload += struct.pack("<i", pri)
        payload += struct.pack("<i", prop)
    # checksum = payload[1]*0x100 + payload[0]  (反汇编里看到的)
    if len(payload) >= 2:
        cs = payload[1] * 0x100 + payload[0]
    else:
        cs = 0
    cs_bytes = struct.pack("<H", cs)
    return cs_bytes + payload, len(cs_bytes + payload)

# 试 1:注入一个目标 (id=1, lon=120, lat=30, alt=0, priority=1, property=1)
data, total_len = make_target_data([
    (1, 120.0, 30.0, 0.0, 1, 1),
])
print(f"\n=== DllInput (target库, len={total_len}) ===", flush=True)
print(f"  data hex: {data.hex()}", flush=True)
buf = (ctypes.c_ubyte * len(data))(*data)
try:
    rc = dll.DllInput(ctypes.cast(buf, ctypes.c_void_p), total_len)
    print(f"  DllInput rc={rc}", flush=True)
except Exception as e:
    print(f"  EXC: {e}", flush=True)
    faulthandler.dump_traceback()

# 看 DB
import sqlite3
db = sqlite3.connect('WEINA.db')
cur = db.cursor()
try:
    cur.execute("SELECT * FROM Target")
    rows = cur.fetchall()
    print(f"  DB Target rows: {len(rows)}", flush=True)
    for r in rows[:5]:
        print(f"    {r}", flush=True)
except Exception as e:
    print(f"  DB query failed: {e}", flush=True)
db.close()

# 现在试 calOpticsTimeWindow
print(f"\n=== calOpticsTimeWindow ===", flush=True)
tgt = (ctypes.c_ubyte * 512)()
out = (ctypes.c_ubyte * (7200*64+1024))()

stk_epoch = 1230768000
now_secs = time.time() - stk_epoch
print(f"# now_secs={now_secs:.0f}", flush=True)

def reset():
    for i in range(512): tgt[i] = 0
    for i in range(len(out)): out[i] = 0

def call(label, t0=0.0, t1=100.0, setup=None):
    print(f"\n  --- {label} ---", flush=True)
    reset()
    if setup: setup(tgt)
    try:
        rc = dll.calOpticsTimeWindow(
            ctypes.cast(tgt, ctypes.c_void_p),
            ctypes.c_double(t0), ctypes.c_double(t1),
            ctypes.cast(out, ctypes.c_void_p))
        print(f"    rc={rc} (0x{rc & 0xffffffff:x})", flush=True)
        if rc >= 0:
            nz = sum(1 for i in range(2048) if out[i] != 0)
            print(f"    out non-zero: {nz}", flush=True)
            if nz > 0:
                print(f"    out[0:128]: {bytes(out[:128]).hex()}", flush=True)
                for off in range(0, 128, 8):
                    d = struct.unpack_from('<d', bytes(out[:128]), off)[0]
                    print(f"      +{off}: double={d}", flush=True)
    except Exception as e:
        print(f"    EXC: {e}", flush=True)

# target 结构(推测):
# +0  int64  target_id
# +8  double start_time (实际上反汇编说 +8 与 t_end 比较,所以可能是某时间)
def set_tgt(tid, t_start):
    def f(b):
        struct.pack_into('<q', b, 0, tid)
        struct.pack_into('<d', b, 8, t_start)
    return f

call("c1: id=1, +8=now, t0=0, t1=now+200",
     t0=0.0, t1=now_secs + 200.0,
     setup=set_tgt(1, now_secs))

call("c2: id=1, +8=0, t0=0, t1=now_secs+200",
     t0=0.0, t1=now_secs + 200.0,
     setup=set_tgt(1, 0.0))

call("c3: id=1, +8=now, t0=now, t1=now+200",
     t0=now_secs, t1=now_secs + 200.0,
     setup=set_tgt(1, now_secs))

print("\n=== ExitSystem ===", flush=True)
dll.ExitSystem()
print("done", flush=True)
