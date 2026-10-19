"""静态库(.lib) -> 动态库(.dll) 薄封装构建器。

纯静态库(.lib)无法被 ctypes 直接加载,需要链接进某个 PE 模块。本模块用
MSVC(cl.exe)生成一个只做「符号转发」的最小 DLL:把静态库中的
DllInit / DllInput / DllOutput 原样导出,之后即可用与 .dll 完全相同的方式
(ctypes.CDLL)加载,上层 DllPlanDriver / CtVisibilityAlgorithm 无需改动。

产物按「静态库路径+时间戳+附加依赖+导出符号集」做键缓存,重复加载不重复编译。

工具链定位顺序:
  1) 环境变量 RWGH_VCVARS 指定的 vcvars 脚本
  2) 当前已具备 INCLUDE/LIB + PATH 中的 cl.exe(说明已在 VS 命令行环境)
  3) vswhere.exe 查询 VS 安装路径下的 VC\\Auxiliary\\Build\\vcvars64.bat
  4) 常见安装目录扫描
"""
from __future__ import annotations

import hashlib
import logging
import os
import shutil
import subprocess
import tempfile
from typing import Iterable, Sequence

from ..core.exceptions import DllLoadError

_log = logging.getLogger("rwgh.algorithm.lib_bridge")

# 静态库中需要导出的算法接口符号(与 tool.h / alg_kd.h 一致)
BRIDGE_SYMBOLS: tuple[str, ...] = ("DllInit", "DllInput", "DllOutput")

_C_TEMPLATE = r"""/* 由 rwgh 自动生成的静态库封装(请勿手动修改)
 * 作用: 把静态库中的算法接口原样导出为 DLL 导出符号,供 ctypes 加载。
 */
extern int DllInit(void);
extern int DllInput(unsigned char *Data, int iLen);
extern int DllOutput(unsigned char *Data, int *iLen);

/* 引用这三个符号,强制链接器从静态库拉取对应目标文件 */
int rwgh_bridge_anchor(void)
{
    const volatile void *p0 = (const void *)DllInit;
    const volatile void *p1 = (const void *)DllInput;
    const volatile void *p2 = (const void *)DllOutput;
    return (p0 != 0) + (p1 != 0) + (p2 != 0);
}
"""


class StaticLibBridge:
    """静态库 -> 转发 DLL 构建器。"""

    def __init__(self, cache_dir: str | None = None,
                 vcvars: str | None = None) -> None:
        self.cache_dir = cache_dir or self._default_cache_dir()
        self._vcvars_override = vcvars

    # ------------------------------------------------------------------ 路径
    @staticmethod
    def _default_cache_dir() -> str:
        base = os.environ.get("RWGH_LIB_BRIDGE_DIR")
        if base:
            return base
        local = os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
        return os.path.join(local, "rwgh", "lib_bridge")

    # ------------------------------------------------------------- 工具链探测
    def find_toolchain(self) -> str:
        """返回可用的 vcvars 脚本路径;空串表示当前环境已可直接调用 cl.exe。"""
        if self._vcvars_override is not None:
            if self._vcvars_override and not os.path.isfile(self._vcvars_override):
                raise DllLoadError(
                    f"RWGH_VCVARS 指定的脚本不存在:{self._vcvars_override}")
            return self._vcvars_override

        env_script = os.environ.get("RWGH_VCVARS")
        if env_script:
            if not os.path.isfile(env_script):
                raise DllLoadError(f"RWGH_VCVARS 指定的脚本不存在:{env_script}")
            return env_script

        # 已在 VS 命令行环境(有 INCLUDE/LIB 且能找到 cl.exe)
        if os.environ.get("INCLUDE") and os.environ.get("LIB") \
                and shutil.which("cl"):
            return ""

        # vswhere 查询
        vswhere = os.path.join(
            os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
            "Microsoft Visual Studio", "Installer", "vswhere.exe")
        if os.path.isfile(vswhere):
            try:
                out = subprocess.run(
                    [vswhere, "-latest", "-products", "*",
                     "-requires", "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
                     "-property", "installationPath"],
                    capture_output=True, text=True, timeout=30)
                install = (out.stdout or "").strip().splitlines()
                if install:
                    cand = os.path.join(install[0].strip(), "VC", "Auxiliary",
                                        "Build", "vcvars64.bat")
                    if os.path.isfile(cand):
                        return cand
            except Exception as exc:  # noqa: BLE001
                _log.warning("vswhere 查询失败: %s", exc)

        # 常见安装目录扫描
        roots = [os.environ.get("ProgramFiles", r"C:\Program Files"),
                 os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")]
        for root in roots:
            if not root:
                continue
            vs_root = os.path.join(root, "Microsoft Visual Studio")
            if not os.path.isdir(vs_root):
                continue
            for edition in sorted(os.listdir(vs_root)):
                cand = os.path.join(vs_root, edition, "VC", "Auxiliary",
                                    "Build", "vcvars64.bat")
                if os.path.isfile(cand):
                    return cand
        return ""

    # ------------------------------------------------------------------ 缓存键
    @staticmethod
    def _cache_key(lib_path: str, deps: Sequence[str],
                   symbols: Sequence[str]) -> str:
        h = hashlib.sha256()
        h.update(os.path.abspath(lib_path).encode("utf-8", "ignore"))
        try:
            h.update(str(os.path.getmtime(lib_path)).encode())
            h.update(str(os.path.getsize(lib_path)).encode())
        except OSError:
            pass
        for d in deps:
            h.update(os.path.abspath(d).encode("utf-8", "ignore"))
            try:
                h.update(str(os.path.getmtime(d)).encode())
            except OSError:
                pass
        h.update("|".join(symbols).encode())
        stem = os.path.splitext(os.path.basename(lib_path))[0]
        safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in stem)
        return f"{safe}_{h.hexdigest()[:12]}"

    # ------------------------------------------------------------------ 构建
    def build(self, lib_path: str, deps: Iterable[str] = (),
              symbols: Sequence[str] = BRIDGE_SYMBOLS) -> str:
        """构建(或复用缓存)转发 DLL,返回其绝对路径。

        失败抛 DllLoadError,消息包含编译器输出以便定位(符号未导出/架构不符等)。
        """
        if not os.path.isfile(lib_path):
            raise DllLoadError(f"静态库不存在:{lib_path}")
        dep_list = [d for d in deps if d]
        for d in dep_list:
            if not os.path.isfile(d):
                raise DllLoadError(f"附加依赖静态库不存在:{d}")

        key = self._cache_key(lib_path, dep_list, symbols)
        out_dir = os.path.join(self.cache_dir, key)
        out_dll = os.path.join(out_dir, "rwgh_bridge.dll")
        if os.path.isfile(out_dll) and os.path.getsize(out_dll) > 0:
            _log.info("复用已构建的静态库封装: %s", out_dll)
            return out_dll

        vcvars = self.find_toolchain()
        if not vcvars and not shutil.which("cl"):
            raise DllLoadError(
                "未找到 MSVC 工具链(cl.exe),无法把静态库(.lib)封装为可加载的 "
                "DLL。请安装 Visual Studio(含 C++ 生成工具),或设置环境变量 "
                "RWGH_VCVARS 指向 vcvars64.bat,或直接提供配套的 .dll。")

        try:
            os.makedirs(out_dir, exist_ok=True)
        except OSError as exc:
            raise DllLoadError(f"无法创建封装缓存目录 {out_dir}: {exc}") from exc

        c_path = os.path.join(out_dir, "rwgh_bridge.c")
        with open(c_path, "w", encoding="utf-8") as f:
            f.write(_C_TEMPLATE)

        bat_path = os.path.join(out_dir, "build.bat")
        with open(bat_path, "w", encoding="gbk") as f:
            f.write(self._build_bat(vcvars, out_dir, lib_path, dep_list, symbols))

        _log.info("构建静态库封装: %s -> %s", lib_path, out_dll)
        try:
            proc = subprocess.run(
                ["cmd", "/c", bat_path],
                capture_output=True, text=True, timeout=600, cwd=out_dir,
                encoding="gbk", errors="replace")
        except subprocess.TimeoutExpired as exc:
            raise DllLoadError(f"静态库封装编译超时(600s):{lib_path}") from exc
        except OSError as exc:
            raise DllLoadError(f"无法执行编译脚本 {bat_path}: {exc}") from exc

        # 链接失败时 link.exe 可能留下 0 字节的同名文件,因此必须同时校验
        # 退出码与产物大小,避免把残缺文件当作构建成功。
        log_text = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
        built_ok = (proc.returncode == 0 and os.path.isfile(out_dll)
                    and os.path.getsize(out_dll) > 0)
        if not built_ok:
            try:
                os.remove(out_dll)
            except OSError:
                pass
            raise DllLoadError(
                f"静态库封装编译失败:{os.path.basename(lib_path)}\n"
                f"常见原因:静态库未导出 {('/'.join(symbols))} 符号(需 extern \"C\" "
                f"且为 C 接口)、架构与当前 Python 不一致(x64/x86)、或缺少附加依赖库。\n"
                f"编译器输出:\n{log_text[-2000:]}")

        _log.info("静态库封装构建成功: %s", out_dll)
        return out_dll

    @staticmethod
    def _build_bat(vcvars: str, out_dir: str, lib_path: str,
                   deps: Sequence[str], symbols: Sequence[str]) -> str:
        lines = ["@echo off"]
        if vcvars:
            lines.append(f'call "{vcvars}" >nul')
        lines.append(f'cd /d "{out_dir}"')
        exports = " ".join(f'/EXPORT:{s}' for s in symbols)
        inputs = " ".join(f'"{p}"' for p in [lib_path, *deps])
        lines.append(
            f'cl /nologo /LD /O2 /Fe:"rwgh_bridge.dll" '
            f'"rwgh_bridge.c" {inputs} /link {exports}')
        lines.append("exit /b %errorlevel%")
        return "\r\n".join(lines) + "\r\n"
