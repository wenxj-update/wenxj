# -*- coding: utf-8 -*-
"""STK12 探查 v4:原始对象直取 DataProviders;卫星 DP/目标设施坐标/时间设置。"""
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
        out = []
        for ds in sets:
            name = getattr(ds, "ElementName", "?")
            try:
                vals = list(ds.GetValues())
            except Exception as e:  # noqa: BLE001
                vals = [f"<{e}>"]
            print(f"  - {name}: {vals[:max_rows]}")
            out.append((name, vals))
        return out
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        return []


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
    root = app.Personality2            # POINTER(_IAgStkObjectRoot),全成员
    sc = root.CurrentScenario          # POINTER(IAgStkObject),全成员
    print("scenario:", sc.InstanceName, "| root.CurrentTime =", root.CurrentTime)

    children = sc.Children
    sat = children.Item("Satellite1")
    dpp = sat.DataProviders

    section("A. DP top-level names")
    try:
        for c in list(dpp)[:60]:
            print("  -", c.Name)
    except Exception:  # noqa: BLE001
        traceback.print_exc()

    t0 = "1 Oct 2026 02:00:00.000"

    section("B. Cartesian Position/Velocity + Classical Elements")
    for path, pre in (("Cartesian Position", "ICRF"),
                      ("Cartesian Velocity", "ICRF"),
                      ("Classical Elements", "J2000")):
        try:
            dp = dpp.GetDataPrvTimeVarFromPath(path)
            try:
                print(f"  {path} PreDataList =", list(dp.PreDataList))
            except Exception:  # noqa: BLE001
                pass
            if pre:
                dp.PreData = pre
            dump_dp(dp.Exec(t0, t0, 60.0), f"{path}/{pre}")
        except Exception as e:  # noqa: BLE001
            print(f"[DP {path}/{pre}] failed: {e}")

    section("C. set CurrentTime and query at that time")
    try:
        root.CurrentTime = t0
        print("after set, CurrentTime =", root.CurrentTime)
    except Exception as e:  # noqa: BLE001
        print("set CurrentTime failed:", e)

    section("D. ground objects: generic-object DP Center + IAgTarget/IAgFacility")
    for i in range(children.Count):
        obj = children.Item(i)
        cls, nm = obj.ClassName, obj.InstanceName
        if cls not in ("Target", "Facility"):
            continue
        print(f"-- {cls} {nm}")
        # 方式1:Center DP
        try:
            dp = obj.DataProviders.GetDataPrvFixedFromPath("Center")
            try:
                print("   Center PreDataList =", list(dp.PreDataList))
            except Exception:  # noqa: BLE001
                pass
            for pre in ("Geodetic", "Earth Fixed", "MSL"):
                try:
                    dp.PreData = pre
                    dump_dp(dp.Exec(), f"{nm}/Center/{pre}")
                except Exception as e:  # noqa: BLE001
                    print(f"   Center/{pre} failed: {e}")
        except Exception as e:  # noqa: BLE001
            print("   Center DP failed:", e)
        # 方式2:专用接口
        if i < 999:
            iface = ag.IAgTarget if cls == "Target" else ag.IAgFacility
            try:
                sp = obj.QueryInterface(iface)
                pos = sp.Position
                pms = [m for m in dir(pos) if not m.startswith("_")]
                print("   pos members:", pms)
                for a in ("GeodeticLatitude", "Latitude", "Longitude",
                          "Altitude", "HeightAboveGround", "HeightAboveEllipsoid"):
                    if hasattr(pos, a):
                        try:
                            print(f"    {a} =", getattr(pos, a))
                        except Exception as e:  # noqa: BLE001
                            print(f"    {a} ? {e}")
            except Exception as e:  # noqa: BLE001
                print(f"   QI {iface} failed: {e}")

    print("\nPROBE V4 DONE", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
