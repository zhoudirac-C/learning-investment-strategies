"""监控引擎 — 分析工具模块。

包含技术指标计算、龙虎榜数据分析、席位分类等函数。
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import TYPE_CHECKING

# 导入依赖
from qing_investment.monitor.context import (
    _pure_stock_code,
    _to_float,
    parse_price_zone,
    _format_zone,
    position_rows,
)

if TYPE_CHECKING:
    import pandas as pd
    from qing_investment.monitor.config import MonitorConfig

CN_TZ = timezone(timedelta(hours=8))


def _compute_vs_ma(close: float, klines: list[dict], ma_days: int) -> float | None:
    """计算收盘价相对 MA 的位置百分比。"""
    closes = [d.get("close") for d in klines if d.get("close") is not None]
    if len(closes) < ma_days:
        return None
    ma = sum(closes[-ma_days:]) / ma_days
    return round((close - ma) / ma * 100, 1) if ma else None


def _compute_near5d_return(klines: list[dict]) -> float | None:
    """计算近5个交易日的累计涨跌幅。"""
    if len(klines) < 2:
        return None
    closes = [d.get("close") for d in klines[-6:] if d.get("close") is not None]
    if len(closes) < 2:
        return None
    return round((closes[-1] - closes[0]) / closes[0] * 100, 1)


def _compute_volume_ratio(today_volume: float, klines: list[dict]) -> float | None:
    """计算今日量/近5日均量的比值。"""
    vols = [d.get("volume", 0) for d in klines[-6:-1] if d.get("volume")]
    if not vols:
        return None
    avg_5d = sum(vols) / len(vols)
    return round(today_volume / avg_5d, 2) if avg_5d else None


def _check_entry_zone_distance(code: str, close: float, config: "MonitorConfig") -> dict:
    """判断收盘价距 entry_zone 的距离。"""
    result = {"entry_zone_distance": None, "entry_zone_range": None}

    for ep in config.strategy_pack.get("entry_points", []):
        ep_code = _pure_stock_code(str(ep.get("code", "")))
        if ep_code == _pure_stock_code(code):
            zone_raw = ep.get("entry_zone") or ""
            zone = parse_price_zone(zone_raw)
            if zone:
                result["entry_zone_range"] = _format_zone(zone)
                if close < zone[0]:
                    result["entry_zone_distance"] = "below"
                elif close <= zone[1]:
                    result["entry_zone_distance"] = "in"
                else:
                    result["entry_zone_distance"] = "above"
            return result

    for theme in config.watchlist.get("themes", []):
        for stock in theme.get("stocks", []):
            if _pure_stock_code(str(stock.get("code", ""))) == _pure_stock_code(code):
                ez = stock.get("entry_zone", {}) or {}
                zone = parse_price_zone(ez.get("price_range", ""))
                if zone:
                    result["entry_zone_range"] = _format_zone(zone)
                    if close < zone[0]:
                        result["entry_zone_distance"] = "below"
                    elif close <= zone[1]:
                        result["entry_zone_distance"] = "in"
                    else:
                        result["entry_zone_distance"] = "above"
                return result

    return result


# ── 龙虎榜数据采集（akshare 东方财富接口）──

_SEAT_TYPE_KEYWORDS = {
    "深股通专用": "外资",
    "沪股通专用": "外资",
    "机构专用": "机构",
    "中信证券股份有限公司": "游资",
    "中国国际金融股份有限公司": "量化",
    "量化": "量化",
}


def _classify_seat_type(name: str) -> str:
    """根据营业部名称判断席位性质。"""
    for keyword, seat_type in _SEAT_TYPE_KEYWORDS.items():
        if keyword in name:
            return seat_type
    return "游资"


def _classify_top_buy_behavior(
    df_buy: "pd.DataFrame",
    df_sell: "pd.DataFrame",
) -> str:
    """判断买一席位的次日行为倾向。

    买一的行为：
    - 锁仓：买一金额 >> 卖一金额，且净额大额为正
    - 做T：买一出现在卖出榜（买卖双向操作）
    - 出局：卖一金额大，且买一不在买入榜前5
    - 加仓：买一金额远超其他席位的卖出
    """
    try:
        top_buy_name = str(df_buy.iloc[0]["交易营业部名称"])
        top_buy_net = float(df_buy.iloc[0]["净额"])
        top_sell_net = float(df_sell.iloc[0]["净额"]) if not df_sell.empty else 0

        buy_names = set(df_buy["交易营业部名称"].tolist())
        sell_names = set(df_sell["交易营业部名称"].tolist())
        overlap = buy_names & sell_names

        if top_buy_name in overlap:
            return "做T"
        elif top_buy_net > abs(top_sell_net) * 3:
            return "锁仓"
        elif top_buy_net > abs(top_sell_net) * 1.5:
            return "加仓"
        elif top_buy_net < abs(top_sell_net) * 0.5:
            return "出局"
        else:
            return "混合"
    except Exception:
        return "unknown"


def _assess_board_quality(df_buy: "pd.DataFrame", df_sell: "pd.DataFrame") -> str:
    """评估封板质量。"""
    try:
        total_buy = float(df_buy["净额"].sum()) if "净额" in df_buy.columns else 0
        total_sell = float(df_sell["净额"].sum()) if "净额" in df_sell.columns else 0
        net = total_buy

        if net > 0 and net > abs(total_sell) * 2:
            return "strong"
        elif net > 0:
            return "medium"
        else:
            return "weak"
    except Exception:
        return "NA"


def _fetch_dragon_tiger_data(
    code: str,
    date_str: str,
    timeout: int = 10,
) -> dict:
    """获取个股龙虎榜数据（akshare 东方财富接口）。

    Args:
        code: 6位股票代码
        date_str: 日期 "2026-06-11" 或 "20260611"
        timeout: 超时秒数

    Returns:
        dict: {
            "dragon_tiger_net": str,
            "dt_seat_type": str,
            "dt_top_buy_behavior": str,
            "dt_is_pure_hot_money": bool,
            "board_quality": str,
            "_error": str,
        }
    """
    result = {
        "dragon_tiger_net": None,
        "dt_seat_type": None,
        "dt_top_buy_behavior": None,
        "dt_is_pure_hot_money": None,
        "board_quality": None,
    }

    try:
        date_compact = date_str.replace("-", "")
        import akshare as ak

        df_buy = ak.stock_lhb_stock_detail_em(symbol=code, date=date_compact, flag="买入")
        df_sell = ak.stock_lhb_stock_detail_em(symbol=code, date=date_compact, flag="卖出")

        if df_buy is None:
            result["_error"] = "当日未上榜"
            return result
        try:
            if df_buy.empty:
                result["_error"] = "当日未上榜"
                return result
        except Exception:
            pass

        # ── 净额 ──
        total_net = float(df_buy["净额"].sum())
        if abs(total_net) >= 100_000_000:
            net_str = f"{'+' if total_net >= 0 else ''}{total_net / 100_000_000:.2f}亿"
        elif abs(total_net) >= 10_000:
            net_str = f"{'+' if total_net >= 0 else ''}{total_net / 10_000:.0f}万"
        else:
            net_str = f"{total_net:.0f}"
        result["dragon_tiger_net"] = net_str

        # ── 席位类型分布 ──
        seat_types = set()
        for _, row in df_buy.iterrows():
            seat_types.add(_classify_seat_type(str(row.get("交易营业部名称", ""))))
        for _, row in df_sell.iterrows():
            seat_types.add(_classify_seat_type(str(row.get("交易营业部名称", ""))))

        seat_types.discard("游资")
        if not seat_types:
            result["dt_seat_type"] = "游资"
            result["dt_is_pure_hot_money"] = True
        elif len(seat_types) == 1:
            result["dt_seat_type"] = list(seat_types)[0]
            result["dt_is_pure_hot_money"] = list(seat_types)[0] == "游资"
        else:
            result["dt_seat_type"] = "+".join(sorted(seat_types))
            result["dt_is_pure_hot_money"] = False

        # ── 买一行为 ──
        result["dt_top_buy_behavior"] = _classify_top_buy_behavior(df_buy, df_sell)

        # ── 封板质量 ──
        result["board_quality"] = _assess_board_quality(df_buy, df_sell)

    except ImportError:
        result["_error"] = "akshare not installed"
    except Exception as e:
        result["_error"] = str(e)

    return result


def _fetch_daily_dragon_tiger_board(
    date_str: str,
    timeout: int = 15,
) -> dict:
    """获取当日全市场龙虎榜总榜（akshare 东方财富接口）。

    数据源：stock_lhb_detail_em
    通常16:00-17:00发布当日数据，因此仅在 >= 16:00 时尝试获取。

    Returns:
        {
            "available": bool,
            "board": [{"code","name","net_buy","reason","pct_change","turnover_rate"}, ...],
            "fetched_at": str,
            "_error": str | None,
        }
    """
    result: dict = {
        "available": False,
        "board": [],
        "fetched_at": datetime.now(tz=CN_TZ).isoformat(),
        "_error": None,
    }

    try:
        import akshare as ak

        date_compact = date_str.replace("-", "")
        df = ak.stock_lhb_detail_em(start_date=date_compact, end_date=date_compact)

        if df is None or df.empty:
            result["_error"] = "当日龙虎榜数据未发布或为空"
            return result

        board = []
        for _, row in df.iterrows():
            net_raw = str(row.get("龙虎榜净买额", "0"))
            entry = {
                "code": str(row.get("代码", "")).strip(),
                "name": str(row.get("名称", "")),
                "net_buy": _format_net_buy_str(net_raw),
                "reason": str(row.get("上榜原因", "")),
                "pct_change": _to_float(row.get("涨跌幅")),
                "turnover_rate": _to_float(row.get("换手率")),
            }
            board.append(entry)

        result["board"] = board
        result["available"] = True
        result["_error"] = None

    except ImportError:
        result["_error"] = "akshare not installed"
    except Exception as e:
        result["_error"] = str(e)

    return result


def _filter_dragon_tiger_board(
    board: list[dict],
    config: "MonitorConfig",
) -> dict:
    """对全市场龙虎榜总榜做三层交叉过滤。

    Args:
        board: _fetch_daily_dragon_tiger_board() 返回的 board list
        config: MonitorConfig

    Returns:
        {
            "watch_dt_items": [str],
            "dt_nettop5": [dict],
            "dt_sector_summary": {str: dict},
        }
    """
    result = {
        "watch_dt_items": [],
        "dt_nettop5": [],
        "dt_sector_summary": {},
    }

    if not board:
        return result

    # ── 构建持仓+观察池的 code 集合 ──
    watch_codes: set[str] = set()
    for pos in position_rows(config):
        watch_codes.add(_pure_stock_code(str(pos.get("code", ""))))
    for theme in config.watchlist.get("themes", []):
        for stock in theme.get("stocks", []):
            watch_codes.add(_pure_stock_code(str(stock.get("code", ""))))

    # ── 构建 code→theme_ids 映射 ──
    code_to_themes: dict[str, list[str]] = {}
    for theme in config.watchlist.get("themes", []):
        tid = theme.get("id", "")
        for stock in theme.get("stocks", []):
            c = _pure_stock_code(str(stock.get("code", "")))
            if c:
                code_to_themes.setdefault(c, []).append(tid)

    # ── 过滤1: 持仓/观察池上榜（按 code 去重，取净额绝对值最大的）──
    best_dt_per_code: dict[str, dict] = {}
    for entry in board:
        code = _pure_stock_code(entry.get("code", ""))
        if code not in watch_codes:
            continue
        net_abs = abs(_parse_net_buy_float(entry.get("net_buy", "0")))
        if code not in best_dt_per_code or net_abs > best_dt_per_code[code]["_net_abs"]:
            best_dt_per_code[code] = {"entry": entry, "_net_abs": net_abs}

    for code, data in best_dt_per_code.items():
        entry = data["entry"]
        result["watch_dt_items"].append(
            f"{entry.get('name','')}({code}) 净买{entry.get('net_buy','0')}"
        )

    # ── 过滤2: 全市场净买入TOP5 ──
    sorted_board = sorted(
        board,
        key=lambda x: _parse_net_buy_float(x.get("net_buy", "0")),
        reverse=True,
    )
    result["dt_nettop5"] = [
        {"code": e.get("code"), "name": e.get("name"), "net_buy": e.get("net_buy")}
        for e in sorted_board[:5]
    ]

    # ── 过滤3: 按持仓 theme 汇总 ──
    for entry in board:
        code = _pure_stock_code(entry.get("code", ""))
        themes = code_to_themes.get(code, [])
        net_float = _parse_net_buy_float(entry.get("net_buy", "0"))
        for tid in themes:
            if tid not in result["dt_sector_summary"]:
                result["dt_sector_summary"][tid] = {"total_net": 0.0, "stocks": []}
            result["dt_sector_summary"][tid]["total_net"] += net_float
            if code not in result["dt_sector_summary"][tid]["stocks"]:
                result["dt_sector_summary"][tid]["stocks"].append(code)

    # 格式化 net 为可读字符串
    for tid in result["dt_sector_summary"]:
        net = result["dt_sector_summary"][tid]["total_net"]
        if abs(net) >= 100_000_000:
            net_str = f"{'+' if net >= 0 else ''}{net / 100_000_000:.2f}亿"
        elif abs(net) >= 10_000:
            net_str = f"{'+' if net >= 0 else ''}{net / 10_000:.0f}万"
        else:
            net_str = f"{net:.0f}"
        result["dt_sector_summary"][tid]["total_net_str"] = net_str
        del result["dt_sector_summary"][tid]["total_net"]

    return result


def _parse_net_buy_float(net_str: str) -> float:
    """将龙虎榜净买额字符串转为浮动数值。"""
    try:
        text = str(net_str).strip()
        if not text or text in ("-", "--"):
            return 0.0
        sign = -1.0 if text.startswith("-") else 1.0
        text = text.lstrip("+-").strip()
        if "亿" in text:
            return sign * float(text.replace("亿", "")) * 100_000_000
        elif "万" in text:
            return sign * float(text.replace("万", "")) * 10_000
        else:
            return sign * float(text)
    except (ValueError, TypeError):
        return 0.0


def _format_net_buy_str(net_raw: str) -> str:
    """将龙虎榜净买额原始字符串格式化为 '+X.XX亿' 或 '+XXXX万' 格式。"""
    try:
        net_float = float(str(net_raw).strip().replace(",", ""))
        if abs(net_float) >= 100_000_000:
            return f"{'+' if net_float >= 0 else ''}{net_float / 100_000_000:.2f}亿"
        elif abs(net_float) >= 10_000:
            return f"{'+' if net_float >= 0 else ''}{net_float / 10_000:.0f}万"
        else:
            return f"{net_float:.0f}"
    except (ValueError, TypeError):
        return str(net_raw)
