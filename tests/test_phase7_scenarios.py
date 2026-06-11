"""
Phase 7 验收测试 — 模拟场景验证
覆盖：7.1 烂板竞价, 7.2 四种持仓类型, 7.3 tomorrow_scenarios

运方式：.venv/bin/python tests/test_phase7_scenarios.py
前置条件：qing-agent 运行在 localhost:8000
"""
from __future__ import annotations

import json
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from pathlib import Path

CN_TZ = timezone(timedelta(hours=8))
QING_AGENT_URL = "http://localhost:8000/analyze/trigger"
QING_AGENT_TIMEOUT = 120
PASS = 0
FAIL = 0

def _post_to_agent(data: dict) -> dict | None:
    payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        QING_AGENT_URL, data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=QING_AGENT_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"  [API ERROR] {e}", file=sys.stderr)
        return None

def print_result(label: str, ok: bool, detail: str = ""):
    global PASS, FAIL
    status = "✅ PASS" if ok else "❌ FAIL"
    if ok:
        PASS += 1
    else:
        FAIL += 1
    print(f"  [{status}] {label}")
    if detail:
        print(f"          {detail}")

def check_text(output: str, expected: str, label: str) -> bool:
    ok = expected.lower() in output.lower()
    print_result(label, ok,
                 f"found='{expected[:50]}'" if ok else f"NOT FOUND: '{expected}'")
    return ok

# ══════════════════════════════════════════════
# 7.1: 模拟盘后测试 — 09:26 烂板竞价
# ══════════════════════════════════════════════
def test_7_1_weak_board_auction():
    print("\n" + "=" * 60)
    print("📊 7.1 模拟盘后测试 — 09:26 烂板竞价低开-3%")
    print("=" * 60)

    data = {
        "analysis_type": "market",
        "stock_code": "",
        "timestamp": datetime(2026, 6, 12, 9, 26, tzinfo=CN_TZ).isoformat(),
        "trigger": {
            "kind": "scheduled",
            "id": "mock-09-26",
            "title": "集合竞价后定调",
            "reason": "模拟测试：烂板票竞价低开",
        },
        "market_framework": {"stage": "等修复", "core_question": "弱势修复能否延续"},
        "alerts": [],
        "market_state": {},
        "sector_signal_counts": {},
        "positions": [
            {
                "code": "002409", "name": "雅克科技",
                "cost": 23.5, "shares": 1000,
                "latest": 22.8, "pct_change": -3.0,
                "avg_cost": 23.5, "unrealized_pct": -2.98,
                "cost_protection_line": 23.5,
                "position_type": "weak_board",
                "sector_tier": {"self_rank_label": 3, "avg_change": 4.5, "total": 5},
            }
        ],
        "watchlist": [],
        "sector_strengths": [],
        "external_sector_boards": {"available": False},
        "quote_snapshot": {
            "source": "mock",
            "quotes": [
                {"code": "sz002409", "name": "雅克科技",
                 "latest": "22.8", "pct_change": "-3.0",
                 "open": "22.5", "high": "22.9", "low": "22.4",
                 "previous_close": "23.5", "volume": "12000", "amount": "273600"},
            ],
            "errors": [],
        },
        "yesterday_summary": {
            "date": "2026-06-11",
            "positions": {
                "002409": {
                    "close": 23.5, "change_pct": 10.0, "is_limit_up": True,
                    "amplitude": 7.2, "turnover_rate": 18.5, "volume_ratio": 2.3,
                    "board_quality": "weak",
                    "dragon_tiger_net": 68000000,
                    "dt_seat_type": "游资主导",
                    "dt_top_buy_behavior": "买一主导",
                    "dt_is_pure_hot_money": False,
                    "avg_cost": 23.5, "unrealized_pct": 0,
                    "vs_ma5": 15.3, "vs_ma10": 22.1,
                }
            },
            "market": {"stage": "等修复", "stage_detail": "弱势震荡"},
            "tomorrow_scenarios": {
                "strong_repair": {
                    "probability": "20%",
                    "auction_signature": "全A高开>0.5%，竞价量放大",
                    "action_if_match": "持仓不动",
                },
                "weak_consolidation": {
                    "probability": "55%",
                    "auction_signature": "全A平开±0.3%，竞价量正常",
                    "action_if_match": "做T为主",
                },
                "strong_divergence": {
                    "probability": "25%",
                    "auction_signature": "全A低开>0.5%，竞价量萎缩",
                    "action_if_match": "直接降仓",
                },
            },
        },
        "auction_snapshot": {
            "002409": {
                "auction_price": 22.8, "auction_change_pct": -3.0,
                "auction_volume": 8000, "auction_volume_ratio": 0.45,
                "auction_trend_920_925": "unknown",
                "auction_vs_yesterday_volume": 0.02,
            }
        },
        "dragon_tiger_board": {},
    }

    resp = _post_to_agent(data)
    if not resp or not resp.get("final_output"):
        print_result("7.1 qing-agent 返回空", False, "agent 无响应或超时")
        return

    output = resp["final_output"]
    print(f"\n--- LLM 输出 ---\n{output}\n-----------------\n")
    check_text(output, "减仓", "烂板竞价提示减仓操作")
    check_text(output, "弱震荡", "剧本验证弱震荡分支")
    check_text(output, "竞价低开", "提及竞价低开偏差")
    check_text(output, "2290", "提及支撑位（若有）")  # 仅当代码中有支撑位分析


# ══════════════════════════════════════════════
# 7.2: 模拟测试 — 09:45 四种持仓类型分支
# ══════════════════════════════════════════════
def test_7_2_position_type_branches():
    print("\n" + "=" * 60)
    print("📊 7.2 模拟测试 — 09:45 四种持仓类型分支")
    print("=" * 60)

    scenarios = [
        ("limit_up", "连板", {
            "latest": 25.85, "pct_change": 10.0, "avg_cost": 23.5,
            "unrealized_pct": 10.0, "position_type": "limit_up",
            "yesterday_is_limit_up": True, "yesterday_amplitude": 2.1,
        }),
        ("weak_board", "烂板", {
            "latest": 23.0, "pct_change": -2.1, "avg_cost": 23.5,
            "unrealized_pct": -2.13, "position_type": "weak_board",
            "yesterday_is_limit_up": True, "yesterday_amplitude": 7.2,
        }),
        ("floating_loss", "浮亏", {
            "latest": 17.8, "pct_change": -1.1, "avg_cost": 22.0,
            "unrealized_pct": -19.09, "position_type": "floating_loss",
            "yesterday_is_limit_up": False, "yesterday_amplitude": 3.5,
        }),
        ("trend", "趋势", {
            "latest": 35.2, "pct_change": 1.5, "avg_cost": 32.0,
            "unrealized_pct": 10.0, "position_type": "trend",
            "yesterday_is_limit_up": False, "yesterday_amplitude": 2.8,
        }),
    ]

    for ptype, label, vals in scenarios:
        print(f"\n--- 分支 {label} ({ptype}) ---")
        today_pct = vals["pct_change"]
        yesterday_summary_pos = {
            "close": vals["avg_cost"] * (1 + today_pct/100),
            "change_pct": 5.0 if vals["yesterday_is_limit_up"] else 1.2,
            "is_limit_up": vals["yesterday_is_limit_up"],
            "amplitude": vals["yesterday_amplitude"],
            "turnover_rate": 12.0, "volume_ratio": 1.5,
            "avg_cost": vals["avg_cost"], "unrealized_pct": vals["unrealized_pct"],
            "vs_ma5": 8.0, "vs_ma10": 12.0,
        }

        data = {
            "analysis_type": "market",
            "stock_code": "",
            "timestamp": datetime(2026, 6, 12, 9, 45, tzinfo=CN_TZ).isoformat(),
            "trigger": {
                "kind": "scheduled", "id": f"mock-09-45-{ptype}",
                "title": "开盘15分钟确认",
                "reason": f"模拟测试：{label}分支验证",
            },
            "market_framework": {"stage": "等修复", "core_question": "测试"},
            "alerts": [],
            "market_state": {},
            "sector_signal_counts": {},
            "positions": [{
                "code": "002409", "name": "雅克科技",
                "cost": vals["avg_cost"], "shares": 1000,
                "latest": vals["latest"], "pct_change": today_pct,
                "avg_cost": vals["avg_cost"],
                "unrealized_pct": vals["unrealized_pct"],
                "cost_protection_line": round(vals["avg_cost"] * 1.05 if vals["unrealized_pct"] > 10 else vals["avg_cost"], 2),
                "position_type": vals["position_type"],
                "sector_tier": {"self_rank_label": 1, "avg_change": pct_map(ptype), "total": 5},
            }],
            "watchlist": [],
            "sector_strengths": [],
            "external_sector_boards": {"available": False},
            "quote_snapshot": {
                "source": "mock", "quotes": [], "errors": [],
            },
            "yesterday_summary": {
                "date": "2026-06-11",
                "positions": {"002409": yesterday_summary_pos},
                "market": {"stage": "等修复"},
            },
            "auction_snapshot": {},
            "dragon_tiger_board": {},
        }

        resp = _post_to_agent(data)
        output = resp["final_output"] if resp and resp.get("final_output") else "(no output)"
        print(f"  输出片段: {output[:120]}...")

        # 分类验证：不同类型期望关键词不同
        if ptype == "weak_board":
            check_text(output, "烂板", f"{label}: 提及烂板")
            check_text(output, "承接", f"{label}: 判断承接")
        elif ptype == "floating_loss":
            check_text(output, "止损", f"{label}: 提示止损/风控")
        elif ptype == "limit_up":
            check_text(output, "封板", f"{label}: 判断封板/开板")
        elif ptype == "trend":
            check_text(output, "量能", f"{label}: 分析量能模式")
            check_text(output, "阶梯", f"{label}: 判断堆量类型")

def pct_map(ptype):
    return {"limit_up": 7.5, "weak_board": 2.0, "floating_loss": -1.5, "trend": 3.0}[ptype]


# ══════════════════════════════════════════════
# 7.3: 模拟测试 — 收盘复盘 tomorrow_scenarios
# ══════════════════════════════════════════════
def test_7_3_closing_tomorrow_scenarios():
    print("\n" + "=" * 60)
    print("📊 7.3 模拟测试 — 收盘复盘 tomorrow_scenarios")
    print("=" * 60)

    data = {
        "analysis_type": "market",
        "stock_code": "",
        "timestamp": datetime(2026, 6, 12, 17, 0, tzinfo=CN_TZ).isoformat(),
        "trigger": {
            "kind": "scheduled", "id": "mock-17-00",
            "title": "收盘复盘（含龙虎榜）",
            "reason": "模拟测试：复杂交易日复盘",
        },
        "market_framework": {"stage": "弱修复失败", "core_question": "上行还是回踩？"},
        "alerts": [],
        "market_state": {},
        "sector_signal_counts": {},
        "positions": [
            {
                "code": "002409", "name": "雅克科技",
                "cost": 23.5, "shares": 1000,
                "latest": 25.85, "pct_change": 10.0,
                "avg_cost": 23.5, "unrealized_pct": 10.0,
                "cost_protection_line": 24.68,
                "position_type": "limit_up",
                "sector_tier": {"self_rank_label": 1, "avg_change": 5.2, "total": 6},
            },
            {
                "code": "000636", "name": "风华高科",
                "cost": 32.0, "shares": 500,
                "latest": 34.5, "pct_change": 2.5,
                "avg_cost": 32.0, "unrealized_pct": 7.81,
                "cost_protection_line": 32.96,
                "position_type": "trend",
                "sector_tier": {"self_rank_label": 2, "avg_change": 2.1, "total": 8},
            },
            {
                "code": "600378", "name": "昊华科技",
                "cost": 18.0, "shares": 2000,
                "latest": 16.5, "pct_change": -2.9,
                "avg_cost": 18.0, "unrealized_pct": -8.33,
                "cost_protection_line": 17.1,
                "position_type": "floating_loss",
            },
        ],
        "watchlist": [],
        "sector_strengths": [],
        "external_sector_boards": {"available": False},
        "quote_snapshot": {
            "source": "mock",
            "quotes": [
                {"code": "sz002409", "name": "雅克科技",
                 "latest": "25.85", "pct_change": "10.0",
                 "volume": "120000", "amount": "3100000"},
                {"code": "sz000636", "name": "风华高科",
                 "latest": "34.5", "pct_change": "2.5",
                 "volume": "80000", "amount": "2760000"},
                {"code": "sh600378", "name": "昊华科技",
                 "latest": "16.5", "pct_change": "-2.9",
                 "volume": "60000", "amount": "990000"},
            ],
            "errors": [],
        },
        "yesterday_summary": {
            "date": "2026-06-11",
            "positions": {
                "002409": {
                    "close": 23.5, "change_pct": 10.0, "is_limit_up": True,
                    "amplitude": 2.5, "board_quality": "strong",
                    "dragon_tiger_net": 818000000, "dt_seat_type": "外资+机构+量化",
                    "avg_cost": 23.5, "unrealized_pct": 0,
                },
                "000636": {
                    "close": 33.6, "change_pct": 1.8, "is_limit_up": False,
                    "amplitude": 3.2, "avg_cost": 32.0, "unrealized_pct": 4.38,
                },
                "600378": {
                    "close": 17.0, "change_pct": -5.6, "is_limit_up": False,
                    "amplitude": 4.1, "avg_cost": 18.0, "unrealized_pct": -5.56,
                },
            },
            "market": {"stage": "弱修复失败",
                       "direction_priority": [{"direction": "机器人", "intensity": "🔥🔥"}],
                       "position_stance": "6成仓"},
            "tomorrow_scenarios": None,
        },
        "dragon_tiger_board": {
            "watch_dt_items": ["雅克科技(002409): +8.18亿"],
            "dt_nettop5": [{"name": "雅克科技", "net_buy": "+8.18亿"}],
            "dt_sector_summary": {"上游材料": {"total_net_str": "+15.2亿", "stocks": ["002409", "000636"]}},
            "_board_count": 109,
        },
    }

    resp = _post_to_agent(data)
    if not resp or not resp.get("final_output"):
        print_result("7.3 qing-agent 返回空", False, "agent 无响应或超时")
        return

    output = resp["final_output"]
    print(f"\n--- LLM 输出 ---\n{output}\n-----------------\n")

    # 验证1: 盘中 view 演进回顾
    check_text(output, "10.0%", "涨停持仓涨幅")
    check_text(output, "2.5%", "趋势股涨幅")

    # 验证2: 连板股处理
    check_text(output, "涨停", "连板股分析")
    check_text(output, "龙虎榜", "龙虎榜回顾")
    check_text(output, "浮亏", "浮亏股处理")
    check_text(output, "8.33", "浮亏比例")

    # 验证3: 龙虎榜引用
    check_text(output, "002409", "龙虎榜标的代码")


def print_summary():
    total = PASS + FAIL
    print(f"\n{'=' * 60}")
    print(f"📋 测试汇总: {PASS} ✅ / {total} 总计")
    if FAIL > 0:
        print(f"  ⚠️  部分测试未通过 — 需要人工判断 LLM 输出是否合理")
    print(f"{'=' * 60}")

if __name__ == "__main__":
    test_7_1_weak_board_auction()
    test_7_2_position_type_branches()
    test_7_3_closing_tomorrow_scenarios()
    print_summary()
