"""hermes_stock_monitor_agent 新增数据块测试：竞价摘要时间窗 + 盘后警示过滤 + 昨日梯队。"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from scripts import hermes_stock_monitor_agent as hsma


class TestAuctionDigestWindow:
    def test_outside_window_returns_none(self):
        assert hsma._fetch_auction_digest(datetime(2026, 8, 11, 10, 30)) is None
        assert hsma._fetch_auction_digest(datetime(2026, 8, 11, 9, 20)) is None

    def test_in_window_calls_api(self, monkeypatch):
        class _Resp:
            def read(self):
                return json.dumps({"data": {"diff": [
                    {"f12": "000802", "f14": "北京文化", "f3": 10.0, "f6": 2.4e8},
                    {"f12": "300862", "f14": "蓝盾光电", "f3": 20.0, "f6": 1.1e8},
                    {"f12": "600664", "f14": "哈药股份", "f3": 3.2, "f6": 5.0e8},
                ]}}).encode()

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        monkeypatch.setattr(hsma.urllib.request, "urlopen", lambda req, timeout=10: _Resp())
        out = hsma._fetch_auction_digest(datetime(2026, 8, 11, 9, 26))
        assert out is not None
        # 主板 ≥9.8 / 创业板 ≥19.8 判定竞价涨停
        assert any("北京文化" in s for s in out["auction_sealed"])
        assert any("蓝盾光电" in s for s in out["auction_sealed"])
        assert not any("哈药股份" in s for s in out["auction_sealed"])
        # 竞价额 top 保留全部 3 只
        assert len(out["top_amount"]) == 3

    def test_api_failure_returns_none(self, monkeypatch):
        def _boom(req, timeout=10):
            raise OSError("网络错误")

        monkeypatch.setattr(hsma.urllib.request, "urlopen", _boom)
        assert hsma._fetch_auction_digest(datetime(2026, 8, 11, 9, 26)) is None


class TestPostCloseAlerts:
    def test_keyword_filter(self, tmp_path, monkeypatch):
        news_dir = tmp_path / "news" / "2026-08-10"
        news_dir.mkdir(parents=True)
        (news_dir / "index.json").write_text(json.dumps([
            {"title": "爱丽家居：股票交易异常波动暨停牌核查公告",
             "stocks": [{"StockID": "603221"}]},
            {"title": "普通行业新闻", "stocks": []},
            {"title": "某公司收到警示函", "stocks": [{"StockID": "600001"}]},
        ], ensure_ascii=False), encoding="utf-8")
        monkeypatch.setattr(hsma, "_KPL_NEWS_DIR", tmp_path / "news")
        out = hsma._load_post_close_alerts("2026-08-11")
        assert out["news_date"] == "2026-08-10"
        assert len(out["items"]) == 2
        assert out["items"][0]["stocks"] == ["603221"]
        assert "停牌" in out["items"][0]["title"]

    def test_no_news_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.setattr(hsma, "_KPL_NEWS_DIR", tmp_path / "nonexistent")
        assert hsma._load_post_close_alerts("2026-08-11") is None


class TestLimitPoolLatest:
    def test_reads_latest_before_today(self, tmp_path, monkeypatch):
        (tmp_path / "20260807.json").write_text(json.dumps(
            {"date": "2026-08-07", "zt_count": 1, "zb_count": 0, "max_lbc": 2,
             "ladder": {"2板": ["A"]}, "auction_sealed": [], "compare": {},
             "zt_items": [{"name": "A", "lbc": 2}], "zb_items": []}), encoding="utf-8")
        (tmp_path / "20260810.json").write_text(json.dumps(
            {"date": "2026-08-10", "zt_count": 99, "zb_count": 14, "max_lbc": 5,
             "ladder": {"5板": ["宝鼎科技"]}, "auction_sealed": ["蓝盾光电"],
             "compare": {"promotion_rate": 0.15, "fanbao": ["高争民爆"]},
             "zt_items": [{"name": "宝鼎科技", "lbc": 5, "hybk": "元件",
                           "fund": 1e8, "zbc": 3},
                          {"name": "首板股", "lbc": 1}],
             "zb_items": []}), encoding="utf-8")
        monkeypatch.setattr(hsma, "_LIMIT_POOL_DIR", tmp_path)
        out = hsma._load_limit_pool_latest("2026-08-11")
        assert out["date"] == "2026-08-10"  # 取最近一日而非 08-07
        assert out["promotion_rate"] == 0.15 and out["fanbao"] == ["高争民爆"]
        # 首板不注入（控制体量）
        assert [i["name"] for i in out["lianban_items"]] == ["宝鼎科技"]

    def test_empty_dir_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.setattr(hsma, "_LIMIT_POOL_DIR", tmp_path)
        assert hsma._load_limit_pool_latest("2026-08-11") is None
