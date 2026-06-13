#!/usr/bin/env python3
"""watchlist.yaml 字段完整性校验脚本。

检查每只 stock 是否具备 poll 正常运行所需的必要字段。
输出分级报告：❌ 致命 / ⚠️ 警告 / ✅ 通过。

用法:
    python scripts/validate_watchlist.py              # 完整报告
    python scripts/validate_watchlist.py --json        # JSON 输出（供 LLM 消费）
    python scripts/validate_watchlist.py --fix-null    # 修复 price_range 文本描述 → null
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import yaml

# ── 项目根路径 ──
REPO_ROOT = Path(__file__).parent.parent


def load_watchlist() -> dict:
    path = REPO_ROOT / "config" / "stock_monitor" / "watchlist.yaml"
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def save_watchlist(data: dict):
    path = REPO_ROOT / "config" / "stock_monitor" / "watchlist.yaml"
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, sort_keys=False, default_flow_style=False)
    print(f"✅ 已保存: {path}")


def count_stocks(data: dict) -> int:
    return sum(len(t.get("stocks", [])) for t in data.get("themes", []))


def validate_all(data: dict) -> list[dict]:
    """校验每只 stock，返回验证结果列表。"""
    results: list[dict] = []
    for theme in data.get("themes", []):
        theme_id = theme.get("id", "?")
        for stock in theme.get("stocks", []):
            issues = _check_stock(stock, theme_id)
            results.append({
                "code": stock.get("code", ""),
                "name": stock.get("name", ""),
                "priority": stock.get("priority", ""),
                "theme": theme_id,
                "issues": issues,
            })
    return results


def _check_stock(stock: dict, theme_id: str) -> list[dict]:
    """检查单只 stock，返回问题列表。"""
    issues: list[dict] = []
    code = stock.get("code", "") or ""
    name = stock.get("name", "") or ""
    priority = str(stock.get("priority", ""))
    ez = stock.get("entry_zone") or {}
    pr = (ez or {}).get("price_range", "")

    # ── P0：缺少关键字段 ──
    if not code:
        issues.append({"level": "❌", "field": "code", "msg": "缺少 code"})
    if not name:
        issues.append({"level": "❌", "field": "name", "msg": f"[{code}] 缺少 name"})
    if not priority:
        issues.append({"level": "❌", "field": "priority", "msg": f"[{code}] 缺少 priority"})

    # ── P1：P1/P2 标的缺少 price_range ──
    # 已持仓标的(holding)允许price_range为null，因为不再设介入区间
    lifecycle_stage = (stock.get("lifecycle") or {}).get("stage", "")
    is_holding = lifecycle_stage == "holding"

    if priority.startswith("P1") or priority.startswith("P2"):
        if not pr and not is_holding:
            issues.append({"level": "❌", "field": "entry_zone.price_range",
                           "msg": f"[{code}/{name}] {priority} 缺少 price_range"})
        elif not pr and is_holding:
            # 已持仓标的price_range=null是设计意图，跳过
            pass
        elif not re.search(r"\d+\.?\d*\s*[~\-]\s*\d+\.?\d*", str(pr)):
            issues.append({"level": "⚠️", "field": "entry_zone.price_range",
                           "msg": f"[{code}/{name}] price_range 格式异常: '{pr}'，建议改为 null 或数字区间"})
        if not ez.get("hard_stop") and not is_holding:
            issues.append({"level": "⚠️", "field": "entry_zone.hard_stop",
                           "msg": f"[{code}/{name}] {priority} 缺少 hard_stop"})

    # ── 跨字段检查 ──
    if "buy_setup" in stock and ez:
        issues.append({"level": "⚠️", "field": "buy_setup",
                       "msg": f"[{code}/{name}] 同时有 buy_setup 和 entry_zone，字段重叠"})

    return issues


def check_duplicates(data: dict) -> list[dict]:
    """检查跨 theme 重复标的。"""
    seen: dict[str, list[str]] = {}
    for theme in data.get("themes", []):
        tid = theme.get("id", "?")
        for stock in theme.get("stocks", []):
            code = stock.get("code", "")
            if code:
                seen.setdefault(code, []).append(tid)
    dups = []
    for code, themes in seen.items():
        if len(themes) > 1:
            dups.append({"code": code, "themes": themes})
    return dups


def print_report(results: list[dict], duplicates: list[dict]):
    """打印人类可读的报告。"""
    errors = [r for r in results for i in r["issues"] if i["level"] == "❌"]
    warnings = [r for r in results for i in r["issues"] if i["level"] == "⚠️"]
    clean = [r for r in results if not r["issues"]]

    print(f"\n{'='*60}")
    print(f"  Watchlist 字段完整性校验报告")
    print(f"  共 {len(results)} 只 stock: "
          f"{len(errors)} ❌, {len(warnings)} ⚠️, {len(clean)} ✅")
    print(f"{'='*60}\n")

    if errors:
        print(f"┃ ❌ 致命问题 ({len(errors)})\n")
        for r in results:
            for i in r["issues"]:
                if i["level"] == "❌":
                    print(f"  {i['msg']}")
        print()

    if warnings:
        print(f"┃ ⚠️ 警告 ({len(warnings)})\n")
        for r in results:
            for i in r["issues"]:
                if i["level"] == "⚠️":
                    print(f"  {i['msg']}")
        print()

    if duplicates:
        print(f"┃ 🔄 跨 theme 重复 ({len(duplicates)})\n")
        for d in duplicates:
            print(f"  {d['code']} 出现在: {', '.join(d['themes'])}")
        print()

    print(f"✅ 完好: {len(clean)} 只")
    for r in clean:
        print(f"  {r['code']:8s} {r['name']:8s} {r['priority']:6s} [{r['theme']}]")


def fix_price_range_text_to_null(data: dict) -> int:
    """修复 price_range 为文本描述而非数字区间的字段 → null。"""
    fixed = 0
    for theme in data.get("themes", []):
        for stock in theme.get("stocks", []):
            ez = stock.get("entry_zone") or {}
            pr = (ez or {}).get("price_range", "")
            if pr and not re.search(r"\d+\.?\d*\s*[~\-]\s*\d+\.?\d*", str(pr)):
                ez["price_range"] = None
                fixed += 1
    return fixed


def main():
    parser = argparse.ArgumentParser(description="watchlist 字段完整性校验")
    parser.add_argument("--json", action="store_true", help="JSON 输出")
    parser.add_argument("--fix-null", action="store_true", help="修复 price_range 文本描述 → null")
    args = parser.parse_args()

    data = load_watchlist()
    results = validate_all(data)
    duplicates = check_duplicates(data)

    if args.fix_null:
        fixed = fix_price_range_text_to_null(data)
        if fixed:
            save_watchlist(data)
            print(f"已修复 {fixed} 处 price_range 文本描述 → null")
            # 重新校验
            results = validate_all(data)
            duplicates = check_duplicates(data)

    if args.json:
        summary = {
            "total": len(results),
            "errors": sum(1 for r in results for i in r["issues"] if i["level"] == "❌"),
            "warnings": sum(1 for r in results for i in r["issues"] if i["level"] == "⚠️"),
            "clean": sum(1 for r in results if not r["issues"]),
            "duplicates": len(duplicates),
            "details": results,
            "duplicate_list": duplicates,
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print_report(results, duplicates)

    # exit code = 有致命问题
    has_errors = any(i["level"] == "❌" for r in results for i in r["issues"])
    sys.exit(1 if has_errors else 0)


if __name__ == "__main__":
    main()
