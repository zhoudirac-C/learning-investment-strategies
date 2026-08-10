#!/usr/bin/env python
"""KPL 每日拉取入口（cron 工作日 15:45 调用）：情绪快照 + 当日资讯全文。

幂等：当日目标文件已存在则跳过对应部分，--force 覆盖重拉。
退出码：0 成功；1 拉取失败；2 配置缺失；3 鉴权失败（token 疑似失效，需重抓）。

手动: set -a && source .env && set +a && .venv/bin/python scripts/kpl_daily_fetch.py
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from investment_engine.kpl import emotion, news
from investment_engine.kpl.client import KplAuthError, KplClient, KplError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="KPL 每日数据拉取")
    parser.add_argument("--date", default=date.today().isoformat())
    parser.add_argument("--out-root", default="infra/data/kpl")
    parser.add_argument("--skip-emotion", action="store_true")
    parser.add_argument("--skip-news", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)

    day = datetime.strptime(args.date, "%Y-%m-%d").date()
    out_root = Path(args.out_root)
    try:
        client = KplClient.from_env()
    except KplError as e:
        print(f"[kpl] 配置错误: {e}", file=sys.stderr)
        return 2

    try:
        if not args.skip_emotion:
            target = out_root / "emotion" / f"{args.date}.json"
            if target.exists() and not args.force:
                print(f"[kpl] 情绪快照已存在，跳过: {target}")
            else:
                data = emotion.fetch_snapshot(client)
                path = emotion.save_snapshot(data, out_root, args.date)
                daban = data.get("daban") or {}
                print(f"[kpl] 情绪快照 → {path}  涨停={daban.get('tZhangTing')}"
                      f" 封板率={daban.get('tFengBan')}"
                      f" 连板数={len(data.get('lianban') or [])}")
        if not args.skip_news:
            target = out_root / "news" / args.date / "index.json"
            if target.exists() and not args.force:
                print(f"[kpl] 资讯已存在，跳过: {target.parent}")
            else:
                articles = news.fetch_day_news(client, day)
                out_dir = news.save_news(articles, out_root, args.date)
                print(f"[kpl] 资讯 → {out_dir}  共 {len(articles)} 篇")
    except KplAuthError as e:
        print(f"[kpl] {e}", file=sys.stderr)
        return 3
    except KplError as e:
        print(f"[kpl] 拉取失败: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
