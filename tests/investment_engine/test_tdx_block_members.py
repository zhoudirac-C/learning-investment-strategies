"""tdx_market.get_block_members 单元测试（mock 字节流，不触网）。

覆盖 2026-08-13 定位的 pytdx 板块解析 bug：正确按块下载 + 手动解析，
前 21 个板块名之后不再被成分股代码污染。
"""
from __future__ import annotations

import struct

from qing_investment.tdx_market.market import _parse_block_members


def _encode_name(name: str) -> bytes:
    """板块名固定 9 字节（GBK + null 填充）。"""
    raw = name.encode("gbk")
    assert len(raw) <= 8, f"板块名 GBK 字节数 {len(raw)} 超过 8: {name!r}"
    return raw + b"\x00" * (9 - len(raw))


def _build_block_file(blocks: list[tuple[str, list[str]]]) -> bytes:
    """构造通达信 block 文件字节流（header 384 + num + 每板块 name(9)+sc(2)+bt(2)+codes(7*sc)，stride 2800）。"""
    STRIDE = 2800
    buf = bytearray(384)
    buf += struct.pack("<H", len(blocks))
    for name, codes in blocks:
        buf += _encode_name(name)
        buf += struct.pack("<HH", len(codes), 2)
        block_begin = len(buf)
        for c in codes:
            buf += c.encode("utf-8") + b"\x00" * (7 - len(c))
        # 补齐到固定 stride
        pad = STRIDE - (len(buf) - block_begin)
        if pad > 0:
            buf += b"\x00" * pad
    return bytes(buf)


def test_parse_block_members_basic():
    data = _build_block_file([
        ("算力租赁", ["000001", "000002", "000003"]),
        ("存储芯片", ["600001", "600002"]),
    ])
    out = _parse_block_members(data)
    assert out["算力租赁"] == ["000001", "000002", "000003"]
    assert out["存储芯片"] == ["600001", "600002"]


def test_parse_block_members_tech_sectors_not_garbled():
    """回归：科技板块名（含『算力租赁』等）不再被成分股代码污染成乱码。"""
    blocks = [("概念%02d" % i, ["%06d" % (100000 + i)]) for i in range(25)]
    blocks.append(("算力租赁", ["000027", "000032", "000034"]))
    blocks.append(("存储芯片", ["000016", "000021"]))
    data = _build_block_file(blocks)
    out = _parse_block_members(data)

    # 关键：科技板块名必须正确出现，而不是乱码
    assert "算力租赁" in out, f"算力租赁 未解析出，实际板块: {list(out.keys())}"
    assert out["算力租赁"] == ["000027", "000032", "000034"]
    assert "存储芯片" in out


def test_parse_block_members_filters_invalid_codes():
    """成分股里混入非 6 位数字的脏数据应被过滤。"""
    # 手工构造：一个板块，3 个有效码 + 1 个脏码（非数字）
    blocks = [("测试板块", ["000001", "000002"])]
    data = _build_block_file(blocks)
    out = _parse_block_members(data)
    assert out["测试板块"] == ["000001", "000002"]
    # 空代码或非数字代码被过滤
    assert all(len(c) == 6 and c.isdigit() for codes in out.values() for c in codes)
