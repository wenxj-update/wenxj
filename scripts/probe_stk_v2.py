# -*- coding: utf-8 -*-
"""STK12 探查 v2:附加到已运行实例,验证时间属性/Position 命令/DP/目标坐标。"""
from __future__ import annotations

import sys
import traceback

PROGID = "STK12.Application"


def section(t):
    print("\n" + "=" * 15 + " " + t + " " + "=" * 15, flush=True)


def dump_cmd(res, label):
    print(f"[{label}]")
    try:
        print("  StatusCode =", res.StatusCode)
    except Exception as e:  # noqa: BLE001
        print("  StatusCode ?", e)
    try:
        print("  Result =", repr(res.Result))
    except Exception as e:  # noqa: BLE001
        print("  Result ?", e)
    try:
        lines = list(res.Lines)
        print(f"  Lines({len(lines)}):")
        for ln in lines[:10]:
            print("   |", ln)
    except Exception as e:  # noqa: BLE001
        print("  Lines ?", e)


def dump_dp(result, label, max_rows=2):
    print(f"[{label}]")
    try:
        sets = list(result.DataSets)
        print("  datasets:", len(sets))
        for ds in sets:
            name = getattr(ds, "ElementName", "?")
            try:
                vals = list(ds.GetValues())
            except Exception as e:  # noqa: BLE001
                vals = [f"<{e}>"]
            print(f"  - {name}: {vals[:max_rows]}")
    except Exception:  # noqa: BLE001
        traceback.print_exc()


def main():
    import comtypes
    import comtypes.client as cc
    try:
        comtypes.CoInitialize()
    except Exception:  # noqa: BLE001
        pass
    cc.GetModule(r"C:\Program Files\AGI\STK 12\bin\AgStkObjects.dll")
    from comtypes.gen import STKObjects as ag
    app = cc.GetActiveObject(PROGID)
    root = app.Personality2
    sc_raw = root.CurrentScenario
    print("scenario =", sc_raw.InstanceName)
    sc = sc_raw.QueryInterface(ag.IAgScenario)

    section("A. scenario time props")
    for prop in ("AnalysisStartTime", "AnalysisStopTime", "Epoch",
                 "AnalysisEpoch", "StartTime", "StopTime"):
        try:
            print(f"  {prop} = {getattr(sc, prop)!r}")
        except Exception as e:  # noqa: BLE001
            print(f"  {prop} ? {e}")

    t_start = sc.StartTime
    t_stop = sc.StopTime
    print("use:", t_start, "->", t_stop)

    section("B. satellite Connect Position")
    for csys in ("ICRF", "J2000", "Fixed"):
        cmd = f'Position */Satellite/Satellite1 {csys} Time "{t_start}"'
        try:
            dump_cmd(root.ExecuteCommand(cmd), csys)
        except Exception as e:  # noqa: BLE001
            print(f"[{csys}] failed: {e}")

    section("C. satellite velocity via Connect")
    for cmd in (
        'Position */Satellite/Satellite1 ICRF Time "' + t_start + '" Velocity',
        'Position */Satellite/Satellite1 J2000 Time "' + t_start + '" Velocity',
    ):
        try:
            dump_cmd(root.ExecuteCommand(cmd), cmd)
        except Exception as e:  # noqa: BLE001
            print("failed:", e)

    section("D. DataProviders")
    children = sc.Children
    sat = children.Item("Satellite1")
    dpp = sat.DataProviders
    for path in ("Cartesian Position", "ICRF Position", "J2000 Position",
                 "Cartesian Velocity", "ICRF Velocity", "J2000 Velocity"):
        try:
            dp = dpp.GetDataPrvTimeVarFromPath(path)
            r = dp.Exec(t_start, t_start, 60.0)
            dump_dp(r, path)
        except Exception as e:  # noqa: BLE001
            print(f"[DP {path}] failed: {e}")

    section("E. Classical Elements DP")
    try:
        dp = dpp.GetDataPrvTimeVarFromPath("Classical Elements")
        try:
            print("PreDataList =", list(dp.PreDataList))
        except Exception as e:  # noqa: BLE001
            print("PreDataList ?", e)
        for pre in ("J2000", "ICRF"):
            try:
                dp.PreData = pre
                dump_dp(dp.Exec(t_start, t_start, 60.0), f"Classical/{pre}")
            except Exception as e:  # noqa: BLE001
                print(f"Classical/{pre} failed: {e}")
    except Exception:  # noqa: BLE001
        traceback.print_exc()

    section("F. ground objects Geodetic")
    for i in range(children.Count):
        obj = children.Item(i)
        if obj.ClassName not in ("Target", "Facility", "Place"):
            continue
        cmd = f'Position */{obj.ClassName}/{obj.InstanceName} Geodetic'
        try:
            dump_cmd(root.ExecuteCommand(cmd), obj.InstanceName)
        except Exception as e:  # noqa: BLE001
            print(f"[{obj.InstanceName}] failed: {e}")

    section("G. animation")
    for c in ("GetAnimTime *", "Animate * GetTime", "GetAnimation * CurrentTime"):
        try:
            dump_cmd(root.ExecuteCommand(c), c)
        except Exception as e:  # noqa: BLE001
            print(f"[{c}] failed: {e}")
    try:
        print("root.CurrentTime =", root.CurrentTime)
    except Exception as e:  # noqa: BLE001
        print("CurrentTime ?", e)

    print("\nPROBE V2 DONE", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
