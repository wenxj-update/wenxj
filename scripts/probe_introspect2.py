# -*- coding: utf-8 -*-
"""内省接口成员:DataProviders/CurrentTime 到底在哪个接口。"""
from __future__ import annotations

import os
import comtypes
import comtypes.client as cc

cc.GetModule(r"C:\Program Files\AGI\STK 12\bin\AgStkObjects.dll")
from comtypes.gen import STKObjects as ag

mod_file = ag.__file__
print("module file:", mod_file, "size:", os.path.getsize(mod_file))

print("_IAgStkObjectRoot has CurrentTime?",
      hasattr(ag._IAgStkObjectRoot, "CurrentTime"))
print("IAgStkObjectRoot has CurrentTime?",
      hasattr(ag.IAgStkObjectRoot, "CurrentTime"))
print("IAgSatellite has DataProviders?",
      hasattr(ag.IAgSatellite, "DataProviders"))
print("IAgSatellite methods sample:",
      [m for m in dir(ag.IAgSatellite) if not m.startswith("_")][:20])
print("IAgStkObject has GetInterface?",
      hasattr(ag.IAgStkObject, "GetInterface"))
print("IAgStkObject methods sample:",
      [m for m in dir(ag.IAgStkObject) if not m.startswith("_")][:30])

# 在整个模块里找谁声明了 DataProviders / CurrentTime
for attr in ("DataProviders", "CurrentTime"):
    owners = [n for n in dir(ag)
              if not n.startswith("_") and hasattr(getattr(ag, n), attr)]
    print(f"owners of {attr}: {owners[:10]}")

try:
    comtypes.CoInitialize()
except Exception:  # noqa: BLE001
    pass
app = cc.GetActiveObject("STK12.Application")
root = app.Personality2
print("root(_IAgStkObjectRoot) CurrentTime?", hasattr(root, "CurrentTime"))
sc = root.CurrentScenario
sat_obj = sc.Children.Item("Satellite1")
print("sat_obj methods with Data/Provider/Interface:",
      [m for m in dir(sat_obj) if "Data" in m or "Provider" in m
       or "Interface" in m][:20])
# GetInterface 尝试
for iname in ("IAgSatellite", "Satellite"):
    try:
        si = sat_obj.GetInterface(iname)
        print(f"GetInterface({iname}) -> {type(si)}, DataProviders?",
              hasattr(si, "DataProviders"))
        if hasattr(si, "DataProviders"):
            dpp = si.DataProviders
            print("dpp type:", type(dpp))
            break
    except Exception as e:  # noqa: BLE001
        print(f"GetInterface({iname}) failed: {e}")
