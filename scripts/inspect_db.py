"""查 SQLite DB schema。"""
import sqlite3
import os
db_path = r'D:\wenxj\7-型号\zwxxx-3\1_文件\1_任务规划\4_测试相关文件\20260922星上测试DLL-2\20260922星上测试DLL-2\WEINA.db'
print(f"DB: {os.path.getsize(db_path)} bytes")
db = sqlite3.connect(db_path)
cur = db.cursor()
cur.execute("SELECT name, sql FROM sqlite_master WHERE type='table'")
rows = cur.fetchall()
print(f"# tables: {len(rows)}")
for name, sql in rows:
    print(f"\n=== {name} ===")
    print(sql)
    # 看是否有数据
    try:
        cur.execute(f"SELECT * FROM {name} LIMIT 3")
        for r in cur.fetchall():
            print(f"  row: {r}")
    except Exception as e:
        print(f"  query failed: {e}")
db.close()
