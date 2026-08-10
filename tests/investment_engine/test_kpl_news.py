"""kpl/news.py 单元测试（实样裁剪自抓包；时间戳动态构造避免时区陷阱）。"""

from __future__ import annotations

import json
from datetime import date, datetime

from investment_engine.kpl.client import KplError
from investment_engine.kpl.news import (
    fetch_day_news,
    fetch_list,
    html_to_text,
    save_news,
)

DAY = date(2026, 8, 10)


def _ts(d: date, hour: int) -> str:
    return str(int(datetime(d.year, d.month, d.day, hour).timestamp()))


def _list_payload(items):
    return {"MsgTop": {"List": items}, "errcode": "0"}


class _FakeClient:
    """按 (c, a) 分发：GetIndexList 返列表，ForumsMsgJX.GetInfo 返全文。"""

    def __init__(self, list_payload, full_by_id=None):
        self.list_payload = list_payload
        self.full_by_id = full_by_id or {}
        self.calls = []

    def post(self, subdomain, c, a, params=None):
        self.calls.append((subdomain, c, a, params))
        if a == "GetIndexList":
            return self.list_payload
        return {"Msg": self.full_by_id[params["MsgID"]], "errcode": "0"}


def test_html_to_text_strips_tags_and_collects_images():
    html = ('<p><strong>公司简介：</strong>宇树科技成立于2016年</p>'
            '<p><img src="https://appcdn.longhuvip.com/a.png" alt="image.png"/></p>'
            '<p>第二段</p>')
    text, images = html_to_text(html)
    assert "公司简介：宇树科技成立于2016年" in text
    assert "第二段" in text
    assert "<p>" not in text and "<strong>" not in text
    assert images == ["https://appcdn.longhuvip.com/a.png"]


def test_fetch_list_filters_by_day():
    items = [
        {"ID": "1", "Title": "当日", "CreateTime": _ts(DAY, 10)},
        {"ID": "2", "Title": "昨日", "CreateTime": _ts(date(2026, 8, 9), 10)},
        {"ID": "3", "Title": "无时间"},  # 缺 CreateTime 跳过
    ]
    client = _FakeClient(_list_payload(items))
    out = fetch_list(client, DAY)
    assert [i["ID"] for i in out] == ["1"]
    assert client.calls[0][:3] == ("apparticle", "IndexPlate", "GetIndexList")
    assert client.calls[0][3] == {"view": "1,2,3,4,6", "st": "2", "Type": "0"}


def test_fetch_day_news_pulls_full_text_per_item():
    items = [{"ID": "42", "Title": "t", "CreateTime": _ts(DAY, 9)},
             {"ID": "43", "Title": "t2", "CreateTime": _ts(DAY, 11)}]
    full = {"42": {"ID": 42, "Title": "t", "Content": "<p>a</p>"},
            "43": {"ID": 43, "Title": "t2", "Content": "<p>b</p>"}}
    client = _FakeClient(_list_payload(items), full)
    articles, skipped = fetch_day_news(client, DAY, pause=0)
    assert [a["ID"] for a in articles] == [42, 43]
    assert skipped == []
    # 列表 1 次 + 全文 2 次
    assert [c[2] for c in client.calls].count("GetInfo") == 2


def test_fetch_day_news_skips_failed_items():
    """单篇业务错误（如 1130 付费无权限）跳过继续；鉴权错误照常致命。"""

    class _FlakyClient(_FakeClient):
        def post(self, subdomain, c, a, params=None):
            if a == "GetInfo" and params["MsgID"] == "978808":
                raise KplError("业务错误 errcode=1130")
            return super().post(subdomain, c, a, params)

    items = [{"ID": "42", "Title": "t", "CreateTime": _ts(DAY, 9)},
             {"ID": "978808", "Title": "付费研报", "CreateTime": _ts(DAY, 10)}]
    full = {"42": {"ID": 42, "Title": "t", "Content": "<p>a</p>"}}
    articles, skipped = fetch_day_news(_FlakyClient(_list_payload(items), full),
                                       DAY, pause=0)
    assert [a["ID"] for a in articles] == [42]
    assert len(skipped) == 1
    assert skipped[0]["item"]["ID"] == "978808"
    assert "1130" in skipped[0]["error"]


def test_save_news_layout(tmp_path):
    articles = [{
        "ID": 42174, "Title": "新股分析：宇树科技、绿控传动",
        "CreateTime": 1786266426, "MsgType": 18, "Stock": [],
        "imgList": ["https://appcdn.longhuvip.com/x.jpg", ""],
        "Content": "<p><strong>新股亮点</strong></p><p>正文</p>",
    }]
    skipped = [{"item": {"ID": "978808", "Title": "付费研报",
                         "CreateTime": "1786320000", "MsgType": None,
                         "Stock": ["600519"],
                         "imgList": {"List": ["https://appcdn.longhuvip.com/y.jpg"]}},
                "error": "业务错误 errcode=1130"}]
    out_dir = save_news(articles, tmp_path, "2026-08-10", skipped=skipped)
    assert out_dir == tmp_path / "news" / "2026-08-10"
    index = json.loads((out_dir / "index.json").read_text())
    assert index[0]["id"] == 42174
    assert index[0]["fetched"] is True
    assert index[0]["img_list"] == ["https://appcdn.longhuvip.com/x.jpg"]  # 空串被过滤
    # skipped 条目进 index 但不生成 md
    assert index[1]["id"] == "978808"
    assert index[1]["fetched"] is False
    assert "1130" in index[1]["error"]
    assert index[1]["img_list"] == ["https://appcdn.longhuvip.com/y.jpg"]
    assert not (out_dir / "978808.md").exists()
    md = (out_dir / "42174.md").read_text()
    assert md.startswith("---\n")
    assert 'title: "新股分析：宇树科技、绿控传动"' in md
    assert "# 新股分析：宇树科技、绿控传动" in md
    assert "新股亮点" in md and "<strong>" not in md
