"""影子预测硬事实校验：输出中的涨停/连板声明必须能在当日涨停池中找到。

只校验机器可判的硬事实（涨停/封板/N 连板），性质判断不干预。
命中错误记入 prediction 的 fact_errors 字段，供归因与毕业统计。
已知盲区：否定句（"未涨停"）靠前字符窗口粗筛，极端表述可能漏判。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from investment_engine.blindtest.dataset import LP_ROOT

# 股名后 10 字内出现 涨停/封板/N连板 即视为硬事实声明
_CLAIM_TMPL = r"{name}[^。；;，,]{{0,10}}?(涨停|封板|(\d+)连板)"
_NEGATION_RE = re.compile(r"[未不没无]")

# 反向提取：任意「X涨停/X封板/X连板」声明（X 为 2-6 个非标点汉字，疑似股名）
_ANY_CLAIM_RE = re.compile(r"([\u4e00-\u9fa5]{2,6})(涨停|封板|(\d+)连板)")
# 连接词/量能语境：X 含这些词时视为句法语段而非股名
_CONNECT_WORDS = (
    "上方", "下方", "昨日", "今日", "前日", "且", "或", "但", "若", "则",
    "家数", "家", "潮", "批量", "集体", "率", "梯队", "竞价", "开盘", "尾盘",
    "盘中", "午盘", "首板", "二板", "三板", "高度", "情绪", "修复", "扩散",
    "确认位", "量级", "回升", "回落", "维持", "转强", "走弱", "停家数",
    # 疑问语段（2026-W36 误报：「国芳集团…是否继续封板」被提取出「是否继续」
    # 当股票名查涨停池——提案 2026-09-05 工程问题 2）
    "是否", "能否", "会否", "继续",
)


def _load_zt_map(day: str, lp_root: Path | None = None) -> dict[str, int]:
    """当日涨停池 name → 连板数；文件缺失返回空（调用方据此跳过校验）。"""
    root = Path(lp_root) if lp_root else LP_ROOT
    path = root / f"{day.replace('-', '')}.json"
    if not path.exists():
        return {}
    d = json.loads(path.read_text(encoding="utf-8"))
    return {str(it["name"]): int(it.get("lbc") or 1)
            for it in (d.get("zt_items") or []) if it.get("name")}


def check_prediction(result: dict, day: str, *, extra_names=(), lp_root=None) -> list[str]:
    """返回硬事实错误描述列表（空=通过）。无当日涨停池数据时返回 []。"""
    zt = _load_zt_map(day, lp_root)
    if not zt:
        return []
    text = json.dumps(result or {}, ensure_ascii=False)
    names = set(zt) | {str(n) for n in extra_names if n}
    errors: list[str] = []
    for name in sorted(names, key=len, reverse=True):  # 长名优先，防子串误配
        for m in re.finditer(_CLAIM_TMPL.format(name=re.escape(name)), text):
            claim = m.group(0)
            if _NEGATION_RE.search(claim):  # "未涨停/不涨停"类否定声明跳过
                continue
            n_lbc = m.group(2)
            if name not in zt:
                errors.append(f"{claim}：当日涨停池无 {name}")
            elif n_lbc and int(n_lbc) != zt[name]:
                errors.append(f"{claim}：当日 {name} 实际为 {zt[name]} 连板")

    # 反向提取：输出中任意「X涨停/X封板/X连板」，X 不在涨停池且不在 extra_names
    # → 疑似幻觉个股声明（2026-08-21 江海股份案例：旧逻辑只扫已知名单漏检）
    known = names  # 涨停池 ∪ extra_names
    seen: set[str] = set()
    for m in _ANY_CLAIM_RE.finditer(text):
        word, verb, n_lbc = m.group(1), m.group(2), m.group(3)
        claim = m.group(0)
        if _NEGATION_RE.search(word) or _NEGATION_RE.search(
                text[max(0, m.start() - 2):m.start()]):
            continue
        # 语境词过滤：X 含连接/量能语境词（如「上方且涨停」「但昨日涨停」）非个股声明
        if any(w in word for w in _CONNECT_WORDS):
            continue
        if word in known or word in seen:
            continue
        seen.add(word)
        errors.append(f"{claim}：当日涨停池无 {word}") if not n_lbc else \
            errors.append(f"{claim}：当日涨停池无 {word}")
    return errors
