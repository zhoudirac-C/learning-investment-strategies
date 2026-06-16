from __future__ import annotations

import argparse
import json
import logging
import re
import subprocess
import time as time_module
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml

from qing_investment.paths import repo_root
from qing_investment.monitor.fetchers import parse_eastmoney_quote_rows


# 向后兼容：fetch 函数（原实现已迁移到 monitor.fetchers）
def fetch_eastmoney_quotes(targets: dict[str, str], timeout: float = 8.0) -> dict:
    """东财行情获取 — 向后兼容实现，使用 urllib + curl 降级。"""
    if not targets:
        return {"source": "eastmoney", "quotes": [], "errors": [], "elapsed_ms": 0}

    QUOTE_FIELDS = "f12,f13,f14,f2,f3,f4,f5,f6,f15,f16,f17,f18"
    BASE_URL = "https://push2.eastmoney.com/api/qt/ulist.np/get"

    started = time_module.perf_counter()
    quotes: list[dict] = []
    errors: list[str] = []

    for chunk in _chunk_targets(targets):
        params = urllib.parse.urlencode(
            {
                "fltt": "2",
                "invt": "2",
                "fields": QUOTE_FIELDS,
                "secids": ",".join(chunk.values()),
            },
            safe=",",
        )
        url = f"{BASE_URL}?{params}"

        try:
            request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            # curl 降级
            try:
                result = subprocess.run(
                    ["curl", "-s", "-L", "--max-time", str(int(timeout)), url],
                    capture_output=True,
                    text=True,
                    check=True,
                )
                payload = json.loads(result.stdout)
            except Exception as curl_exc:
                # 如果 chunk 包含多个标的，尝试拆分为单个标的
                if len(chunk) > 1:
                    for single_label, single_sec_id in chunk.items():
                        single_chunk = {single_label: single_sec_id}
                        single_params = urllib.parse.urlencode(
                            {
                                "fltt": "2",
                                "invt": "2",
                                "fields": QUOTE_FIELDS,
                                "secids": single_sec_id,
                            },
                            safe=",",
                        )
                        single_url = f"{BASE_URL}?{single_params}"
                        try:
                            single_request = urllib.request.Request(single_url, headers={"User-Agent": "Mozilla/5.0"})
                            with urllib.request.urlopen(single_request, timeout=timeout) as single_response:
                                single_payload = json.loads(single_response.read().decode("utf-8"))
                                quotes.extend(parse_eastmoney_quote_rows(single_payload.get("data", {}).get("diff", []), single_chunk))
                        except Exception:
                            try:
                                single_result = subprocess.run(
                                    ["curl", "-s", "-L", "--max-time", str(int(timeout)), single_url],
                                    capture_output=True,
                                    text=True,
                                    check=True,
                                )
                                single_payload = json.loads(single_result.stdout)
                                quotes.extend(parse_eastmoney_quote_rows(single_payload.get("data", {}).get("diff", []), single_chunk))
                            except Exception:
                                pass
                else:
                    errors.append(f"urllib: {exc}; curl: {curl_exc}")
                continue

        quotes.extend(parse_eastmoney_quote_rows(payload.get("data", {}).get("diff", []), chunk))

    latency = round((time_module.perf_counter() - started) * 1000, 1)
    return {
        "source": "eastmoney",
        "quotes": quotes,
        "errors": errors,
        "elapsed_ms": latency,
    }


def _chunk_targets(targets: dict[str, str], chunk_size: int = 80) -> list[dict[str, str]]:
    """将目标拆分为多个 chunk。"""
    items = list(targets.items())
    return [dict(items[i : i + chunk_size]) for i in range(0, len(items), chunk_size)]


def fetch_tencent_quotes(targets: dict[str, str]) -> dict:
    """腾讯行情获取 — 委托给 monitor.fetchers.TencentFetcher。"""
    from qing_investment.monitor.fetchers import TencentFetcher
    result = TencentFetcher().fetch(targets)
    return {
        "source": "tencent_gtimg",
        "quotes": result.data.get("quotes", []),
        "errors": [result.error] if result.error else [],
        "elapsed_ms": result.latency_ms,
    }


logger = logging.getLogger(__name__)
CN_TZ = ZoneInfo("Asia/Shanghai")
DEFAULT_CONFIG_DIR = repo_root() / "config" / "stock_monitor"
QUOTE_FIELDS = "f12,f13,f14,f2,f3,f4,f5,f6,f15,f16,f17,f18"
EASTMONEY_QUOTE_URL = "https://push2.eastmoney.com/api/qt/ulist.np/get"
QUOTE_CHUNK_SIZE = 15
MARKET_INDEXES = {
    "上证指数": "1.000001",
    "深证成指": "0.399001",
    "创业板指": "0.399006",
    "科创50": "1.000688",
    "全A指数": "1.000985",   # 中证全指，同花顺全A(883657)无公开API，用此替代
}


# ──────────────────────────────────────────
# 数据提取工具函数 — 已委托给 monitor.context 模块
# 以下为向后兼容的包装函数，内部调用 Phase 2 新模块
# ──────────────────────────────────────────

def _string_items(value: object) -> list[str]:
    """将值转换为字符串列表 — 委托给 monitor.context 模块。
    原实现已迁移，保留函数签名以保持向后兼容。"""
    from qing_investment.monitor.context import _string_items as _new_string_items
    return _new_string_items(value)


def format_watchlist_condition_line(row: dict) -> str:
    """格式化观察列表条件行 — 委托给 monitor.context 模块。
    原实现已迁移，保留函数签名以保持向后兼容。"""
    from qing_investment.monitor.context import format_watchlist_condition_line as _new_format
    return _new_format(row)


def sector_group_rows(config: MonitorConfig) -> list[dict]:
    """提取板块组成员行 — 委托给 monitor.context 模块。
    原实现已迁移，保留函数签名以保持向后兼容。"""
    from qing_investment.monitor.context import sector_group_rows as _new_sector_rows
    return _new_sector_rows(config)


def unique_stock_count(rows: list[dict]) -> int:
    """统计唯一股票数量 — 委托给 monitor.context 模块。
    原实现已迁移，保留函数签名以保持向后兼容。"""
    from qing_investment.monitor.context import unique_stock_count as _new_count
    return _new_count(rows)


# ──────────────────────────────────────────
# 股票代码工具函数 — 已委托给 monitor.fetchers 模块
# 以下为向后兼容的包装函数，内部调用 Phase 0 新模块
# ──────────────────────────────────────────

def stock_code_to_secid(code: str) -> str | None:
    """将股票代码转换为 secid 格式 — 委托给 monitor.fetchers 模块。
    原实现已迁移，保留函数签名以保持向后兼容。"""
    from qing_investment.monitor.fetchers import stock_code_to_secid as _new_stock_code_to_secid
    return _new_stock_code_to_secid(code)


def collect_quote_targets(config: MonitorConfig) -> dict[str, str]:
    """收集所有需要获取行情的标的 — 委托给 monitor.fetchers 模块。
    原实现已迁移，保留函数签名以保持向后兼容。"""
    from qing_investment.monitor.fetchers import collect_quote_targets as _new_collect
    return _new_collect(config)


@dataclass
class MonitorConfig:
    config_dir: Path
    positions: dict
    watchlist: dict
    strategy_pack: dict
    positions_path: Path
    direction_pool: dict = field(default_factory=dict)
    stock_pool: dict = field(default_factory=dict)

    def get(self, key: str, default: Any = None) -> Any:
        """模拟 dict.get() 以兼容 RuleEngine。"""
        if key == "positions":
            return self.positions
        if key == "watchlist":
            return self.watchlist
        if key == "strategy_pack":
            return self.strategy_pack
        if key == "direction_pool":
            return self.direction_pool
        if key == "stock_pool":
            return self.stock_pool
        if key == "config_dir":
            return str(self.config_dir)
        if key == "positions_path":
            return str(self.positions_path)
        # 兼容 strategy_pack 中的字段（如 market_framework, sector_groups 等）
        if self.strategy_pack and isinstance(self.strategy_pack, dict):
            return self.strategy_pack.get(key, default)
        return default

    def __getitem__(self, key: str) -> Any:
        result = self.get(key)
        if result is None:
            raise KeyError(key)
        return result

    def __contains__(self, key: str) -> bool:
        return self.get(key) is not None


@dataclass(frozen=True)
class RuleAlert:
    action: str
    stock_code: str
    stock_name: str
    price: float
    trigger: str
    severity: str
    summary: str


@dataclass(frozen=True)
class SectorStrength:
    id: str
    name: str
    style: str
    average_pct_change: float
    red_ratio: float
    quote_count: int
    total_amount: float


@dataclass(frozen=True)
class AgentAnalysisTrigger:
    kind: str
    id: str
    title: str
    reason: str
    dedupe_key: str


@dataclass
class BuySignalCandidate:
    """买入信号候选（poll 层输出，不是最终信号）"""
    stock_code: str
    stock_name: str
    price: float
    is_candidate: bool
    matched_conditions: list[str]
    entry_zone: tuple[float, float] | None = None
    stop_loss: float | None = None
    claim_basis: str = ""
    odds_analysis: dict | None = None


DEFAULT_AGENT_ANALYSIS_SCHEDULE = [
    {
        "id": "open_auction",
        "time": "09:26",
        "name": "集合竞价后",
        "focus": "竞价方向（高开/低开/平开），方向强弱对比，建立今天核心假设，更新 daily_state",
        "prompt": "cron_opening",
    },
    {
        "id": "open_confirm",
        "time": "09:45",
        "name": "开盘15分钟确认",
        "focus": "9:30假设是否成立？开盘15分钟内指数和方向是否按预期走？若不成立，修正假设",
        "prompt": "cron_open_confirm",
    },
    {
        "id": "morning_confirm",
        "time": "10:00",
        "name": "10点确认",
        "focus": "30分钟后，今天基调基本确定。是强修复/弱修复/分歧/防御？写出今日机会模式初筛",
        "prompt": "cron_morning_confirm",
    },
    {
        "id": "opportunity_scan",
        "time": "10:30",
        "name": "30分钟确认",
        "focus": "基于早盘走势，7大机会模式逐一检查，给出「今日最有希望触发机会的3-5只标的」",
        "prompt": "cron_opportunity_scan",
    },
    {
        "id": "noon_review",
        "time": "11:20",
        "name": "上午收盘前",
        "focus": "上午定性 + 午后预案。\"如果下午延续上午，该做什么？如果下午反转，该做什么？\"",
        "prompt": "cron_noon_review",
    },
    {
        "id": "afternoon_risk",
        "time": "13:10",
        "name": "午后风险窗口",
        "focus": "验证午后只看不买纪律，检查持仓是否触发风控，识别午后冲高回落风险",
        "prompt": "cron_afternoon_risk",
    },
    {
        "id": "mid_afternoon",
        "time": "14:00",
        "name": "午盘监控",
        "focus": "对比上午预期和下午实际走势，决定是否需要尾盘调整",
        "prompt": "cron_midday",
    },
    {
        "id": "tail_condition",
        "time": "14:55",
        "name": "尾盘条件单",
        "focus": "是否触发尾盘买入/卖出/尾盘杀风险？今日持仓怎么过夜？",
        "prompt": "cron_tail_condition",
    },
    {
        "id": "closing_review",
        "time": "15:20",
        "name": "收盘复盘",
        "focus": "全天观点演进回顾，更新 daily_state + strategy_pack，写复盘报告",
        "prompt": "cron_closing",
    },
]


def parse_price_zone(value: object) -> tuple[float, float] | None:
    """解析价格区间 — 委托给 monitor.context 模块。
    原实现已迁移，保留函数签名以保持向后兼容。"""
    from qing_investment.monitor.context import parse_price_zone as _new_parse
    return _new_parse(value)


def _to_float(value: object) -> float | None:
    """转换为浮点数 — 委托给 monitor.context 模块。
    原实现已迁移，保留函数签名以保持向后兼容。"""
    from qing_investment.monitor.context import _to_float as _new_to_float
    return _new_to_float(value)


def _pure_stock_code(code: object) -> str:
    """从 '600519.SH' 提取 '600519' — 委托给 monitor.context 模块。
    原实现已迁移，保留函数签名以保持向后兼容。"""
    from qing_investment.monitor.context import _pure_stock_code as _new_pure
    return _new_pure(code)


def _quotes_by_code(quote_snapshot: dict) -> dict[str, dict]:
    """将 quote_snapshot 按股票代码索引 — 委托给 monitor.context 模块。
    原实现已迁移，保留函数签名以保持向后兼容。"""
    from qing_investment.monitor.context import _quotes_by_code as _new_quotes
    return _new_quotes(quote_snapshot)


def _quote_for_stock(quotes: dict[str, dict], code: object) -> dict | None:
    """从 quotes 字典中查找指定股票代码的行情 — 委托给 monitor.context 模块。
    原实现已迁移，保留函数签名以保持向后兼容。"""
    from qing_investment.monitor.context import _quote_for_stock as _new_quote
    return _new_quote(quotes, code)


def _quotes_by_label(quote_snapshot: dict) -> dict[str, dict]:
    """将 quote_snapshot 按标签索引 — 委托给 monitor.context 模块。
    原实现已迁移，保留函数签名以保持向后兼容。"""
    from qing_investment.monitor.context import _quotes_by_label as _new_quotes
    return _new_quotes(quote_snapshot)


def _format_zone(zone: tuple[float, float]) -> str:
    """格式化价格区间 — 委托给 monitor.context 模块。
    原实现已迁移，保留函数签名以保持向后兼容。"""
    from qing_investment.monitor.context import _format_zone as _new_format
    return _new_format(zone)


# ──────────────────────────────────────────
# 规则评估函数 — 已委托给 monitor.rules 模块
# 以下为向后兼容的包装函数，内部调用 Phase 1 新模块
# ──────────────────────────────────────────

def evaluate_position_alerts(
    config: MonitorConfig,
    quote_snapshot: dict,
) -> list[RuleAlert]:
    """持仓规则评估 — 委托给 monitor.rules.PositionRuleEngine。
    原实现已迁移，保留函数签名以保持向后兼容。"""
    from qing_investment.monitor.rules import PositionRuleEngine
    return PositionRuleEngine().evaluate(config, quote_snapshot)


def evaluate_buy_signal_candidates(
    config: MonitorConfig,
    quote_snapshot: dict,
) -> list[BuySignalCandidate]:
    """买入信号候选筛选 — 委托给 monitor.rules.BuySignalRuleEngine。
    原实现已迁移，保留函数签名以保持向后兼容。"""
    from qing_investment.monitor.rules import BuySignalRuleEngine
    engine = BuySignalRuleEngine()
    # 传入完整 config（含 stock_pool / direction_pool），兼容 dict 类型
    return engine._evaluate_candidates(config if hasattr(config, 'get') else config, quote_snapshot)


def evaluate_buy_signal_alerts(
    config: MonitorConfig,
    quote_snapshot: dict,
) -> list[RuleAlert]:
    """买入信号告警 — 委托给 monitor.rules.BuySignalRuleEngine。
    原实现已迁移，保留函数签名以保持向后兼容。"""
    from qing_investment.monitor.rules import BuySignalRuleEngine
    return BuySignalRuleEngine().evaluate(config, quote_snapshot)


def evaluate_market_alerts(
    config: MonitorConfig,
    quote_snapshot: dict,
    *,
    current_time: datetime | None = None,
) -> list[RuleAlert]:
    """指数规则评估 — 委托给 monitor.rules.IndexRuleEngine。
    原实现已迁移，保留函数签名以保持向后兼容。"""
    from qing_investment.monitor.rules import IndexRuleEngine
    return IndexRuleEngine().evaluate(config, quote_snapshot, current_time=current_time)


def compute_sector_strength(
    config: MonitorConfig,
    quote_snapshot: dict,
) -> list[SectorStrength]:
    """板块强度计算 — 委托给 monitor.rules.SectorRotationRuleEngine。
    原实现已迁移，保留函数签名以保持向后兼容。"""
    from qing_investment.monitor.rules import SectorRotationRuleEngine
    # _compute_sector_strength 是实例方法，需要创建实例
    return SectorRotationRuleEngine()._compute_sector_strength(config, quote_snapshot)


def _aggregate_sector_strength(
    strengths: dict[str, SectorStrength],
    group_ids: list[str],
) -> SectorStrength | None:
    """板块聚合 — 委托给 monitor.rules.SectorRotationRuleEngine。
    原实现已迁移，保留函数签名以保持向后兼容。"""
    from qing_investment.monitor.rules import SectorRotationRuleEngine
    return SectorRotationRuleEngine._aggregate(strengths, group_ids)


def evaluate_sector_rotation_alerts(
    config: MonitorConfig,
    quote_snapshot: dict,
) -> list[RuleAlert]:
    """板块轮动规则评估 — 委托给 monitor.rules.SectorRotationRuleEngine。
    原实现已迁移，保留函数签名以保持向后兼容。"""
    from qing_investment.monitor.rules import SectorRotationRuleEngine
    return SectorRotationRuleEngine().evaluate(config, quote_snapshot)


def evaluate_monitor_alerts(
    config: MonitorConfig,
    quote_snapshot: dict,
    *,
    current_time: datetime | None = None,
) -> list[RuleAlert]:
    """Evaluate all monitoring rules — 委托给 Phase 1 RuleEngine 模块。

    原实现已迁移至: qing_investment.monitor.rules.RuleEngine
    保留此函数以保持向后兼容。
    """
    from qing_investment.monitor.rules import evaluate_monitor_alerts as _new_evaluate
    return _new_evaluate(config, quote_snapshot, current_time=current_time)


def format_alerts_message(
    alerts: list[RuleAlert],
    value: datetime,
    quote_snapshot: dict,
) -> str:
    """格式化告警消息 — 委托给 Phase 3 OutputManager 模块。

    原实现已迁移至: qing_investment.monitor.output.AlertOutputManager
    保留此函数以保持向后兼容。
    """
    from qing_investment.monitor.output import format_alerts_message as _new_format
    return _new_format(alerts, value, quote_snapshot)


def alert_fingerprint(alert: RuleAlert) -> str:
    """生成告警指纹 — 委托给 monitor.output 模块。
    原实现已迁移，保留函数签名以保持向后兼容。"""
    from qing_investment.monitor.output import _alert_fingerprint
    return _alert_fingerprint(alert)


def load_monitor_state(path: Path) -> dict:
    """加载监控状态 — 委托给 Phase 5 Scheduler 模块。

    原实现已迁移至: qing_investment.monitor.scheduler.StateManager
    保留此函数以保持向后兼容。
    """
    from qing_investment.monitor.scheduler import load_monitor_state as _new_load
    return _new_load(path)


def save_monitor_state(path: Path, state: dict) -> None:
    """保存监控状态 — 委托给 Phase 5 Scheduler 模块。

    原实现已迁移至: qing_investment.monitor.scheduler.StateManager
    保留此函数以保持向后兼容。
    """
    from qing_investment.monitor.scheduler import save_monitor_state as _new_save
    return _new_save(path, state)


def filter_new_alerts(
    alerts: list[RuleAlert],
    state: dict,
    value: datetime,
    *,
    dedupe_minutes: int,
    dedupe_by_type: dict | None = None,
) -> list[RuleAlert]:
    """告警去重 — 委托给 monitor.output 模块。
    原实现已迁移，保留函数签名以保持向后兼容。"""
    from qing_investment.monitor.output import filter_new_alerts as _new_filter
    return _new_filter(alerts, state, value, dedupe_minutes=dedupe_minutes, dedupe_by_type=dedupe_by_type)


def record_emitted_alerts(
    state: dict,
    alerts: list[RuleAlert],
    value: datetime,
) -> None:
    """记录已发出告警 — 委托给 monitor.output 模块。
    原实现已迁移，保留函数签名以保持向后兼容。"""
    from qing_investment.monitor.output import record_emitted_alerts as _new_record
    return _new_record(state, alerts, value)


def format_alert_decision_log(
    all_alerts: list[RuleAlert],
    emitted_alerts: list[RuleAlert],
    value: datetime,
) -> list[dict]:
    """格式化告警决策日志 — 委托给 monitor.output 模块。
    原实现已迁移，保留函数签名以保持向后兼容。"""
    from qing_investment.monitor.output import AlertFormatter
    formatter = AlertFormatter()
    emitted_keys = {alert_fingerprint(alert) for alert in emitted_alerts}
    log: list[dict] = []
    for alert in all_alerts:
        status = "emitted" if alert_fingerprint(alert) in emitted_keys else "suppressed"
        log.append(formatter.format_log_entry(alert, value, status=status))
    return log


def update_sector_signal_counts(
    state: dict,
    alerts: list[RuleAlert],
    value: datetime,
) -> None:
    """更新板块信号计数 — 委托给 monitor.scheduler 模块。
    原实现已迁移，保留函数签名以保持向后兼容。"""
    from qing_investment.monitor.scheduler import update_sector_signal_counts as _new_update
    return _new_update(state, alerts, value)


def update_market_state(
    state: dict,
    alerts: list[RuleAlert],
    quote_snapshot: dict,
    value: datetime,
) -> None:
    """更新市场状态 — 委托给 monitor.scheduler 模块。
    原实现已迁移，保留函数签名以保持向后兼容。"""
    from qing_investment.monitor.scheduler import update_market_state as _new_update
    return _new_update(state, alerts, value, quote_snapshot)


def agent_analysis_schedule_rows(config: MonitorConfig) -> list[dict]:
    """获取Agent分析计划行 — 委托给 monitor.scheduler 模块。
    原实现已迁移，保留函数签名以保持向后兼容。"""
    from qing_investment.monitor.scheduler import agent_analysis_schedule_rows as _new_rows
    return _new_rows(config)


def _hhmm(value: datetime) -> str:
    """获取时间HH:MM格式 — 委托给 monitor.scheduler 模块。
    原实现已迁移，保留函数签名以保持向后兼容。"""
    from qing_investment.monitor.scheduler import _hhmm as _new_hhmm
    return _new_hhmm(value)


def _agent_history(state: dict) -> dict:
    """获取Agent分析历史 — 委托给 monitor.scheduler 模块。
    原实现已迁移，保留函数签名以保持向后兼容。"""
    from qing_investment.monitor.scheduler import _agent_history as _new_history
    return _new_history(state)


def _agent_dedupe_key_for_schedule(row: dict, value: datetime) -> str:
    """获取Agent分析去重键 — 委托给 monitor.scheduler 模块。
    原实现已迁移，保留函数签名以保持向后兼容。"""
    from qing_investment.monitor.scheduler import _agent_dedupe_key_for_schedule as _new_key
    return _new_key(row, value)


def find_agent_analysis_trigger(
    config: MonitorConfig,
    state: dict,
    value: datetime,
    alerts: list[RuleAlert],
) -> AgentAnalysisTrigger | None:
    """查找Agent分析触发器 — 委托给 monitor.scheduler 模块。
    原实现已迁移，保留函数签名以保持向后兼容。"""
    from qing_investment.monitor.scheduler import find_agent_analysis_trigger as _new_find
    return _new_find(config, state, value, alerts)


def find_any_agent_analysis_trigger(
    config: MonitorConfig,
    state: dict,
    value: datetime,
    alerts: list[RuleAlert],
) -> AgentAnalysisTrigger | None:
    """查找任意Agent分析触发器 — 委托给 monitor.scheduler 模块。
    原实现已迁移，保留函数签名以保持向后兼容。"""
    from qing_investment.monitor.scheduler import find_any_agent_analysis_trigger as _new_find
    return _new_find(config, state, value, alerts)


def record_agent_analysis_trigger(
    state: dict,
    trigger: AgentAnalysisTrigger,
    value: datetime,
) -> None:
    """记录Agent分析触发器 — 委托给 monitor.scheduler 模块。
    原实现已迁移，保留函数签名以保持向后兼容。"""
    from qing_investment.monitor.scheduler import record_agent_analysis_trigger as _new_record
    return _new_record(state, trigger, value)


def is_scheduled_agent_analysis_time(config: MonitorConfig, value: datetime) -> bool:
    """检查是否为Agent分析计划时间 — 委托给 monitor.scheduler 模块。
    原实现已迁移，保留函数签名以保持向后兼容。"""
    from qing_investment.monitor.scheduler import is_scheduled_agent_analysis_time as _new_check
    return _new_check(config, value)


# ──────────────────────────────────────────────
# Phase 1: 昨日特征摘要系统
# ──────────────────────────────────────────────

SUMMARY_CONFIG_DIR = DEFAULT_CONFIG_DIR
SUMMARY_FILENAME = "daily_review_summary.json"

# 字段清单（设计文档 §1.1）
SUMMARY_FIELDS_BASIC = ["close", "open", "high", "low", "change_pct", "volume", "amount"]
SUMMARY_FIELDS_BOARD = ["is_limit_up", "consecutive_limit_ups", "weak_board",
                        "board_open_count", "first_board_time", "board_seal_ratio",
                        "board_quality"]
SUMMARY_FIELDS_TECH = ["turnover_rate", "amplitude", "volume_ratio",
                       "vs_ma5", "vs_ma10", "near5d_return"]
SUMMARY_FIELDS_DETAIL = ["intraday_pattern", "sector_avg_change",
                         "dragon_tiger_net", "entry_zone_distance", "entry_zone_range",
                         "dt_seat_type", "dt_top_buy_behavior", "dt_is_pure_hot_money"]
SUMMARY_FIELDS_COST = ["avg_cost", "unrealized_pct", "cost_protection_line"]
ALL_SUMMARY_FIELDS = (SUMMARY_FIELDS_BASIC + SUMMARY_FIELDS_BOARD + SUMMARY_FIELDS_TECH
                      + SUMMARY_FIELDS_DETAIL + SUMMARY_FIELDS_COST)

# 涨停判定阈值（主板10%，创业板/科创板20% — 但用户仅主板可交易）
LIMIT_UP_THRESHOLD = 9.5  # 涨停临界%

# 通用计算函数
# 为兼容性，不在模块最外层定义，放在函数内部


def _summary_file_path(config_dir: Path | None = None) -> Path:
    """返回 summary 文件路径 — 委托给 monitor.scheduler 模块。
    原实现已迁移，保留函数签名以保持向后兼容。"""
    from qing_investment.monitor.scheduler import _summary_file_path as _new_path
    return _new_path(config_dir)


def _compute_vs_ma(close: float, klines: list[dict], ma_days: int) -> float | None:
    """计算收盘价相对 MA 的位置百分比 — 委托给 monitor.analysis 模块。
    原实现已迁移，保留函数签名以保持向后兼容。"""
    from qing_investment.monitor.analysis import _compute_vs_ma as _new_compute
    return _new_compute(close, klines, ma_days)


def _compute_near5d_return(klines: list[dict]) -> float | None:
    """计算近5个交易日的累计涨跌幅 — 委托给 monitor.analysis 模块。
    原实现已迁移，保留函数签名以保持向后兼容。"""
    from qing_investment.monitor.analysis import _compute_near5d_return as _new_compute
    return _new_compute(klines)


def _compute_volume_ratio(today_volume: float, klines: list[dict]) -> float | None:
    """计算今日量/近5日均量的比值 — 委托给 monitor.analysis 模块。
    原实现已迁移，保留函数签名以保持向后兼容。"""
    from qing_investment.monitor.analysis import _compute_volume_ratio as _new_compute
    return _new_compute(today_volume, klines)


def _check_entry_zone_distance(code: str, close: float, config: MonitorConfig) -> dict:
    """判断收盘价距 entry_zone 的距离 — 委托给 monitor.analysis 模块。
    原实现已迁移，保留函数签名以保持向后兼容。"""
    from qing_investment.monitor.analysis import _check_entry_zone_distance as _new_check
    return _new_check(code, close, config)

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
    """根据营业部名称判断席位性质 — 委托给 monitor.analysis 模块。
    原实现已迁移，保留函数签名以保持向后兼容。"""
    from qing_investment.monitor.analysis import _classify_seat_type as _new_classify
    return _new_classify(name)


def _classify_top_buy_behavior(
    df_buy: "pd.DataFrame",
    df_sell: "pd.DataFrame",
) -> str:
    """判断买一席位的次日行为倾向 — 委托给 monitor.analysis 模块。
    原实现已迁移，保留函数签名以保持向后兼容。"""
    from qing_investment.monitor.analysis import _classify_top_buy_behavior as _new_classify
    return _new_classify(df_buy, df_sell)


def _assess_board_quality(df_buy: "pd.DataFrame", df_sell: "pd.DataFrame") -> str:
    """评估封板质量 — 委托给 monitor.analysis 模块。
    原实现已迁移，保留函数签名以保持向后兼容。"""
    from qing_investment.monitor.analysis import _assess_board_quality as _new_assess
    return _new_assess(df_buy, df_sell)


def _fetch_dragon_tiger_data(
    code: str,
    date_str: str,
    timeout: int = 10,
) -> dict:
    """获取个股龙虎榜数据（akshare 东方财富接口）— 委托给 monitor.fetchers 模块。
    原实现已迁移，保留函数签名以保持向后兼容。"""
    from qing_investment.monitor.fetchers import _fetch_dragon_tiger_data as _new_fetch
    return _new_fetch(code, date_str, timeout)


def _fetch_daily_dragon_tiger_board(
    date_str: str,
    timeout: int = 15,
) -> dict:
    """获取当日全市场龙虎榜总榜（akshare 东方财富接口）— 委托给 monitor.fetchers 模块。
    原实现已迁移，保留函数签名以保持向后兼容。"""
    from qing_investment.monitor.analysis import _fetch_daily_dragon_tiger_board as _new_fetch
    return _new_fetch(date_str, timeout)


def _filter_dragon_tiger_board(
    board: list[dict],
    config: MonitorConfig,
) -> dict:
    """对全市场龙虎榜总榜做三层交叉过滤 — 委托给 monitor.fetchers 模块。
    原实现已迁移，保留函数签名以保持向后兼容。"""
    from qing_investment.monitor.analysis import _filter_dragon_tiger_board as _new_filter
    return _new_filter(board, config)
    return result


def _parse_net_buy_float(net_str: str) -> float:
    """解析龙虎榜净买额字符串为浮点数 — 委托给 monitor.analysis 模块。
    原实现已迁移，保留函数签名以保持向后兼容。"""
    from qing_investment.monitor.analysis import _parse_net_buy_float as _new_parse
    return _new_parse(net_str)


def _format_net_buy_str(net_raw: str) -> str:
    """将龙虎榜净买额原始字符串格式化为 '+X.XX亿' 或 '+XXXX万' 格式 — 委托给 monitor.analysis 模块。
    原实现已迁移，保留函数签名以保持向后兼容。"""
    from qing_investment.monitor.analysis import _format_net_buy_str as _new_format
    return _new_format(net_raw)


def _build_yesterday_summary(
    config: MonitorConfig,
    quote_snapshot: dict,
    state: dict,
    daily_state: dict | None = None,
) -> dict:
    """构建昨日特征摘要 — 委托给 monitor.scheduler 模块。
    原实现已迁移，保留函数签名以保持向后兼容。"""
    from qing_investment.monitor.scheduler import _build_yesterday_summary as _new_build
    return _new_build(config, quote_snapshot, state, daily_state)


def _save_yesterday_summary(
    summary: dict,
    config_dir: Path | None = None,
) -> None:
    """保存昨日特征摘要到文件 — 委托给 monitor.scheduler 模块。
    原实现已迁移，保留函数签名以保持向后兼容。"""
    from qing_investment.monitor.scheduler import _save_yesterday_summary as _new_save
    return _new_save(summary, config_dir)


def _update_summary_tomorrow_scenarios(
    summary: dict,
    scenarios: list[dict],
) -> None:
    """更新昨日特征摘要中的明日场景 — 委托给 monitor.scheduler 模块。
    原实现已迁移，保留函数签名以保持向后兼容。"""
    from qing_investment.monitor.scheduler import _update_summary_tomorrow_scenarios as _new_update
    return _new_update(summary, scenarios)


def _load_yesterday_summary(
    config_dir: Path | None = None,
) -> dict | None:
    """加载昨日特征摘要 — 委托给 monitor.scheduler 模块。
    原实现已迁移，保留函数签名以保持向后兼容。"""
    from qing_investment.monitor.scheduler import _load_yesterday_summary as _new_load
    return _new_load(config_dir)


def _auction_cache_path(
    date_str: str,
    config_dir: Path | None = None,
) -> Path:
    """返回竞价缓存文件路径 — 委托给 monitor.scheduler 模块。
    原实现已迁移，保留函数签名以保持向后兼容。"""
    from qing_investment.monitor.scheduler import _auction_cache_path as _new_path
    return _new_path(date_str, config_dir)


def _load_auction_cache(
    date_str: str,
    config_dir: Path | None = None,
) -> dict | None:
    """加载竞价缓存 — 委托给 monitor.scheduler 模块。
    原实现已迁移，保留函数签名以保持向后兼容。"""
    from qing_investment.monitor.scheduler import _load_auction_cache as _new_load
    return _new_load(date_str, config_dir)


def _save_auction_cache(
    date_str: str,
    data: dict,
    config_dir: Path | None = None,
) -> None:
    """保存竞价缓存 — 委托给 monitor.scheduler 模块。
    原实现已迁移，保留函数签名以保持向后兼容。"""
    from qing_investment.monitor.scheduler import _save_auction_cache as _new_save
    return _new_save(date_str, data, config_dir)


def _update_auction_cache(
    date_str: str,
    snapshot: dict,
    config_dir: Path | None = None,
) -> None:
    """更新竞价缓存 — 委托给 monitor.scheduler 模块。
    原实现已迁移，保留函数签名以保持向后兼容。"""
    from qing_investment.monitor.scheduler import _update_auction_cache as _new_update
    return _new_update(date_str, snapshot, config_dir)


def _compute_auction_volume_ratio(
    auction_volume: float,
    yesterday_volume: float,
) -> float | None:
    """计算竞价量/昨日成交量的比值 — 委托给 monitor.analysis 模块。
    原实现已迁移，保留函数签名以保持向后兼容。"""
    from qing_investment.monitor.analysis import _compute_auction_volume_ratio as _new_compute
    return _new_compute(auction_volume, yesterday_volume)


def _compute_auction_vs_yesterday_volume(
    auction_volume: float,
    yesterday_volume: float,
) -> float | None:
    """计算竞价量相对昨日成交量的百分比 — 委托给 monitor.analysis 模块。
    原实现已迁移，保留函数签名以保持向后兼容。"""
    from qing_investment.monitor.analysis import _compute_auction_vs_yesterday_volume as _new_compute
    return _new_compute(auction_volume, yesterday_volume)


def _auction_snapshot(
    code: str,
    date_str: str,
    timeout: int = 10,
) -> dict:
    """获取个股竞价快照 — 委托给 monitor.fetchers 模块。
    原实现已迁移，保留函数签名以保持向后兼容。"""
    from qing_investment.monitor.fetchers import _auction_snapshot as _new_snapshot
    return _new_snapshot(code, date_str, timeout)


def _extract_auction_snapshot_for_context(
    snapshot: dict,
) -> dict:
    """从竞价快照提取关键字段用于 context — 委托给 monitor.context 模块。
    原实现已迁移，保留函数签名以保持向后兼容。"""
    from qing_investment.monitor.context import _extract_auction_snapshot_for_context as _new_extract
    return _new_extract(snapshot)


def _build_sector_tiers(
    config: MonitorConfig,
    quote_snapshot: dict,
) -> dict:
    """构建板块分层 — 委托给 monitor.context 模块。
    原实现已迁移，保留函数签名以保持向后兼容。"""
    from qing_investment.monitor.context import _build_sector_tiers as _new_build
    return _new_build(config, quote_snapshot)


def _agent_context_data(
    config: MonitorConfig,
    quote_snapshot: dict,
    state: dict,
) -> dict:
    """构建 Agent 分析所需的 context 数据 — 委托给 monitor.context 模块。
    原实现已迁移，保留函数签名以保持向后兼容。"""
    from qing_investment.monitor.context import _agent_context_data as _new_data
    return _new_data(config, quote_snapshot, state)


def format_agent_analysis_context(
    *args,
) -> str:
    """格式化 Agent 分析 context — 委托给 monitor.context 模块。
    原实现已迁移，保留函数签名以保持向后兼容。
    
    支持两种调用方式:
        format_agent_analysis_context(data)           # 新方式（单 dict）
        format_agent_analysis_context(config, datetime, trigger, alerts, quotes, state)  # 旧方式
    """
    from qing_investment.monitor.context import format_agent_analysis_context as _new_format
    if len(args) == 1 and isinstance(args[0], dict):
        return _new_format(args[0])
    # 旧方式：6个位置参数
    if len(args) == 6:
        config, value, trigger, alerts, quotes, state = args
        data = {
            "config": config,
            "value": value,
            "trigger": trigger,
            "alerts": alerts,
            "quotes": quotes,
            "state": state,
        }
        return _new_format(data)
    raise TypeError(f"format_agent_analysis_context() takes 1 or 6 arguments ({len(args)} given)")


def format_agent_json_context(*args) -> str:
    """格式化 Agent JSON context — 委托给 monitor.context 模块。
    原实现已迁移，保留函数签名以保持向后兼容。
    
    支持两种调用方式:
        format_agent_json_context(data)                              # 新方式（单 dict）
        format_agent_json_context(config, value, trigger, alerts, snapshot, state)  # 旧方式
    """
    from qing_investment.monitor.context import format_agent_json_context as _new_format
    if len(args) == 6:
        # 旧调用方式: format_agent_json_context(config, value, trigger, alerts, snapshot, state)
        config, value, trigger, alerts, snapshot, state = args
        # 构建 buy_signal_candidates
        buy_signal_candidates = []
        try:
            from qing_investment.monitor.rules import BuySignalRuleEngine
            engine = BuySignalRuleEngine()
            cfg = config.strategy_pack if hasattr(config, 'strategy_pack') else config
            raw_candidates = engine._evaluate_candidates(cfg, snapshot)
            for c in raw_candidates:
                if getattr(c, 'is_candidate', False):
                    buy_signal_candidates.append({
                        "stock_code": c.stock_code,
                        "stock_name": c.stock_name,
                        "price": c.price,
                        "entry_zone": list(c.entry_zone) if c.entry_zone else None,
                        "stop_loss": c.stop_loss,
                        "matched_conditions": c.matched_conditions,
                        "claim_basis": getattr(c, 'claim_basis', ''),
                        "odds_analysis": getattr(c, 'odds_analysis', {}),
                    })
        except Exception:
            pass
        data = {
            "timestamp": value.astimezone(ZoneInfo("Asia/Shanghai")).isoformat(),
            "trigger": {
                "kind": trigger.kind,
                "id": trigger.id,
                "title": trigger.title,
                "reason": trigger.reason,
            },
            "alerts": [{"action": a.action, "stock_code": a.stock_code,
                        "stock_name": getattr(a, "stock_name", ""),
                        "summary": a.summary} for a in alerts],
            "quote_snapshot": snapshot,
            "positions": config.positions,
            "watchlist": config.watchlist,
            "market_framework": config.strategy_pack.get("market_framework", {}),
            "state": state,
            "buy_signal_candidates": buy_signal_candidates,
        }
        return _new_format(data)
    return _new_format(args[0])


def _state_date(
    state: dict,
) -> str:
    """从 state 中提取日期 — 委托给 monitor.scheduler 模块。
    原实现已迁移，保留函数签名以保持向后兼容。"""
    from qing_investment.monitor.scheduler import _state_date as _new_date
    return _new_date(state)


def summarize_daily_review(
    config_or_state: Any,
    quote_snapshot_or_date: Any,
    state: dict | None = None,
) -> dict:
    """汇总每日复盘 — 委托给 monitor.scheduler 模块。
    原实现已迁移，保留函数签名以保持向后兼容。
    支持两种调用方式:
        summarize_daily_review(config, quote_snapshot, state)  # 旧方式
        summarize_daily_review(state, date_text)                # 新方式
    """
    from qing_investment.monitor.scheduler import summarize_daily_review as _new_summarize
    if state is not None:
        # 旧调用方式: summarize_daily_review(config, quote_snapshot, state)
        # 从 state 中提取日期，或用当前日期
        date_text = state.get("last_review_date", "")
        return _new_summarize(state, date_text)
    # 新调用方式: summarize_daily_review(state, date_text)
    return _new_summarize(config_or_state, quote_snapshot_or_date)


def _append_review_entries(
    review: dict,
    entries: list[dict],
) -> None:
    """追加复盘条目 — 委托给 monitor.scheduler 模块。
    原实现已迁移，保留函数签名以保持向后兼容。"""
    from qing_investment.monitor.scheduler import _append_review_entries as _new_append
    return _new_append(review, entries)


def format_daily_review_context(
    config_or_review: Any,
    value: datetime | None = None,
    state: dict | None = None,
) -> str:
    """格式化每日复盘 context — 委托给 monitor.scheduler 模块。
    原实现已迁移，保留函数签名以保持向后兼容。
    支持两种调用方式:
        format_daily_review_context(config, datetime, state)  # 旧方式
        format_daily_review_context(review)                      # 新方式
    """
    from qing_investment.monitor.context import format_daily_review_context as _new_format
    if value is not None and state is not None:
        # 旧调用方式: format_daily_review_context(config, datetime, state)
        # 构造 review dict
        review = summarize_daily_review(state, value.strftime("%Y-%m-%d"))
        return _new_format(review)
    # 新调用方式: format_daily_review_context(review)
    return _new_format(config_or_review)


def load_yaml(
    path: str | Path,
) -> dict:
    """加载 YAML 文件 — 委托给 monitor.context 模块。
    原实现已迁移，保留函数签名以保持向后兼容。"""
    from qing_investment.monitor.context import load_yaml as _new_load
    return _new_load(path)


def load_monitor_config(
    path: str | Path,
) -> MonitorConfig:
    """加载监控配置 — 委托给 monitor.context 模块。
    原实现已迁移，保留函数签名以保持向后兼容。"""
    from qing_investment.monitor.context import load_monitor_config as _new_load
    return _new_load(path)


def format_quote_line(
    quote: dict,
) -> str:
    """格式化行情行 — 委托给 monitor.output 模块。
    原实现已迁移，保留函数签名以保持向后兼容。"""
    from qing_investment.monitor.output import format_quote_line as _new_format
    return _new_format(quote)


def format_status_message(
    config_or_status: Any,
    value: datetime | None = None,
) -> str:
    """格式化状态消息 — 委托给 monitor.scheduler 模块。
    原实现已迁移，保留函数签名以保持向后兼容。
    支持两种调用方式:
        format_status_message(config, datetime)  # 旧方式
        format_status_message(status)             # 新方式（status dict 需含 config）
    """
    from qing_investment.monitor.scheduler import format_status_message as _scheduler_format
    if value is not None:
        # 旧调用方式: format_status_message(config, datetime)
        return _scheduler_format(config_or_status, value)
    # 新调用方式: format_status_message(status)
    # status dict 中应该有 config 和 datetime 信息，尝试提取
    status = config_or_status
    if isinstance(status, dict) and "config" in status and "time" in status:
        return _scheduler_format(status["config"], status["time"])
    # 兜底：直接格式化 dict
    return f"[状态] {status}"


def format_smoke_message(
    smoke: dict,
) -> str:
    """格式化烟雾消息 — 委托给 monitor.output 模块。
    原实现已迁移，保留函数签名以保持向后兼容。"""
    from qing_investment.monitor.output import format_smoke_message as _new_format
    return _new_format(smoke)


def format_analysis_context(
    config_or_context: Any,
    value: datetime | None = None,
) -> str:
    """格式化分析 context — 委托给 monitor.context/scheduler 模块。
    原实现已迁移，保留函数签名以保持向后兼容。
    支持两种调用方式:
        format_analysis_context(config, datetime)  # 旧方式
        format_analysis_context(context)             # 新方式
    """
    if value is not None:
        # 旧调用方式: format_analysis_context(config, datetime)
        from qing_investment.monitor.scheduler import format_analysis_context as _scheduler_format
        return _scheduler_format(config_or_context, value)
    # 新调用方式: format_analysis_context(context)
    from qing_investment.monitor.context import format_analysis_context as _new_format
    return _new_format(config_or_context)


def format_live_analysis_context(
    context: dict,
) -> str:
    """格式化实时分析 context — 委托给 monitor.context 模块。
    原实现已迁移，保留函数签名以保持向后兼容。"""
    from qing_investment.monitor.context import format_live_analysis_context as _new_format
    return _new_format(context)


def validate_position_price_zones(
    config: MonitorConfig,
) -> list[str]:
    """验证持仓价格区间 — 委托给 monitor.rules 模块。
    原实现已迁移，保留函数签名以保持向后兼容。"""
    from qing_investment.monitor.rules import validate_position_price_zones as _new_validate
    return _new_validate(config)


def run_tick(
    config: MonitorConfig,
    quote_snapshot_or_time: Any,
    state: dict | None = None,
    *,
    emit_status: bool = False,
    ignore_trading_time: bool = False,
    quote_fetcher: Any | None = None,
    state_path: str | None = None,
    dedupe_minutes: int = 30,
    agent_context_on_trigger: bool = False,
) -> dict | str:
    """执行一次监控 tick — 委托给 monitor.scheduler 模块。
    原实现已迁移，保留函数签名以保持向后兼容。
    支持两种调用方式:
        run_tick(config, quote_snapshot, state)              # 新方式
        run_tick(config, datetime, emit_status=..., ...)    # 旧方式
    """
    from qing_investment.monitor.scheduler import run_tick as _new_run, is_a_share_trading_time
    if isinstance(quote_snapshot_or_time, datetime):
        # 旧调用方式: run_tick(config, datetime, emit_status=..., ignore_trading_time=...)
        time_value = quote_snapshot_or_time
        return _new_run(
            config,
            time_value,
            emit_status=emit_status,
            ignore_trading_time=ignore_trading_time,
            quote_fetcher=quote_fetcher,
            state_path=Path(state_path) if state_path else None,
            dedupe_minutes=dedupe_minutes,
            agent_context_on_trigger=agent_context_on_trigger,
        )
    # 新调用方式: run_tick(config, quote_snapshot, state)
    # scheduler.run_tick 不接受这种签名，需要适配
    empty_state = state or {}
    # 从 quote_snapshot 推断时间（如果可能）或用当前时间
    from datetime import datetime as _dt
    now = _dt.now(CN_TZ)
    return _new_run(
        config,
        now,
        emit_status=False,
        ignore_trading_time=True,
        quote_fetcher=lambda _targets: quote_snapshot_or_time,
    )


def build_parser() -> "argparse.ArgumentParser":
    """构建命令行参数解析器 — 委托给 monitor.scheduler 模块。
    原实现已迁移，保留函数签名以保持向后兼容。"""
    from qing_investment.monitor.scheduler import build_parser as _new_build
    return _new_build()


def main(argv: list[str] | None = None) -> int:
    """主入口 — 委托给 monitor.scheduler 模块。
    原实现已迁移，保留函数签名以保持向后兼容。"""
    from qing_investment.monitor.scheduler import main as _new_main
    return _new_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())

