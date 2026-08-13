"""每日编排：数据就绪检查 → 盲判 → 当日阶段评分 → 到期回填 → 判错归因。"""
from __future__ import annotations

import json
from pathlib import Path

from investment_engine.blindtest.truth import load_truth
from investment_engine.shadow.attribute import ATTR_DIR, PROPOSAL_DIR, run_attribution
from investment_engine.shadow.maturity import run_maturity
from investment_engine.shadow.predict import PRED_DIR, has_fresh_data, prediction_path, run_predict


def _direction_missed(rec: dict) -> bool:
    """到期方向超额均值 ≤0 视为 direction_miss。"""
    details = (rec.get("due_scores") or {}).get("direction_details") or []
    if not details:
        return False
    excess = [d["dir_ret"] - d["bench_ret"] for d in details]
    return sum(excess) / len(excess) <= 0


def run(day: str, *, config_dir, db_path=None,
        pred_dir: Path = PRED_DIR, attr_dir: Path = ATTR_DIR,
        proposal_dir: Path = PROPOSAL_DIR, model: str = "deepseek-chat",
        client=None) -> dict:
    if not has_fresh_data(day, db_path=db_path):
        return {"date": day, "status": "no_data"}

    pred = run_predict(day, config_dir=config_dir, db_path=db_path,
                       pred_dir=pred_dir, model=model, client=client)
    if pred.get("status") == "error":
        return {"date": day, "status": "predict_error", "error": pred.get("error")}

    # 当日阶段评分（skipped 日读已有记录）
    rec_path = prediction_path(day, pred_dir)
    rec = json.loads(rec_path.read_text(encoding="utf-8"))
    if rec.get("stage_hit") is None:
        truth = load_truth(db_path=db_path)
        label = truth.get(day)
        if label is not None:
            rec["stage_hit"] = rec["result"].get("market_stage") == label
            rec_path.write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")

    # 回填当日早盘盲判（-pre）的 stage_hit（同一份真值，收盘后才有）
    from investment_engine.shadow.premarket import premarket_path
    pre_path = premarket_path(day, pred_dir)
    if pre_path.exists():
        pre = json.loads(pre_path.read_text(encoding="utf-8"))
        if pre.get("status") == "pending_maturity" and pre.get("stage_hit") is None:
            truth = load_truth(db_path=db_path)
            label = truth.get(day)
            if label is not None:
                pre["stage_hit"] = pre["result"].get("market_stage") == label
                pre_path.write_text(json.dumps(pre, ensure_ascii=False, indent=2), encoding="utf-8")

    # 到期回填 + 到期日的 direction_miss 归因
    mat = run_maturity(day, config_dir=config_dir, db_path=db_path, pred_dir=pred_dir)
    attributed = []

    if rec.get("stage_hit") is False:
        run_attribution(day, trigger="stage_miss", pred=rec,
                        score_info={"truth": load_truth(db_path=db_path).get(day)},
                        attr_dir=attr_dir, proposal_dir=proposal_dir,
                        model=model, client=client)
        attributed.append(day)

    # 到期且方向判错的往日归因
    if mat["scored"]:
        for path in sorted(Path(pred_dir).glob("*.json")):
            old = json.loads(path.read_text(encoding="utf-8"))
            if old.get("status") == "scored" and _direction_missed(old) \
                    and not (Path(attr_dir) / f"{old['date']}.json").exists():
                run_attribution(old["date"], trigger="direction_miss", pred=old,
                                score_info=old.get("due_scores") or {},
                                attr_dir=attr_dir, proposal_dir=proposal_dir,
                                model=model, client=client)
                attributed.append(old["date"])

    return {"date": day, "status": "ok", "stage_hit": rec.get("stage_hit"),
            "matured": mat["scored"], "attributed": bool(attributed),
            "attributed_days": attributed}
