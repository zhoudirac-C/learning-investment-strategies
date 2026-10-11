"""估值 overlay 单测（mock 数据层，不联网）。"""
from investment_engine.sentiment import valuation_overlay as vo


def test_classify_cyclical():
    assert vo.classify_board("煤炭开采加工") == "cyclical"
    assert vo.classify_board("半导体") == "growth"


def test_assess_cheap_growth(monkeypatch):
    # 3 只成分股，当前 PE 都在自身 3 年历史底部 → cheap
    monkeypatch.setattr(vo, "get_board_stocks", lambda b: ["000001", "000002", "000003"])
    monkeypatch.setattr(vo, "fetch_valuation_latest",
                        lambda c: {"PE_TTM": 10.0, "PB_MRQ": 1.0})
    monkeypatch.setattr(vo, "fetch_history",
                        lambda c, field, days=1095: [10.0 + i for i in range(100)])
    r = vo.assess_valuation("半导体", use_cache=False)
    assert r["method"] == "pe_percentile"
    assert r["cheap"] is True
    assert r["value"] <= 30.0
    assert r["n_stocks"] == 3


def test_assess_expensive_cyclical(monkeypatch):
    # 周期板块 PB 处于历史高位 → 不 cheap
    monkeypatch.setattr(vo, "get_board_stocks", lambda b: ["600001", "600002", "600003"])
    monkeypatch.setattr(vo, "fetch_valuation_latest",
                        lambda c: {"PE_TTM": 8.0, "PB_MRQ": 5.0})
    monkeypatch.setattr(vo, "fetch_history",
                        lambda c, field, days=1095: [1.0 + i * 0.04 for i in range(100)])
    r = vo.assess_valuation("煤炭开采加工", use_cache=False)
    assert r["method"] == "pb_percentile"
    assert r["cheap"] is False
    assert r["value"] >= 80.0


def test_assess_no_stocks(monkeypatch):
    monkeypatch.setattr(vo, "get_board_stocks", lambda b: [])
    r = vo.assess_valuation("不存在板块", use_cache=False)
    assert r["cheap"] is None
    assert r["n_stocks"] == 0
