"""亚洲盘前外部市场数据聚合。

为 09:00 pre_market 节点提供：
- 美股隔夜指数与核心科技股
- 日韩开盘后指数
- A50/期货/美元指数/美债等

每个数据源独立超时，失败记录到 errors，不阻塞其他源。
"""

from __future__ import annotations

import asyncio
import json
import logging
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 5.0


def _http_get(url: str, timeout: float = _DEFAULT_TIMEOUT, encoding: str = "utf-8") -> str:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
    }
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode(encoding, errors="ignore")


def _parse_tencent_quote_line(line: str) -> dict[str, Any] | None:
    """解析腾讯行情返回的单行 v_xxx=\"...\";"""
    line = line.strip()
    if not line or "=" not in line:
        return None
    var, val = line.split("=", 1)
    val = val.strip('";')
    parts = val.split("~")
    if len(parts) < 35:
        return None
    try:
        return {
            "code": parts[2],
            "name": parts[1],
            "price": float(parts[3]) if parts[3] else None,
            "prev_close": float(parts[4]) if parts[4] else None,
            "open": float(parts[5]) if parts[5] else None,
            "high": float(parts[33]) if parts[33] else None,
            "low": float(parts[34]) if parts[34] else None,
            "pct_change": float(parts[32]) if parts[32] else None,
        }
    except (ValueError, IndexError):
        return None


# ── 美股 ──
def _fetch_us_overnight() -> dict[str, Any]:
    """美股隔夜：指数用东方财富全球指数，个股用腾讯行情。"""
    result: dict[str, Any] = {"indices": {}, "semi_index": None, "tech_stocks": {}, "news_summary": ""}
    errors: list[str] = []

    # 1) 全球指数
    try:
        import akshare as ak

        df = ak.index_global_spot_em()
        # 列名通常包含 "名称", "最新价", "涨跌幅"
        name_col = "名称"
        price_col = "最新价"
        pct_col = "涨跌幅"
        if name_col in df.columns and price_col in df.columns and pct_col in df.columns:
            mapping = {
                "纳斯达克": "nasdaq",
                "道琼斯": "dow",
                "标普500": "sp500",
                "费城半导体": "sox",
            }
            for _, row in df.iterrows():
                name = str(row[name_col]).strip()
                for cn, en in mapping.items():
                    if cn in name:
                        result["indices"][en] = {
                            "name": name,
                            "price": row[price_col],
                            "pct_change": row[pct_col],
                        }
                        if en == "sox":
                            result["semi_index"] = result["indices"][en]
                        break
    except Exception as e:
        errors.append(f"全球指数: {e}")

    # 2) 核心科技股（腾讯行情）
    try:
        # usIXIC=纳斯达克指数, usSOX=费城半导体, NVDA, MU
        url = "https://qt.gtimg.cn/q=usIXIC,usSOX,NVDA,MU"
        data = _http_get(url, encoding="gbk")
        for line in data.split(";"):
            q = _parse_tencent_quote_line(line)
            if not q:
                continue
            code = q["code"]
            if code == ".IXIC":
                result["indices"].setdefault("nasdaq", q)
            elif code == ".SOX":
                result["semi_index"] = q
                result["indices"].setdefault("sox", q)
            elif code in ("NVDA",):
                result["tech_stocks"]["nvda"] = q
            elif code in ("MU",):
                result["tech_stocks"]["mu"] = q
    except Exception as e:
        errors.append(f"美股科技股: {e}")

    if errors:
        result["errors"] = errors
    return result


# ── 日韩 ──
def _fetch_asia_first_hour() -> dict[str, Any]:
    """日韩开盘后 1 小时：指数为主，个股受数据源限制可能缺失。"""
    result: dict[str, Any] = {"indices": {}, "tech_stocks": {}, "feedback": ""}
    errors: list[str] = []

    try:
        import akshare as ak

        df = ak.index_global_spot_em()
        name_col = "名称"
        price_col = "最新价"
        pct_col = "涨跌幅"
        mapping = {
            "韩国KOSPI": "kospi",
            "日经225": "nikkei",
        }
        for _, row in df.iterrows():
            name = str(row[name_col]).strip()
            for cn, en in mapping.items():
                if cn in name:
                    result["indices"][en] = {
                        "name": name,
                        "price": row[price_col],
                        "pct_change": row[pct_col],
                    }
                    break
    except Exception as e:
        errors.append(f"日韩指数: {e}")

    # 日韩个股暂无稳定免费接口，标记为不可用
    result["tech_stocks"] = {
        "samsung": None,
        "sk_hynix": None,
        "tokyo_electron": None,
        "softbank": None,
        "note": "日韩个股暂无稳定免费数据源",
    }

    if errors:
        result["errors"] = errors
    return result


# ── 期货与地缘 ──
def _fetch_futures_geopolitics() -> dict[str, Any]:
    """A50、原油、黄金、美元指数、10Y 美债。"""
    result: dict[str, Any] = {
        "a50": None,
        "crude": None,
        "gold": None,
        "dxy": None,
        "us10y": None,
        "risks": [],
    }
    errors: list[str] = []

    # A50 期货（东方财富全球指数 / 股指期货）
    try:
        import akshare as ak

        df = ak.index_global_spot_em()
        name_col = "名称"
        price_col = "最新价"
        pct_col = "涨跌幅"
        for _, row in df.iterrows():
            name = str(row[name_col]).strip()
            if "A50" in name or "富时中国A50" in name:
                result["a50"] = {"name": name, "price": row[price_col], "pct_change": row[pct_col]}
                break
    except Exception as e:
        errors.append(f"A50: {e}")

    # 外盘期货（原油、黄金）
    try:
        import akshare as ak

        df = ak.futures_foreign_commodity_realtime()
        name_col = "商品名称" if "商品名称" in df.columns else "名称"
        price_col = "最新价" if "最新价" in df.columns else "现价"
        pct_col = "涨跌幅"
        for _, row in df.iterrows():
            name = str(row[name_col]).strip()
            item = {"name": name, "price": row.get(price_col), "pct_change": row.get(pct_col)}
            if "原油" in name and result["crude"] is None:
                result["crude"] = item
            elif "黄金" in name and result["gold"] is None:
                result["gold"] = item
    except Exception as e:
        errors.append(f"外盘期货: {e}")

    # 美元指数 / 美债（akshare 外汇接口）
    try:
        import akshare as ak

        df = ak.fx_spot_quote()
        if "商品名称" in df.columns and "最新价" in df.columns:
            for _, row in df.iterrows():
                name = str(row["商品名称"]).strip()
                if "美元指数" in name:
                    result["dxy"] = {"name": name, "price": row["最新价"], "pct_change": row.get("涨跌幅")}
                    break
    except Exception as e:
        errors.append(f"外汇: {e}")

    result["us10y"] = {"note": "10Y 美债收益率暂无稳定免费数据源"}
    result["risks"] = errors or ["地缘/政策风险需人工补充"]
    return result


async def fetch_pre_market_brief() -> dict[str, Any]:
    """聚合亚洲盘前信息。

    每个数据源独立在 5 秒内完成，失败不阻塞其他源。
    """
    loop = asyncio.get_event_loop()

    async def _run(fn):
        try:
            return await asyncio.wait_for(loop.run_in_executor(None, fn), timeout=_DEFAULT_TIMEOUT)
        except asyncio.TimeoutError:
            return {"error": "timeout"}
        except Exception as e:
            return {"error": str(e)}

    us_task = _run(_fetch_us_overnight)
    asia_task = _run(_fetch_asia_first_hour)
    futures_task = _run(_fetch_futures_geopolitics)

    us_result, asia_result, futures_result = await asyncio.gather(us_task, asia_task, futures_task)

    available = not (
        (isinstance(us_result, dict) and us_result.get("error"))
        and (isinstance(asia_result, dict) and asia_result.get("error"))
        and (isinstance(futures_result, dict) and futures_result.get("error"))
    )

    core_assumption = ""
    if isinstance(us_result, dict) and not us_result.get("error"):
        nasdaq = us_result.get("indices", {}).get("nasdaq", {})
        pct = nasdaq.get("pct_change")
        if pct is not None:
            direction = "涨" if float(pct) > 0 else "跌"
            core_assumption = f"隔夜美股{direction}，亚洲盘情绪受其带动，09:26重点观察A股高开/低开幅度与量能。"

    return {
        "available": available,
        "us_overnight": us_result,
        "asia_first_hour": asia_result,
        "futures_geopolitics": futures_result,
        "core_assumption": core_assumption or "外部数据不完整，核心假设需等待09:26竞价确认",
        "key_risks": [
            "隔夜美股波动",
            "A50 期指与汇率联动",
        ],
    }
