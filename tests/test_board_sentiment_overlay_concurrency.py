"""估值 overlay 并发化测试（2026-10-16 治本方案 B1）。

背景：10-16 板块情绪温度计 cron 因 `Script timed out after 900s` 失败。
根因：valuation_overlay.assess_valuation 对每个 cold 板块**串行**遍历最多
60 只成分股，每只 2 次 HTTP + 1.5s sleep（~2.1-3.5s/股），31 个 cold 板块
需 30-50 分钟，而 cron 有效超时仅 900s（env HERMES_CRON_SCRIPT_TIMEOUT 覆盖
config 的 600）—— 结构上必然跑不完。

本测试锁定并发化契约：
1. `assess_all_valuations` 批量并发入口存在，且能覆盖全部 cold 板块；
2. 并发显著快于串行（用可注入的慢 fetch 模拟 60 股 × 1.5s 的真实耗时）；
3. 单板块结果与串行口径一致（不因并发引入数值漂移）。
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from investment_engine.sentiment import valuation_overlay as vo  # noqa: E402


def _fake_stocks(n: int = 60) -> list[str]:
    return [f"{i:06d}" for i in range(n)]


def test_assess_all_valuations_covers_every_board(monkeypatch, tmp_path):
    """批量入口必须对每个传入板块返回结果，一条不落。"""
    monkeypatch.setattr(vo, "CACHE_DIR", tmp_path)
    boards = [f"板块{i}" for i in range(31)]

    monkeypatch.setattr(vo, "get_board_stocks", lambda b: _fake_stocks(5))

    def fake_latest(code):
        return {"PE_TTM": 20.0}

    def fake_history(code, field, days=None):
        return [10.0, 30.0] * 40  # 80 点 > MIN 60

    monkeypatch.setattr(vo, "fetch_valuation_latest", fake_latest)
    monkeypatch.setattr(vo, "fetch_history", fake_history)
    monkeypatch.setattr(vo, "SLEEP_S", 0.0)

    out = vo.assess_all_valuations(boards)

    assert set(out) == set(boards), "批量入口漏算板块"
    for b in boards:
        assert out[b]["board"] == b


def test_assess_all_valuations_is_concurrent(monkeypatch, tmp_path):
    """并发契约：31 板块 × 60 股 × 0.05s 串行需 >90s，并发应远低于串行墙钟。

    断言并发墙钟 < 串行理论值的 50%，防止实现退回串行。
    """
    monkeypatch.setattr(vo, "CACHE_DIR", tmp_path)
    boards = [f"板块{i}" for i in range(31)]
    per_stock_sleep = 0.05

    monkeypatch.setattr(vo, "get_board_stocks", lambda b: _fake_stocks(60))

    def slow_latest(code):
        time.sleep(per_stock_sleep)
        return {"PE_TTM": 20.0}

    def slow_history(code, field, days=None):
        time.sleep(per_stock_sleep)
        return [10.0, 30.0] * 40

    monkeypatch.setattr(vo, "fetch_valuation_latest", slow_latest)
    monkeypatch.setattr(vo, "fetch_history", slow_history)
    monkeypatch.setattr(vo, "SLEEP_S", 0.0)
    monkeypatch.setattr(vo, "MAX_STOCKS", 60)

    serial_estimate = len(boards) * 60 * per_stock_sleep * 2  # ≈186s

    t0 = time.monotonic()
    out = vo.assess_all_valuations(boards)
    elapsed = time.monotonic() - t0

    assert len(out) == len(boards)
    assert elapsed < serial_estimate * 0.5, (
        f"并发未生效：墙钟 {elapsed:.1f}s 对比串行估计 {serial_estimate:.1f}s")


def test_results_match_serial_semantics(monkeypatch, tmp_path):
    """并发结果与串行口径一致：value/cheap/n_stocks 必须相同。"""
    monkeypatch.setattr(vo, "CACHE_DIR", tmp_path)
    board = "测试板块"
    monkeypatch.setattr(vo, "get_board_stocks", lambda b: _fake_stocks(10))

    def fake_latest(code):
        return {"PE_TTM": 20.0}

    def fake_history(code, field, days=None):
        return [10.0] * 70 + [30.0] * 10  # 70/80 低于 20 → pct=87.5

    monkeypatch.setattr(vo, "fetch_valuation_latest", fake_latest)
    monkeypatch.setattr(vo, "fetch_history", fake_history)
    monkeypatch.setattr(vo, "SLEEP_S", 0.0)

    serial = vo.assess_valuation(board, use_cache=False)
    # 清缓存后走批量并发
    for p in tmp_path.glob("*.json"):
        p.unlink()
    batch = vo.assess_all_valuations([board])[board]

    assert batch["value"] == serial["value"]
    assert batch["cheap"] == serial["cheap"]
    assert batch["n_stocks"] == serial["n_stocks"]
