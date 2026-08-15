"""归因分类器测试（mock client）。"""
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from investment_engine.shadow.attribute import (
    KNOWN_DATA_GAPS, parse_attribution, run_attribution,
)


def _fake_client(payload: str):
    msg = SimpleNamespace(content=payload)
    choice = SimpleNamespace(message=msg)
    completions = SimpleNamespace(create=lambda **kw: SimpleNamespace(choices=[choice]))
    return SimpleNamespace(chat=SimpleNamespace(completions=completions))


ATTR_JSON = json.dumps({
    "types": ["数据缺"],
    "analysis": "缺少板块资金流，无法验证主线强度",
    "proposals": [{"type": "data-channel", "title": "补板块资金流通道",
                   "action": "调研东财板块资金流接口并接入缓存"}],
}, ensure_ascii=False)


class TestParseAttribution:
    def test_valid(self):
        a = parse_attribution(ATTR_JSON)
        assert a["types"] == ["数据缺"]
        assert a["proposals"][0]["type"] == "data-channel"

    def test_bad_type_rejected(self):
        bad = json.dumps({"types": ["运气差"], "analysis": "", "proposals": []})
        with pytest.raises(ValueError, match="types"):
            parse_attribution(bad)

    def test_garbage_rejected(self):
        with pytest.raises(ValueError):
            parse_attribution("不是json")


class TestRunAttribution:
    def setup_method(self):
        self.attr_dir = Path(tempfile.mkdtemp(prefix="attr_"))
        self.prop_dir = Path(tempfile.mkdtemp(prefix="prop_"))

    def teardown_method(self):
        import shutil
        shutil.rmtree(self.attr_dir, ignore_errors=True)
        shutil.rmtree(self.prop_dir, ignore_errors=True)

    def test_writes_attribution_and_proposal(self, monkeypatch):
        monkeypatch.setattr(
            "investment_engine.shadow.attribute.call_deepseek",
            lambda m, **kw: ATTR_JSON)
        pred = {"date": "2026-08-07",
                "result": {"market_stage": "震荡", "directions": [], "used_patterns": []},
                "stage_hit": False}
        rec = run_attribution(
            "2026-08-07", trigger="stage_miss", pred=pred, score_info={"truth": "调整"},
            attr_dir=self.attr_dir, proposal_dir=self.prop_dir)
        assert rec["triggers"] == ["stage_miss"]
        assert rec["types"] == ["数据缺"]
        assert len(rec["proposal_refs"]) == 1
        prop = Path(rec["proposal_refs"][0])
        text = prop.read_text(encoding="utf-8")
        assert "status: open" in text and "data-channel" in text

    def test_second_trigger_merges(self, monkeypatch):
        monkeypatch.setattr(
            "investment_engine.shadow.attribute.call_deepseek",
            lambda m, **kw: ATTR_JSON)
        pred = {"date": "2026-08-07",
                "result": {"market_stage": "震荡", "directions": [], "used_patterns": []},
                "stage_hit": False}
        run_attribution("2026-08-07", trigger="stage_miss", pred=pred,
                        score_info={}, attr_dir=self.attr_dir, proposal_dir=self.prop_dir)
        rec = run_attribution("2026-08-07", trigger="direction_miss", pred=pred,
                              score_info={}, attr_dir=self.attr_dir, proposal_dir=self.prop_dir)
        assert rec["triggers"] == ["stage_miss", "direction_miss"]

    def test_known_gaps_listed(self):
        assert "板块资金流" in KNOWN_DATA_GAPS


class TestSupersedeAttribution:
    def setup_method(self):
        self.attr_dir = Path(tempfile.mkdtemp(prefix="attr_"))
        self.prop_dir = Path(tempfile.mkdtemp(prefix="prop_"))

    def teardown_method(self):
        import shutil
        shutil.rmtree(self.attr_dir, ignore_errors=True)
        shutil.rmtree(self.prop_dir, ignore_errors=True)

    def _seed(self, day="2026-08-07", prop_status="status: open"):
        prop = self.prop_dir / f"{day}-data-channel-x.md"
        prop.write_text(f"---\ndate: {day}\ntype: data-channel\n{prop_status}\n---\n\n# t\n",
                        encoding="utf-8")
        rec = {"date": day, "triggers": ["stage_miss"], "types": ["数据缺"],
               "analysis": "a", "proposal_refs": [str(prop)]}
        (self.attr_dir / f"{day}.json").write_text(
            json.dumps(rec, ensure_ascii=False), encoding="utf-8")
        return prop

    def test_supersede_retracts_open_proposal(self):
        from investment_engine.shadow.attribute import supersede_attribution
        prop = self._seed()
        rec = supersede_attribution("2026-08-07", attr_dir=self.attr_dir,
                                    proposal_dir=self.prop_dir)
        assert rec["superseded"] is True
        assert rec["retracted_proposals"] == [prop.name]
        text = prop.read_text(encoding="utf-8")
        assert "status: retracted" in text and "status: open" not in text

    def test_supersede_keeps_applied_proposal(self):
        from investment_engine.shadow.attribute import supersede_attribution
        prop = self._seed(prop_status="status: applied")
        rec = supersede_attribution("2026-08-07", attr_dir=self.attr_dir,
                                    proposal_dir=self.prop_dir)
        assert rec["retracted_proposals"] == []
        assert "status: applied" in prop.read_text(encoding="utf-8")

    def test_supersede_idempotent_and_missing(self):
        from investment_engine.shadow.attribute import supersede_attribution
        self._seed()
        supersede_attribution("2026-08-07", attr_dir=self.attr_dir,
                              proposal_dir=self.prop_dir)
        assert supersede_attribution("2026-08-07", attr_dir=self.attr_dir,
                                     proposal_dir=self.prop_dir) is None
        assert supersede_attribution("2099-01-01", attr_dir=self.attr_dir,
                                     proposal_dir=self.prop_dir) is None

    def test_new_attribution_ignores_superseded_triggers(self, monkeypatch):
        from investment_engine.shadow.attribute import supersede_attribution
        monkeypatch.setattr(
            "investment_engine.shadow.attribute.call_deepseek",
            lambda m, **kw: ATTR_JSON)
        self._seed()
        supersede_attribution("2026-08-07", attr_dir=self.attr_dir,
                              proposal_dir=self.prop_dir)
        pred = {"date": "2026-08-07",
                "result": {"market_stage": "震荡", "directions": [], "used_patterns": []},
                "stage_hit": False}
        rec = run_attribution("2026-08-07", trigger="direction_miss", pred=pred,
                              score_info={}, attr_dir=self.attr_dir,
                              proposal_dir=self.prop_dir)
        assert rec["triggers"] == ["direction_miss"]  # 不合并 superseded 旧 trigger
