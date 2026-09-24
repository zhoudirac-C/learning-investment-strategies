#!/usr/bin/env python3
"""雪球 P3 WAF 探测 + 自启（no_agent cron 脚本，零 LLM 消耗）

模式：qing-stock-monitor-ops §3.1「探测驱动 + 静默退出」
- P3 已在跑        → 静默 exit 0
- B+C 已全部完成    → stdout 完成摘要（投递一次后不再重复：靠 completion 标记文件）
- IP 仍封禁        → 静默 exit 0（stderr 记录）
- IP 解封且未在跑  → 启动 P3（--source B,C），stdout 报告

cron：每 30 分钟一次。no_agent 语义：stdout 非空才投递，空=静默。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path("/home/ubuntu/learning-investment-strategies")
PROGRESS = REPO / "data" / "xueqiu" / "posts" / "_progress.json"
CANDIDATES = REPO / "data" / "xueqiu" / "candidates.json"
COMPLETION_MARK = REPO / "data" / "xueqiu" / "posts" / "_bc_done.mark"
LOG = REPO / "logs" / "p3_waf_probe.log"


def log_stderr(msg: str) -> None:
    line = f"[{time.strftime('%m-%d %H:%M:%S')}] {msg}"
    print(line, file=sys.stderr)
    try:
        with open(LOG, "a") as f:
            f.write(line + "\n")
    except Exception:  # noqa: BLE001
        pass


def p3_running() -> bool:
    r = subprocess.run(["pgrep", "-f", "timeline_backtest.py"],
                       capture_output=True, text=True)
    return r.returncode == 0


def bc_status() -> tuple[int, int]:
    cands = json.loads(CANDIDATES.read_text())["with_uid"]
    bc = [c for c in cands if c.get("source", "")[:1] in ("B", "C")]
    progress = json.loads(PROGRESS.read_text()) if PROGRESS.exists() else {}
    done = sum(1 for c in bc if str(c["uid"]) in progress)
    return done, len(bc)


def probe() -> bool:
    """单页探测 IP 是否解封。True=解封。"""
    cookies = json.loads(Path("/home/ubuntu/xq_cookies.json").read_text())
    pw_cookies = [{"name": c["name"], "value": c["value"],
                   "domain": c.get("domain", ".xueqiu.com"),
                   "path": c.get("path", "/")}
                  for c in cookies if "xueqiu" in (c.get("domain") or "")]
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(
            user_data_dir="/home/ubuntu/.config/chromium", headless=True,
            executable_path="/usr/bin/google-chrome-stable",
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/152.0.0.0 Safari/537.36"),
            args=["--disable-blink-features=AutomationControlled"])
        ctx.add_cookies(pw_cookies)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        # 2026-09-24：裸域被 WAF 模式拦截（与 P3 取数同维度），www 同路径正常。
        # 先访问首页预热（对齐实测成功序列），再探 www API
        page.goto("https://xueqiu.com/", timeout=30000, wait_until="domcontentloaded")
        time.sleep(2)
        page.goto("https://www.xueqiu.com/v4/statuses/user_timeline.json"
                  "?user_id=6876843497&page=1&count=20", timeout=30000)
        time.sleep(2)
        txt = page.evaluate("document.body.innerText")
        return (txt or "").strip().startswith("{")


def main() -> None:
    done, total = bc_status()
    if COMPLETION_MARK.exists():
        log_stderr(f"B+C 已完成（{done}/{total}），标记文件存在，退出")
        return
    if p3_running():
        log_stderr(f"P3 在跑（{done}/{total}），静默")
        return
    if done >= total:
        # 刚完成：输出摘要一次（并打标记，之后静默）
        COMPLETION_MARK.write_text(time.strftime("%Y-%m-%d %H:%M:%S"))
        progress = json.loads(PROGRESS.read_text())
        n_ok = sum(1 for v in progress.values() if v["status"] == "ok")
        n_partial = sum(1 for v in progress.values() if str(v["status"]).startswith("partial"))
        print(f"✅ 雪球P3 B+C 回测全部完成：{done}/{total}（ok {n_ok} / partial {n_partial}）")
        return
    try:
        ok = probe()
    except Exception as e:  # noqa: BLE001
        log_stderr(f"探测异常 {type(e).__name__}: {str(e)[:80]}")
        return
    if not ok:
        log_stderr(f"IP 仍封禁（{done}/{total}），静默")
        return
    # 解封 → 启动 P3（B+C，断点续跑）
    subprocess.Popen(
        [str(REPO / ".venv/bin/python"),
         str(REPO / "scripts/xueqiu_expert/timeline_backtest.py"),
         "--source", "B,C"],
        cwd=str(REPO),
        stdout=open(REPO / "logs" / "p3_bc_run.log", "a"),
        stderr=subprocess.STDOUT,
        start_new_session=True)
    log_stderr(f"IP 解封，P3 已启动（{done}/{total}）")
    print(f"🚀 IP 解封，雪球P3（B+C 渠道 {total} 人）已启动，当前进度 {done}/{total}")


if __name__ == "__main__":
    main()
