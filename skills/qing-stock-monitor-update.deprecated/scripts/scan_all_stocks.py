#!/usr/bin/env python3
"""
扫描项目中所有产业板块提到的核心标的，轮询获取实时行情+历史K线，
结合 strategy_pack 中的介入区间 + 技术分析，判断今天是否适合买入。

技术分析维度：
1. 均线系统（5/10/20日均线，判断多头/空头/缠绕）
2. 支撑位/压力位（近期20日高点/低点）
3. 回撤幅度（从近期高点回撤百分比）
4. 量价关系（今日量能 vs 20日均量）
5. K线形态（长下影、阳线反包、十字星、大阳线/大阴线、连续下跌后收阳）
6. 综合评分（strong_buy/buy/neutral/sell/strong_sell）

用法:
    cd ~/learning-investment-strategies
    venv/bin/python3 skills/qing-stock-monitor-update/scripts/scan_all_stocks.py
"""

from __future__ import annotations

import json
import re
import sys
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

# ── 路径 ──
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
CONFIG_DIR = PROJECT_ROOT / "config" / "stock_monitor"

# ── 颜色 ──
C_GREEN = "\033[32m"
C_RED = "\033[31m"
C_YELLOW = "\033[33m"
C_CYAN = "\033[36m"
C_MAGENTA = "\033[35m"
C_RESET = "\033[0m"


def load_yaml(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def extract_all_codes_from_project() -> set[str]:
    """从 watchlist + strategy_pack 提取所有股票代码"""
    codes: set[str] = set()

    wl = load_yaml(CONFIG_DIR / "watchlist.yaml")
    for theme in wl.get("themes", []):
        for stock in theme.get("stocks", []):
            code = stock.get("code", "")
            if code:
                codes.add(normalize_code(code))

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
    """统一为 sh/sz + 数字 格式"""
    code = code.strip().upper()
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
    return code.lower()


def fetch_realtime_quotes(codes: list[str]) -> dict[str, dict]:
    """通过腾讯财经 API 批量获取实时行情"""
    all_data: dict[str, dict] = {}
    batch_size = 60

    for i in range(0, len(codes), batch_size):
        batch = codes[i : i + batch_size]
        tencent_codes = [to_tencent_format(c) for c in batch]
        url = f"https://qt.gtimg.cn/q={','.join(tencent_codes)}"

        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw = resp.read().decode("gb2312", errors="ignore")
        except Exception as e:
            print(f"[ERROR] 实时行情请求失败: {e}", file=sys.stderr)
            continue

        for line in raw.strip().split(";"):
            line = line.strip()
            if not line or "=" not in line:
                continue
            left, right = line.split("=", 1)
            right = right.strip().strip('"')
            if not right:
                continue

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


def fetch_history_kline(code: str, days: int = 60) -> list[dict] | None:
    """
    通过腾讯财经获取历史K线数据（前复权）
    返回: [{date, open, close, low, high, volume}, ...]
    
    腾讯K线字段顺序: k[0]=日期, k[1]=开盘, k[2]=收盘, k[3]=最高, k[4]=最低, k[5]=成交量
    """
    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = "2026-04-01"

    url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={code},day,{start_date},{end_date},{days},qfq"

    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        klines = data.get("data", {}).get(code, {}).get("qfqday", [])
        if not klines:
            klines = data.get("data", {}).get(code, {}).get("day", [])

        result = []
        for k in klines:
            if len(k) >= 6:
                result.append({
                    "date": k[0],
                    "open": float(k[1]),
                    "close": float(k[2]),
                    "high": float(k[3]),    # 腾讯格式: k[3]=最高
                    "low": float(k[4]),     # 腾讯格式: k[4]=最低
                    "volume": float(k[5]),
                })
        return result
    except Exception as e:
        print(f"[WARN] {code} 历史数据获取失败: {e}", file=sys.stderr)
        return None


def calc_ma(klines: list[dict], period: int) -> float | None:
    """计算简单移动平均线"""
    if len(klines) < period:
        return None
    closes = [k["close"] for k in klines[-period:]]
    return sum(closes) / len(closes)


def calc_avg_volume(klines: list[dict], period: int = 20) -> float | None:
    """计算平均成交量"""
    if len(klines) < period:
        return None
    volumes = [k["volume"] for k in klines[-period:]]
    return sum(volumes) / len(volumes)


def find_recent_high_low(klines: list[dict], days: int = 20) -> tuple[float, float]:
    """找近期高点和低点"""
    recent = klines[-days:] if len(klines) >= days else klines
    highs = [k["high"] for k in recent]
    lows = [k["low"] for k in recent]
    return max(highs), min(lows)


def analyze_technical(code: str, realtime: dict, klines: list[dict] | None) -> dict:
    """
    技术分析主函数
    返回技术分析结果字典
    """
    result = {
        "ma5": None,
        "ma10": None,
        "ma20": None,
        "ma_trend": "unknown",
        "support": None,
        "resistance": None,
        "retracement_pct": None,
        "volume_ratio": None,
        "volume_signal": "unknown",
        "candle_pattern": "unknown",
        "candle_score": 0,
        "overall_score": 0,
        "overall_signal": "neutral",
        "details": [],
    }

    if not klines or len(klines) < 5:
        result["details"].append("历史数据不足，无法技术分析")
        return result

    price = realtime["price"]
    today_open = realtime["open"]
    today_high = realtime["high"]
    today_low = realtime["low"]
    today_volume = realtime["volume"]

    # ── 1. 均线系统 ──
    result["ma5"] = calc_ma(klines, 5)
    result["ma10"] = calc_ma(klines, 10)
    result["ma20"] = calc_ma(klines, 20)

    if result["ma5"] and result["ma10"] and result["ma20"]:
        ma5, ma10, ma20 = result["ma5"], result["ma10"], result["ma20"]

        if price > ma5 > ma10 > ma20:
            result["ma_trend"] = "strong_bull"
            result["overall_score"] += 2
            result["details"].append(f"均线多头排列（价>MA5>MA10>MA20），强势")
        elif price > ma5 > ma10:
            result["ma_trend"] = "bull"
            result["overall_score"] += 1
            result["details"].append(f"短期均线多头（价>MA5>MA10），偏强")
        elif price < ma5 < ma10 < ma20:
            result["ma_trend"] = "strong_bear"
            result["overall_score"] -= 2
            result["details"].append(f"均线空头排列，弱势")
        elif price < ma5 < ma10:
            result["ma_trend"] = "bear"
            result["overall_score"] -= 1
            result["details"].append(f"短期均线空头，偏弱")
        else:
            result["ma_trend"] = "mixed"
            result["details"].append(f"均线缠绕，趋势不明（MA5={ma5:.1f}, MA10={ma10:.1f}, MA20={ma20:.1f}）")

        # 价格与MA20的关系（中期趋势）
        if price > ma20 * 1.05:
            result["details"].append(f"股价高于MA20约 {(price/ma20-1)*100:.1f}%，中期偏强")
        elif price < ma20 * 0.95:
            result["details"].append(f"股价低于MA20约 {(1-price/ma20)*100:.1f}%，中期偏弱")

    # ── 2. 支撑位/压力位 + 回撤幅度 ──
    recent_high, recent_low = find_recent_high_low(klines, 20)
    result["support"] = recent_low
    result["resistance"] = recent_high

    if recent_high > 0:
        result["retracement_pct"] = (recent_high - price) / recent_high * 100
        if result["retracement_pct"] > 20:
            result["overall_score"] += 1
            result["details"].append(f"从近期高点回撤 {result['retracement_pct']:.1f}%，调整较充分")
        elif result["retracement_pct"] < 5:
            result["overall_score"] -= 1
            result["details"].append(f"从近期高点仅回撤 {result['retracement_pct']:.1f}%，仍在高位")

    # ── 3. 量价关系 ──
    avg_vol = calc_avg_volume(klines, 20)
    if avg_vol and today_volume > 0:
        result["volume_ratio"] = today_volume / avg_vol
        if result["volume_ratio"] > 1.5:
            result["volume_signal"] = "heavy_volume"
            result["overall_score"] += 1
            result["details"].append(f"放量（量能比20日均量高 {(result['volume_ratio']-1)*100:.0f}%）")
        elif result["volume_ratio"] < 0.6:
            result["volume_signal"] = "light_volume"
            result["overall_score"] -= 1
            result["details"].append(f"缩量（量能比20日均量低 {(1-result['volume_ratio'])*100:.0f}%）")
        else:
            result["volume_signal"] = "normal_volume"
            result["details"].append(f"量能正常（为20日均量的 {result['volume_ratio']*100:.0f}%）")

    # ── 4. K线形态分析 ──
    if len(klines) >= 2:
        prev = klines[-2]  # 昨日
        prev_close = prev["close"]

        # 今日K线实体
        body = abs(price - today_open)
        upper_shadow = today_high - max(price, today_open)
        lower_shadow = min(price, today_open) - today_low
        total_range = today_high - today_low

        if total_range > 0:
            # 长下影线（止跌信号）
            if lower_shadow / total_range > 0.5 and body / total_range < 0.3:
                result["candle_pattern"] = "long_lower_shadow"
                result["candle_score"] += 2
                result["overall_score"] += 2
                result["details"].append("长下影线，盘中回踩后拉回，止跌信号")

            # 阳线反包（强势信号）
            elif price > today_open and price > prev_close and today_open < prev_close:
                result["candle_pattern"] = "bullish_engulfing"
                result["candle_score"] += 2
                result["overall_score"] += 1
                result["details"].append("阳线反包，强势信号")

            # 十字星（变盘信号）
            elif body / total_range < 0.1:
                result["candle_pattern"] = "doji"
                result["candle_score"] += 1
                result["details"].append("十字星，变盘信号")

            # 大阳线
            elif price > today_open and (price - today_open) / prev_close > 0.05:
                result["candle_pattern"] = "big_bull"
                result["candle_score"] += 1
                result["overall_score"] += 1
                result["details"].append("大阳线，强势")

            # 大阴线
            elif price < today_open and (today_open - price) / prev_close > 0.05:
                result["candle_pattern"] = "big_bear"
                result["candle_score"] -= 1
                result["overall_score"] -= 1
                result["details"].append("大阴线，弱势")

        # 连续下跌后的阳线（反弹信号）
        if len(klines) >= 3:
            last3 = klines[-3:]
            if all(last3[i]["close"] < last3[i]["open"] for i in range(2)) and price > today_open:
                result["candle_score"] += 1
                result["overall_score"] += 1
                result["details"].append("连续阴线后收阳，反弹信号")

    # ── 5. 综合评分 ──
    score = result["overall_score"]
    if score >= 3:
        result["overall_signal"] = "strong_buy"
    elif score >= 1:
        result["overall_signal"] = "buy"
    elif score <= -3:
        result["overall_signal"] = "strong_sell"
    elif score <= -1:
        result["overall_signal"] = "sell"
    else:
        result["overall_signal"] = "neutral"

    return result


def get_entry_zones() -> dict[str, dict]:
    """从 strategy_pack.yaml 读取介入区间配置"""
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
    nums = re.findall(r"\d+\.?\d*", zone_str.replace("区间", ""))
    if len(nums) >= 2:
        return float(nums[0]), float(nums[1])
    return None


def check_buyable(code: str, info: dict, zone_cfg: dict, tech: dict) -> dict:
    """
    综合判断：介入区间 + 技术分析
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
            "detail": {"note": note, "tech": tech},
        }

    # 2. 无具体区间
    zone = parse_zone(zone_str)
    if zone is None:
        return {
            "status": "no_zone",
            "reason": f"无具体介入区间: {zone_str}",
            "detail": {"note": note, "tech": tech},
        }

    low_z, high_z = zone
    price = info["price"]
    low_today = info["low"]
    change_pct = info["change_pct"]

    # 3. 当前价在区间内
    in_zone = low_z <= price <= high_z
    touched_zone = low_z <= low_today <= high_z

    # 结合技术分析
    tech_signal = tech.get("overall_signal", "neutral")
    tech_score = tech.get("overall_score", 0)

    if in_zone:
        if tech_signal in ("strong_buy", "buy"):
            return {
                "status": "buyable",
                "reason": f"✅ 当前价在介入区间内 + 技术信号积极（{tech_signal}, 评分{tech_score}）",
                "detail": {
                    "zone_low": low_z,
                    "zone_high": high_z,
                    "price": price,
                    "low_today": low_today,
                    "change_pct": change_pct,
                    "position": position,
                    "note": note,
                    "tech": tech,
                },
            }
        elif tech_signal in ("strong_sell", "sell"):
            return {
                "status": "wait",
                "reason": f"⚠️ 当前价在介入区间内，但技术信号偏空（{tech_signal}, 评分{tech_score}），建议观望",
                "detail": {
                    "zone_low": low_z,
                    "zone_high": high_z,
                    "price": price,
                    "low_today": low_today,
                    "change_pct": change_pct,
                    "position": position,
                    "note": note,
                    "tech": tech,
                },
            }
        else:
            return {
                "status": "buyable",
                "reason": f"✅ 当前价在介入区间内（技术评分{tech_score}，中性）",
                "detail": {
                    "zone_low": low_z,
                    "zone_high": high_z,
                    "price": price,
                    "low_today": low_today,
                    "change_pct": change_pct,
                    "position": position,
                    "note": note,
                    "tech": tech,
                },
            }

    # 4. 盘中曾触及区间
    if touched_zone:
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
                "tech": tech,
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
                "tech": tech,
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
                "tech": tech,
            },
        }

    return {"status": "unknown", "reason": "未知状态", "detail": {"tech": tech}}


def print_tech_analysis(tech: dict, indent: str = "    "):
    """打印技术分析详情"""
    for detail in tech.get("details", []):
        print(f"{indent}• {detail}")

    ma5 = tech.get("ma5")
    ma10 = tech.get("ma10")
    ma20 = tech.get("ma20")
    if ma5 and ma10 and ma20:
        print(f"{indent}• 均线: MA5={ma5:.1f}, MA10={ma10:.1f}, MA20={ma20:.1f}")

    support = tech.get("support")
    resistance = tech.get("resistance")
    if support and resistance:
        print(f"{indent}• 近期支撑: {support:.1f}, 压力: {resistance:.1f}")

    retracement = tech.get("retracement_pct")
    if retracement is not None:
        print(f"{indent}• 从近期高点回撤: {retracement:.1f}%")

    vol_ratio = tech.get("volume_ratio")
    if vol_ratio is not None:
        print(f"{indent}• 量比: {vol_ratio:.2f}x")

    candle = tech.get("candle_pattern")
    if candle and candle != "unknown":
        print(f"{indent}• K线形态: {candle}")

    score = tech.get("overall_score", 0)
    signal = tech.get("overall_signal", "neutral")
    signal_color = C_GREEN if "buy" in signal else (C_RED if "sell" in signal else C_YELLOW)
    print(f"{indent}• 技术评分: {signal_color}{score} ({signal}){C_RESET}")


def main():
    print("=" * 100)
    print(f"【全项目标的扫描 + 技术分析】{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 100)

    # 1. 提取所有代码
    print("\n[1/5] 提取项目中所有标的...")
    codes = extract_all_codes_from_project()
    print(f"      共找到 {len(codes)} 个唯一标的")

    # 2. 读取介入区间配置
    print("\n[2/5] 读取 strategy_pack 介入区间...")
    zones = get_entry_zones()
    print(f"      共找到 {len(zones)} 个标的的介入配置")

    # 3. 获取实时行情
    print(f"\n[3/5] 获取实时行情（腾讯财经 API）...")
    codes_list = sorted(codes)
    quotes = fetch_realtime_quotes(codes_list)
    print(f"      成功获取 {len(quotes)} 个标的行情")

    # 4. 获取历史K线并做技术分析
    print(f"\n[4/5] 获取历史K线并进行技术分析...")
    tech_results: dict[str, dict] = {}
    for i, code in enumerate(codes_list):
        if code not in quotes:
            continue
        klines = fetch_history_kline(code, days=60)
        tech = analyze_technical(code, quotes[code], klines)
        tech_results[code] = tech
        if (i + 1) % 20 == 0:
            print(f"      已分析 {i + 1}/{len(codes_list)}...")

    # 5. 综合判断买入机会
    print(f"\n[5/5] 综合判断买入机会...")

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
        tech = tech_results.get(code, {})

        if not zone_cfg:
            no_zone.append((code, info, {"entry_zone": "无配置", "note": "未在 strategy_pack 中配置"}, tech))
            continue

        result = check_buyable(code, info, zone_cfg, tech)

        if result["status"] == "buyable":
            buyable.append((code, info, zone_cfg, result, tech))
        elif result["status"] == "avoid":
            avoid.append((code, info, zone_cfg, result, tech))
        elif result["status"] == "no_zone":
            no_zone.append((code, info, zone_cfg, result, tech))
        else:
            wait.append((code, info, zone_cfg, result, tech))

    # ── 输出结果 ──

    # 5.1 可买入
    print(f"\n{'=' * 100}")
    print(f"{C_GREEN}✅ 可买入标的（介入区间 + 技术信号积极）{C_RESET} — 共 {len(buyable)} 个")
    print("=" * 100)
    for code, info, zone_cfg, result, tech in buyable:
        d = result["detail"]
        print(f"\n  {C_GREEN}▶ {info['name']} ({code}){C_RESET}")
        print(f"    现价: {info['price']:.2f} | 涨幅: {info['change_pct']:+.2f}% | 最低: {info['low']:.2f}")
        print(f"    介入区间: [{d['zone_low']:.2f}-{d['zone_high']:.2f}] | 建议仓位: {d['position']}")
        print(f"    触发条件: {zone_cfg.get('trigger', 'N/A')}")
        print(f"    失效条件: {zone_cfg.get('invalidation', 'N/A')}")
        print(f"    {C_CYAN}【技术分析】{C_RESET}")
        print_tech_analysis(tech, indent="      ")
        if d.get("note"):
            print(f"    备注: {d['note'][:80]}...")

    # 5.2 等回踩
    print(f"\n{'=' * 100}")
    print(f"{C_YELLOW}⏳ 等回踩标的（未达介入区间或技术信号偏空）{C_RESET} — 共 {len(wait)} 个")
    print("=" * 100)
    for code, info, zone_cfg, result, tech in wait:
        d = result["detail"]
        print(f"\n  {C_YELLOW}▶ {info['name']} ({code}){C_RESET}")
        print(f"    现价: {info['price']:.2f} | 涨幅: {info['change_pct']:+.2f}% | 最低: {info['low']:.2f}")
        print(f"    {result['reason']}")
        if d.get("position"):
            print(f"    建议仓位: {d['position']}")
        print(f"    {C_CYAN}【技术分析】{C_RESET}")
        print_tech_analysis(tech, indent="      ")

    # 5.3 不介入
    print(f"\n{'=' * 100}")
    print(f"{C_RED}🚫 博主明确不介入{C_RESET} — 共 {len(avoid)} 个")
    print("=" * 100)
    for code, info, zone_cfg, result, tech in avoid:
        print(f"\n  {C_RED}▶ {info['name']} ({code}){C_RESET}")
        print(f"    现价: {info['price']:.2f} | 涨幅: {info['change_pct']:+.2f}%")
        print(f"    原因: {result['reason']}")
        if result["detail"].get("note"):
            print(f"    备注: {result['detail']['note'][:80]}...")

    # 5.4 无具体区间
    print(f"\n{'=' * 100}")
    print(f"{C_CYAN}❓ 无具体介入区间{C_RESET} — 共 {len(no_zone)} 个")
    print("=" * 100)
    for item in no_zone:
        if len(item) == 5:
            code, info, zone_cfg, result, tech = item
        else:
            code, info, zone_cfg, tech = item
            result = zone_cfg
        print(f"\n  {C_CYAN}▶ {info.get('name', code)} ({code}){C_RESET}")
        if isinstance(result, dict):
            print(f"    {result.get('reason', '无配置')}")
        else:
            print(f"    {result}")
        if tech and tech.get("overall_score") is not None:
            print(f"    技术评分: {tech['overall_score']} ({tech.get('overall_signal', 'neutral')})")

    # 5.5 无数据
    if no_data:
        print(f"\n{'=' * 100}")
        print(f"⚠️ 未获取到行情 — 共 {len(no_data)} 个")
        print("=" * 100)
        for code in no_data:
            print(f"  {code}")

    # ── 总结 ──
    print(f"\n{'=' * 100}")
    print("【总结】")
    print(f"  总标的数: {len(codes)}")
    print(f"  {C_GREEN}可买入: {len(buyable)}{C_RESET}")
    print(f"  {C_YELLOW}等回踩: {len(wait)}{C_RESET}")
    print(f"  {C_RED}不介入: {len(avoid)}{C_RESET}")
    print(f"  {C_CYAN}无区间: {len(no_zone)}{C_RESET}")
    print(f"  无数据: {len(no_data)}")
    print("=" * 100)


if __name__ == "__main__":
    main()
