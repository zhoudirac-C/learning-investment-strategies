"""新浪源：分钟线（60m/30m，缠论引擎 M7-1 实证通道）+ 实时行情。

经验内嵌（chan_engine skill 实证纪律）：
- urllib 默认 UA 被新浪限流 → 必须完整浏览器 UA
- 分钟线窗口上限 datalen=260
- 空列表/异常响应视为限流特征 → 抛错触发降级（绝不静默当成功）
- 新浪分钟线字段序：day,open,high,low,close,volume（收盘在第 4 位，
  又与前两家不同——"字段序各厂商不同"三度验证）
- 复权因子 qfq/hfq（a-stock-data V3.7）：qfq 因子是除数、hfq 是乘数，
  方向传反不报错但数值差几倍；qfq 最新一条恒为 1.0 可自检
"""

from __future__ import annotations

from qing_investment.marketdata import ratelimit
from qing_investment.marketdata.errors import SourceUnavailable
from qing_investment.marketdata.http import http_get_json, http_get
from qing_investment.marketdata.symbol import norm_ticker, prefix_for

SOURCE = "sina"

#: 新浪分钟线窗口上限（M7-1 skill 实证）
SINA_DATALEN_MAX = 260

_HEADERS = {"Referer": "https://finance.sina.com.cn/"}


def sina_symbol(code: str, *, kind: str = "auto") -> str:
    """'sh512400' 原样；'512400'→'sh512400'。"""
    low = str(code).strip().lower()
    if low.startswith(("sh", "sz", "bj")) and len(low) >= 8:
        return low
    digits = norm_ticker(str(code).strip())
    return f"{prefix_for(digits, kind=kind)}{digits}"


def fetch_minute(code: str, tf: int, datalen: int = SINA_DATALEN_MAX) -> list[dict]:
    """新浪分钟线（30/60）。返回统一 bar shape（bar_time=分钟粒度），升序。

    空列表/异常响应抛 SourceUnavailable（限流特征，交 router 降级）。
    """
    if tf not in (30, 60):
        raise ValueError(f"新浪分钟线仅支持 30/60（收到 tf={tf}）")
    datalen = min(datalen, SINA_DATALEN_MAX)
    sym = sina_symbol(code)
    url = (
        "https://quotes.sina.cn/cn/api/json_v2.php/CN_MarketDataService.getKLineData"
        f"?symbol={sym}&scale={tf}&ma=no&datalen={datalen}"
    )
    ratelimit.acquire(SOURCE)
    try:
        raw = http_get_json(url, headers=_HEADERS, timeout=10)
    except Exception as e:
        raise SourceUnavailable(f"sina {tf}m request failed: {type(e).__name__}: {e}") from e
    if not isinstance(raw, list) or not raw or "close" not in (raw[0] or {}):
        raise SourceUnavailable(f"sina {tf}m abnormal response: {str(raw)[:80]}")
    bars = []
    for r in raw:
        bars.append({
            "bar_time": str(r.get("day"))[:16],
            "open": _f(r.get("open")), "high": _f(r.get("high")),
            "low": _f(r.get("low")), "close": _f(r.get("close")),
            "volume": _f(r.get("volume")), "amount": 0.0,
        })
    bars = [b for b in bars if b["bar_time"]]
    bars.sort(key=lambda k: k["bar_time"])
    return bars


def fetch_kline(code: str, klt: int, count: int, *, kind: str = "auto") -> list[dict]:
    """新浪 K线 router 适配：101→不支持（日线无复权意义），30/60 走 fetch_minute。"""
    if klt in (30, 60):
        return fetch_minute(code, klt, datalen=min(count + 2, SINA_DATALEN_MAX))
    raise ValueError(f"新浪源不支持 klt={klt}（仅 30/60 分钟线）")


def fetch_quotes(codes: list[str], *, kind: str = "auto") -> list[dict]:
    """新浪实时行情（hq.sinajs.cn，GBK；必须 Referer）。"""
    syms = []
    for c in codes:
        try:
            syms.append(sina_symbol(c, kind=kind))
        except ValueError:
            continue
    if not syms:
        return []
    url = "https://hq.sinajs.cn/list=" + ",".join(syms)
    ratelimit.acquire(SOURCE)
    text = http_get(url, headers=_HEADERS, encoding="gbk", timeout=10)
    quotes = []
    for line in text.strip().splitlines():
        if '"' not in line or "=" not in line:
            continue
        key = line.split("=")[0].split("_")[-1]
        vals = line.split('"')[1].split(",")
        if len(vals) < 32:
            continue
        try:
            quotes.append({
                "code": key.lstrip("shzbj"),
                "name": vals[0],
                # 新浪字段序：名称,今开,昨收,现价,最高,最低,...
                "open": float(vals[1] or 0),
                "prev_close": float(vals[2] or 0),
                "price": float(vals[3] or 0),
                "high": float(vals[4] or 0),
                "low": float(vals[5] or 0),
                "volume": float(vals[8] or 0),
                "amount": float(vals[9] or 0),
                # 涨跌幅新浪不直接给出（防误用不编造），由调用方按需自算：
                # (price - prev_close) / prev_close * 100
                "change_pct": None,
                "source": SOURCE,
            })
        except (ValueError, IndexError):
            continue
    return quotes


def adjust_factor(code: str, kind: str = "qfq") -> list[dict]:
    """新浪复权因子序列（qfq/hfq），按日期倒序（最新在前）。

    返回 ``[{"date": "YYYY-MM-DD", "factor": float}]``。
    自检口径：qfq 最新一条因子恒为 1.0；北交所无复权因子（404 抛错）。
    """
    if kind not in ("qfq", "hfq"):
        raise ValueError(f"kind 只能是 'qfq' 或 'hfq'，收到 {kind!r}")
    sym = sina_symbol(code)
    url = f"https://finance.sina.com.cn/realstock/company/{sym}/{kind}.js"
    ratelimit.acquire(SOURCE)
    text = http_get(url, headers=_HEADERS, timeout=10)
    import json
    brace = text.find("{")
    if brace < 0:
        raise SourceUnavailable(f"新浪复权因子响应无 JSON（{sym}/{kind}）: {text[:120]}")
    try:
        data, _ = json.JSONDecoder().raw_decode(text[brace:])
    except json.JSONDecodeError as e:
        raise SourceUnavailable(f"新浪复权因子 JSON 解析失败（{sym}/{kind}）: {e}") from e
    return [{"date": it["d"], "factor": float(it["f"])} for it in data.get("data", [])]


def apply_adjust(bars: list[dict], factors: list[dict], kind: str = "qfq") -> list[dict]:
    """把复权因子套到不复权 K线上（返回新列表）。

    🔴 因子为空必须抛错——新浪对不支持的标的返回空 data，
    原样返回会把不复权价当复权价交出去（看着正常但是错的）。
    🔴 早于首个因子日的 bar 无因子可套 → 抛错（不猜）。
    """
    if kind not in ("qfq", "hfq"):
        raise ValueError(f"kind 只能是 'qfq' 或 'hfq'，收到 {kind!r}")
    if not factors:
        raise ValueError("复权因子列表为空（新浪对不支持的标的返回空 data），拒绝用未复权价冒充")
    # 因子表：date → factor；新浪序列最新在前 → 反转成升序便于阶梯查找
    ladder = sorted(((f["date"], f["factor"]) for f in factors), key=lambda x: x[0])
    earliest = ladder[0][0]
    out = []
    for b in bars:
        d = str(b.get("bar_time") or b.get("date") or "")[:10]
        if d < earliest:
            raise ValueError(
                f"bar {d} 早于最早复权因子日 {earliest}，因子表不覆盖（请拉长因子序列）"
            )
        fac = None
        for fdate, fval in ladder:
            if fdate <= d:
                fac = fval
            else:
                break
        if fac is None or fac == 0:
            raise ValueError(f"bar {d} 找不到有效复权因子")
        row = dict(b)
        if kind == "qfq":
            for k in ("open", "high", "low", "close"):
                if row.get(k) is not None:
                    row[k] = round(row[k] / fac, 4)
        else:
            for k in ("open", "high", "low", "close"):
                if row.get(k) is not None:
                    row[k] = round(row[k] * fac, 4)
        out.append(row)
    return out


def _f(v):
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
