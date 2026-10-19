# -*- coding: utf-8 -*-
"""STK12 探查 v5:组路径 DP(名称/坐标系)、CurrentTime 浮点语义、地面点 Planetodetic。"""
from __future__ import annotations

import sys
import traceback

PROGID = "STK12.Application"
t0 = "1 Oct 2026 02:00:00.000"


def section(t):
    print("\n" + "=" * 15 + " " + t + " " + "=" * 15, flush=True)


def dump_dp(result, label):
    print(f"[{label}]")
    try:
        for ds in list(result.DataSets):
            name = getattr(ds, "ElementName", "?")
            try:
                vals = list(ds.GetValues())
            except Exception as e:  # noqa: BLE001
                vals = [f"<{e}>"]
            print(f"  - {name}: {vals[:3]}")
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
    sc = root.CurrentScenario
    children = sc.Children
    sat = children.Item("Satellite1")
    dpp = sat.DataProviders

    section("A. grouped DP paths")
    for path in ("Cartesian Position/ICRF", "Cartesian Velocity/ICRF",
                 "Cartesian Position/Fixed", "Classical Elements/J2000"):
        try:
            dp = dpp.GetDataPrvTimeVarFromPath(path)
            dump_dp(dp.Exec(t0, t0, 60.0), path)
        except Exception as e:  # noqa: BLE001
            print(f"[{path}] failed: {e}")

    section("B. CurrentTime float semantics")
    try:
        print("before:", root.CurrentTime)
        root.CurrentTime = 0.0
        print("set 0.0 ->", root.CurrentTime)
        root.CurrentTime = 60.0
        print("set 60.0 ->", root.CurrentTime)
    except Exception:  # noqa: BLE001
        traceback.print_exc()

    section("C. ground Position Query methods (kashi_01 + target 11-100)")
    for cls, nm in (("Facility", "kashi_01"), ("Target", "11-100")):
        obj = children.Item(nm)
        iface = ag.IAgFacility if cls == "Facility" else ag.IAgTarget
        pos = obj.QueryInterface(iface).Position
        print(f"-- {nm} PosType =", end=" ")
        try:
            print(pos.PosType)
        except Exception as e:  # noqa: BLE001
            print("?", e)
        for meth in ("QueryPlanetodetic", "QueryCartesian",
                     "QueryGeodetic", "QueryPlanetocentric"):
            try:
                r = getattr(pos, meth)()
                members = [m for m in dir(r) if not m.startswith("_")]
                print(f"  {meth}() members: {members}")
                for a in ("Latitude", "Longitude", "Altitude", "X", "Y", "Z",
                          "Radial", "Azimuth", "Elevation"):
                    if hasattr(r, a):
                        try:
                            print("    ", a, "=", getattr(r, a))
                        except Exception:  # noqa: BLE001
                            pass
            except Exception as e:  # noqa: BLE001
                print(f"  {meth}() failed: {e}")

    section("D. facility DP names (geodetic backup path)")
    fac = children.Item("kashi_01")
    try:
        names = [c.Name for c in list(fac.DataProviders)]
        geo = [n for n in names if "pos" in n.lower() or "coord" in n.lower()
               or "center" in n.lower() or "geod" in n.lower() or "lat" in n.lower()]
        print("position-related DPs:", geo)
    except Exception:  # noqa: BLE001
        traceback.print_exc()

    print("\nPROBE V5 DONE", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
