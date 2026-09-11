"""代码归一化：任意写法 → 6 位纯码 + 市场前缀。

对齐 a-stock-data ``norm_ticker``/``get_prefix`` 的号段规则，并整合本仓库
既有口径（``stock_data._normalize_code``、``update_index_klines_intraday``
的 ``sh000932`` 指数形式、``chan_engine`` 的 ``sh512400`` 形式）。

核心规则（踩坑来源均标注）：

1. 显式前缀优先（``sh600519`` / ``600519.SH``），但**前后缀矛盾抛错不猜**。
2. 号段推断：92 开头必先于 9x 判断（920xxx 北交所 vs 900xxx 沪B）；
   ``code.startswith('6')`` 判沪是**错误口径**——会把 510300/588000/900901
   全判错（a-stock-data 2026-08-19 实测，#46）。
3. 解析失败抛 :class:`ValueError`，绝不返空——静默空码会把"格式错"
   伪装成"无数据"（a-stock-data 东财研报 hits=0 教训）。
"""

from __future__ import annotations

import re

_SH_INDEX_EXACT = {
    "000300", "000905", "000016", "000688", "000852", "000010", "000985",
}


def is_index_code(code: str) -> bool:
    """指数形态判定：带市场字母前缀（sh000001/sz399001）。

    对齐 ``chan_engine.data.fetch.is_index`` 口径：含字母即视为指数形式。
    注意纯 6 位码（'000001'）存在指数/个股歧义，本函数不做猜测——
    调用方应通过 ``prefix_for(kind)`` 显式声明。
    """
    return any(c.isalpha() for c in code)


def norm_ticker(code: str, *, stock_only: bool = False) -> str:
    """任意写法 → 6 位纯数字码。解析失败抛 ValueError。

    >>> norm_ticker("SH600519")
    '600519'
    >>> norm_ticker("600519.SH")
    '600519'
    >>> norm_ticker("sz000016")
    '000016'
    """
    raw = str(code).strip()
    m = re.fullmatch(r"^(?:sh|sz|bj)?([0-9]{6})(?:\.(?:sh|sz|bj|SH|SZ|BJ))?$", raw, re.I)
    if not m:
        raise ValueError(
            f"无法解析股票代码 {code!r}：需要 6 位数字或带 sh/sz/bj 前后缀"
            "（如 600519 / sh600519 / 600519.SH）"
        )
    digits = m.group(1)
    pre = re.match(r"^(sh|sz|bj)", raw, re.I)
    suf = re.search(r"\.(sh|sz|bj)$", raw, re.I)
    if stock_only and (digits.startswith(("000", "880", "399")) and (pre or suf)):
        # 显式指数写法（sh000001 等）在 stock_only 下拒绝
        raise ValueError(f"{code!r} 是指数代码，不是个股")
    if pre and suf and pre.group(1).lower() != suf.group(1).lower():
        raise ValueError(f"{code!r} 市场标识前后矛盾（{pre.group(1)} vs {suf.group(1)}），不猜市场")
    if pre and _segment_market(digits) != pre.group(1).lower() and digits[:2] not in ("00",):
        # 显式前缀与号段矛盾（000 段深市指数/个股两用，不拦）
        raise ValueError(
            f"{code!r} 的市场标识与号段矛盾：{digits} 按号段属 "
            f"{_segment_market(digits)} 市，而不是 {pre.group(1)} 市"
        )
    return digits


def _segment_market(digits: str) -> str:
    """按号段推断市场：sh / sz / bj。92 先于 9x 判断（920 北交所 vs 900 沪B）。"""
    if digits.startswith("92"):
        return "bj"
    if digits.startswith(("4", "8")):
        return "bj"
    if digits.startswith(("5", "6", "9")):
        return "sh"
    return "sz"


def prefix_for(code: str, *, kind: str = "auto") -> str:
    """返回市场前缀（sh/sz/bj）。

    kind="auto"：显式前缀优先（但与号段矛盾且非两义段时抛错），
    否则按号段。
    kind="stock"/"index"：纯 6 位码时按号段 + 语义修正
      - 指数：000/880/399 段按沪/同花顺/深归属；
        上证系列 000xxx 属沪（000001=上证指数），与深市个股 000 段是两回事，
        调用方必须传 kind="index" 消歧。
    """
    raw = str(code).strip()
    low = raw.lower()
    m = re.match(r"^(sh|sz|bj)", low)
    if m:
        explicit = m.group(1)
        digits = norm_ticker(raw)
        # 显式前缀与号段矛盾 → 抛错（两义段除外：000 深个股/沪指数两用、880 TDX指数）
        seg = _segment_market(digits)
        ambiguous = digits.startswith(("000", "880"))
        if not ambiguous and seg != explicit and not (explicit == "sh" and digits in _SH_INDEX_EXACT):
            raise ValueError(
                f"{code!r} 市场标识({explicit})与号段({seg})矛盾，不猜市场"
            )
        return explicit
    digits = norm_ticker(raw)
    if kind == "index":
        if digits.startswith("399"):
            return "sz"
        if digits.startswith(("000", "880", "932")):
            return "sh"
        return _segment_market(digits)
    if kind == "stock":
        if digits in _SH_INDEX_EXACT or digits.startswith("880"):
            raise ValueError(f"{code!r} 是指数号段，不是个股")
        return _segment_market(digits)
    # auto
    if digits.startswith("92"):
        return "bj"
    if digits in _SH_INDEX_EXACT or digits.startswith("880"):
        return "sh"
    return _segment_market(digits)


def resolve_symbol(code: str, *, kind: str = "auto") -> tuple[str, str]:
    """归一为 (prefix, digits)。异常写法抛 ValueError。

    显式前缀优先保留（'sh000932' 必须回 sh——auto 号段推断会把
    000 段判成深市，这正是 pre_fetch_index_klines 里的 sh000932 坑）。
    """
    raw = str(code).strip()
    low = raw.lower()
    m = re.match(r"^(sh|sz|bj)", low)
    if m:
        return m.group(1), norm_ticker(raw)
    digits = norm_ticker(raw)
    return prefix_for(digits, kind=kind), digits
