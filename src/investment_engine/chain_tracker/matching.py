"""信息 → 产业链匹配（T11）。

匹配源是 knowledge/industry-chains/<chain_id>/chain.yaml（schema 校验过的知识库正本，
也是 T13 状态回写的目标），不是 config/stock_monitor/chain_registry.yaml。

三级匹配规则：
1. 标的匹配：公告/研报的股票代码命中 mappings.code，或股票名称出现在标题
2. 拉丁关键词：从 metric/materials/driver/链名 提取的拉丁 token（FR8/WF6/CCL/Rubin…），
   大小写不敏感子串匹配标题
3. 中文碎片：仅从 tracking_metrics.metric 和 segments.materials 提取的具体名词
  （铜箔/玻璃布/覆铜板…），经停用词过滤，避免"价格/产能"这类泛化词灌爆匹配

设计取向：宁可多匹配（LLM 会判 irrelevant），不可漏匹配（漏掉就是信号丢失）。
"""
from __future__ import annotations

import re

# 从指标名拆出的中文碎片若过于泛化则不作关键词（否则公告洪水会灌爆 LLM 预算）
_STOP_FRAGMENTS = {
    "价格", "供给", "需求", "产能", "产量", "进度", "进展", "利用率", "认证",
    "出货", "出货量", "政策", "交易", "量产", "首飞", "装机", "装机量", "订单",
    "排期", "执行", "落地", "现状", "缺口", "部署", "轮次", "价值量", "渗透率",
    "份额", "产业链", "应用", "制造", "运营",
    # 下游应用领域的泛化行业名词（实测 2026-08-28 数据 flooding 来源：
    # "工业"命中"天润工业/代工业务"、"电力"命中"龙源电力"、"通信"命中"信维通信"）
    "工业", "电力", "通信", "新能源", "建筑", "军工", "钢铁", "手机",
    "医院", "药店", "汽车电子", "服务",
}

# 泛化拉丁 token（实测 "AI" 命中半数研报标题）
_LATIN_STOP = {"AI"}

_LATIN_RE = re.compile(r"[A-Za-z][A-Za-z0-9.\-]*")
_PAREN_RE = re.compile(r"[(（]([^)）]*)[)）]")
_SPLIT_RE = re.compile(r"[/、,，\s→]+")
_HAN_RE = re.compile(r"[一-鿿]")


def _latin_tokens(text: str) -> set[str]:
    return {t.upper() for t in _LATIN_RE.findall(text or "")
            if len(t) >= 2 and t.upper() not in _LATIN_STOP}


def _paren_contents(text: str) -> set[str]:
    out: set[str] = set()
    for c in _PAREN_RE.findall(text or ""):
        for frag in _SPLIT_RE.split(c):
            frag = frag.strip()
            if len(frag) >= 2:
                out.add(frag.upper() if not _HAN_RE.search(frag) else frag)
    return out


def _chinese_fragments(text: str) -> set[str]:
    """去掉拉丁 token 与括号内容后按分隔符切，保留 2-8 字非停用词中文名词。"""
    t = _LATIN_RE.sub("/", _PAREN_RE.sub("/", text or ""))
    out: set[str] = set()
    for frag in _SPLIT_RE.split(t):
        frag = frag.strip()
        if 2 <= len(frag) <= 8 and _HAN_RE.search(frag) and frag not in _STOP_FRAGMENTS:
            out.add(frag)
    return out


def extract_chain_signals(chain: dict) -> dict:
    """从 chain.yaml dict 提取匹配信号：codes / names / keywords。"""
    codes: set[str] = set()
    names: set[str] = set()
    for m in chain.get("mappings") or []:
        code = str(m.get("code") or "").strip()
        if code:
            codes.add(code)
        name = str(m.get("name") or "").strip()
        if name:
            names.add(name)

    keywords: set[str] = set()
    # 拉丁 token + 括号内容：指标、环节材料、链名、驱动因素
    latin_sources = [chain.get("name") or "", chain.get("driver") or ""]
    for tm in chain.get("tracking_metrics") or []:
        latin_sources.append(str(tm.get("metric") or ""))
    for seg in chain.get("segments") or []:
        for mat in seg.get("materials") or []:
            latin_sources.append(str(mat))
    for text in latin_sources:
        keywords |= _latin_tokens(text)
        keywords |= _paren_contents(text)

    # 中文碎片只从指标名与材料名提取（具体名词），driver/thesis 的散文不拆
    for tm in chain.get("tracking_metrics") or []:
        keywords |= _chinese_fragments(str(tm.get("metric") or ""))
    for seg in chain.get("segments") or []:
        for mat in seg.get("materials") or []:
            keywords |= _chinese_fragments(str(mat))
        # 材料括号里的公司名/代号也收（如 覆铜板(建滔/生益/南亚)）
        for mat in seg.get("materials") or []:
            keywords |= _paren_contents(str(mat))

    keywords = {k for k in keywords if k and k not in _STOP_FRAGMENTS}
    return {"codes": codes, "names": names, "keywords": keywords}


def build_chain_index(chains: list[dict]) -> dict[str, dict]:
    return {c["chain_id"]: extract_chain_signals(c) for c in chains}


def _match_one(item: dict, index: dict[str, dict]) -> list[str]:
    # 期货等信息自带预分配链
    preassigned = [cid for cid in (item.get("chain_ids") or []) if cid in index]
    if preassigned:
        return preassigned

    title = item.get("title") or ""
    title_upper = title.upper()
    stock_code = item.get("stock_code") or ""
    stock_name = item.get("stock_name") or ""
    # 公告天然是公司级事件：只按标的代码/名称匹配。
    # 公告标题做关键词匹配全是噪音（实测 "工业"→天润工业、"电力"→龙源电力）。
    notice_only = item.get("source") == "notice"

    matched: list[str] = []
    for chain_id, sig in index.items():
        if stock_code and stock_code in sig["codes"]:
            matched.append(chain_id)
            continue
        if stock_name and stock_name in sig["names"]:
            matched.append(chain_id)
            continue
        if notice_only:
            continue
        if any(n in title for n in sig["names"]):
            matched.append(chain_id)
            continue
        if any(k in title_upper for k in sig["keywords"]):
            matched.append(chain_id)
    return matched


def match_items(items: list[dict], index: dict[str, dict]) -> list[tuple[dict, str]]:
    """返回 (item, chain_id) 配对列表；同 item 同 chain 只出现一次。"""
    pairs: list[tuple[dict, str]] = []
    for item in items:
        for chain_id in _match_one(item, index):
            pairs.append((item, chain_id))
    return pairs
