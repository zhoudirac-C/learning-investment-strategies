"""120min 走腾讯原生 m120 的回归测试 (2026-09-10)。

背景
====
东财 **无原生 120min**（klt=120 非标准取值，实测返回空），此前 120min 由
60min 合成（`_synth_120min_from_60min`），实测与腾讯原生 m120 存在偏差：

  bar_time      字段   腾讯原生   我们合成   差异
  09-09 11:30   close   3949.89   3956.24   Δ6.35
  09-10 11:30   close   3937.78   3942.09   Δ4.31
  全样本最大差异: close 6.73 / low 6.22 / open 0.43 / high 0.07

腾讯 `m120` 是**原生** 120min 接口：
  - 486 根 / 1 年，每日恰好 2 根
  - 相邻间隔 210 分钟 = 09:30→11:30 + 午休 + 13:00→15:00（跨午休特征正确）
  - 字段序: 时间, 开, 收, 高, 低, 量

本测试锁定：klt=120 必须**优先**走腾讯原生，合成仅作兜底。
"""

import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

SCRIPTS = {
    "update_index_klines_intraday.py": "fetch_latest_klines",
    "pre_fetch_index_klines.py": "fetch_index_klines",
}


def _load(script_name: str):
    spec = importlib.util.spec_from_file_location(
        f"t120_{script_name.replace('.', '_')}", REPO / "scripts" / script_name
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("script", list(SCRIPTS))
def test_120min_prefers_tencent_native(script, monkeypatch):
    """klt=120 必须走腾讯 m120，不得先走东财（东财无此周期）。"""
    mod = _load(script)
    calls = {"tencent": 0, "eastmoney": 0}

    if script == "pre_fetch_index_klines.py":
        real_native = mod._fetch_tencent_native

        def spy_native(*a, **kw):
            calls["tencent"] += 1
            return real_native(*a, **kw)

        monkeypatch.setattr(mod, "_fetch_tencent_native", spy_native)

        # 东财路径：若被调用则计数（不抛错，避免掩盖真实返回）
        orig_urlopen = mod.urllib.request.urlopen

        def spy_urlopen(req, *a, **kw):
            url = req.full_url if hasattr(req, "full_url") else str(req)
            if "eastmoney" in url:
                calls["eastmoney"] += 1
            return orig_urlopen(req, *a, **kw)

        monkeypatch.setattr(mod.urllib.request, "urlopen", spy_urlopen)
        rows = mod.fetch_index_klines("sh000001", 120, 10)
    else:
        real_tx = mod.fetch_latest_klines_from_tencent

        def spy_tx(*a, **kw):
            calls["tencent"] += 1
            return real_tx(*a, **kw)

        monkeypatch.setattr(mod, "fetch_latest_klines_from_tencent", spy_tx)

        real_em = mod._eastmoney_get

        def spy_em(*a, **kw):
            calls["eastmoney"] += 1
            return real_em(*a, **kw)

        monkeypatch.setattr(mod, "_eastmoney_get", spy_em)
        rows = mod.fetch_latest_klines("sh000001", 120, 10)

    assert rows, "120min 应有数据"
    assert calls["tencent"] >= 1, "应调用腾讯 m120"
    assert calls["eastmoney"] == 0, f"不应先走东财，实际调用 {calls['eastmoney']} 次"


@pytest.mark.parametrize("script", list(SCRIPTS))
def test_120min_bar_shape(script):
    """腾讯 m120 返回的 bar 结构正确，且每日恰好 2 根、跨午休。"""
    mod = _load(script)
    if script == "pre_fetch_index_klines.py":
        rows = mod.fetch_index_klines("sh000001", 120, 20)
    else:
        rows = mod.fetch_latest_klines("sh000001", 120, 20)

    assert len(rows) == 20

    # 时间升序、无重复
    times = [r["bar_time"] for r in rows]
    assert times == sorted(times)
    assert len(set(times)) == len(times)

    # 每根都是 :30 收（11:30 / 15:00）
    for r in rows:
        assert r["bar_time"][11:16] in ("11:30", "15:00"), r["bar_time"]

    # OHLC 基本约束
    for r in rows:
        assert r["high"] >= max(r["open"], r["close"]) - 1e-6
        assert r["low"] <= min(r["open"], r["close"]) + 1e-6

    # 每日恰好 2 根
    from collections import Counter
    per_day = Counter(r["bar_time"][:10] for r in rows)
    assert set(per_day.values()) == {2}, f"每日根数异常: {dict(per_day)}"


def test_tencent_field_order_is_open_close_high_low():
    """字段序必须是 时间,开,收,高,低,量 —— 写错会静默产出脏数据。

    用已知真实数据锚定（上证 2026-09-10）：
      09:30 开 = 3939.09
      11:30 收 = 3937.78
      上午最高 3949.25 / 最低 3927.35（= 全天高低）
    """
    mod = _load("pre_fetch_index_klines.py")
    rows = mod.fetch_index_klines("sh000001", 120, 10)
    by_t = {r["bar_time"]: r for r in rows}

    b = by_t.get("2026-09-10 11:30")
    assert b is not None, "缺少 09-10 11:30 这根"
    assert b["open"] == pytest.approx(3939.09, abs=0.01), "首价应为 09:30 开盘"
    assert b["close"] == pytest.approx(3937.78, abs=0.01), "收价应为 11:30 时刻"
    assert b["high"] == pytest.approx(3949.25, abs=0.01)
    assert b["low"] == pytest.approx(3927.35, abs=0.01)

    # 若字段序写错（把高当收），close 会等于 3949.25 —— 显式排除
    assert abs(b["close"] - b["high"]) > 1.0, "close 不应等于 high（字段序错位信号）"
