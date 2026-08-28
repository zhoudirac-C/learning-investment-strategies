"""历史日线抓取：akshare → baostock 降级链（M6-1，设计文档 §4.1）。

代码形式约定：
- 个股：裸 6 位数字（'600519'）
- 指数：带市场字母前缀（'sh000001' / 'sz399001'）

归一输出行：``{"date": "YYYY-MM-DD", "open", "high", "low", "close",
"volume"(单位：股), "amount"(元或 None)}``。

降级纪律（对齐 AGENTS.md 数据诚实原则）：双源皆挂抛 ``DataFetchError``，
禁止编造；空结果视为成功响应（该区间无交易），不触发降级。

M7-1 增补（chanlun-m7-multitimeframe-skill.md §4）：分钟线（60m/30m）
新浪 → TDX 降级链。继承 skill 实证坑：腾讯分钟线不可用必须新浪；
curl + 完整 UA（urllib 默认 UA 被限流）；新浪 datalen=260 窗口上限。
归一输出分钟行：``{"dt": "YYYY-MM-DD HH:MM", "open", "high", "low",
"close", "volume", "complete"}``，complete=0 为盘中未完成 bar（§4.3）。
"""
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timedelta, timezone
from typing import Any

_CN_TZ = timezone(timedelta(hours=8))

#: M7-1 仅支持 60m/30m（设计 §2.2：30m 已是最细）
VALID_MINUTE_TF = (30, 60)

#: 新浪分钟线窗口上限（skill 实证）
_SINA_DATALEN = 260

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"


class DataFetchError(RuntimeError):
    """双源皆失败。消息含各源错误明细，便于定位。"""


def is_index(code: str) -> bool:
    """含字母前缀（sh/sz）为指数形式；纯 6 位数字为个股。"""
    return any(c.isalpha() for c in code)


def to_baostock_code(code: str) -> str:
    """'600519'→'sh.600519'；'000001'→'sz.000001'；'sh000001'→'sh.000001'。

    个股市场判定沿用 investment_engine.backtest.history._secid 口径：
    5/6/9 开头沪市，其余深市。
    """
    if is_index(code):
        prefix, digits = code[:2], code[2:]
        return f"{prefix}.{digits}"
    market = "sh" if code.startswith(("5", "6", "9")) else "sz"
    return f"{market}.{code}"


# ── 归一化（纯函数，单测直测） ──

def _f(v: Any) -> float | None:
    """宽松 float 转换：空串/None/非法值 → None。"""
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _date_str(v: Any) -> str:
    """日期统一 'YYYY-MM-DD'（容忍 Timestamp/date 等带时间尾的形式）。"""
    return str(v)[:10]


def normalize_akshare_stock_records(records: list[dict]) -> list[dict]:
    """akshare ``stock_zh_a_hist`` 记录 → 归一行。成交量"手"×100 归一到"股"。"""
    rows = []
    for r in records:
        vol = _f(r.get("成交量"))
        rows.append({
            "date": _date_str(r.get("日期")),
            "open": _f(r.get("开盘")),
            "high": _f(r.get("最高")),
            "low": _f(r.get("最低")),
            "close": _f(r.get("收盘")),
            "volume": vol * 100 if vol is not None else None,
            "amount": _f(r.get("成交额")),
        })
    return rows


def normalize_akshare_index_records(records: list[dict]) -> list[dict]:
    """akshare ``stock_zh_index_daily``（新浪源）记录 → 归一行。

    新浪指数源无成交额字段 → amount=None（不编造）；volume 单位存疑，
    按 akshare 惯例 ×100（设计文档附录 A 存疑登记）。
    """
    rows = []
    for r in records:
        vol = _f(r.get("volume"))
        rows.append({
            "date": _date_str(r.get("date")),
            "open": _f(r.get("open")),
            "high": _f(r.get("high")),
            "low": _f(r.get("low")),
            "close": _f(r.get("close")),
            "volume": vol * 100 if vol is not None else None,
            "amount": _f(r.get("amount")),
        })
    return rows


def normalize_baostock_rows(raw_rows: list[list[str]], fields: list[str]) -> list[dict]:
    """baostock ``query_history_k_data_plus`` 行 → 归一行。volume 原生单位为股。"""
    rows = []
    for raw in raw_rows:
        d = dict(zip(fields, raw))
        rows.append({
            "date": _date_str(d.get("date")),
            "open": _f(d.get("open")),
            "high": _f(d.get("high")),
            "low": _f(d.get("low")),
            "close": _f(d.get("close")),
            "volume": _f(d.get("volume")),
            "amount": _f(d.get("amount")),
        })
    return rows


# ── 抓取（触网，单测一律 mock） ──

def _fetch_akshare(code: str, start: str | None, end: str | None) -> list[dict]:
    import akshare as ak

    if is_index(code):
        df = ak.stock_zh_index_daily(symbol=code)
        records = df.to_dict("records")
        rows = normalize_akshare_index_records(records)
    else:
        df = ak.stock_zh_a_hist(
            symbol=code,
            period="daily",
            start_date=(start or "19900101").replace("-", ""),
            end_date=(end or "20991231").replace("-", ""),
            adjust="qfq",
        )
        rows = normalize_akshare_stock_records(df.to_dict("records"))
    if start:
        rows = [r for r in rows if r["date"] >= start]
    if end:
        rows = [r for r in rows if r["date"] <= end]
    return rows


def _fetch_baostock(code: str, start: str | None, end: str | None) -> list[dict]:
    import baostock as bs

    fields = ["date", "open", "high", "low", "close", "volume", "amount"]
    lg = bs.login()
    if lg.error_code != "0":
        raise DataFetchError(f"baostock login failed: {lg.error_msg}")
    try:
        rs = bs.query_history_k_data_plus(
            to_baostock_code(code),
            ",".join(fields),
            start_date=start or "1990-12-19",
            end_date=end or "2099-12-31",
            frequency="d",
            adjustflag="2",  # 前复权（设计文档 §4.2 口径）
        )
        if rs.error_code != "0":
            raise DataFetchError(f"baostock query failed: {rs.error_msg}")
        raw: list[list[str]] = []
        while rs.next():
            raw.append(rs.get_row_data())
        return normalize_baostock_rows(raw, fields)
    finally:
        bs.logout()


def fetch_daily(
    code: str,
    start: str | None = None,
    end: str | None = None,
) -> tuple[list[dict], str]:
    """抓取前复权日线，返回 (归一行列表, 实际源名)。日期升序。

    降级链：akshare → baostock → DataFetchError。空结果视为成功响应
    （该区间无交易），不触发降级。
    """
    errors: list[str] = []
    for source, fn in (("akshare", _fetch_akshare), ("baostock", _fetch_baostock)):
        try:
            rows = fn(code, start, end)
        except Exception as e:  # 传输层失败 → 降级下一源
            errors.append(f"{source}: {type(e).__name__}: {e}")
            continue
        rows.sort(key=lambda r: r["date"])
        return rows, source
    raise DataFetchError(f"all sources failed for {code}: " + "; ".join(errors))


# ── M7-1 分钟线（60m/30m）：新浪 → TDX ──

def to_sina_symbol(code: str) -> str:
    """新浪 symbol 必须带市场前缀：'sh512400' 原样；'512400'→'sh512400'。

    个股/ETF 市场判定与 to_baostock_code 同口径：5/6/9 开头沪市，其余深市。
    """
    if is_index(code):
        return code
    market = "sh" if code.startswith(("5", "6", "9")) else "sz"
    return f"{market}{code}"


def normalize_sina_minute_records(records: list[dict]) -> list[dict]:
    """新浪 ``getKLineData`` 记录 → 归一分钟行。dt 截到分钟（str[:16]）。

    新浪 volume 原样透传（单位未 ×100，与 skill 现行口径一致）。
    """
    rows = []
    for r in records:
        rows.append({
            "dt": str(r.get("day"))[:16],
            "open": _f(r.get("open")),
            "high": _f(r.get("high")),
            "low": _f(r.get("low")),
            "close": _f(r.get("close")),
            "volume": _f(r.get("volume")),
        })
    return rows


def normalize_tdx_minute_records(records: list[dict]) -> list[dict]:
    """TDX ``get_kline`` 记录 → 归一分钟行。分钟 bar 用完整 datetime，缺则退 date。"""
    rows = []
    for r in records:
        dt = r.get("datetime") or str(r.get("date", ""))
        rows.append({
            "dt": str(dt)[:16],
            "open": _f(r.get("open")),
            "high": _f(r.get("high")),
            "low": _f(r.get("low")),
            "close": _f(r.get("close")),
            "volume": _f(r.get("volume")),
        })
    return rows


def mark_complete(rows: list[dict], now: datetime | None = None) -> list[dict]:
    """打 complete 标记（§4.3）：dt > now（截断到分钟）→ 盘中未完成 bar = 0。

    分钟 bar 的 dt 为该周期结束时刻（新浪/TDX 同口径）：盘中进行中的
    最后一根 bar dt 落在未来 → complete=0；收盘后全部 dt ≤ now → 1。
    """
    now = now or datetime.now(_CN_TZ)
    now_min = now.strftime("%Y-%m-%d %H:%M")
    for r in rows:
        r["complete"] = 0 if r["dt"] > now_min else 1
    return rows


def validate_minute_rows(rows: list[dict]) -> list[dict]:
    """入库前校验（§4.3 数据诚实防线）：dt 必须完整可解析到分钟，o/h/l/c 非 None。

    脏行 = 源端异常 → 抛 ``DataFetchError`` 触发降级/报错，禁止静默入库：
    dt 缺失会塌缩主键（多行覆盖成一行），纯日期 dt 盘中会被 mark_complete
    误判 complete=1（反未来函数）。volume 缺失容忍（load_bars 有 0.0 兜底）。
    """
    for i, r in enumerate(rows):
        dt = r.get("dt") or ""
        try:
            datetime.strptime(dt, "%Y-%m-%d %H:%M")
        except (TypeError, ValueError):
            raise DataFetchError(f"分钟行[{i}] dt 异常: {dt!r}")
        for k in ("open", "high", "low", "close"):
            if r.get(k) is None:
                raise DataFetchError(f"分钟行[{i}] {dt} 缺字段 {k}")
    return rows


def _curl_json(url: str) -> Any:
    """curl + 完整 UA 拉 JSON（skill 实证：urllib 默认 UA 被新浪限流）。"""
    out = subprocess.run(
        ["curl", "-s", "--max-time", "10", "-A", _UA, url],
        capture_output=True, check=True,
    )
    return json.loads(out.stdout.decode("utf-8", errors="replace"))


def _fetch_sina_minute(code: str, tf: int, datalen: int = _SINA_DATALEN) -> list[dict]:
    """新浪分钟线。空列表/异常响应视为限流特征 → 抛错触发 TDX 降级（skill 实证纪律）。"""
    url = (
        "https://quotes.sina.cn/cn/api/json_v2.php/CN_MarketDataService.getKLineData"
        f"?symbol={to_sina_symbol(code)}&scale={tf}&ma=no&datalen={datalen}"
    )
    try:
        raw = _curl_json(url)
    except Exception as e:
        raise DataFetchError(f"sina {tf}m request failed: {type(e).__name__}: {e}") from e
    if not isinstance(raw, list) or not raw or "close" not in raw[0]:
        raise DataFetchError(f"sina {tf}m abnormal response: {str(raw)[:80]}")
    return validate_minute_rows(normalize_sina_minute_records(raw))


def _get_tdx_market():
    """懒加载 TdxMarket（pytdx 直连）。失败抛原始异常（调用方包成 DataFetchError，
    保留根因——import 里的真实 bug 不得报成笼统'不可用'）。"""
    from qing_investment.tdx_market.market import TdxMarket

    return TdxMarket()


def _fetch_tdx_minute(code: str, tf: int, datalen: int = _SINA_DATALEN) -> list[dict]:
    """TDX 分钟线降级层。空结果视为成功响应（该窗口无交易），与日线口径一致。"""
    try:
        market = _get_tdx_market()
    except Exception as e:
        raise DataFetchError(f"TDX 不可用: {type(e).__name__}: {e}") from e
    rows = market.get_kline(to_sina_symbol(code), f"{tf}min", count=datalen)
    return validate_minute_rows(normalize_tdx_minute_records(rows))


def fetch_minute(
    code: str,
    tf: int,
    datalen: int = _SINA_DATALEN,
) -> tuple[list[dict], str]:
    """抓取分钟线（60m/30m），返回 (归一行列表, 实际源名)。dt 升序，含 complete 标记。

    降级链：新浪 → TDX → DataFetchError。库内既有快照即天然 stale 层
    （分钟库幂等 upsert，双源皆挂时调用方复读库即可，数据层不另设缓存）。
    窗口上限 datalen=260 ≈ 60m 2.6 个月 / 30m 1.4 个月（§4.2 能力边界）。
    """
    if tf not in VALID_MINUTE_TF:
        raise ValueError(f"不支持的分钟周期 tf={tf}（仅 {VALID_MINUTE_TF}）")
    errors: list[str] = []
    for source, fn in (("sina", _fetch_sina_minute), ("tdx", _fetch_tdx_minute)):
        try:
            rows = fn(code, tf, datalen)
        except Exception as e:  # 传输层失败 → 降级下一源
            errors.append(f"{source}: {type(e).__name__}: {e}")
            continue
        rows.sort(key=lambda r: r["dt"])
        return mark_complete(rows), source
    raise DataFetchError(f"all sources failed for {code} {tf}m: " + "; ".join(errors))
