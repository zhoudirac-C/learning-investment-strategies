"""板块分时强度：TDX 880 板块指数 60min K线 → 分时强弱标记与拉升定性。

提案：framework/proposals/2026-08-18-data-channel-intraday-sector-strength.md
回答「拉升发生在哪个时段、由哪类板块完成」——UP 2026-08-18 复盘核心一刀：
「下午拉升由银行完成 = 避险资金抬指数 = 诱多嫌疑」。

通道选型（2026-08-19 实测）：
- 东财板块分钟接口（akshare stock_board_industry_hist_min_em）本机被拒连
  （RemoteDisconnected），不可用；
- TDX 880 板块指数 60min K线可用（与 intraday_amount 同通道）。
- 880 代码↔板块名映射：通达信二级行业指数公开对照表
  （cnblogs.com/duan-qs/p/18000349）+ 2026-08-18 涨跌幅行为核验
  （防御阵营 银行+1.21/煤炭+1.53/石油+2.12 vs 进攻阵营 通信设备-1.6/软件服务-1.05，
  与当日「防御全天强势、进攻回落」盘面一致）。
  注意：早期探测曾误配 880491→半导体以外的行业，pct 指纹在 TDX/东财分类
  口径差异下不可靠，最终以公开对照表为准。

落盘：infra/data/sector_intraday/{yyyymmdd}.json（cron 15:40 前后，与 fund_flow
同窗口）；盲判数据包经 dataset._load_sector_intraday 入包。
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

# 板块清单：防御/进攻二分（UP 8-18：防御拉升=避险、进攻拉升=做多）。
# 医药归防御：UP 近期框架把医药放在「回踩期过渡方向」（与防御同角色）。
SECTORS: dict[str, dict[str, str]] = {
    "880471": {"name": "银行", "camp": "防御"},
    "880301": {"name": "煤炭", "camp": "防御"},
    "880310": {"name": "石油", "camp": "防御"},
    "880305": {"name": "电力", "camp": "防御"},
    "880360": {"name": "农林牧渔", "camp": "防御"},
    "880398": {"name": "医疗保健", "camp": "防御"},
    "880491": {"name": "半导体", "camp": "进攻"},
    "880490": {"name": "通信设备", "camp": "进攻"},
    "880493": {"name": "软件服务", "camp": "进攻"},
    "880492": {"name": "元器件", "camp": "进攻"},
    "880472": {"name": "证券", "camp": "进攻"},
}

# 标记阈值（初始标定，随样本积累校准）
_PM_STRONG = 0.4   # 午后涨跌幅 ≥ +0.4% → 午后走强
_PM_WEAK = -0.4    # 午后涨跌幅 ≤ -0.4% → 午后转弱
_LEAD_COUNT_GAP = 1  # 真强势只数之差 > 1（即 ≥2）才判阵营主导

DATA_ROOT = Path("infra/data/sector_intraday")


def _bar_day(bar: dict) -> str:
    return str(bar.get("datetime", ""))[:10]


def _split_day(bars: list[dict]) -> tuple[list[dict], list[dict]]:
    """按最新一天切分：(之前交易日 bars, 最新日 bars)。"""
    if not bars:
        return [], []
    day = _bar_day(bars[-1])
    today = [b for b in bars if _bar_day(b) == day]
    prev = [b for b in bars if _bar_day(b) < day]
    return prev, today


def _am_close(today: list[dict]) -> dict | None:
    """上午收盘 bar（11:30）；缺失时退化为当日首根。"""
    for b in today:
        if str(b.get("datetime", ""))[11:16] == "11:30":
            return b
    return today[0] if today else None


def _marker(am_pct: float, pm_pct: float) -> str:
    """强弱性质标记（UP 8-18 区分：拉升由谁完成 = 真强势，而非超跌反弹）。

    - 真强势：上午不弱 + 午后走强（全天强势且午后加强，做多/避险主动性买盘）；
    - 超跌反弹：上午深跌 + 午后回升（仅修复早盘跌幅，性质弱于真强势）；
    - 午后转弱 / 平稳。
    """
    if pm_pct >= _PM_STRONG:
        return "真强势" if am_pct >= 0 else "超跌反弹"
    if pm_pct <= _PM_WEAK:
        return "午后转弱"
    return "平稳"


def compute_sector_intraday(*, tdx=None, sectors: dict | None = None) -> dict | None:
    """拉 SECTORS 60min K线，计算全日/上午/下午涨跌幅、标记与阵营拉升定性。

    tdx 可注入 TdxMarket 兼容对象（测试用）；None 时自建 TdxMarket。
    任一板块拉取失败跳过该板块；全部失败/无当日数据返回 None。
    """
    sectors = sectors or SECTORS
    mkt = tdx
    if mkt is None:
        from qing_investment.tdx_market.market import TdxMarket
        mkt = TdxMarket()

    rows: list[dict] = []
    row_days: list[str] = []
    for code, meta in sectors.items():
        try:
            bars = mkt.get_kline(code, category="60min", count=16)
        except Exception:  # noqa: BLE001 - 单板块失败不阻断其余
            continue
        prev, today = _split_day(bars or [])
        if not prev or not today:
            continue
        # 收盘完整性守卫：最新日最后一根必须是 15:00 bar。盘前/盘中拉取时
        # 部分板块会带出当日 stub bar（close=昨收 → 0.0% 假行），且幂等文件名
        # 会挡住收盘后的真实落盘（2026-08-19 08:52 实测踩中）。
        if str(today[-1].get("datetime", ""))[11:16] != "15:00":
            continue
        prev_close = prev[-1].get("close")
        am = _am_close(today)
        last = today[-1]
        if not prev_close or not am or not am.get("close") or not last.get("close"):
            continue
        day_pct = round((last["close"] / prev_close - 1) * 100, 2)
        am_pct = round((am["close"] / prev_close - 1) * 100, 2)
        pm_pct = round((last["close"] / am["close"] - 1) * 100, 2)
        rows.append({"code": code, "name": meta["name"], "camp": meta["camp"],
                     "day_pct": day_pct, "am_pct": am_pct, "pm_pct": pm_pct,
                     "marker": _marker(am_pct, pm_pct)})
        row_days.append(_bar_day(last))
    if not rows:
        return None

    # 日期一致性：各板块最新交易日可能不一致（数据延迟/漏过守卫的 stub），
    # 只保留众数日期（并列取最新），避免同一文件混入不同交易日。
    counts = Counter(row_days)
    day = max(counts, key=lambda d: (counts[d], d))
    rows = [r for r, d in zip(rows, row_days) if d == day]

    # 阵营拉升定性：比「真强势」只数（午后走强且上午不弱），差 ≥2 才判主导——
    # 8-18 实证：下午全板块普升但防御 4 只真强势、进攻 0 只（均为超跌反弹），
    # 与 UP「下午拉升由银行（防御）完成」一致；单看午后均值会误判为均衡/进攻。
    strong: dict[str, int] = {}
    for r in rows:
        if r["marker"] == "真强势":
            strong[r["camp"]] = strong.get(r["camp"], 0) + 1
    pm_lead = "均衡"
    if strong:
        ranked = sorted(strong.items(), key=lambda kv: kv[1], reverse=True)
        if len(ranked) == 1 or ranked[0][1] - ranked[1][1] > _LEAD_COUNT_GAP:
            pm_lead = ranked[0][0]

    return {"date": day, "sectors": rows, "pm_lead_camp": pm_lead,
            "note": "pm_lead_camp=防御 → 避险资金抬指数（诱多嫌疑）；进攻 → 做多资金；"
                    "判据=真强势只数（上午不弱+午后走强），超跌反弹不计入"}


def save_sector_intraday(data: dict, root: Path | str = DATA_ROOT) -> Path:
    """落盘 {root}/{yyyymmdd}.json（幂等由调用方判断）。"""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{data['date'].replace('-', '')}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_sector_intraday(day: str, root: Path | str = DATA_ROOT) -> dict | None:
    """读落盘（day='YYYY-MM-DD'）；无文件/坏文件返回 None。"""
    path = Path(root) / f"{day.replace('-', '')}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
