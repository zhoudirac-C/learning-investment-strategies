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
)

# ── Gate 1: 字段完整性 ──────────────────────────────────
def gate1_missing_fields(claim: dict) -> list[str]:
    """检查 18 个必需字段是否都存在"""
    missing = []
    for k in REQUIRED_FIELDS:
        if k not in claim or claim[k] is None or claim[k] == "":
            missing.append(k)
    return missing


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
    if rs is None or rs is None:
        links = claim.get("links", {})
        rs = links.get("related_stocks", [])

    statement = claim.get("statement", "")
    interpretation = claim.get("interpretation", "")

    # 如果 statement/interpretation 提到公司但 related_stocks 为空
    # 简单判断：如果 claim 提到任何以 "公司" / "股份" / "有限" / "科技" 结尾的词
    has_company = any(
        kw in statement or kw in interpretation
        for kw in ["股份", "有限", "科技", "电子", "智能", "医疗", "能源"]
    )
    if has_company and (not rs or rs == []):
        errors.append("statement/interpretation 提到公司名但 related_stocks 为空")

    # 检查 related_stocks 格式
    if rs and isinstance(rs, list):
        for item in rs:
            if isinstance(item, str) and not item.startswith("#"):
                errors.append(f"related_stocks 项是字符串格式 '{item}'，应为 {{code/name/role}} 对象")
            elif isinstance(item, dict):
                if "code" not in item or "name" not in item:
                    errors.append(f"related_stocks 项 {item} 缺 code/name 字段")
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
def gate5_stock_codes(claim: dict) -> list[str]:
    """检查 statement/interpretation 中提到的公司名是否带 6 位代码"""
    errors = []
    import re

    text = claim.get("statement", "") + "\n" + claim.get("interpretation", "")

    # 找到所有 "公司名(数字)" 模式
    code_refs = re.findall(r"[（(](\d{4,6})[）)]", text)
    for code in code_refs:
        if len(code) != 6:
            errors.append(f"股票代码 '{code}' 不是 6 位")

    # 找到所有 "公司名" 模式下无代码的
    # 中文公司名模式：2-5 字中文 + "股份"/"科技"/"电子"/"智能"/"医疗"/"有限"
    company_names = re.findall(r"([\u4e00-\u9fff]{2,5}(?:股份|科技|电子|智能|医疗|有限))", text)
    for name in set(company_names):
        # 检查后面是否紧跟 (6位代码)
        if not re.search(re.escape(name) + r"[（(]\d{6}[）)]", text):
            errors.append(f"'{name}' 在文本中出现但未标注 6 位代码")
    return errors


# ── 主校验函数 ──────────────────────────────────────────
def validate_claims(claims: list[dict]) -> list[dict]:
    """对 claims 列表执行全部 5 道门禁检查"""
    results = []
    for claim in claims:
        cid = claim.get("id", "?")
        errors = []
        errors.extend(gate1_missing_fields(claim))
        errors.extend(gate2_enum_invalid(claim))
        errors.extend(gate3_related_stocks(claim))
        errors.extend(gate4_atomicity(claim))
        errors.extend(gate5_stock_codes(claim))
        if errors:
            results.append({"id": cid, "errors": errors})
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

    if "--all" in sys.argv:
        # 全量审计
        claims_dir = REPO_ROOT / "knowledge" / "claims"
        yaml_files = sorted(f for f in claims_dir.glob("*.yaml") if not f.name.endswith(".bak"))
        total_errors = 0
        for fpath in yaml_files:
            try:
                claims = load_claims(str(fpath))
                results = validate_claims(claims)
                if results:
                    print(f"❌ {fpath.name}")
                    for r in results:
                        for e in r["errors"]:
                            print(f"   {r['id']}: {e}")
                    total_errors += len(results)
            except Exception as e:
                print(f"⚠️  {fpath.name}: 解析失败 — {e}")
        if total_errors == 0:
            print("✅ 全量审计通过")
            sys.exit(0)
        else:
            print(f"\n⚠️  共 {total_errors} 条 claim 有错误")
            sys.exit(1)

    elif len(sys.argv) >= 2:
        path = sys.argv[1]
        try:
            claims = load_claims(path)
            results = validate_claims(claims)
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
