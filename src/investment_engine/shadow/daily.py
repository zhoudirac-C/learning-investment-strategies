"""每日编排：数据就绪检查 → 盲判 → 当日阶段评分 → 到期回填 → 判错归因。"""
from __future__ import annotations

import json
from pathlib import Path

from investment_engine.blindtest.replay import DEFAULT_MODEL  # noqa: F401 - run() 默认模型统一走 replay.py
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
        proposal_dir: Path = PROPOSAL_DIR, model: str = DEFAULT_MODEL,
        client=None, force: bool = False) -> dict:
    if not has_fresh_data(day, db_path=db_path):
        return {"date": day, "status": "no_data"}

    pred = run_predict(day, config_dir=config_dir, db_path=db_path,
                       pred_dir=pred_dir, model=model, client=client, force=force,
                       attr_dir=attr_dir, proposal_dir=proposal_dir)
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
    pre = None
    if pre_path.exists():
        pre = json.loads(pre_path.read_text(encoding="utf-8"))
        if pre.get("status") == "pending_maturity" and pre.get("stage_hit") is None:
            truth = load_truth(db_path=db_path)
            label = truth.get(day)
            if label is not None:
                pre["stage_hit"] = pre["result"].get("market_stage") == label
                pre_path.write_text(json.dumps(pre, ensure_ascii=False, indent=2), encoding="utf-8")

    # 历史 pending_maturity 记录 stage_hit sweep 回填（提案 2026-09-05 工程问题 4）：
    # 收盘轨 429 缺席时当日记录 stage_hit 永久空缺（08-31~09-02-pre 三连空缺根因），
    # 后续成功运行日 sweep 全目录补回填；error 记录不动（无 result 可比对）
    truth_all = load_truth(db_path=db_path)
    if truth_all:
        for path in sorted(Path(pred_dir).glob("*.json")):
            try:
                old = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            if old.get("status") == "error" or old.get("stage_hit") is not None:
                continue
            old_day = str(old.get("date") or "")
            label = truth_all.get(old_day)
            if not old_day or label is None:
                continue
            old_stage = (old.get("result") or {}).get("market_stage")
            if not old_stage:
                continue
            old["stage_hit"] = old_stage == label
            path.write_text(json.dumps(old, ensure_ascii=False, indent=2),
                            encoding="utf-8")

    # 到期回填 + 到期日的 direction_miss 归因
    mat = run_maturity(day, config_dir=config_dir, db_path=db_path, pred_dir=pred_dir)
    attributed = []

    # 早盘判错同样归因（2026-08-27 补缺口：8-20/8-24 早盘 stage_miss 漏归因）
    if pre is not None and pre.get("stage_hit") is False:
        run_attribution(day, trigger="stage_miss_premarket", pred=pre,
                        score_info={"truth": load_truth(db_path=db_path).get(day),
                                    "track": "premarket"},
                        attr_dir=attr_dir, proposal_dir=proposal_dir,
                        model=model, client=client)
        attributed.append(day)

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
