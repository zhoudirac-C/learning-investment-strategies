"""通达信行情高层查询接口。

TdxMarket 是其他模块应当使用的入口。它封装了：

- 股票/指数代码 → (market, code) 的转换（沪/深/北交所/指数/板块指数）
- pytdx 原始字段 → 项目统一 dict 字段的映射（对齐 stock_data.py 的格式）
- K线周期字符串 → pytdx category 数字
- 批量行情自动分批（单次 ≤80 支，避免服务器拒绝）

输出 dict 的 source 字段统一为 'tdx'，便于后续接入 stock_data.py 的
多源 fallback 链时与 'tencent_gtimg' / 'eastmoney' 区分。

字段对齐（参考 src/qing_investment/agent/tools/stock_data.py）：

- 实时行情: code/name/price/prev_close/open/high/low/volume/amount/
            pct_change/change/is_index/source
- K线:      date/open/close/high/low/volume/amount/pct_change/source
"""

from __future__ import annotations

import logging
from typing import Any

from .client import TdxClient
from .exceptions import TdxDataError, TdxSymbolError
from .hosts import HostCapability

logger = logging.getLogger(__name__)

# pytdx 市场常量（与 pytdx.hq.TDXParams 一致）
MARKET_SZ = 0
MARKET_SH = 1

# K线周期字符串 → pytdx category
KLINE_CATEGORY: dict[str, int] = {
    "5min": 0,
    "15min": 1,
    "30min": 2,
    "60min": 3,
    "1hour": 3,
    "daily": 4,
    "day": 4,
    "weekly": 5,
    "week": 5,
    "monthly": 6,
    "month": 6,
    "1min": 7,
    "quarter": 10,
    "year": 11,
}

# 单次实时行情批量上限（pytdx 经验值）
_QUOTE_BATCH = 80


def resolve_symbol(code: str) -> tuple[int, str, bool]:
    """把股票/指数代码解析为 (market, pure_code, is_index)。

    优先用 sh/sz/bj 前缀或 .sh/.sz/.bj/.ss 后缀确定市场；无前缀时按代码
    数字推断。注意 000001 在沪市为上证指数、在深市为平安银行，由前缀决定。
    """
    if not code:
        raise TdxSymbolError(f"空代码: {code!r}")
    c = code.strip().lower()
    market_hint: int | None = None
    # 前缀 sh/sz/bj
    if c.startswith("sh"):
        market_hint = MARKET_SH
        c = c[2:]
    elif c.startswith("sz"):
        market_hint = MARKET_SZ
        c = c[2:]
    elif c.startswith("bj"):
        market_hint = MARKET_SH  # 北交所走 market=1
        c = c[2:]
    # 后缀
    for suf, m in ((".sh", MARKET_SH), (".ss", MARKET_SH), (".sz", MARKET_SZ), (".bj", MARKET_SH)):
        if c.endswith(suf):
            if market_hint is None:
                market_hint = m
            c = c[: -len(suf)]
            break
    if not c.isdigit() or len(c) != 6:
        raise TdxSymbolError(f"无法识别的代码: {code!r}")

    # 指数/板块指数判断
    is_index = False
    if c.startswith("399"):
        is_index = True
        if market_hint is None:
            market_hint = MARKET_SZ
    elif c.startswith(("999", "880")):
        is_index = True
        if market_hint is None:
            market_hint = MARKET_SH
    elif c in ("000300", "000016", "000905", "000852", "000688", "000985", "000932"):
        is_index = True
        if market_hint is None:
            market_hint = MARKET_SH
    elif market_hint == MARKET_SH and c == "000001":
        # 000001 在沪市为上证指数，在深市为平安银行
        is_index = True

    # 个股 market 推断（无 hint 时）
    if market_hint is None:
        if c.startswith("6"):
            market_hint = MARKET_SH
        elif c.startswith(("0", "3")):
            market_hint = MARKET_SZ
        elif c.startswith(("8", "4", "92")):
            market_hint = MARKET_SH  # 北交所
        else:
            raise TdxSymbolError(f"无法识别的代码: {code!r}")

    return market_hint, c, is_index


def _f(value: Any) -> float | None:
    """安全转 float，None/异常 → None。"""
    if value is None:
        return None
    try:
        f = float(value)
        # pytdx 对无数据字段常返回 0 或极大值，保留原值，由上层判断
        return f
    except (TypeError, ValueError):
        return None


class TdxMarket:
    """通达信行情查询入口（高层 API）。

    >>> mkt = TdxMarket()
    >>> mkt.get_quotes(["600519", "000001"])  # 茅台、平安银行
    >>> mkt.get_kline("600519", category="daily", count=10)
    """

    def __init__(self, client: TdxClient | None = None) -> None:
        self.client = client or TdxClient()

    # ------------------------------------------------------------------
    # 实时行情
    # ------------------------------------------------------------------

    def get_quotes(self, codes: list[str]) -> list[dict]:
        """批量实时行情。自动按 _QUOTE_BATCH 分批。"""
        if not codes:
            return []
        # 解析 + 去重保序
        seen: set[tuple[int, str]] = set()
        pairs: list[tuple[int, str]] = []
        code_map: dict[tuple[int, str], str] = {}
        for code in codes:
            market, pure, _ = resolve_symbol(code)
            key = (market, pure)
            if key in seen:
                continue
            seen.add(key)
            pairs.append(key)
            code_map[key] = code

        out: list[dict] = []
        for i in range(0, len(pairs), _QUOTE_BATCH):
            batch = pairs[i : i + _QUOTE_BATCH]
            raw = self.client.execute(
                HostCapability.CapMainQuote,
                lambda api, b=batch: api.get_security_quotes(b),
                retry_empty=True,
            )
            if not raw:
                continue
            for item in raw:
                out.append(self._map_quote(item))
        return out

    def get_quote(self, code: str) -> dict | None:
        """单只实时行情。"""
        rows = self.get_quotes([code])
        return rows[0] if rows else None

    def _map_quote(self, item: dict) -> dict:
        price = _f(item.get("price"))
        prev_close = _f(item.get("last_close"))
        open_p = _f(item.get("open"))
        high = _f(item.get("high"))
        low = _f(item.get("low"))
        vol = _f(item.get("vol")) or _f(item.get("volume"))
        amount = _f(item.get("amount"))
        code = str(item.get("code", "")).lstrip("shszbj")
        market = item.get("market")
        is_index = market is not None and code.startswith(("399", "999", "880"))
        pct_change = None
        change = None
        if price is not None and prev_close and prev_close > 0:
            change = round(price - prev_close, 4)
            pct_change = round((price / prev_close - 1) * 100, 4)
        # 五档盘口
        bid = [
            {"price": _f(item.get(f"bid{i}")), "volume": _f(item.get(f"bid_vol{i}"))}
            for i in range(1, 6)
        ]
        ask = [
            {"price": _f(item.get(f"ask{i}")), "volume": _f(item.get(f"ask_vol{i}"))}
            for i in range(1, 6)
        ]
        return {
            "code": code,
            "market": market,
            "name": item.get("name"),
            "price": price,
            "prev_close": prev_close,
            "open": open_p,
            "high": high,
            "low": low,
            "volume": vol,
            "amount": amount,
            "cur_vol": _f(item.get("cur_vol")),
            "buy_vol": _f(item.get("b_vol")),
            "sell_vol": _f(item.get("s_vol")),
            "change": change,
            "pct_change": pct_change,
            "is_index": is_index,
            "bid": bid,
            "ask": ask,
            "source": "tdx",
        }

    # ------------------------------------------------------------------
    # K线
    # ------------------------------------------------------------------

    def get_kline(
        self,
        code: str,
        category: str | int = "daily",
        count: int = 100,
        start: int = 0,
    ) -> list[dict]:
        """个股K线。``category`` 可为 'daily'/'weekly'/'monthly'/'5min' 等或数字。"""
        market, pure, is_index = resolve_symbol(code)
        cat = self._category(category)
        cap = HostCapability.CapMainKline
        if is_index:
            cap = HostCapability.CapMainKline  # 指数K线同样走 Kline 能力
        raw = self.client.execute(
            cap,
            lambda api: (
                api.get_index_bars(cat, market, pure, start, count)
                if is_index
                else api.get_security_bars(cat, market, pure, start, count)
            ),
            retry_empty=True,
        )
        if not raw:
            return []
        return self._map_klines(raw)

    def get_index_kline(
        self,
        code: str,
        category: str | int = "daily",
        count: int = 100,
        start: int = 0,
    ) -> list[dict]:
        """指数K线（便捷别名，等价于对指数代码调用 get_kline）。"""
        return self.get_kline(code, category=category, count=count, start=start)

    def _map_klines(self, raw: list[dict]) -> list[dict]:
        rows: list[dict] = []
        prev_close: float | None = None
        # pytdx 返回按时间正序；先算 prev_close 再保持顺序
        for item in raw:
            close = _f(item.get("close"))
            date = self._kline_date(item)
            pct_change = None
            if close is not None and prev_close and prev_close > 0:
                pct_change = round((close / prev_close - 1) * 100, 4)
            if close is not None:
                prev_close = close
            rows.append({
                "date": date,
                "datetime": item.get("datetime"),
                "open": _f(item.get("open")),
                "close": close,
                "high": _f(item.get("high")),
                "low": _f(item.get("low")),
                "volume": _f(item.get("vol")) or _f(item.get("volume")),
                "amount": _f(item.get("amount")),
                "pct_change": pct_change,
                "source": "tdx",
            })
        return rows

    @staticmethod
    def _kline_date(item: dict) -> str:
        dt = item.get("datetime")
        if dt:
            return str(dt)[:10]
        y, mo, d = item.get("year"), item.get("month"), item.get("day")
        if y and mo and d:
            return f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"
        return ""

    @staticmethod
    def _category(category: str | int) -> int:
        if isinstance(category, int):
            return category
        key = str(category).lower()
        if key not in KLINE_CATEGORY:
            raise TdxDataError(f"未知 K线周期: {category!r}，可选: {list(KLINE_CATEGORY)}")
        return KLINE_CATEGORY[key]

    # ------------------------------------------------------------------
    # 分时 / 分笔
    # ------------------------------------------------------------------

    def get_intraday(self, code: str) -> list[dict]:
        """当日分时数据。

        注意：pytdx 的 ``get_minute_time_data`` 仅返回 ``price``/``vol`` 两个字段，
        且部分服务器返回的 price 为归一化值（非真实成交价）。如需精确分时，
        建议沿用现有腾讯分时源；本接口主要作为 fallback。
        """
        market, pure, _ = resolve_symbol(code)
        raw = self.client.execute(
            HostCapability.CapMainMinute,
            lambda api: api.get_minute_time_data(market, pure),
        )
        if not raw:
            return []
        out = []
        for item in raw:
            out.append({
                "price": _f(item.get("price")),
                "volume": _f(item.get("vol")),
                "source": "tdx",
            })
        return out

    def get_history_intraday(self, code: str, date: str) -> list[dict]:
        """历史分时，date 格式 'YYYYMMDD'。"""
        market, pure, _ = resolve_symbol(code)
        raw = self.client.execute(
            HostCapability.CapMainMinute,
            lambda api: api.get_history_minute_time_data(market, pure, int(date)),
        )
        if not raw:
            return []
        return [{"price": _f(p), "source": "tdx"} for p in raw if _f(p) is not None]

    def get_transaction(self, code: str, start: int = 0, count: int = 2000) -> list[dict]:
        """当日分笔成交。"""
        market, pure, _ = resolve_symbol(code)
        raw = self.client.execute(
            HostCapability.CapMainTrade,
            lambda api: api.get_transaction_data(market, pure, start, count),
        )
        if not raw:
            return []
        out = []
        for item in raw:
            out.append({
                "time": item.get("time"),
                "price": _f(item.get("price")),
                "volume": _f(item.get("vol")) or _f(item.get("volume")),
                "buyorsell": item.get("buyorsell"),
                "source": "tdx",
            })
        return out

    # ------------------------------------------------------------------
    # 基本面
    # ------------------------------------------------------------------

    def get_finance(self, code: str) -> dict:
        """财务信息（最新一期）。"""
        market, pure, _ = resolve_symbol(code)
        raw = self.client.execute(
            HostCapability.CapMainFinance,
            lambda api: api.get_finance_info(market, pure),
        )
        if not raw:
            return {}
        # raw 通常是单个 dict
        item = raw[0] if isinstance(raw, list) else raw
        out = dict(item) if isinstance(item, dict) else {"raw": item}
        out["source"] = "tdx"
        return out

    def get_xdxr(self, code: str) -> list[dict]:
        """除权除息信息。"""
        market, pure, _ = resolve_symbol(code)
        raw = self.client.execute(
            HostCapability.CapMainXdxr,
            lambda api: api.get_xdxr_info(market, pure),
        )
        if not raw:
            return []
        out = []
        for item in raw:
            d = dict(item) if isinstance(item, dict) else {"raw": item}
            d["source"] = "tdx"
            out.append(d)
        return out

    # ------------------------------------------------------------------
    # 证券列表 / 板块
    # ------------------------------------------------------------------

    def get_security_list(self, market: int, start: int = 0, count: int = 1000) -> list[dict]:
        """获取证券列表（分页）。market: 0=深, 1=沪。

        注意：pytdx ``get_security_list`` 签名实际为 ``(market, start)``，
        ``count`` 参数仅用于文档说明（pytdx 内部固定每页约 1000 条）。
        当前部分服务器环境该方法返回 None（pytdx 已知问题），如需完整
        证券列表建议沿用 akshare。
        """
        raw = self.client.execute(
            HostCapability.CapMainList,
            lambda api: api.get_security_list(market, start),
            retry_empty=True,
        )
        if not raw:
            return []
        out = []
        for item in raw:
            d = dict(item) if isinstance(item, dict) else {"raw": item}
            d["source"] = "tdx"
            out.append(d)
        return out

    def get_block_info(self, blockfile: str = "block_zs.dat") -> list[dict]:
        """获取并解析板块文件（默认指数板块）。

        常用 blockfile: block_zs.dat(指数), block_gn.dat(概念),
        block_fg.dat(风格).
        """
        raw = self.client.execute(
            HostCapability.CapSector880,
            lambda api: api.get_and_parse_block_info(blockfile),
            retry_empty=True,
        )
        if not raw:
            return []
        out = []
        for item in raw:
            d = dict(item) if isinstance(item, dict) else {"raw": item}
            d["source"] = "tdx"
            out.append(d)
        return out

    def get_block_members(self, blockfile: str = "block_gn.dat") -> dict[str, list[str]]:
        """正确解析板块文件，返回 {板块名: [成分股裸码, ...]}。

        绕过 pytdx 的 get_and_parse_block_info 下载 bug：后者每次
        get_block_info(blockfile, start, size) 传的是「总大小」而非剩余
        chunk 大小，且服务器单次返回上限 ~60000 字节，导致拼接错位——
        表现为 block_gn.dat 前 21 个板块名正常、之后板块名被成分股代码
        污染（2026-08-13 实测定位）。

        正确做法：按 60000 字节分块、传剩余字节数，手动按通达信 block
        格式解析（header 384 + num(2) + 每板块 name(9) + sc(2)+bt(2) +
        codes(7*sc)，每板块 stride 固定 2800）。
        """
        raw = self.client.execute(
            HostCapability.CapSector880,
            lambda api: _download_block_raw(api, blockfile),
            retry_empty=True,
        )
        if not raw:
            return {}
        return _parse_block_members(raw)


def _download_block_raw(api, blockfile: str, chunk: int = 60000) -> bytes:
    """正确分块下载板块文件原始字节（修复 pytdx 拼接 bug）。"""
    import struct as _struct

    meta = api.get_block_info_meta(blockfile)
    size = meta["size"]
    content = bytearray()
    start = 0
    while start < size:
        ask = min(chunk, size - start)
        piece = api.get_block_info(blockfile, start, ask)
        if not piece:
            break
        content.extend(piece)
        start += len(piece)
        if len(piece) < ask:
            break
    return bytes(content)


def _parse_block_members(data: bytes) -> dict[str, list[str]]:
    """按通达信 block 文件格式解析 板块名 → 成分股裸码列表。"""
    import struct as _struct

    pos = 384
    (num,) = _struct.unpack("<H", data[pos:pos + 2])
    pos += 2
    out: dict[str, list[str]] = {}
    for _ in range(num):
        name = data[pos:pos + 9].decode("gbk", "ignore").rstrip("\x00")
        pos += 9
        (stock_count, _bt) = _struct.unpack("<HH", data[pos:pos + 4])
        pos += 4
        block_begin = pos
        codes: list[str] = []
        for _ in range(stock_count):
            c = data[pos:pos + 7].decode("utf-8", "ignore").rstrip("\x00")
            pos += 7
            if c and c.isdigit() and len(c) == 6:
                codes.append(c)
        if name:
            out[name] = codes
        pos = block_begin + 2800
    return out
