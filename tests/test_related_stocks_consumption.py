#!/usr/bin/env python3
"""Neo4j migrate / Qdrant payload 对 related_stocks 的消费 —— 回归测试。

背景（2026-09-19）：
    存量回填了 411 条 related_stocks，但审计发现 migrate_claims_to_neo4j.py
    与 index_claims_to_qdrant.py **都不读该字段** → 回填只停在 YAML 层，
    图库/向量库拿不到。
    本测试锁定「related_stocks 必须进入 Neo4j Stock 节点/ABOUT 边 + Qdrant payload」。

运行: python -m pytest tests/test_related_stocks_consumption.py -v
"""
import ast
import importlib.util
import inspect
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
MIGRATE = REPO / "scripts" / "migrate_claims_to_neo4j.py"
QDRANT = REPO / "scripts" / "index_claims_to_qdrant.py"
GATE_PATH = REPO / "scripts" / "gate_validate_claims.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    import sys
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# ── A. migrate 侧：必须从 related_stocks 提取标的 ────────────────

def test_extract_related_stocks_exists():
    """migrate 脚本必须提供 extract_related_stocks()。"""
    src = MIGRATE.read_text(encoding="utf-8")
    assert "def extract_related_stocks" in src, (
        "migrate 缺 extract_related_stocks() —— related_stocks 不会被消费"
    )


def test_extract_related_stocks_reads_field():
    """extract_related_stocks 必须从 claim['related_stocks'] 取值。"""
    mod = _load(MIGRATE, "migrate_test_mod")
    fn = getattr(mod, "extract_related_stocks", None)
    assert fn is not None, "缺 extract_related_stocks"
    claim = {
        "id": "claim-test-001-a",
        "related_stocks": [
            {"code": "688981", "name": "中芯国际", "role": "回填-正文提及"},
            {"code": "601133.SH", "name": "柏诚股份", "role": "参考标的"},
        ],
    }
    out = fn(claim)
    codes = {str(x[0] if isinstance(x, (tuple, list)) else x) for x in out}
    assert "688981" in codes, f"related_stocks 里的 688981 未被提取: {out}"
    assert "601133" in codes, f"带后缀的 601133.SH 未归一为 601133: {out}"


def test_extract_related_stocks_handles_missing():
    """无 related_stocks 字段 → 返回空，不抛异常。"""
    mod = _load(MIGRATE, "migrate_test_mod2")
    fn = getattr(mod, "extract_related_stocks", None)
    if fn is None:
        pytest.skip("extract_related_stocks 尚未实现")
    assert fn({"id": "x"}) == []
    assert fn({"id": "x", "related_stocks": None}) == []
    assert fn({"id": "x", "related_stocks": []}) == []


def test_extract_related_stocks_skips_empty_code():
    """空 code（内联列表没补上的）应跳过，不能建出空码 Stock 节点。"""
    mod = _load(MIGRATE, "migrate_test_mod3")
    fn = getattr(mod, "extract_related_stocks", None)
    if fn is None:
        pytest.skip("extract_related_stocks 尚未实现")
    out = fn({"id": "x", "related_stocks": [
        {"code": "", "name": "某标的"},
        {"code": "688981", "name": "中芯国际"},
    ]})
    codes = [str(x[0] if isinstance(x, (tuple, list)) else x) for x in out]
    assert "" not in codes
    assert "688981" in codes


# ── B. migrate 侧：Stock 节点 name 必须用真名而非 subject ────────

def test_stock_node_name_uses_related_stock_name():
    """建 Stock 节点时 name 应来自 related_stocks 的 name，不是 claim.subject。

    历史 bug：`SET s.name = $name` 里 $name = claim.subject，
    导致 Stock.name 变成 '主战场在科技上游材料方向分散' 这类句子。
    """
    src = MIGRATE.read_text(encoding="utf-8")
    # related_stocks 处理块中必须引用 name 字段
    i = src.find("def extract_related_stocks")
    assert i > 0, "缺 extract_related_stocks"
    seg = src[i:i + 2500]
    assert '"name"' in seg or "'name'" in seg, (
        "extract_related_stocks 未返回 name —— Stock 节点会继续用 subject 当名字"
    )


# ── C. Qdrant 侧：payload 与 Cypher RETURN 都要带该字段 ──────────

def test_qdrant_cypher_return_includes_related_stocks():
    """index_claims_to_qdrant.py 的 Cypher RETURN 必须含 related_stocks。

    （skill qing-sync-server-mode：payload 字段来自 Cypher RETURN，
      只改 payload 字典而漏 RETURN → 字段恒为空。）
    """
    src = QDRANT.read_text(encoding="utf-8")
    i = src.find("MATCH (c:Claim) RETURN")
    assert i > 0, "未找到 Cypher RETURN 语句"
    # RETURN 由多段相邻字符串字面量拼成，取其后 800 字符窗口
    window = src[i:i + 800]
    assert "related_stocks" in window, (
        f"Cypher RETURN 缺 related_stocks —— payload 里该字段会恒为空。"
        f"当前窗口: {window[:300]}"
    )


def test_qdrant_payload_includes_related_stocks():
    """payload 字典必须写入 related_stocks。"""
    src = QDRANT.read_text(encoding="utf-8")
    i = src.find("payload={")
    assert i > 0, "未找到 payload={...} 组装块"
    seg = src[i:i + 1500]
    assert "related_stocks" in seg, (
        "payload 字典缺 related_stocks 键"
    )


# ── D. 存量畸形码修复（2026-09-19）────────────────────────────

MALFORMED = [
    ("sh688", "珂玛科技", "301611"),      # 前缀式残码 + 原代码也不对（非 688 系）
    ("sz301018", "申菱环境", "301018"),   # 前缀式残码，去掉 sz 即可
]


@pytest.mark.parametrize("bad,stock,good", MALFORMED)
def test_malformed_code_fixed_in_repo(bad, stock, good):
    """存量 related_stocks 的 `sh688` / `sz301018` 必须已修为纯 6 位码。"""
    import yaml
    hits = []
    for fp in sorted((REPO / "knowledge" / "claims").glob("claim-*.yaml")):
        doc = yaml.safe_load(fp.read_text(encoding="utf-8"))
        if doc is None:
            continue
        items = doc if isinstance(doc, list) else (
            doc["claims"] if isinstance(doc, dict) and isinstance(doc.get("claims"), list) else [doc])
        for c in items:
            if not isinstance(c, dict):
                continue
            for x in (c.get("related_stocks") or []):
                if isinstance(x, dict) and str(x.get("code")) == bad:
                    hits.append((fp.name, c.get("id")))
    assert not hits, f"仍存在畸形码 '{bad}': {hits}"


def test_malformed_code_replaced_with_correct_value():
    """修复后的代码必须是正确值（珂玛科技=301611，不是 688 系）。"""
    import yaml

    def norm(v):
        return str(v).split(".")[0].strip()

    found = []
    for fp in sorted((REPO / "knowledge" / "claims").glob("claim-*.yaml")):
        doc = yaml.safe_load(fp.read_text(encoding="utf-8"))
        if doc is None:
            continue
        items = doc if isinstance(doc, list) else (
            doc["claims"] if isinstance(doc, dict) and isinstance(doc.get("claims"), list) else [doc])
        for c in items:
            if not isinstance(c, dict):
                continue
            for x in (c.get("related_stocks") or []):
                if isinstance(x, dict) and x.get("name") == "珂玛科技":
                    found.append(norm(x.get("code")))
    assert found, "已找不到 珂玛科技 条目"
    assert all(v == "301611" for v in found), f"珂玛科技 代码应为 301611，实际 {found}"


def test_hk_stock_marked_non_tradable():
    """港股码（01548 金斯瑞）不应作为 A 股 code —— role 须标注不可交易。"""
    import yaml
    ok = False
    for fp in sorted((REPO / "knowledge" / "claims").glob("claim-*.yaml")):
        doc = yaml.safe_load(fp.read_text(encoding="utf-8"))
        if doc is None:
            continue
        items = doc if isinstance(doc, list) else (
            doc["claims"] if isinstance(doc, dict) and isinstance(doc.get("claims"), list) else [doc])
        for c in items:
            if not isinstance(c, dict):
                continue
            for x in (c.get("related_stocks") or []):
                if isinstance(x, dict) and x.get("name") == "金斯瑞":
                    role = str(x.get("role", ""))
                    code = str(x.get("code", ""))
                    ok = ok or ("港股" in role) or ("不可交易" in role) or (len(code) == 6)
    assert ok, "金斯瑞（港股 01548）未标注不可交易/未归一为 A 股码"


# ── E. gate3 对境外标的的处置（2026-09-19）──────────────────────

gate = _load(GATE_PATH, "gate_for_rs_test")


def _gate3(rs):
    return gate.gate3_related_stocks(
        {"id": "t", "claim_type": "stock-view", "statement": "x",
         "interpretation": "", "related_stocks": rs})


def test_gate3_accepts_hk_with_non_tradable_role():
    """港股码带 .HK + role 标注不可交易 → 放行。"""
    errs = _gate3([{"code": "01548.HK", "name": "金斯瑞", "role": "港股不可交易"}])
    assert errs == [], errs


def test_gate3_rejects_bare_hk_code():
    """裸港股码（无后缀无标注）→ 报错。"""
    errs = _gate3([{"code": "01548", "name": "金斯瑞", "role": "龙头"}])
    assert any("不是纯数字" in e for e in errs), errs


def test_gate3_rejects_prefix_residue():
    """前缀式残码 sh688 / sz301018 → 仍报错。"""
    for bad in ("sh688", "sz301018"):
        errs = _gate3([{"code": bad, "name": "x"}])
        assert any("不是纯数字" in e for e in errs), f"{bad} 未被检出: {errs}"
