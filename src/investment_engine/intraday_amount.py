"""分时量能：TDX 60min 四点曲线计算 + 落盘/读取（C1 分时腿）。

预估模型（2026-08-20 校准，提案 2026-08-20-fix-intraday-amount-calibration）：
旧版「预估全天 = 累计 × 240/已交易分钟」朴素外推，在 A 股首小时成交占比
40-50% 的分布下系统性高估近一倍（08-17~19 预估/实际偏差约 2 倍，「冲量滑落
（全天缩量）」3/3 天误触发）。现改为：用同通道近 20 个交易日 60min 历史计算
各时点「累计成交/全日成交」占比中位数，预估全天 = 时点累计 ÷ 该时点占比中位数；
输出校准残差（各历史日 10:30 校准预估 vs 当日实际的绝对偏差中位数）供阈值重定。
无历史样本时回退朴素外推，校准字段为 None。

键名与 dataset 现产出兼容：date/分时/开盘预估全天_亿/尾盘实际全天_亿/形态
一字不动（prompt 规则 9 引用「形态」字段）；环比前日_pct/占比中位数/校准残差_pct
为新增并列字段。形态判定沿用原阈值，但输入已是校准后预估。

与 dataset 版差异：day 不入参时由 TDX 返回数据推导（最新完整交易日），便于
收盘后 cron 落盘；也可显式传 day 重算历史日（校准只用该日之前的样本，防泄漏）。
TDX 不可达/当日数据不足时返回 None（与 dataset 现状一致）。
"""

from __future__ import annotations

import json
import statistics
from pathlib import Path

DEFAULT_DATA_DIR = Path("infra/data/intraday_amount")

_MINUTE_MAP = {"10:30": 60, "11:30": 120, "14:00": 180, "15:00": 240}
_HIST_DAYS = 20  # 校准样本窗口（近 20 个交易日）


def _day_points(bars: list[dict], out: dict[str, dict[str, float]]) -> None:
    """60min K 线累入 {交易日: {时点: 成交额(亿)}}（两市分时对齐后合并）。"""
    for r in bars:
        dt = str(r.get("datetime", ""))
        day, hm = dt[:10], dt[11:16]
        if hm not in _MINUTE_MAP:
            continue
        slot = out.setdefault(day, {})
        slot[hm] = slot.get(hm, 0.0) + (r.get("amount") or 0) / 1e8


def _cum_curve(pts: dict[str, float]) -> list[float]:
    """{时点: 成交额} → 四点累计曲线（按 _MINUTE_MAP 顺序）。"""
    cum, out = 0.0, []
    for hm in _MINUTE_MAP:
        cum += pts[hm]
        out.append(cum)
    return out


def compute_intraday_amount(tdx=None, day: str | None = None) -> dict | None:
    """用 TDX 拉上证+深证 60min 成交额，构建盘中量能形态。

    tdx 可注入 TdxMarket 兼容对象（测试用）；None 时自建 TdxMarket。
    day 缺省取数据最新完整交易日；显式传入时按该日重算（校准只用更早交易日）。
    返回 None（TDX 拉取失败/完整交易日不足）或：
    {date, 分时[{时点,累计_亿,预估全天_亿}], 开盘预估全天_亿, 尾盘实际全天_亿, 形态,
     环比前日_pct, 占比中位数, 校准残差_pct}。
    """
    try:
        mkt = tdx
        if mkt is None:
            from qing_investment.tdx_market import TdxMarket
            mkt = TdxMarket()
        count = (_HIST_DAYS + 1) * 4
        sh = mkt.get_kline("sh000001", "60min", count=count)
        sz = mkt.get_kline("sz399001", "60min", count=count)
    except Exception:
        return None
    if not sh or not sz:
        return None
    per_day: dict[str, dict[str, float]] = {}
    _day_points(sh, per_day)
    _day_points(sz, per_day)
    days = sorted(d for d, pts in per_day.items() if len(pts) == len(_MINUTE_MAP))
    if day is None:
        if not days:
            return None
        day = days[-1]
    elif day not in days:
        return None
    target_cum = _cum_curve(per_day[day])
    prior_cums = [(d, _cum_curve(per_day[d])) for d in days if d < day]
    prior_cums = prior_cums[-_HIST_DAYS:]

    hms = list(_MINUTE_MAP)
    samples = {hm: [] for hm in hms}
    for _, c in prior_cums:
        if c[-1] <= 0:
            continue
        for i, hm in enumerate(hms):
            samples[hm].append(c[i] / c[-1])
    ratio_med = ({hm: round(statistics.median(samples[hm]), 3) for hm in hms}
                 if samples[hms[0]] else None)

    rows = []
    for i, hm in enumerate(hms):
        cum = target_cum[i]
        if ratio_med:
            est = cum / ratio_med[hm]
        else:  # 无历史样本：回退 ×240/已交易分钟 朴素外推
            est = cum * (240.0 / _MINUTE_MAP[hm])
        rows.append({"时点": hm, "累计_亿": round(cum, 0), "预估全天_亿": round(est, 0)})

    residual = None
    if ratio_med:
        devs = [abs(c[0] / ratio_med["10:30"] / c[-1] - 1) * 100
                for _, c in prior_cums if c[-1] > 0]
        residual = round(statistics.median(devs), 1) if devs else None
    huanbi = None
    if prior_cums and prior_cums[-1][1][-1] > 0:
        huanbi = round((target_cum[-1] / prior_cums[-1][1][-1] - 1) * 100, 1)

    open_est = rows[0]["预估全天_亿"]
    close_actual = rows[-1]["累计_亿"]
    if open_est > close_actual * 1.2:
        shape = "冲量滑落（全天缩量）"
    elif close_actual > open_est * 1.1:
        shape = "逐级放大（健康放量）"
    else:
        shape = "平量"
    return {"date": day, "分时": rows, "开盘预估全天_亿": open_est,
            "尾盘实际全天_亿": round(close_actual, 0), "形态": shape,
            "环比前日_pct": huanbi, "占比中位数": ratio_med,
            "校准残差_pct": residual}


def load_intraday_amount(day: str,
                         data_dir: Path = DEFAULT_DATA_DIR) -> dict | None:
    """读 <data_dir>/<yyyymmdd>.json；day 为 YYYY-MM-DD，不存在返回 None。"""
    path = Path(data_dir) / f"{day.replace('-', '')}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def save_intraday_amount(day: str, payload: dict,
                         data_dir: Path = DEFAULT_DATA_DIR) -> Path:
    """写 <data_dir>/<yyyymmdd>.json；day 为 YYYY-MM-DD。"""
    out_dir = Path(data_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{day.replace('-', '')}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n",
                    encoding="utf-8")
    return path
