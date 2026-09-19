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


# ── G. related_stocks 豁免（方案A新增，2026-09-19）────────────
#
# 语义依据：gate3 已确立「标的池 = related_stocks」。正文提到公司名、
# 而该标的已在 related_stocks 结构化列出 → 视为已标注，不要求在正文重复写码。
# 目的：消除产业链罗列式 claim 的噪音（一条 claim 罗列 20+ 公司名）。

def _claim_rs(statement, rs, interpretation=""):
    return {"id": "test-rs-001-a", "statement": statement,
            "interpretation": interpretation, "related_stocks": rs}


def test_company_in_related_stocks_is_exempt():
    """正文提到、且已在 related_stocks → 不报错。"""
    c = _claim_rs("WAIC超节点产业链核心环节包括交换芯片（盛科通信25.6T订单突破）",
                  [{"code": "688702", "name": "盛科通信", "role": "交换芯片"}])
    errs = gate.gate5_stock_codes(c)
    assert errs == [], f"已在 related_stocks 却报错: {errs}"


def test_company_not_in_related_stocks_still_reports():
    """正文提到、但 related_stocks 也没有 → 仍必须报错（真缺口）。"""
    c = _claim_rs("WAIC超节点产业链核心环节包括交换芯片（盛科通信25.6T订单突破）",
                  [{"code": "000063", "name": "中兴通讯", "role": "交换芯片"}])
    errs = gate.gate5_stock_codes(c)
    assert any("盛科通信" in e for e in errs), f"真缺口未报: {errs}"


def test_empty_related_stocks_still_reports():
    """related_stocks 为空 → 照常报错（不能因字段存在就全放行）。"""
    c = _claim_rs("买入中晶科技20万元", [])
    errs = gate.gate5_stock_codes(c)
    assert any("中晶科技" in e for e in errs), errs


def test_related_stocks_none_still_reports():
    """related_stocks 缺失（None）→ 照常报错。"""
    c = {"id": "t", "statement": "买入中晶科技20万元", "interpretation": ""}
    errs = gate.gate5_stock_codes(c)
    assert any("中晶科技" in e for e in errs), errs


# ── H. 代码格式扩展（方案A新增，2026-09-19）──────────────────
#
# 存量已写入的代码有多种等效写法，旧正则 [（(]\d{6}[）)] 认不全：
#   - 全角括号（603221）
#   - 带交易所后缀 688652.SH / 002897.SZ
# 这些都是有效标注，不应重复报错。

CODE_FORMAT_CASES = [
    "买入爱丽家居（603221）纯博弈",          # 全角括号（已在旧用例）
    "京仪装备(688652.SH)温控接近独供",       # .SH 后缀
    "意华股份(002897.SZ)是800G连接器厂商",   # .SZ 后缀
    "某标的(830799.BJ)为北交所标的",          # .BJ 后缀
    "京仪装备（688652.SH）温控接近独供",     # 全角 + 后缀
]


@pytest.mark.parametrize("text", CODE_FORMAT_CASES)
def test_code_format_variants_accepted(text):
    """全角括号 / 交易所后缀 均视为已标注。"""
    errs = gate.gate5_stock_codes(_claim(text))
    assert errs == [], f"'{text}' 有效标注被误报: {errs}"


# ── I. 研报署名豁免（方案A新增，2026-09-19）──────────────────
#
# 「据华泰证券」「东吴证券测算」「引用长江证券观点」是信息源署名，
# 不是投资标的。这类命中应放行（用户 2026-09-19 拍板豁免）。

BROKER_CASES = [
    "据国海证券，非UP独立判断",
    "UP引用中信建投观点认为MLCC进入超级周期",
    "据华泰证券测算，2028年国产超节点市场空间有望达3414亿元",
    "UP引用东吴证券观点，指出锡、铟、铪三种小金属具备涨价逻辑",
    "复盘引用长江证券观点",
    "据国信证券，MLCC超级周期区别于2018年",
    "据华泰证券黄乐平团队，六张网工程要求本土供应商占比不低于80%",
    "UP引用兴业证券观点并给出个人判断",
]


@pytest.mark.parametrize("text", BROKER_CASES)
def test_broker_attribution_exempt(text):
    """研报/券商署名 → 不报错。"""
    errs = gate.gate5_stock_codes(_claim(text))
    assert errs == [], f"研报署名 '{text}' 误报: {errs}"


def test_broker_word_alone_still_reports():
    """「华泰证券」作为标的出现（无署名语境）→ 仍报错。"""
    c = _claim("华泰证券今日涨停，券商板块整体走强")
    errs = gate.gate5_stock_codes(c)
    assert any("华泰证券" in e for e in errs), errs


# ── K. gate3 接受交易所后缀码（2026-09-19 方案A）──────────────
#
# 存量 related_stocks 大量使用 `688652.SH` / `002897.SZ` 写法（53 claim / 93 处），
# 旧 gate3 只认纯 6 位数字 → 误报。后缀是有效且无歧义的 A 股标注，应接受。

def _claim3(rs):
    return {"id": "t", "claim_type": "stock-view", "statement": "x",
            "interpretation": "", "related_stocks": rs}


def test_gate3_accepts_suffix_code():
    errs = gate.gate3_related_stocks(
        _claim3([{"code": "688652.SH", "name": "京仪装备"}]))
    assert errs == [], f"后缀码被误报: {errs}"


def test_gate3_accepts_sz_bj_suffix():
    for c in ("002897.SZ", "830799.BJ", "600487.SH"):
        errs = gate.gate3_related_stocks(_claim3([{"code": c, "name": "x"}]))
        assert errs == [], f"'{c}' 被误报: {errs}"


def test_gate3_still_rejects_non_code():
    errs = gate.gate3_related_stocks(_claim3([{"code": "NVDA", "name": "英伟达"}]))
    assert any("不是纯数字" in e for e in errs), errs


def test_gate3_still_rejects_short_code():
    errs = gate.gate3_related_stocks(_claim3([{"code": "12345", "name": "x"}]))
    assert any("不是纯数字" in e for e in errs), errs


# ── L. 研报署名变体（2026-09-19 实测 23 处误入标的，回填时发现）─────
#
# 首版豁免只用 6 字邻域，漏掉大量真实变体 → 23 个券商名被写进 related_stocks。
# 本条覆盖实测的全部变体形态。

BROKER_VARIANT_CASES = [
    "国金证券定义为继HBM之后的算力新瓶颈",           # XX证券定义为
    "东吴证券/国盛证券研报逻辑支撑",                  # 多券商并列+研报
    "兴业证券指C端AI需求爆发或带动腾讯算力需求",      # XX证券指
    "据国盛、东吴证券",                              # 据+并列
    "卖方公开测算（中泰证券假设10%渗透率）",          # 卖方+XX证券假设
    "国金证券点评国内创新药步入业绩兑现黄金窗口",     # XX证券点评
    "东吴证券陈海进认为当前海外算力估值锚已变",       # XX证券+人名+认为
    "浙商证券信息技术团队认为AI自主获取访问权限",     # XX证券团队认为
    "中信证券保荐、拟募资42.02亿",                    # XX证券保荐
    "国联民生证券指其打通传统软件服务",               # XX证券指
    "中信建投许光坦提到的国内设备与零部件出海窗口",   # XX证券+人名
    "UP给出与卖方（长江证券）不同的医药判断框架",     # 卖方（XX证券）
    "招商证券：AI加速半导体万亿美元时代落地",         # XX证券：
    "东吴证券预测2026-2028年归母净利17.9/18.5",     # XX证券预测
    "东方证券通信团队测算，从1.6T可插拔升级至3.2T",   # XX证券团队测算
    "中金公司换股吸收合并东兴证券、信达证券已获通过",  # 并购语境
]


@pytest.mark.parametrize("text", BROKER_VARIANT_CASES)
def test_broker_variant_exempt(text):
    """研报署名各类变体 → 不报错。"""
    errs = gate.gate5_stock_codes(_claim(text))
    assert errs == [], f"研报署名变体 '{text}' 误报: {errs}"


BROKER_AS_TARGET_CASES = [
    "华泰证券今日涨停，券商板块整体走强",
    "中信证券大跌3%，券商股集体回调",
    "东方财富、中信证券领涨券商板块",
]


@pytest.mark.parametrize("text", BROKER_AS_TARGET_CASES)
def test_broker_as_target_reports(text):
    """券商作为标的（涨跌语境）→ 仍必须报错，不能被豁免规则吞掉。"""
    errs = gate.gate5_stock_codes(_claim(text))
    assert any("证券" in e for e in errs), f"标的语境被误豁免: {text} -> {errs}"
