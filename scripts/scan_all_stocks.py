#!/usr/bin/env python3
"""
扫描项目中所有产业板块提到的核心标的，轮询获取实时行情，
结合 strategy_pack 中的介入区间，判断今天适合买入的标的。

用法:
    cd ~/learning-investment-strategies
    venv/bin/python3 scripts/scan_all_stocks.py
"""

from __future__ import annotations

import json
import re
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

import yaml

# ── 路径 ──
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PROJECT_ROOT / "config" / "stock_monitor"

# ── 颜色 ──
C_GREEN = "\033[32m"
C_RED = "\033[31m"
C_YELLOW = "\033[33m"
C_CYAN = "\033[36m"
C_RESET = "\033[0m"


def load_yaml(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def extract_all_codes_from_project() -> set[str]:
    """
    从以下位置提取所有股票代码：
    1. config/stock_monitor/watchlist.yaml 中所有 themes[].stocks[].code
    2. config/stock_monitor/strategy_pack.yaml 中 sector_groups[].members[].code
    3. config/stock_monitor/strategy_pack.yaml 中 quant_entry_strategy.entry_points[].code
    """
    codes: set[str] = set()

    # 1. watchlist
    wl = load_yaml(CONFIG_DIR / "watchlist.yaml")
    for theme in wl.get("themes", []):
        for stock in theme.get("stocks", []):
            code = stock.get("code", "")
            if code:
                codes.add(normalize_code(code))

    # 2. strategy_pack sector_groups + entry_points
    sp = load_yaml(CONFIG_DIR / "strategy_pack.yaml")
    for group in sp.get("sector_groups", []):
        for member in group.get("members", []):
            code = member.get("code", "")
            if code:
                codes.add(normalize_code(code))
    for ep in sp.get("quant_entry_strategy", {}).get("entry_points", []):
        code = ep.get("code", "")
        if code:
            codes.add(normalize_code(code))

    return codes


def normalize_code(code: str) -> str:
    """
    统一为 sh/sz + 数字 格式。
    输入可能是: 600160.SH, sh600160, 600160
    """
    code = code.strip().upper()
    # 去掉 .SH / .SZ 后缀
    if ".SH" in code:
        return "sh" + code.replace(".SH", "").replace(".SZ", "").lower()
    if ".SZ" in code:
        return "sz" + code.replace(".SH", "").replace(".SZ", "").lower()
    if code.startswith("SH"):
        return "sh" + code[2:].lower()
    if code.startswith("SZ"):
        return "sz" + code[2:].lower()
    if code.startswith(("6", "5", "68")):
        return "sh" + code.lower()
    if code.startswith(("0", "3", "30")):
        return "sz" + code.lower()
    return code.lower()


def to_tencent_format(code: str) -> str:
    """sh600160 -> sh600160 (腾讯财经格式与我们的相同)"""
    return code.lower()


def fetch_realtime_quotes(codes: list[str]) -> dict[str, dict]:
    """
    通过腾讯财经 API 批量获取实时行情。
    每次最多 60 个，分批请求。
    """
    all_data: dict[str, dict] = {}
    batch_size = 60

    for i in range(0, len(codes), batch_size):
        batch = codes[i : i + batch_size]
        tencent_codes = [to_tencent_format(c) for c in batch]
        url = f"https://qt.gtimg.cn/q={','.join(tencent_codes)}"

        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                },
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw = resp.read().decode("gb2312", errors="ignore")
        except Exception as e:
            print(f"[ERROR] 请求失败: {e}", file=sys.stderr)
            continue

        # 解析返回数据
        for line in raw.strip().split(";"):
            line = line.strip()
            if not line or "=" not in line:
                continue
            left, right = line.split("=", 1)
            right = right.strip().strip('"')
            if not right:
                continue

            # 提取 code
            match = re.search(r"v_(sh\d+|sz\d+)", left)
            if not match:
                continue
            code = match.group(1)

            fields = right.split("~")
            if len(fields) < 45:
                continue

            try:
                name = fields[1]
                price = float(fields[3]) if fields[3] else 0.0
                pre_close = float(fields[4]) if fields[4] else 0.0
                open_price = float(fields[5]) if fields[5] else 0.0
                high = float(fields[33]) if fields[33] else 0.0
                low = float(fields[34]) if fields[34] else 0.0
                change_pct = float(fields[32]) if fields[32] else 0.0
                volume = int(fields[36]) if fields[36] else 0
                turnover = float(fields[37]) if fields[37] else 0.0

                all_data[code] = {
                    "name": name,
                    "price": price,
                    "pre_close": pre_close,
                    "open": open_price,
                    "high": high,
                    "low": low,
                    "change_pct": change_pct,
                    "volume": volume,
                    "turnover": turnover,
                }
            except (ValueError, IndexError):
                continue

    return all_data


def get_entry_zones() -> dict[str, dict]:
    """从 strategy_pack.yaml 读取介入区间配置。"""
    sp = load_yaml(CONFIG_DIR / "strategy_pack.yaml")
    zones: dict[str, dict] = {}

    for ep in sp.get("quant_entry_strategy", {}).get("entry_points", []):
        code = normalize_code(ep.get("code", ""))
        if not code:
            continue
        zones[code] = {
            "name": ep.get("name", ""),
            "entry_zone": ep.get("entry_zone", ""),
            "position_ratio": ep.get("position_ratio", ""),
            "trigger": ep.get("trigger", ""),
            "invalidation": ep.get("invalidation", ""),
            "note": ep.get("note", ""),
        }

    return zones


def parse_zone(zone_str: str) -> tuple[float, float] | None:
    """解析 '55-57区间' 或 '470-480' 为 (low, high)"""
    if not zone_str or zone_str in ("只观察不介入", "等分歧回踩", "等充分调整", "无"):
        return None
    # 提取数字
    nums = re.findall(r"\d+\.?\d*", zone_str.replace("区间", ""))
    if len(nums) >= 2:
        return float(nums[0]), float(nums[1])
    return None


def check_buyable(code: str, info: dict, zone_cfg: dict) -> dict:
    """
    判断标的是否适合买入。
    返回: {"status": "buyable|wait|avoid|no_zone", "reason": str, "detail": dict}
    """
    zone_str = zone_cfg.get("entry_zone", "")
    position = zone_cfg.get("position_ratio", "")
    note = zone_cfg.get("note", "")

    # 1. 明确不介入
    if zone_str in ("只观察不介入", "❌ 不介入") or str(position) in ("0", "0成", "'0'"):
        return {
            "status": "avoid",
            "reason": "博主明确不介入/只观察",
            "detail": {"note": note},
        }

    # 2. 无具体区间
    zone = parse_zone(zone_str)
    if zone is None:
        return {
            "status": "no_zone",
            "reason": f"无具体介入区间: {zone_str}",
            "detail": {"note": note},
        }

    low_z, high_z = zone
    price = info["price"]
    low_today = info["low"]
    change_pct = info["change_pct"]

    # 3. 当前价在区间内
    if low_z <= price <= high_z:
        return {
            "status": "buyable",
            "reason": f"✅ 当前价 {price} 在介入区间 [{low_z}-{high_z}] 内",
            "detail": {
                "zone_low": low_z,
                "zone_high": high_z,
                "price": price,
                "low_today": low_today,
                "change_pct": change_pct,
                "position": position,
                "note": note,
            },
        }

    # 4. 今天最低价曾触及区间（盘中回踩过）
    if low_z <= low_today <= high_z:
        return {
            "status": "wait",
            "reason": f"⏳ 盘中曾回踩到区间 [{low_z}-{high_z}]（最低 {low_today}），但现价已反弹",
            "detail": {
                "zone_low": low_z,
                "zone_high": high_z,
                "price": price,
                "low_today": low_today,
                "change_pct": change_pct,
                "position": position,
                "note": note,
            },
        }

    # 5. 尚未回踩到区间
    if price > high_z:
        gap = (price - high_z) / high_z * 100
        return {
            "status": "wait",
            "reason": f"⬆️ 尚未回踩（现价 {price}，区间 [{low_z}-{high_z}]，还差约 {gap:.1f}%）",
            "detail": {
                "zone_low": low_z,
                "zone_high": high_z,
                "price": price,
                "low_today": low_today,
                "change_pct": change_pct,
                "gap_pct": gap,
                "position": position,
                "note": note,
            },
        }

    # 6. 跌破区间
    if price < low_z:
        gap = (low_z - price) / low_z * 100
        return {
            "status": "wait",
            "reason": f"📉 已跌破介入区间（现价 {price} < {low_z}，偏离 {gap:.1f}%）",
            "detail": {
                "zone_low": low_z,
                "zone_high": high_z,
                "price": price,
                "low_today": low_today,
                "change_pct": change_pct,
                "gap_pct": gap,
                "position": position,
                "note": note,
            },
        }

    return {"status": "unknown", "reason": "未知状态", "detail": {}}


def main():
    print("=" * 90)
    print(f"【全项目标的扫描】{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 90)

    # 1. 提取所有代码
    print("\n[1/4] 提取项目中所有标的...")
    codes = extract_all_codes_from_project()
    print(f"      共找到 {len(codes)} 个唯一标的")

    # 2. 读取介入区间配置
    print("\n[2/4] 读取 strategy_pack 介入区间...")
    zones = get_entry_zones()
    print(f"      共找到 {len(zones)} 个标的的介入配置")

    # 3. 获取实时行情
    print(f"\n[3/4] 获取实时行情（腾讯财经 API）...")
    codes_list = sorted(codes)
    quotes = fetch_realtime_quotes(codes_list)
    print(f"      成功获取 {len(quotes)} 个标的行情")

    # 4. 判断买入机会
    print(f"\n[4/4] 分析买入机会...")

    buyable: list[tuple] = []
    wait: list[tuple] = []
    avoid: list[tuple] = []
    no_zone: list[tuple] = []
    no_data: list[str] = []

    for code in codes_list:
        if code not in quotes:
            no_data.append(code)
            continue

        info = quotes[code]
        zone_cfg = zones.get(code, {})

        if not zone_cfg:
            # 有行情但无策略配置
            no_zone.append((code, info, {"entry_zone": "无配置", "note": "未在 strategy_pack 中配置"}))
            continue

        result = check_buyable(code, info, zone_cfg)

        if result["status"] == "buyable":
            buyable.append((code, info, zone_cfg, result))
        elif result["status"] == "avoid":
            avoid.append((code, info, zone_cfg, result))
        elif result["status"] == "no_zone":
            no_zone.append((code, info, zone_cfg, result))
        else:
            wait.append((code, info, zone_cfg, result))

    # ── 输出结果 ──

    # 4.1 可买入
    print(f"\n{'=' * 90}")
    print(f"{C_GREEN}✅ 可买入标的（当前价在介入区间内）{C_RESET} — 共 {len(buyable)} 个")
    print("=" * 90)
    for code, info, zone_cfg, result in buyable:
        d = result["detail"]
        print(f"\n  {C_GREEN}▶ {info['name']} ({code}){C_RESET}")
        print(f"    现价: {info['price']:.2f} | 涨幅: {info['change_pct']:+.2f}% | 最低: {info['low']:.2f}")
        print(f"    介入区间: [{d['zone_low']:.2f}-{d['zone_high']:.2f}] | 建议仓位: {d['position']}")
        print(f"    触发条件: {zone_cfg.get('trigger', 'N/A')}")
        print(f"    失效条件: {zone_cfg.get('invalidation', 'N/A')}")
        if d.get("note"):
            print(f"    备注: {d['note'][:80]}...")

    # 4.2 等回踩
    print(f"\n{'=' * 90}")
    print(f"{C_YELLOW}⏳ 等回踩标的（尚未到介入区间或盘中已回踩过）{C_RESET} — 共 {len(wait)} 个")
    print("=" * 90)
    for code, info, zone_cfg, result in wait:
        d = result["detail"]
        print(f"\n  {C_YELLOW}▶ {info['name']} ({code}){C_RESET}")
        print(f"    现价: {info['price']:.2f} | 涨幅: {info['change_pct']:+.2f}% | 最低: {info['low']:.2f}")
        print(f"    {result['reason']}")
        if d.get("position"):
            print(f"    建议仓位: {d['position']}")

    # 4.3 不介入
    print(f"\n{'=' * 90}")
    print(f"{C_RED}🚫 博主明确不介入{C_RESET} — 共 {len(avoid)} 个")
    print("=" * 90)
    for code, info, zone_cfg, result in avoid:
        print(f"\n  {C_RED}▶ {info['name']} ({code}){C_RESET}")
        print(f"    现价: {info['price']:.2f} | 涨幅: {info['change_pct']:+.2f}%")
        print(f"    原因: {result['reason']}")
        if result["detail"].get("note"):
            print(f"    备注: {result['detail']['note'][:80]}...")

    # 4.4 无具体区间
    print(f"\n{'=' * 90}")
    print(f"{C_CYAN}❓ 无具体介入区间{C_RESET} — 共 {len(no_zone)} 个")
    print("=" * 90)
    for item in no_zone:
        if len(item) == 4:
            code, info, zone_cfg, result = item
        else:
            code, info, zone_cfg = item
            result = zone_cfg
        print(f"\n  {C_CYAN}▶ {info.get('name', code)} ({code}){C_RESET}")
        if isinstance(result, dict):
            print(f"    {result.get('reason', '无配置')}")
        else:
            print(f"    {result}")

    # 4.5 无数据
    if no_data:
        print(f"\n{'=' * 90}")
        print(f"⚠️ 未获取到行情 — 共 {len(no_data)} 个")
        print("=" * 90)
        for code in no_data:
            print(f"  {code}")

    # ── 总结 ──
    print(f"\n{'=' * 90}")
    print("【总结】")
    print(f"  总标的数: {len(codes)}")
    print(f"  {C_GREEN}可买入: {len(buyable)}{C_RESET}")
    print(f"  {C_YELLOW}等回踩: {len(wait)}{C_RESET}")
    print(f"  {C_RED}不介入: {len(avoid)}{C_RESET}")
    print(f"  {C_CYAN}无区间: {len(no_zone)}{C_RESET}")
    print(f"  无数据: {len(no_data)}")
    print("=" * 90)


if __name__ == "__main__":
    main()
