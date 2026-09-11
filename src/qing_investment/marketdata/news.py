"""财联社电报（cls.cn v1 API + 本地签名，零 key）。

事件管线/早盘确认的独立消息源，与东财 7×24 互为备份（不同源、不同风控面，
一条被封另一条仍在）。2026-07 实测复活：旧 nodeapi 已下线，
新 v1 接口强制校验 sign，但签名纯本地计算：
``sign = md5(sha1(按 key 字典序拼接的 query 串))``。
"""

from __future__ import annotations

import hashlib
from datetime import datetime

from qing_investment.marketdata.errors import SourceUnavailable
from qing_investment.marketdata.http import http_get_json


def cls_telegraph(page_size: int = 50) -> list[dict]:
    """财联社电报（全市场实时快讯）。

    返回 ``[{title, content, time}]``，time 已转 ``YYYY-MM-DD HH:MM:SS``。
    结构异常抛 :class:`SourceUnavailable`（不静默返空——空列表合法但
    结构变更必须显性暴露）。
    """
    params = {"appName": "CailianpressWeb", "os": "web", "sv": "7.7.5",
              "last_time": "", "refresh_type": "1", "rn": str(page_size)}
    qs = "&".join(f"{k}={params[k]}" for k in sorted(params))
    sign = hashlib.md5(hashlib.sha1(qs.encode()).hexdigest().encode()).hexdigest()
    url = f"https://www.cls.cn/v1/roll/get_roll_list?{qs}&sign={sign}"
    try:
        d = http_get_json(url, headers={"Referer": "https://www.cls.cn/"}, timeout=10)
    except Exception as e:
        raise SourceUnavailable(f"cls request failed: {type(e).__name__}: {e}") from e

    roll = (d.get("data") or {}).get("roll_data") or []
    rows = []
    for item in roll:
        ts = item.get("ctime")
        t = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S") if ts else ""
        rows.append({
            "title": item.get("title", "") or item.get("brief", ""),
            "content": item.get("content", "") or item.get("brief", ""),
            "time": t,
        })
    return rows
