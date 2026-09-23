"""盘中量能快照落盘（腾讯分钟线通道，不依赖东财）。

用途（2026-09-23 新增）：`intraday_amount_fetch.py` 依赖东财 60min amount，
而东财对本机云 IP 是重度间歇封禁（实测成功率 ~17%，push2his 曾 0/10）。
封禁窗口内 15:35 cron 完全无产出 → pre-run 拿不到量能字段 → LLM 拼数字。

本脚本用**腾讯分钟线**（实测稳定、1 次成功）落一个轻量量能快照，
作为封禁期的兜底产出：
    infra/data/intraday_amount/{yyyymmdd}_{HHMM}.json

字段（与 intraday_amount 的四点曲线互为补充，不取代它）：
    date / time / source / indices{now,pct,open,high,low,prev_close}
    / turnover{sh_yi,sz_yi,total_yi} / note

用法:
    PYTHONPATH=src .venv/bin/python scripts/intraday_turnover_snapshot.py
    PYTHONPATH=src .venv/bin/python scripts/intraday_turnover_snapshot.py --out-root infra/data/intraday_amount
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from qing_investment import marketdata as md  # noqa: E402


def _index_quote(code: str) -> dict | None:
    try:
        r = md.get_quotes([code], kind="index")
    except Exception:  # noqa: BLE001
        return None
    qs = r.get("quotes") or []
    if not qs:
        return None
    q = qs[0]
    return {"now": q.get("price"), "pct": q.get("change_pct"),
            "open": q.get("open"), "high": q.get("high"),
            "low": q.get("low"), "prev_close": q.get("prev_close")}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="盘中量能快照（腾讯分钟线兜底通道）")
    parser.add_argument("--out-root", default="infra/data/intraday_amount")
    parser.add_argument("--no-write", action="store_true",
                        help="只打印不落盘（联调用）")
    args = parser.parse_args(argv)

    now = datetime.now()
    day = now.strftime("%Y-%m-%d")
    try:
        total, src = md.get_market_turnover()
    except Exception as e:  # noqa: BLE001
        print(f"[turnover-snapshot] 量能不可用: {type(e).__name__}: {str(e)[:160]}",
              file=sys.stderr)
        return 1

    # 分指数拆解（失败不阻断整体）
    sh = sz = None
    try:
        sh, _ = md.get_turnover("sh000001", kind="index")
        sz, _ = md.get_turnover("sz399001", kind="index")
    except Exception:  # noqa: BLE001
        pass

    payload = {
        "date": day,
        "time": now.strftime("%H%M"),
        "source": f"marketdata get_market_turnover [{src}]",
        "indices": {k: v for k, v in (
            ("上证指数", _index_quote("sh000001")),
            ("深证成指", _index_quote("sz399001")),
            ("创业板指", _index_quote("sz399006")),
            ("科创50", _index_quote("sh000688")),
        ) if v},
        "turnover": {
            "sh_yi": round(sh / 1e8, 1) if sh else None,
            "sz_yi": round(sz / 1e8, 1) if sz else None,
            "total_yi": round(total / 1e8, 1),
        },
        "note": "腾讯分钟线累计成交额口径（元）。与 intraday_amount 的四点曲线互补；"
                "收盘后（15:00 之后）运行即为全天值。",
    }

    if args.no_write:
        print(json.dumps(payload, ensure_ascii=False, indent=1))
        return 0

    out_root = Path(args.out_root)
    out_root.mkdir(parents=True, exist_ok=True)
    path = out_root / f"{now.strftime('%Y%m%d_%H%M')}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n",
                    encoding="utf-8")
    print(f"[turnover-snapshot] 量能快照 → {path}  两市合计={payload['turnover']['total_yi']}亿")
    return 0


if __name__ == "__main__":
    sys.exit(main())
