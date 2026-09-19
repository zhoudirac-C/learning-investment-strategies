#!/usr/bin/env python3
"""
Gate 验证门禁 — Claim 字段完整性 + 格式校验

用法：
  # 校验单个 YAML 文件
  python scripts/gate_validate_claims.py knowledge/claims/claim-20260609-001.yaml

  # 校验临时 JSON 草稿（Step 1 产出）
  python scripts/gate_validate_claims.py temp/claims/step1_raw.json

  # 校验所有 claim 文件（全量审计）
  python scripts/gate_validate_claims.py --all

退出码：0 = 通过, 1 = 有错误
"""

import json, sys, os, re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from qing_investment.claim_schema import (
    REQUIRED_FIELDS,
    VALID_CLAIM_TYPES,
    VALID_TIMEFRAMES,
    VALID_CONFIDENCE,
    VALID_STATUS,
    VALID_INTENSITY,
    VALID_STANCE,
)

# ── Gate 1: 字段完整性 ──────────────────────────────────
# 2026-09-14 多 up 体系扩展：up_id 为新增必填字段，
# 但存量 claim（回填前）可能缺失。对静态审计（--all）降级为警告，
# 对新建 claim（pipeline Step 1/2）保持强制。
GRANDFATHERED_FIELDS = {"up_id"}


def gate1_missing_fields(claim: dict, strict: bool = True) -> tuple[list[str], list[str]]:
    """检查必需字段是否都存在。

    返回 (errors, warnings)。strict=False 时 GRANDFATHERED_FIELDS 缺失进 warnings。
    """
    missing = []
    warnings = []
    for k in REQUIRED_FIELDS:
        if k not in claim or claim[k] is None or claim[k] == "":
            if not strict and k in GRANDFATHERED_FIELDS:
                warnings.append(k)
            else:
                missing.append(k)
    return missing, warnings


# ── Gate 2: 枚举值合法性 ────────────────────────────────
def gate2_enum_invalid(claim: dict) -> list[str]:
    """检查枚举字段是否合法"""
    errors = []
    ct = claim.get("claim_type")
    if ct and ct not in VALID_CLAIM_TYPES:
        errors.append(f"claim_type='{ct}' 不在 {sorted(VALID_CLAIM_TYPES)}")
    tf = claim.get("timeframe")
    if tf and tf not in VALID_TIMEFRAMES:
        errors.append(f"timeframe='{tf}' 不在 {sorted(VALID_TIMEFRAMES)}")
    cf = claim.get("confidence")
    if cf and cf not in VALID_CONFIDENCE:
        errors.append(f"confidence='{cf}' 不在 {sorted(VALID_CONFIDENCE)}")
    st = claim.get("status")
    if st and st not in VALID_STATUS:
        errors.append(f"status='{st}' 不在 {sorted(VALID_STATUS)}")
    # stance 非必填；仅当存在时校验（2026-09-17 新增，存量缺失合法）
    sa = claim.get("stance")
    if sa and sa not in VALID_STANCE:
        errors.append(f"stance='{sa}' 不在 {sorted(VALID_STANCE)}")
    ins = claim.get("intensity")
    if ins and ins not in VALID_INTENSITY:
        errors.append(f"intensity='{ins}' 不在 {sorted(VALID_INTENSITY)}")
    return errors


# ── Gate 3: related_stocks ──────────────────────────────
def gate3_related_stocks(claim: dict) -> list[str]:
    """检查 related_stocks
    - 涉及个股的 claim 必须填
    - 无标的必须写 []
    - 格式必须是 code/name/role 三元组（非旧格式字符串）
    """
    errors = []
    rs = claim.get("related_stocks")
    # 如果是旧格式（放在 links 下），也检查
    if rs is None:
        links = claim.get("links", {})
        rs = links.get("related_stocks", [])

    statement = claim.get("statement", "")
    interpretation = claim.get("interpretation", "")

    # 只检查 stock-view 和 sector-theme 类型（其他类型通常不涉及具体标的）
    ct = claim.get("claim_type", "")
    if ct not in ("stock-view", "sector-theme"):
        return errors

    # 检查 statement 中是否包含 6 位数字代码（说明提到了个股但在 related_stocks 没列）
    import re
    has_code_in_text = bool(re.findall(r"[（(]\d{6}[）)]", statement))
    if has_code_in_text and (not rs or rs == []):
        errors.append("statement 中标注了 A 股代码但 related_stocks 为空")

    # 检查 related_stocks 格式
    if rs and isinstance(rs, list):
        for item in rs:
            if isinstance(item, str) and not item.startswith("#"):
                errors.append(f"related_stocks 项是字符串格式 '{item}'，应为 {{code/name/role}} 对象")
            elif isinstance(item, dict):
                if "code" not in item or "name" not in item:
                    errors.append(f"related_stocks 项 {item} 缺 code/name 字段")
                # Gate 3b: code 必须是字符串（6位数字代码，可选 .SH/.SZ/.BJ 后缀），不能是整数
                #  2026-09-19：后缀写法（688652.SH）是存量广泛使用的有效标注，放行。
                #  港股/美股码（01548.HK）非 A 股标的，必须有交易所后缀且 role 标注不可交易。
                code_val = item.get("code")
                if isinstance(code_val, int):
                    errors.append(f"related_stocks code={code_val} 是整数类型，应改为字符串 '{code_val}'")
                elif isinstance(code_val, str):
                    if re.fullmatch(r"\d{6}(?:\.(?:SH|SZ|BJ))?", code_val.strip()):
                        pass  # 合法 A 股码
                    elif re.fullmatch(r"\d{4,5}\.(?:HK|US|O|N)", code_val.strip()):
                        # 境外标的：允许，但 role 必须显式标注不可交易（AQ 纪律）
                        role = str(item.get("role", ""))
                        if "不可交易" not in role and "港股" not in role and "美股" not in role:
                            errors.append(
                                f"related_stocks code='{code_val}' 为境外标的，"
                                f"role 须标注「不可交易」"
                            )
                    else:
                        errors.append(f"related_stocks code='{code_val}' 不是纯数字字符串")
    return errors


# ── Gate 4: 原子性 ──────────────────────────────────────
def gate4_atomicity(claim: dict) -> list[str]:
    """检查 claim 是否包含多个主题/标的"""
    errors = []
    subject = claim.get("subject", "")
    for sep in ["、", "/", "+", " & ", " and "]:
        if sep in subject:
            errors.append(f"subject 含 '{sep}' — 可能包含多主题")
            break
    return errors


# ── Gate 5: 股票代码格式 ────────────────────────────────
#
# 2026-09-18 重构（v3）：词典最大匹配。
#
# 演进史：
#   v1 正则 `[中文]{2,5}(?:股份|科技|电子|智能|医疗|有限)` + 黑名单
#      → 「科技/电子」是高频普通名词，宽匹配必然误报，黑名单堆到 300+ 仍堵不住
#   v2 结构约束（后缀表+前缀禁则）+ 词典验证
#      → 公司名不以后缀词结尾（有研硅/风华高科/爱丽家居/中际旭创全漏检）
#   v3 词典最大匹配（本版）
#      → 已知全部 5,565 个 A 股公司名，直接在文本里扫描匹配；
#        不用正则猜后缀，故无 v1/v2 两类失败。
#
# 残留处理：极少数公司名与板块词/别家同名（宇树科技=三板、剑桥科技=同名港股），
# 用 _AMBIGUOUS_NAMES 处理。这类「同形词」有限可枚举，与 v1 的无限「截断片段」不同。

# 与板块词/口语同形的公司名（历史 data 里的误报来源，逐个人工确认）
_AMBIGUOUS_NAMES = {
    "宇树科技",      # 未上市（三板），复盘语境指机器人板块
    "剑桥科技",      # 同名港股，复盘语境多指光模块板块
    "南亚科技",      # 台股
    "戴尔科技",      # 美股
    "迈威尔科技",    # 美股 Marvell
    "明略科技",      # 港股 02718
    "中国航天科技",  # 集团名，非上市主体
    # 普通名词型股票简称（词典里存在，但复盘语境几乎不指该标的）
    "机器人",        # 新松/机器人(300024)，语境几乎总是指板块
    "驱动力",        # 口语「驱动力」= 推动因素
    "陆家嘴",        # 常指地名/板块
    "中国移动",      # 口语多指运营商/板块
    "中国联通",
    "中国电信",
}

# ── v4 新增（2026-09-19 方案A）──────────────────────────────
#
# 1) 代码标注识别（含全角括号 + 交易所后缀）
#    存量已写入的等效写法：688652.SH / 002897.SZ / 830799.BJ / （603221）
_CODE_SUFFIX_RE = r"\s*[（(]\s*\d{4,6}\s*(?:\.(?:SH|SZ|BJ))?\s*[）)]"

# 2) 券商/研报机构名 —— 作为「信息源署名」出现时豁免，作为标的不豁免。
#    收录口径：仅头部券商与常被研报引用的机构；刻意保持短名单（避免误放行真标的）。
BROKER_HOUSE_NAMES = {
    "中信证券", "中信建投", "国泰海通", "国泰君安", "华泰证券", "招商证券",
    "广发证券", "申万宏源", "海通证券", "国信证券", "东方证券", "光大证券",
    "兴业证券", "东吴证券", "长江证券", "国金证券", "华创证券", "天风证券",
    "国海证券", "民生证券", "方正证券", "中金公司", "中银证券", "浙商证券",
    "西部证券", "东兴证券", "太平洋证券", "国元证券", "财通证券", "华安证券",
    "太平洋", "开源证券", "信达证券", "国联民生", "中泰证券", "华西证券",
    "山西证券", "第一创业", "财达证券", "湘财股份", "首创证券", "华林证券",
    "国盛证券", "华宝证券", "华鑫证券", "华福证券", "东海证券", "华龙证券",
    "国都证券", "川财证券", "华金证券", "国融证券", "粤开证券", "德邦证券",
    "华源证券", "东方财富", "同花顺", "指南针",
}

# 3) 署名语境标记：机构名**之前**的引导词，或**之后**的动作词。
#    例：「据华泰证券测算」「引用长江证券观点」「XX证券指/认为/定义为/点评/预测」
#    ⚠️ 2026-09-19 实测：仅靠 6 字邻域太窄，漏掉大量变体
#    （「国金证券定义为」「东吴证券/国盛证券研报逻辑」「中信证券保荐」「招商证券：」），
#    故另行叠加"券商名 + 券商后缀/动作词"的整体模式判定。
_BROKER_LEAD_RE = re.compile(
    r"(据|根据|引用|引用自|来自|摘自|参考|源自|转引|援引|结合)\s*$")
_BROKER_TAIL_RE = re.compile(
    r"^\s*(观点|测算|判断|认为|分析|团队|研报|报告|数据|统计|指出|预计|表示|看|提出|"
    r"提供|显示|定[义调]|点评|预测|保荐|称|指|估|假设|曾|):?\s*"
)
# 「XX证券」+ 券商行业动作词，几乎必然是署名（券商作为标的时不会这么搭配）
_BROKER_CONTEXT_RE = re.compile(
    r"(研报|卖方|保荐|承销|分析师|团队)" + r"|" + r"(券商|机构)(?!板块|股|行业)")
# 但若该券商名本身是句子主语/标的（后接涨跌/走势词），则是标的而非署名
_BROKER_AS_TARGET_RE = re.compile(
    r"^\s*(今日|昨日|当天|盘中)?\s*(涨停|跌停|大涨|大跌|走强|走弱|领涨|领跌|拉升|"
    r"异动|封板|开板|破位|创新高|再创新高|新低|上涨|下跌|放量|缩量|收涨|收跌)")
# 并列券商（「东吴证券/国盛证券研报」）—— 名后紧跟分隔符再接另一券商
_BROKER_CHAIN_RE = re.compile(r"^\s*[/、，,]\s*[\u4e00-\u9fff]{2,6}证券")


def _is_broker_attribution(text: str, name: str) -> bool:
    """判断 name 在 text 中是否处于「研报署名」语境。

    四重判定（命中任一即视为署名）：
      1. 名前 12 字内有引导词（据/引用/来自/援引…）
      2. 名后紧跟券商动作词（观点/测算/认为/定义为/点评/保荐…）
      3. 名的邻域（前 25 字）出现券商语境词（研报/卖方/团队/保荐…）
      4. 名后紧跟「/另一券商」（并列署名）

    ⚠️ 例外：若该名后紧跟涨跌/走势词（= 它本身是标的），一律不豁免。
    """
    for m in re.finditer(re.escape(name), text):
        i = m.start()
        tail_win = text[m.end() : m.end() + 10]
        if _BROKER_AS_TARGET_RE.search(tail_win):
            # 作为标的出现（华泰证券今日涨停）→ 不豁免
            continue
        if _BROKER_CHAIN_RE.search(tail_win):
            return True
        lead_win = text[max(0, i - 12) : i]
        if _BROKER_LEAD_RE.search(lead_win):
            return True
        if _BROKER_TAIL_RE.search(tail_win):
            return True
        near_win = text[max(0, i - 25) : m.end() + 12]
        if _BROKER_CONTEXT_RE.search(near_win):
            return True
    return False


def _load_company_names() -> set:
    """加载 A 股公司名词典（data/company_names.json）。

    词典不存在时返回空集合 → gate 降级为「无检出」（保守，宁可漏报不误报）。
    """
    import json
    from pathlib import Path as _P

    cache = _P(__file__).resolve().parent.parent / "data" / "company_names.json"
    if not cache.exists():
        return set()
    try:
        with open(cache, encoding="utf-8") as f:
            return set(json.load(f))
    except Exception:
        return set()


_COMPANY_NAMES: set | None = None


def _company_names() -> set:
    global _COMPANY_NAMES
    if _COMPANY_NAMES is None:
        _COMPANY_NAMES = _load_company_names()
    return _COMPANY_NAMES


def _is_course_claim(claim: dict) -> bool:
    """缠论课程类 claim —— 其历史案例中的公司名是教学素材，非投资标的。

    判别：claim id 日期段 < 2020（课程原始日期）或 source_path 含 chanlun。
    2026-09-19：这类 claim 共 337 条，其中 11 处命中 gate5，
    属「课中以贵州茅台2004年周线二买为历史案例演示」一类，整批豁免。
    """
    cid = str(claim.get("id", ""))
    m = re.match(r"claim-(\d{8})", cid)
    if m and int(m.group(1)[:4]) < 2020:
        return True
    sp = str(claim.get("source_path", "")).lower()
    return "chanlun" in sp


_ANALOGY_LEAD_RE = re.compile(r"(类似|参照|类比|如同|好比|对标|相当于)\s*$")


def _is_analogy_mention(text: str, name: str) -> bool:
    """类比引用 —— 「类似赛力斯第一步」「类似同花顺的轻量版」是修辞对照，非标的。

    2026-09-19：存量中此类仅 2 处，但仍需豁免以免污染标的池。
    """
    for m in re.finditer(re.escape(name), text):
        if _ANALOGY_LEAD_RE.search(text[max(0, m.start() - 8) : m.start()]):
            return True
    return False


def gate5_stock_codes(claim: dict) -> list[str]:
    """检查 statement/interpretation 中提到的公司名是否带 6 位代码。

    v4（2026-09-19 方案A）：在 v3 词典最大匹配之上，新增三条豁免/识别规则：

      1. **related_stocks 豁免** —— 正文提到的公司名若已在 related_stocks
         结构化列出（name 匹配），视为已标注。语义依据：gate3 确立「标的池 =
         related_stocks」，产业链罗列式 claim（一条列 20+ 公司名）不应要求在
         正文重复写码。
      2. **代码格式扩展** —— 旧正则 `[（(]\\d{6}[）)]` 认不出 `688652.SH` /
         `002897.SZ` / `.BJ` 后缀写法；这些是有效标注，扩展识别。
      3. **研报署名豁免** —— 「据华泰证券」「东吴证券测算」「引用长江证券观点」
         是信息源署名而非投资标的（用户 2026-09-19 拍板豁免）。
    """
    import re

    errors = []
    text = claim.get("statement", "") + "\n" + claim.get("interpretation", "")

    # 1) 代码位数校验
    code_refs = re.findall(r"[（(](\d{4,6})[）)]", text)
    for code in code_refs:
        if len(code) != 6:
            errors.append(f"股票代码 '{code}' 不是 6 位")

    # 2) 词典最大匹配检出公司名
    names = _company_names()
    if not names:
        return errors  # 无词典则降级（不误报）

    hits: set[str] = set()
    n = len(text)
    i = 0
    # 按长度降序预排序，用于贪心最长匹配
    sorted_names = sorted(names, key=len, reverse=True)
    maxlen = max((len(x) for x in sorted_names), default=0)

    # 用 set 加速精确匹配：对每个起点尝试 [2..maxlen] 长度
    while i < n:
        matched = False
        for L in range(min(maxlen, n - i), 1, -1):
            cand = text[i : i + L]
            if cand in names:
                hits.add(cand)
                i += L
                matched = True
                break
        if not matched:
            i += 1

    # 3) 过滤同形词 + 已标注代码 + 豁免项
    #    related_stocks 中已结构化列出的标的 → 正文无需重复写码（2026-09-19）
    rs = claim.get("related_stocks") or []
    rs_names: set[str] = set()
    if isinstance(rs, list):
        for item in rs:
            if isinstance(item, dict) and item.get("name"):
                rs_names.add(str(item["name"]))

    for name in hits:
        if name in _AMBIGUOUS_NAMES:
            continue
        if _is_course_claim(claim):
            # 缠论课程历史案例 → 教学素材非标的（2026-09-19）
            continue
        if name in BROKER_HOUSE_NAMES and _is_broker_attribution(text, name):
            # 研报署名语境 → 信息源非标的（2026-09-19 用户拍板）
            continue
        if _is_analogy_mention(text, name):
            # 类比引用（「类似赛力斯第一步」）→ 修辞对照非标的
            continue
        if name in rs_names:
            # 已在 related_stocks 结构化列出 → 豁免
            continue
        if re.search(re.escape(name) + _CODE_SUFFIX_RE, text):
            # 该名字后紧跟有效代码标注（含全角括号 / .SH/.SZ/.BJ 后缀）→ 已标注
            continue
        errors.append(f"'{name}' 在文本中出现但未标注 6 位代码")

    return sorted(errors)


# ── 主校验函数 ──────────────────────────────────────────
def validate_claims(claims: list[dict], step: int = 2, strict: bool = True) -> list[dict]:
    """对 claims 列表执行门禁检查

    step=1: 只检查字段完整性 + 枚举 + 原子性（不含 related_stocks/代码）
    step=2: 全量检查（所有 5 道门禁）

    strict=True  : up_id 缺失 = 错误（用于新建 claim 的 pipeline 门禁）
    strict=False : up_id 缺失 = 警告（用于存量全量审计，回填过渡期）
    """
    results = []
    for claim in claims:
        cid = claim.get("id", "?")
        errors = []
        warns = []
        missing, warn_fields = gate1_missing_fields(claim, strict=strict)
        errors.extend(missing)
        warns.extend(f"缺失新字段(存量宽限): {w}" for w in warn_fields)
        errors.extend(gate2_enum_invalid(claim))
        if step >= 2:
            errors.extend(gate3_related_stocks(claim))
        errors.extend(gate4_atomicity(claim))
        if step >= 2:
            errors.extend(gate5_stock_codes(claim))
        if errors:
            results.append({"id": cid, "errors": errors, "warnings": warns})
        elif warns:
            results.append({"id": cid, "errors": [], "warnings": warns})
    return results


def load_claims(path: str) -> list[dict]:
    """从文件加载 claims 列表，支持 YAML 和 JSON"""
    import yaml

    path = str(REPO_ROOT / path) if not path.startswith("/") else path
    with open(path) as f:
        data = yaml.safe_load(f)

    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        if "claims" in data:
            return data["claims"]
        if "claim" in data:
            return [data["claim"]]
        if "id" in data:
            return [data]
    raise ValueError(f"无法解析 claims: {path}")


def main():
    import yaml  # noqa

    step = 2  # default full check
    args = sys.argv[1:]
    # Parse --step N
    step_idx = [i for i, a in enumerate(args) if a == "--step"]
    if step_idx:
        step = int(args[step_idx[0] + 1])
        args.pop(step_idx[0] + 1)
        args.pop(step_idx[0])

    if "--all" in args:
        # 全量审计（存量宽限：up_id 缺失仅警告）
        claims_dir = REPO_ROOT / "knowledge" / "claims"
        yaml_files = sorted(f for f in claims_dir.glob("*.yaml") if not f.name.endswith(".bak"))
        total_errors = 0
        total_warns = 0
        for fpath in yaml_files:
            try:
                claims = load_claims(str(fpath))
                results = validate_claims(claims, step=step, strict=False)
                errs = [r for r in results if r["errors"]]
                wrns = [r for r in results if not r["errors"] and r.get("warnings")]
                if errs:
                    print(f"❌ {fpath.name}")
                    for r in errs:
                        for e in r["errors"]:
                            print(f"   {r['id']}: {e}")
                    total_errors += len(errs)
                total_warns += len(wrns)
            except Exception as e:
                print(f"⚠️  {fpath.name}: 解析失败 — {e}")
        if total_warns:
            print(f"\nℹ️  共 {total_warns} 条 claim 缺 up_id（存量宽限，待回填第二阶段）")
        if total_errors == 0:
            print("✅ 全量审计通过")
            sys.exit(0)
        else:
            print(f"\n⚠️  共 {total_errors} 条 claim 有错误")
            sys.exit(1)

    elif len(args) >= 1:
        path = args[0]
        try:
            claims = load_claims(path)
            results = validate_claims(claims, step=step)
            if results:
                print(f"❌ {path} — {len(results)} 条 claim 未通过")
                for r in results:
                    print(f"  {r['id']}:")
                    for e in r["errors"]:
                        print(f"    - {e}")
                sys.exit(1)
            else:
                print(f"✅ {path} — {len(claims)} 条 claim 全部通过")
                sys.exit(0)
        except Exception as e:
            print(f"❌ 校验失败: {e}")
            sys.exit(1)
    else:
        print("用法: python scripts/gate_validate_claims.py <file.yml|--all>")
        sys.exit(1)


if __name__ == "__main__":
    main()
