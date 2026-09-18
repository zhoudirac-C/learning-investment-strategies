#!/usr/bin/env python3
"""Gate 5 股票代码检查 — 回归测试

覆盖三类用例：
  A. 真公司名未标注代码 → 必须报错
  B. 假阳性短语（历史 300+ 白名单的等价物）→ 必须不报错
  C. 真公司名已标注代码 → 必须不报错

运行: python -m pytest tests/test_gate5_stock_codes.py -v
"""

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_gate_module():
    """直接加载 gate_validate_claims.py（含内部函数）。"""
    spec = importlib.util.spec_from_file_location(
        "gate_validate_claims", REPO_ROOT / "scripts" / "gate_validate_claims.py"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["gate_validate_claims"] = mod
    spec.loader.exec_module(mod)
    return mod


gate = _load_gate_module()


def _claim(statement: str, interpretation: str = "") -> dict:
    return {"id": "test-001-a", "statement": statement, "interpretation": interpretation}


# ── A. 真公司名未标注代码 → 必须报错 ────────────────────────

REAL_COMPANY_CASES = [
    ("买入中晶科技20万元", "中晶科技"),
    ("跟踪有研硅的产能", "有研硅"),
    ("长源东谷与泰豪科技为备用电源线索", "长源东谷"),
    ("泰豪科技等相关业务线索", "泰豪科技"),
    ("芯碁微装直写光刻、东威科技垂直连续电镀", "芯碁微装"),
    ("百普赛斯与阳光诺和可从上游切入", "百普赛斯"),
    ("红棉股份、云南旅游作为情绪样本", "红棉股份"),
    ("风华高科是MLCC高标", "风华高科"),
    ("汉森制药辨识度更高", "汉森制药"),
    ("爱丽家居前高33.61", "爱丽家居"),
    ("中际旭创代表CPO方向", "中际旭创"),
    ("沪电股份是PCB高标", "沪电股份"),
]


@pytest.mark.parametrize("text,name", REAL_COMPANY_CASES)
def test_real_company_missing_code_reports_error(text, name):
    """真公司名没带代码 → 必须报错。"""
    errs = gate.gate5_stock_codes(_claim(text))
    assert any(name in e for e in errs), f"{name} 应被检出但未检出: {errs}"


# ── B. 假阳性短语 → 必须不报错（核心回归）────────────────────

FALSE_POSITIVE_CASES = [
    # 本批（9/18 青枫浦上专栏）实际踩到的 4 条
    "以及这种压力是否继续传导至国内科技股",
    "非科技方向的延续性以科技分歧为前提",
    "既要看自身催化，也要看科技是否持续吸引增量",
    "今天对科技的判断不宜过度悲观",
    # 历史白名单里的典型样本（抽样，覆盖各类截断模式）
    "高位科技",
    "低位科技",
    "聚焦硬科技",
    "量子科技",
    "宇树科技",
    "三星电子",
    "迈威尔科技",
    "戴尔科技",
    "南亚科技",
    "剑桥科技",
    "武昆股份",
    "调整空间有限",
    "涨幅有限",
    "预期有限",
    "弹性有限",
    "参与价值有限",
    "隔夜美股科技",
    "资金集中在科技",
    "主线肯定是科技",
    "本周定位为科技",
    "受制于科技",
    "资金从科技",
    "风格从非科技",
    "硬件之外的科技",
    "海外链科技",
    "消费电子",
    "汽车电子",
    "配套电子",
    "光电子",
    "人工智能",
    "具身智能",
    "空间智能",
]


@pytest.mark.parametrize("text", FALSE_POSITIVE_CASES)
def test_false_positive_not_reported(text):
    """普通短语/板块词 → 不得报错。"""
    errs = gate.gate5_stock_codes(_claim(text))
    assert errs == [], f"'{text}' 误报: {errs}"


# ── C. 真公司名已标注代码 → 必须不报错 ──────────────────────

ANNOTATED_CASES = [
    "买入中晶科技(003026)20万元",
    "跟踪有研硅(688432)的产能",
    "长源东谷(603950)、泰豪科技(600590)等相关业务线索",
    "芯碁微装(688630)直写光刻、东威科技(688700)垂直连续电镀",
    "百普赛斯(301080)与阳光诺和(688621)可从上游切入",
    "红棉股份(000523)、云南旅游(002059)作为情绪样本",
    "买入爱丽家居（603221）纯博弈",
]


@pytest.mark.parametrize("text", ANNOTATED_CASES)
def test_annotated_company_not_reported(text):
    """已带 6 位代码 → 不得报错。"""
    errs = gate.gate5_stock_codes(_claim(text))
    assert errs == [], f"'{text}' 误报: {errs}"


# ── D. 代码位数校验保留 ──────────────────────────────────

def test_non_six_digit_code_reported():
    """括号内非 6 位数字 → 报错。"""
    errs = gate.gate5_stock_codes(_claim("某公司(1234)"))
    assert any("不是 6 位" in e for e in errs), errs


def test_six_digit_code_accepted():
    """6 位代码 → 不报错。"""
    errs = gate.gate5_stock_codes(_claim("某公司(603221)"))
    assert not any("不是 6 位" in e for e in errs), errs


# ── E. interpretation 字段也要检查 ───────────────────────

def test_interpretation_field_checked():
    """interpretation 中的未标注公司名也要报错。"""
    errs = gate.gate5_stock_codes(_claim("", "重点关注中晶科技的硅片业务"))
    assert any("中晶科技" in e for e in errs), errs


# ── F. 词典闭包性质（防止未来回退化）────────────────────────

def test_all_detections_come_from_dictionary():
    """任何检出必须是词典里的真实公司名 —— 零猜测原则。

    这条断言锁死 v3 的核心性质：不再用正则「猜」公司名。
    若未来有人改回正则宽匹配，此测试会失败。
    """
    import json
    from pathlib import Path

    dic_path = Path(__file__).resolve().parent.parent / "data" / "company_names.json"
    dic = set(json.load(open(dic_path, encoding="utf-8")))

    # 一批典型文案
    samples = [
        "买入中晶科技20万元",
        "跟踪有研硅的产能",
        "风华高科是MLCC高标",
        "爱丽家居前高33.61",
        "中际旭创代表CPO方向",
        "长源东谷(603950)、泰豪科技(600590)",
        "今天对科技的判断不宜过度悲观",
        "调整空间有限",
    ]
    for text in samples:
        for err in gate.gate5_stock_codes(_claim(text)):
            if "不是 6 位" in err:
                continue
            name = err.split("'")[1]
            assert name in dic, f"检出 '{name}' 不在词典中 —— 零猜测原则被破坏"


def test_dictionary_is_loaded():
    """词典必须可加载（缺失时会静默降级为零检出，需显式守护）。"""
    names = gate._company_names()
    assert len(names) > 5000, f"词典仅 {len(names)} 条，疑似未生成"
    for must in ["中晶科技", "有研硅", "长源东谷", "风华高科", "爱丽家居"]:
        assert must in names, f"词典缺 {must}"
