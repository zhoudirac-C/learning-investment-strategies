#!/usr/bin/env python3
"""构建 A 股公司名词典（Gate 5 L4 词典验证用）。

数据源优先级：
  1. akshare `stock_info_a_code_name`（全量 A 股代码+简称，一次拉全）
  2. 东方财富 clist API 分页（akshare 不可用时的兜底）

输出：data/company_names.json — 公司简称集合。

用法:
    python scripts/build_company_dict.py            # 全量拉取
    python scripts/build_company_dict.py --check    # 只看现有词典状态
"""

import argparse
import json
import time
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT = REPO_ROOT / "data" / "company_names.json"


def fetch_via_akshare() -> set[str]:
    """akshare 全量 A 股简称（首选）。"""
    try:
        import akshare as ak
    except ImportError:
        print("  akshare 不可用，跳过")
        return set()

    try:
        df = ak.stock_info_a_code_name()
        names = {str(n).strip() for n in df["name"].tolist() if str(n).strip()}
        print(f"  akshare: {len(names)} 个")
        return names
    except Exception as e:
        print(f"  akshare 失败: {e}")
        return set()


def fetch_via_eastmoney() -> set[str]:
    """东财 clist API 分页（兜底）。"""
    api = (
        "https://push2.eastmoney.com/api/qt/clist/get"
        "?pn={pn}&pz=100&po=1&np=1&fltt=2&invt=2"
        "&fid=f12&fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048"
        "&fields=f12,f14"
    )
    names: set[str] = set()
    pn = 1
    while pn <= 80:
        try:
            req = urllib.request.Request(
                api.format(pn=pn),
                headers={
                    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
                    "Referer": "https://quote.eastmoney.com/",
                },
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            print(f"  eastmoney pn={pn} 失败: {e}")
            break

        diff = (data.get("data") or {}).get("diff") or []
        if not diff:
            break
        for item in diff:
            n = (item.get("f14") or "").strip()
            if n:
                names.add(n)
        if pn % 10 == 0:
            print(f"  eastmoney pn={pn}: 累计 {len(names)}")
        if len(diff) < 100:
            break
        pn += 1
        time.sleep(0.2)

    print(f"  eastmoney: {len(names)} 个")
    return names


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只检查现有词典")
    args = ap.parse_args()

    if args.check:
        if OUT.exists():
            names = set(json.load(open(OUT, encoding="utf-8")))
            print(f"词典存在: {OUT} — {len(names)} 个公司名")
            for s in ["中晶科技", "有研硅", "长源东谷", "泰豪科技", "风华高科", "红棉股份"]:
                print(f"  {s}: {'✅' if s in names else '❌'}")
        else:
            print(f"词典不存在: {OUT}")
        return

    print("拉取 A 股公司名词典...")
    names = fetch_via_akshare()
    if not names:
        print("akshare 无数据，改用东财兜底...")
        names = fetch_via_eastmoney()

    if not names:
        print("❌ 未拉到任何公司名，词典未更新")
        return

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(sorted(names), f, ensure_ascii=False, indent=1)
    print(f"✅ 词典写入 {OUT} — {len(names)} 个公司名")


if __name__ == "__main__":
    main()

