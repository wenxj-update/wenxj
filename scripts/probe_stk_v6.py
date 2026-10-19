# -*- coding: utf-8 -*-
"""STK12 探查 v6:确认 Planetodetic 元组取值;步进时刻 DP 查询。"""
from __future__ import annotations

import comtypes
import comtypes.client as cc

cc.GetModule(r"C:\Program Files\AGI\STK 12\bin\AgStkObjects.dll")
from comtypes.gen import STKObjects as ag

comtypes.CoInitialize()
app = cc.GetActiveObject("STK12.Application")
root = app.Personality2
sc = root.CurrentScenario
children = sc.Children

# 1) 地面点经纬度元组
for i in range(children.Count):
    obj = children.Item(i)
    cls, nm = obj.ClassName, obj.InstanceName
    if cls not in ("Facility", "Target"):
        continue
    iface = ag.IAgFacility if cls == "Facility" else ag.IAgTarget
    pos = obj.QueryInterface(iface).Position
    r = pos.QueryPlanetodetic()
    print(f"{cls:8s} {nm:10s} planetodetic -> type={type(r).__name__} "
          f"len={len(r) if hasattr(r, '__len__') else '?'} value={r!r}")
    if hasattr(r, "__len__") and len(r) >= 3:
        lat, lon, alt = float(r[0]), float(r[1]), float(r[2])
        print(f"         lat={lat:.6f} lon={lon:.6f} alt={alt:.3f} "
              f"(units likely rad/rad/m or deg/deg/m)")
        break

# 2) 直接对全部 9 个点取值,确认单位(喀什经纬度约 75.9E/39.5N)
print("\nall ground objects:")
for i in range(children.Count):
    obj = children.Item(i)
    cls, nm = obj.ClassName, obj.InstanceName
    if cls not in ("Facility", "Target"):
        continue
    iface = ag.IAgFacility if cls == "Facility" else ag.IAgTarget
    r = obj.QueryInterface(iface).Position.QueryPlanetodetic()
    print(f"  {nm:10s} {float(r[0]):.8f} {float(r[1]):.8f} {float(r[2]):.3f}")

# 3) 步进时刻(场景开始 +120s)查询卫星状态
sat = children.Item("Satellite1")
dpp = sat.DataProviders
t = "1 Oct 2026 02:02:00.000"
for path in ("Cartesian Position/ICRF", "Cartesian Velocity/ICRF",
             "Cartesian Position/Fixed", "Cartesian Velocity/Fixed"):
    dp = dpp.GetDataPrvTimeVarFromPath(path)
    res = dp.Exec(t, t, 60.0)
    vals = {ds.ElementName: list(ds.GetValues()) for ds in res.DataSets}
    print(path, "->", {k: v[:1] for k, v in vals.items() if k != "Time"})
