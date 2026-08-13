"""早盘盘前盲判：预测当日走势（数据 = 前一交易日收盘 + 隔夜外盘）。

与复盘盲判（predict.py，判当日）互补：
- 复盘盲判（22:00）：用当日收盘数据判当日，落盘 predictions/{day}.json
- 早盘盲判（9:28）：用昨日收盘数据 + 隔夜外盘预测当日，落盘 predictions/{day}-pre.json

评分口径一致：预测的 market_stage 对比当日机械真值（truth[{day}]），
stage_hit 由复盘盲判在当日收盘后回填（见 shadow/daily.py）。
"""
from __future__ import annotations

import json
from pathlib import Path

from investment_engine.backtest.history import list_trading_days
from investment_engine.blindtest.dataset import build_daily_pack
from investment_engine.blindtest.replay import (
    DEFAULT_MODEL, PROMPT_VERSION, call_deepseek, parse_result,
)

PRED_DIR = Path("evals/shadow/predictions")
OVERNIGHT_ROOT = Path("infra/data/overnight_us")

PREMARKET_SYSTEM_PROMPT = """你是一个执行已验证方法论的市场分析引擎。基于给定的昨日收盘客观数据与隔夜外盘，独立完成【今日盘前预测】。
要求：
1. 每个判断必须声明所用的数据项；不得引用任何人物的言论或观点。
2. core_patterns 为全量判据框架（含推理步骤与证伪条件）：预判今日市场阶段（sentiment_cycle）与方向主线（mainline_identification）时必须逐条对照其步骤，并在 stage_reason / directions 的 reason 中体现对照结果；patterns 仅为扩展框架索引。实际用到的框架 id 登记在 used_patterns。
3. 严格输出 JSON（不要输出其他文字）：
{"market_stage": "主升|震荡|调整|恐慌（四选一，预判今日收盘最可能的阶段）",
 "stage_reason": "一句话依据（必须引用昨日量能/情绪数据或隔夜外盘）",
 "scenarios": [{"name": "情形A", "condition": "触发条件", "conclusion": "应对结论", "key": "区分关键变量"}],
 "watch_next": ["今日可观察、可证伪的验证变量"],
 "invalidation": ["本判断的失效条件"],
 "directions": [{"direction_id": "从给定方向池选择，1-3个", "reason": "一句话依据",
                "posture": "趋势|波段|右侧确认|回避（四选一）",
                "stocks": ["该方向下给定股票池中的代码，每方向1-2个"]}],
 "used_patterns": ["pattern_id"]}
4. 没有把握的方向可以不选，宁缺毋滥。scenarios 给 1-2 个互斥情形即可。"""


def premarket_path(day: str, pred_dir: Path = PRED_DIR) -> Path:
    return Path(pred_dir) / f"{day}-pre.json"


def _prev_trading_day(day: str, db_path=None) -> str | None:
    """day 之前最后一个已有数据的交易日。"""
    days = list_trading_days("2000-01-01", day, db_path)
    prev = [d for d in days if d < day]
    return prev[-1] if prev else None


def _load_overnight(day: str, overnight_root: Path | None = None) -> dict | None:
    """读隔夜外盘映射（infra/data/overnight_us/{day}.json），缺失返回 None。"""
    root = Path(overnight_root) if overnight_root else OVERNIGHT_ROOT
    path = root / f"{day}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _pack_to_premarket_prompt(pack: dict, target_day: str, overnight: dict | None) -> str:
    """序列化为盘前预测 prompt 正文（边界日期 = target_day）。"""
    from investment_engine.blindtest.dataset import assert_no_leakage

    header = (
        f"今天是 {target_day} 盘前。以下是截至昨日（{pack['date']}）收盘的客观数据，"
        "请据此预测今日走势。"
        "注意：产业链知识库与方向池为最新版静态快照（不含任何时变状态字段）。\n\n"
    )
    body = {
        k: v for k, v in pack.items()
        if k not in ("glossary", "missing")
    }
    if overnight is not None:
        # 精简隔夜外盘：只保留主题 + 关键映射股涨跌，去掉非必要字段；
        # earnings_note 可能含来源指称（如"UP早盘记录"），打码防泄漏
        from investment_engine.blindtest.dataset import FORBIDDEN_RE

        body["overnight_us"] = {
            "date": overnight.get("date"),
            "themes": [
                {"name": FORBIDDEN_RE.sub("██", t.get("name", "")),
                 "stocks": [
                     {"symbol": s.get("symbol"), "name": s.get("name"),
                      "pct_change": s.get("pct_change"),
                      "earnings_note": FORBIDDEN_RE.sub(
                          "██", s.get("earnings_note", ""))}
                     for s in t.get("stocks", []) if "error" not in s
                 ]}
                for t in overnight.get("themes", [])
            ],
        }
    text = header + json.dumps(body, ensure_ascii=False, separators=(",", ":"))
    text += "\n\n## 术语词典\n" + pack["glossary"]
    assert_no_leakage(text, target_day)  # 出厂自检（边界=预测日）
    return text


def run_predict_premarket(day: str, *, config_dir, db_path=None,
                          pred_dir: Path = PRED_DIR, overnight_root=None,
                          model: str = DEFAULT_MODEL, client=None) -> dict:
    """对某日做盘前盲判（预测当日）。已完成日跳过；error 日重跑覆盖。"""
    path = premarket_path(day, pred_dir)
    if path.exists():
        try:
            old = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            old = {}
        if old.get("status") not in (None, "error"):
            return {"status": "skipped", "date": day}

    try:
        prev_day = _prev_trading_day(day, db_path=db_path)
        if prev_day is None:
            return {"date": day, "status": "no_data",
                    "error": "无前一交易日数据"}
        pack = build_daily_pack(prev_day, config_dir=Path(config_dir), db_path=db_path)
        overnight = _load_overnight(day, overnight_root)
        text = _pack_to_premarket_prompt(pack, day, overnight)
        raw = call_deepseek(
            [{"role": "system", "content": PREMARKET_SYSTEM_PROMPT},
             {"role": "user", "content": text}],
            model=model, client=client, tag="shadow_premarket")
        result = parse_result(raw)
        rec = {"date": day, "result": result, "raw": raw,
               "prompt_version": PROMPT_VERSION,
               "stage_hit": None, "due_scores": None, "status": "pending_maturity",
               "meta": {"prev_day": prev_day,
                        "overnight_date": (overnight or {}).get("date")}}
    except Exception as e:  # noqa: BLE001 - 失败留 error 记录，次日重跑
        rec = {"date": day, "status": "error", "error": str(e)[:200]}

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
    return rec
