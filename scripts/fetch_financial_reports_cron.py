#!/usr/bin/env python3
"""
财报数据预拉取定时任务。

执行时间：建议每周一 23:00（A股收盘后、财报季低频更新）
功能：
  1. 读取 watchlist.yaml + positions.yaml + stock_pool.yaml，提取全部股票代码
  2. 批量拉取每只股票近 2 年三大报表（利润表、资产负债表、现金流量表）
  3. 写入 SQLite 本地缓存（与 K 线共用 kline_cache.db）

环境变量：
  - FORCE_FINANCIAL_FETCH=1：跳过周一 23:00 窗口检查，用于手动重跑
  - HERMES_REPO_ROOT：指定项目根目录
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
    return Path(__file__).resolve().parents[1]


REPO_ROOT = _repo_root()
SRC_PATH = REPO_ROOT / "src"
CONFIG_PATH = REPO_ROOT / "config" / "stock_monitor"

if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

import yaml
from qing_investment.kline_cache import init_db, save_financial_reports
from qing_investment.agent.tools.stock_data import fetch_financial_reports

# ── 常量 ──
CN_TZ = timezone(timedelta(hours=8))
FINANCIAL_YEARS = 2
DELAY_BETWEEN_STOCK = 0.3  # 每只间隔 0.3 秒，避免 akshare/东财限流


# ── 配置读取 ──
def _load_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _extract_stock_codes() -> list[str]:
    """从 watchlist.yaml、positions.yaml 和 stock_pool.yaml 提取股票代码，去重排序。"""
    codes: set[str] = set()

    watchlist = _load_yaml(CONFIG_PATH / "watchlist.yaml")
    for theme in watchlist.get("themes", []):
        for stock in theme.get("stocks", []):
            code = str(stock.get("code", "")).strip()
            if code:
                codes.add(code)

    positions_path = CONFIG_PATH / "positions.yaml"
    if positions_path.exists():
        positions = _load_yaml(positions_path)
        for account in positions.get("accounts", []):
            for pos in account.get("positions", []):
                code = str(pos.get("code", "")).strip()
                if code:
                    codes.add(code)

    strategy_pack = _load_yaml(CONFIG_PATH / "strategy_pack.yaml")
    for ep in strategy_pack.get("entry_points", []):
        code = str(ep.get("code", "")).strip()
        if code:
            codes.add(code)

    stock_pool = _load_yaml(CONFIG_PATH / "stock_pool.yaml")
    for stock in stock_pool.get("stocks", []):
        code = str(stock.get("code", "")).strip()
        if code:
            codes.add(code)

    return sorted(codes)


def main() -> int:
    now_cn = datetime.now(CN_TZ)

    # 默认仅在周一 23:00 前后执行；手动重跑需设置 FORCE_FINANCIAL_FETCH=1
    weekday, hour = now_cn.weekday(), now_cn.hour
    in_window = weekday == 0 and 22 <= hour <= 23
    if not in_window and os.environ.get("FORCE_FINANCIAL_FETCH") != "1":
        print(
            f"[SKIP] 当前时间 {now_cn.strftime('%Y-%m-%d %H:%M')} 不是财报预拉取窗口"
            f"（周一 22:00-23:59），跳过执行。"
        )
        return 0

    init_db()
    codes = _extract_stock_codes()
    total = len(codes)

    if not codes:
        print("[WARN] 未提取到任何股票代码")
        return 0

    print(f"[{now_cn.strftime('%H:%M')}] 开始预拉取 {total} 只标的近 {FINANCIAL_YEARS} 年财报数据...")

    success_count = 0
    fail_count = 0

    for idx, code in enumerate(codes, 1):
        try:
            reports = fetch_financial_reports(code, years=FINANCIAL_YEARS)
            saved_any = False
            for statement_type, records in reports.items():
                if records:
                    save_financial_reports(code, records, statement_type)
                    saved_any = True
            if saved_any:
                success_count += 1
                print(f"  ✅ {code}: 三大报表已保存")
            else:
                fail_count += 1
                print(f"  ⚠️ {code}: 无财报数据")
        except Exception as e:
            fail_count += 1
            print(f"  ❌ {code}: 财报拉取失败 ({str(e)[:60]})")

        if idx % 10 == 0 or idx == total:
            print(f"  ... 进度 {idx}/{total} (✅{success_count} ❌{fail_count})")

        time.sleep(DELAY_BETWEEN_STOCK)

    fail_rate = fail_count / total if total else 0
    status = "OK" if fail_rate <= 0.2 else "WARN"

    print(
        f"[{now_cn.strftime('%H:%M')}] 财报预拉取完成 [{status}]:"
        f" ✅{success_count} ❌{fail_count} / 总计{total}"
        f" (失败率 {fail_rate:.1%})"
    )

    return 0 if fail_rate <= 0.2 else 1


if __name__ == "__main__":
    raise SystemExit(main())
