"""信息归一化：研报/公告/期货异动 → 统一 InfoItem。

InfoItem 字段：info_id / source / title / published_at / stock_code / stock_name /
industry_name / org / url / chain_ids（期货预分配，其他源为空）。

去重键规则（硬规则：用 info_id 不用标题）：
- 研报：东财 infoCode
- 公告：url 中的 AN id；缺失时 sha1(code|title|date) 兜底
- 期货：futures:{symbol}:{date}:{30min窗口}
"""
from __future__ import annotations

import hashlib
import re

_AN_RE = re.compile(r"(AN\d{6,})")


def normalize_report(r: dict) -> dict:
    return {
        "info_id": str(r.get("info_code") or "").strip(),
        "source": "report",
        "title": str(r.get("title") or "").strip(),
        "published_at": str(r.get("publish_date") or "")[:10],
        "stock_code": str(r.get("stock_code") or "").strip() or None,
        "stock_name": str(r.get("stock_name") or "").strip() or None,
        "industry_name": str(r.get("industry_name") or "").strip() or None,
        "org": str(r.get("org") or "").strip() or None,
        "url": str(r.get("pdf_url") or "").strip() or None,
        "chain_ids": [],
    }


def normalize_notice(n: dict) -> dict:
    url = str(n.get("url") or "")
    m = _AN_RE.search(url)
    if m:
        info_id = m.group(1)
    else:
        digest = hashlib.sha1(
            f"{n.get('code')}|{n.get('title')}|{n.get('date')}".encode("utf-8")
        ).hexdigest()[:16]
        info_id = f"notice:{digest}"
    return {
        "info_id": info_id,
        "source": "notice",
        "title": str(n.get("title") or "").strip(),
        "published_at": str(n.get("date") or "")[:10],
        "stock_code": str(n.get("code") or "").strip() or None,
        "stock_name": str(n.get("name") or "").strip() or None,
        "industry_name": None,
        "org": None,
        "url": url or None,
        "chain_ids": [],
    }


def make_futures_item(*, symbol: str, name: str, change_pct: float,
                      last: float, prev_settle: float, date: str, window: str,
                      chain_ids: list[str]) -> dict:
    direction = "涨" if change_pct >= 0 else "跌"
    return {
        "info_id": f"futures:{symbol}:{date}:{window}",
        "source": "futures",
        "title": (f"{name}主力连续({symbol})异动：{direction} {abs(change_pct):.1f}%"
                  f"（最新 {last}，昨结 {prev_settle}）"),
        "published_at": f"{date} {window}",
        "stock_code": None,
        "stock_name": None,
        "industry_name": None,
        "org": "新浪期货",
        "url": None,
        "chain_ids": list(chain_ids),
    }
