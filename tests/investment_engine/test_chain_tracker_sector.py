"""板块异动触发器测试（fund_flow 本地落盘 → 发现候选）。"""
import json
import tempfile
from pathlib import Path

from investment_engine.chain_tracker.sector import load_sector_anomalies


def _fund_flow() -> dict:
    return {
        "date": "2026-08-28",
        "industry": {"即时": [
            {"序号": 1, "行业": "种植业与林业", "行业-涨跌幅": 3.08,
             "净额": 2.16, "领涨股": "敦煌种业", "领涨股-涨跌幅": 10.02},
            {"序号": 2, "行业": "银行", "行业-涨跌幅": 0.42,
             "领涨股": "工商银行", "领涨股-涨跌幅": 0.6},
        ]},
        "concept": {"即时": [
            {"序号": 1, "行业": "供销社", "行业-涨跌幅": 3.06,
             "领涨股": "辉隆股份", "领涨股-涨跌幅": 9.97},
            {"序号": 2, "行业": "HJT电池", "行业-涨跌幅": -3.20,
             "领涨股": "迈为股份", "领涨股-涨跌幅": -8.1},
            {"序号": 3, "行业": "CPO", "行业-涨跌幅": 1.10,
             "领涨股": "中际旭创", "领涨股-涨跌幅": 2.0},
        ]},
    }


class TestSectorAnomalies:
    def test_threshold_filter_both_sections(self):
        d = Path(tempfile.mkdtemp(prefix="sector_test_"))
        (d / "20260828.json").write_text(json.dumps(_fund_flow(),
                                                  ensure_ascii=False),
                                         encoding="utf-8")
        items = load_sector_anomalies("2026-08-28", root=d)
        # 种植业3.08 / 供销社3.06 / HJT-3.20 过阈；银行0.42 / CPO1.10 滤掉
        assert len(items) == 3
        by_id = {i["info_id"]: i for i in items}
        assert "sector:2026-08-28:industry:种植业与林业" in by_id
        assert "sector:2026-08-28:concept:供销社" in by_id
        assert "sector:2026-08-28:concept:HJT电池" in by_id
        it = by_id["sector:2026-08-28:concept:供销社"]
        assert it["source"] == "sector"
        assert "供销社板块涨 3.1%" in it["title"]
        assert "辉隆股份" in it["title"]
        assert "HJT电池板块跌 3.2%" in by_id["sector:2026-08-28:concept:HJT电池"]["title"]

    def test_custom_threshold(self):
        d = Path(tempfile.mkdtemp(prefix="sector_test_"))
        (d / "20260828.json").write_text(json.dumps(_fund_flow(),
                                                  ensure_ascii=False),
                                         encoding="utf-8")
        assert len(load_sector_anomalies("2026-08-28", root=d,
                                         threshold_pct=5.0)) == 0

    def test_missing_file_returns_empty(self):
        d = Path(tempfile.mkdtemp(prefix="sector_test_"))
        assert load_sector_anomalies("2026-08-28", root=d) == []

    def test_broken_file_returns_empty(self):
        d = Path(tempfile.mkdtemp(prefix="sector_test_"))
        (d / "20260828.json").write_text("不是json", encoding="utf-8")
        assert load_sector_anomalies("2026-08-28", root=d) == []
