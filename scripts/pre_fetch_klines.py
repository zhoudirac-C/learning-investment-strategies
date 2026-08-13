#!/usr/bin/env python3
"""
开盘前 K线预拉取脚本。

执行时间：建议 06:30（A股开盘前）及 15:00-16:30（收盘后补数据）
功能：
  1. 读取 watchlist.yaml + positions.yaml + stock_pool.yaml，提取全部股票代码
  2. 批量拉取日K线（90根），写入 SQLite 本地缓存
  3. 盘中 poll/Agent 优先读本地，不再重复调用 API

云端部署注意：
  - 必须设置 TZ=Asia/Shanghai，或服务器时区为 CST
  - 东财 API 对固定 IP 有限流，批次要小、间隔要长
  - 失败率 >20% 返回非0，cron 可据此告警
"""

from __future__ import annotations

import os
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ── 路径配置 ──
def _repo_root() -> Path:
    configured = os.environ.get("HERMES_REPO_ROOT")
    if configured:
        return Path(configured)
    # 从脚本位置推导：scripts/pre_fetch_klines.py → repo_root
    return Path(__file__).resolve().parents[1]


REPO_ROOT = _repo_root()
SRC_PATH = REPO_ROOT / "src"
CONFIG_PATH = REPO_ROOT / "config" / "stock_monitor"

# 确保 src 在 Python 路径中
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

import yaml
from qing_investment.kline_cache import init_db, save_klines, mark_cache_ready
from qing_investment.agent.tools.stock_data import fetch_stock_kline

# ── 常量 ──
CN_TZ = timezone(timedelta(hours=8))
BATCH_SIZE = 5           # 每批 5 只（云端固定 IP，保守策略）
DELAY_BETWEEN_BATCH = 3.0  # 批次间隔 3 秒
DELAY_BETWEEN_STOCK = 0.5  # 单只间隔 0.5 秒
MAX_RETRIES = 3
DAYS_TO_FETCH = 90


# ── 配置读取 ──
def _load_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _extract_stock_codes() -> list[str]:
    """从 watchlist.yaml、positions.yaml 和 stock_pool.yaml 提取股票代码，去重排序。"""
    codes: set[str] = set()

    # 1. watchlist
    watchlist = _load_yaml(CONFIG_PATH / "watchlist.yaml")
    for theme in watchlist.get("themes", []):
        for stock in theme.get("stocks", []):
            code = str(stock.get("code", "")).strip()
            if code:
                codes.add(code)

    # 2. positions（可能不存在，如云端首次部署）
    positions_path = CONFIG_PATH / "positions.yaml"
    if positions_path.exists():
        positions = _load_yaml(positions_path)
        for account in positions.get("accounts", []):
            for pos in account.get("positions", []):
                code = str(pos.get("code", "")).strip()
                if code:
                    codes.add(code)
    else:
        print("[INFO] positions.yaml 不存在，跳过持仓代码提取")

    # 3. entry_points（strategy_pack.yaml 中的观察标的）
    strategy_pack = _load_yaml(CONFIG_PATH / "strategy_pack.yaml")
    for ep in strategy_pack.get("entry_points", []):
        code = str(ep.get("code", "")).strip()
        if code:
            codes.add(code)

    # 4. stock_pool（方向候选池）
    stock_pool = _load_yaml(CONFIG_PATH / "stock_pool.yaml")
    for stock in stock_pool.get("stocks", []):
        code = str(stock.get("code", "")).strip()
        if code:
            codes.add(code)

    return sorted(codes)


def _watchlist_codes() -> set[str]:
    """提取 watchlist 的核心股票代码"""
    watchlist = _load_yaml(CONFIG_PATH / "watchlist.yaml")
    codes: set[str] = set()
    for theme in watchlist.get("themes", []):
        for stock in theme.get("stocks", []):
            code = str(stock.get("code", "")).strip()
            if code:
                codes.add(code)
    return codes


# ── 核心逻辑 ──
def main() -> int:
    # === 时区校验（云端关键）===
    now_cn = datetime.now(CN_TZ)
    today_str = now_cn.strftime("%Y-%m-%d")

    # 有效执行窗口：开盘前 06:00-09:15 或收盘后 15:00-16:30（CST）
    hour, minute = now_cn.hour, now_cn.minute
    pre_open_window = (6 <= hour < 9) or (hour == 9 and minute < 15)
    post_close_window = (hour == 15) or (hour == 16 and minute <= 30)
    in_window = pre_open_window or post_close_window

    # === 缓存就绪检查：今天已预拉取过则跳过 ===
    # 注意：收盘后窗口必须强制补拉（覆盖当日收盘价），早盘 ready 标记不能拦收盘后补拉。
    # 2026-08-13 实测：早盘 08:30 mark ready 后，15:35 收盘补拉被 is_cache_ready 跳过，
    # 导致 stock_pool 个股 K 线停在 T-1，盲判 build_daily_pack 的 stocks/directions 全空。
    if not os.environ.get("FORCE_KLINE_FETCH") and not post_close_window:
        from qing_investment.kline_cache import is_cache_ready
        if is_cache_ready(today_str):
            print(f"[SKIP] {today_str} K线预拉取已完成，跳过（如需强制重跑设 FORCE_KLINE_FETCH=1）")
            return 0

    if not in_window:
        # 手动执行时跳过时间检查（DEBUG模式）
        if os.environ.get("FORCE_KLINE_FETCH") != "1":
            print(
                f"[SKIP] 当前时间 {now_cn.strftime('%H:%M')} 不是预拉取窗口"
                f"（06:00-09:15 或 15:00-16:30 CST），跳过执行。"
            )
            return 0

    # 环境变量提示
    tz_env = os.environ.get("TZ", "")
    if tz_env and tz_env != "Asia/Shanghai":
        print(f"[WARN] TZ={tz_env}，建议设置为 Asia/Shanghai")

    # === 初始化 ===
    init_db()
    codes = _extract_stock_codes()
    total = len(codes)

    if not codes:
        print("[WARN] 未提取到任何股票代码，检查 watchlist.yaml/positions.yaml/stock_pool.yaml")
        return 0

    print(f"[{now_cn.strftime('%H:%M')}] 预拉取 {total} 只标的日K线（{DAYS_TO_FETCH}日）...")

    # ── 数量级警告 ──
    if total > 100 and pre_open_window:
        print(f"  ↪ 标的数 {total} 较多，仅拉取 watchlist 核心标的（约63只），其余按需触达")
        codes = [c for c in codes if c in _watchlist_codes()]
        total = len(codes)
        print(f"  ↪ 调整后: {total} 只")

    # ── TDX 连通性探测 ──
    # TDX 服务器在电信/联通机房，腾讯云环境常连不上
    # 提前测一次，连不上则跳过 TDX 直接走腾讯 API（每只省 ~15s 超时等待）
    _tdx_available = True
    try:
        from qing_investment.tdx_market import TdxClient, TdxMarket
        # 创建一个短超时客户端（3s 而非默认 15s），快速失败
        probe_client = TdxClient(connect_timeout=3.0, max_attempts=2)
        probe_mkt = TdxMarket(client=probe_client)
        probe_result = probe_mkt.get_kline("600519", category="daily", count=5)
        if not probe_result:
            print("  ⚠️ TDX 探测：连上但无数据 → 标记不可用")
            _tdx_available = False
        else:
            print(f"  ✅ TDX 探测成功（{probe_result[-1].get('date','?')} 数据）")
    except Exception as e:
        print(f"  ⚠️ TDX 不可用（{e!r}）→ 跳过 TDX 直接走腾讯 API")
        _tdx_available = False

    # === 分批拉取 ===
    success_count = 0
    fail_count = 0
    skip_count = 0

    for i in range(0, total, BATCH_SIZE):
        batch = codes[i : i + BATCH_SIZE]
        batch_num = i // BATCH_SIZE + 1
        total_batches = (total + BATCH_SIZE - 1) // BATCH_SIZE

        for code in batch:
            klines = None
            last_error = ""

            # 重试循环
            for attempt in range(1, MAX_RETRIES + 1):
                try:
                    if _tdx_available:
                        klines = fetch_stock_kline(code, days=DAYS_TO_FETCH, force_refresh=True)
                    else:
                        # TDX 不可用，跳过 TDX 直接走腾讯 → 东财降级
                        from qing_investment.agent.tools.stock_data import (
                            fetch_stock_kline_tencent,
                            fetch_stock_kline_eastmoney,
                        )
                        klines = fetch_stock_kline_tencent(code, days=DAYS_TO_FETCH)
                        if not klines:
                            klines = fetch_stock_kline_eastmoney(code, days=DAYS_TO_FETCH)
                    break
                except Exception as e:
                    last_error = str(e)
                    if attempt < MAX_RETRIES:
                        sleep_sec = 5 * attempt  # 5s, 10s
                        print(f"  ⚠️ {code}: 第{attempt}次失败，{sleep_sec}s后重试...")
                        time.sleep(sleep_sec)
                    else:
                        print(f"  ❌ {code}: 重试耗尽 ({last_error[:60]})")

            # 保存结果
            if klines:
                save_klines(code, klines)
                success_count += 1
            elif last_error:
                fail_count += 1
                # 写入空标记，避免后续反复拉取同一只失败票
                save_klines(code, [])
            else:
                skip_count += 1
                print(f"  ⚠️ {code}: 无数据（可能停牌/退市）")
                save_klines(code, [])

            time.sleep(DELAY_BETWEEN_STOCK)

        # 批次间延迟（防东财限流）
        if i + BATCH_SIZE < total:
            time.sleep(DELAY_BETWEEN_BATCH)

    # === 标记完成 ===
    today = now_cn.strftime("%Y-%m-%d")
    mark_cache_ready(today)

    fail_rate = fail_count / total if total else 0
    status = "OK" if fail_rate <= 0.2 else "WARN"

    print(
        f"[{now_cn.strftime('%H:%M')}] 预拉取完成 [{status}]:"
        f" ✅{success_count} ❌{fail_count} ⚠️{skip_count} / 总计{total}"
        f" (失败率 {fail_rate:.1%})"
    )

    return 0 if fail_rate <= 0.2 else 1


if __name__ == "__main__":
    raise SystemExit(main())
