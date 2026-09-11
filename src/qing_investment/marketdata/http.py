"""统一 HTTP 层：UA/超时/重试/GBK 解码，全项目共用。

消灭 7 处重复 ``_http_get``（stock_data / update_index_klines_intraday /
fetchers / chan_engine fetch / stock_sector_mapper / external_market_fetcher /
pre_fetch_index_klines 各写一份、UA 与超时各异）。

经验内嵌：
- 完整浏览器 UA（urllib 默认 UA 被新浪限流——chan_engine skill 实证）
- GBK 解码支持（腾讯 qt.gtimg 是 GBK）
- 指数退避重试（2s/4s/6s，对齐 update_index_klines_intraday 既有行为）
"""

from __future__ import annotations

import json
import time
import urllib.request

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
DEFAULT_HEADERS = {
    "Accept": "*/*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "User-Agent": DEFAULT_UA,
    "Connection": "keep-alive",
}


class HttpError(RuntimeError):
    """HTTP 请求在全部重试后失败。"""


def http_get(
    url: str,
    *,
    headers: dict | None = None,
    timeout: float = 15.0,
    encoding: str = "utf-8",
    max_retries: int = 3,
) -> str:
    """GET 并返回解码文本。失败重试（指数退避），全败抛 HttpError。"""
    merged = dict(DEFAULT_HEADERS)
    if headers:
        merged.update(headers)
    last_err: Exception | None = None
    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(url, headers=merged)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode(encoding, errors="replace")
        except Exception as e:  # noqa: BLE001 — 网络错误五花八门，统一重试
            last_err = e
            if attempt + 1 < max_retries:
                time.sleep(2.0 * (attempt + 1))
    raise HttpError(f"GET {url[:120]} 失败（{max_retries} 次重试后）: {last_err}") from last_err


def http_get_json(url: str, *, headers: dict | None = None, timeout: float = 15.0,
                  encoding: str = "utf-8", max_retries: int = 3):
    """GET 并解析 JSON。"""
    return json.loads(http_get(url, headers=headers, timeout=timeout,
                               encoding=encoding, max_retries=max_retries))
