# -*- coding: utf-8 -*-
"""STK12 探查 v3:QI 正确接口,DP 取卫星状态/根数,目标/设施经纬度,root.CurrentTime。"""
from __future__ import annotations

import sys
import traceback

PROGID = "STK12.Application"


def section(t):
    print("\n" + "=" * 15 + " " + t + " " + "=" * 15, flush=True)


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


def try_dp(dpp, path, predata, t0, t1, dt=60.0):
    tag = f"{path} / {predata}" if predata else path
    try:
        dp = dpp.GetDataPrvTimeVarFromPath(path)
        if predata:
            dp.PreData = predata
        dump_dp(dp.Exec(t0, t1, dt), tag)
    except Exception as e:  # noqa: BLE001
        print(f"[DP {tag}] failed: {e}")


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
    root = app.Personality2.QueryInterface(ag.IAgStkObjectRoot)
    sc_obj = root.CurrentScenario
    sc = sc_obj.QueryInterface(ag.IAgScenario)
    t_start, t_stop = sc.StartTime, sc.StopTime
    print("scenario =", sc_obj.InstanceName, t_start, "->", t_stop)

    section("A. root.CurrentTime")
    try:
        print("CurrentTime =", root.CurrentTime)
    except Exception as e:  # noqa: BLE001
        print("CurrentTime ?", e)

    section("B. satellite DPs")
    children = sc_obj.Children
    sat = children.Item("Satellite1").QueryInterface(ag.IAgSatellite)
    dpp = sat.DataProviders
    # 先列可用 DP 名(目录)
    try:
        cats = list(dpp)
        print("DP categories:", [getattr(c, "Name", "?") for c in cats][:40])
    except Exception:  # noqa: BLE001
        pass
    for path, pre in (("Cartesian Position", "ICRF"),
                      ("Cartesian Position", "Fixed"),
                      ("Cartesian Velocity", "ICRF"),
                      ("Classical Elements", "J2000")):
        try_dp(dpp, path, pre, t_start, t_start)

    section("C. set CurrentTime then query")
    try:
        root.CurrentTime = t_start
        # DP 单点查询用 ExecSingle?TimeVar DP Exec(t,t,dt) 即可
        try_dp(dpp, "Cartesian Position", "ICRF", t_start, t_start)
    except Exception:  # noqa: BLE001
        traceback.print_exc()

    section("D. targets (IAgTarget position introspection)")
    for i in range(children.Count):
        obj = children.Item(i)
        cls, nm = obj.ClassName, obj.InstanceName
        if cls == "Target":
            tgt = obj.QueryInterface(ag.IAgTarget)
            pos = tgt.Position
            members = [m for m in dir(pos) if not m.startswith("_")][:30]
            print(f"Target {nm}: pos members = {members}")
            for meth in ("GetGeodetic", "GetCartesian"):
                try:
                    r = getattr(pos, meth)()
                    print(f"  .{meth}() ->", r)
                    for a in ("Latitude", "Longitude", "Altitude", "X", "Y", "Z"):
                        try:
                            print("    ", a, "=", getattr(r, a))
                        except Exception:  # noqa: BLE001
                            pass
                    break
                except Exception as e:  # noqa: BLE001
                    print(f"  .{meth}() ? {e}")
            break  # 一个 Target 足够确认接口

    section("E. facilities (IAgFacility position)")
    fac = children.Item("kashi_01").QueryInterface(ag.IAgFacility)
    fpos = fac.Position
    members = [m for m in dir(fpos) if not m.startswith("_")]
    print("facility pos members =", members)
    for a in ("GeodeticLatitude", "Longitude", "Altitude", "HeightAboveGround",
              "Latitude"):
        try:
            print("  ", a, "=", getattr(fpos, a))
        except Exception as e:  # noqa: BLE001
            print(f"   {a} ? {e}")

    section("F. all ground objects via DP 'Center'")
    for i in range(children.Count):
        obj = children.Item(i)
        if obj.ClassName not in ("Target", "Facility"):
            continue
        try:
            if obj.ClassName == "Target":
                dpp2 = obj.QueryInterface(ag.IAgTarget).DataProviders
            else:
                dpp2 = obj.QueryInterface(ag.IAgFacility).DataProviders
            try:
                dp = dpp2.GetDataPrvFixedFromPath("Center")
                print(f"{obj.InstanceName}: Center PreDataList =",
                      list(getattr(dp, "PreDataList", [])))
                for pre in ("Geodetic", "Earth Fixed"):
                    try:
                        dp.PreData = pre
                        r = dp.Exec()
                        dump_dp(r, f"{obj.InstanceName}/Center/{pre}")
                    except Exception as e:  # noqa: BLE001
                        print(f"  {pre} failed: {e}")
            except Exception as e:  # noqa: BLE001
                print(f"{obj.InstanceName} Center DP ? {e}")
        except Exception:  # noqa: BLE001
            traceback.print_exc()
        break  # 先验证一个

    print("\nPROBE V3 DONE", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
