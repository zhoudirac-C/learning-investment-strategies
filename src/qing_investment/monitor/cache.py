"""监控引擎 — 内存缓存层 (Subtask 2)

TTL 缓存，支持行情/龙虎榜/竞价数据的时间敏感复用。

设计原则:
    - 无外部依赖（纯 dict + time）
    - TTL 过期自动失效
    - 上限控制防内存泄漏
    - 命中率可追踪
"""

from __future__ import annotations

import json
import time as time_module
from datetime import datetime
from pathlib import Path
from typing import Any


class CacheEntry:
    """缓存条目。"""

    __slots__ = ("value", "expires_at", "size")

    def __init__(self, value: Any, ttl: float):
        self.value = value
        self.expires_at = time_module.monotonic() + ttl
        self.size = 1

    def is_expired(self) -> bool:
        return time_module.monotonic() > self.expires_at

    @property
    def ttl_remaining(self) -> float:
        return max(0.0, self.expires_at - time_module.monotonic())


class DataCache:
    """TTL 内存缓存。

    用法:
        cache = DataCache(max_entries=1000)
        cache.set("quotes:600519", data, ttl=30)
        data = cache.get("quotes:600519")
    """

    def __init__(self, max_entries: int = 1000):
        self._data: dict[str, CacheEntry] = {}
        self._max_entries = max_entries
        self._hits = 0
        self._misses = 0
        self._sets = 0
        self._expired = 0
        self._evictions = 0

    # ── 核心接口 ──────────────────────────────

    def get(self, key: str) -> Any | None:
        """获取缓存值。过期条目自动视为未命中。"""
        entry = self._data.get(key)
        if entry is None:
            self._misses += 1
            return None
        if entry.is_expired():
            del self._data[key]
            self._misses += 1
            self._expired += 1
            return None
        self._hits += 1
        return entry.value

    def set(self, key: str, value: Any, ttl: float = 30.0) -> None:
        """设置缓存。

        Args:
            key: 缓存键，建议格式 '{data_type}:{code}'
            value: 缓存值
            ttl: 过期秒数（默认30秒）
        """
        self._evict_if_full()
        self._data[key] = CacheEntry(value, ttl)
        self._sets += 1

    def invalidate(self, pattern: str | None = None) -> int:
        """使缓存失效。

        Args:
            pattern: 前缀匹配模式，如 'quotes:' 使所有行情缓存失效。
                     None 时清空全部。

        Returns:
            int: 失效条目数
        """
        if pattern is None:
            count = len(self._data)
            self._data.clear()
            return count

        keys = [k for k in self._data if k.startswith(pattern)]
        for k in keys:
            del self._data[k]
        return len(keys)

    def get_or_set(
        self, key: str, factory, ttl: float = 30.0
    ) -> Any:
        """获取或创建缓存（cache-aside 模式）。"""
        cached = self.get(key)
        if cached is not None:
            return cached
        value = factory()
        self.set(key, value, ttl=ttl)
        return value

    # ── 统计 ──────────────────────────────────

    def stats(self) -> dict:
        """缓存统计。"""
        total = self._hits + self._misses
        return {
            "size": len(self._data),
            "max_entries": self._max_entries,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": round(self._hits / total, 3) if total > 0 else 0.0,
            "sets": self._sets,
            "expired": self._expired,
            "evictions": self._evictions,
        }

    def clear(self) -> None:
        """清空全部缓存。"""
        self._data.clear()

    # ── 内部 ──────────────────────────────────

    def _evict_if_full(self) -> None:
        """超过上限时，清除最旧的 25% 条目。"""
        if len(self._data) < self._max_entries:
            return

        # 按过期时间排序，淘汰最旧的
        sorted_keys = sorted(
            self._data.keys(),
            key=lambda k: self._data[k].expires_at,
        )
        evict_count = max(1, self._max_entries // 4)
        for k in sorted_keys[:evict_count]:
            del self._data[k]
            self._evictions += 1


# ── 单例 ──────────────────────────────────────

# 默认 TTL 常量
TTL_QUOTES = 30        # 行情缓存 30 秒
TTL_DRAGON_TIGER = 300  # 龙虎榜 5 分钟
TTL_AUCTION = 600       # 竞价数据 10 分钟

_default_cache: DataCache | None = None


def get_cache() -> DataCache:
    """获取全局缓存单例。"""
    global _default_cache
    if _default_cache is None:
        _default_cache = DataCache(max_entries=2000)
    return _default_cache


def reset_cache() -> None:
    """重置全局缓存（主要用于测试）。"""
    global _default_cache
    _default_cache = None


# ── 竞价缓存管理器 ──────────────────────────

class AuctionCache:
    """竞价数据缓存 — 内存+文件分层。

    当日数据走内存（快速读写），历史数据走 JSON 文件（持久化）。
    写入时同步更新两层。
    """

    def __init__(self, config_dir: str | Path | None = None):
        self._config_dir = Path(config_dir) if config_dir else Path.home() / ".hermes"
        self._cache_file = self._config_dir / "auction_cache.json"
        self._mem_cache: DataCache | None = None

    # ── 属性 ──

    @property
    def mem(self) -> DataCache:
        if self._mem_cache is None:
            self._mem_cache = DataCache(max_entries=500)
        return self._mem_cache

    # ── 公开接口 ──

    def load(self) -> dict:
        """读取竞价缓存（内存→文件回退）。"""
        cached = self.mem.get("auction:full")
        if cached is not None:
            return cached
        return self._load_file()

    def save(self, cache: dict) -> bool:
        """保存竞价缓存（内存+文件双写）。"""
        self.mem.set("auction:full", dict(cache), ttl=TTL_AUCTION)
        return self._save_file(cache)

    def update(self, auction_data: dict[str, dict], max_days: int = 30) -> None:
        """更新竞价缓存，追加当日数据。

        Args:
            auction_data: {code_pure: {volume, price, date}}
            max_days: 保留最近 N 天数据
        """
        cache = self.load()
        today = datetime.now().strftime("%Y-%m-%d")

        for code, data in auction_data.items():
            if code not in cache:
                cache[code] = []
            existing = [e for e in cache[code] if e.get("date") != today]
            existing.append({
                "date": today,
                "volume": data.get("volume"),
                "price": data.get("price") or data.get("latest"),
                "change_pct": data.get("change_pct") or data.get("pct_change"),
            })
            existing.sort(key=lambda e: e.get("date", ""), reverse=True)
            cache[code] = existing[:max_days]

        self.save(cache)

    def get_history(self, code: str, days: int = 5) -> list[dict]:
        """获取某只股票最近 N 天的竞价历史。"""
        cache = self.load()
        entries = cache.get(code, [])
        # memory cache recent data + file fallback
        today_entries = [e for e in entries if e.get("date") == datetime.now().strftime("%Y-%m-%d")]
        hist_entries = [e for e in entries if e.get("date") != datetime.now().strftime("%Y-%m-%d")]
        combined = today_entries + hist_entries
        return combined[:days]

    # ── 内部文件操作 ──

    def _load_file(self) -> dict:
        if self._cache_file.exists():
            try:
                return json.loads(self._cache_file.read_text(encoding="utf-8"))
            except Exception:
                return {}
        return {}

    def _save_file(self, cache: dict) -> bool:
        try:
            self._cache_file.write_text(
                json.dumps(cache, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            return True
        except Exception:
            return False
