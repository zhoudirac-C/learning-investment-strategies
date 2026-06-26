"""Qing-Agent 监控引擎 — 数据获取层 (Phase 0)

基于 AlphaAnalyst 的 Fetcher-Agent 分离原则，将 stock_monitor.py 中耦合的
行情拉取逻辑拆分为独立的 Fetcher 模块。

架构设计:
    ┌─────────────────────────────────────────┐
    │           DataFetcher (统一入口)         │
    │    ┌─────────┐ ┌─────────┐ ┌─────────┐ │
    │    │ Eastmoney│ │ Tencent │ │  Sina   │ │
    │    │Fetcher  │ │Fetcher │ │Fetcher │ │
    │    │(pri=0)  │ │(pri=1) │ │(pri=2) │ │
    │    └────┬────┘ └────┬────┘ └────┬────┘ │
    │         └────────────┴───────────┘      │
    │              降级链: 东财→腾讯→新浪      │
    └─────────────────────────────────────────┘

降级策略:
    1. 东财 (priority=0): 数据最全，但限流严格
    2. 腾讯 (priority=1): 最稳定，对服务器IP友好
    3. 新浪 (priority=2): 备用，覆盖大部分A股

向后兼容:
    现有 stock_monitor.py 中的 fetch_quotes_with_fallback() 将委托给本模块的
    DataFetcher.fetch()，行为完全一致。
"""

from __future__ import annotations

import json
import re
import subprocess
import time as time_module
import urllib.parse
import urllib.request
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, Field


# ──────────────────────────────────────────
# 工具函数
# ──────────────────────────────────────────

def chunk_quote_targets(
    targets: dict[str, str],
    *,
    chunk_size: int = 15,
) -> list[dict[str, str]]:
    """将行情目标分批，每批不超过 chunk_size 个。

    Args:
        targets: {名称: 代码} 字典
        chunk_size: 每批大小（默认15，匹配东财API限制）

    Returns:
        分批后的字典列表
    """
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    items = list(targets.items())
    return [
        dict(items[index : index + chunk_size])
        for index in range(0, len(items), chunk_size)
    ]


# ──────────────────────────────────────────
# 数据模型
# ──────────────────────────────────────────

class FetcherOutput(BaseModel):
    """单个 Fetcher 的返回结果，参考 AlphaAnalyst 设计。"""

    source: str = Field(description="数据源标识，如 eastmoney_push2")
    data: dict[str, Any] = Field(default_factory=dict, description="获取到的行情数据")
    latency_ms: float = Field(default=0.0, description="请求耗时(毫秒)")
    error: str | None = Field(default=None, description="错误信息，成功时为 None")
    quotes_count: int = Field(default=0, description="成功获取的quote数量")


class QuoteData(BaseModel):
    """标准化行情数据结构。"""

    secid: str = Field(description="标准化代码，如 1.000001")
    label: str = Field(description="显示标签")
    code: str = Field(description="纯数字代码，如 000001")
    name: str = Field(description="股票名称")
    latest: float | None = Field(default=None, description="最新价")
    previous_close: float | None = Field(default=None, description="昨收")
    open: float | None = Field(default=None, description="开盘价")
    high: float | None = Field(default=None, description="最高价")
    low: float | None = Field(default=None, description="最低价")
    volume: float | None = Field(default=None, description="成交量")
    amount: float | None = Field(default=None, description="成交额")
    pct_change: float | None = Field(default=None, description="涨跌幅%")
    change: float | None = Field(default=None, description="涨跌额")


# ──────────────────────────────────────────
# Fetcher 基类
# ──────────────────────────────────────────

class BaseFetcher(ABC):
    """行情获取器基类，参考 AlphaAnalyst 的 Fetcher 设计。

    每个 Fetcher 负责从一个特定数据源获取行情，支持:
    - 独立超时控制
    - 健康检查 (is_available)
    - 错误隔离 (一个Fetcher失败不影响其他)
    """

    name: str = "base"
    priority: int = 0  # 优先级，数字越小越优先
    timeout: float = 10.0  # 默认超时(秒)

    @abstractmethod
    def fetch(self, targets: dict[str, str]) -> FetcherOutput:
        """获取行情数据。

        Args:
            targets: {label: secid} 映射，如 {"平安银行": "0.000001"}

        Returns:
            FetcherOutput: 标准化输出，包含 source/data/latency/error
        """
        ...

    def is_available(self) -> bool:
        """检查数据源是否可用。子类可覆盖做健康检查。"""
        return True

    def _http_get(self, url: str, timeout: float | None = None, encoding: str = "utf-8") -> str:
        """发送GET请求并返回文本内容。"""
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        }
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout or self.timeout) as resp:
            return resp.read().decode(encoding, errors="ignore")


# ──────────────────────────────────────────
# 东财 Fetcher (priority=0, 数据最全)
# ──────────────────────────────────────────

class EastmoneyFetcher(BaseFetcher):
    """东方财富行情获取器。

    API: https://push2.eastmoney.com/api/qt/ulist.np/get
    特点: 数据字段最全，但限流严格，适合作为首选。
    """

    name = "eastmoney"
    priority = 0
    timeout = 8.0

    _QUOTE_FIELDS = (
        "f12,f13,f14,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11,f15,f16,f17,f18,f20,f21,f22,f23,f24,f25,f26,f27,f28,f29,f30,f31,f32,f33,f34,f35,f36,f37,f38,f39,f40,f41,f42,f43,f44,f45,f46,f47,f48,f49,f50,f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63,f64,f65,f66,f67,f68,f69,f70,f71,f72,f73,f74,f75,f76,f77,f78,f79,f80,f81,f82,f83,f84,f85,f86,f87,f88,f89,f90,f91,f92,f93,f94,f95,f96,f97,f98,f99,f100,f101,f102,f103,f104,f105,f106,f107,f108,f109,f110,f111,f112,f113,f114,f115,f116,f117,f118,f119,f120,f121,f122,f123,f124,f125,f126,f127,f128,f129,f130,f131,f132,f133,f134,f135,f136,f137,f138,f139,f140,f141,f142,f143,f144,f145,f146,f147,f148,f149,f150,f151,f152,f153,f154,f155,f156,f157,f158,f159,f160,f161,f162,f163,f164,f165,f166,f167,f168,f169,f170,f171,f172,f173,f174,f175,f176,f177,f178,f179,f180,f181,f182,f183,f184,f185,f186,f187,f188,f189,f190,f191,f192,f193,f194,f195,f196,f197,f198,f199,f200"
    )
    _BASE_URL = "https://push2.eastmoney.com/api/qt/ulist.np/get"

    def fetch(self, targets: dict[str, str]) -> FetcherOutput:
        if not targets:
            return FetcherOutput(source="eastmoney", error="empty targets")

        started = time_module.perf_counter()
        quotes: list[dict] = []
        errors: list[str] = []

        for chunk in self._chunk_targets(targets):
            chunk_result = self._fetch_chunk(chunk)
            quotes.extend(chunk_result.get("quotes", []) or [])
            errors.extend(chunk_result.get("errors", []) or [])

        latency = round((time_module.perf_counter() - started) * 1000, 1)

        return FetcherOutput(
            source="eastmoney",
            data={"quotes": quotes, "errors": errors},
            latency_ms=latency,
            error="; ".join(errors) if errors else None,
            quotes_count=len(quotes),
        )

    def _chunk_targets(self, targets: dict[str, str], chunk_size: int = 80) -> list[dict[str, str]]:
        """将目标拆分为多个chunk，避免URL过长。"""
        items = list(targets.items())
        return [dict(items[i : i + chunk_size]) for i in range(0, len(items), chunk_size)]

    def _fetch_chunk(self, chunk: dict[str, str]) -> dict:
        """获取单个chunk的数据。"""
        params = urllib.parse.urlencode(
            {
                "fltt": "2",
                "invt": "2",
                "fields": self._QUOTE_FIELDS,
                "secids": ",".join(chunk.values()),
            },
            safe=",",
        )
        url = f"{self._BASE_URL}?{params}"

        try:
            request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            # 尝试curl降级
            curl_result = self._fetch_with_curl(url, chunk)
            if not curl_result.get("errors"):
                return curl_result
            return {
                "source": "eastmoney",
                "quotes": [],
                "errors": [str(exc), *curl_result.get("errors", [])],
            }

        rows = (payload.get("data") or {}).get("diff") or []
        quotes = self._parse_rows(rows, chunk)

        return {"source": "eastmoney", "quotes": quotes, "errors": []}

    def _fetch_with_curl(self, url: str, targets: dict[str, str]) -> dict:
        """urllib失败时尝试curl。"""
        try:
            result = subprocess.run(
                ["curl", "-fsSL", "--max-time", str(self.timeout), url],
                capture_output=True,
                text=True,
                timeout=self.timeout + 2,
            )
            if result.returncode != 0:
                return {
                    "source": "eastmoney_curl",
                    "quotes": [],
                    "errors": [f"curl failed: {result.stderr[:200]}"],
                }
            payload = json.loads(result.stdout)
            rows = (payload.get("data") or {}).get("diff") or []
            quotes = self._parse_rows(rows, targets)
            return {"source": "eastmoney_curl", "quotes": quotes, "errors": []}
        except Exception as exc:
            return {"source": "eastmoney_curl", "quotes": [], "errors": [str(exc)]}

    def _parse_rows(self, rows: list, targets: dict[str, str]) -> list[dict]:
        """解析东财返回的行数据。"""
        quotes = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            secid = f"{row.get('f13', '')}.{row.get('f12', '')}"
            label = None
            for lbl, sid in targets.items():
                if sid == secid:
                    label = lbl
                    break

            quotes.append(
                {
                    "secid": secid,
                    "label": label or row.get("f14", ""),
                    "code": row.get("f12", ""),
                    "name": row.get("f14", ""),
                    "latest": row.get("f2"),
                    "previous_close": row.get("f18"),
                    "open": row.get("f17"),
                    "high": row.get("f15"),
                    "low": row.get("f16"),
                    "volume": row.get("f5"),
                    "amount": row.get("f6"),
                    "pct_change": row.get("f3"),
                    "change": row.get("f4"),
                }
            )
        return quotes


# ──────────────────────────────────────────
# 腾讯 Fetcher (priority=1, 最稳定)
# ──────────────────────────────────────────

class TencentFetcher(BaseFetcher):
    """腾讯财经行情获取器。

    API: https://qt.gtimg.cn/q={codes}
    特点: 最稳定，对服务器IP友好，适合作为备用。
    """

    name = "tencent"
    priority = 1
    timeout = 15.0

    def fetch(self, targets: dict[str, str]) -> FetcherOutput:
        if not targets:
            return FetcherOutput(source="tencent_gtimg", error="empty targets")

        started = time_module.perf_counter()
        tencent_map, name_map = self._build_code_maps(targets)

        if not tencent_map:
            return FetcherOutput(source="tencent_gtimg", error="no valid codes")

        all_quotes: list[dict] = []
        tencent_codes = list(tencent_map.keys())
        chunk_size = 60

        try:
            for i in range(0, len(tencent_codes), chunk_size):
                chunk = tencent_codes[i : i + chunk_size]
                chunk_quotes = self._fetch_chunk(chunk, tencent_map, name_map)
                all_quotes.extend(chunk_quotes)
        except Exception as exc:
            latency = round((time_module.perf_counter() - started) * 1000, 1)
            return FetcherOutput(
                source="tencent_gtimg",
                data={"quotes": all_quotes},
                latency_ms=latency,
                error=str(exc),
                quotes_count=len(all_quotes),
            )

        latency = round((time_module.perf_counter() - started) * 1000, 1)
        return FetcherOutput(
            source="tencent_gtimg",
            data={"quotes": all_quotes},
            latency_ms=latency,
            quotes_count=len(all_quotes),
        )

    def _build_code_maps(self, targets: dict[str, str]) -> tuple[dict[str, str], dict[str, str]]:
        """构建腾讯格式代码映射。"""
        tencent_map: dict[str, str] = {}  # tencent_code -> secid
        name_map: dict[str, str] = {}  # tencent_code -> label

        for label, secid in targets.items():
            tc = self._to_tencent_code(secid)
            if tc:
                tencent_map[tc] = secid
                name_map[tc] = label
        return tencent_map, name_map

    def _to_tencent_code(self, code_str: str) -> str | None:
        """将secid转换为腾讯格式。"""
        code = str(code_str).strip().upper()
        # 处理 secid 格式: "1.000001"
        match = re.match(r"([10])\.(\d{6})", code)
        if match:
            mkt, num = match.groups()
            return f"{'sh' if mkt == '1' else 'sz'}{num}"
        # 处理 "000001.SZ" 格式
        match = re.match(r"(\d{6})\.(SH|SZ)", code)
        if match:
            num, mkt = match.groups()
            return f"{'sh' if mkt == 'SH' else 'sz'}{num}"
        # 处理纯数字
        if re.match(r"\d{6}$", code):
            if code.startswith(("600", "601", "603", "605", "688", "689")):
                return f"sh{code}"
            else:
                return f"sz{code}"
        return None

    def _fetch_chunk(
        self, chunk: list[str], tencent_map: dict[str, str], name_map: dict[str, str]
    ) -> list[dict]:
        """获取单个chunk的腾讯行情。"""
        url = f"https://qt.gtimg.cn/q={','.join(chunk)}"
        data = self._http_get(url, encoding="gbk")

        quotes = []
        for line in data.strip().split(";"):
            line = line.strip()
            if not line or not line.startswith("v_"):
                continue

            match = re.match(r"v_(\w+)=\"(.+)\"", line)
            if not match:
                continue

            tc_code, content = match.groups()
            parts = content.split("~")
            if len(parts) < 35:
                continue

            latest = self._to_float(parts[3])
            prev = self._to_float(parts[4])
            open_price = self._to_float(parts[5])
            high = self._to_float(parts[33])
            low = self._to_float(parts[34])
            volume = self._to_float(parts[6])
            amount = self._to_float(parts[37]) if len(parts) > 37 else None

            pct_change = None
            change = None
            if latest is not None and prev is not None and prev > 0:
                pct_change = round((latest - prev) / prev * 100, 2)
                change = round(latest - prev, 2)

            quotes.append(
                {
                    "secid": tencent_map.get(tc_code, tc_code),
                    "label": name_map.get(tc_code, parts[1]),
                    "code": parts[2],
                    "name": parts[1],
                    "latest": parts[3],
                    "previous_close": parts[4],
                    "open": parts[5],
                    "high": parts[33] if high is not None else None,
                    "low": parts[34] if low is not None else None,
                    "volume": parts[6],
                    "amount": parts[37] if len(parts) > 37 else None,
                    "pct_change": pct_change,
                    "change": change,
                }
            )
        return quotes

    def _to_float(self, val: str) -> float | None:
        """安全转换为float。"""
        try:
            return float(val) if val else None
        except (ValueError, TypeError):
            return None


# ──────────────────────────────────────────
# 新浪 Fetcher (priority=2, 备用)
# ──────────────────────────────────────────

class SinaFetcher(BaseFetcher):
    """新浪财经行情获取器。

    API: https://hq.sinajs.cn/list={codes}
    特点: 备用接口，覆盖大部分A股。
    """

    name = "sina"
    priority = 2
    timeout = 10.0

    def fetch(self, targets: dict[str, str]) -> FetcherOutput:
        if not targets:
            return FetcherOutput(source="sina", error="empty targets")

        started = time_module.perf_counter()
        sina_codes = []
        code_to_target: dict[str, tuple[str, str]] = {}  # sina_code -> (label, secid)

        for label, secid in targets.items():
            sc = self._to_sina_code(secid)
            if sc:
                sina_codes.append(sc)
                code_to_target[sc] = (label, secid)

        if not sina_codes:
            return FetcherOutput(source="sina", error="no valid codes")

        try:
            url = f"https://hq.sinajs.cn/list={','.join(sina_codes)}"
            data = self._http_get(url, encoding="gbk")
            quotes = self._parse_data(data, code_to_target)
        except Exception as exc:
            latency = round((time_module.perf_counter() - started) * 1000, 1)
            return FetcherOutput(source="sina", error=str(exc), latency_ms=latency)

        latency = round((time_module.perf_counter() - started) * 1000, 1)
        return FetcherOutput(
            source="sina",
            data={"quotes": quotes},
            latency_ms=latency,
            quotes_count=len(quotes),
        )

    def _to_sina_code(self, secid: str) -> str | None:
        """将secid转换为新浪格式。"""
        code = str(secid).strip().upper()
        match = re.match(r"([10])\.(\d{6})", code)
        if match:
            mkt, num = match.groups()
            return f"{'sh' if mkt == '1' else 'sz'}{num}"
        match = re.match(r"(\d{6})\.(SH|SZ)", code)
        if match:
            num, mkt = match.groups()
            return f"{'sh' if mkt == 'SH' else 'sz'}{num}"
        if re.match(r"\d{6}$", code):
            if code.startswith(("600", "601", "603", "605", "688", "689")):
                return f"sh{code}"
            else:
                return f"sz{code}"
        return None

    def _parse_data(self, data: str, code_to_target: dict) -> list[dict]:
        """解析新浪返回数据。"""
        quotes = []
        for line in data.strip().split(";"):
            line = line.strip()
            if not line or "var hq_str_" not in line:
                continue

            match = re.match(r"var hq_str_(\w+)=\"(.+)\"", line)
            if not match:
                continue

            sina_code, content = match.groups()
            if not content or content == '"':
                continue

            parts = content.split(",")
            if len(parts) < 8:
                continue

            label, secid = code_to_target.get(sina_code, (sina_code, sina_code))
            name = parts[0]
            latest = self._to_float(parts[3])
            prev = self._to_float(parts[2])
            open_price = self._to_float(parts[1])
            high = self._to_float(parts[4])
            low = self._to_float(parts[5])
            volume = self._to_float(parts[8]) if len(parts) > 8 else None
            amount = self._to_float(parts[9]) if len(parts) > 9 else None

            pct_change = None
            change = None
            if latest is not None and prev is not None and prev > 0:
                pct_change = round((latest - prev) / prev * 100, 2)
                change = round(latest - prev, 2)

            quotes.append(
                {
                    "secid": secid,
                    "label": label,
                    "code": secid.split(".")[-1] if "." in secid else secid[-6:],
                    "name": name,
                    "latest": parts[3],
                    "previous_close": parts[2],
                    "open": parts[1],
                    "high": parts[4] if high is not None else None,
                    "low": parts[5] if low is not None else None,
                    "volume": parts[8] if len(parts) > 8 else None,
                    "amount": parts[9] if len(parts) > 9 else None,
                    "pct_change": pct_change,
                    "change": change,
                }
            )
        return quotes

    def _to_float(self, val: str) -> float | None:
        """安全转换为float。"""
        try:
            return float(val) if val else None
        except (ValueError, TypeError):
            return None


# ──────────────────────────────────────────
# 统一入口: DataFetcher
# ──────────────────────────────────────────

class DataFetcher:
    """统一行情数据获取器，管理多个 Fetcher 的注册和降级链。

    参考 AlphaAnalyst 的并发 Fetcher 设计，但当前为串行降级
    (未来可扩展为 asyncio.gather 并发)。

    Usage:
        fetcher = DataFetcher()
        result = fetcher.fetch({"平安银行": "0.000001", "贵州茅台": "1.600519"})
        # result: FetcherOutput with source="eastmoney" or "tencent" or "sina"
    """

    def __init__(self):
        self._fetchers: list[BaseFetcher] = []
        self._register_defaults()

    def _register_defaults(self) -> None:
        """注册默认的 Fetcher 集合。"""
        self.register(EastmoneyFetcher())
        self.register(TencentFetcher())
        self.register(SinaFetcher())

    def register(self, fetcher: BaseFetcher) -> None:
        """注册一个 Fetcher。"""
        self._fetchers.append(fetcher)
        # 按优先级排序
        self._fetchers.sort(key=lambda f: f.priority)

    def fetch(self, targets: dict[str, str]) -> FetcherOutput:
        """按优先级获取行情，失败则降级到下一个 Fetcher。

        Args:
            targets: {label: secid} 映射

        Returns:
            FetcherOutput: 第一个成功的 Fetcher 结果，或最后一个失败的错误
        """
        if not targets:
            return FetcherOutput(source="none", error="empty targets")

        last_error: FetcherOutput | None = None
        all_errors: list[str] = []

        for fetcher in self._fetchers:
            if not fetcher.is_available():
                continue

            try:
                result = fetcher.fetch(targets)
                # 成功标准: 无错误且获取到数据
                if result.error is None and result.quotes_count > 0:
                    return result
                # 部分成功也接受 (获取到一些数据)
                if result.quotes_count > 0:
                    return result
                # 完全失败，记录错误继续降级
                if result.error:
                    all_errors.append(f"{fetcher.name}: {result.error[:100]}")
                last_error = result
            except Exception as exc:
                all_errors.append(f"{fetcher.name}: {str(exc)[:100]}")

        # 所有 Fetcher 都失败
        return FetcherOutput(
            source="all_failed",
            error="; ".join(all_errors) if all_errors else "all fetchers failed",
            latency_ms=last_error.latency_ms if last_error else 0.0,
        )

    def fetch_all(self, targets: dict[str, str]) -> list[FetcherOutput]:
        """尝试所有 Fetcher，返回所有结果（用于调试/对比）。"""
        results = []
        for fetcher in self._fetchers:
            try:
                result = fetcher.fetch(targets)
                results.append(result)
            except Exception as exc:
                results.append(
                    FetcherOutput(
                        source=fetcher.name,
                        error=str(exc),
                    )
                )
        return results


# ── 并发 Fetch 包装器 ──────────────────────────

class ConcurrentDataFetcher:
    """并发数据获取器。

    用 ThreadPoolExecutor 并行拉取多种数据源（行情/龙虎榜/竞价），
    总延迟 = 最慢的单源延迟，非各源延迟之和。

    用法:
        cf = ConcurrentDataFetcher()
        results = cf.fetch_all_sources(config, quote_snapshot=None)
        # results = {"quotes": ..., "dragon_tiger": ..., "auction": ...}
    """

    def __init__(self, max_workers: int = 4, timeout: float = 10.0):
        self._max_workers = max_workers
        self._timeout = timeout

    def fetch_quotes(self, config: Any) -> dict:
        """获取行情数据（带缓存）。"""
        from qing_investment.monitor.cache import get_cache, TTL_QUOTES

        cache = get_cache()
        cache_key = "quotes:all"

        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        targets = collect_quote_targets(config)
        result = _get_fetcher().fetch(targets)

        # 标准化输出
        output = {
            "source": result.source,
            "quotes": result.data.get("quotes", []),
            "errors": [result.error] if result.error else [],
            "elapsed_ms": result.latency_ms,
        }

        cache.set(cache_key, output, ttl=TTL_QUOTES)
        return output

    def fetch_dragon_tiger(self, config: Any) -> dict:
        """获取龙虎榜数据（带缓存）。"""
        from qing_investment.monitor.cache import get_cache, TTL_DRAGON_TIGER

        cache = get_cache()
        cache_key = "dragon_tiger:all"

        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            import akshare as ak
            df = ak.stock_dzjy_mrmx(symbol="1")
            if df is None or df.empty:
                result = {"error": "empty dragon tiger data", "data": []}
            else:
                result = {"data": df.to_dict("records"), "count": len(df)}
        except Exception as exc:
            result = {"error": str(exc), "data": []}

        cache.set(cache_key, result, ttl=TTL_DRAGON_TIGER)
        return result

    def fetch_all_sources(
        self,
        config: Any,
        *,
        include_dragon_tiger: bool = False,
        include_auction: bool = False,
    ) -> dict:
        """并发拉取所有数据源。

        Args:
            config: MonitorConfig
            include_dragon_tiger: 是否拉龙虎榜
            include_auction: 是否拉竞价数据

        Returns:
            dict: {source: data, ...}
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed

        results: dict[str, dict] = {}
        tasks: dict[str, Callable[[], Any]] = {"quotes": lambda: self.fetch_quotes(config)}

        if include_dragon_tiger:
            tasks["dragon_tiger"] = lambda: self.fetch_dragon_tiger(config)

        with ThreadPoolExecutor(max_workers=self._max_workers) as executor:
            future_map = {
                executor.submit(fn): name for name, fn in tasks.items()
            }
            for future in as_completed(future_map, timeout=self._timeout):
                name = future_map[future]
                try:
                    results[name] = future.result()
                except Exception as exc:
                    results[name] = {"error": str(exc)}

        # 填充超时的源
        for name in tasks:
            if name not in results:
                results[name] = {"error": f"timeout (>={self._timeout}s)"}

        return results


# ──────────────────────────────────────────
# 向后兼容: 委托函数
# ──────────────────────────────────────────

# 全局单例 (lazy init)
_data_fetcher: DataFetcher | None = None


def _get_fetcher() -> DataFetcher:
    """获取全局 DataFetcher 单例。"""
    global _data_fetcher
    if _data_fetcher is None:
        _data_fetcher = DataFetcher()
    return _data_fetcher


def fetch_quotes(targets: dict[str, str]) -> dict:
    """向后兼容的委托函数，行为与 stock_monitor.fetch_quotes_with_fallback 一致。

    Returns:
        dict: {"source": str, "quotes": list, "errors": list, "elapsed_ms": float}
    """
    result = _get_fetcher().fetch(targets)
    return {
        "source": result.source,
        "quotes": result.data.get("quotes", []),
        "errors": [result.error] if result.error else [],
        "elapsed_ms": result.latency_ms,
    }


def fetch_quotes_with_fallback(targets: dict[str, str]) -> dict:
    """别名，与 fetch_quotes 行为一致。"""
    return fetch_quotes(targets)


# ──────────────────────────────────────────
# 股票代码工具函数
# ──────────────────────────────────────────


# 市场指数映射（与 stock_monitor.py 保持一致）
MARKET_INDEXES = {
    "上证指数": "1.000001",
    "深证成指": "0.399001",
    "创业板指": "0.399006",
    "科创50": "1.000688",
    "全A指数": "1.000985",
    "上证50": "1.000016",
    "沪深300": "1.000300",
    "中证500": "1.000905",
    "中证1000": "1.000852",
    "国证2000（微盘股代理）": "0.399303",  # 东财暂无中证2000(932000)，用国证2000观测微盘股边缘化
}


def parse_eastmoney_quote_rows(rows: list[dict], targets: dict[str, str]) -> list[dict]:
    """解析东财行情返回数据。"""
    reverse = {secid: label for label, secid in targets.items()}
    quotes = []
    for item in rows:
        code = item.get("f12")
        market = item.get("f13")
        secid = f"{market}.{code}" if market not in (None, "") and code else None
        label = reverse.get(secid or "")
        if not label:
            matches = [
                name for name, target in targets.items() if target.endswith(f".{code}")
            ]
            label = matches[0] if len(matches) == 1 else item.get("f14", "")

        quotes.append(
            {
                "secid": secid,
                "label": label,
                "code": code,
                "name": item.get("f14"),
                "latest": item.get("f2"),
                "pct_change": item.get("f3"),
                "change": item.get("f4"),
                "volume": item.get("f5"),
                "amount": item.get("f6"),
                "high": item.get("f15"),
                "low": item.get("f16"),
                "open": item.get("f17"),
                "previous_close": item.get("f18"),
            }
        )
    return quotes


def stock_code_to_secid(code: str) -> str | None:
    """将股票代码转换为 secid 格式。

    例如: 600519.SH -> 1.600519
          000001.SZ -> 0.000001
    """
    match = re.fullmatch(r"(\d{6})\.(SH|SZ)", code.strip().upper())
    if not match:
        return None
    pure, market = match.groups()
    return f"{'1' if market == 'SH' else '0'}.{pure}"


def collect_quote_targets(config: Any) -> dict[str, str]:
    """收集所有需要获取行情的标的。

    包括: 市场指数 + 持仓股票 + 观察列表股票 + 板块组成员
    """
    from qing_investment.monitor.context import position_rows, watchlist_stock_rows, sector_group_rows

    targets = dict(MARKET_INDEXES)
    seen_secids = set(targets.values())

    for row in position_rows(config) + watchlist_stock_rows(config):
        code = str(row.get("code", ""))
        secid = stock_code_to_secid(code)
        if secid and secid not in seen_secids:
            label = f"{row.get('name', '')}({code})"
            targets[label] = secid
            seen_secids.add(secid)

    for row in sector_group_rows(config):
        code = str(row.get("code", ""))
        secid = stock_code_to_secid(code)
        if secid and secid not in seen_secids:
            label = f"{row.get('group_name', '')}/{row.get('name', '')}({code})"
            targets[label] = secid
            seen_secids.add(secid)

    return targets


def _pure_stock_code(raw: str) -> str:
    """从 '600519.SH' 或 '600519' 中提取纯数字代码。"""
    match = re.search(r"(\d{6})", raw)
    return match.group(1) if match else raw


def _auction_snapshot(
    code: str,
    date_str: str,
    timeout: int = 10,
) -> dict:
    """获取个股竞价快照。

    在 09:25-09:26 调用，此时实时行情的 latest = 竞价撮合价，
    volume 包含竞价量。通过 DataFetcher 获取个股实时行情后提取。

    Args:
        code: 股票代码（6位纯数字或带后缀如 600519.SH）
        date_str: 日期字符串（如 '2026-06-14'）
        timeout: 超时秒数

    Returns:
        dict: {code: {open, volume, latest, high, low, pct_change, time}}
    """
    import time as _time

    pure_code = _pure_stock_code(code)
    secid = stock_code_to_secid(code)
    if not secid:
        return {}

    target = {pure_code: secid}
    result = _get_fetcher().fetch(target)
    quotes = result.data.get("quotes", [])

    for quote in quotes:
        q_code = _pure_stock_code(str(quote.get("code", "")))
        if q_code == pure_code:
            return {
                pure_code: {
                    "open": quote.get("open"),
                    "latest": quote.get("latest"),
                    "high": quote.get("high"),
                    "low": quote.get("low"),
                    "volume": quote.get("volume"),
                    "amount": quote.get("amount"),
                    "pct_change": quote.get("pct_change"),
                    "time": date_str,
                }
            }

    return {}
