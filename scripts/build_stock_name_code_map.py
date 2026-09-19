#!/usr/bin/env python3
"""构建/读取 A 股全量 name<->code 映射缓存（data/stock_name_code_map.json）。

gate5 的词典只存了 name；回填 related_stocks 需要 name→code。
优先 akshare，失败则用东财 clist 兜底（与 build_company_dict.py 同源）。
"""
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "data" / "stock_name_code_map.json"


def via_akshare() -> dict:
    try:
        import akshare as ak
        df = ak.stock_info_a_code_name()
        m = {}
        for _, row in df.iterrows():
            code = str(row["code"]).zfill(6)
            name = str(row["name"]).strip()
            if name and code.isdigit() and len(code) == 6:
                m[name] = code
        print(f"  akshare: {len(m)} 条")
        return m
    except Exception as e:
        print(f"  akshare 失败: {e}")
        return {}


def via_eastmoney() -> dict:
    import urllib.request
    m = {}
    for fs in ("m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048",):
        for pn in range(1, 30):
            url = ("http://push2.eastmoney.com/api/qt/clist/get?"
                   f"pn={pn}&pz=200&po=1&np=1&fltt=2&invt=2&fid=f3&fs={fs}"
                   "&fields=f12,f14")
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                d = json.loads(urllib.request.urlopen(req, timeout=15).read().decode())
                items = (d.get("data") or {}).get("diff") or []
                if not items:
                    break
                for it in items:
                    code = str(it.get("f12", "")).zfill(6)
                    name = str(it.get("f14", "")).strip()
                    if name and code.isdigit() and len(code) == 6:
                        m[name] = code
            except Exception as e:
                print(f"  东财 pn={pn} 失败: {e}")
                break
    print(f"  东财: {len(m)} 条")
    return m


def main():
    if OUT.exists() and "--force" not in sys.argv:
        m = json.load(open(OUT, encoding="utf-8"))
        print(f"缓存已存在: {len(m)} 条 → {OUT}")
        return
    print("构建 name→code 映射...")
    m = via_akshare()
    if len(m) < 4000:
        print("akshare 数据不足，转东财兜底")
        m2 = via_eastmoney()
        for k, v in m2.items():
            m.setdefault(k, v)
    OUT.write_text(json.dumps(m, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    print(f"写出 {len(m)} 条 → {OUT}")


if __name__ == "__main__":
    main()
