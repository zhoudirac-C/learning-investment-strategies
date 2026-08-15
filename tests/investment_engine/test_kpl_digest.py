"""KPL 资讯初调层测试。"""
import json
import tempfile
from pathlib import Path

from investment_engine.kpl.digest import (
    match_articles, render_digest, run,
)


def _item(i, title, fetched=True, stocks=None):
    return {"id": i, "title": title, "create_time": 1, "msg_type": 9,
            "stocks": stocks or [], "img_list": [], "fetched": fetched}


class TestMatch:
    def test_title_keyword_and_stock_name(self):
        items = [_item(1, "PCB产业链深度拆解：上游材料持续涨价"),
                 _item(2, "大盘每日复盘"),
                 _item(3, "深南电路获大客户定点", fetched=False)]
        hits = match_articles(items, ["产业链", "涨价", "深南电路"])
        assert [h["id"] for h in hits] == [1, 3]
        assert "产业链" in hits[0]["matched"] and "涨价" in hits[0]["matched"]
        assert hits[1]["fetched"] is False  # 付费条目作为线索保留

    def test_empty_keywords(self):
        assert match_articles([_item(1, "任意标题")], []) == []


class TestRun:
    def test_digest_written(self):
        root = Path(tempfile.mkdtemp(prefix="kplnews_"))
        (root / "news" / "2026-08-14").mkdir(parents=True)
        (root / "news" / "2026-08-14" / "index.json").write_text(json.dumps([
            _item(1, "MLCC产业链涨价梳理"),
            _item(2, "涨停板复盘"),
        ]), encoding="utf-8")
        digest_root = root / "digest"
        out = run("2026-08-14", news_root=root / "news", digest_root=digest_root,
                  stock_pool=Path("/nonexistent.yaml"))
        text = out.read_text(encoding="utf-8")
        assert "命中 1 条" in text and "MLCC产业链涨价梳理" in text
        assert "涨停板复盘" not in text.split("命中")[1].split("## 全文可读")[1]

    def test_no_news_returns_none(self):
        root = Path(tempfile.mkdtemp(prefix="kplnews_"))
        assert run("2026-08-14", news_root=root, digest_root=root,
                   stock_pool=Path("/nonexistent.yaml")) is None
