"""东财板块（行业概念）成员与实时涨跌幅——880 板块指数的替代通道。

背景（2026-09-23）：
`sector_intraday.py` 原用 TDX 880 板块指数 60min K线（`CapMainKline`），
而该能力已被 TDX 服务端**按接口粒度封禁**（实测「尝试 5 台服务器均返回空结果」），
TDX 其余能力（CapSector880 板块成分文件等）存活但**不含 880 指数K线**。

替代思路：东财 clist 支持按板块过滤成分股（`fs=b:BKxxxx`），
用成分股实时涨跌幅聚合出板块强度——与既有 tdx-sector 聚合同一口径思路。

已验证（2026-09-23）：
    银行 BK0475 → total=42；半导体 BK1036 → total=187（含 f2 价/f3 涨跌幅）
成分股列表来自东财板块清单（`fs=m:90+t:2` 行业 / `t:3` 概念），
名称与 TDX 880 分类**不完全一一对应**（东财分一/二/三级），
故本模块提供「按名称搜索 BK 代码」而非硬编码映射。

经验内嵌：
- 东财 clist 大响应（pz>300）会超时 → **pz≤100**
- 东财间歇封禁 / http=000 → **指数退避重试 ≥6 次**（本次实测 2-4 次才成功）
"""
from __future__ import annotations

import time

from qing_investment.marketdata import ratelimit

SOURCE = "eastmoney_board"

_HEADERS = {"Referer": "https://quote.eastmoney.com/"}

#: 进程内熔断标志（见 _fetch_json docstring）。每次进程启动重置。
_EM_BOARD_DEAD = False

#: 行业/概念板块清单接口
_BOARD_LIST = ("http://push2.eastmoney.com/api/qt/clist/get"
               "?pn={pn}&pz=100&po=1&np=1&fltt=2&invt=2"
               "&fs=m:90+t:{t}&fields=f12,f14,f3&fid=f3")

#: 板块成分股接口（fs=b:BKxxxx）
_BOARD_MEMBERS = ("http://push2.eastmoney.com/api/qt/clist/get"
                  "?pn=1&pz=100&po=1&np=1&fltt=2&invt=2"
                  "&fs=b:{bk}&fields=f2,f3,f12,f14&fid=f3")


def _fetch_json(url: str, *, timeout: int = 15, retries: int = 4) -> dict | None:
    """带指数退避重试的东财 JSON 拉取（东财间歇 http=000 必需）。

    **进程内熔断**：确认失败后本进程直接短路后续请求——sector_intraday 要逐板块
    拉 11 个板块 × 每个 8 次重试，东财封禁时累计耗时可达 10+ 分钟，必然撞 cron
    超时（对齐 skill `qing-stock-monitor-ops` §0.1 的失败路径熔断模式）。
    """
    global _EM_BOARD_DEAD
    if _EM_BOARD_DEAD:
        return None

    from qing_investment.marketdata.http import http_get_json

    for i in range(retries):
        ratelimit.acquire("eastmoney")
        try:
            return http_get_json(url, headers=_HEADERS, timeout=timeout)
        except Exception:  # noqa: BLE001 — 网络/JSON 错误统一重试
            time.sleep(0.9 * (i + 1))
    # 全部重试失败 → 本进程内熔断（后续调用直接 return None，不再逐次重试）
    _EM_BOARD_DEAD = True
    return None


def board_list(kind: str = "industry") -> list[dict]:
    """板块清单。kind: 'industry'(m:90 t:2) / 'concept'(m:90 t:3)。

    返回 ``[{"code": "BK0475", "name": "银行", "change_pct": 0.59}, ...]``。
    """
    t = 2 if kind == "industry" else 3
    rows: list[dict] = []
    for pn in range(1, 12):
        data = _fetch_json(_BOARD_LIST.format(pn=pn, t=t))
        page = ((data or {}).get("data") or {}).get("diff") or []
        if not page:
            break
        for r in page:
            rows.append({"code": r.get("f12"), "name": r.get("f14"),
                         "change_pct": r.get("f3")})
        if len(page) < 100:
            break
        time.sleep(0.15)
    return rows


def find_board(name: str, *, kind: str = "industry") -> str | None:
    """按名称找板块代码 BKxxxx（精确优先，其次包含匹配）。找不到返回 None。"""
    boards = board_list(kind)
    for b in boards:
        if b.get("name") == name:
            return b.get("code")
    for b in boards:
        if name and name in str(b.get("name") or ""):
            return b.get("code")
    return None


def board_members(bk: str) -> list[dict]:
    """板块成分股实时快照：``[{code,name,price,change_pct}]``（一次 ≤100 只）。"""
    data = _fetch_json(_BOARD_MEMBERS.format(bk=bk))
    rows = ((data or {}).get("data") or {}).get("diff") or []
    out = []
    for r in rows:
        out.append({"code": r.get("f12"), "name": r.get("f14"),
                    "price": r.get("f2"), "change_pct": r.get("f3")})
    return out


def board_strength(bk: str) -> dict | None:
    """板块强度：成分股涨跌幅均值 + 样本数（等价 tdx 板块聚合口径）。

    返回 ``{code, n, avg_pct, up, down}``；无成分或拉取失败返回 None。
    """
    members = board_members(bk)
    pcts = [m["change_pct"] for m in members
            if isinstance(m.get("change_pct"), (int, float))]
    if not pcts:
        return None
    return {"code": bk, "n": len(pcts),
            "avg_pct": round(sum(pcts) / len(pcts), 3),
            "up": sum(1 for p in pcts if p > 0),
            "down": sum(1 for p in pcts if p < 0),
            "source": SOURCE}


#: 板块指数 K线（push2his，与个股同接口，secid=90.BKxxxx）
_BOARD_KLINE = ("https://push2his.eastmoney.com/api/qt/stock/kline/get"
                "?secid=90.{bk}&fields1=f1,f2,f3,f4,f5,f6"
                "&fields2=f51,f52,f53,f54,f55,f56,f57"
                "&klt={klt}&fqt=1&end=20500101&lmt={lmt}")


def board_kline(bk: str, klt: int = 60, count: int = 16) -> list[dict]:
    """板块指数 K线（东财 90.BKxxxx）。

    **880 板块 K线的替代通道**：TDX `CapMainKline` 已被封禁，无法再拉 880 指数
    K线；东财板块指数与 880 同为通达信/东财分类下的行业指数，分钟级形态可用于
    「拉升发生在哪个时段」的定性（与 sector_intraday 的用途一致）。

    返回统一 bar shape（bar_time/open/close/high/low/volume/amount），升序。
    东财间歇封禁 → 内部重试；全败返回 []。
    """
    url = _BOARD_KLINE.format(bk=bk, klt=klt, lmt=count + 3)
    data = _fetch_json(url)
    rows = ((data or {}).get("data") or {}).get("klines") or []
    bars = []
    for row in rows:
        parts = str(row).split(",")
        if len(parts) < 6:
            continue
        try:
            bars.append({
                "bar_time": parts[0],
                # 东财字段序：开,收,高,低
                "open": float(parts[1]), "close": float(parts[2]),
                "high": float(parts[3]), "low": float(parts[4]),
                "volume": float(parts[5]),
                "amount": float(parts[6]) if len(parts) > 6 and parts[6] else 0.0,
                "source": SOURCE,
            })
        except (ValueError, IndexError):
            continue
    bars.sort(key=lambda k: k["bar_time"])
    return bars[-count:] if len(bars) > count else bars


def board_kline_by_name(name: str, klt: int = 60, count: int = 16,
                        *, kind: str = "industry") -> list[dict]:
    """按板块名拉 K线（内部先查 BK 代码）。找不到返回 []。"""
    bk = find_board(name, kind=kind)
    if not bk:
        return []
    return board_kline(bk, klt=klt, count=count)
