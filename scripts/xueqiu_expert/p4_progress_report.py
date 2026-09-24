#!/usr/bin/env python3
"""雪球大牛回测 P4/P5 进度报告（cron 每 2h 播报，no_agent）。

数据源（全部只读）：
  logs/p4_verdict_run.log        主日志（阶段进度行）
  logs/llm_calls_p4.jsonl        LLM 调用落账（活性 + 兜底切换证据）
  data/xueqiu/candidates_posts.json / verdicts/ / expert_ranking.json
  sources/raw/xueqiu/            全文快照计数

输出语义：stdout 非空即投递飞书——每次都报进度；异常用 ❌/⚠️ 前缀。
永远 exit 0（进度播报不是故障，故障信息写在报告里）。
"""
from __future__ import annotations

import json
import re
import subprocess
import time
from pathlib import Path

ROOT = Path("/home/ubuntu/learning-investment-strategies")
RUN_LOG = ROOT / "logs" / "p4_verdict_run.log"
LLM_LOG = ROOT / "logs" / "llm_calls_p4.jsonl"
CAND = ROOT / "data" / "xueqiu" / "candidates_posts.json"
VERDICTS = ROOT / "data" / "xueqiu" / "verdicts"
RANKING = ROOT / "data" / "xueqiu" / "expert_ranking.json"
SNAPS = ROOT / "sources" / "raw" / "xueqiu"
STALL_MIN = 30  # 主日志+LLM账本都超过此分钟数无新内容 → 疑似卡住


def alive() -> bool:
    r = subprocess.run(["pgrep", "-fc", "scripts/xueqiu_expert/verdict_pipeline.py"],
                       capture_output=True, text=True)
    try:
        return int(r.stdout.strip() or "0") > 0
    except ValueError:
        return False


def age_minutes(path: Path) -> float | None:
    try:
        return (time.time() - path.stat().st_mtime) / 60
    except OSError:
        return None


def _last(rex: str, text: str):
    ms = list(re.finditer(rex, text))
    return ms[-1] if ms else None


def parse_run_log(text: str) -> dict:
    out = {"phase": "unknown", "errors": 0}
    pats = {
        "select_done": r"候选帖落盘 (\d+) 条（硬层 (\d+) / LLM兜底 (\d+)）",
        "tag": r"LLM 标签兜底进度 (\d+)/(\d+)",
        "fetch": r"全文进度 (\d+)/(\d+) \(ok (\d+) / miss (\d+) / skip (\d+)\)",
        "fetch_done": r"全文完成：新增 (\d+)，失败 (\d+)（回退摘要判定），已有 (\d+)",
        "judge": r"判定进度 (\d+)/(\d+)（有命中帖 (\d+) / 无 (\d+)）",
        "judge_done": r"判定完成：判定帖 (\d+)，覆盖 (\d+) 人",
        "ranking": r"TOP20 →",
    }
    m = _last(pats["select_done"], text)
    if m:
        out["select"] = {"candidates": int(m.group(1)), "hard": int(m.group(2)),
                         "llm": int(m.group(3))}
    m = _last(pats["tag"], text)
    if m:
        out["phase"] = "llm_tag"
        out["tag"] = {"done": int(m.group(1)), "total": int(m.group(2))}
    m = _last(pats["fetch"], text)
    if m:
        out["phase"] = "fetch"
        out["fetch"] = {"done": int(m.group(1)), "total": int(m.group(2)),
                        "ok": int(m.group(3)), "miss": int(m.group(4))}
    m = _last(pats["fetch_done"], text)
    if m:
        out["fetch_done"] = {"new": int(m.group(1)), "miss": int(m.group(2)),
                             "skip": int(m.group(3))}
    m = _last(pats["judge"], text)
    if m:
        out["phase"] = "judge"
        out["judge"] = {"done": int(m.group(1)), "total": int(m.group(2)),
                        "hit": int(m.group(3))}
    if re.search(pats["judge_done"], text):
        out["phase"] = "judge_done"
    if re.search(pats["ranking"], text):
        out["phase"] = "ranking_done"
    out["errors"] = len(re.findall(r"⚠️|Traceback|全链失败", text))
    return out


def llm_health() -> dict:
    try:
        lines = LLM_LOG.read_text().strip().splitlines()[-300:]
    except OSError:
        return {}
    recs = []
    for ln in lines:
        try:
            recs.append(json.loads(ln))
        except json.JSONDecodeError:
            continue
    if not recs:
        return {}
    hour_ago = time.time() - 3600
    recent = [r for r in recs if r.get("ts", "") >= time.strftime(
        "%Y-%m-%dT%H:%M", time.localtime(hour_ago))]
    ok_recent = [r for r in recent if r.get("ok")]
    last_ok = next((r for r in reversed(recs) if r.get("ok")), None)
    return {
        "last_model": (last_ok or {}).get("model", "?"),
        "fail_1h": len(recent) - len(ok_recent),
        "ok_1h": len(ok_recent),
        "judge_1h": sum(1 for r in recent if r.get("kind") == "judge" and r.get("ok")),
        "tag_1h": sum(1 for r in recent if r.get("kind") == "tag" and r.get("ok")),
    }


def main() -> None:
    lines: list[str] = []
    running = alive()
    run_age = age_minutes(RUN_LOG)
    llm_age = age_minutes(LLM_LOG)
    log_text = ""
    try:
        log_text = RUN_LOG.read_text(errors="replace")
    except OSError:
        pass
    info = parse_run_log(log_text)
    health = llm_health()

    if RANKING.exists():
        lines.append("✅ **雪球P4/P5 已全部完成**（expert_ranking.json 已产出）")
        try:
            rep = json.loads(RANKING.read_text())
            sr = rep.get("sample_review", {})
            lines.append(f"- 评估 {rep.get('experts_evaluated')} 人 | "
                         f"抽样复核 {sr.get('judged', 0)}/{sr.get('total', 20)}"
                         f"（误差率 {sr.get('machine_error_rate')}）")
            for r in rep.get("top20", [])[:5]:
                lines.append(f"  #{r.get('rank')} {r.get('screen_name')} "
                             f"综合{r.get('composite')} 强{r.get('strong')}/中{r.get('mid')}")
        except Exception as e:  # noqa: BLE001
            lines.append(f"⚠️ ranking 读取失败: {e}")
        lines.append("- 本播报任务可以关闭：回复「停止 雪球P4进度播报」")
    elif not running and run_age is not None and run_age > 5:
        lines.append("❌ **P4 进程已退出但未产出 expert_ranking.json —— 疑似中断！**")
        lines.append(f"- 主日志最后更新 {run_age:.0f} 分钟前，请检查 logs/p4_verdict_run.log 尾部")
        lines.append("- 断点已落盘（候选/快照/判定进度），重新拉起即可续跑")
    else:
        phase = info["phase"]
        lines.append(f"📊 **雪球P4 进度**（{'🟢 运行中' if running else '🟡 进程不在（可能阶段间落盘）'})")
        if "select" in info:
            s = info["select"]
            lines.append(f"- 候选帖选择：{s['candidates']} 条（硬层 {s['hard']} / LLM兜底 {s['llm']}）")
        if phase == "llm_tag" and "tag" in info:
            t = info["tag"]
            pct = t["done"] / t["total"] * 100 if t["total"] else 0
            lines.append(f"- 阶段①LLM标签兜底：{t['done']}/{t['total']}（{pct:.0f}%）")
        elif phase == "fetch" and "fetch" in info:
            f_ = info["fetch"]
            pct = f_["done"] / f_["total"] * 100 if f_["total"] else 0
            lines.append(f"- 阶段②全文抓取：{f_['done']}/{f_['total']}（{pct:.0f}%，"
                         f"成功 {f_['ok']} / 失败回退 {f_['miss']}）")
        elif "fetch_done" in info and phase == "judge":
            pass
        if phase == "judge" and "judge" in info:
            j = info["judge"]
            pct = j["done"] / j["total"] * 100 if j["total"] else 0
            lines.append(f"- 阶段③LLM判定：{j['done']}/{j['total']}（{pct:.0f}%，"
                         f"命中帖 {j['hit']}）")
        if info["phase"] == "judge_done":
            lines.append("- 阶段③LLM判定已完成，等待汇总/评分")

    # 活性与异常
    newest = min([x for x in (run_age, llm_age) if x is not None], default=None)
    if newest is not None and newest > STALL_MIN and RANKING.exists() is False:
        lines.append(f"⚠️ 近 {newest:.0f} 分钟无任何新日志/LLM调用 —— 可能卡在长重试，下轮仍无进展需人工介入")
    if health:
        lines.append(f"- LLM 健康（近1h）：成功 {health['ok_1h']} / 失败 {health['fail_1h']}"
                     f"（tag {health['tag_1h']} + judge {health['judge_1h']}），"
                     f"当前主用模型 {health['last_model']}")
    try:
        n_snap = len(list(SNAPS.glob("*.md")))
    except OSError:
        n_snap = 0
    n_verdicts = len(list(VERDICTS.glob("[0-9]*.json"))) if VERDICTS.exists() else 0
    lines.append(f"- 落盘：全文快照 {n_snap} | verdicts {n_verdicts} 人 | "
                 f"主日志告警行 {info['errors']}")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
