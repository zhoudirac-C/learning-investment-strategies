"""每日盲判：复用 blindtest 数据包与 DeepSeek 契约，prediction 按日落盘。"""
from __future__ import annotations

import json
from pathlib import Path

from investment_engine.blindtest.dataset import build_daily_pack, pack_to_prompt
from investment_engine.blindtest.replay import DEFAULT_MODEL, build_messages, call_deepseek, parse_result

PRED_DIR = Path("evals/shadow/predictions")


def prediction_path(day: str, pred_dir: Path = PRED_DIR) -> Path:
    return Path(pred_dir) / f"{day}.json"


def has_fresh_data(day: str, db_path=None) -> bool:
    """缓存最新交易日期 == day 才算就绪。"""
    from investment_engine.backtest.history import list_trading_days

    days = list_trading_days("2000-01-01", day, db_path)
    return bool(days) and days[-1] == day


def run_predict(day: str, *, config_dir, db_path=None, pred_dir: Path = PRED_DIR,
                model: str = DEFAULT_MODEL, client=None) -> dict:
    """对某日盲判。已完成日跳过（幂等）；error 日重跑覆盖。"""
    path = prediction_path(day, pred_dir)
    if path.exists():
        try:
            old = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            old = {}
        if old.get("status") not in (None, "error"):
            return {"status": "skipped", "date": day}

    try:
        pack = build_daily_pack(day, config_dir=Path(config_dir), db_path=db_path)
        text = pack_to_prompt(pack)  # 内含防泄漏断言
        raw = call_deepseek(build_messages(text), model=model, client=client)
        result = parse_result(raw)
        rec = {"date": day, "result": result, "raw": raw,
               "stage_hit": None, "due_scores": None, "status": "pending_maturity"}
    except Exception as e:  # noqa: BLE001 - 失败留 error 记录，次日重跑
        rec = {"date": day, "status": "error", "error": str(e)[:200]}

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
    return rec
