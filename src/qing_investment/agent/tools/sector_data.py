from __future__ import annotations

import json
import logging
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal


logger = logging.getLogger(__name__)


class SectorDataUnavailableError(Exception):
    """Raised when all sector data providers fail.

    Callers must stop and surface this instead of letting the LLM hallucinate
    sector analysis from stale or missing data.
    """


# Eastmoney API templates
_EASTMONEY_CONCEPT_URL = (
    "https://push2.eastmoney.com/api/qt/clist/get"
    "?pn=1&pz={top_n}&po=1&np=1&fltt=2&invt=2&fid=f3"
    "&fs=m:90+t:3+f:!50"
    "&fields=f12,f14,f2,f3,f4,f5,f6,f15,f16,f17,f18"
)
_EASTMONEY_INDUSTRY_URL = (
    "https://push2.eastmoney.com/api/qt/clist/get"
    "?pn=1&pz={top_n}&po=1&np=1&fltt=2&invt=2&fid=f3"
    "&fs=m:90+t:2+f:!50"
    "&fields=f12,f14,f2,f3,f4,f5,f6,f15,f16,f17,f18"
)

# Sina API templates
_SINA_BOARD_URL = {
    "concept": "http://money.finance.sina.com.cn/q/view/newFLJK.php?param=class",
    "industry": "http://money.finance.sina.com.cn/q/view/newFLJK.php?param=industry",
}

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://quote.eastmoney.com/",
    "Accept": "application/json, text/plain, */*",
}

_SINA_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://finance.sina.com.cn/",
    "Accept": "*/*",
}


# ---------------------------------------------------------------------------
# 本地缓存：20 分钟 TTL，失败时可回退到过期缓存
# ---------------------------------------------------------------------------
_SECTOR_CACHE_TTL_SECONDS = 20 * 60
_SECTOR_CACHE_DIR = Path.home() / ".kimi-code-im-bot" / "cache"
_SECTOR_CACHE_PATH = _SECTOR_CACHE_DIR / "sector_boards.json"


class _SectorDataCache:
    """文件缓存板块数据，TTL 20 分钟，失败时允许使用过期数据。"""

    def __init__(self, path: Path = _SECTOR_CACHE_PATH, ttl: int = _SECTOR_CACHE_TTL_SECONDS):
        self.path = path
        self.ttl = ttl
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning("[SectorDataCache] load failed: %s", e)
            return {}

    def _save(self, data: dict[str, Any]) -> None:
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, default=str)
        except Exception as e:
            logger.warning("[SectorDataCache] save failed: %s", e)

    def get(self, board_type: str) -> tuple[list[dict] | None, str | None, bool]:
        """返回 (items, provider, is_fresh)。无缓存或解析失败返回 (None, None, False)。"""
        data = self._load()
        entry = data.get(board_type)
        if not entry:
            return None, None, False
        ts = entry.get("timestamp")
        if not ts:
            return None, None, False
        try:
            cached_at = datetime.fromisoformat(ts)
        except Exception:
            return None, None, False
        age = (datetime.now(timezone.utc) - cached_at).total_seconds()
        is_fresh = age < self.ttl
        items = entry.get("items")
        provider = entry.get("provider")
        if not isinstance(items, list) or not items:
            return None, None, False
        freshness = "fresh" if is_fresh else f"stale({age/60:.0f}min)"
        logger.info("[SectorDataCache] %s hit: %d items, provider=%s, %s", board_type, len(items), provider, freshness)
        return items, provider, is_fresh

    def set(self, board_type: str, items: list[dict], provider: str) -> None:
        data = self._load()
        data[board_type] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "items": items,
            "provider": provider,
        }
        self._save(data)


@dataclass(frozen=True, slots=True)
class SectorBoardItem:
    code: str
    name: str
    pct_change: float | None
    latest: float | None
    amount: float | None
    rank: int
    board_type: Literal["concept", "industry"]


def _to_float(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    text = str(value).strip()
    if not text or text in {"-", "--"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _request_with_retry(
    url: str,
    headers: dict[str, str],
    *,
    retries: int = 3,
    timeout: int = 15,
) -> bytes:
    """Fetch URL with exponential backoff; raises on final failure."""
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = resp.read()
                logger.info("[sector_data] %s attempt=%d OK bytes=%d", url.split('?')[0], attempt + 1, len(data))
                return data
        except urllib.error.HTTPError as e:
            logger.warning("[sector_data] %s attempt=%d HTTPError %s", url.split('?')[0], attempt + 1, e)
            if e.code >= 500 or e.code == 429:
                last_error = e
                time.sleep(2**attempt)
                continue
            raise
        except Exception as e:
            logger.warning("[sector_data] %s attempt=%d error %s", url.split('?')[0], attempt + 1, e)
            last_error = e
            time.sleep(2**attempt)
            continue
    raise last_error or urllib.error.URLError("Unknown failure after retries")


# ---------------------------------------------------------------------------
# Eastmoney provider
# ---------------------------------------------------------------------------

def _parse_eastmoney_board_response(
    raw: bytes,
    board_type: Literal["concept", "industry"],
) -> list[SectorBoardItem]:
    if not raw:
        return []
    try:
        payload = json.loads(raw.decode("utf-8", errors="ignore"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return []

    data = payload.get("data") or {}
    diff = data.get("diff") or []
    if not isinstance(diff, list):
        return []

    results: list[SectorBoardItem] = []
    for idx, row in enumerate(diff, start=1):
        if not isinstance(row, dict):
            continue
        results.append(
            SectorBoardItem(
                code=str(row.get("f12", "")),
                name=str(row.get("f14", "")),
                pct_change=_to_float(row.get("f3")),
                latest=_to_float(row.get("f2")),
                amount=_to_float(row.get("f6")),
                rank=idx,
                board_type=board_type,
            )
        )
    return results


def fetch_eastmoney_boards(
    board_type: Literal["concept", "industry"] = "concept",
    top_n: int = 30,
    *,
    retries: int = 3,
    timeout: int = 15,
) -> list[SectorBoardItem]:
    """Fetch Eastmoney sector board ranking.

    Raises urllib.error.URLError on persistent failure so the caller can
    fall back to the next provider.
    """
    url_template = _EASTMONEY_CONCEPT_URL if board_type == "concept" else _EASTMONEY_INDUSTRY_URL
    url = url_template.format(top_n=max(1, min(top_n, 500)))
    raw = _request_with_retry(url, _HEADERS, retries=retries, timeout=timeout)
    items = _parse_eastmoney_board_response(raw, board_type)
    if not items:
        raise urllib.error.URLError(f"Eastmoney returned empty board list for {board_type}")
    return items


# ---------------------------------------------------------------------------
# Sina provider
# ---------------------------------------------------------------------------

_SINA_JS_RE = re.compile(r"var\s+S_Finance_bankuai_\w+\s*=\s*(\{.+\});?\s*$")


def _parse_sina_board_response(
    raw: bytes,
    board_type: Literal["concept", "industry"],
) -> list[SectorBoardItem]:
    if not raw:
        return []
    try:
        text = raw.decode("gbk", errors="ignore")
    except UnicodeDecodeError:
        text = raw.decode("utf-8", errors="ignore")

    m = _SINA_JS_RE.search(text.strip())
    if not m:
        return []

    try:
        payload = json.loads(m.group(1))
    except json.JSONDecodeError:
        return []

    results: list[SectorBoardItem] = []
    for idx, (key, value) in enumerate(payload.items(), start=1):
        if not isinstance(value, str):
            continue
        parts = value.split(",")
        if len(parts) < 7:
            continue
        # parts layout: code, name, count, avg_price, change, pct_change, turnover, amount, leader_code, ...
        results.append(
            SectorBoardItem(
                code=parts[0],
                name=parts[1],
                pct_change=_to_float(parts[5]),
                latest=_to_float(parts[3]),
                amount=_to_float(parts[7]),
                rank=idx,
                board_type=board_type,
            )
        )
    return results


def fetch_sina_boards(
    board_type: Literal["concept", "industry"] = "concept",
    top_n: int = 30,
    *,
    retries: int = 3,
    timeout: int = 15,
) -> list[SectorBoardItem]:
    """Fetch Sina sector board data, sort by pct_change, and return top_n."""
    url = _SINA_BOARD_URL[board_type]
    raw = _request_with_retry(url, _SINA_HEADERS, retries=retries, timeout=timeout)
    items = _parse_sina_board_response(raw, board_type)
    if not items:
        raise urllib.error.URLError(f"Sina returned empty board list for {board_type}")

    valid = [i for i in items if i.pct_change is not None]
    ranked = sorted(valid, key=lambda x: x.pct_change or 0, reverse=True)
    results: list[SectorBoardItem] = []
    for idx, item in enumerate(ranked, start=1):
        if idx > top_n:
            break
        results.append(
            SectorBoardItem(
                code=item.code,
                name=item.name,
                pct_change=item.pct_change,
                latest=item.latest,
                amount=item.amount,
                rank=idx,
                board_type=item.board_type,
            )
        )
    return results


# ---------------------------------------------------------------------------
# 同花顺板块数据（akshare 封装）
# ---------------------------------------------------------------------------

def fetch_ths_change_boards(
    board_type: Literal["concept", "industry"] = "concept",
    top_n: int = 30,
    *,
    retries: int = 2,
    timeout: int = 30,
) -> list[SectorBoardItem]:
    """通过 akshare 获取同花顺/东财混合板块异动排行（含概念+行业）。

    作为 eastmoney/sina 都失败时的兜底，数据包含真实板块涨跌幅，
    如 存储芯片、半导体概念、机器人概念 等。
    """
    import akshare as ak

    logger.info("[sector_data] fetching ths change boards for %s", board_type)
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            df = ak.stock_board_change_em()
            if df is None or df.empty:
                raise urllib.error.URLError("ths returned empty dataframe")
            # 字段：板块名称, 涨跌幅, 主力净流入, ...
            items: list[SectorBoardItem] = []
            for idx, row in df.iterrows():
                name = str(row.get("板块名称", ""))
                pct = _to_float(row.get("涨跌幅"))
                if not name or pct is None:
                    continue
                items.append(
                    SectorBoardItem(
                        code="",
                        name=name,
                        pct_change=pct,
                        latest=None,
                        amount=None,
                        rank=int(idx) + 1,
                        board_type=board_type,
                    )
                )
            ranked = sorted(items, key=lambda x: x.pct_change or 0, reverse=True)
            if not ranked:
                raise urllib.error.URLError("ths returned no valid board items")
            return ranked[:top_n]
        except Exception as e:
            last_error = e
            logger.warning("[sector_data] ths attempt=%d failed: %s", attempt + 1, e)
            if attempt < retries - 1:
                time.sleep(2**attempt)
    raise last_error or urllib.error.URLError("ths fetch failed")


# ---------------------------------------------------------------------------
# Unified fetch with cascading fallback
# ---------------------------------------------------------------------------

_sector_cache = _SectorDataCache()


def _items_to_dicts(items: list[SectorBoardItem]) -> list[dict]:
    return [
        {
            "code": i.code,
            "name": i.name,
            "pct_change": i.pct_change,
            "latest": i.latest,
            "amount": i.amount,
            "rank": i.rank,
            "board_type": i.board_type,
        }
        for i in items
    ]


def _dicts_to_items(dicts: list[dict], board_type: Literal["concept", "industry"]) -> list[SectorBoardItem]:
    return [
        SectorBoardItem(
            code=d.get("code", ""),
            name=d.get("name", ""),
            pct_change=_to_float(d.get("pct_change")),
            latest=_to_float(d.get("latest")),
            amount=_to_float(d.get("amount")),
            rank=int(d.get("rank", idx + 1)),
            board_type=board_type,
        )
        for idx, d in enumerate(dicts)
    ]


def _fetch_with_fallback(
    board_type: Literal["concept", "industry"],
    top_n: int,
    *,
    retries: int = 3,
    timeout: int = 15,
) -> tuple[list[SectorBoardItem], str]:
    """Try providers in order; return (items, provider_name).

    优先读 20 分钟缓存；所有 provider 失败时回退到过期缓存。
    Raises SectorDataUnavailableError if every provider fails and no cache.
    """
    # 1. 检查缓存
    cached_items, cached_provider, is_fresh = _sector_cache.get(board_type)
    if cached_items and is_fresh:
        return _dicts_to_items(cached_items, board_type)[:top_n], f"{cached_provider}_cache"

    # 2. 按优先级拉取
    providers: list[tuple[str, callable]] = [
        ("eastmoney", fetch_eastmoney_boards),
        ("sina", fetch_sina_boards),
        ("ths_change", fetch_ths_change_boards),
    ]
    last_exception: Exception | None = None
    for provider_name, fn in providers:
        try:
            items = fn(board_type, top_n, retries=retries, timeout=timeout)
            if items:
                _sector_cache.set(board_type, _items_to_dicts(items), provider_name)
                logger.info("[sector_data] %s fetched from %s, items=%d", board_type, provider_name, len(items))
                return items[:top_n], provider_name
        except Exception as e:
            logger.warning("[sector_data] provider %s failed for %s: %s", provider_name, board_type, e)
            last_exception = e
            continue

    # 3. 所有 provider 失败，回退到过期缓存
    if cached_items:
        logger.warning("[sector_data] all providers failed for %s, using stale cache", board_type)
        return _dicts_to_items(cached_items, board_type)[:top_n], f"{cached_provider}_stale"

    raise SectorDataUnavailableError(
        f"All sector data providers failed for {board_type}. "
        f"Last error: {last_exception}"
    ) from last_exception


def fetch_all_sector_boards(
    top_n: int = 30,
    *,
    retries: int = 3,
    timeout: int = 15,
) -> dict[str, dict]:
    """Fetch concept + industry boards with cascading provider fallback.

    Returns {"concept": {"items": [...], "provider": "..."}, ...}.
    Raises SectorDataUnavailableError if a board type cannot be loaded.
    """
    concept_items, concept_provider = _fetch_with_fallback(
        "concept", top_n, retries=retries, timeout=timeout
    )
    industry_items, industry_provider = _fetch_with_fallback(
        "industry", top_n, retries=retries, timeout=timeout
    )
    return {
        "concept": {"items": concept_items, "provider": concept_provider},
        "industry": {"items": industry_items, "provider": industry_provider},
    }


# ---------------------------------------------------------------------------
# Agent-facing formatting
# ---------------------------------------------------------------------------

def boards_to_agent_format(
    boards: dict[str, dict],
    *,
    max_leaders: int = 15,
    max_laggards: int = 10,
) -> dict[str, dict]:
    """Convert raw board data into a stable agent-facing payload."""

    def _item_dict(item: SectorBoardItem) -> dict:
        return {
            "code": item.code,
            "name": item.name,
            "pct_change": item.pct_change,
            "latest": item.latest,
            "amount": item.amount,
            "rank": item.rank,
        }

    out: dict[str, dict] = {"available": True}
    for board_type in ("concept", "industry"):
        bundle = boards.get(board_type) or {}
        items = bundle.get("items", [])
        provider = bundle.get("provider", "unknown")
        valid = [i for i in items if i.pct_change is not None]
        leaders = sorted(valid, key=lambda x: (x.pct_change or 0), reverse=True)[:max_leaders]
        laggards = sorted(valid, key=lambda x: (x.pct_change or 0))[:max_laggards]
        out[board_type] = {
            "leaders": [_item_dict(i) for i in leaders],
            "laggards": [_item_dict(i) for i in laggards],
            "count": len(items),
            "source": provider,
        }
    return out


def get_sector_strength_snapshot(
    top_n: int = 30,
    *,
    retries: int = 3,
    timeout: int = 15,
) -> dict[str, dict]:
    """High-level helper: fetch + format with cascading fallback.

    Raises SectorDataUnavailableError on total failure so callers can halt
    instead of hallucinating analysis.
    """
    boards = fetch_all_sector_boards(top_n=top_n, retries=retries, timeout=timeout)
    return boards_to_agent_format(boards)
