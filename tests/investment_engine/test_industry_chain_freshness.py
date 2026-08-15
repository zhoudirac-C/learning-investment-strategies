"""产业链保鲜巡检测试。"""
import tempfile
from datetime import date
from pathlib import Path

import yaml

from investment_engine.industry_chain.freshness import inspect_chains, render_report


def _seed(root: Path, cid: str, chain_lv: str, segments: list[dict],
          mappings: list[dict]) -> None:
    d = root / cid
    d.mkdir(parents=True)
    (d / "chain.yaml").write_text(yaml.safe_dump({
        "chain_id": cid, "name": f"{cid}链", "thesis": "t",
        "segments": segments, "mappings": mappings, "last_verified": chain_lv,
    }, allow_unicode=True), encoding="utf-8")


class TestInspect:
    def test_stale_and_never_verified(self):
        root = Path(tempfile.mkdtemp(prefix="chains_"))
        _seed(root, "a-chain", None,  # 链级无日期 → 空字段无兜底
              [{"id": "s1", "name": "新鲜环节", "last_verified": "2026-08-10"},
               {"id": "s2", "name": "过期环节", "last_verified": "2026-01-01"},
               {"id": "s3", "name": "未核实环节"}],
              [{"code": "002371", "name": "北方华创", "segment": "s1",
                "relation": "r", "elasticity": "core", "last_verified": "2026-08-15"}])
        chains = inspect_chains(root, today=date(2026, 8, 16), stale_days=90)
        stale = chains["a-chain"]["stale"]
        labels = {e["label"] for e in stale}
        assert "过期环节" in labels and "未核实环节" in labels
        assert "新鲜环节" not in labels and not any("北方华创" in l for l in labels)
        never = next(e for e in stale if e["label"] == "未核实环节")
        assert never["age_days"] is None
        old = next(e for e in stale if e["label"] == "过期环节")
        assert old["age_days"] > 90

    def test_inherits_chain_level_when_field_empty(self):
        root = Path(tempfile.mkdtemp(prefix="chains_"))
        _seed(root, "b-chain", "2026-08-10",  # 链级新鲜 → 空字段继承不过期
              [{"id": "s1", "name": "无日期环节"}], [])
        chains = inspect_chains(root, today=date(2026, 8, 16), stale_days=90)
        assert chains["b-chain"]["stale"] == []

    def test_empty_dir(self):
        assert inspect_chains(Path("/nonexistent")) == {}


class TestRender:
    def test_report_sections(self):
        root = Path(tempfile.mkdtemp(prefix="chains_"))
        _seed(root, "a-chain", "2026-01-01", [], [])
        text = render_report(inspect_chains(root, today=date(2026, 8, 16)))
        assert "保鲜巡检" in text and "a-chain链" in text
