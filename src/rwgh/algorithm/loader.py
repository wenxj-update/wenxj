"""算法库加载器:统一支持 .dll(动态库)与 .lib(静态库/导入库)。

三种来源 -> 统一得到可调用的 ctypes 句柄(LoadedDll):
  1) .dll                 直接 ctypes.CDLL / WinDLL
  2) .lib(导入库)         自动定位同名/带 lib 前缀的伴随 .dll,按 1) 加载
  3) .lib(纯静态库)       用 MSVC 生成转发 DLL(见 lib_bridge.py),缓存在本地,
                          再按 1) 加载

上层(DllPlanDriver / CtVisibilityAlgorithm)只通过 LoadedDll.<func>() 访问函数,
完全不感知底层来源,因此业务逻辑层无需任何改动。

LoadedDll.backend 记录实际来源,便于界面/日志显示:
  "dll"             直接加载的动态库
  "import-lib"      由导入库定位到的伴随动态库
  "static-bridge"   由静态库现场构建的转发动态库
"""
from __future__ import annotations

import ctypes
import logging
import os
from typing import Any, Iterable

from .lib_bridge import BRIDGE_SYMBOLS, StaticLibBridge
from .signature import SignatureRegistry
from ..core.exceptions import DllLoadError

_log = logging.getLogger("rwgh.algorithm.loader")

# 导入库中用于识别的导入描述符标记(MSVC 导入库特有)
_IMPORT_LIB_MARKER = b"__IMPORT_DESCRIPTOR_"


class LoadedDll:
    """已加载的库,函数属性按签名绑定。"""

    def __init__(self, handle: ctypes._CFuncPtr,  # type: ignore[name-defined]
                 registry: SignatureRegistry,
                 *, backend: str = "dll", source_path: str = "") -> None:
        self._handle = handle
        self._registry = registry
        self.backend = backend
        self.source_path = source_path

    def __getattr__(self, name: str) -> Any:
        # 取出底层函数对象
        try:
            func = getattr(self._handle, name)
        except AttributeError as e:
            raise DllLoadError(f"function not found in dll: {name}") from e
        # 按签名绑定
        sig = self._registry.get(name)
        if sig is not None:
            if sig.argtypes:
                func.argtypes = list(sig.argtypes)
            func.restype = sig.restype
        return func

    @property
    def handle(self) -> Any:
        return self._handle


def _first_convention(registry: SignatureRegistry) -> str:
    for sig in registry.all():
        return sig.convention
    return "cdecl"


def detect_lib_kind(path: str) -> str:
    """判别 .lib 是「导入库」还是「纯静态库」。

    导入库(import library,配套 .dll 使用)内嵌 MSVC 导入描述符标记;
    纯静态库不含该标记。读取失败时保守返回 "static"。
    """
    try:
        with open(path, "rb") as f:
            while True:
                chunk = f.read(1 << 20)
                if not chunk:
                    break
                if _IMPORT_LIB_MARKER in chunk:
                    return "import"
    except OSError as exc:
        _log.warning("读取 .lib 判定类型失败: %s", exc)
    return "static"


def find_companion_dll(lib_path: str) -> str | None:
    """为导入库定位伴随 .dll(同目录,同名或去掉 lib 前缀)。"""
    d = os.path.dirname(os.path.abspath(lib_path))
    stem = os.path.splitext(os.path.basename(lib_path))[0]
    names = [stem + ".dll"]
    if stem.lower().startswith("lib"):
        names.append(stem[3:] + ".dll")
    for name in names:
        cand = os.path.join(d, name)
        if os.path.isfile(cand):
            return cand
    # 目录内唯一 .dll 时兜底
    try:
        dlls = [os.path.join(d, f) for f in os.listdir(d)
                if f.lower().endswith(".dll")]
    except OSError:
        return None
    return dlls[0] if len(dlls) == 1 else None


class DllLoader:
    """动态库(.dll)加载器,按签名约定选择 CDLL / WinDLL。"""

    def load(self, path: str, registry: SignatureRegistry,
             *, backend: str = "dll") -> LoadedDll:
        if not path:
            raise DllLoadError("dll path is empty")
        if not os.path.isfile(path):
            raise DllLoadError(f"dll not found: {path}")

        conv = _first_convention(registry)
        try:
            if conv == "stdcall":
                handle = ctypes.WinDLL(path)
            else:
                handle = ctypes.CDLL(path)
        except OSError as e:
            raise DllLoadError(f"load dll failed {path}: {e}") from e

        return LoadedDll(handle, registry, backend=backend, source_path=path)


class LibraryLoader:
    """算法库统一加载器:自动适配 .dll / .lib(导入库 / 纯静态库)。"""

    def __init__(self, bridge: StaticLibBridge | None = None,
                 extra_deps: Iterable[str] = ()) -> None:
        self._dll_loader = DllLoader()
        self._bridge = bridge or StaticLibBridge()
        # 纯静态库链接时需要的附加依赖(.lib),常见于算法库拆分为多个静态库
        self._extra_deps = [d for d in extra_deps if d]

    def set_extra_deps(self, deps: Iterable[str]) -> None:
        self._extra_deps = [d for d in deps if d]

    @property
    def bridge(self) -> StaticLibBridge:
        return self._bridge

    def load(self, path: str, registry: SignatureRegistry) -> LoadedDll:
        """按文件类型自动选择加载方式。"""
        if not path:
            raise DllLoadError("算法库路径为空")
        if not os.path.isfile(path):
            raise DllLoadError(f"算法库文件不存在:{path}")

        ext = os.path.splitext(path)[1].lower()
        if ext == ".dll":
            return self._load_dll(path, registry)
        if ext == ".lib":
            return self._load_lib(path, registry)
        raise DllLoadError(
            f"不支持的算法库类型 [{ext or '无扩展名'}]:{path}(仅支持 .dll / .lib)")

    # ------------------------------------------------------------------ 分派
    def _load_dll(self, path: str, registry: SignatureRegistry) -> LoadedDll:
        dll = self._dll_loader.load(path, registry, backend="dll")
        # 立即解析必需符号,把「符号缺失」在加载阶段就暴露出来
        self._check_symbols(dll, path)
        _log.info("动态库加载成功: %s", path)
        return dll

    def _load_lib(self, path: str, registry: SignatureRegistry) -> LoadedDll:
        kind = detect_lib_kind(path)
        if kind == "import":
            companion = find_companion_dll(path)
            if companion is None:
                raise DllLoadError(
                    f"{os.path.basename(path)} 是导入库(需要配套 .dll 才能运行),"
                    f"但在同目录未找到同名/带 lib 前缀的 .dll。"
                    f"请把配套动态库放到同一目录,或直接选择 .dll 文件。")
            dll = self._dll_loader.load(companion, registry,
                                        backend="import-lib")
            self._check_symbols(dll, companion)
            _log.info("导入库 %s -> 加载伴随动态库 %s", path, companion)
            return dll

        # 纯静态库:构建转发 DLL 后加载
        bridge_dll = self._bridge.build(path, deps=self._extra_deps,
                                        symbols=BRIDGE_SYMBOLS)
        dll = self._dll_loader.load(bridge_dll, registry,
                                    backend="static-bridge")
        self._check_symbols(dll, bridge_dll)
        _log.info("静态库 %s -> 封装为 %s 并加载完成", path, bridge_dll)
        return dll

    @staticmethod
    def _check_symbols(dll: LoadedDll, path: str) -> None:
        missing = []
        for name in BRIDGE_SYMBOLS:
            try:
                getattr(dll, name)
            except DllLoadError:
                missing.append(name)
        if missing:
            raise DllLoadError(
                f"算法库缺少必需接口符号:{'、'.join(missing)}(来自 {path});"
                f"该库需导出 {'、'.join(BRIDGE_SYMBOLS)}(C 接口,extern \"C\")。")

    # -------------------------------------------------------------- 描述信息
    @staticmethod
    def backend_label(backend: str) -> str:
        """后端类型的中文说明(供界面显示)。"""
        return {
            "dll": "动态库 DLL",
            "import-lib": "导入库 .lib(已定位配套 DLL)",
            "static-bridge": "静态库 .lib(已封装为可加载 DLL)",
        }.get(backend, backend)
