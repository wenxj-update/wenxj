"""解析框架测试:用真实 STK 报文格式与数据块 hex 验证。"""
import os

import pytest

from rwgh.parsing.loader import load_dir
from rwgh.parsing.parser import FrameParser
from rwgh.parsing.registry import FormatRegistry
from rwgh.core.exceptions import ParseError
from rwgh.models.orbit import stk_seconds_to_datetime

FORMATS = os.path.join(os.path.dirname(__file__), "..", "config", "formats")

# 真实数据块(来自 xlsx 测试数据)
TIME_HEX = "0B010001000100010010213A46400000"          # 星时 2026-09-01 04:00:00
ELEM_HEX = ("A012000100010001003E213A4898291B54410000029E0000AFC2"
            "000036CE0000E8C90000BC9E"
            + "00" * 24)   # 6 个 reserved 各 4 字节


@pytest.fixture
def registry():
    reg = FormatRegistry()
    load_dir(FORMATS, reg)
    return reg


@pytest.fixture
def parser():
    return FrameParser()


def test_load_formats(registry):
    names = {s.name for s in registry.all()}
    assert "stk_time" in names
    assert "stk_orbit_data" in names
    assert "stk_orbit_elements" in names
    assert "visibility_report" in names
    t = registry.get("stk_time")
    assert t.total_length == 16
    assert t.magic == b"\x0b\x01"


def test_parse_stk_time_real(registry, parser):
    pkt = parser.parse(bytes.fromhex(TIME_HEX), registry.get("stk_time"))
    assert pkt.fields["packet_type"] == 0x0B01
    assert pkt.fields["cur_packet_len"] == 16
    assert pkt.fields["time_seconds"] == 557467200
    assert pkt.fields["time_millis"] == 0
    dt = stk_seconds_to_datetime(pkt.fields["time_seconds"],
                                 pkt.fields["time_millis"])
    assert dt.year == 2026 and dt.month == 9 and dt.day == 1
    assert dt.hour == 4


def test_parse_orbit_elements_real(registry, parser):
    pkt = parser.parse(bytes.fromhex(ELEM_HEX),
                       registry.get("stk_orbit_elements"))
    assert pkt.fields["packet_type"] == 0xA012
    assert pkt.fields["cur_packet_len"] == 62
    assert pkt.fields["epoch_seconds"] == 557467800
    assert abs(pkt.fields["semi_major_axis"] - 6896.569) < 1e-3
    assert abs(pkt.fields["eccentricity"] - 0.000670) < 1e-6
    assert abs(pkt.fields["inclination"] - 44.994) < 1e-3
    assert abs(pkt.fields["raan"] - 14.030) < 1e-3
    assert abs(pkt.fields["arg_perigee"] - 59.593) < 1e-3
    assert abs(pkt.fields["mean_anomaly"] - 48.286) < 1e-3


def test_detect_by_magic(registry, parser):
    frame = bytes.fromhex(TIME_HEX)
    spec = registry.detect(frame)
    assert spec is not None
    assert spec.name == "stk_time"


def test_wrong_length_raises(registry, parser):
    with pytest.raises(ParseError):
        parser.parse(b"\x0b\x01\x00", registry.get("stk_time"))


def test_visibility_report_roundtrip(registry, parser):
    spec = registry.get("visibility_report")
    vals = {
        "packet_type": 0x5B5B, "total_packets": 1, "sequence_no": 1,
        "cur_packet_no": 1, "cur_packet_len": spec.total_length,
        "satellite_id": 5, "target_id": 999, "aos_time": 1, "los_time": 61,
        "max_el": 47.5,
    }
    frame = parser.build(spec, vals)
    pkt = parser.parse(frame, spec)
    assert pkt.fields["satellite_id"] == 5
    assert abs(pkt.fields["max_el"] - 47.5) < 1e-3
