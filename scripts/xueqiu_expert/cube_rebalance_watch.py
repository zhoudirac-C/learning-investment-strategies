#!/usr/bin/env python3
"""雪球大牛 TOP20 C类（组合主理人）调仓监控（增量 → 飞书）。

背景：C 类专家一般不发帖，timeline 监控对他们系统性失灵；他们的信号在组合调仓上。
口径（2026-10-11 用户拍板方向）：
- 监控对象 = ① 文本轨 TOP20 中 source==C 的 9 人 + ② 组合轨 cube_expert_ranking.json
  中有命中分（hit_events>0）且不在 ① 中的成员（2026-10-11 拍板方案④，合计 14 人）。
  理由：文本 9 人是主跟对象；组合轨有命中者是被验证过"提前布局能力"的增量，两边互补。
- 端点 = /cubes/rebalancing/current.json（返回 last_rb 含完整 holdings 快照）。
- 触发 = last_rb.id 相对 state 变化；state 同时存 holdings 快照用于 diff。
- 首次运行/新 cube 静默建基线（防空刷）；之后 rb_id 变化才输出。
- 权重噪声：快照间隔内的价格漂移会造成权重微动，报告阈值 |Δ|>=1.0pp；
  新进/清仓标的始终报告。rb_id 未变时静默刷新快照（保持 diff 基线新鲜）。
限流：SLEEP=5s；110017 走 60/120/180s 退避 + 双域名轮换（xueqiu-cube-tracking 口径）。
状态：data/xueqiu/cube_watch_state.json {symbol: {rb_id, holdings{symbol:weight}, updated_at}}
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DATA = REPO / "data" / "xueqiu"
RANKING = DATA / "expert_ranking.json"
CUBE_RANKING = DATA / "cube_expert_ranking.json"
CAND = DATA / "candidates.json"
STATE = DATA / "cube_watch_state.json"
TOP_N = 20
SLEEP = 5.0
REPORT_THRESHOLD_PP = 1.0  # 权重变化报告阈值（百分点），过滤价格漂移噪声
MAX_CHANGE_LINES = 12  # 单次调仓最多展开的股票行数


def log_err(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def cookie_header() -> str:
    cookies = json.loads((Path.home() / "xq_cookies.json").read_text(encoding="utf-8"))
    return "; ".join(f"{c['name']}={c['value']}" for c in cookies if "xueqiu" in (c.get("domain") or ""))


def load_c_members() -> list[dict]:
    """监控名单 = ① 文本轨 TOP20 source==C + ② 组合轨有命中分的增量（方案④）。

    ② 的 cube_symbol 直接来自 cube_expert_ranking.json；① 的按 uid 匹配
    （兜底 candidates.json）。
    """
    top = json.loads(RANKING.read_text(encoding="utf-8")).get("top20", [])[:TOP_N]
    c_members = [t for t in top if t.get("source") == "C"]
    sym_by_uid: dict[str, str] = {}
    cube_rows: list[dict] = []
    if CUBE_RANKING.exists():
        cube_rows = json.loads(CUBE_RANKING.read_text(encoding="utf-8")).get("top", [])
        for r in cube_rows:
            if r.get("cube_symbol"):
                sym_by_uid[str(r["uid"])] = r["cube_symbol"]
    if CAND.exists():
        for c in json.loads(CAND.read_text(encoding="utf-8")).get("with_uid", []):
            uid = str(c.get("uid"))
            if uid not in sym_by_uid and c.get("cube_symbol"):
                sym_by_uid[uid] = c["cube_symbol"]
    out = []
    seen: set[str] = set()
    for m in c_members:
        uid = str(m["uid"])
        seen.add(uid)
        out.append({"uid": uid, "screen_name": m.get("screen_name") or uid,
                    "rank": m.get("rank"), "group": "文本TOP20-C",
                    "cube_symbol": sym_by_uid.get(uid)})
    # ② 组合轨有命中分的增量（cube 回测证明有提前布局能力的人）
    for r in cube_rows:
        uid = str(r.get("uid"))
        if uid in seen or "error" in r or not r.get("cube_symbol"):
            continue
        if (r.get("hit_events") or 0) <= 0:
            continue
        seen.add(uid)
        out.append({"uid": uid, "screen_name": r.get("screen_name") or uid,
                    "rank": r.get("rank"), "group": "组合轨命中",
                    "cube_symbol": r["cube_symbol"]})
    return out


class RateLimited(RuntimeError):
    pass


def fetch_current(cube_symbol: str) -> dict:
    """GET /cubes/rebalancing/current.json，110017 退避 + 双域名轮换。"""
    hosts = ["www.xueqiu.com", "xueqiu.com"]
    backoffs = [0, 60, 120, 180]
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36",
        "Referer": "https://www.xueqiu.com/",
        "Cookie": cookie_header(),
    }
    for attempt in range(1, 5):
        host = hosts[(attempt - 1) % len(hosts)]
        url = f"https://{host}/cubes/rebalancing/current.json?cube_symbol={cube_symbol}"
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:  # noqa: BLE001
            body = e.read().decode("utf-8", errors="replace")[:300]
            if e.code == 400 and "110017" in body:
                if attempt < 4:
                    log_err(f"{cube_symbol} 限流 110017（{host}），{backoffs[attempt]}s 后重试")
                    time.sleep(backoffs[attempt])
                    continue
                raise RateLimited(f"{cube_symbol} 持续限流 110017")
            raise RuntimeError(f"HTTP {e.code} {body[:120]}")
    raise RuntimeError("unreachable")


def load_state() -> dict:
    if STATE.exists():
        try:
            return json.loads(STATE.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return {}
    return {}


def holdings_map(last_rb: dict) -> dict[str, float]:
    out = {}
    for h in last_rb.get("holdings") or []:
        sym = h.get("stock_symbol")
        w = h.get("weight")
        if sym and w is not None:
            out[sym] = round(float(w), 2)
    return out


def holdings_names(last_rb: dict) -> dict[str, str]:
    return {h.get("stock_symbol"): h.get("stock_name", "")
            for h in last_rb.get("holdings") or [] if h.get("stock_symbol")}


def fmt_ts(ms) -> str:
    try:
        return datetime.fromtimestamp(int(ms) / 1000).strftime("%m-%d %H:%M")
    except Exception:  # noqa: BLE001
        return "unknown"


def diff_holdings(old: dict[str, float], new: dict[str, float],
                  names: dict[str, str]) -> list[str]:
    lines = []
    for sym in sorted(new, key=lambda s: -new[s]):
        nm = names.get(sym) or sym
        if sym not in old:
            lines.append(f"  🟢 新进 {nm}({sym}) {new[sym]:.1f}%")
        elif abs(new[sym] - old[sym]) >= REPORT_THRESHOLD_PP:
            arrow = "↑" if new[sym] > old[sym] else "↓"
            lines.append(f"  {arrow} {nm}({sym}) {old[sym]:.1f}% → {new[sym]:.1f}%")
    for sym in sorted(old):
        if sym not in new:
            lines.append(f"  🔴 清仓 {sym}（原 {old[sym]:.1f}%）")
    return lines


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--init", action="store_true", help="只建基线（state 落盘），不产生推送输出")
    ap.add_argument("--dry-run", action="store_true", help="不联网，只核对监控名单与 state")
    args = ap.parse_args()

    members = load_c_members()
    state = load_state()

    if args.dry_run:
        print(f"C类监控 {len(members)} 人 / state {len(state)} 个 cube")
        for m in members:
            st = state.get(m["cube_symbol"] or "", {})
            print(f"  [{m.get('group','?')}] #{m['rank']} {m['screen_name']} {m['uid']} cube={m['cube_symbol']} "
                  f"rb_id={st.get('rb_id')} holdings={len(st.get('holdings') or {})}")
        return

    blocks: list[str] = []
    errors: list[str] = []
    for m in members:
        sym = m.get("cube_symbol")
        name = m["screen_name"]
        if not sym:
            errors.append(f"⚠️ {name}({m['uid']}) 无 cube_symbol，跳过")
            continue
        try:
            data = fetch_current(sym)
        except RateLimited as e:
            errors.append(f"⚠️ {name} {sym} {e}")
            continue
        except Exception as e:  # noqa: BLE001
            errors.append(f"⚠️ {name} {sym} 抓取失败: {str(e)[:120]}")
            continue
        time.sleep(SLEEP)

        last_rb = data.get("last_rb") or {}
        rb_id = last_rb.get("id")
        if not rb_id:
            continue
        new_holdings = holdings_map(last_rb)
        prev = state.get(sym) or {}
        prev_rb_id = prev.get("rb_id")
        prev_holdings = prev.get("holdings") or {}

        if prev_rb_id is None:
            # 首次见该 cube：静默建基线
            state[sym] = {"rb_id": rb_id, "holdings": new_holdings,
                          "updated_at": last_rb.get("updated_at")}
            continue

        if rb_id == prev_rb_id:
            # 无新调仓：静默刷新快照，保持 diff 基线新鲜
            state[sym] = {"rb_id": rb_id, "holdings": new_holdings,
                          "updated_at": last_rb.get("updated_at")}
            continue

        # 新调仓
        names = holdings_names(last_rb)
        changes = diff_holdings(prev_holdings, new_holdings, names)
        status = last_rb.get("status") or "?"
        status_zh = {"success": "已成交", "pending": "挂单未成交"}.get(status, status)
        head = (f"📊 {name} 的 {sym} 调仓（{fmt_ts(last_rb.get('updated_at'))}，{status_zh}）"
                f" <https://xueqiu.com/P/{sym}>")
        if changes:
            shown = changes[:MAX_CHANGE_LINES]
            more = len(changes) - len(shown)
            block = "\n".join([head] + shown + ([f"  …另有 {more} 只变动省略"] if more else []))
        else:
            block = head + "\n  （权重微调，无 |Δ|≥1pp 的个股变动）"
        blocks.append(block)
        state[sym] = {"rb_id": rb_id, "holdings": new_holdings,
                      "updated_at": last_rb.get("updated_at")}

    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")

    if args.init:
        log_err(f"基线已建立：{len(state)} 个 cube")
        return
    if not blocks and not errors:
        return
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    out = [f"雪球TOP20-C类 组合调仓监控（{now}）"]
    out.extend(errors)
    out.extend(blocks)
    print("\n".join(out), flush=True)


if __name__ == "__main__":
    main()
