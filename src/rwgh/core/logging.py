"""日志初始化。"""
from __future__ import annotations

import ctypes
import io
import logging
import os
import sys
from typing import Any


def _setup_console_cp() -> None:
    """设置 Windows 控制台代码页为 UTF-8,让 DLL 的 printf 中文输出不乱码。

    DLL 内部用 printf 直接写 C 层 stdout,绕过 Python 的 sys.stdout。
    需通过 Win32 API SetConsoleOutputCP(65001) 把控制台输出代码页
    设为 UTF-8,DLL 输出的 UTF-8 中文字节才能被正确显示。
    """
    if os.name != "nt":
        return
    try:
        k32 = ctypes.windll.kernel32
        # 65001 = CP_UTF8
        k32.SetConsoleOutputCP(65001)
        k32.SetConsoleCP(65001)
    except Exception:  # noqa: BLE001
        pass


def _make_utf8_stream():
    """返回一个 UTF-8 编码的输出流,避免 Windows 控制台中文乱码。"""
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        return sys.stdout
    except Exception:  # noqa: BLE001
        # Python 3.6/3.7 无 reconfigure,回退为包装 UTF-8 流
        return io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                errors="replace", line_buffering=True)


def setup_logging(cfg: dict[str, Any] | None = None) -> logging.Logger:
    cfg = cfg or {}
    level = logging.getLevelName(str(cfg.get("level", "INFO")).upper())
    log_file = cfg.get("file", "logs/rwgh.log")

    if log_file:
        os.makedirs(os.path.dirname(log_file) or ".", exist_ok=True)

    # 先设置控制台代码页,再配置 Python stdout,确保 DLL 和 Python
    # 的中文输出都不乱码
    _setup_console_cp()

    root = logging.getLogger("rwgh")
    root.setLevel(level)
    root.handlers.clear()

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )

    sh = logging.StreamHandler(_make_utf8_stream())
    sh.setFormatter(fmt)
    root.addHandler(sh)

    if log_file:
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setFormatter(fmt)
        root.addHandler(fh)

    return root
