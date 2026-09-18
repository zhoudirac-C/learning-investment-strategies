"""异动驱动发现规则层测试（limit_pool + fund_flow → 题材热度卡 → 触发/阶段）。

对应 docs/design/chain-momentum-discovery-design.md §4.1-4.3。
"""
import json
import tempfile
from pathlib import Path

import pytest

from investment_engine.chain_tracker.momentum import (
    aggregate_theme_cards, judge_stage, load_limit_pool, trigger_themes,
)


def _zt(code, name, hybk, lbc=1, fund=1e8, fbt="93000", pct=10.0, zbc=0):
    return {"code": code, "name": name, "hybk": hybk, "lbc": lbc,
            "fund": fund, "fbt": fbt, "pct": pct, "zbc": zbc,
            "days_ct": f"{lbc}天{lbc}板"}


def _pool(items, zb_items=None):
    return {"date": "2026-09-16", "zt_count": len(items),
            "zb_count": len(zb_items or []), "zt_items": items,
            "zb_items": zb_items or []}


def _flow(*concept_rows):
    return {"concept": {"即时": [
        {"行业": name, "行业-涨跌幅": pct, "领涨股": leader,
         "领涨股-涨跌幅": lpct}
        for name, pct, leader, lpct in concept_rows]},
        "industry": {"即时": []}}


class TestAggregateThemeCards:
    def test_groups_by_hybk(self):
        pool = _pool([
            _zt("001", "剑桥科技", "通信设备", lbc=2, fund=3e8, fbt="92500"),
            _zt("002", "新易盛", "通信设备", lbc=1, fund=2e8, fbt="93500"),
            _zt("003", "中际旭创", "通信设备", lbc=1, fund=1e8, fbt="100000"),
            _zt("004", "百通能源", "电力", lbc=1),
        ])
        cards = {c["theme"]: c for c in aggregate_theme_cards(pool=pool)}
        card = cards["通信设备"]
        assert card["zt_count"] == 3
        assert card["first_board_count"] == 2
        assert card["max_lbc"] == 2
        assert card["seal_fund"] == pytest.approx(6e8)
        assert card["earliest_seal"] == "09:25"
        # leaders：连板高者优先
        assert card["leaders"][0] == "剑桥科技"
        assert len(card["stocks"]) == 3
        assert cards["电力"]["zt_count"] == 1

    def test_cross_references_fund_flow_pct(self):
        pool = _pool([_zt("001", "新易盛", "通信设备"),
                      _zt("002", "剑桥科技", "通信设备"),
                      _zt("003", "百通能源", "电力")])
        flow = _flow(("通信设备", 4.3, "剑桥科技", 10.0),
                     ("CPO", 5.1, "中际旭创", 12.0))
        cards = {c["theme"]: c for c in
                 aggregate_theme_cards(pool=pool, flow=flow)}
        # 精确名命中
        assert cards["通信设备"]["sector_pct"] == pytest.approx(4.3)
        # 无匹配时 None
        assert cards["电力"]["sector_pct"] is None

    def test_streak_days_from_prev_pool(self):
        pool = _pool([_zt("001", "新易盛", "通信设备"),
                      _zt("002", "剑桥科技", "通信设备")])
        prev = _pool([_zt("003", "天孚通信", "通信设备"),
                      _zt("004", "光迅科技", "通信设备")])
        cards = {c["theme"]: c for c in
                 aggregate_theme_cards(pool=pool, prev_pool=prev)}
        assert cards["通信设备"]["streak_days"] == 2
        cards = {c["theme"]: c for c in aggregate_theme_cards(pool=pool)}
        assert cards["通信设备"]["streak_days"] == 1

    def test_broken_count_per_theme(self):
        pool = _pool([_zt("001", "新易盛", "通信设备"),
                      _zt("002", "百通能源", "电力")],
                     zb_items=[{"code": "009", "name": "杂股", "hybk": "通信设备"},
                               {"code": "010", "name": "杂股2", "hybk": "电力"}])
        cards = {c["theme"]: c for c in aggregate_theme_cards(pool=pool)}
        assert cards["通信设备"]["broken_count"] == 1
        assert cards["电力"]["broken_count"] == 1


class TestTrigger:
    def _card(self, **kw):
        base = {"theme": "T", "zt_count": 1, "first_board_count": 1,
                "max_lbc": 1, "sector_pct": None, "streak_days": 1}
        base.update(kw)
        return base

    def test_zt_burst(self):
        cards = [self._card(zt_count=3)]
        out = trigger_themes(cards)
        assert len(out) == 1 and "zt_burst" in out[0]["trigger_reasons"]

    def test_ladder(self):
        cards = [self._card(zt_count=2, max_lbc=2)]
        out = trigger_themes(cards)
        assert len(out) == 1 and "ladder" in out[0]["trigger_reasons"]

    def test_resonance(self):
        cards = [self._card(zt_count=2, sector_pct=3.5)]
        out = trigger_themes(cards)
        assert len(out) == 1 and "resonance" in out[0]["trigger_reasons"]

    def test_single_stock_filtered(self):
        cards = [self._card(zt_count=1, sector_pct=2.0)]
        assert trigger_themes(cards) == []

    def test_custom_threshold(self):
        cards = [self._card(zt_count=4)]
        assert trigger_themes(cards, min_zt=5) == []


class TestJudgeStage:
    def _card(self, **kw):
        base = {"theme": "T", "zt_count": 5, "first_board_count": 4,
                "max_lbc": 1, "streak_days": 1, "broken_count": 0}
        base.update(kw)
        return base

    def test_startup(self):
        stage, ev = judge_stage(self._card())
        assert stage == "阶段1-启动期"
        assert ev["first_board_ratio"] == pytest.approx(0.8)

    def test_acceleration_by_ladder(self):
        stage, _ = judge_stage(self._card(max_lbc=3, first_board_count=1))
        assert stage == "阶段2-加速期"

    def test_acceleration_by_zt_growth(self):
        prev = self._card(zt_count=3)
        stage, _ = judge_stage(self._card(zt_count=5), prev_card=prev)
        assert stage == "阶段2-加速期"

    def test_divergence(self):
        prev = self._card(zt_count=6)
        # 涨停 6→3 环比下降，炸板 2/(3+2)=40% > 30%
        stage, _ = judge_stage(self._card(zt_count=3, broken_count=2,
                                          first_board_count=1),
                               prev_card=prev)
        assert stage == "阶段3-分歧期"

    def test_top(self):
        prev = self._card(max_lbc=3, zt_count=5)
        stage, _ = judge_stage(self._card(max_lbc=1, zt_count=1,
                                          first_board_count=1),
                               prev_card=prev)
        assert stage == "阶段4-见顶期"


class TestLoadLimitPool:
    def test_roundtrip(self):
        d = Path(tempfile.mkdtemp(prefix="pool_test_"))
        (d / "20260916.json").write_text(json.dumps(_pool([_zt("1", "A", "电力")])),
                                         encoding="utf-8")
        pool = load_limit_pool("2026-09-16", root=d)
        assert pool["zt_items"][0]["name"] == "A"

    def test_missing_returns_none(self):
        d = Path(tempfile.mkdtemp(prefix="pool_test_"))
        assert load_limit_pool("2026-09-16", root=d) is None

    def test_broken_returns_none(self):
        d = Path(tempfile.mkdtemp(prefix="pool_test_"))
        (d / "20260916.json").write_text("不是json", encoding="utf-8")
        assert load_limit_pool("2026-09-16", root=d) is None
