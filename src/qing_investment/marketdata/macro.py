"""宏观层：人民银行社融 / 国家统计局 PMI（月频，勿当日频信号用）。

移植自 a-stock-data v3.8.0 Layer 11。发布日固定（社融次月中旬、PMI 月末），
未发布月份不会出现在返回里。社融仅支持 2021 年起（2020 及更早为旧版式，
传入会抛错而非返回可疑数据）。

fail-fast 纪律：三级跳链路（索引→年份页→专题页→附件）任何一级结构变更
都抛错；PMI 三个主指标解析不到必须抛错——统计局改一次措辞就静默返回
一串 None，调用方会当成"本月没数据"。
"""

from __future__ import annotations

import io
import re

from qing_investment.marketdata.errors import SourceUnavailable

_UA = {"User-Agent": "Mozilla/5.0"}
PBC_BASE = "https://www.pbc.gov.cn"
PBC_INDEX = f"{PBC_BASE}/diaochatongjisi/116219/116319/index.html"
NBS_INDEX = "https://www.stats.gov.cn/sj/zxfb/"


def _macro_get(url: str, timeout: int = 30) -> str:
    import requests
    r = requests.get(url, headers=_UA, timeout=timeout)
    r.raise_for_status()
    r.encoding = r.apparent_encoding or "utf-8"
    return r.text


def pboc_social_financing(year: int | None = None) -> list[dict]:
    """人民银行「社会融资规模增量统计表」— 月度，单位亿元。

    返回 ``[{month: "2026-01", afre_total, rmb_loans, ..., loans_written_off}]``，
    仅含已发布月份（未发布整行为空 → 丢弃，不编造）。
    year=None 取最新年；仅支持 2021+。
    """
    import pandas as pd
    idx = _macro_get(PBC_INDEX)
    years = re.findall(r"""href=["']([^"']+)[\"'][^>]*>\s*(\d{4})年统计数据\s*</a>""", idx)
    if not years:
        raise SourceUnavailable("人民银行索引页未找到「XXXX年统计数据」链接，结构可能已变更")
    table = {int(y): href for href, y in years}
    target = max(table) if year is None else year
    if target not in table:
        raise ValueError(f"人民银行无 {target} 年数据（本端点仅支持 2021 起），可选: {sorted(table, reverse=True)[:8]}")

    ypage = _macro_get(PBC_BASE + table[target] if not table[target].startswith("http") else table[target])
    topics = re.findall(r"""href=["']([^"']+)[\"'][^>]*>\s*(社会融资规模)\s*</a>""", ypage)
    if not topics:
        raise SourceUnavailable(f"{target} 年页未找到「社会融资规模」专题链接")
    tpage = _macro_get(PBC_BASE + topics[0][0] if not topics[0][0].startswith("http") else topics[0][0])
    books = re.findall(r"""href=["']([^"']+\.xlsx?)[\"']""", tpage)
    if not books:
        raise SourceUnavailable(f"{target} 年社融专题页未找到 xls/xlsx 附件")

    import requests
    content = requests.get(
        books[0] if books[0].startswith("http") else PBC_BASE + books[0],
        headers=_UA, timeout=60,
    ).content
    raw = pd.read_excel(io.BytesIO(content), header=None)

    start = None
    for i in range(len(raw)):
        if str(raw.iloc[i, 0]).strip() == "月份":
            start = i
            break
    if start is None:
        raise SourceUnavailable(
            f"{target} 年社融表没有独立「月份」表头（2020 及更早为旧版式，仅支持 2021+）"
        )

    cols = ["month", "afre_total", "rmb_loans", "fx_loans", "entrusted_loans",
            "trust_loans", "undiscounted_bankers_acceptance", "corporate_bonds",
            "government_bonds", "equity_financing", "abs_by_depository",
            "loans_written_off"]
    df = raw.iloc[start + 3:].copy().iloc[:, :len(cols)]
    df.columns = cols
    df = df[df["month"].astype(str).str.match(r"^\d{4}\.\d{1,2}$", na=False)].copy()
    for c in cols[1:]:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    def _month_label(v):
        # Excel 把 `2026.10` 吃成浮点 `2026.1`，与 1 月 `2026.01` 撞车；
        # 1 月恒写两位 → 单个小数位必是被吃尾零的 x0 月
        m = re.match(r"^(\d{4})\.(\d{1,2})$", str(v).strip())
        if not m:
            return None
        mon = m.group(2)
        if len(mon) == 1:
            mon += "0"
        return f"{m.group(1)}-{int(mon):02d}"

    df["month"] = [_month_label(v) for v in df["month"]]
    df = df[df["month"].notna()]
    df = df[df["month"].str.startswith(f"{target}-")].reset_index(drop=True)
    df = df.dropna(subset=["afre_total"]).reset_index(drop=True)
    if df.empty:
        raise SourceUnavailable(f"社融表解析后无有效月份（{target} 年），格式可能已变更")
    return df.to_dict("records")


def nbs_pmi() -> dict:
    """国家统计局最新 PMI：制造业/非制造业/综合 + 大中小型企业分档。

    > 50 扩张、< 50 收缩；连续两月同向才算趋势。
    """
    idx = _macro_get(NBS_INDEX)
    links = re.findall(r'<a[^>]+href="([^"]+)"[^>]*>\s*([^<]{6,80}?)\s*</a>', idx)
    hit = next(((u, t) for u, t in links if "采购经理指数" in t), None)
    if not hit:
        raise SourceUnavailable("统计局最新发布页未找到「采购经理指数」条目")
    href, title = hit
    url = href if href.startswith("http") else NBS_INDEX + href.lstrip("./")

    html = _macro_get(url)
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html, flags=re.S)
    text = re.sub(r"<[^>]+>", "", text)
    # 🔴 正文全角括号内带空格（`（ PMI ）为 49.2%`），必须整个删空白
    text = re.sub(r"[\s\u3000\xa0]+", "", text)

    def grab(pat):
        m = re.search(pat, text)
        return float(m.group(1)) if m else None

    ym = re.search(r"(\d{4})年(\d{1,2})月", title)
    large = medium = small = None
    combined = re.search(r"大、中、小型企业PMI分别为([\d.]+)%、([\d.]+)%和([\d.]+)%", text)
    if combined:
        large, medium, small = (float(x) for x in combined.groups())
    else:
        m_ms = re.search(r"中、小型企业PMI分别为([\d.]+)%和([\d.]+)%", text)
        if m_ms:
            medium, small = (float(x) for x in m_ms.groups())
        for name, pat in (("large", r"大型企业PMI为([\d.]+)%"),
                          ("medium", r"中型企业PMI为([\d.]+)%"),
                          ("small", r"小型企业PMI为([\d.]+)%")):
            m = re.search(pat, text)
            if m:
                v = float(m.group(1))
                if name == "large":
                    large = v
                elif name == "medium" and medium is None:
                    medium = v
                elif name == "small" and small is None:
                    small = v

    result = {
        "title": title.strip(),
        "period": f"{ym.group(1)}-{int(ym.group(2)):02d}" if ym else None,
        "manufacturing_pmi": grab(r"(?<!非)制造业采购经理指数（PMI）为([\d.]+)%"),
        "non_manufacturing_pmi": grab(r"非制造业商务活动指数为([\d.]+)%"),
        "composite_pmi": grab(r"综合PMI产出指数为([\d.]+)%"),
        "pmi_large": large, "pmi_medium": medium, "pmi_small": small,
        "source_url": url,
    }
    absent = [k for k in ("manufacturing_pmi", "non_manufacturing_pmi", "composite_pmi")
              if result[k] is None]
    if absent:
        raise SourceUnavailable(f"PMI 正文措辞可能已变更，无法解析 {absent}；页面：{url}")
    return result
