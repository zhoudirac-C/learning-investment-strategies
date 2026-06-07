#!/usr/bin/env python3
"""
Add `topic` and `tags` fields to old-format YAML claim files
in knowledge/claims/ that are missing these fields.

Usage:
    python3 scripts/add_topics_tags.py

This script auto-generates Chinese topic phrases and keyword tags
for claims using rule-based extraction from subject, statement, and claim_type.
It handles three YAML formats: claims: wrapper, bare list, and single dict.

See qing-learning SKILL.md references/claim-topic-tag-generation.md for details.
"""

import os
import re
import yaml
import sys

CLAIMS_DIR = "/home/ubuntu/learning-investment-strategies/knowledge/claims"

# Files to skip (already fixed)
SKIP_FILES = set()

# Sector keyword mapping
SECTOR_KEYWORDS = [
    # Technology / AI
    "半导体", "AI", "人工智能", "算力", "国产算力", "算力租赁", "算力硬件",
    "燃气轮机", "光模块", "CPO", "PCB", "存储", "存储芯片", "HBM", "DDR5",
    "碳化硅", "机器人", "商业航天", "低空经济", "量子计算", "自动驾驶",
    "国产替代", "信创", "操作系统", "数据库", "GPU", "GPU数据库",
    "物理AI",
    # New energy
    "新能源", "锂电池", "储能", "光伏", "风电", "核能", "电力设备",
    "电网", "特高压", "变压器",
    # Defense & aerospace
    "国防军工", "军工", "卫星", "导弹", "无人机",
    # Healthcare
    "生物医药", "创新药", "医疗器械", "中药",
    # Consumer & electronics
    "消费电子", "苹果链", "华为链", "小米链",
    "消费", "白酒", "食品饮料", "家电", "汽车",
    # Commodities & resources
    "煤炭", "石油", "资源", "有色", "稀土", "黄金", "白银",
    # Infrastructure & real estate
    "电力", "地产", "基建", "建材", "水泥", "钢铁",
    # Financial
    "金融", "券商", "银行", "保险",
    # Media & services
    "游戏", "传媒", "教育", "旅游",
    # Specific stocks
    "长鑫", "长鑫存储", "长江存储", "中芯国际", "华为", "字节",
    "兆易创新", "深科技", "雅克科技", "合肥城建", "上峰水泥",
    "通富微电", "茂莱光学", "汇成真空", "海光信息", "寒武纪",
    "拓维信息", "网宿科技", "金风科技", "润泽科技", "星环科技",
    "沪电股份", "深南电路", "中际旭创", "天孚通信", "新易盛",
    "光迅科技", "上海微电子", "新凯来", "华虹",
    # Markets & indices
    "美股", "标普500", "纳斯达克", "道琼斯",
    "恒生", "港股", "A股", "上证", "深证", "上证指数", "深证成指",
    "创业板", "科创板", "创业板指", "科创50",
    "北交所", "沪深300", "中证500", "中证1000",
    # Macro & policy
    "美联储", "央行", "利率", "降息", "加息",
    "人民币", "汇率", "美元", "油价", "PPI", "CPI", "GDP",
    "蒙代尔", "不可能三角",
    # Market concepts
    "市场情绪", "指数调整", "仓位管理", "风险控制",
    "进攻", "防御", "防守反击", "劣性轮动", "良性轮动",
    "龙头", "中军", "跟风", "前排", "后排",
    "止跌信号", "情绪拐点", "量能见底", "修复博弈",
    "高低切", "多空", "空头回补",
    # K-line / technical patterns
    "顶部结构", "底部结构", "调整周期", "日线",
    "30分钟", "60分钟", "120分钟",
    "空方", "多方", "恐慌", "衰竭", "杀跌",
    "二次恐慌", "博弈窗口", "左侧博弈",
]

CLAIM_TYPE_TAGS = {
    "market-cycle": "市场周期",
    "sector-theme": "板块主题",
    "macro": "宏观",
    "technical-signal": "技术信号",
    "operation": "操作策略",
    "methodology": "方法论",
    "stock-view": "个股观点",
    "catalyst": "消息催化",
    "risk-warning": "风险提示",
    "valuation": "估值分析",
}

GENERIC_SUBJECTS = {
    "市场情绪", "操作策略", "仓位管理", "市场周期判断", "大盘",
    "反弹性质判断", "轮动判断", "轮动质量判断", "弱分歧质量",
    "大长腿承接阈值", "科技板块", "强势板块操作策略",
    "5-7成仓位与低吸核心", "板块判断方法论", "标普500",
}

KNOWN_STOCKS = {
    "兆易创新", "深科技", "雅克科技", "合肥城建", "上峰水泥",
    "通富微电", "茂莱光学", "汇成真空", "海光信息", "寒武纪",
    "拓维信息", "网宿科技", "金风科技", "润泽科技", "星环科技",
    "沪电股份", "深南电路", "中际旭创", "天孚通信", "新易盛",
    "光迅科技", "长鑫存储", "长江存储", "中芯国际", "华虹",
    "上海微电子", "新凯来", "华为", "字节",
}

# ── Extraction helpers ──────────────────────────────────────────

def extract_stock_names(text):
    """Extract stock names from text using known stock name list."""
    if not text:
        return []
    names = set()
    for stock in KNOWN_STOCKS:
        if stock in text:
            names.add(stock)
    return list(names)

def extract_sector_keywords(text):
    """Extract sector keywords from text, prioritizing longer matches."""
    if not text:
        return []
    found = set()
    sorted_keywords = sorted(SECTOR_KEYWORDS, key=len, reverse=True)
    for kw in sorted_keywords:
        if kw in text:
            idx = text.find(kw)
            is_contained = False
            for existing in found:
                existing_idx = text.find(existing)
                if existing_idx <= idx and idx + len(kw) <= existing_idx + len(existing):
                    is_contained = True
                    break
            if not is_contained:
                found.add(kw)
    return list(found)

def extract_concept(text, max_len=18):
    """Extract the key concept phrase from text (first clause)."""
    if not text:
        return ""
    clauses = re.split(r'[，,。！？；：\n]', text)
    for clause in clauses:
        clause = clause.strip()
        if len(clause) >= 5:
            clause = re.sub(r'^[\d一二三四五六七八九十]+[、.,)）]\s*', '', clause)
            if 5 <= len(clause) <= max_len:
                return clause
            elif len(clause) > max_len:
                sub = re.split(r'[的之]', clause)
                if len(sub) > 1 and len(sub[0].strip()) >= 5:
                    result = sub[0].strip()
                    if len(result) <= max_len:
                        return result
                result = clause[:max_len]
                result = re.sub(r'[（(][^）)]*$', '', result)
                result = result.rstrip('，,。')
                if len(result) >= 5:
                    return result
                return clause[:max_len]
    return ""

def generate_topic(subject, statement):
    """Generate topic from subject and statement."""
    if subject and len(subject) >= 5 and len(subject) <= 20 and subject not in GENERIC_SUBJECTS:
        return subject
    concept = extract_concept(statement, 20)
    if concept and len(concept) >= 5:
        return concept
    if subject and concept and subject not in GENERIC_SUBJECTS:
        combined = f"{subject}{concept}"
        if len(combined) <= 20:
            return combined
    if concept:
        return concept[:20]
    if subject:
        return subject[:20]
    return "待分类"

def generate_tags(subject, statement, claim_type, related_stocks):
    """Generate tags from subject, statement, claim_type, and related stocks."""
    tags = set()

    # 1. Add claim_type category
    if claim_type in CLAIM_TYPE_TAGS:
        tags.add(CLAIM_TYPE_TAGS[claim_type])

    # 2. Extract sector keywords
    full_text = f"{subject or ''} {statement or ''}"
    sectors = extract_sector_keywords(full_text)
    for s in sectors[:5]:
        tags.add(s)

    # 3. Extract stock names
    stocks = extract_stock_names(full_text)
    for s in stocks[:4]:
        tags.add(s)

    # 4. Add from related_stocks field
    if related_stocks:
        for rs in related_stocks[:3]:
            name = re.sub(r'\([^)]*\)', '', rs).strip()
            if name and len(name) >= 2:
                tags.add(name)

    # 5. Extract key financial/technical terms from statement
    if statement:
        technical_terms = {
            "底部结构": None, "顶部结构": None, "调整周期": None,
            "情绪拐点": None, "量能": None, "缩量": None, "放量": None,
            "止跌": None, "修复": None, "反弹": None, "反转": None,
            "分化": None, "共振": None, "轮动": None, "回调": None,
            "追高": None, "低吸": None, "仓位": None,
            "防御": None, "进攻": None, "主线": None, "催化": None,
            "估值": None, "业绩": None, "IPO": None, "扩产": None,
            "涨价": None, "降息": None, "加息": None, "通胀": None,
            "滞胀": None, "衰退": None, "黄金坑": None, "龙回头": None, "二波": None,
        }
        for term in technical_terms:
            if re.search(term, statement):
                tags.add(term)

    tags_list = list(tags)

    # Pad to minimum 3 tags
    if len(tags_list) < 3:
        ct_tag = CLAIM_TYPE_TAGS.get(claim_type)
        if ct_tag and ct_tag not in tags_list:
            tags_list.append(ct_tag)
        if subject and len(subject) <= 8 and subject not in tags_list:
            tags_list.append(subject)
        if len(tags_list) < 3 and subject:
            trunc = subject[:6] if len(subject) > 6 else subject
            if trunc not in tags_list:
                tags_list.append(trunc)

    # Deduplicate substrings (e.g., "上证" ⊆ "上证指数")
    deduped = []
    sorted_by_len = sorted(tags_list, key=len, reverse=True)
    for tag in sorted_by_len:
        if not any(tag in other and tag != other for other in deduped):
            deduped.append(tag)
    tags_list = deduped

    # Re-pad if dedup reduced below minimum
    if len(tags_list) < 3:
        ct_tag = CLAIM_TYPE_TAGS.get(claim_type)
        if ct_tag and ct_tag not in tags_list:
            tags_list.append(ct_tag)
        if subject and len(subject) <= 8 and subject not in tags_list:
            tags_list.append(subject)
        if len(tags_list) < 3 and ct_tag and ct_tag not in tags_list:
            tags_list.append(ct_tag)

    # Trim to max 8
    if len(tags_list) > 8:
        ct_tag = CLAIM_TYPE_TAGS.get(claim_type)
        if ct_tag and ct_tag in tags_list:
            tags_list.remove(ct_tag)
    if len(tags_list) > 8:
        tags_list = tags_list[:8]

    return tags_list

def process_claims(claims_list):
    """Process a list of claim dicts, adding topic/tags where missing."""
    fields_added = 0
    for claim in claims_list:
        if not isinstance(claim, dict):
            continue
        if "topic" in claim and "tags" in claim:
            continue

        subject = claim.get("subject", "")
        statement = claim.get("statement", "") or claim.get("text", "")
        claim_type = claim.get("claim_type", "")
        related_stocks = claim.get("related_stocks", []) or []

        if "topic" not in claim:
            claim["topic"] = generate_topic(subject, statement)
            fields_added += 1
        if "tags" not in claim:
            claim["tags"] = generate_tags(subject, statement, claim_type, related_stocks)
            fields_added += 1

    return fields_added

# ── YAML read/write helpers ─────────────────────────────────────

def read_yaml_file(filepath):
    """Read a YAML file and return parsed structure + first line."""
    with open(filepath, 'r', encoding='utf-8') as f:
        raw = f.read()
    first_line = raw.strip().split('\n')[0].strip() if raw.strip() else ""
    data = yaml.safe_load(raw)
    return data, first_line

def format_yaml_field(indent, key, val):
    """Format a single YAML field."""
    sub_indent = indent + "  "
    if isinstance(val, list):
        if not val:
            return f"{indent}{key}: []"
        lines = [f"{indent}{key}:"]
        for item in val:
            if isinstance(item, str) and ('\n' in item or '"' in item or ':' in item):
                lines.append(f'{sub_indent}- "{item}"')
            else:
                lines.append(f"{sub_indent}- {item}")
        return '\n'.join(lines)
    elif isinstance(val, dict):
        if not val:
            return f"{indent}{key}: {{}}"
        lines = [f"{indent}{key}:"]
        for k, v in val.items():
            if isinstance(v, list):
                if not v:
                    lines.append(f"{sub_indent}{k}: []")
                else:
                    lines.append(f"{sub_indent}{k}:")
                    for item in v:
                        lines.append(f"{sub_indent}  - {item}")
            else:
                lines.append(f"{sub_indent}{k}: {v}")
        return '\n'.join(lines)
    elif isinstance(val, bool):
        return f"{indent}{key}: {'true' if val else 'false'}"
    elif isinstance(val, (int, float)):
        return f"{indent}{key}: {val}"
    elif isinstance(val, str):
        if '\n' in val:
            indented_val = val.strip().replace('\n', f'\n{sub_indent}')
            return f"{indent}{key}: |\n{sub_indent}{indented_val}"
        elif ':' in val or '#' in val or val.startswith('{') or val.startswith('['):
            return f'{indent}{key}: "{val}"'
        else:
            return f"{indent}{key}: {val}"
    else:
        return f"{indent}{key}: {val}"

def write_yaml_file(filepath, claims_list, is_wrapper=False, is_single=False):
    """Write claims back to YAML file preserving format."""
    lines = []
    if is_wrapper:
        lines.append("claims:")
    for claim in claims_list:
        if is_wrapper:
            lines.append(f"  - id: {claim.get('id', '')}")
        elif is_single:
            lines.append(f"id: {claim.get('id', '')}")
        else:
            lines.append(f"- id: {claim.get('id', '')}")

        field_order = [
            'id', 'topic', 'source_path', 'source_date', 'source_type',
            'extracted_at', 'claim_type', 'subject', 'timeframe',
            'statement', 'text', 'evidence_quote', 'interpretation',
            'confidence', 'status', 'supersedes', 'contradicts',
            'links', 'intensity', 'tags', 'related_stocks',
            'scope', 'time_frame', 'related_claims',
        ]

        if is_wrapper:
            indent = "    "
        elif is_single:
            indent = ""
        else:
            indent = "  "

        for key in field_order:
            if key == 'id':
                continue
            if key in claim and claim[key] is not None:
                lines.append(format_yaml_field(indent, key, claim[key]))

        standard_fields = set(field_order)
        for key in claim:
            if key not in standard_fields and claim[key] is not None:
                lines.append(format_yaml_field(indent, key, claim[key]))

    content = '\n'.join(lines) + '\n'
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)

def process_file(filepath, skip_set=None):
    """Process a single claim file. Returns (fields_added, total_claims)."""
    if skip_set is None:
        skip_set = set()
    basename = os.path.basename(filepath)
    if basename in skip_set:
        return 0, 0

    data, first_line = read_yaml_file(filepath)
    if data is None:
        return 0, 0

    is_wrapper = first_line.startswith("claims:")
    is_single = first_line.startswith("id:")

    if is_wrapper and isinstance(data, dict) and "claims" in data:
        claims_list = data["claims"]
    elif isinstance(data, list):
        claims_list = data
    elif isinstance(data, dict) and "id" in data:
        claims_list = [data]
    else:
        return 0, 0

    all_have = all(
        isinstance(c, dict) and "topic" in c and "tags" in c
        for c in claims_list
    )
    if all_have:
        return 0, len(claims_list)

    fields_added = process_claims(claims_list)
    write_yaml_file(filepath, claims_list, is_wrapper, is_single)
    return fields_added, len(claims_list)

def main():
    import sys
    yaml_files = sorted([
        f for f in os.listdir(CLAIMS_DIR)
        if f.endswith('.yaml') and f not in SKIP_FILES
    ])
    total_modified = 0
    total_claims = 0
    for fname in yaml_files:
        filepath = os.path.join(CLAIMS_DIR, fname)
        mod, claims = process_file(filepath, SKIP_FILES)
        total_modified += mod
        total_claims += claims
        if mod > 0:
            print(f"  {fname}: {mod} fields, {claims} claims")
    print(f"\nTotal: {total_modified} fields added across {total_claims} claims in {len(yaml_files)} files")
    return 0

if __name__ == "__main__":
    sys.exit(main())
