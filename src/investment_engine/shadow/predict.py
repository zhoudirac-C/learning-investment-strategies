"""每日盲判：复用 blindtest 数据包与 DeepSeek 契约，prediction 按日落盘。"""
from __future__ import annotations

import json
from pathlib import Path

from investment_engine.blindtest.dataset import build_daily_pack, pack_to_prompt
from investment_engine.blindtest.replay import (
    DEFAULT_MODEL, PROMPT_VERSION, build_messages, call_deepseek, parse_result,
    run_with_validation,
)

PRED_DIR = Path("evals/shadow/predictions")


def prediction_path(day: str, pred_dir: Path = PRED_DIR) -> Path:
    return Path(pred_dir) / f"{day}.json"


def has_fresh_data(day: str, db_path=None) -> bool:
    """缓存最新交易日期 == day 才算就绪。"""
    from investment_engine.backtest.history import list_trading_days

    days = list_trading_days("2000-01-01", day, db_path)
    return bool(days) and days[-1] == day


def _load_prior_summary(day: str, pred_dir: Path = PRED_DIR, db_path=None) -> dict | None:
    """读前一交易日的复盘盲判摘要，作为连续状态注入 prompt（P0-3）。

    只提取非泄漏字段（盲判结果本身无来源指称），并显式带 date 标注日期，
    避免 LLM 把昨日 stage_reason 里的「今日」误解成当日。
    """
    from investment_engine.backtest.history import list_trading_days

    days = list_trading_days("2000-01-01", day, db_path)
    prev = [d for d in days if d < day]
    if not prev:
        return None
    prev_day = prev[-1]
    path = prediction_path(prev_day, pred_dir)
    if not path.exists():
        return None
    try:
        rec = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    result = rec.get("result") or {}
    if not result:
        return None
    return {
        "date": prev_day,
        "market_stage": result.get("market_stage", ""),
        "nature": result.get("nature", ""),
        "stage_reason": result.get("stage_reason", ""),
        "watch_next": list(result.get("watch_next") or [])[:5],
        "directions": [
            {"direction_id": d.get("direction_id", ""), "posture": d.get("posture", "")}
            for d in (result.get("directions") or [])
            if d.get("direction_id")
        ],
        # 连续状态：周期定位（反弹第几天）+ 昨日操作位置，供今日接力判断
        "cycle_state": result.get("cycle_state") or {},
        "operation": result.get("operation") or {},
    }


def run_predict(day: str, *, config_dir, db_path=None, pred_dir: Path = PRED_DIR,
                model: str = DEFAULT_MODEL, client=None, force: bool = False,
                attr_dir=None, proposal_dir=None, overnight_root=None) -> dict:
    """对某日盲判。已完成日跳过（幂等）；error 日重跑覆盖。

    force=True 时强制重跑已完成日（数据修复场景）：覆盖前作废旧归因
    （supersede_attribution），新记录重置为 pending_maturity 重新走评分/结算。
    """
    path = prediction_path(day, pred_dir)
    if path.exists():
        try:
            old = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            old = {}
        if old.get("status") not in (None, "error"):
            if not force:
                return {"status": "skipped", "date": day}
            from investment_engine.shadow.attribute import supersede_attribution
            kw = {}
            if attr_dir is not None:
                kw["attr_dir"] = attr_dir
            if proposal_dir is not None:
                kw["proposal_dir"] = proposal_dir
            supersede_attribution(day, reason=f"prediction_rerun:{day}", **kw)
            path.unlink()

    try:
        pack = build_daily_pack(day, config_dir=Path(config_dir), db_path=db_path)
        # P0-3 连续状态：注入前一交易日复盘盲判摘要
        prior = _load_prior_summary(day, pred_dir=pred_dir, db_path=db_path)
        if prior:
            pack["prior_day"] = prior
        # 2026-08-20 复盘路径补注入隔夜外盘（与盘前同一精简结构，防泄漏同规）：
        # 复盘要答「外力/内生」题，隔夜美股映射个股必须可见
        from investment_engine.shadow.premarket import _load_overnight, slim_overnight
        overnight = _load_overnight(day, overnight_root)
        if overnight:
            pack["overnight_us"] = slim_overnight(overnight)
        text = pack_to_prompt(pack)  # 内含防泄漏断言
        raw, result, validation = run_with_validation(
            build_messages(text), pack, model=model, client=client,
            tag="shadow_predict", call_fn=call_deepseek)
        from investment_engine.shadow.factcheck import check_prediction
        fact_errors = check_prediction(
            result, day, extra_names=[s.get("name") for s in pack.get("stocks", [])])
        rec = {"date": day, "result": result, "raw": raw,
               "prompt_version": PROMPT_VERSION,
               "stage_hit": None, "due_scores": None, "status": "pending_maturity",
               "validation": validation}
        if fact_errors:
            rec["fact_errors"] = fact_errors
    except Exception as e:  # noqa: BLE001 - 失败留 error 记录，次日重跑
        rec = {"date": day, "status": "error", "error": str(e)[:200]}

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
    return rec
