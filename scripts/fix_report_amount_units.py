#!/usr/bin/env python3
"""修复历史 pre-run 报告中的「量能」单位错配事故（2026-09-23）。

## 事故
`_build_degraded_digest`（`agent/graph/nodes.py`）把腾讯/东财返回的 **元** 口径
`amount` 当 **万元** 处理（`/1e4`），量能数值放大 **1e4 倍**。
触发条件：market_summary LLM 子节点失败（llm_empty）→ 走规则拼装降级路径。

## ⚠️ 修复范围纪律（重要）
错误值在报告里出现**两类位置，必须区别对待**：

1. **原始数据段**：`量能：沪深合计约N亿` ← **修这个**
   （`【未加工原始数据】` 段里的权威数字，下游引用源头）

2. **报告元描述/引用**：如
   - `⚠️ 量能字段明显错误：\`沪深合计约87173482亿\`（单位溢出，实际为 8,872 亿）`
   - `🔴 pre-run 量能字段不可用（87173482亿），已在报告弃用并独立重采`
   ← **绝不能改**！这是报告**自己诊断并弃用**该值的纠错痕迹，
     改掉等于伪造历史、抹掉"系统曾发现此问题"的证据链。

因此本脚本**只匹配带 `量能：沪深合计约` 前缀的形态**，不做裸值替换。

## 换算
原代码 `元 / 1e4`（误当万元）→ 修复值 = 错误值 / 1e4（= 还原为亿）。
需通过日内时段合理性校验（开盘半小时 1500-9000 亿 / 上午 3000-15000 /
午前 5000-20000 / 午后 8000-30000），不过则保留原值待人工复核。

## 用法
    python3 scripts/fix_report_amount_units.py            # dry-run
    python3 scripts/fix_report_amount_units.py --apply    # 写入
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

CRON_OUTPUT = Path.home() / ".hermes" / "cron" / "output"

TIME_BUCKETS = {
    # 09 时段跨「开盘瞬间」与「9:30-10:00 前半场」，量级跨度极大：
    # 9:30-9:32 只有 100-500 亿，9:50-10:00 已达 3000-9000 亿 → 放宽下限
    "09": (50, 9000, "开盘半小时"),
    "10": (3000, 15000, "上午盘中"),
    "11": (5000, 20000, "上午收盘前"),
    "13": (8000, 25000, "午后开盘"),
    "14": (8000, 30000, "午后"),
}

#: ⚠️ 必须带 `量能：` 前缀——只修原始数据段，不碰元描述里的裸值
PATTERN = re.compile(r"量能：沪深合计约(\d{7,})亿")


def bucket_for(hh: str) -> tuple[int, int, str]:
    return TIME_BUCKETS.get(hh, (1000, 30000, "未知时段"))


def fix_text(text: str, filename: str) -> tuple[str, list[dict]]:
    m = re.search(r"\d{4}-\d{2}-\d{2}_(\d{2})-\d{2}-\d{2}", filename)
    hh = m.group(1) if m else ""
    lo, hi, label = bucket_for(hh)
    records: list[dict] = []

    def repl(mo: re.Match) -> str:
        n = int(mo.group(1))
        real = n / 10000.0
        ok = lo <= real <= hi
        records.append({"raw": n, "real": round(real, 1), "ok": ok,
                        "bucket": label, "time": hh})
        if not ok:
            return mo.group(0)
        return f"量能：沪深合计约{real:.0f}亿"

    return PATTERN.sub(repl, text), records


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="修复历史报告量能单位错配（仅原始数据段）")
    ap.add_argument("--apply", action="store_true", help="实际写入（默认 dry-run）")
    ap.add_argument("--dir", default=str(CRON_OUTPUT))
    args = ap.parse_args(argv)

    root = Path(args.dir)
    files = sorted(root.rglob("*.md")) + sorted(root.rglob("*.txt"))
    n_fix = n_skip = n_files = 0
    for f in files:
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            continue
        if not PATTERN.search(text):
            continue
        new, recs = fix_text(text, f.name)
        fixed = [r for r in recs if r["ok"]]
        skipped = [r for r in recs if not r["ok"]]
        n_fix += len(fixed)
        n_skip += len(skipped)
        if not recs:
            continue
        n_files += 1
        print(f"\n{f.relative_to(root)}")
        for r in recs:
            mark = "✅" if r["ok"] else "⚠️ 跳过(超合理区间)"
            print(f"   {r['raw']:>12}亿 → {r['real']:>9.1f}亿  "
                  f"[{r['time']} {r['bucket']}] {mark}")
        if fixed and args.apply:
            f.write_text(new, encoding="utf-8")
            print("   → 已写回")

    print(f"\n{'=' * 60}")
    print(f"涉及 {n_files} 文件 / 修 {n_fix} 处 / 跳过 {n_skip} 处"
          f"{'（已写入）' if args.apply else '（dry-run，加 --apply 写入）'}")
    print("注：报告元描述里的裸值（如「pre-run 量能字段不可用（87173482亿）」）"
          "按纪律不动——那是报告自身的纠错痕迹。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
