# -*- coding: utf-8 -*-
"""内省 comtypes 生成模块中的接口名与 QI 返回对象真实类型。"""
from __future__ import annotations

import comtypes
import comtypes.client as cc

cc.GetModule(r"C:\Program Files\AGI\STK 12\bin\AgStkObjects.dll")
from comtypes.gen import STKObjects as ag

names_root = [n for n in dir(ag) if "StkObjectRoot" in n]
names_sat = [n for n in dir(ag) if n.startswith("IAgSatellite")]
names_sc = [n for n in dir(ag) if n.startswith("IAgScenario")]
print("root interfaces:", names_root)
print("sat interfaces:", names_sat)
print("sc interfaces:", names_sc)

try:
    comtypes.CoInitialize()
except Exception:  # noqa: BLE001
    pass
app = cc.GetActiveObject("STK12.Application")
p2 = app.Personality2
print("Personality2 type:", type(p2))

# 尝试不同 QI
for iname in names_root:
    iface = getattr(ag, iname)
    try:
        q = p2.QueryInterface(iface)
        print(f"QI {iname} -> {type(q)}")
        for a in ("CurrentTime", "ExecuteCommand", "CurrentScenario"):
            print("   has", a, ":", hasattr(q, a))
        break
    except Exception as e:  # noqa: BLE001
        print(f"QI {iname} failed: {e}")

sc = p2.CurrentScenario
sat_obj = sc.Children.Item("Satellite1")
print("sat raw type:", type(sat_obj))
for iname in names_sat:
    iface = getattr(ag, iname)
    try:
        q = sat_obj.QueryInterface(iface)
        print(f"QI {iname} -> {type(q)}; DataProviders?", hasattr(q, "DataProviders"))
    except Exception as e:  # noqa: BLE001
        print(f"QI {iname} failed: {e}")
