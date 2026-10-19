"""异常基类层次。"""
from __future__ import annotations


class RwghError(Exception):
    """所有框架异常的基类。"""


class ConfigError(RwghError):
    """配置加载/校验错误。"""


class ParseError(RwghError):
    """报文解析错误(格式不匹配、校验失败、字段越界等)。"""


class FramerError(RwghError):
    """组帧/拆帧错误。"""


class DllLoadError(RwghError):
    """dll 加载或函数绑定错误。"""


class StkError(RwghError):
    """STK COM 调用错误。"""


class TransportError(RwghError):
    """传输层错误。"""
