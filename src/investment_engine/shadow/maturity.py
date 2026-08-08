"""到期回填：prediction 满 5 个交易日后补方向/标的超额评分。"""
from __future__ import annotations

import json
from pathlib import Path

from investment_engine.backtest.history import list_trading_days
from investment_engine.blindtest.score import _direction_members, direction_scores, stock_scores
from investment_engine.shadow.predict import PRED_DIR

HORIZON = 5


def due_predictions(day: str, *, db_path=None, pred_dir: Path = PRED_DIR,
                    horizon: int = HORIZON) -> list[Path]:
    """找出截至 day 已到期的 prediction 文件（due_scores 尚未回填）。"""
    if not Path(pred_dir).exists():
        return []
    due = []
    for path in sorted(Path(pred_dir).glob("*.json")):
        try:
            rec = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if rec.get("status") != "pending_maturity" or rec.get("due_scores") is not None:
            continue
        pred_day = rec["date"]
        if pred_day >= day:
            continue
        days_between = list_trading_days(pred_day, day, db_path)
        if len(days_between) - 1 >= horizon:  # 不含 prediction 日本身
            due.append(path)
    return due


def run_maturity(day: str, *, config_dir, db_path=None, pred_dir: Path = PRED_DIR,
                 horizon: int = HORIZON) -> dict:
    """给到期 prediction 回填 due_scores，status 置 scored。"""
    stats = {"scored": 0}
    for path in due_predictions(day, db_path=db_path, pred_dir=pred_dir, horizon=horizon):
        rec = json.loads(path.read_text(encoding="utf-8"))
        results = [{"date": rec["date"], "ok": True, "result": rec["result"]}]
        dirs = direction_scores(results, config_dir=config_dir, db_path=db_path, horizon=horizon)
        stocks = stock_scores(results, db_path=db_path, horizon=horizon)
        rec["due_scores"] = {
            "directions": {k: v for k, v in dirs.items() if k != "details"},
            "stocks": {k: v for k, v in stocks.items() if k != "details"},
            "direction_details": dirs["details"],
        }
        rec["status"] = "scored"
        path.write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
        stats["scored"] += 1
    return stats
