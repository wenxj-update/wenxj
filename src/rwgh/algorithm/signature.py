"""dll 函数签名注册表。

【扩展点2】用户后续在此注册真实 .dll 的函数签名(argtypes/restype/convention)。
签名确定后,CtVisibilityAlgorithm 等即可正确调用。
"""
from __future__ import annotations

import ctypes
from dataclasses import dataclass, field
from typing import Any


@dataclass
class FuncSignature:
    """单个 dll 函数的签名描述。"""
    name: str
    argtypes: tuple = field(default_factory=tuple)   # ctypes 类型元组
    restype: Any = None                              # ctypes 类型或 None(void)
    convention: str = "cdecl"                        # "cdecl"(CDLL) | "stdcall"(WinDLL)


class SignatureRegistry:
    """函数签名注册表。"""

    def __init__(self) -> None:
        self._sigs: dict[str, FuncSignature] = {}

    def register(self, sig: FuncSignature) -> None:
        if sig.name in self._sigs:
            raise ValueError(f"duplicate function signature: {sig.name}")
        self._sigs[sig.name] = sig

    def get(self, name: str) -> FuncSignature | None:
        return self._sigs.get(name)

    def all(self) -> list[FuncSignature]:
        return list(self._sigs.values())

    def names(self) -> list[str]:
        return list(self._sigs.keys())


# ====== 真实 DLL 签名(按参考工程 RWGH_test/tool.h 接口定义)======
#   DllInit()                        初始化(调用一次)
#   DllInput(Byte* Data, int iLen)   向 DLL 输入报文(字节流+长度)
#   DllOutput(Byte* Data, int* iLen) 轮询读输出,res==0 且 iLen>0 有数据
def default_registry() -> SignatureRegistry:
    """构建含真实接口签名的注册表。"""
    reg = SignatureRegistry()
    reg.register(FuncSignature(
        name="DllInit",
        argtypes=(),
        restype=ctypes.c_int,
        convention="cdecl"))
    reg.register(FuncSignature(
        name="DllInput",
        argtypes=(ctypes.POINTER(ctypes.c_ubyte), ctypes.c_int),
        restype=ctypes.c_int,
        convention="cdecl"))
    reg.register(FuncSignature(
        name="DllOutput",
        argtypes=(ctypes.POINTER(ctypes.c_ubyte),
                  ctypes.POINTER(ctypes.c_int)),
        restype=ctypes.c_int,
        convention="cdecl"))
    return reg
