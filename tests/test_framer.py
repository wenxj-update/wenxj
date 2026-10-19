"""组帧状态机测试:多 magic 同步、粘包/拆包。"""
import os

import pytest

from rwgh.parsing.parser import FrameParser
from rwgh.parsing.registry import FormatRegistry
from rwgh.parsing.loader import load_dir
from rwgh.core.config import FrameConfig
from rwgh.transport.framer import Framer

FORMATS = os.path.join(os.path.dirname(__file__), "..", "config", "formats")

# 真实数据块
TIME_HEX = "0B010001000100010010213A46400000"
ELEM_HEX = ("A012000100010001003E213A4898291B54410000029E0000AFC2"
            "000036CE0000E8C90000BC9E" + "00" * 24)


@pytest.fixture
def stk_specs():
    reg = FormatRegistry()
    load_dir(FORMATS, reg)
    return reg


@pytest.fixture
def frame_cfg():
    return FrameConfig(magic=b"\x0b\x01", length_offset=8, length_bytes=2,
                      length_includes="frame", max_frame=4096,
                      checksum_algo="crc32")


def test_single_frame(stk_specs, frame_cfg):
    magic_list = [s.magic for s in stk_specs.all() if s.magic]
    fr = Framer(frame_cfg, magic_list=magic_list)
    f = bytes.fromhex(TIME_HEX)
    out = list(fr.feed(f))
    assert out == [f]


def test_two_frames_one_chunk(stk_specs, frame_cfg):
    magic_list = [s.magic for s in stk_specs.all() if s.magic]
    fr = Framer(frame_cfg, magic_list=magic_list)
    f1 = bytes.fromhex(TIME_HEX)
    f2 = bytes.fromhex(ELEM_HEX)
    out = list(fr.feed(f1 + f2))
    assert out == [f1, f2]


def test_split_across_chunks(stk_specs, frame_cfg):
    magic_list = [s.magic for s in stk_specs.all() if s.magic]
    fr = Framer(frame_cfg, magic_list=magic_list)
    f = bytes.fromhex(TIME_HEX)
    half = len(f) // 2
    out = list(fr.feed(f[:half])) + list(fr.feed(f[half:]))
    assert out == [f]


def test_garbage_before_magic_resync(stk_specs, frame_cfg):
    magic_list = [s.magic for s in stk_specs.all() if s.magic]
    fr = Framer(frame_cfg, magic_list=magic_list)
    f = bytes.fromhex(TIME_HEX)
    out = list(fr.feed(b"\x00\x01\x02" + f))
    assert out == [f]


def test_partial_magic_across_chunks(stk_specs, frame_cfg):
    magic_list = [s.magic for s in stk_specs.all() if s.magic]
    fr = Framer(frame_cfg, magic_list=magic_list)
    f = bytes.fromhex(TIME_HEX)
    out = list(fr.feed(f[:1])) + list(fr.feed(f[1:]))
    assert out == [f]
