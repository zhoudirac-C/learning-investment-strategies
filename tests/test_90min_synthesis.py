"""90min 合成：跨日污染 bug 的回归测试 (2026-09-10)。

背景
====
`synthesize_90min_klines` 原实现用 `for g in range(len(rows) // 3)` 全局按
bar 数硬切 30min 序列，**不按交易日分组**。后果：

1. **跨日拼接**（最严重）：某日 30min 根数 != 9 时，切分错位会传染到之后
   所有交易日。实测上证 249 组里 48 组混了不同日期的数据。
2. **跨午休拼接**：`11:30 + 13:00 + 13:30` 三根拼成的"90min K线"实际跨 2 小时。
3. **末组残缺**：7/9 个指数 30min 总根数不整除 3，末尾 1-2 根被静默丢弃。

下游影响：盲判 `_compute_cycle_states` 用 90min 做底部结构识别
(`recent_bottom`) → 污染会传导到 cycle_state / "反弹第N天" 判断。

修复：按交易日分组，日内每 3 根切一根；不完整日（<3 根的尾组）跳过，
待数据补齐后下次运行自动纳入。

本测试离线可跑（用临时 sqlite）。
"""

from __future__ import annotations

import importlib.util
import sqlite3
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
CN_TZ = timezone(timedelta(hours=8))

SCHEMA = """
CREATE TABLE index_klines (
    code TEXT NOT NULL, timeframe TEXT NOT NULL, bar_time TEXT NOT NULL,
    open REAL, high REAL, low REAL, close REAL, volume REAL, amount REAL,
    dif REAL, dea REAL, macd_hist REAL, updated_at TEXT,
    PRIMARY KEY (code, timeframe, bar_time)
)
"""


def _load(script_name: str, tmpdb: Path):
    """加载脚本模块，并把 DB_PATH 指向临时库。"""
    spec = importlib.util.spec_from_file_location(
        f"mod_{script_name}", REPO / "scripts" / script_name
    )
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    m.DB_PATH = tmpdb
    return m


def _mkdb(tmp_path: Path) -> Path:
    db = tmp_path / "t.db"
    c = sqlite3.connect(db)
    c.executescript(SCHEMA)
    c.commit()
    c.close()
    return db


def _insert_30min(db: Path, bars: list[tuple[str, float, float, float, float]]):
    """bars: (bar_time, open, high, low, close)"""
    c = sqlite3.connect(db)
    c.executemany(
        "INSERT INTO index_klines (code,timeframe,bar_time,open,high,low,close,volume,amount)"
        " VALUES ('sh000001','30min',?,?,?,?,?,100,1000)",
        bars,
    )
    c.commit()
    c.close()


def _read_90min(db: Path):
    c = sqlite3.connect(db)
    c.row_factory = sqlite3.Row
    rows = c.execute(
        "SELECT * FROM index_klines WHERE timeframe='90min' ORDER BY bar_time"
    ).fetchall()
    c.close()
    return [dict(r) for r in rows]


FULL_DAY_0909 = [
    ("2026-09-09 10:00", 3943.92, 3945.12, 3935.64, 3942.03),
    ("2026-09-09 10:30", 3948.94, 3951.07, 3948.23, 3950.21),
    ("2026-09-09 11:00", 3948.34, 3949.64, 3948.34, 3949.64),
    ("2026-09-09 11:30", 3952.28, 3956.61, 3949.89, 3949.89),
    ("2026-09-09 13:00", 3952.28, 3956.60, 3949.88, 3949.88),
    ("2026-09-09 13:30", 3950.04, 3950.04, 3948.56, 3948.56),
    ("2026-09-09 14:00", 3939.36, 3939.50, 3938.14, 3938.20),
    ("2026-09-09 14:30", 3953.12, 3953.27, 3951.19, 3951.19),
    ("2026-09-09 15:00", 3952.92, 3958.11, 3951.50, 3951.50),
]

# 8 根的不完整日（缺 15:00）—— 用于触发错位传染
SHORT_DAY_0908 = [
    ("2026-09-08 10:00", 100.0, 101.0, 99.0, 100.5),
    ("2026-09-08 10:30", 100.5, 101.5, 99.5, 101.0),
    ("2026-09-08 11:00", 101.0, 102.0, 100.0, 101.5),
    ("2026-09-08 11:30", 101.5, 102.5, 100.5, 102.0),
    ("2026-09-08 13:00", 102.0, 103.0, 101.0, 102.5),
    ("2026-09-08 13:30", 102.5, 103.5, 101.5, 103.0),
    ("2026-09-08 14:00", 103.0, 104.0, 102.0, 103.5),
    ("2026-09-08 14:30", 103.5, 104.5, 102.5, 104.0),
    # 缺 15:00 → 仅 8 根
]

# 不完整日：缺 11:00 和 13:00（模拟盘中抓取）
PARTIAL_DAY_0910 = [
    ("2026-09-10 10:00", 3939.09, 3946.58, 3927.35, 3938.89),
    ("2026-09-10 10:30", 3939.42, 3939.51, 3937.10, 3938.79),
    ("2026-09-10 11:30", 3938.79, 3939.51, 3937.10, 3938.60),
    ("2026-09-10 13:30", 3938.60, 3943.81, 3930.66, 3935.96),
    ("2026-09-10 14:00", 3935.96, 3936.00, 3933.00, 3934.87),
    ("2026-09-10 14:30", 3934.87, 3935.00, 3932.50, 3934.00),
    ("2026-09-10 15:00", 3934.00, 3935.99, 3933.50, 3934.40),
]


# --------------------------------------------------------------------------
# 核心回归：不得跨日
# --------------------------------------------------------------------------

@pytest.mark.parametrize("script", [
    "pre_fetch_index_klines.py",
    "update_index_klines_intraday.py",
])
def test_no_cross_day_grouping(tmp_path, script):
    """任何一根 90min 都不得混入不同交易日的数据。

    用「首日 8 根（缺1根）+ 次日 9 根」构造：全局 //3 硬切会让
    第 2 组 = 0908末2根 + 0909首1根 → 跨日（实测已复现）。

    校验：每根 90min 的 high 必须等于其 bar_time 所在日内某段的 high，
    即不得出现「日内最高价被相邻日抬高」。
    """
    db = _mkdb(tmp_path)
    _insert_30min(db, SHORT_DAY_0908 + FULL_DAY_0909)
    m = _load(script, db)
    m.synthesize_90min_klines("sh000001", dry_run=False)
    out = _read_90min(db)
    assert out, "应产出 90min 数据"

    # 0908 的各段 high 都 <= 104.5；0909 的都 >= 3935
    # 若跨日拼接，会出现「0908 的 bar 带 0909 的价位」或反之
    for b in out:
        day = b["bar_time"][:10]
        if day == "2026-09-08":
            assert b["high"] <= 105.0, (
                f"0908 的 90min high={b['high']} 疑似混入 0909 数据（量级不符）"
            )
            assert b["low"] >= 98.0, f"0908 的 low={b['low']} 异常"
        elif day == "2026-09-09":
            assert b["high"] >= 3930.0, (
                f"0909 的 90min high={b['high']} 疑似混入 0908 数据（量级不符）"
            )


def test_short_day_does_not_contaminate_next_day(tmp_path):
    """首日缺 1 根时，次日数据不得被拖入前一组。

    修复前：17 根 //3 = 5 组，组2 = 0908(14:00,14:30) + 0909(10:00) → 跨日。
    """
    db = _mkdb(tmp_path)
    _insert_30min(db, SHORT_DAY_0908 + FULL_DAY_0909)
    m = _load("update_index_klines_intraday.py", db)
    m.synthesize_90min_klines("sh000001", dry_run=False)
    out = _read_90min(db)

    d0908 = [b for b in out if b["bar_time"].startswith("2026-09-08")]
    d0909 = [b for b in out if b["bar_time"].startswith("2026-09-09")]
    # 0908 有 8 根 → 2 根（末2根不足3，跳过）；0909 完整 → 3 根
    assert len(d0908) == 2, f"0908 应为 2 根（8//3），实际 {len(d0908)}"
    assert len(d0909) == 3, f"0909 应为 3 根，实际 {len(d0909)}"

    # 关键：0908 末根的 close 必须是 0908 自己的，不能是 0909 的价
    # 8 根按 i=0(10:00,10:30,11:00) 和 i=3(11:30,13:00,13:30) 切 → 末根 13:30
    assert d0908[-1]["bar_time"] == "2026-09-08 13:30", \
        f"0908 末根应为 13:30，实际 {d0908[-1]['bar_time']}"
    assert d0908[-1]["close"] < 200, "0908 末根 close 不得是 0909 的价位"
    assert d0908[-1]["close"] == pytest.approx(103.0), "末根收盘取 13:30 的 close"

    # 0909 首根必须完整由 0909 三根构成
    assert d0909[0]["bar_time"] == "2026-09-09 11:00"
    assert d0909[0]["open"] == pytest.approx(3943.92)
    assert d0909[0]["high"] == pytest.approx(3951.07)


def test_no_cross_session_fabrication(tmp_path):
    """组内首末时刻跨度不应超过 90 分钟 + 午休（实际实现是日内连续3根）。

    这里校验更本质的一点：同一组的 low 不得低于该时段外的最低点，
    即 0909 第2根（11:30+13:00+13:30）的 low 必须是这三根的最小值。
    """
    db = _mkdb(tmp_path)
    _insert_30min(db, FULL_DAY_0909)
    m = _load("pre_fetch_index_klines.py", db)
    m.synthesize_90min_klines("sh000001", dry_run=False)
    out = _read_90min(db)

    assert len(out) == 3, "完整日应有 3 根"
    b0, b1, b2 = out
    # 组0 = 10:00,10:30,11:00
    assert b0["bar_time"] == "2026-09-09 11:00"
    assert b0["open"] == pytest.approx(3943.92), "开盘取首根"
    assert b0["close"] == pytest.approx(3949.64), "收盘取末根"
    assert b0["high"] == pytest.approx(3951.07), "high=max(3945.12,3951.07,3949.64)"
    assert b0["low"] == pytest.approx(3935.64), "low=min"
    # 组1 = 11:30,13:00,13:30
    assert b1["bar_time"] == "2026-09-09 13:30"
    assert b1["high"] == pytest.approx(3956.61)
    assert b1["low"] == pytest.approx(3948.56)
    # 组2 = 14:00,14:30,15:00
    assert b2["bar_time"] == "2026-09-09 15:00"
    assert b2["close"] == pytest.approx(3951.50)


def test_partial_trailing_day_skipped(tmp_path):
    """当日根数 <3 时跳过该日（不产出残缺 bar）。"""
    db = _mkdb(tmp_path)
    _insert_30min(db, FULL_DAY_0909 + [
        ("2026-09-10 10:00", 1.0, 2.0, 0.5, 1.5),
        ("2026-09-10 10:30", 1.5, 2.5, 1.0, 2.0),
    ])
    m = _load("update_index_klines_intraday.py", db)
    m.synthesize_90min_klines("sh000001", dry_run=False)
    out = _read_90min(db)
    days = {b["bar_time"][:10] for b in out}
    assert "2026-09-10" not in days, "不足3根的当日应跳过"
    assert len([b for b in out if b["bar_time"].startswith("2026-09-09")]) == 3


def test_macd_computed(tmp_path):
    """合成后应带 MACD（dif/dea/macd_hist）。"""
    db = _mkdb(tmp_path)
    bars = []
    # 造 40 个完整交易日 → 120 根 90min，足够算 MACD
    for d in range(40):
        day = f"2026-06-{d+1:02d}"
        for i, t in enumerate(["10:00", "10:30", "11:00", "11:30",
                               "13:00", "13:30", "14:00", "14:30", "15:00"]):
            px = 100.0 + d * 0.5 + i * 0.1
            bars.append((f"{day} {t}", px, px + 1, px - 1, px + 0.5))
    _insert_30min(db, bars)
    m = _load("update_index_klines_intraday.py", db)
    m.synthesize_90min_klines("sh000001", dry_run=False)
    out = _read_90min(db)
    assert len(out) == 120, f"40 日 × 3 = 120 根，实际 {len(out)}"
    with_macd = [b for b in out if b["dif"] is not None]
    assert with_macd, "应有 MACD 值"
    assert out[-1]["macd_hist"] is not None, "末根应有 macd_hist"


def test_idempotent(tmp_path):
    """重复运行结果一致（全量覆盖语义）。"""
    db = _mkdb(tmp_path)
    _insert_30min(db, FULL_DAY_0909 + PARTIAL_DAY_0910)
    m = _load("update_index_klines_intraday.py", db)
    m.synthesize_90min_klines("sh000001", dry_run=False)
    first = [(b["bar_time"], b["close"]) for b in _read_90min(db)]
    m.synthesize_90min_klines("sh000001", dry_run=False)
    second = [(b["bar_time"], b["close"]) for b in _read_90min(db)]
    assert first == second, "重复运行不应产生差异"
