#!/usr/bin/env python3
"""C 类关注分组同步（2026-10-11）：把「大牛TOP20-C」分组成员更新为业绩轨口径。

背景：C 类定义已从文本轨 TOP20-C（9 人）切换为业绩轨 cube_perf_ranking.json
TOP20 剔除僵尸组合后的活跃名单（当前 18 人）。大牛TOP20 主组 = A/B/C 三类合集
（2026-10-11 用户明确），所以 C 成员须同时挂「大牛TOP20」+「大牛TOP20-C」。
本脚本把雪球账号的「大牛TOP20-C」分组成员与新名单对齐：
- 新名单内：未关注则关注，分组 = 该 uid 既有管理分组 ∪ {主组, C组}
- 旧 C 组成员但不在新名单：从 C 组移除（保留其在其他管理分组的成员身份）

⚠️ members/update.json 是全集覆盖语义：必须传该用户所有管理分组的 gid 合集，
   否则会把用户从其他组里挤掉（2026-10-11 业绩TOP5 首次操作踩坑，本脚本修复）。

用法：.venv/bin/python scripts/xueqiu_expert/sync_c_group.py [--dry-run]
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DATA = REPO / "data" / "xueqiu"
PERF = DATA / "cube_perf_ranking.json"
WATCH_STATE = DATA / "cube_watch_state.json"
GROUP_C = "大牛TOP20-C"
MANAGED_GROUPS = ["大牛TOP20", "大牛TOP20-A", "大牛TOP20-B", GROUP_C, "业绩TOP5"]
SELF_UID = 6418654314


def load_target_uids() -> list[tuple[str, str]]:
    """业绩轨 TOP20 剔除僵尸组合 → [(uid, name)]（保持排名顺序）。"""
    perf = json.loads(PERF.read_text(encoding="utf-8"))
    stale = set()
    if WATCH_STATE.exists():
        st = json.loads(WATCH_STATE.read_text(encoding="utf-8"))
        stale = {sym for sym, v in st.items() if v.get("stale")}
    out = []
    for r in perf.get("top", [])[:20]:
        if "error" in r or not r.get("cube_symbol") or r["cube_symbol"] in stale:
            continue
        out.append((str(r["uid"]), r.get("screen_name") or str(r["uid"])))
    return out


def main() -> None:
    dry = "--dry-run" in sys.argv
    targets = load_target_uids()
    target_uids = {u for u, _ in targets}
    print(f"目标 C 类名单 {len(targets)} 人（业绩轨 TOP20 − 僵尸）")
    for i, (u, n) in enumerate(targets, 1):
        print(f"  #{i:>2} {n}({u})")
    if dry:
        return

    from playwright.sync_api import sync_playwright
    cookies = json.loads((Path.home() / "xq_cookies.json").read_text())
    pw_cookies = [{"name": c["name"], "value": c["value"],
                   "domain": c.get("domain", ".xueqiu.com"), "path": c.get("path", "/")}
                  for c in cookies if "xueqiu" in (c.get("domain") or "")]

    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(
            user_data_dir="/home/ubuntu/.config/chromium",
            headless=True,
            executable_path="/usr/bin/google-chrome-stable",
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/152.0.0.0 Safari/537.36"),
            args=["--disable-blink-features=AutomationControlled"])
        ctx.add_cookies(pw_cookies)  # type: ignore[arg-type]  # playwright 接受该 dict 列表，Pyright 误报
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto("https://xueqiu.com/center/#/friends",
                  wait_until="domcontentloaded", timeout=60000)
        time.sleep(8)

        page.evaluate("""() => {
            window.__post = async (path, data) => {
                const t = await fetch('/provider/session/token.json?api_path=' + encodeURIComponent(path));
                const tk = (await t.json()).session_token;
                const body = new URLSearchParams({...(data || {}), session_token: tk});
                const r = await fetch(path, {method: 'POST',
                    headers: {'Content-Type': 'application/x-www-form-urlencoded'}, body});
                return {status: r.status, text: (await r.text()).slice(0, 300)};
            };
        }""")

        def api_post(path, data=None):
            return page.evaluate("([p, d]) => window.__post(p, d)", [path, data or {}])

        def api_get(path):
            return page.evaluate(
                "async (p) => { const r = await fetch(p); return await r.text(); }", path)

        # 1) 分组 gid 映射
        groups = json.loads(api_get("/friendships/groups.json"))
        gid_of = {g["name"]: g["id"] for g in groups if g["name"] in MANAGED_GROUPS}
        if GROUP_C not in gid_of:
            print(f"❌ 分组「{GROUP_C}」不存在"); return
        gid_c = gid_of[GROUP_C]
        gid_main = gid_of["大牛TOP20"]
        print(f"管理分组: {gid_of}")

        # 2) 每个管理分组的成员 → uid → 既有 gid 集合
        uid_gids: dict[str, set] = {}
        for gname, gid in gid_of.items():
            for pg in range(1, 6):
                data = json.loads(api_get(
                    f"/friendships/groups/members.json?uid={SELF_UID}&page={pg}&gid={gid}"))
                users = data.get("users", [])
                if not users:
                    break
                for u in users:
                    uid_gids.setdefault(str(u.get("id")), set()).add(gid)
                if len(users) < 20:
                    break
                time.sleep(1)
        old_c = {u for u, gs in uid_gids.items() if gid_c in gs}
        print(f"旧「{GROUP_C}」成员 {len(old_c)} 人")

        # 3) 已关注全集
        followed = set()
        for pg in range(1, 10):
            data = json.loads(api_get(
                f"/friendships/groups/members.json?uid={SELF_UID}&page={pg}&gid=0"))
            users = data.get("users", [])
            if not users:
                break
            followed.update(str(u.get("id")) for u in users)
            if len(users) < 20:
                break
            time.sleep(1)
        print(f"已关注 {len(followed)} 人")

        # 4) 新名单：关注 + 入 C 组（保留既有分组）
        ok = 0
        for i, (uid, name) in enumerate(targets, 1):
            fmsg = "已关注"
            if uid not in followed:
                rf = api_post(f"/friendships/create/{uid}.json")
                fmsg = "关注✓" if rf["status"] == 200 else f"关注✗{rf['status']}:{rf['text'][:80]}"
                time.sleep(2.5)
            gids = set(uid_gids.get(uid, set())) | {gid_c, gid_main}
            rg = api_post("/friendships/groups/members/update.json",
                          {"uid": uid, "gid": ",".join(str(g) for g in gids)})
            gmsg = "入组✓" if rg["status"] == 200 else f"入组✗{rg['status']}:{rg['text'][:80]}"
            if rg["status"] == 200:
                ok += 1
            print(f"[{i}/{len(targets)}] {name}({uid}) {fmsg} {gmsg} (gids={sorted(gids)})")
            time.sleep(1.5)

        # 5) 旧 C 组多余的：移除 C 组成员身份（保留其他组）
        removed = 0
        for uid in sorted(old_c - target_uids):
            gids = uid_gids.get(uid, set()) - {gid_c}
            rg = api_post("/friendships/groups/members/update.json",
                          {"uid": uid, "gid": ",".join(str(g) for g in gids)})
            rmsg = "移除✓" if rg["status"] == 200 else f"移除✗{rg['status']}:{rg['text'][:80]}"
            if rg["status"] == 200:
                removed += 1
            print(f"[移出] {uid} {rmsg} (剩余 gids={sorted(gids)})")
            time.sleep(1.5)

        # 6) 验证
        time.sleep(2)
        groups = json.loads(api_get("/friendships/groups.json"))
        for g in groups:
            if g["name"] in MANAGED_GROUPS or g["name"] == "全部":
                print(f"  「{g['name']}」成员 {g['member_count']}")
        print(f"完成：入组 {ok}/{len(targets)}，移出 {removed}")


if __name__ == "__main__":
    main()
