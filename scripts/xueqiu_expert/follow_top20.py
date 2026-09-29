"""雪球 TOP20 大牛批量关注 + 分组（2026-09-29 运维脚本）。

接口签名（逆向自 vue-web bundle，2026-09-29 实测）：
- 写接口需先 GET /session/token.json?api_path=<path> 拿 session_token，随 POST 一起提交
- 关注：POST /friendships/create/{uid}.json
- 分组：POST /friendships/groups/members/update.json  data={uid, gid}（gid=该用户分组全集，逗号拼接）
- 建组：POST /friendships/groups/create.json data={name}（同样要 session_token）

用法：.venv/bin/python scripts/xueqiu_expert/follow_top20.py [--group 大牛TOP20]
"""
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
RANKING = REPO / "data" / "xueqiu" / "expert_ranking.json"


def main():
    group_name = "大牛TOP20"
    if "--group" in sys.argv:
        group_name = sys.argv[sys.argv.index("--group") + 1]

    top = json.loads(RANKING.read_text())["top20"]
    uids = [(str(r["uid"]), r["screen_name"]) for r in top]
    print(f"TOP{len(uids)}，目标分组「{group_name}」")

    from playwright.sync_api import sync_playwright
    cookies = json.loads((Path.home() / "xq_cookies.json").read_text())
    pw_cookies = [{"name": c["name"], "value": c["value"],
                   "domain": c.get("domain", ".xueqiu.com"),
                   "path": c.get("path", "/")}
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
        ctx.add_cookies(pw_cookies)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto("https://xueqiu.com/center/#/friends",
                  wait_until="domcontentloaded", timeout=60000)
        time.sleep(8)  # WAF challenge + SPA 初始化

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

        # 1) 建/找分组
        groups = json.loads(api_get("/friendships/groups.json"))
        gid = next((g["id"] for g in groups if g["name"] == group_name), None)
        if gid is None:
            r = api_post("/friendships/groups/create.json", {"name": group_name})
            print(f"创建分组: {r['status']} {r['text'][:150]}")
            groups = json.loads(api_get("/friendships/groups.json"))
            gid = next((g["id"] for g in groups if g["name"] == group_name), None)
        print(f"分组 gid={gid}")
        if gid is None:
            print("❌ 分组创建失败，中止"); return

        # 2) 已关注名单（避免重复关注）
        followed = set()
        for pg in range(1, 7):
            data = json.loads(api_get(
                f"/friendships/groups/members.json?uid=6418654314&page={pg}&gid=0"))
            users = data.get("users", [])
            if not users:
                break
            followed.update(str(u.get("id")) for u in users)
            if len(users) < 20:
                break
            time.sleep(1)
        print(f"已关注 {len(followed)} 人")

        # 3) 逐个：关注（若未关注）→ 入组
        ok_f = ok_g = 0
        for i, (uid, name) in enumerate(uids, 1):
            fmsg = "已关注"
            if uid not in followed:
                rf = api_post(f"/friendships/create/{uid}.json")
                if rf["status"] == 200:
                    ok_f += 1; fmsg = "关注✓"
                else:
                    fmsg = f"关注✗{rf['status']}:{rf['text'][:80]}"
                time.sleep(2.5)  # 写操作限速防验证码
            else:
                ok_f += 1
            rg = api_post("/friendships/groups/members/update.json",
                          {"uid": uid, "gid": str(gid)})
            gmsg = "入组✓" if rg["status"] == 200 else f"入组✗{rg['status']}:{rg['text'][:80]}"
            if rg["status"] == 200:
                ok_g += 1
            print(f"[{i}/{len(uids)}] {name}({uid}) {fmsg} {gmsg}")
            time.sleep(1.5)

        # 4) 验证
        time.sleep(2)
        groups = json.loads(api_get("/friendships/groups.json"))
        for g in groups:
            if g["name"] in (group_name, "全部", "未分组"):
                print(f"  「{g['name']}」成员 {g['member_count']}")
        print(f"完成：关注 {ok_f}/{len(uids)}，入组 {ok_g}/{len(uids)}")


if __name__ == "__main__":
    main()
