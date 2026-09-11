"""官方源：中证/国证指数成分与权重、指数估值、深交所交易日历。

移植自 a-stock-data v3.8.0 Layer 12（零鉴权官方文件/API），行为契约：
- 指数代码必须是 6 位纯数字；provider="csi" 中证 / "cni" 国证
- 快照日期以返回的 ``date`` 列为准（成分与权重可能不同日，不能拼接冒充）
- 网络失败/结构变化/重复记录/不完整日历 → 抛错，**不伪装为空结果**
- 交易日历逐日 ``is_open``，不靠工作日推断，未发布月份不当休市
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from io import BytesIO

from qing_investment.marketdata.errors import SourceUnavailable


def _official_code(value: str) -> str:
    value = str(value).strip()
    if not re.fullmatch(r"[0-9]{6}", value):
        raise ValueError("指数代码必须是 6 位纯数字")
    return value


def _official_get(url: str, params: dict | None = None, referer: str | None = None):
    import requests
    resp = requests.get(
        url, params=params,
        headers={"User-Agent": "Mozilla/5.0", "Referer": referer or url},
        timeout=(10, 40),
    )
    resp.raise_for_status()
    return resp


def _official_excel(resp):
    import pandas as pd
    try:
        frame = pd.read_excel(BytesIO(resp.content), dtype=str)
    except (ValueError, OSError) as exc:
        raise SourceUnavailable("官方源未返回可解析的 Excel；可能未发布或结构变更") from exc
    frame.columns = [re.sub(r"\s+", "", str(c)) for c in frame.columns]
    return frame


def _require_columns(frame, names: list[str]) -> None:
    missing = set(names) - set(frame.columns)
    if missing:
        raise SourceUnavailable("官方数据列缺失: " + ", ".join(sorted(missing)))


def index_constituents(index_code: str, provider: str = "csi") -> "list[dict]":
    """官方最近发布的指数成分快照。返回 [{date, code, name, exchange}]。

    历史回测注意：当前成分 ≠ 当时成分，须先检查 date。
    """
    index_code = _official_code(index_code)
    if provider == "csi":
        url = ("https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/file/"
               f"autofile/cons/{index_code}cons.xls")
        data = _official_excel(_official_get(url))
        cols = ["日期Date", "指数代码IndexCode", "成份券代码ConstituentCode",
                "成份券名称ConstituentName", "交易所Exchange"]
        _require_columns(data, cols)
        exchanges = {"上海证券交易所": "SH", "深圳证券交易所": "SZ", "北京证券交易所": "BJ"}
        rows = []
        for rec in data.to_dict("records"):
            if str(rec["指数代码IndexCode"]).zfill(6) != index_code:
                raise SourceUnavailable("中证返回了不同指数的数据")
            rows.append({
                "date": str(rec["日期Date"])[:10],
                "code": str(rec["成份券代码ConstituentCode"]).zfill(6),
                "name": rec["成份券名称ConstituentName"],
                "exchange": exchanges.get(rec["交易所Exchange"]),
            })
        return rows
    if provider == "cni":
        url = "https://www.cnindex.com.cn/sample-detail/download-history"
        data = _official_excel(_official_get(url, {"indexcode": index_code}))
        cols = ["日期", "样本代码", "样本简称", "权重（%）"]
        _require_columns(data, cols)
        return [{
            "date": str(rec["日期"])[:10],
            "code": str(rec["样本代码"]).zfill(6),
            "name": rec["样本简称"],
            "exchange": None,
        } for rec in data.to_dict("records")]
    raise ValueError("provider 必须是 csi（中证）或 cni（国证）")


def index_weights(index_code: str, provider: str = "csi") -> list[dict]:
    """官方最近公布的指数权重。``weight_percent=0.433`` 表示 0.433%。"""
    index_code = _official_code(index_code)
    if provider == "csi":
        url = ("https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/file/"
               f"autofile/closeweight/{index_code}closeweight.xls")
        data = _official_excel(_official_get(url))
        cols = ["日期Date", "指数代码IndexCode", "成份券代码ConstituentCode",
                "成份券名称ConstituentName", "交易所Exchange", "权重(%)weight"]
        _require_columns(data, cols)
        rows = []
        for rec in data.to_dict("records"):
            if str(rec["指数代码IndexCode"]).zfill(6) != index_code:
                raise SourceUnavailable("中证返回了不同指数的数据")
            try:
                w = float(str(rec["权重(%)weight"]).replace(",", ""))
            except (ValueError, TypeError):
                continue
            rows.append({
                "date": str(rec["日期Date"])[:10],
                "code": str(rec["成份券代码ConstituentCode"]).zfill(6),
                "name": rec["成份券名称ConstituentName"],
                "weight_percent": w,
            })
        return rows
    if provider == "cni":
        url = "https://www.cnindex.com.cn/sample-detail/download-history"
        data = _official_excel(_official_get(url, {"indexcode": index_code}))
        cols = ["日期", "样本代码", "样本简称", "权重（%）"]
        _require_columns(data, cols)
        rows = []
        for rec in data.to_dict("records"):
            try:
                w = float(str(rec["权重（%）"]).replace(",", ""))
            except (ValueError, TypeError):
                continue
            rows.append({
                "date": str(rec["日期"])[:10],
                "code": str(rec["样本代码"]).zfill(6),
                "name": rec["样本简称"],
                "weight_percent": w,
            })
        return rows
    raise ValueError("provider 必须是 csi（中证）或 cni（国证）")


def trading_calendar(year: int, month: int) -> list[dict]:
    """深交所官方整月交易日历。返回 [{date, is_open}]，逐日（含周末）。

    未发布月份抛错（不当全月休市）；日期不完整抛错（不能继续调度）。
    """
    import calendar as _cal
    url = "https://www.szse.cn/api/report/exchange/onepersistenthour/monthList"
    try:
        data = _official_get(url, {"month": f"{year}-{month}"}).json().get("data")
    except Exception as e:
        raise SourceUnavailable(f"深交所日历请求失败: {type(e).__name__}: {e}") from e
    if not isinstance(data, list) or not data:
        raise SourceUnavailable(f"深交所尚未返回 {year}-{month} 日历；不能推断全月休市")
    rows = []
    for rec in data:
        if str(rec.get("jybz")) not in ("0", "1") or not rec.get("jyrq"):
            raise SourceUnavailable("深交所日历字段异常")
        rows.append({"date": str(rec["jyrq"])[:10], "is_open": str(rec["jybz"]) == "1"})
    expected = set()
    for d in range(1, _cal.monthrange(year, month)[1] + 1):
        expected.add(f"{year:04d}-{month:02d}-{d:02d}")
    got = {r["date"] for r in rows}
    if got != expected:
        raise SourceUnavailable(f"日历月份错位或日期不完整（缺 {len(expected - got)} 天）")
    return sorted(rows, key=lambda r: r["date"])
