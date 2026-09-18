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

import json, sys, os
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
                # Gate 3b: code 必须是字符串（6位数字代码），不能是整数
                code_val = item.get("code")
                if isinstance(code_val, int):
                    errors.append(f"related_stocks code={code_val} 是整数类型，应改为字符串 '{code_val}'")
                elif isinstance(code_val, str) and not code_val.isdigit():
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


def gate5_stock_codes(claim: dict) -> list[str]:
    """检查 statement/interpretation 中提到的公司名是否带 6 位代码。

    v3：词典最大匹配 —— 在文本中扫描已知 A 股公司名，命中且未标注代码则报错。
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

    # 3) 过滤同形词 + 已标注代码
    for name in hits:
        if name in _AMBIGUOUS_NAMES:
            continue
        if re.search(re.escape(name) + r"[（(]\d{6}[）)]", text):
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
