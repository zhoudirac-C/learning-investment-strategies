"""THS 行业板块 → 成分股映射缓存（板块情绪温度计用）。

通道（2026-10-11 实测，q.10jqka 的 ajax 接口 403 但 HTML 翻页页可通）：
- 板块名单+代码：akshare stock_board_industry_name_ths()（90 个行业）
- 成分股：https://q.10jqka.com.cn/thshy/detail/code/{code}/page/{n}/
  带 hexin-v cookie（akshare 自带 ths.js + py_mini_racer 现场计算，每请求新 v），
  解析 stockpage.10jqka.com.cn/{6位代码} 链接，总页数从页面 "1/10" 样式提取。

产出 {6位股票代码: 行业板块名} 落盘 infra/data/board_members.json，TTL 7 天。
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime, timedelta
from pathlib import Path

import py_mini_racer
import requests
from akshare.datasets import get_ths_js

ROOT = Path(__file__).resolve().parents[3]
CACHE = ROOT / "infra" / "data" / "board_members.json"
TTL_DAYS = 7
SLEEP_S = 1.2
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "Chrome/89.0.4389.90 Safari/537.36")
_JS = py_mini_racer.MiniRacer()
_JS.eval(open(get_ths_js("ths.js")).read())


def _fresh_v() -> str:
    return _JS.call("v")


def _list_boards() -> dict[str, str]:
    """返回 {板块名: 板块代码}。"""
    import akshare as ak
    df = ak.stock_board_industry_name_ths()
    return {str(r["name"]): str(r["code"]) for _, r in df.iterrows()}


def _fetch_board_cons(code: str) -> set[str]:
    """拉一个行业的全部成分股代码（翻页）。"""
    stocks: set[str] = set()
    page = 1
    while True:
        url = f"https://q.10jqka.com.cn/thshy/detail/code/{code}/page/{page}/"
        r = requests.get(url, headers={"User-Agent": UA, "Cookie": f"v={_fresh_v()}"},
                         timeout=15)
        if r.status_code != 200:
            break
        found = set(re.findall(r"stockpage\.10jqka\.com\.cn/(\d{6})", r.text))
        if not found:
            break
        new = found - stocks
        stocks |= found
        if not new:  # 翻页到头（返回重复页）
            break
        page += 1
        if page > 30:  # 保险丝
            break
        time.sleep(SLEEP_S)
    return stocks


def _fetch_map() -> dict[str, str]:
    boards = _list_boards()
    stock2board: dict[str, str] = {}
    for i, (name, code) in enumerate(boards.items(), 1):
        try:
            cons = _fetch_board_cons(code)
            for c in cons:
                stock2board.setdefault(c, name)
            print(f"[{i}/{len(boards)}] {name}: {len(cons)} 只", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"WARN 成分拉取失败 {name}: {str(e)[:60]}", flush=True)
        time.sleep(SLEEP_S)
    return stock2board


def get_stock_board_map(force: bool = False) -> dict[str, str]:
    """返回 {6位代码: 行业板块名}；缓存 7 天。"""
    if not force and CACHE.exists():
        data = json.loads(CACHE.read_text(encoding="utf-8"))
        ts = datetime.fromisoformat(data["updated_at"])
        if datetime.now() - ts < timedelta(days=TTL_DAYS):
            return data["map"]
    m = _fetch_map()
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(
        {"updated_at": datetime.now().isoformat(timespec="seconds"),
         "n_stocks": len(m), "map": m}, ensure_ascii=False), encoding="utf-8")
    return m


def get_board_stocks(board: str) -> list[str]:
    """反向：板块名 → 成分股代码列表（估值 overlay 用）。"""
    m = get_stock_board_map()
    return sorted(c for c, b in m.items() if b == board)


if __name__ == "__main__":
    mp = get_stock_board_map()
    print(f"成分映射: {len(mp)} 只股票, 缓存 {CACHE}")
