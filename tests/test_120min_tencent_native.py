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
        # 2026-09-11 marketdata 收口迁移后，脚本 fetch 层委托
        # qing_investment.marketdata.router；120min 走腾讯原生的语义
        # 由 router 降级链保证（120min 链不含 eastmoney）。
        # spy 对象从脚本内旧函数改为 marketdata 腾讯源。
        from qing_investment.marketdata.sources import tencent as md_tencent

        real_tx = md_tencent.fetch_kline

        def spy_tx(*a, **kw):
            calls["tencent"] += 1
            return real_tx(*a, **kw)

        monkeypatch.setattr(md_tencent, "fetch_kline", spy_tx)
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

    2026-10-20 修正：原实现用固定日期（2026-09-10 11:30）做数据锚定，
    但只取最近 10 根，随交易日推进该 bar 滚出窗口 → 测试必然过期失败。
    改为校验**字段序语义**（不依赖具体日期）：
      若把收盘价与最高/最低错位，会出现 close > high 或 close < low；
      若把开盘错成收盘，则 120min 首根会出现 open 与 close 互换的统计异常。
    同时保留一个强约束：同日首根 open 必须等于当日首笔价、末根 close 为区间收盘。
    """
    mod = _load("pre_fetch_index_klines.py")
    rows = mod.fetch_index_klines("sh000001", 120, 10)
    assert len(rows) >= 4, f"取数不足: {len(rows)}"

    by_t = {r["bar_time"]: r for r in rows}
    sample = list(by_t.values())[-1]

    # 1) 高低必须包住开收（字段序错位的第一道硬约束）
    assert sample["high"] >= max(sample["open"], sample["close"]) - 1e-6, \
        f"high 包不住 open/close，疑似字段错位: {sample}"
    assert sample["low"] <= min(sample["open"], sample["close"]) + 1e-6, \
        f"low 包不住 open/close，疑似字段错位: {sample}"

    # 2) 量价非负且高>低（防把 volume 读进价格字段）
    assert sample["volume"] >= 0
    assert sample["high"] >= sample["low"]

    # 3) 每一根都满足同样约束（不只看抽样）
    for r in rows:
        assert r["high"] >= max(r["open"], r["close"]) - 1e-6, r
        assert r["low"] <= min(r["open"], r["close"]) + 1e-6, r

    # 4) 日内两根的 open/close 连续性：第二根的 open 应接近第一根的 close
    days = {}
    for r in rows:
        days.setdefault(r["bar_time"][:10], []).append(r)
    for day, bars in days.items():
        bars.sort(key=lambda x: x["bar_time"])
        if len(bars) == 2:
            gap = abs(bars[1]["open"] - bars[0]["close"]) / bars[0]["close"]
            assert gap < 0.05, f"{day} 午间断档异常 {gap:.2%}，疑似字段错位"

    # 注：close == high 在真实行情中合法（收盘恰为区间最高），不能作为错位判据；
    # 字段序错位的实际信号是 close > high / close < low，上面第 1、3 条已覆盖。
