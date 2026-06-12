"""SQLite K线缓存层 —— 日K数据本地存储，支持 WAL 模式多读单写。

设计目标：
- 开盘前预拉取日K写入 SQLite，全天各组件共享
- poll 层和 Agent 层优先读本地，将网络 I/O 转为本地 I/O
- 纯文件数据库，无 Docker/服务依赖，适合云端部署
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# ── 路径配置 ──
_DEFAULT_DB_PATH = (
    Path(__file__).resolve().parents[2] / "infra" / "data" / "kline_cache.db"
)

_CN_TZ = timezone(timedelta(hours=8))


# ── 连接管理 ──
@contextmanager
def _get_conn(write: bool = False, db_path: Path | None = None):
    """获取 SQLite 连接，自动配置 WAL 模式和超时。

    Args:
        write: True 表示写入模式（pre_fetch 使用），False 表示只读模式（poll/Agent 使用）
        db_path: 自定义数据库路径，默认使用 infra/data/kline_cache.db
    """
    path = db_path or _DEFAULT_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)

    # timeout=30: 等待锁释放的最长时间（秒）
    conn = sqlite3.connect(str(path), timeout=30.0)
    conn.row_factory = sqlite3.Row

    # WAL 模式：支持多读单写，适合"pre_fetch 写 + poll/Agent 读"场景
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA temp_store=MEMORY;")

    if not write:
        # poll/Agent 只读时启用 query_only，防止意外写入
        conn.execute("PRAGMA query_only=ON;")

    try:
        yield conn
    finally:
        conn.close()


# ── 初始化 ──
def init_db(db_path: Path | None = None) -> None:
    """初始化 SQLite 表结构（首次运行时自动创建，幂等）。"""
    with _get_conn(write=True, db_path=db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS stocks_kline (
                code TEXT NOT NULL,
                trade_date TEXT NOT NULL,
                open REAL,
                high REAL,
                low REAL,
                close REAL,
                volume REAL,
                turnover REAL,
                amplitude REAL,
                pct_change REAL,
                updated_at TEXT,
                PRIMARY KEY (code, trade_date)
            );

            CREATE INDEX IF NOT EXISTS idx_kline_code_date
                ON stocks_kline(code, trade_date);

            CREATE TABLE IF NOT EXISTS kline_meta (
                key TEXT PRIMARY KEY,
                value TEXT
            );
            """
        )
        conn.commit()


# ── 写入 ──
def save_klines(
    code: str,
    klines: list[dict[str, Any]],
    db_path: Path | None = None,
) -> None:
    """保存单只股票的日K线（覆盖写入该股票的历史数据）。

    Args:
        code: 股票代码，如 "600378"
        klines: K线数据列表，每项为 dict，至少包含 date, open, high, low, close
        db_path: 自定义数据库路径
    """
    with _get_conn(write=True, db_path=db_path) as conn:
        # 先删除该股票旧数据，再插入新数据（覆盖策略）
        conn.execute("DELETE FROM stocks_kline WHERE code = ?", (code,))

        if klines:
            conn.executemany(
                """INSERT INTO stocks_kline
                    (code, trade_date, open, high, low, close,
                     volume, turnover, amplitude, pct_change, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        code,
                        str(d.get("date", d.get("trade_date", ""))),
                        float(d.get("open", 0)) if d.get("open") is not None else None,
                        float(d.get("high", 0)) if d.get("high") is not None else None,
                        float(d.get("low", 0)) if d.get("low") is not None else None,
                        float(d.get("close", 0)) if d.get("close") is not None else None,
                        float(d.get("volume", 0)) if d.get("volume") is not None else None,
                        float(d.get("turnover", 0)) if d.get("turnover") is not None else None,
                        float(d.get("amplitude", 0)) if d.get("amplitude") is not None else None,
                        float(d.get("pct_change", 0)) if d.get("pct_change") is not None else None,
                        d.get("updated_at", datetime.now(_CN_TZ).isoformat()),
                    )
                    for d in klines
                ],
            )
        conn.commit()


# ── 读取 ──
def get_klines(
    code: str,
    days: int = 30,
    db_path: Path | None = None,
) -> list[dict[str, Any]]:
    """读取最近 N 日 K线，按 trade_date 升序（旧→新）返回。

    返回格式与 API 原始格式兼容：
    - date: 交易日期（兼容 API 的 date 字段）
    - open/high/low/close/volume/turnover/amplitude/pct_change

    Args:
        code: 股票代码
        days: 读取最近多少个交易日
        db_path: 自定义数据库路径

    Returns:
        K线数据列表，正序排列。无数据时返回空列表。
    """
    with _get_conn(write=False, db_path=db_path) as conn:
        cursor = conn.execute(
            """SELECT * FROM stocks_kline
                WHERE code = ?
                ORDER BY trade_date DESC
                LIMIT ?""",
            (code, days),
        )
        rows = cursor.fetchall()

        result = []
        for row in reversed(rows):
            d = dict(row)
            # 字段名兼容性映射：trade_date → date（与 API 返回格式一致）
            if "trade_date" in d:
                d["date"] = d.pop("trade_date")
            result.append(d)
        return result


def get_ma(
    code: str,
    days: int = 20,
    db_path: Path | None = None,
) -> float | None:
    """计算最近 N 日收盘价的移动平均。

    Args:
        code: 股票代码
        days: 均线周期
        db_path: 自定义数据库路径

    Returns:
        均线值，K线不足时返回 None。
    """
    klines = get_klines(code, days=days, db_path=db_path)
    if len(klines) < days:
        return None
    return sum(d["close"] for d in klines) / days


def get_latest_price(
    code: str,
    db_path: Path | None = None,
) -> dict[str, Any] | None:
    """获取某只股票最新一根 K线数据。

    Returns:
        最新 K线 dict，无数据时返回 None。
    """
    klines = get_klines(code, days=1, db_path=db_path)
    return klines[-1] if klines else None


# ── 预拉取标记 ──
def is_cache_ready(date: str | None = None, db_path: Path | None = None) -> bool:
    """检查某交易日 K线是否已预拉取完成。

    Args:
        date: 日期字符串 "YYYY-MM-DD"，默认今天
        db_path: 自定义数据库路径

    Returns:
        True 表示已预拉取，False 表示未预拉取或数据不存在。
    """
    if date is None:
        date = datetime.now(_CN_TZ).strftime("%Y-%m-%d")

    with _get_conn(write=False, db_path=db_path) as conn:
        cursor = conn.execute(
            "SELECT value FROM kline_meta WHERE key = ?",
            (f"ready_{date}",),
        )
        row = cursor.fetchone()
        return row is not None


def mark_cache_ready(
    date: str | None = None,
    db_path: Path | None = None,
) -> None:
    """标记某交易日预拉取已完成。

    Args:
        date: 日期字符串 "YYYY-MM-DD"，默认今天
        db_path: 自定义数据库路径
    """
    if date is None:
        date = datetime.now(_CN_TZ).strftime("%Y-%m-%d")

    with _get_conn(write=True, db_path=db_path) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO kline_meta (key, value) VALUES (?, ?)",
            (f"ready_{date}", date),
        )
        conn.commit()


def clear_cache_ready(
    date: str | None = None,
    db_path: Path | None = None,
) -> None:
    """清除某交易日的预拉取标记（用于重试或测试）。"""
    if date is None:
        date = datetime.now(_CN_TZ).strftime("%Y-%m-%d")

    with _get_conn(write=True, db_path=db_path) as conn:
        conn.execute(
            "DELETE FROM kline_meta WHERE key = ?",
            (f"ready_{date}",),
        )
        conn.commit()


# ── 诊断工具 ──
def get_cache_stats(db_path: Path | None = None) -> dict[str, Any]:
    """获取缓存统计信息（用于调试和监控）。"""
    with _get_conn(write=False, db_path=db_path) as conn:
        # 总股票数
        cursor = conn.execute(
            "SELECT COUNT(DISTINCT code) as stock_count FROM stocks_kline"
        )
        stock_count = cursor.fetchone()["stock_count"]

        # 总 K线数
        cursor = conn.execute("SELECT COUNT(*) as kline_count FROM stocks_kline")
        kline_count = cursor.fetchone()["kline_count"]

        # 指数K线数
        cursor = conn.execute("SELECT COUNT(*) as idx_count FROM index_klines")
        idx_kline_count = cursor.fetchone()["idx_count"]

        # 最近更新日期
        cursor = conn.execute(
            "SELECT MAX(updated_at) as last_update FROM stocks_kline"
        )
        last_update = cursor.fetchone()["last_update"]

        # 预拉取标记
        cursor = conn.execute("SELECT key, value FROM kline_meta")
        meta = {row["key"]: row["value"] for row in cursor.fetchall()}

        return {
            "stock_count": stock_count,
            "kline_count": kline_count,
            "index_kline_count": idx_kline_count,
            "last_update": last_update,
            "meta": meta,
        }


# ── 指数多级别K线读取 ──

def get_index_klines(
    code: str,
    timeframe: str = "daily",
    bars: int = 100,
    db_path: Path | None = None,
) -> list[dict[str, Any]]:
    """读取指数最近 N 根 K 线（含 MACD），按时间升序。

    Args:
        code: 指数代码，如 'sh000001', 'sh000985', 'sz399001', 'sz399006'
        timeframe: 周期，'30min' / '60min' / '120min' / 'daily'
        bars: 读取最近多少根
        db_path: 自定义数据库路径

    Returns:
        K线数据列表，正序排列（旧→新）。字段含 dif/dea/macd_hist。
    """
    with _get_conn(write=False, db_path=db_path) as conn:
        cursor = conn.execute(
            """SELECT * FROM index_klines
                WHERE code = ? AND timeframe = ?
                ORDER BY bar_time DESC
                LIMIT ?""",
            (code, timeframe, bars),
        )
        rows = cursor.fetchall()

        result = []
        for row in reversed(rows):
            result.append(dict(row))
        return result


def get_index_macd_snapshot(
    code: str,
    db_path: Path | None = None,
) -> dict[str, Any]:
    """获取某一指数所有周期的 MACD 快照。

    返回每个周期的最新一根 K 线的 MACD 状态，
    以及对最近 N 根 K 线的简单趋势判断。

    Args:
        code: 指数代码
        db_path: 自定义数据库路径

    Returns:
        {
            "code": "sh000001",
            "timeframes": {
                "daily": {
                    "latest_bar": "2026-06-12",
                    "close": 4035.48,
                    "dif": -27.99, "dea": -17.28, "macd_hist": -21.41,
                    "trend": "绿柱缩短" | "绿柱放大" | "红柱缩短" | "红柱放大",
                    "dif_cross": "下穿" | "上穿" | null  # 最近3根是否出现DIF/DEA交叉
                },
                ...
            }
        }
    """
    result = {"code": code, "timeframes": {}}

    with _get_conn(write=False, db_path=db_path) as conn:
        for tf in ["daily", "120min", "90min", "60min", "30min"]:
            # 取最近5根（含MACD）
            cursor = conn.execute(
                """SELECT * FROM index_klines
                    WHERE code = ? AND timeframe = ?
                    ORDER BY bar_time DESC
                    LIMIT 5""",
                (code, tf),
            )
            rows = cursor.fetchall()
            if not rows:
                continue

            # rows 是降序（新→旧）
            latest = dict(rows[0])
            tf_data = {
                "latest_bar": latest["bar_time"],
                "close": latest["close"],
                "dif": latest["dif"],
                "dea": latest["dea"],
                "macd_hist": latest["macd_hist"],
            }

            # MACD柱趋势（最近3根）
            if len(rows) >= 2:
                hist_now = rows[0]["macd_hist"]
                hist_prev = rows[1]["macd_hist"]
                if hist_now is not None and hist_prev is not None:
                    if hist_now > hist_prev:
                        tf_data["hist_trend"] = "绿柱缩短" if hist_now < 0 else "红柱放大"
                    elif hist_now < hist_prev:
                        tf_data["hist_trend"] = "绿柱放大" if hist_now < 0 else "红柱缩短"
                    else:
                        tf_data["hist_trend"] = "持平"

            # DIF/DEA 交叉检测（最近3根）
            if len(rows) >= 2:
                dif_now = rows[0]["dif"]
                dea_now = rows[0]["dea"]
                dif_prev = rows[1]["dif"]
                dea_prev = rows[1]["dea"]
                if all(v is not None for v in [dif_now, dea_now, dif_prev, dea_prev]):
                    if dif_prev <= dea_prev and dif_now > dea_now:
                        tf_data["dif_cross"] = "金叉(DIF上穿DEA)"
                    elif dif_prev >= dea_prev and dif_now < dea_now:
                        tf_data["dif_cross"] = "死叉(DIF下穿DEA)"

            result["timeframes"][tf] = tf_data

    return result


# ── MACD分析投喂LLM ──

def format_multi_tf_macd_report(
    codes: list[str] | None = None,
    bars: int = 12,
    db_path: Path | None = None,
) -> str:
    """生成多指数 × 多级别的 MACD 分析报告（精简版，直接喂给LLM）。"""
    import sqlite3

    if codes is None:
        codes = ["sh000985", "sh000001"]
    index_names = {
        "sh000001": "上证指数", "sh000985": "中证全指",
    }
    tf_order = ["daily", "120min", "90min", "60min", "30min"]
    tf_names = {"daily": "日线", "120min": "120分钟", "90min": "90分钟", "60min": "60分钟", "30min": "30分钟"}
    now_str = datetime.now(_CN_TZ).strftime('%m-%d %H:%M')

    conn = sqlite3.connect(str(db_path or _DEFAULT_DB_PATH))
    conn.row_factory = sqlite3.Row

    lines = [f"📊 多级别MACD快照（{now_str}）", ""]

    # 精简快照：只一行一个指数，每个级别一个数字
    for code in codes:
        name = index_names.get(code, code)
        vals = []
        for tf in tf_order:
            row = conn.execute(
                "SELECT close, dif, dea, macd_hist FROM index_klines WHERE code=? AND timeframe=? ORDER BY bar_time DESC LIMIT 1",
                (code, tf)
            ).fetchone()
            if row and row["dif"] is not None:
                h = row["macd_hist"]
                tf_short = {"daily": "日", "120min": "120", "90min": "90", "60min": "60", "30min": "30"}.get(tf, tf)
                arrow = "↑" if h and h > 0 else "↓" if h and h < 0 else "—"
                vals.append(f"{tf_short}{arrow}({row['dif']:.0f})")
        lines.append(f"  {name}: {' '.join(vals)}")

    # 详情段：按 codes 列表中第一个指数展示（而非硬编码 sh000985）
    code_primary = codes[0] if codes else "sh000985"
    primary_name = index_names.get(code_primary, code_primary)
    lines.append(f"\n📈 {primary_name}日线细节:")
    rows = conn.execute(
        "SELECT bar_time, close, dif, dea, macd_hist FROM index_klines WHERE code=? AND timeframe='daily' ORDER BY bar_time DESC LIMIT 5",
        (code_primary,)
    ).fetchall()
    for r in reversed(rows):
        h = r["macd_hist"]
        color = "🔴" if h and h > 0 else "🟢" if h and h < 0 else "⚪"
        lines.append(f"  {r['bar_time'][-5:]} C:{r['close']:.0f} DIF:{r['dif']:.0f} DEA:{r['dea']:.0f} 柱:{h:.0f} {color}")

    # 60分钟最近5根（同样跟第一个指数）
    lines.append(f"\n⏱️ {primary_name}60分钟细节:")
    rows = conn.execute(
        "SELECT bar_time, close, dif, dea, macd_hist FROM index_klines WHERE code=? AND timeframe='60min' ORDER BY bar_time DESC LIMIT 5",
        (code_primary,)
    ).fetchall()
    for r in reversed(rows):
        h = r["macd_hist"]
        color = "🔴" if h and h > 0 else "🟢" if h and h < 0 else "⚪"
        lines.append(f"  {r['bar_time'][-5:]} C:{r['close']:.0f} DIF:{r['dif']:.0f} DEA:{r['dea']:.0f} 柱:{h:.0f} {color}")

    conn.close()
    return "\n".join(lines)


# ── 神奇九转（TD Sequential）──

def compute_td_sequential(klines: list[dict]) -> list[dict]:
    """计算神奇九转（TD Sequential）序列计数。

    TD Sell Setup（高9）：连续9根收盘价 > 4根前的收盘价 → 超买信号
    TD Buy Setup（低9）：连续9根收盘价 < 4根前的收盘价 → 超卖信号

    每根K线返回: {"td_type": "高"/"低"/"", "td_count": 0-9}
    """
    if len(klines) < 5:
        return [{"td_type": "", "td_count": 0} for _ in klines]

    result: list[dict] = []
    sell_count = 0
    buy_count = 0

    for i, k in enumerate(klines):
        if i < 4:
            result.append({"td_type": "", "td_count": 0})
            continue

        close_now = k["close"]
        close_4_ago = klines[i - 4]["close"]

        if close_now > close_4_ago:
            sell_count += 1
            buy_count = 0
            result.append({"td_type": "高", "td_count": min(sell_count, 9)})
        elif close_now < close_4_ago:
            buy_count += 1
            sell_count = 0
            result.append({"td_type": "低", "td_count": min(buy_count, 9)})
        else:
            sell_count = 0
            buy_count = 0
            result.append({"td_type": "", "td_count": 0})

    return result


def compute_td_report(
    code: str,
    timeframe: str = "daily",
    bars: int = 30,
    db_path: Path | None = None,
) -> str:
    """计算某指数某周期的九转序列并格式化输出。

    Args:
        code: 指数代码
        timeframe: 周期
        bars: 读取最近多少根K线用于计算
        db_path: 自定义数据库路径

    Returns:
        格式化的九转序列文本（含最新状态+最近信号列表）
    """
    import sqlite3

    conn = sqlite3.connect(str(db_path or _DEFAULT_DB_PATH))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM index_klines WHERE code=? AND timeframe=? ORDER BY bar_time ASC",
        (code, timeframe)
    ).fetchall()
    conn.close()

    if len(rows) < 5:
        return ""

    # 解析并计算
    klines = [{"close": r["close"], "bar_time": r["bar_time"], "high": r["high"], "low": r["low"]} for r in rows]
    td_seq = compute_td_sequential(klines)

    # 取最新和最近信号
    recent: list[str] = []
    completions: list[str] = []  # 已经完成的9次信号（历史事件）
    latest_status = ""
    last_cpl_type = ""  # 防重复：连续同方向的9只记第一次
    last_cpl_bar = ""
    for i in range(len(td_seq) - 1, max(len(td_seq) - bars - 1, -1), -1):
        if i < 0:
            break
        t = td_seq[i]
        k = klines[i]
        if t["td_count"] == 9:
            cpl_key = t["td_type"]
            if cpl_key != last_cpl_type:  # 方向变了才算新完成信号
                completions.append(f"  {k['bar_time']}  {'🔴高9' if t['td_type']=='高' else '🟢低9'}")
                last_cpl_type = cpl_key
                last_cpl_bar = k['bar_time']
            elif i == len(td_seq) - 1:
                # 最新一根还是同方向9→标记为延续而非新信号
                if completions:
                    completions[-1] = f"  {last_cpl_bar}  {'🔴高9(延续中)' if t['td_type']=='高' else '🟢低9(延续中)'}"
        elif t["td_count"] >= 8:
            recent.append(f"  {k['bar_time']}  {'🔴高'+str(t['td_count']):>6s}" if t["td_type"] == "高" else f"  {k['bar_time']}  {'🟢低'+str(t['td_count']):>6s}")
        if i == len(td_seq) - 1 and t["td_count"] > 0:
            latest_status = f"{'🔴高' if t['td_type']=='高' else '🟢低'}{t['td_count']}"

    lines = [f"神奇九转（{timeframe}）: 当前序列 {latest_status if latest_status else '无'}"]
    if completions:
        lines.append("  已完成信号:")
        lines.extend(completions)
    if recent:
        lines.append("  接近完成（8/9）:")
        lines.extend(recent)
    return "\n".join(lines)


# ── 斐波那契时间窗口 ──

def compute_fibonacci_time_report(
    code: str,
    db_path: Path | None = None,
) -> str:
    """计算主要指数距离斐波那契关键时间节点的距离。

    斐波那契关键时间窗口: 8, 13, 21, 34, 55 个交易日
    从最近一次明显的高点/低点或结构信号开始计数。

    Returns:
        格式化的斐波那契时间分析文本
    """
    import sqlite3

    conn = sqlite3.connect(str(db_path or _DEFAULT_DB_PATH))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT bar_time, close, dif, dea, macd_hist FROM index_klines WHERE code=? AND timeframe='daily' ORDER BY bar_time ASC",
        (code,)
    ).fetchall()
    conn.close()

    if len(rows) < 55:
        fib_report = f"数据不足55个交易日（当前{len(rows)}），无法计算完整斐波那契时间窗口"
        return fib_report

    closes = [r["close"] for r in rows]
    n = len(closes)

    # 检测近期关键高点（60日内的阶段高点）
    peaks = []
    half_window = 10
    for i in range(half_window, n - half_window):
        if all(closes[i] >= closes[i - j] for j in range(1, half_window + 1)) and \
           all(closes[i] >= closes[i + j] for j in range(1, half_window + 1)):
            peaks.append((rows[i]["bar_time"], closes[i], i))

    # 检测近期关键低点
    troughs = []
    for i in range(half_window, n - half_window):
        if all(closes[i] <= closes[i - j] for j in range(1, half_window + 1)) and \
           all(closes[i] <= closes[i + j] for j in range(1, half_window + 1)):
            troughs.append((rows[i]["bar_time"], closes[i], i))

    # 取最近3个高点/低点，检查距当前交易日的距离
    last_idx = n - 1
    fib_numbers = [8, 13, 21, 34, 55]

    lines = ["斐波那契时间窗口分析（日线）:", ""]

    # 从最近的高点算
    recent_peaks = [p for p in peaks if last_idx - p[2] <= 60]
    if recent_peaks:
        nearest_peak = recent_peaks[-1]
        days_from_peak = last_idx - nearest_peak[2]
        lines.append(f"  📈 最近高点: {nearest_peak[0]} ({nearest_peak[1]:.2f}) 距今 {days_from_peak} 交易日")
        for fb in fib_numbers:
            diff = abs(days_from_peak - fb)
            if diff <= 3:
                lines.append(f"    → 接近斐波那契数 {fb}（差{diff}天）⚠️")
        lines.append("")

    # 从最近的低点算
    recent_troughs = [t for t in troughs if last_idx - t[2] <= 60]
    if recent_troughs:
        nearest_trough = recent_troughs[-1]
        days_from_trough = last_idx - nearest_trough[2]
        lines.append(f"  📉 最近低点: {nearest_trough[0]} ({nearest_trough[1]:.2f}) 距今 {days_from_trough} 交易日")
        for fb in fib_numbers:
            diff = abs(days_from_trough - fb)
            if diff <= 3:
                lines.append(f"    → 接近斐波那契数 {fb}（差{diff}天）⚠️")
        lines.append("")

    if not recent_peaks and not recent_troughs:
        lines.append("  未检测到明显的高点/低点")

    return "\n".join(lines[:12])  # 限制输出长度
