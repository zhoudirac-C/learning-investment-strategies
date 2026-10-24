"""claim 市场结果结算（M3 回写机制 v1，spec 2026-10-24-m3-outcome-writeback）。

对已有 direction（LLM 判向）的 claim，按 basis（指数/个股）取 kline_cache
收盘价，计算 source_date 后第 5 个交易日 forward 收益，机械判定
hit / miss / neutral_window；缺数据诚实标 pending_data / insufficient_data。
结算幂等，重跑覆盖 outcome 块；不触碰 confidence 原字段。
"""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import date
from pathlib import Path

WINDOW_DAYS = 5
HIT_THRESHOLD_PCT = 1.0

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_KLINE_DB = PROJECT_ROOT / "infra" / "data" / "kline_cache.db"

_OUTCOME_FIELDS = (
    "result", "reason", "evaluated_at", "window_days", "basis_code",
    "t0_date", "t5_date", "t0_close", "t5_close", "fwd_return_pct",
)


def normalize_stock_code(code: str) -> str:
    """规范化股票代码为 6位+交易所后缀；指数代码（sh/sz 前缀）原样返回。"""
    s = str(code or "").strip()
    if re.match(r"^(sh|sz)\d{6}$", s):
        return s
    digits = re.sub(r"\D", "", s)
    if len(digits) != 6:
        return s
    first = digits[0]
    if first in "69":
        suffix = "SH"
    elif first in "48":
        suffix = "BJ"
    else:
        suffix = "SZ"
    return f"{digits}.{suffix}"


def load_series(db_path, code: str) -> list[tuple[str, float]]:
    """读取日线收盘价序列 [(date, close), ...] 按日期升序。

    sh/sz 前缀读 index_klines（timeframe='daily'），其余读 stocks_kline。
    """
    con = sqlite3.connect(str(db_path))
    try:
        if re.match(r"^(sh|sz)\d{6}$", code):
            rows = con.execute(
                "SELECT bar_time, close FROM index_klines "
                "WHERE code = ? AND timeframe = 'daily' ORDER BY bar_time",
                (code,),
            ).fetchall()
            out = [(str(d)[:10], float(c)) for d, c in rows if c is not None]
        else:
            rows = con.execute(
                "SELECT trade_date, close FROM stocks_kline "
                "WHERE code = ? ORDER BY trade_date",
                (code,),
            ).fetchall()
            out = [(str(d)[:10], float(c)) for d, c in rows if c is not None]
        out.sort(key=lambda x: x[0])
        return out
    finally:
        con.close()


def settle_claim(claim: dict, db_path=DEFAULT_KLINE_DB,
                 today: str | None = None) -> dict:
    """结算单条 claim → outcome dict（含 result/reason/价格明细）。

    today：用于 pending_data 判断的「当前日」（可注入固定值便于测试）；
    默认取系统当天。direction.value 必须为 bullish/bearish，否则 ValueError。
    """
    direction = claim.get("direction") or {}
    value = direction.get("value")
    if value not in ("bullish", "bearish"):
        raise ValueError(f"direction.value 必须是 bullish/bearish， got {value!r}")
    evaluated_at = today or date.today().isoformat()

    basis = str(direction.get("basis_code") or "").strip()
    if not basis:
        return {"result": "insufficient_data", "reason": "direction 缺 basis_code",
                "evaluated_at": evaluated_at, "window_days": WINDOW_DAYS,
                "basis_code": ""}
    if not re.match(r"^(sh|sz)\d{6}$", basis):
        basis = normalize_stock_code(basis)

    series = load_series(db_path, basis)
    if not series:
        return {"result": "insufficient_data",
                "reason": f"kline 缓存无 {basis} 日线",
                "evaluated_at": evaluated_at, "window_days": WINDOW_DAYS,
                "basis_code": basis}

    sd = str(claim.get("source_date") or "")
    t0_idx = next((i for i, (d, _) in enumerate(series) if d >= sd), None)
    if t0_idx is None:
        return {"result": "insufficient_data",
                "reason": f"source_date {sd} 早于 {basis} 全部 K 线",
                "evaluated_at": evaluated_at, "window_days": WINDOW_DAYS,
                "basis_code": basis}

    t5_idx = t0_idx + WINDOW_DAYS
    if t5_idx >= len(series):
        return {"result": "pending_data",
                "reason": f"第 {WINDOW_DAYS} 交易日未到（最新 {series[-1][0]}）",
                "evaluated_at": evaluated_at, "window_days": WINDOW_DAYS,
                "basis_code": basis,
                "t0_date": series[t0_idx][0], "t0_close": series[t0_idx][1]}

    t0_date, t0_close = series[t0_idx]
    t5_date, t5_close = series[t5_idx]
    ret = round((t5_close - t0_close) / t0_close * 100.0, 4)  # 4 位 round 消除浮点噪声
    aligned = ret >= HIT_THRESHOLD_PCT if value == "bullish" else ret <= -HIT_THRESHOLD_PCT
    opposed = ret <= -HIT_THRESHOLD_PCT if value == "bullish" else ret >= HIT_THRESHOLD_PCT
    if aligned:
        result, reason = "hit", ""
    elif opposed:
        result, reason = "miss", ""
    else:
        result = "neutral_window"
        reason = f"|{ret:.2f}%| < {HIT_THRESHOLD_PCT}% 阈值"

    return {
        "result": result, "reason": reason,
        "evaluated_at": evaluated_at, "window_days": WINDOW_DAYS,
        "basis_code": basis,
        "t0_date": t0_date, "t5_date": t5_date,
        "t0_close": t0_close, "t5_close": t5_close,
        "fwd_return_pct": round(ret, 2),
    }


_BLOCK_FIELD_ORDERS = {
    "outcome": _OUTCOME_FIELDS,
    "direction": ("value", "basis_kind", "basis_code", "rationale",
                  "annotated_at", "annotator"),
}


def write_block_to_yaml(file_path: Path, claim_id: str, block: str,
                        data: dict) -> None:
    """把命名块（outcome/direction）写入 claim YAML（幂等覆盖）。

    定位 claim 块（`- id: <claim_id>`），在块尾（下一个 `- ` 或 EOF）前
    移除旧同名块并插入新块；字段缩进 = 块字段缩进 + 2。
    """
    text = Path(file_path).read_text(encoding="utf-8")
    lines = text.split("\n")

    # id 行容忍：前导空格、可选 `- ` 前缀、可选引号、行尾注释
    #（存量 YAML 存在 id 不在块首、带引号等非常规写法，如 claim-20261011-001）
    id_pat = re.compile(
        rf"^\s*(?:-\s+)?id:\s*['\"]?{re.escape(claim_id)}['\"]?\s*(?:#.*)?$")
    start = next((i for i, ln in enumerate(lines) if id_pat.match(ln)), None)
    if start is None:
        raise LookupError(f"{file_path} 中未找到 claim id {claim_id}")

    id_indent = len(lines[start]) - len(lines[start].lstrip())
    dict_format = False
    if re.match(r"^\s*-\s+", lines[start]):
        # id 就在 `- id:` 行：块首即本行
        dash_indent = id_indent
        block_start = start
        field_indent = dash_indent + 2
    else:
        # id 在块中间（非常规写法）：向前找**缩进严格小于字段层**的列表项
        # 短横线——supersedes 等嵌套列表项与字段同层（indent == id_indent），
        # 不得误作块首（claim-20261011-001 实录）
        dash_indent = None
        for i in range(start, -1, -1):
            m = re.match(r"^(\s*)-\s+\S", lines[i])
            if m and len(m.group(1)) < id_indent:
                dash_indent = len(m.group(1))
                block_start = i
                break
        if dash_indent is None:
            # 单 claim 字典格式：块 = 整个顶层映射（至 EOF）；
            # 顶层列表值（related_stocks 等）的 `- ` 行是 claim 内容，
            # 绝不可作块尾（claim-20260904-015 实录方向块插进 related_stocks）
            dict_format = True
            dash_indent = id_indent
            block_start = 0
            field_indent = id_indent
        else:
            field_indent = dash_indent + 2

    end = len(lines)
    if not dict_format:
        for i in range(block_start + 1, len(lines)):
            if re.match(r"^\s*-\s+\S", lines[i]) and \
                    (len(lines[i]) - len(lines[i].lstrip())) <= dash_indent:
                end = i
                break

    # 移除旧同名块（扫描整个块，含 id 行之前的字段）
    i = block_start + 1
    final = lines[:block_start + 1]
    while i < end:
        ln = lines[i]
        if re.match(rf"^{' ' * field_indent}{re.escape(block)}:\s*$", ln):
            i += 1
            while i < end and (lines[i].strip() == ""
                               or len(lines[i]) - len(lines[i].lstrip()) > field_indent):
                i += 1
            continue
        final.append(ln)
        i += 1

    order = _BLOCK_FIELD_ORDERS[block]
    out_lines = [f"{' ' * field_indent}{block}:"]
    for key in order:
        if key in data and data[key] not in (None, ""):
            v = data[key]
            if isinstance(v, bool):
                out_lines.append(f"{' ' * (field_indent + 2)}{key}: {str(v).lower()}")
            elif isinstance(v, (int, float)):
                out_lines.append(f"{' ' * (field_indent + 2)}{key}: {v}")
            else:
                # 字符串统一 JSON 双引号：防 `|`（块标量）、`>`、`- `、`#` 等
                # YAML 指示符炸文件（2026-10-24 实录：reason 的 |x%| 损坏 30 文件）
                out_lines.append(
                    f"{' ' * (field_indent + 2)}{key}: {json.dumps(str(v), ensure_ascii=False)}")

    tail = lines[end:]
    Path(file_path).write_text("\n".join(final + out_lines + tail), encoding="utf-8")


def write_outcome_to_yaml(file_path: Path, claim_id: str, outcome: dict) -> None:
    """把 outcome 块写入 claim YAML（幂等：二次回写覆盖，不残留旧键）。"""
    write_block_to_yaml(file_path, claim_id, "outcome", outcome)
