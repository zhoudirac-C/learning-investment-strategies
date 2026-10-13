"""成交集中度（top5% 成交额占比）测试 — 提案 2026-10-13-pack-enhancement-turnover-concentration。

UP 004-f 的筹码出清锚：「成交额前5%个股集中度 6-7月≈54% → 10月≈43%」。
本地复算口径：全A按当日成交额降序，top5% 个股成交额合计 / 全市场成交额。
"""
from __future__ import annotations

import json

import pytest

from investment_engine.blindtest.dataset import _load_concentration
from investment_engine.shadow.concentration import compute_concentration


class TestComputeConcentration:
    def _rows(self, amounts):
        # 模拟东财 clist 行：f12 代码、f6 成交额（元）
        return [{"f12": f"{i:06d}", "f6": a} for i, a in enumerate(amounts)]

    def test_top5pct_share(self):
        # 100 只：第 1 只 100 元，其余 99 只各 1 元 → top5% = 前5只
        amounts = [100.0] + [1.0] * 99
        r = compute_concentration(self._rows(amounts), top_pct=0.05)
        assert r["n_stocks"] == 100
        assert r["top_n"] == 5
        # top5 = 100+1+1+1+1 = 104；全市场 = 199
        assert r["concentration_pct"] == pytest.approx(104 / 199 * 100, abs=0.01)
        assert r["total_amount_yi"] == pytest.approx(199 / 1e8 * 1e8 / 1e8, abs=0.01)

    def test_unsorted_input_gets_sorted(self):
        amounts = [1.0] * 95 + [50.0, 30.0, 20.0, 10.0, 5.0]
        r = compute_concentration(self._rows(amounts), top_pct=0.05)
        # top5 = 50+30+20+10+5=115；total=95+115=210
        assert r["concentration_pct"] == pytest.approx(115 / 210 * 100, abs=0.01)

    def test_filters_zero_and_missing_amount(self):
        rows = self._rows([100.0, 0, None, "-", 1.0] + [1.0] * 95)
        r = compute_concentration(rows, top_pct=0.05)
        assert r["n_stocks"] == 97  # 0/None/'-' 剔除
        # top_n=int(97*0.05)=4 → top4=100+1+1+1=103, total=196
        assert r["top_n"] == 4
        assert r["concentration_pct"] == pytest.approx(103 / 196 * 100, abs=0.01)

    def test_empty_rows(self):
        assert compute_concentration([], top_pct=0.05) is None

    def test_top_pct_rounding(self):
        # 5562 只的 5% = 278.1 → 取 floor 278
        amounts = [1.0] * 5562
        r = compute_concentration(self._rows(amounts), top_pct=0.05)
        assert r["top_n"] == 278


class TestLoadConcentration:
    def _write(self, tmp_path, date, conc=45.0, total=15000.0):
        (tmp_path / f"{date}.json").write_text(json.dumps({
            "date": date, "concentration_pct": conc,
            "total_amount_yi": total, "n_stocks": 5500, "top_n": 275,
        }, ensure_ascii=False))

    def test_returns_latest_le_day(self, tmp_path):
        self._write(tmp_path, "2026-10-09", conc=46.0)
        self._write(tmp_path, "2026-10-12", conc=44.0)
        r = _load_concentration("2026-10-13", data_dir=tmp_path)
        assert r["as_of"] == "2026-10-12"
        assert r["concentration_pct"] == 44.0

    def test_replay_safety_excludes_future(self, tmp_path):
        self._write(tmp_path, "2026-10-12", conc=44.0)
        self._write(tmp_path, "2026-10-13", conc=30.0)  # 未来数据
        r = _load_concentration("2026-10-12", data_dir=tmp_path)
        assert r["as_of"] == "2026-10-12"
        assert r["concentration_pct"] == 44.0

    def test_none_when_no_data(self, tmp_path):
        assert _load_concentration("2026-10-13", data_dir=tmp_path) is None

    def test_stale_marked(self, tmp_path):
        self._write(tmp_path, "2026-09-30", conc=47.0)
        r = _load_concentration("2026-10-13", data_dir=tmp_path)
        assert r["as_of"] == "2026-09-30"
        assert r["stale_days"] >= 5  # 如实标注陈旧度

    def test_trend_window(self, tmp_path):
        # 25 个交易日数据 → 带 20 日均值与当前相对位置
        import datetime as dt
        d0 = dt.date(2026, 9, 1)
        for i in range(25):
            d = d0 + dt.timedelta(days=i)
            if d.weekday() < 5:
                self._write(tmp_path, d.isoformat(), conc=50.0 - i * 0.3)
        r = _load_concentration("2026-10-13", data_dir=tmp_path)
        assert "ma20_pct" in r
        assert r["ma20_pct"] > r["concentration_pct"]  # 递减序列最新值低于均值
