"""v24 LLM 回归：对恐慌簇 3 个错判日以 v24 prompt 重跑盘后盲判。
临时 pred_dir=/tmp/v24-regression/，不触碰仓库预测记录。"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from investment_engine.shadow.predict import run_predict

DAYS = ["2026-10-15", "2026-10-16", "2026-10-22"]
CONFIG = Path(__file__).resolve().parent.parent / "config/stock_monitor"

for day in DAYS:
    tmp = Path(tempfile.mkdtemp(prefix=f"v24-{day}-", dir="/tmp/v24-regression"))
    try:
        rec = run_predict(day, config_dir=CONFIG, pred_dir=tmp, force=True)
        result = rec.get("result") or {}
        v = [x for x in (rec.get("validation") or [])]
        print(f"== {day} ==", flush=True)
        print(json.dumps({
            "stage": result.get("market_stage"),
            "nature": result.get("nature"),
            "validation": v,
            "prompt_version": rec.get("prompt_version"),
        }, ensure_ascii=False))
    except Exception as e:
        print(f"== {day} == FAILED: {str(e)[:200]}", flush=True)
    print(f"tmp_pred: {tmp}", flush=True)
