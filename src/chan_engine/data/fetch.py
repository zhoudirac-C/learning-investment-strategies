"""历史日线抓取：akshare → baostock 降级链（M6-1，设计文档 §4.1）。

代码形式约定：
- 个股：裸 6 位数字（'600519'）
- 指数：带市场字母前缀（'sh000001' / 'sz399001'）

归一输出行：``{"date": "YYYY-MM-DD", "open", "high", "low", "close",
"volume"(单位：股), "amount"(元或 None)}``。

降级纪律（对齐 AGENTS.md 数据诚实原则）：双源皆挂抛 ``DataFetchError``，
禁止编造；空结果视为成功响应（该区间无交易），不触发降级。
"""
from __future__ import annotations

from typing import Any


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
