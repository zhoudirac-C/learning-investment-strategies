"""东财研报/公告管线测试（fake session，不触网）。"""
import json
import tempfile
from pathlib import Path

from investment_engine import research_feed
from investment_engine.research_feed import (
    fetch_reports_range, group_by_date, run_range,
)


def _row(info_code, title="t", qtype="0", date="2026-08-14", industry_code="459"):
    return {
        "infoCode": info_code, "title": title, "orgSName": "东吴证券",
        "publishDate": f"{date}T10:00:00", "indvInduCode": industry_code,
        "indvInduName": "元件", "stockCode": "002916", "stockName": "深南电路",
        "emRatingName": "买入", "attachPages": 20,
    }


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class _FakeSession:
    """按 pageNo 翻页返回预设页。"""

    def __init__(self, pages_by_qtype):
        self.pages_by_qtype = pages_by_qtype  # {qtype: [page1_rows, page2_rows]}
        self.calls = 0

    def get(self, url, params=None, timeout=None, headers=None):
        self.calls += 1
        qtype = params["qType"]
        page = int(params["pageNo"]) - 1
        pages = self.pages_by_qtype.get(qtype, [])
        rows = pages[page] if page < len(pages) else []
        return _FakeResp({"TotalPage": len(pages), "data": rows})


class TestFetchReportsRange:
    def test_pagination_and_dedupe(self):
        pages = {
            "0": [[_row("A1"), _row("A2")], [_row("A2"), _row("A3")]],  # A2 跨页重复
            "1": [[_row("B1", qtype="1")]],
            "2": [],
        }
        rows = fetch_reports_range("2026-08-01", "2026-08-15",
                                   session=_FakeSession(pages))
        codes = [r["info_code"] for r in rows]
        assert codes == ["A1", "A2", "A3", "B1"]
        r0 = rows[0]
        assert r0["pdf_url"].endswith("A1_1.pdf")
        assert r0["industry_name"] == "元件" and r0["qtype_name"] == "个股研报"
        assert r0["publish_date"] == "2026-08-14"

    def test_empty_window(self):
        rows = fetch_reports_range("2026-08-01", "2026-08-02",
                                   session=_FakeSession({}))
        assert rows == []


class TestGroupByDate:
    def test_groups_and_drops_dirty(self):
        rows = [{"publish_date": "2026-08-14"}, {"publish_date": "2026-08-14"},
                {"publish_date": ""}, {"publish_date": None}]
        g = group_by_date(rows)
        assert len(g["2026-08-14"]) == 2 and "" not in g


class TestRunRange:
    def setup_method(self):
        self.root = Path(tempfile.mkdtemp(prefix="research_"))

    def teardown_method(self):
        import shutil
        shutil.rmtree(self.root, ignore_errors=True)

    def _pages(self):
        return {"0": [[_row("A1", date="2026-08-13"), _row("A2", date="2026-08-14")]],
                "1": [], "2": []}

    def test_idempotent_skip_and_force(self, monkeypatch):
        monkeypatch.setattr(research_feed, "fetch_notices", lambda day: [])
        pages = self._pages
        s1 = run_range("2026-08-13", "2026-08-14", root=self.root,
                       session=_FakeSession(self._pages()))
        assert s1["reports"] == {"2026-08-13": 1, "2026-08-14": 1}
        s2 = run_range("2026-08-13", "2026-08-14", root=self.root,
                       session=_FakeSession(self._pages()))
        assert s2["reports"] == {} and sorted(s2["skipped"]) == ["2026-08-13", "2026-08-14"]
        s3 = run_range("2026-08-13", "2026-08-14", root=self.root, force=True,
                       session=_FakeSession(self._pages()))
        assert len(s3["reports"]) == 2

    def test_notices_saved(self, monkeypatch):
        monkeypatch.setattr(research_feed, "fetch_notices",
                            lambda day: [{"code": "002916", "title": "t", "date": day}])
        run_range("2026-08-14", "2026-08-14", root=self.root,
                  session=_FakeSession(self._pages()))
        n = json.loads((self.root / "notices" / "2026-08-14.json")
                       .read_text(encoding="utf-8"))
        assert n[0]["code"] == "002916"
