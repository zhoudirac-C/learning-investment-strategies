"""雪球大牛回测 P4/P5 纯函数测试：窗口过滤 / 提及提取 / 关键词匹配 / 评分。

设计：docs/design/xueqiu-expert-backtest-design.md §4.4（2026-09-24 拍板 B/B/A）
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "xueqiu_expert"))

import pytest

from verdict_pipeline import (
    build_event_index,
    extract_stock_mentions,
    find_window_hits,
    is_original,
    keyword_hit_sectors,
    parse_llm_json,
    parse_post_date,
    score_expert,
    stock_to_sectors,
)

# ---------- parse_post_date ----------


def test_parse_post_date_from_ms():
    # 2025-06-01 00:00:00 UTC+8 = 1748707200000 ms
    ms = int(date(2025, 6, 1).strftime("%s")) * 1000
    assert parse_post_date(ms) == date(2025, 6, 1)


def test_parse_post_date_from_str():
    assert parse_post_date("2025-06-01") == date(2025, 6, 1)
    assert parse_post_date("2025-06-01 12:30:00") == date(2025, 6, 1)


def test_parse_post_date_invalid():
    assert parse_post_date(None) is None
    assert parse_post_date("") is None
    assert parse_post_date("not-a-date") is None


# ---------- is_original ----------


def test_is_original():
    assert is_original({"retweet": False, "description": "看多算力"}) is True
    assert is_original({"retweet": True, "description": ""}) is False
    # P3 实测：回复帖无 retweet 标记但 description 以"回复"开头
    assert is_original({"retweet": False, "description": "回复<a href=\"x\">@某人</a>: 同意"}) is False


# ---------- build_event_index / find_window_hits ----------


@pytest.fixture
def event_index():
    events = [
        {"sector": "存储芯片", "code": "301", "kind": "concept",
         "launch_date": "2025-06-10", "max_gain_20d": 25.0},
        {"sector": "存储芯片", "code": "301", "kind": "concept",
         "launch_date": "2025-09-01", "max_gain_20d": 30.0},
        {"sector": "创新药", "code": "302", "kind": "concept",
         "launch_date": "2025-06-01", "max_gain_20d": 22.0},
    ]
    return build_event_index(events)


def test_find_window_hit_strong(event_index):
    # 提前 7~21 天 + 对应板块 → 强命中
    hits = find_window_hits(event_index, "存储芯片", date(2025, 6, 2))
    assert len(hits) == 1
    assert hits[0]["lead_days"] == 8
    assert hits[0]["tier"] == "strong"


def test_find_window_hit_mid(event_index):
    # 提前 3~6 天 → 中命中
    hits = find_window_hits(event_index, "存储芯片", date(2025, 6, 7))
    assert hits[0]["tier"] == "mid"


def test_find_window_outside(event_index):
    # 窗口外：太早 / 太晚 / 板块无事件
    assert find_window_hits(event_index, "存储芯片", date(2025, 5, 1)) == []
    assert find_window_hits(event_index, "存储芯片", date(2025, 6, 8)) == []  # 提前 2 天
    assert find_window_hits(event_index, "存储芯片", date(2025, 6, 11)) == []  # 已启动
    assert find_window_hits(event_index, "不存在的板块", date(2025, 6, 2)) == []


# ---------- extract_stock_mentions ----------


def test_extract_stock_mentions_with_code():
    text = "$英维克(SZ002837)$ 液冷订单饱满，$平安银行(SH600000)$ 也提一下"
    assert extract_stock_mentions(text) == {"002837", "600000"}


def test_extract_stock_mentions_bare_code():
    assert extract_stock_mentions("601127 赛力斯继续看多") == {"601127"}


def test_extract_stock_mentions_noise_rejected():
    # 6 位数字但非股票上下文（日期、手机号片段）不误提
    assert extract_stock_mentions("20250601 发布会") == set()


# ---------- keyword_hit_sectors ----------


def test_keyword_hit_direct():
    text = "存储芯片这波涨价周期还没走完"
    assert "存储芯片" in keyword_hit_sectors(text, {"存储芯片", "创新药"})


def test_keyword_hit_containment():
    # 帖子说"存储"，事件库板块叫"存储芯片"——双向包含命中
    assert "存储芯片" in keyword_hit_sectors(text := "存储涨价潮", {"存储芯片"})


def test_keyword_no_false_hit_on_short_name():
    # 单字板块名不做包含匹配（防误召回）
    assert keyword_hit_sectors("这个方案可行", {"可"}) == set()


# ---------- stock_to_sectors ----------


def test_stock_to_sectors():
    mapping = {
        "002837": [{"node": "gn_x", "name": "液冷概念", "board_type": "concept"}],
        "600000": [{"node": "hy_y", "name": "银行", "board_type": "industry"}],
    }
    s2s = stock_to_sectors(mapping)
    assert s2s["002837"] == {"液冷概念"}
    assert s2s["600000"] == {"银行"}


# ---------- score_expert ----------


def test_score_expert_formula():
    hits = [
        {"sector": "存储芯片", "tier": "strong"},
        {"sector": "创新药", "tier": "strong"},
        {"sector": "存储芯片", "tier": "mid"},
    ]
    s = score_expert(hits, total_original_posts=100)
    assert s["eye_score"] == 3 * 2 + 1          # 强×3 + 中×1
    assert s["persist"] == 2                    # 命中跨越 2 个板块
    assert s["density"] == pytest.approx(3 / 100)
    assert s["composite"] == pytest.approx(
        s["eye_score"] * 0.5 + s["persist"] * 0.3 + s["density"] * 0.2)


def test_score_expert_empty():
    s = score_expert([], total_original_posts=0)
    assert s["composite"] == 0


# ---------- parse_llm_json ----------


def test_parse_llm_json_tolerates_fence():
    raw = "```json\n{\"stance\": \"bullish\"}\n```"
    assert parse_llm_json(raw) == {"stance": "bullish"}


def test_parse_llm_json_invalid_returns_none():
    assert parse_llm_json("抱歉我无法判断") is None
