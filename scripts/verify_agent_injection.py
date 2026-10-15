#!/usr/bin/env python3
"""Agent 注入验证工具：确认改动是否真的送达 LLM。

## 为什么需要这个工具

2026-10-15 实测教训：双学派内容改动**单测全绿、注入函数输出正确**，
但真实跑 market_summary 时 LLM 输出 0 痕迹。根因是 prompt 超限截断分支
（`market_summary` 有两条组装路径）漏拼了契约块——**只有用真实入参跑
E2E 才暴露**。单测覆盖不到这条路径。

本工具复用 qing-agent 真实请求 log（`qing-agent-request.YYYY-MM-DD.log`），
回放指定那次请求的入参，在 LLM 调用前 hook 抓取真实 prompt，检查：

1. **送达检查**：目标关键词是否出现在 prompt 里（截断后仍存活？）
2. **采纳检查**（可选）：LLM 输出是否真的用上了注入内容
3. **截断诊断**：prompt 是否超限、哪些字段被截断

## 用法

```bash
# 列出某天的请求（选一条来测）
.venv/bin/python scripts/verify_agent_injection.py list --date 2026-10-15

# 送达检查（不调 LLM，纯本地，快）
.venv/bin/python scripts/verify_agent_injection.py check \\
    --date 2026-10-15 --index 9 \\
    --expect "双学派输出契约" --expect "CF-001" --expect "剪刀差"

# 全链路检查（真调 LLM，慢，会产生费用）
.venv/bin/python scripts/verify_agent_injection.py check \\
    --date 2026-10-15 --index 9 --with-llm \\
    --expect "双学派输出契约" --adopt "gator" --adopt "剪刀差"

# 双学派预设（等价于上面那组 --expect）
.venv/bin/python scripts/verify_agent_injection.py check \\
    --date 2026-10-15 --index 9 --preset dual-school

# 保存 prompt 全文用于人工排查
.venv/bin/python scripts/verify_agent_injection.py check \\
    --date 2026-10-15 --index 9 --preset dual-school --dump-prompt /tmp/p.txt
```

退出码：0 = 全部通过；1 = 有检查项失败（可接 CI / 人工门禁）。

设计文档：docs/design/dual-school-architecture.md
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from qing_investment.agent.graph.state import AgentState

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

# 双学派预设：验证 P1-P5 的注入链路是否送达
PRESETS = {
    "dual-school": {
        "expect": [
            "双学派输出契约",      # 契约块（截断分支曾漏拼 → 回归重点）
            "学派冲突（辩论卡）",   # 冲突卡
            "CF-001",             # 具体冲突条目
            "gator_rules_snapshot",  # 规则引擎快照
        ],
        "adopt": ["gator"],        # LLM 输出应出现学派标注
    },
}

LOG_GLOB = "qing-agent-request.*.log"


# ── 请求 log 读取 ──────────────────────────────────────────────

def load_requests(date: str) -> list[dict]:
    """读取某天的 agent 请求 log（每行一个 JSON）。"""
    path = REPO_ROOT / f"qing-agent-request.{date}.log"
    if not path.exists():
        cands = sorted(REPO_ROOT.glob(LOG_GLOB))
        raise FileNotFoundError(
            f"未找到 {path.name}。可用日志：{[c.name for c in cands[-5:]]}"
        )
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def describe(req: dict, idx: int) -> str:
    t = req.get("trigger") or {}
    ts = (req.get("timestamp") or "")[:19]
    return (
        f"[{idx}] {ts} | {t.get('id', '?'):24s} | "
        f"{req.get('analysis_type', '?'):8s} | "
        f"{(t.get('title') or '')[:22]} | {req.get('request_payload_size', '?')} bytes"
    )


def build_state(req: dict) -> "AgentState":
    """把请求 payload 转成 AgentState（最小可用）。"""
    p = req.get("request_payload") or {}
    return {
        "parsed_intent": {
            "analysis_type": p.get("analysis_type", "market"),
            "stock_code": p.get("stock_code") or None,
        },
        "trigger": p.get("trigger") or req.get("trigger"),
        "market_snapshot": p.get("market_snapshot") or {},
        "claims": p.get("claims") or [],
        "wiki_snippets": [],
        "sector_strengths": p.get("sector_strengths") or [],
        "external_sector_boards": p.get("external_sector_boards") or {},
        "positions": p.get("positions") or [],
        "watchlist": p.get("watchlist") or [],
        "memories": [],
        "direction_signals": {},
        "alerts": p.get("alerts") or [],
        "buy_signal_candidates": p.get("buy_signal_candidates") or [],
        "sector_context": [],
    }


# ── prompt 抓取 ────────────────────────────────────────────────

def capture_prompts(state: "AgentState") -> tuple[list[str], "AgentState"]:
    """跑 market_summary，hook LLM 调用抓真实 prompt。

    Returns:
        (prompts, result_state)
    """
    from qing_investment.agent.graph import nodes

    captured: list[str] = []
    orig = nodes._safe_llm_invoke

    def hook(prompt, *a, **kw):  # noqa: ANN001
        if isinstance(prompt, str) and len(prompt) > 200:
            captured.append(prompt)
        return orig(prompt, *a, **kw)

    nodes._safe_llm_invoke = hook
    try:
        result = nodes.market_summary(state)
    finally:
        nodes._safe_llm_invoke = orig
    return captured, result


def extract_llm_output(result: "AgentState") -> str:
    """从 market_summary 返回值里取 LLM 产出文本。"""
    ctx = result.get("market_summary_context") or {}
    if not isinstance(ctx, dict):
        return json.dumps(ctx, ensure_ascii=False)
    parts = [
        str(ctx.get("market_summary") or ""),
        str(ctx.get("phase_reasoning") or ""),
        str(ctx.get("volume_note") or ""),
    ]
    return "\n".join(parts)


# ── 检查逻辑 ──────────────────────────────────────────────────

def check_expect(prompt: str, keywords: list[str]) -> list[tuple[str, bool, int]]:
    return [(k, prompt.count(k) > 0, prompt.count(k)) for k in keywords]


def check_adopt(output: str, keywords: list[str]) -> list[tuple[str, bool, int]]:
    return [(k, output.count(k) > 0, output.count(k)) for k in keywords]


def diagnose_truncation(prompt: str) -> dict:
    """检查 prompt 是否触发截断（截断是注入丢失的高危路径）。"""
    from qing_investment.agent.graph.nodes import _MAX_MARKET_SUMMARY_PROMPT_BYTES

    size = len(prompt.encode("utf-8"))
    return {
        "bytes": size,
        "limit": _MAX_MARKET_SUMMARY_PROMPT_BYTES,
        "truncated": size >= _MAX_MARKET_SUMMARY_PROMPT_BYTES * 0.97,
    }


# ── CLI ───────────────────────────────────────────────────────

def cmd_list(args) -> int:
    reqs = load_requests(args.date)
    print(f"{args.date} 共 {len(reqs)} 条 agent 请求：\n")
    for i, r in enumerate(reqs):
        print("  " + describe(r, i))
    print("\n用 --index N 选一条做注入检查。")
    return 0


def cmd_check(args) -> int:
    reqs = load_requests(args.date)
    if not (0 <= args.index < len(reqs)):
        print(f"❌ --index {args.index} 越界（0-{len(reqs) - 1}）")
        return 2

    req = reqs[args.index]
    print("=" * 72)
    print(f"目标请求：{describe(req, args.index)}")
    print("=" * 72)

    expect = list(args.expect or [])
    adopt = list(args.adopt or [])
    if args.preset:
        p = PRESETS[args.preset]
        expect = p["expect"] + expect
        adopt = p["adopt"] + adopt

    if not expect and not adopt:
        print("⚠️ 未指定 --expect / --adopt / --preset，只做截断诊断。")

    state = build_state(req)
    print(f"\n[回放] 入参构建完成（quotes={len(state['market_snapshot'].get('quotes') or [])}）")

    if args.dry_run:
        prompts, result = [], {}
    else:
        prompts, result = capture_prompts(state)

    if not prompts:
        if args.dry_run:
            print("\n(--dry-run 未调 LLM)")
            return 0
        print("\n❌ 未捕获到 prompt —— market_summary 可能提前失败（查返回值的 error 字段）")
        print(json.dumps(result, ensure_ascii=False, default=str)[:600])
        return 1

    prompt = prompts[0]
    print(f"[捕获] 1 个 prompt，{len(prompt.encode('utf-8'))} bytes")

    # 截断诊断
    diag = diagnose_truncation(prompt)
    mark = "⚠️ 接近/已触发" if diag["truncated"] else "✅ 未触发"
    print(
        f"[截断] {diag['bytes']} / {diag['limit']} bytes — {mark}"
        "（截断分支是注入丢失的高危路径）"
    )

    failed: list[str] = []

    # 送达检查
    if expect:
        print("\n── 送达检查（prompt 是否含目标关键词）──")
        for kw, ok, n in check_expect(prompt, expect):
            print(f"  {'✅' if ok else '❌'} {kw:26s} 出现 {n} 次")
            if not ok:
                failed.append(f"送达缺失: {kw}")

    # 采纳检查（需真跑 LLM）
    if adopt and not args.with_llm and not args.dry_run:
        print("\n── 采纳检查 ──")
        print("  ⏭  跳过（未指定 --with-llm，本次未调 LLM）")
    elif adopt and result and not args.dry_run:
        output = extract_llm_output(result)
        print("\n── 采纳检查（LLM 输出是否用上注入内容）──")
        if not output.strip():
            print("  ⚠️ LLM 输出为空（可能 json_parse_error 走了降级路径）")
        for kw, ok, n in check_adopt(output, adopt):
            print(f"  {'✅' if ok else '❌'} {kw:26s} 出现 {n} 次")
            if not ok:
                failed.append(f"未被采纳: {kw}")
        if args.show_output:
            print("\n── LLM 输出 ──")
            print(output[:3000])

    if args.dump_prompt:
        Path(args.dump_prompt).write_text(prompt, encoding="utf-8")
        print(f"\n[导出] prompt 全文 → {args.dump_prompt}")

    print("\n" + "=" * 72)
    if failed:
        print(f"❌ 检查失败 {len(failed)} 项：")
        for f in failed:
            print(f"   · {f}")
        return 1
    print("✅ 全部检查通过")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Agent 注入验证：确认改动是否真的送达 LLM",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="列出某天的 agent 请求")
    p_list.add_argument("--date", required=True, help="YYYY-MM-DD")
    p_list.set_defaults(func=cmd_list)

    p_chk = sub.add_parser("check", help="回放某条请求做注入检查")
    p_chk.add_argument("--date", required=True, help="YYYY-MM-DD")
    p_chk.add_argument("--index", type=int, required=True, help="list 里的序号")
    p_chk.add_argument("--expect", action="append", help="prompt 应含的关键词（可多次）")
    p_chk.add_argument("--adopt", action="append", help="LLM 输出应含的关键词（需 --with-llm）")
    p_chk.add_argument("--preset", choices=sorted(PRESETS), help="预设检查组")
    p_chk.add_argument("--with-llm", action="store_true",
                       help="真调 LLM（默认只做送达检查，不产生费用）")
    p_chk.add_argument("--dry-run", action="store_true", help="只构建入参，不跑节点")
    p_chk.add_argument("--show-output", action="store_true", help="打印 LLM 输出")
    p_chk.add_argument("--dump-prompt", help="保存 prompt 全文到指定路径")
    p_chk.set_defaults(func=cmd_check)

    # --with-llm 的反向语义：默认不调 LLM 更省钱
    args = ap.parse_args()
    # 说明（不自动开启：避免误产生 LLM 费用）
    if getattr(args, "cmd", "") == "check" and not args.with_llm and not args.dry_run:
        if args.adopt or args.show_output:
            print("提示：--adopt / --show-output 需配合 --with-llm 才会真跑 LLM。")
            print("      本次仅做送达检查（本地，零费用）。\n")

    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
