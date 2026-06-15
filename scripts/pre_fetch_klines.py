#!/usr/bin/env python3
"""
开盘前 K线预拉取脚本。

执行时间：建议 06:30（A股开盘前）
功能：
  1. 读取 watchlist.yaml + positions.yaml，提取全部股票代码
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
    """从 watchlist.yaml 和 positions.yaml 提取股票代码，去重排序。"""
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

    return sorted(codes)


# ── 核心逻辑 ──
def main() -> int:
    # === 时区校验（云端关键）===
    now_cn = datetime.now(CN_TZ)

    # 必须在 A 股开盘前执行（06:00-09:15 CST）
    hour, minute = now_cn.hour, now_cn.minute
    in_window = (6 <= hour < 9) or (hour == 9 and minute < 15)

    if not in_window:
        # 手动执行时跳过时间检查（DEBUG模式）
        if os.environ.get("FORCE_KLINE_FETCH") != "1":
            print(
                f"[SKIP] 当前时间 {now_cn.strftime('%H:%M')} 不是预拉取窗口"
                f"（06:00-09:15 CST），跳过执行。"
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
        print("[WARN] 未提取到任何股票代码，检查 watchlist.yaml/positions.yaml")
        return 0

    print(f"[{now_cn.strftime('%H:%M')}] 预拉取 {total} 只标的日K线（{DAYS_TO_FETCH}日）...")

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
                    klines = fetch_stock_kline(code, days=DAYS_TO_FETCH)
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
                print(f"  ✅ {code}: {len(klines)} 根K线")
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

        # 进度报告
        if batch_num % 5 == 0 or batch_num == total_batches:
            progress = min(i + BATCH_SIZE, total)
            print(
                f"  ... 进度 {progress}/{total}"
                f" (✅{success_count} ❌{fail_count} ⚠️{skip_count})"
            )

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
