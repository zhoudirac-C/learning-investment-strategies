# 板块情绪温度计（Board Sentiment Thermometer）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 全市场 90 个 THS 行业板块的日度情绪温度（0-100），识别"人声鼎沸"（>80，卖给散户区）与"无人问津+便宜"（<20 且估值低分位，逆向建仓区），每日复盘附温度榜、跨极值时推送飞书。

**Architecture:** 以 THS 板块指数日K（量能为骨架，akshare 通道已有）+ 东财 datacenter（龙虎榜/两融，实测通）为数据源；**绕开 push2 系**（本机 IP 被东财 push2/push2ex/push2his 风控断连，已实测）。估值 overlay 复用 `fetch_board_valuation.py` 的 datacenter 报表口径，对进入冰封区的板块惰性计算。温度 = 量能分位(0.40) + 龙虎榜散户化(0.25) + 融资热度(0.20) + 量价形态(0.15)。

**Tech Stack:** Python 3.11, akshare(THS), urllib(东财 datacenter), PyYAML, 项目现有 cron wrapper 模式（`~/.hermes/scripts/qing_*.py` 稳定入口 → repo scripts）

## Global Constraints

- **东财 push2 系全禁**（push2/push2ex/push2his/push2delay 本机被风控，RemoteDisconnected 实测）；只允许 datacenter-web.eastmoney.com 和 akshare-THS 通道
- datacenter 请求头固定 `{"User-Agent": "Mozilla/5.0", "Referer": "https://data.eastmoney.com/"}`，每次请求间隔 ≥1.5s
- akshare THS 接口间隔 ≥1.2s（沿用 fetch_board_klines.py 的 SLEEP_S）
- cron wrapper 放 `~/.hermes/scripts/`（qing_ 前缀，稳定入口勿改名），repo 侧脚本可自由演进
- 推送纪律（用户拍板）：板块温度跨 80/20 极值才单独推送；每日 17:00 复盘固定附温度榜（鼎沸 TOP5 + 冰封 TOP5）
- 估值口径纪律（a-share-valuation-data skill）：中位数汇总；PEG 除以增速百分数值；EPS1<=0 剔除；机构覆盖 <5 家剔除
- positions.yaml 等 gitignore 文件永不入库；`git add -A` 后 `git status --short` 检查
- 不产出无条件买卖指令，输出必须带数据时间戳

## 文件结构

| 文件 | 职责 |
|---|---|
| `scripts/fetch_all_board_klines.py`（新建） | 全量 90 个 THS 行业板块日K，落 `infra/data/board_klines_all/industry_<name>.json`；独立于产业链的 board_klines/ 互不干扰 |
| `scripts/fetch_billboard_daily.py`（新建） | 龙虎榜日更（datacenter RPT_DAILYBILLBOARD_DETAILSNEW + RPT_OPERATEDEPT_ACTIVE 席位明细），识别拉萨系散户席位，落 `infra/data/billboard/YYYY-MM-DD.json` |
| `scripts/fetch_margin_detail.py`（新建） | 个股融资余额（datacenter RPTA_WEB_RZRQ_GGMX），落 `infra/data/margin/YYYY-MM-DD.json` |
| `src/investment_engine/sentiment/__init__.py`（新建） | 包 |
| `src/investment_engine/sentiment/thermometer.py`（新建） | 温度计算核心：输入板块K线/龙虎榜/融资 → 每板块 4 分量+总分 |
| `src/investment_engine/sentiment/valuation_overlay.py`（新建） | 冰封区板块惰性估值：THS 成分股 → PE/PB 中位数+分位 → cheap/expensive 判定 |
| `src/investment_engine/sentiment/board_members.py`（新建） | THS 行业板块→成分股映射缓存（`infra/data/board_members.json`，7 天 TTL） |
| `scripts/board_sentiment_daily.py`（新建） | 日度编排：读数据 → 算温度 → 落 `infra/data/board_sentiment/YYYY-MM-DD.json` → 跨极值输出推送文本 |
| `~/.hermes/scripts/qing_board_sentiment.py`（新建 wrapper） | cron 稳定入口 |
| `scripts/calibrate_sentiment.py`（新建） | 历史校准：2024/9/24-10/8、2025/4/7 双锚点验证温度曲线 |
| `tests/investment_engine/sentiment/test_thermometer.py`（新建） | 温度计算单测 |
| `tests/investment_engine/sentiment/test_valuation_overlay.py`（新建） | 估值判定单测 |

---

### Task 1: 全量板块日K拉取脚本

**Files:**
- Create: `scripts/fetch_all_board_klines.py`
- Reference: `scripts/fetch_board_klines.py`（复用其 bar 格式与增量合并模式）

**Interfaces:**
- Produces: `infra/data/board_klines_all/industry_<板块名>.json`，bar = `{"date","open","high","low","close","volume","amount"}`（date 升序，与 fetch_board_klines.py 完全一致）
- Produces: `main() -> int`（0=至少一个板块成功；1=全部失败）

- [ ] **Step 1: 写脚本**

```python
#!/usr/bin/env python3
"""全量 THS 行业板块日K拉取（板块情绪温度计的数据层）。

akshare stock_board_industry_name_ths() 拿 90 个行业板块名单，
stock_board_industry_index_ths 逐个拉日K，增量合并落盘
infra/data/board_klines_all/industry_<name>.json。

首跑回填 500 自然日（≈340 交易日，够 250 日分位用）；之后每次拉 150 自然日增量。
与产业链的 infra/data/board_klines/ 目录隔离，互不影响。
手动: .venv/bin/python scripts/fetch_all_board_klines.py [--backfill] [--only 板块名 ...]
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "infra" / "data" / "board_klines_all"
SLEEP_S = 1.2
RETRY = 2


def list_boards() -> list[str]:
    import akshare as ak
    df = ak.stock_board_industry_name_ths()
    return [str(n) for n in df["name"].tolist()]


def out_path(board: str) -> Path:
    safe = board.replace("/", "_").replace("(", "_").replace(")", "_")
    return OUT_DIR / f"industry_{safe}.json"


def fetch_board(board: str, lookback_days: int) -> list[dict]:
    import akshare as ak
    end = dt.date.today()
    start = end - dt.timedelta(days=lookback_days)
    df = ak.stock_board_industry_index_ths(
        symbol=board, start_date=start.strftime("%Y%m%d"), end_date=end.strftime("%Y%m%d"))
    return [{"date": str(r["日期"])[:10], "open": float(r["开盘价"]),
             "high": float(r["最高价"]), "low": float(r["最低价"]),
             "close": float(r["收盘价"]), "volume": float(r["成交量"]),
             "amount": float(r["成交额"])} for _, r in df.iterrows()]


def merge(path: Path, new_bars: list[dict]) -> int:
    old = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    by_date = {b["date"]: b for b in old}
    for b in new_bars:
        by_date[b["date"]] = b
    merged = [by_date[k] for k in sorted(by_date)]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(merged, ensure_ascii=False), encoding="utf-8")
    return len(merged)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill", action="store_true", help="回填 500 自然日（首跑用）")
    ap.add_argument("--only", nargs="*", default=None)
    args = ap.parse_args()
    lookback = 500 if args.backfill else 150

    boards = list_boards()
    if args.only:
        boards = [b for b in boards if b in set(args.only)]
    print(f"板块数: {len(boards)}, lookback={lookback}d", file=sys.stderr)

    ok = fail = 0
    for i, b in enumerate(boards, 1):
        err = None
        for _ in range(RETRY + 1):
            try:
                bars = fetch_board(b, lookback)
                n = merge(out_path(b), bars)
                ok += 1
                print(f"[{i}/{len(boards)}] {b}: {n} bars", file=sys.stderr)
                break
            except Exception as e:  # noqa: BLE001
                err = e
                time.sleep(3)
        else:
            fail += 1
            print(f"[{i}/{len(boards)}] {b}: WARN {str(err)[:80]}", file=sys.stderr)
        time.sleep(SLEEP_S)
    print(f"完成: ok={ok} fail={fail}", file=sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: 单板块冒烟**

Run: `cd ~/learning-investment-strategies && .venv/bin/python scripts/fetch_all_board_klines.py --backfill --only 半导体`
Expected: stderr 打印 `板块数: 1` + `半导体: ~340 bars`，`infra/data/board_klines_all/industry_半导体.json` 存在且首条 date ≤ 2025-03

- [ ] **Step 3: 全量回填（约 90×(1.2s+拉取) ≈ 5-8 分钟）**

Run: `nohup .venv/bin/python scripts/fetch_all_board_klines.py --backfill > /tmp/board_klines_backfill.log 2>&1 &`，完成后 `grep 完成 /tmp/board_klines_backfill.log`，fail 应为 0 或个位数

- [ ] **Step 4: Commit**

`git add scripts/fetch_all_board_klines.py && git commit -m "sentiment: full THS industry board klines fetcher"`（infra/data/ 在 gitignore 内，确认 `git status --short` 无数据文件）

---

### Task 2: 温度计算核心（纯函数，TDD）

**Files:**
- Create: `src/investment_engine/sentiment/__init__.py`（空文件）
- Create: `src/investment_engine/sentiment/thermometer.py`
- Test: `tests/investment_engine/sentiment/test_thermometer.py`

**Interfaces:**
- Consumes: Task 1 的 bars 列表；Task 3/4 的板块级资金统计 dict
- Produces:
  - `percentile_rank(values: list[float], current: float) -> float`（0-100，current 在 values 中的分位）
  - `volume_component(bars: list[dict], window: int = 250) -> float`（量能分位：近5日均成交额 在 250 日 5日均额序列中的分位）
  - `pattern_component(bars: list[dict]) -> float`（量价形态 0-100：20 日涨幅 × 量能放大共振加分；天量滞涨/长上影加分到"热"；地量走平到低分）
  - `billboard_component(board_stats: dict | None) -> float`（0-100：散户席位买入占比 + 上榜频次归一化；无数据返回 None，权重让给量能）
  - `margin_component(margin_chg_20d: float | None, hist: list[float]) -> float`（融资 20 日变化率的历史分位）
  - `compute_temperature(bars, board_stats=None, margin_chg=None, margin_hist=[]) -> dict`，返回 `{"score": 0-100, "components": {...}, "zone": "hot"|"cold"|"neutral", "as_of": 最后bar日期}`
  - zone 判定：score ≥80 → "hot"；≤20 → "cold"；否则 "neutral"

- [ ] **Step 1: 写失败测试**

```python
# tests/investment_engine/sentiment/test_thermometer.py
from investment_engine.sentiment.thermometer import (
    compute_temperature, percentile_rank, volume_component)


def _bars(amounts, closes=None):
    closes = closes or [100.0] * len(amounts)
    return [{"date": f"2026-{i:04d}", "open": c, "high": c, "low": c,
             "close": c, "volume": 1.0, "amount": a}
            for i, (a, c) in enumerate(zip(amounts, closes))]


def test_percentile_rank_basic():
    assert percentile_rank([1, 2, 3, 4, 5], 5) == 100.0
    assert percentile_rank([1, 2, 3, 4, 5], 1) == 0.0
    assert 40 <= percentile_rank([1, 2, 3, 4, 5], 3) <= 60


def test_volume_component_cold():
    # 历史高量、当前地量 → 低分
    bars = _bars([100.0] * 245 + [5.0] * 5)
    assert volume_component(bars) <= 10


def test_volume_component_hot():
    bars = _bars([10.0] * 245 + [200.0] * 5)
    assert volume_component(bars) >= 90


def test_compute_temperature_zones():
    cold = compute_temperature(_bars([100.0] * 245 + [5.0] * 5))
    assert cold["zone"] == "cold"
    hot = compute_temperature(_bars([10.0] * 245 + [200.0] * 5),
                              board_stats={"retail_buy_ratio": 0.9, "board_hits_20d": 15})
    assert hot["zone"] == "hot"
    assert set(hot["components"]) >= {"volume", "pattern", "billboard"}


def test_compute_temperature_missing_optional_data():
    # 无龙虎榜/融资数据时权重自动归一化到可用分量，不报错
    r = compute_temperature(_bars([10.0] * 250))
    assert 0 <= r["score"] <= 100
    assert r["components"]["billboard"] is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd ~/learning-investment-strategies && .venv/bin/python -m pytest tests/investment_engine/sentiment/test_thermometer.py -v`
Expected: FAIL（ModuleNotFoundError）

- [ ] **Step 3: 实现 thermometer.py**

```python
"""板块情绪温度计核心（纯函数，无 IO）。

温度 = 0.40×量能分位 + 0.25×龙虎榜散户化 + 0.20×融资热度 + 0.15×量价形态。
可选分量缺失时，权重在可用分量间按比例重归一化。
"""
from __future__ import annotations

WEIGHTS = {"volume": 0.40, "billboard": 0.25, "margin": 0.20, "pattern": 0.15}
HOT, COLD = 80.0, 20.0


def percentile_rank(values: list[float], current: float) -> float:
    vals = sorted(v for v in values if v is not None)
    if not vals:
        return 50.0
    below = sum(1 for v in vals if v < current)
    return round(100.0 * below / len(vals), 1)


def _ma5_amounts(bars: list[dict]) -> list[float]:
    amts = [b["amount"] for b in bars]
    return [sum(amts[i - 4:i + 1]) / 5 for i in range(4, len(amts))]


def volume_component(bars: list[dict], window: int = 250) -> float:
    ma5 = _ma5_amounts(bars)[-window:]
    if len(ma5) < 20:
        return 50.0
    return percentile_rank(ma5[:-1], ma5[-1])


def pattern_component(bars: list[dict]) -> float:
    """量价形态：涨+放量=热；天量滞涨(出货特征)=更热；跌+缩量=冷。"""
    if len(bars) < 25:
        return 50.0
    closes = [b["close"] for b in bars]
    amts = [b["amount"] for b in bars]
    ret20 = (closes[-1] / closes[-21] - 1) * 100
    amt_ratio = (sum(amts[-5:]) / 5) / max(sum(amts[-25:-5]) / 20, 1e-9)
    score = 50.0 + ret20 * 2.0           # 20日涨幅每 +1% → +2 分
    score += min(max((amt_ratio - 1) * 40, -25), 25)  # 放量±
    # 天量滞涨：5 日均额 > 25 日均额 1.8 倍 且近 5 日涨幅 <1% → 出货特征，直接热
    if amt_ratio > 1.8 and abs((closes[-1] / closes[-6] - 1) * 100) < 1.0:
        score = max(score, 85.0)
    return max(0.0, min(100.0, score))


def billboard_component(board_stats: dict | None) -> float | None:
    """board_stats: {"retail_buy_ratio": 0-1, "board_hits_20d": int}"""
    if not board_stats:
        return None
    ratio = board_stats.get("retail_buy_ratio", 0.0)
    hits = board_stats.get("board_hits_20d", 0)
    return min(100.0, ratio * 70 + min(hits, 15) / 15 * 30)


def margin_component(margin_chg_20d: float | None, hist: list[float]) -> float | None:
    if margin_chg_20d is None or len(hist) < 60:
        return None
    return percentile_rank(hist, margin_chg_20d)


def compute_temperature(bars: list[dict], board_stats: dict | None = None,
                        margin_chg: float | None = None,
                        margin_hist: list[float] | None = None) -> dict:
    comps: dict[str, float | None] = {
        "volume": volume_component(bars),
        "pattern": pattern_component(bars),
        "billboard": billboard_component(board_stats),
        "margin": margin_component(margin_chg, margin_hist or []),
    }
    avail = {k: v for k, v in comps.items() if v is not None}
    wsum = sum(WEIGHTS[k] for k in avail)
    score = sum(avail[k] * WEIGHTS[k] for k in avail) / wsum if wsum else 50.0
    score = round(score, 1)
    zone = "hot" if score >= HOT else ("cold" if score <= COLD else "neutral")
    return {"score": score, "components": comps, "zone": zone,
            "as_of": bars[-1]["date"] if bars else None}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/investment_engine/sentiment/test_thermometer.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

`git add src/investment_engine/sentiment/ tests/investment_engine/sentiment/ && git commit -m "sentiment: thermometer core (volume/pattern/billboard/margin components)"`

---

### Task 3: 龙虎榜日更 + 散户席位识别

**Files:**
- Create: `scripts/fetch_billboard_daily.py`
- Create: `src/investment_engine/sentiment/board_members.py`

**Interfaces:**
- Consumes: datacenter `RPT_DAILYBILLBOARD_DETAILSNEW`（日榜汇总，含 SECURITY_CODE/EXPLAIN）+ `RPT_BILLBOARD_DAILYDETAILSBUY`（营业部明细，含 OPERATEDEPT_NAME/BUY）
- Consumes: `board_members.get_stock_board_map() -> dict[str, str]`（6位代码 → THS 行业板块名，缓存 `infra/data/board_members.json`，7 天 TTL，逐板块 `ak.stock_board_industry_cons_ths(symbol=板块名)` 聚合）
- Produces: `infra/data/billboard/YYYY-MM-DD.json` = `{板块名: {"retail_buy_ratio": 0-1, "board_hits_20d": int, "total_buy": float, "stocks": [...]}}`
- 拉萨系散户席位名单（硬编码，知名散户集中营）：
  ```python
  RETAIL_DEPTS = ("东方财富证券拉萨团结路", "东方财富证券拉萨东环路",
                  "东方财富证券拉萨北京路", "东方财富证券拉萨察古大道",
                  "东方财富证券山南香曲东路")
  ```

- [ ] **Step 1: 实现 board_members.py**：`get_stock_board_map()` 读缓存 TTL 7 天；过期则遍历 90 个行业板块拉成分（1.2s 间隔，约 2 分钟），落盘 `{stock_code: board_name}`
- [ ] **Step 2: 实现 fetch_billboard_daily.py**：拉当日榜 → 逐只上榜股拉营业部明细 → 按 board_members 映射聚合到板块 → 算 retail_buy_ratio（拉萨系买入额/总买入额）→ 与近 20 日历史文件合并算 board_hits_20d
- [ ] **Step 3: 冒烟**：`.venv/bin/python scripts/fetch_billboard_daily.py --date 20261009`（用已知有数据的交易日），检查输出 JSON 有板块聚合结果
- [ ] **Step 4: Commit** `git commit -m "sentiment: billboard daily fetcher with retail-dept detection"`

---

### Task 4: 融资余额板块聚合

**Files:**
- Create: `scripts/fetch_margin_detail.py`

**Interfaces:**
- Consumes: datacenter `RPTA_WEB_RZRQ_GGMX`（个股融资余额明细；**先验证端点字段名**，若 404/字段错则在东财 data center 页面找替代报表，禁 push2）
- Produces: `infra/data/margin/YYYY-MM-DD.json` = `{stock_code: rzye}`；板块聚合在 Task 5 编排层做（按 board_members 汇总，算 20 日变化率序列）

- [ ] **Step 1: 端点验证**：`curl "https://datacenter-web.eastmoney.com/api/data/v1/get?reportName=RPTA_WEB_RZRQ_GGMX&columns=ALL&pageSize=2&source=WEB"` 确认字段
- [ ] **Step 2: 实现 + 冒烟**：`.venv/bin/python scripts/fetch_margin_detail.py --date 20261010`
- [ ] **Step 3: Commit** `git commit -m "sentiment: margin detail fetcher"`

---

### Task 5: 估值 overlay（冰封区专用）

**Files:**
- Create: `src/investment_engine/sentiment/valuation_overlay.py`
- Create: `scripts/fetch_board_members.py`（板块成分股列表独立拉取，供估值用）
- Test: `tests/investment_engine/sentiment/test_valuation_overlay.py`

**Interfaces:**
- Consumes: THS 行业成分股（akshare）；datacenter RPT_VALUEANALYSIS_DET（PE_TTM/PB_MRQ 日频历史，3 年窗口算分位）
- Produces:
  - `classify_board(board_name: str) -> "growth"|"cyclical"`（配置表 `config/stock_monitor/sentiment_board_class.yaml`；默认 growth，周期类显式列出：煤炭/钢铁/有色/化工/航运/养殖/银行/地产/石油石化/建材）
  - `assess_valuation(board_name: str) -> dict`：`{"method": "pe_percentile"|"pb_percentile", "value": 分位数, "cheap": bool, "median_pe"/"median_pb": float, "n_stocks": int, "as_of": str}`
  - cheap 判定：growth → PE_TTM 中位数的 3 年分位 <30%；cyclical → PB_MRQ 中位数的 3 年分位 <20%（与 fetch_board_valuation.py 的 PB_PERCENTILE_MAX 一致）

- [ ] **Step 1: 写失败测试**（mock 成分股 PE/PB 列表，验证中位数/分位/cheap 判定、增长 vs 周期路由）
- [ ] **Step 2: 实现 valuation_overlay.py**（复用 fetch_board_valuation.py 的 `_em_get` 模式与中位数纪律；每板块成分股 PE/PB 拉取用 datacenter 分页，间隔 1.5s）
- [ ] **Step 3: 冒烟**：对已知低估板块（如 煤炭）与高估板块各跑一次 `assess_valuation`，人工核对分位数合理
- [ ] **Step 4: Commit** `git commit -m "sentiment: valuation overlay for cold-zone boards"`

---

### Task 6: 日度编排 + cron + 复盘集成

**Files:**
- Create: `scripts/board_sentiment_daily.py`
- Create: `~/.hermes/scripts/qing_board_sentiment.py`（wrapper，稳定入口）
- Modify: 复盘脚本读取 `infra/data/board_sentiment/<date>.json` 附温度榜（找到 17:00 复盘脚本中合适的注入点，加"板块温度榜"小节：鼎沸 TOP5/冰封 TOP5 含 score+估值标签）

**Interfaces:**
- Produces: `infra/data/board_sentiment/YYYY-MM-DD.json` =
  ```json
  {"date": "...", "boards": [{"name": "...", "score": 0-100, "zone": "...",
    "components": {...}, "valuation": {...}|null}], 
   "hot_top5": [...], "cold_top5": [...]}
  ```
- 估值惰性计算：仅 zone=="cold" 的板块调用 `assess_valuation`（控量：冰封板块一般 <10 个）；`cold + cheap` → 标记 `opportunity: true`
- 推送输出（stdout 非空=推飞书）：仅当有板块**新跨入** hot/cold 区（与前一日文件 diff）时输出，文本含板块名/分数/估值标签/数据日期

- [ ] **Step 1: 实现 board_sentiment_daily.py**（编排 Task 1 数据 + thermometer + billboard/margin 最新文件 + valuation overlay）
- [ ] **Step 2: 用 Task 1 回填数据干跑**：`.venv/bin/python scripts/board_sentiment_daily.py --date 20261010`，检查输出 JSON 90 个板块齐全、zone 分布合理（不可能全 hot 或全 cold）
- [ ] **Step 3: 建 cron**：schedule 工作日 16:20（在 15:40 板块K线之后），no_agent wrapper；先在 cronjob 里 `run` 一次验证投递
- [ ] **Step 4: 复盘集成 + Commit** `git commit -m "sentiment: daily orchestrator + cron + review integration"`

---

### Task 7: 历史校准（双锚点）

**Files:**
- Create: `scripts/calibrate_sentiment.py`

**Interfaces:**
- Consumes: Task 1 的 500 日回填 bars（覆盖 2024/9/24-10/8 需回填 800 自然日，Task 1 首跑后用 `--backfill` 加深或单独补拉）
- Produces: 校准报告打印：每个锚点日期的全市场温度分布（mean/median/90分位）+ 典型板块温度（证券/白酒/半导体）

- [ ] **Step 1: 加深回填至 800 自然日**（校准窗口 2024/9 需要）：改 `--backfill` 参数化天数，`--backfill-days 800` 跑一次
- [ ] **Step 2: 实现校准脚本**：对 2024-09-23（应冷）、2024-10-08（应热）、2025-04-07（应冷）三个截面，用 bars 截至当日的切片跑 compute_temperature（仅量能+形态两分量能算的部分），输出分布
- [ ] **Step 3: 人工核对**：2024-10-08 全市场中位温度应 >70、证券板块 >85；2024-09-23 中位应 <30。不达标则调 WEIGHTS/pattern 参数并重跑，直到锚点吻合
- [ ] **Step 4: Commit** `git commit -m "sentiment: calibration against 2024/9-10 and 2025/4 anchors"`

---

## Self-Review

- Spec coverage：全市场板块(T1) ✓；量能/形态(T2) ✓；龙虎榜散户席位(T3) ✓；融资(T4) ✓；无人问津+便宜(T5) ✓；每日复盘+极值推送(T6) ✓；双锚点校准(T7) ✓；push2 规避 ✓
- 已知缺口（明示不做）：东财主力资金流（push2 被封，无替代）；涨停池统计（push2ex 被封）；股吧讨论量（参数调试成本高，二期再说）
- 类型一致性：thermometer 的 `board_stats` dict 键与 fetch_billboard_daily 输出键一致（retail_buy_ratio/board_hits_20d）；valuation_overlay 的 cheap 判定与 fetch_board_valuation.py 阈值纪律一致
