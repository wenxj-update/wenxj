"""试探 DllInput 的真实数据格式。

发现:
- DllInput rc=0 但日志说 "type=256 (0x100) 无法解析"
- 0x100 = 256 = 我们 data[0..1] (LE) = 0x0001 → 不对,那应该是 1
- 实际 0x100 可能是 (data[1]*0x100 + data[0]) 的反 — 我们 checksum 字段

看反汇编 #18: call 0x18002aeb0 — 入参 ecx = 全局值 0xd3 = 211
所以 type 是从全局查表,key 是什么?

也许 DllInput 参数#2 是 type code!不是长度!让我重读反汇编:
  movzx edx, word [rsp+0x38]   # 取参数#2 word
  mov rcx, [rsp+0x30]           # 取参数#1
  call 0x180035ae0               # 调用

在 0x180035ae0 内部:
  movzx eax, word [rsp+0x2888]   # 这是参数#2 (0x2880 是 rsp 位置,加 8 是参数#2)
                                  # 实际值是参数#2 的 word
  mov [rsp+0x46], ax              # 保存为 word
  
后来:#26 mov rdx, [rsp+0x2880]   # 参数#1
      #27 lea rcx, [rsp+0x4a]
      #28 call memcpy             # memcpy(local, data, type_code??)

所以参数#2 真的是长度!但内部又用它做 type code?让我再看一遍 — 实际是:
- 参数#2 (word) = 长度
- 用长度做 memcpy

但全局 [rip+0x253bf6] 在 0x18002ab90 是:
  mov ecx, [rip+0x253bf6]
  call 0x18002aeb0

这里 ecx 是全局值(不是参数),用作 type code 在表里查处理函数。但 211 是固定的?不对,等等:
反汇编 #17: mov ecx, dword [rsp+0x40]
这里 [rsp+0x40] 是从 0x18002ab90 入口参数#1 来的。
0x18002ab90 入口:
  mov [rsp+8], ecx   # 参数#1 (int32) 存到 +8
  mov [rsp+0x10], rdx  # 参数#2 (data*) 存到 +0x10
  sub rsp, 0x30
  ...
  mov ecx, [rsp+0x40]  # 取 +8+0x38 = 原 [rsp+8] = 参数#1

所以参数#1 是 type code! 0x180035ae0 调 0x18002ab90 时,ecx 是什么?
0x180035ae0 内部 #51: mov ecx, dword [rip + 0x253bf6]
                       call 0x18002ab90

所以 type code 来自全局变量 [rip+0x253bf6] = 0x1802897d4
我们之前看到 int32=211, uint32=211, hex=d3000000d7000000

但 211 不是 256!那 256 从哪来?

可能日志的 "type=256" 是另一个东西,比如 message_id。
看 0x18002aeb0 用的 ecx = 211 在表里查不到对应处理函数,然后 DllInput 返回 1 或别的码,但日志输出"消息 type=256"。

让我换思路:直接用各种 type code 测试,不依赖反汇编。
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

# 试不同 type code 作为参数#2(可能不是长度,是 type code!)
# 我们之前 len=46 rc=0,所以 0x2E=46 不可能 type code
# 但试试 type=1, 2, 3 看返回值

# 先准备一个 payload(目标库格式)
payload = struct.pack("<i", 1)  # count=1
payload += struct.pack("<q", 1)  # id=1
payload += struct.pack("<d", 120.0)  # lon
payload += struct.pack("<d", 30.0)  # lat
payload += struct.pack("<d", 0.0)  # alt
payload += struct.pack("<i", 1)  # priority
payload += struct.pack("<i", 1)  # property

# 校验和 = payload[1]*0x100 + payload[0]
cs = payload[1] * 0x100 + payload[0] if len(payload) >= 2 else 0
data = struct.pack("<H", cs) + payload
total_len = len(data)
print(f"\n# payload len={len(payload)}, total={total_len}, data hex={data.hex()}", flush=True)

# 试不同 type code 作为参数#2(占位类型 0-10)
buf = (ctypes.c_ubyte * len(data))(*data)
print(f"\n=== try different type codes (param#2) ===", flush=True)
for tc in [0, 1, 2, 3, 4, 5, 0x10, 0x100, 0x200, 0x1000]:
    try:
        # 重新构造 buf(每次)
        b = (ctypes.c_ubyte * len(data))(*data)
        rc = dll.DllInput(ctypes.cast(b, ctypes.c_void_p), tc)
        print(f"  DllInput(type={tc}, 0x{tc:x}) rc={rc}", flush=True)
    except Exception as e:
        print(f"  DllInput(type={tc}) EXC: {e}", flush=True)
        # 可能崩溃了,重新 init
        time.sleep(0.5)
        try: dll.ExitSystem()
        except: pass
        dll2 = ctypes.CDLL(r'D:\wenxj\7-型号\zwxxx-3\1_文件\1_任务规划\4_测试相关文件\20260922星上测试DLL-2\20260922星上测试DLL-2\WeiNa2_star_win.dll')
        dll2.DllInit.argtypes=[]; dll2.DllInit.restype=ctypes.c_int
        dll2.DllInput.argtypes=[ctypes.c_void_p, ctypes.c_int]; dll2.DllInput.restype=ctypes.c_int
        dll2.ExitSystem.argtypes=[]; dll2.ExitSystem.restype=ctypes.c_int
        dll2.DllInit()
        time.sleep(1)
        dll = dll2
        continue
    time.sleep(0.2)

# 看 DB
import sqlite3
db = sqlite3.connect('WEINA.db')
cur = db.cursor()
try:
    cur.execute("SELECT * FROM Target")
    rows = cur.fetchall()
    print(f"\n# DB Target rows: {len(rows)}", flush=True)
    for r in rows[:5]:
        print(f"  {r}", flush=True)
except Exception as e:
    print(f"  DB failed: {e}", flush=True)
db.close()

print("\n=== ExitSystem ===", flush=True)
dll.ExitSystem()
print("done", flush=True)
