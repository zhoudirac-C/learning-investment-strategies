#!/usr/bin/env python3
"""Step 2 enrichment: annotate stock codes, add related_stocks and tags."""
import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
IN_FILE = REPO_ROOT / "temp" / "claims" / "20260712_232117_85b7b1" / "step1_raw.json"
OUT_FILE = REPO_ROOT / "temp" / "claims" / "20260712_232117_85b7b1" / "step2_enriched.json"

# name -> (6-digit code, official name)
NAME_MAP = {
    "寒武纪": ("688256", "寒武纪"),
    "工业富联": ("601138", "工业富联"),
    "中船特气": ("688146", "中船特气"),
    "中微公司": ("688012", "中微公司"),
    "兆易创新": ("603986", "兆易创新"),
    "智微智能": ("001339", "智微智能"),
    "行云科技": ("300209", "行云科技"),
    "浪潮信息": ("000977", "浪潮信息"),
    "锐捷网络": ("301165", "锐捷网络"),
    "紫光股份": ("000938", "紫光股份"),
    "铖昌科技": ("001270", "铖昌科技"),
    "常山药业": ("300255", "常山药业"),
    "众生药业": ("002317", "众生药业"),
    "昭衍新药": ("603127", "昭衍新药"),
    "双鹭药业": ("002038", "双鹭药业"),
    "唯特偶": ("301319", "唯特偶"),
    "本川智能": ("300964", "本川智能"),
    "麦格米特": ("002851", "麦格米特"),
    "中信建投": ("601066", "中信建投"),
    "银河证券": ("601881", "中国银河"),
    "中金": ("601995", "中金公司"),
}

TAGS = {
    "claim-20260712-001-a": ["放量阴包阳", "杀跌情绪", "短线偏空", "市场结构"],
    "claim-20260712-002-b": ["仓位管理", "防守策略", "短线应对"],
    "claim-20260712-003-c": ["大势判断", "市场风险", "多头不利"],
    "claim-20260712-004-d": ["周一观察", "情绪反馈", "调整级别"],
    "claim-20260712-005-e": ["指数背离", "科技股", "个股普涨", "市场割裂"],
    "claim-20260712-006-f": ["科技分化", "非科技走强", "反弹反复性"],
    "claim-20260712-007-g": ["内生性回调", "筹码波动", "算力趋势"],
    "claim-20260712-008-h": ["放量阴包阳", "情绪释放", "节奏确认"],
    "claim-20260712-009-i": ["条件化框架", "周一应对", "防守为先"],
    "claim-20260712-010-j": ["存量博弈", "板块跷跷板", "系统性转换"],
    "claim-20260712-011-k": ["中报预告", "基本面验证", "博弈焦点"],
    "claim-20260712-012-l": ["科技再筛选", "商业航天", "国产算力", "高拥挤释放"],
    "claim-20260712-013-m": ["科技无序波动", "降低关注", "避免强交易"],
    "claim-20260712-014-n": ["昇腾950", "全国算力网", "国产算力"],
    "claim-20260712-015-o": ["国产模型", "Token调用量", "ARR增长", "算力需求"],
    "claim-20260712-016-p": ["算力链", "Q2业绩", "算力租赁", "国产交换机"],
    "claim-20260712-017-q": ["商业航天", "卡节点", "阶段主线"],
    "claim-20260712-018-r": ["商业航天", "周一应对", "前排持续性", "放量长阳"],
    "claim-20260712-019-s": ["AI应用", "硬件领跌", "高低切换"],
    "claim-20260712-020-t": ["科技内部分化", "硬件", "应用软件"],
    "claim-20260712-021-u": ["港股科技", "AI含量", "价值重估"],
    "claim-20260712-022-v": ["海外云厂商", "估值锚", "AI资本开支"],
    "claim-20260712-023-w": ["港股映射", "AI应用", "资金轮动"],
    "claim-20260712-024-x": ["医药趋势", "防御线", "非科技轮动"],
    "claim-20260712-025-y": ["食品饮料", "中报业绩", "防御补充"],
    "claim-20260712-026-z": ["美国CPI", "通胀叙事", "科技情绪"],
    "claim-20260712-027-aa": ["WAIC", "人工智能大会", "科技催化"],
    "claim-20260712-028-ab": ["中报预告", "7月15日", "阶段底部"],
    "claim-20260712-029-ac": ["Token调用量", "模型ARR", "北美云厂Capex"],
    "claim-20260712-030-ad": ["国产CPU", "Intel涨价", "Agent需求", "信创"],
    "claim-20260712-031-ae": ["算力租赁", "业绩高增", "有卡有利润"],
    "claim-20260712-032-af": ["锡膏", "光模块升级", "国产替代"],
    "claim-20260712-033-ag": ["CIPB功率基板", "AI服务器电源", "麦格米特订单"],
    "claim-20260712-034-ah": ["原奶", "周期反转", "奶价回升"],
    "claim-20260712-035-ai": ["食品饮料", "中报预告", "选股优先级"],
    "claim-20260712-036-aj": ["氦气", "出口管制", "国产供应链"],
    "claim-20260712-037-ak": ["绿电", "储能", "节能降碳政策"],
}


def board_suffix(code: str) -> str:
    if code.startswith(("300", "301")):
        return "创业板不可交易"
    if code.startswith("688"):
        return "科创板不可交易"
    if code.startswith(("8", "4", "43")):
        return "北交所不可交易"
    return "主板可交易"


def annotate(text: str) -> str:
    """Annotate known company names with their 6-digit codes."""
    if not text:
        return text
    # Sort by length desc to match longer names first.
    for name in sorted(NAME_MAP.keys(), key=len, reverse=True):
        code, _ = NAME_MAP[name]
        # Skip if already annotated (followed by '(' or '（' with code)
        pattern = re.escape(name) + r"(?![（(])"
        repl = f"{name}({code})"
        text = re.sub(pattern, repl, text)
    return text


def related_stocks_for(text: str) -> list[dict]:
    """Collect related stocks found in text."""
    found = {}
    for name in sorted(NAME_MAP.keys(), key=len, reverse=True):
        code, official = NAME_MAP[name]
        if name in text or (code in text):
            if code not in found:
                found[code] = official
    # Keep deterministic order by first appearance in text
    items = []
    seen = set()
    for name in sorted(NAME_MAP.keys(), key=len, reverse=True):
        code, official = NAME_MAP[name]
        if code in found and code not in seen:
            idx = text.find(name) if name in text else len(text)
            items.append((idx, code, official))
            seen.add(code)
    items.sort(key=lambda x: x[0] if x[0] >= 0 else len(text))
    return [
        {"code": code, "name": official, "role": board_suffix(code)}
        for _, code, official in items
    ]


def main():
    with open(IN_FILE, encoding="utf-8") as f:
        data = json.load(f)

    claims = data.get("claims", data)
    enriched_count = 0
    for claim in claims:
        cid = claim.get("id", "")
        # Annotate text fields
        for key in ("statement", "interpretation", "evidence_quote"):
            if key in claim and isinstance(claim[key], str):
                claim[key] = annotate(claim[key])

        # Add related_stocks from all textual fields combined
        combined = "\n".join(
            str(claim.get(k, "")) for k in ("statement", "interpretation", "evidence_quote")
        )
        rs = related_stocks_for(combined)
        claim["related_stocks"] = rs

        # Add tags
        claim["tags"] = TAGS.get(cid, [])

        # Ensure topic
        if not claim.get("topic"):
            claim["topic"] = claim.get("subject", "")

        enriched_count += 1

    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump({"claims": claims}, f, ensure_ascii=False, indent=2)

    print(f"Enriched {enriched_count} claims -> {OUT_FILE}")


if __name__ == "__main__":
    main()
