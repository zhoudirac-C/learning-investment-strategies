"""业绩预告催化块测试 — 提案 2026-10-13-pattern-nomination-earnings-catalyst-test。

UP 业绩检验框架（011-l/004-h/001-h）：业绩预告落地后的价格反应是板块转折
观察信号。pack 注入 `earnings_catalysts` 块 = 近 3 日公告中的业绩预告/快报清单。
"""
from __future__ import annotations

import json

from investment_engine.blindtest.dataset import _load_earnings_catalysts


def _write_notices(root, date, items):
    d = root / "notices"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{date}.json").write_text(json.dumps(items, ensure_ascii=False))


class TestEarningsCatalysts:
    def test_filters_forecast_and_flash_report(self, tmp_path):
        _write_notices(tmp_path, "2026-10-12", [
            {"code": "688498", "name": "源杰科技", "title": "源杰科技:2026年前三季度业绩预告"},
            {"code": "600664", "name": "哈药股份", "title": "哈药股份:关于回购股份的公告"},
            {"code": "300623", "name": "捷捷微电", "title": "捷捷微电:2026年前三季度业绩快报"},
        ])
        r = _load_earnings_catalysts("2026-10-12", research_root=tmp_path)
        assert len(r) == 2
        assert {x["code"] for x in r} == {"688498", "300623"}

    def test_excludes_false_positive_yuji(self, tmp_path):
        """「预计」类非业绩公告不得命中（关联交易预计/募集资金预计等）。"""
        _write_notices(tmp_path, "2026-10-12", [
            {"code": "301587", "name": "中瑞股份", "title": "中瑞股份:关于增加2026年度日常关联交易预计的公告"},
            {"code": "000001", "name": "平安银行", "title": "平安银行:2026年前三季度业绩预告"},
        ])
        r = _load_earnings_catalysts("2026-10-12", research_root=tmp_path)
        assert [x["code"] for x in r] == ["000001"]

    def test_replay_safety_excludes_future(self, tmp_path):
        _write_notices(tmp_path, "2026-10-12", [
            {"code": "600001", "name": "A", "title": "A:2026年前三季度业绩预告"}])
        _write_notices(tmp_path, "2026-10-13", [
            {"code": "600002", "name": "B", "title": "B:2026年前三季度业绩预告"}])
        r = _load_earnings_catalysts("2026-10-12", research_root=tmp_path)
        assert [x["code"] for x in r] == ["600001"]

    def test_lookback_window_3_days(self, tmp_path):
        _write_notices(tmp_path, "2026-10-09", [
            {"code": "600003", "name": "C", "title": "C:2026年前三季度业绩预告"}])
        _write_notices(tmp_path, "2026-10-05", [
            {"code": "600004", "name": "D", "title": "D:2026年前三季度业绩预告"}])
        r = _load_earnings_catalysts("2026-10-12", research_root=tmp_path)
        codes = {x["code"] for x in r}
        assert "600003" in codes
        assert "600004" not in codes  # 超出回看窗口

    def test_none_when_empty(self, tmp_path):
        _write_notices(tmp_path, "2026-10-12", [
            {"code": "600664", "name": "哈药股份", "title": "哈药股份:分红公告"}])
        assert _load_earnings_catalysts("2026-10-12", research_root=tmp_path) is None

    def test_cap_20(self, tmp_path):
        items = [{"code": f"6000{i:02d}", "name": f"X{i}",
                  "title": f"X{i}:2026年前三季度业绩预告"} for i in range(25)]
        _write_notices(tmp_path, "2026-10-12", items)
        r = _load_earnings_catalysts("2026-10-12", research_root=tmp_path)
        assert len(r) == 20
