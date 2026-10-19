"""从 YAML 加载 FormatSpec。

YAML 结构见 config/formats/*.yaml。字段定义与 FormatSpec/FieldSpec/ChecksumSpec 对应。
"""
from __future__ import annotations

from typing import Any

import yaml

from .spec import FormatSpec, FieldSpec, ChecksumSpec
from ..core.exceptions import ConfigError


def _parse_magic(val: Any) -> bytes:
    if isinstance(val, (bytes, bytearray)):
        return bytes(val)
    if isinstance(val, int):
        n = max(1, (val.bit_length() + 7) // 8)
        return val.to_bytes(n, "big")
    if isinstance(val, str):
        s = val.strip()
        if s.lower().startswith("0x"):
            n = max(1, (int(s, 16).bit_length() + 7) // 8)
            return int(s, 16).to_bytes(n, "big")
        return s.encode("ascii")
    raise ConfigError(f"invalid magic: {val!r}")


def load_spec_from_dict(data: dict[str, Any]) -> FormatSpec:
    name = data.get("name")
    if not name:
        raise ConfigError("format spec missing 'name'")

    magic_raw = data.get("magic")
    magic = _parse_magic(magic_raw) if magic_raw is not None else None

    fields = []
    for fd in data.get("fields", []):
        enum_raw = fd.get("enum")
        enum = None
        if enum_raw is not None:
            # YAML 可写 {1: "ON", 2: "OFF"} 或 [{value: 1, name: "ON"}, ...]
            if isinstance(enum_raw, dict):
                enum = {int(k): str(v) for k, v in enum_raw.items()}
            elif isinstance(enum_raw, list):
                enum = {int(e["value"]): str(e["name"]) for e in enum_raw}
        fields.append(FieldSpec(
            name=fd["name"],
            offset=int(fd["offset"]),
            type=str(fd["type"]),
            endian=str(fd.get("endian", "<")),
            scale=float(fd.get("scale", 1.0)),
            units=str(fd.get("units", "")),
            enum=enum,
        ))

    checksum = None
    cs_raw = data.get("checksum")
    if cs_raw:
        checksum = ChecksumSpec(
            algo=str(cs_raw["algo"]),
            offset=int(cs_raw.get("offset", 0)),
            length=int(cs_raw.get("length", 0)),
            field_offset=int(cs_raw["field_offset"]),
            field_bytes=int(cs_raw.get("field_bytes", 4)),
        )

    return FormatSpec(
        name=str(name),
        total_length=int(data.get("total_length", 0)),
        magic=magic,
        magic_offset=int(data.get("magic_offset", 0)),
        fields=tuple(fields),
        checksum=checksum,
        description=str(data.get("description", "")),
    )


def load_spec_from_file(path: str) -> FormatSpec:
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ConfigError(f"invalid format yaml: {path}")
    return load_spec_from_dict(data)


def load_dir(dir_path: str, registry) -> int:
    """加载目录下所有 *.yaml 注册到 registry,返回加载数量。"""
    import os
    n = 0
    for fn in sorted(os.listdir(dir_path)):
        if not fn.lower().endswith((".yaml", ".yml")):
            continue
        spec = load_spec_from_file(os.path.join(dir_path, fn))
        registry.register(spec)
        n += 1
    return n
