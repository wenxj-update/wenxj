"""配置加载:从 YAML 读取并校验。"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

import yaml

from .exceptions import ConfigError


@dataclass
class FrameConfig:
    magic: bytes = b"\x5a\x5a"
    length_offset: int = 2
    length_bytes: int = 2
    length_includes: str = "body"   # "body" | "frame"
    max_frame: int = 4096
    checksum_algo: str = "crc32"
    checksum_offset: int = 0
    checksum_field: int = -1


@dataclass
class StkConfig:
    version: str = "12.2"
    progid: str = "STK12.Application"
    visible: bool = False
    install_dir: str = ""
    tlb_path: str = ""
    scenario_path: str = ""        # .sc 场景文件完整路径
    step_seconds: float = 60.0     # 每个节拍推进的仿真秒数
    tick_ms: int = 1000            # 节拍间隔(墙钟毫秒)
    connect_push_cmds: list = field(default_factory=lambda: ["Connect {host} {port}"])


@dataclass
class TransportConfig:
    host: str = "127.0.0.1"
    port: int = 8001
    frame: FrameConfig = field(default_factory=FrameConfig)


@dataclass
class AlgorithmConfig:
    visibility_dll: str = ""     # 可见性算法库路径(.dll 或 .lib)
    datalink_dll: str = ""
    # 纯静态库(.lib)链接时需要的附加依赖库,分号分隔(可选)
    lib_extra_deps: str = ""


@dataclass
class AppConfig:
    stk: StkConfig = field(default_factory=StkConfig)
    transport: TransportConfig = field(default_factory=TransportConfig)
    algorithm: AlgorithmConfig = field(default_factory=AlgorithmConfig)
    mode: str = "mock"   # "real" | "mock"
    command_template: str = ""   # 指令模板 xlsm 路径(空则仅用 stub)
    packet_format_xlsx: str = ""  # 数据包格式定义 xlsx 路径
    logging: dict[str, Any] = field(default_factory=dict)


def _parse_magic(val: Any) -> bytes:
    if isinstance(val, (bytes, bytearray)):
        return bytes(val)
    if isinstance(val, int):
        # 0x5A5A -> 2 bytes big-endian
        n = max(1, (val.bit_length() + 7) // 8)
        return val.to_bytes(n, "big")
    if isinstance(val, str):
        s = val.strip()
        if s.lower().startswith("0x"):
            return int(s, 16).to_bytes(2, "big")
        return s.encode("ascii")
    raise ConfigError(f"invalid magic value: {val!r}")


def load_config(path: str) -> AppConfig:
    if not os.path.isfile(path):
        raise ConfigError(f"config file not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    stk_raw = raw.get("stk", {})
    tr_raw = raw.get("transport", {})
    fr_raw = tr_raw.get("frame", {})
    algo_raw = raw.get("algorithm", {})

    frame = FrameConfig(
        magic=_parse_magic(fr_raw.get("magic", "0x5A5A")),
        length_offset=int(fr_raw.get("length_offset", 2)),
        length_bytes=int(fr_raw.get("length_bytes", 2)),
        length_includes=str(fr_raw.get("length_includes", "body")),
        max_frame=int(fr_raw.get("max_frame", 4096)),
        checksum_algo=str(fr_raw.get("checksum_algo", "crc32")),
        checksum_offset=int(fr_raw.get("checksum_offset", 0)),
        checksum_field=int(fr_raw.get("checksum_field", -1)),
    )

    cfg = AppConfig(
        stk=StkConfig(
            version=str(stk_raw.get("version", "12.2")),
            progid=str(stk_raw.get("progid", "STK12.Application")),
            visible=bool(stk_raw.get("visible", False)),
            install_dir=str(stk_raw.get("install_dir", "")),
            tlb_path=str(stk_raw.get("tlb_path", "")),
            scenario_path=str(stk_raw.get("scenario_path", "")),
            step_seconds=float(stk_raw.get("step_seconds", 60.0)),
            tick_ms=int(stk_raw.get("tick_ms", 1000)),
            connect_push_cmds=list(stk_raw.get("connect_push_cmds",
                                            ["Connect {host} {port}"])),
        ),
        transport=TransportConfig(
            host=str(tr_raw.get("host", "127.0.0.1")),
            port=int(tr_raw.get("port", 8001)),
            frame=frame,
        ),
        algorithm=AlgorithmConfig(
            visibility_dll=str(algo_raw.get("visibility_dll", "")),
            datalink_dll=str(algo_raw.get("datalink_dll", "")),
            lib_extra_deps=str(algo_raw.get("lib_extra_deps", "")),
        ),
        mode=str(raw.get("mode", "mock")),
        command_template=str(raw.get("command_template", "")),
        packet_format_xlsx=str(raw.get("packet_format_xlsx", "")),
        logging=dict(raw.get("logging", {})),
    )
    return cfg


def save_config(cfg: AppConfig, path: str) -> None:
    """将配置写回 YAML 文件(持久化 DLL/模板等路径)。"""
    data = {
        "stk": {
            "version": cfg.stk.version,
            "progid": cfg.stk.progid,
            "visible": cfg.stk.visible,
            "install_dir": cfg.stk.install_dir,
            "tlb_path": cfg.stk.tlb_path,
            "scenario_path": cfg.stk.scenario_path,
            "step_seconds": cfg.stk.step_seconds,
            "tick_ms": cfg.stk.tick_ms,
            "connect_push_cmds": cfg.stk.connect_push_cmds,
        },
        "transport": {
            "host": cfg.transport.host,
            "port": cfg.transport.port,
            "frame": {
                "magic": "0x" + cfg.transport.frame.magic.hex().upper()
                         if cfg.transport.frame.magic else "0x5A5A",
                "length_offset": cfg.transport.frame.length_offset,
                "length_bytes": cfg.transport.frame.length_bytes,
                "length_includes": cfg.transport.frame.length_includes,
                "max_frame": cfg.transport.frame.max_frame,
                "checksum_algo": cfg.transport.frame.checksum_algo,
                "checksum_offset": cfg.transport.frame.checksum_offset,
                "checksum_field": cfg.transport.frame.checksum_field,
            },
        },
        "algorithm": {
            "visibility_dll": cfg.algorithm.visibility_dll,
            "datalink_dll": cfg.algorithm.datalink_dll,
            "lib_extra_deps": cfg.algorithm.lib_extra_deps,
        },
        "command_template": cfg.command_template,
        "packet_format_xlsx": cfg.packet_format_xlsx,
        "logging": cfg.logging,
        "mode": cfg.mode,
    }
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False,
                  sort_keys=False)
