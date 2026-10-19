"""注入目标到 SQLite DB,再调 calOpticsTimeWindow。

策略:
1. 启动 dll(DllInit)
2. 直接用 sqlite3 往 WEINA.db 插入一个目标(经度120 纬度30)
3. calOpticsTimeWindow 用 target_id=1 + start_time 试探
4. 看是否能返回 0
"""
import ctypes, faulthandler, os, sys, time, struct, sqlite3
faulthandler.enable()
os.chdir(r'D:\wenxj\7-型号\zwxxx-3\1_文件\1_任务规划\4_测试相关文件\20260922星上测试DLL-2\20260922星上测试DLL-2')

dll = ctypes.CDLL(r'D:\wenxj\7-型号\zwxxx-3\1_文件\1_任务规划\4_测试相关文件\20260922星上测试DLL-2\20260922星上测试DLL-2\WeiNa2_star_win.dll')
dll.DllInit.argtypes=[]; dll.DllInit.restype=ctypes.c_int
dll.calOpticsTimeWindow.argtypes=[ctypes.c_void_p, ctypes.c_double, ctypes.c_double, ctypes.c_void_p]
dll.calOpticsTimeWindow.restype=ctypes.c_int
dll.ExitSystem.argtypes=[]; dll.ExitSystem.restype=ctypes.c_int

print("=== DllInit ===", flush=True)
rc = dll.DllInit()
print(f"  rc={rc}", flush=True)
time.sleep(1.0)

# 现在直接操作 DB
print("\n=== insert target to DB ===", flush=True)
db = sqlite3.connect('WEINA.db')
cur = db.cursor()
# 先清空
try:
    cur.execute("DELETE FROM Target")
except Exception: pass
# 插入一个目标
cur.execute("INSERT INTO Target (target_id, priority, property, lon, lat, alt, is_use) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (1, 1, 1, 120.0, 30.0, 0.0, 1))
db.commit()
# 查看
cur.execute("SELECT * FROM Target")
for r in cur.fetchall():
    print(f"  inserted: {r}", flush=True)
db.close()  # 重要:让 dll 重新打开

print("\n=== calOpticsTimeWindow ===", flush=True)
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
    except Exception as e:
        print(f"    EXC: {e}", flush=True)

# 各种 target 内存布局尝试

# 假设 A: target_id (int64 at +0), start_time (double at +8)
def set_A(b):
    struct.pack_into('<q', b, 0, 1)         # target_id=1
    struct.pack_into('<d', b, 8, float(now_secs))  # start_time=now
call("A: target_id=1 @+0, start_time=now @+8",
     t0=now_secs, t1=now_secs+100.0, setup=set_A)

# 假设 B: target_id (int32 at +0), start_time (double at +8)
def set_B(b):
    struct.pack_into('<i', b, 0, 1)         # target_id=1 (int32)
    struct.pack_into('<d', b, 8, float(now_secs))
call("B: target_id=1 @+0 (i32), start_time=now @+8",
     t0=now_secs, t1=now_secs+100.0, setup=set_B)

# 假设 C: 不带 target_id,start_time + 后续字段(可能 target 结构是完整的)
def set_C(b):
    struct.pack_into('<d', b, 8, float(now_secs))
    struct.pack_into('<d', b, 16, 120.0)  # lon
    struct.pack_into('<d', b, 24, 30.0)   # lat
    struct.pack_into('<d', b, 32, 0.0)    # alt
call("C: +8=now, +16=lon=120, +24=lat=30, +32=alt=0",
     t0=now_secs, t1=now_secs+100.0, setup=set_C)

# 假设 D: target 是 DB 行的镜像: int target_id @0, int priority @4, int property @8, double lon @16...
# 但反汇编说 +8 是 double,所以这布局不对。除非 +0 是 target_id, +8 之后是别的东西
# 试 D: target_id @0, 其他全 0
def set_D(b):
    struct.pack_into('<i', b, 0, 1)  # target_id=1
call("D: target_id=1 @+0 only (rest zero)",
     t0=now_secs, t1=now_secs+100.0, setup=set_D)

# 假设 E: start_time 必须在 [t0, t1] 之间(非 now)
call("E: target[+8]=now+50, t0=now, t1=now+100",
     t0=now_secs, t1=now_secs+100.0,
     setup=lambda b: struct.pack_into('<d', b, 8, float(now_secs + 50.0)))

# 假设 F: target_id + start_time + 0x10 处可能是字节长度或类型
def set_F(b):
    struct.pack_into('<i', b, 0, 1)             # target_id=1
    struct.pack_into('<d', b, 8, float(now_secs + 50.0))  # start_time
    struct.pack_into('<i', b, 16, 1)           # 某类型=1?
call("F: id=1, +8=start_time, +16=1",
     t0=now_secs, t1=now_secs+100.0, setup=set_F)

print("\n=== ExitSystem ===", flush=True)
time.sleep(0.3)
dll.ExitSystem()
print("done", flush=True)
