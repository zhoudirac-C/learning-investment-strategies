"""intraday_changes.py 单元测试（monkeypatch akshare，不触网）。"""
from __future__ import annotations

import json

import pytest

from investment_engine import intraday_changes as ic
from investment_engine.blindtest.dataset import _load_intraday_changes


DAY = "20260812"


@pytest.fixture
def fake_ak(monkeypatch):
    """封涨停板返回 2 条，大笔买入返回 1 条，其余返回空（返回 list[dict]，与 _fetch_one 一致）。"""
    def _fake(symbol):
        if symbol == "封涨停板":
            return [
                {"time": "14:54:30", "code": "600721", "name": "百花医药",
                 "sector": "封涨停板", "info": "14.030000,4042894,14.03000,0.100392"},
                {"time": "14:51:24", "code": "603369", "name": "今世缘",
                 "sector": "封涨停板", "info": "30.720000,746590,30.72000,0.099893"},
            ]
        if symbol == "大笔买入":
            return [{"time": "09:35:11", "code": "000001", "name": "平安银行",
                     "sector": "大笔买入", "info": "12.50,100000,12.50,0.0312"}]
        return []
    monkeypatch.setattr(ic, "_fetch_one", _fake)


def test_build_intraday_changes_structure(fake_ak):
    data = ic.build_intraday_changes(DAY)
    assert data["date"] == "2026-08-12"
    assert data["counts"]["封涨停板"] == 2
    assert data["counts"]["大笔买入"] == 1
    assert data["counts"]["火箭发射"] == 0
    assert data["total"] == 3
    # types 里封涨停板是 list[dict]
    assert isinstance(data["types"]["封涨停板"], list)
    assert data["types"]["封涨停板"][0]["code"] == "600721"


def test_build_one_type_error_not_fatal(monkeypatch):
    def _fake(symbol):
        if symbol == "封涨停板":
            raise RuntimeError("network")
        return []
    monkeypatch.setattr(ic, "_fetch_one", _fake)
    data = ic.build_intraday_changes(DAY)
    assert data["counts"]["封涨停板"] is None
    assert "error" in data["types"]["封涨停板"]
    assert data["counts"]["大笔买入"] == 0  # 其余正常


def test_save_roundtrip(fake_ak, tmp_path):
    data = ic.build_intraday_changes(DAY)
    path = ic.save_intraday_changes(data, tmp_path, DAY)
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert path.name == "20260812.json"
    assert saved["counts"]["封涨停板"] == 2


def test_load_intraday_changes_pack_block(fake_ak, tmp_path):
    """盲判包 block：counts + highlights（关键类型、解析 pct、封顶）。"""
    data = ic.build_intraday_changes(DAY)
    ic.save_intraday_changes(data, tmp_path, DAY)
    block = _load_intraday_changes("2026-08-12", tmp_path)
    assert block["date"] == "2026-08-12"
    assert block["counts"]["封涨停板"] == 2
    assert block["total"] == 3
    # highlights 抽取封涨停板（在 _IC_KEY_TYPES 首位）与大笔买入
    types_in_hl = {h["type"] for h in block["highlights"]}
    assert "封涨停板" in types_in_hl and "大笔买入" in types_in_hl
    # pct 从相关信息末段解析
    zt = next(h for h in block["highlights"] if h["type"] == "封涨停板")
    assert zt["code"] == "600721" and zt["pct"] == "0.100392"


def test_load_intraday_changes_missing(tmp_path):
    assert _load_intraday_changes("2026-08-12", tmp_path) is None
