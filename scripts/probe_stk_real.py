# -*- coding: utf-8 -*-
"""STK12 真实 COM 探查脚本(证据收集,不改业务代码)。

验证:
1) CreateObject STK12.Application / Person2
2) LoadScenario zw.sc
3) 场景时间 + Children 枚举(类名/对象名)
4) Connect Position 命令取卫星 ICRF/J2000 位置
5) DataProvider 取 Cartesian/ICRF Position+Velocity 与 Classical Elements
6) Target/Facility 大地坐标
"""
from __future__ import annotations

import os
import sys
import time
import traceback

SCENARIO = r"D:\Users\87752\Documents\STK 11 (x64)\zw\zw.sc"
PROGID = "STK12.Application"


def section(title: str) -> None:
    print("\n" + "=" * 20 + " " + title + " " + "=" * 20, flush=True)


def dump_cmd_result(res, label: str) -> None:
    """打印 ExecuteCommand 返回对象的全部可用信息。"""
    print(f"[{label}]")
    try:
        print("  StatusCode =", res.StatusCode)
    except Exception as e:  # noqa: BLE001
        print("  StatusCode ?", e)
    for attr in ("Result",):
        try:
            v = getattr(res, attr)
            print(f"  {attr} = {v!r}")
        except Exception as e:  # noqa: BLE001
            print(f"  {attr} ? {e}")
    try:
        lines = list(res.Lines)
        print(f"  Lines({len(lines)}):")
        for ln in lines[:20]:
            print("   |", ln)
    except Exception as e:  # noqa: BLE001
        print("  Lines ?", e)


def dump_dp(result, label: str, max_rows: int = 3) -> None:
    """打印 DataProvider Exec 结果。"""
    print(f"[{label}]")
    try:
        sets = list(result.DataSets)
        print("  datasets:", len(sets))
        cols = {}
        for ds in sets:
            try:
                name = ds.ElementName
            except Exception:  # noqa: BLE001
                name = "?"
            try:
                vals = list(ds.GetValues())
            except Exception as e:  # noqa: BLE001
                vals = [f"<{e}>"]
            cols[name] = vals
            print(f"  - {name}: {vals[:max_rows]}")
        return cols
    except Exception as e:  # noqa: BLE001
        print("  dump failed:", e)
        traceback.print_exc()
        return {}


def main() -> int:
    import comtypes
    import comtypes.client as cc
    try:
        comtypes.CoInitialize()
    except Exception:  # noqa: BLE001
        pass

    section("1. create/attach STK")
    t0 = time.time()
    app = None
    try:
        app = cc.GetActiveObject(PROGID)
        print("attached to running STK instance")
    except Exception:  # noqa: BLE001
        app = cc.CreateObject(PROGID)
        print("created new STK instance")
    try:
        app.Visible = True
    except Exception as e:  # noqa: BLE001
        print("visible set failed:", e)
    root = app.Personality2
    print("root ok, startup %.1f s" % (time.time() - t0))

    section("2. load scenario")
    try:
        root.LoadScenario(SCENARIO)
        print("LoadScenario ok:", SCENARIO)
    except Exception as e:  # noqa: BLE001
        print("LoadScenario failed:", e)
        traceback.print_exc()
        return 2
    sc = root.CurrentScenario
    print("scenario =", sc.InstanceName)
    try:
        print("StartTime =", sc.StartTime)
        print("StopTime  =", sc.StopTime)
        print("Epoch     =", getattr(sc, "Epoch", "?"))
    except Exception as e:  # noqa: BLE001
        print("time props failed:", e)

    section("3. enumerate children")
    children = sc.Children
    print("count =", children.Count)
    names = []
    for i in range(children.Count):
        obj = children.Item(i)
        names.append((obj.ClassName, obj.InstanceName))
        print(f"  [{i}] {obj.ClassName:12s} {obj.InstanceName}")
    sat_name = next((n for c, n in names if c == "Satellite"), "Satellite1")

    # DP 用的起止时间
    t_start = sc.StartTime
    t_stop = sc.StopTime

    section("4. Connect Position (satellite)")
    for csys in ("ICRF", "J2000"):
        cmd = f'Position */Satellite/{sat_name} {csys} Time "{t_start}"'
        try:
            res = root.ExecuteCommand(cmd)
            dump_cmd_result(res, cmd)
        except Exception as e:  # noqa: BLE001
            print(f"cmd failed [{cmd}]:", e)

    section("5. DataProviders position/velocity")
    sat = children.Item(sat_name)
    dpp = sat.DataProviders
    for path in ("Cartesian Position", "ICRF Position", "J2000 Position",
                 "Cartesian Velocity", "ICRF Velocity", "J2000 Velocity"):
        try:
            dp = dpp.GetDataPrvTimeVarFromPath(path)
            r = dp.Exec(t_start, t_start, 60.0)
            dump_dp(r, path)
        except Exception as e:  # noqa: BLE001
            print(f"[DP {path}] failed: {e}")

    section("6. Classical Elements")
    try:
        dp = dpp.GetDataPrvTimeVarFromPath("Classical Elements")
        print("PreData candidates:", list(getattr(dp, "PreDataList", [])))
        try:
            dp.PreData = "J2000"
        except Exception as e:  # noqa: BLE001
            print("PreData=J2000 failed:", e)
        r = dp.Exec(t_start, t_start, 60.0)
        dump_dp(r, "Classical Elements/J2000")
    except Exception as e:  # noqa: BLE001
        print("Classical Elements DP failed:", e)
        traceback.print_exc()

    section("7. Target / Facility positions")
    for cls, nm in names:
        if cls not in ("Target", "Place", "Facility"):
            continue
        cmd = f'Position */{cls}/{nm} Geodetic'
        try:
            res = root.ExecuteCommand(cmd)
            dump_cmd_result(res, cmd)
        except Exception as e:  # noqa: BLE001
            print(f"cmd failed [{cmd}]:", e)

    section("8. current animation time")
    try:
        res = root.ExecuteCommand("GetAnimTime *")
        dump_cmd_result(res, "GetAnimTime *")
    except Exception as e:  # noqa: BLE001
        print("GetAnimTime failed:", e)

    print("\nPROBE DONE. STK left open for inspection.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
