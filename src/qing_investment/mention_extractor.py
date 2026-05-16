from __future__ import annotations

import re
from dataclasses import dataclass

KNOWN_STOCK_NAMES = {
    "中际旭创",
    "中国长城",
    "寒武纪",
    "海光信息",
    "兆易创新",
    "江波龙",
    "新易盛",
    "天孚通信",
    "网宿科技",
}

KNOWN_SECTORS = {"国产算力", "CPO", "AI", "存储", "半导体", "电力", "商业航天", "机器人"}
STOCK_CODE_RE = re.compile(r"(?<!\d)(?:[0368]\d{5})(?!\d)")


@dataclass(frozen=True)
class Mentions:
    stock_codes: list[str]
    stock_names: list[str]
    sectors: list[str]


def extract_mentions(text: str) -> Mentions:
    codes = sorted(set(STOCK_CODE_RE.findall(text)))
    stock_names = sorted(name for name in KNOWN_STOCK_NAMES if name in text)
    sectors = sorted(sector for sector in KNOWN_SECTORS if sector in text)
    return Mentions(stock_codes=codes, stock_names=stock_names, sectors=sectors)
