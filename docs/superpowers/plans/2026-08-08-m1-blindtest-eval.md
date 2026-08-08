# M1 盲测 eval 实施计划（历史回放 + 双对比评分 → 基线命中率报告）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 落地 v2.1 第十节/第十四节的 M1 里程碑——全量 71 个交易日历史回放，DeepSeek 盲出"市场阶段+方向+标的"判断，机械真值标签双对比评分，产出 AI 独立推理基线命中率报告。

**Architecture:** 新建 `src/investment_engine/blindtest/` 子包（dataset/truth/replay/score/up_baseline 五模块）+ `scripts/blindtest_replay.py` CLI。复用 M0 产物：`backtest/history.py`（区间 K 线）、`backtest/hit_rate.py`（前向收益）、`distill/pattern_schema.py` 校验过的 10 框架、产业链知识库、术语词典。设计全文见 `docs/superpowers/specs/2026-08-08-m1-blindtest-design.md`（**先读它**）。

**Tech Stack:** Python 3.11+ / openai 包（连 DeepSeek OpenAI 兼容端点）/ PyYAML / SQLite / pytest。

**调研已确认的关键事实（写代码直接用）：**

| 依赖 | 确认结果 |
|---|---|
| K 线缓存 | `infra/data/kline_cache.db`，217 标的覆盖 2026-04-27~2026-08-07（71 交易日）；`investment_engine.backtest.history.get_klines_range(code, start, end, db_path)` 兼容裸码与带后缀码；`coverage(db_path)` 键为裸码 |
| 指数拉取 | `_normalize_code` 按 6 开头判 sh，指数 "000300.SH" 会被错判成 sz000300 —— **指数必须用内联腾讯请求（full_code=sh000300/sh000001）绕开**，缓存落库用别名 `IDX000300`/`IDX000001`（防与平安银行 000001.SZ 裸码混淆） |
| 方向池 | `config/stock_monitor/direction_pool.yaml` 顶层 `directions: [{id, name, current_stage, industry_chain...}]`；`load_monitor_config` 返回 `cfg.direction_pool`。**current_stage 是 2026-07-24 的时变状态，进数据包只取 id+name** |
| LLM 客户端 | venv 已装 `openai 2.41.0`；DeepSeek 端点 `https://api.deepseek.com`，model `deepseek-chat`，OpenAI 兼容；key 读环境变量 `DEEPSEEK_API_KEY` |
| UP 原文 | `sources/raw/财经/` 26-05~07 共 197 篇；日期定位：文件名含 `26-MM-DD` token |
| 防泄漏 | prompt 机械断言：不含晚于当日的 `YYYY-MM-DD` 日期、不含 `UP\|青枫浦\|博主` |
| pytest | `tests/investment_engine/` 无 `__init__.py`（遮蔽坑，M0 已踩）；命令 `.venv/bin/pytest` |

**执行约束（用户指令）：** 不用 subagent、逐任务按本计划 commit message 提交（已授权）、不改 `src/qing_investment/`、`.venv/bin/pytest`。DeepSeek key 不落盘不进 git。指数/股票缓存文件 gitignored，不产生 commit。

**成本估算：** 每数据包 ~24KB（≈12K tokens）× 71 日 ≈ 0.9M input tokens，DeepSeek 约 ¥2-5。

---

## 文件结构

```
src/investment_engine/blindtest/
├── __init__.py            # Task 2
├── truth.py               # Task 2：机械真值标签（主升/震荡/调整/恐慌）
├── dataset.py             # Task 3：测试集枚举 + 每日数据包 + 防泄漏断言
├── replay.py              # Task 4：prompt 组装 + DeepSeek 调用 + 断点续跑
├── score.py               # Task 5：阶段一致率 + 方向/标的 5 日超额
└── up_baseline.py         # Task 6：vs UP 抽样对照（诊断用）
scripts/
├── fetch_index_klines.py  # Task 1：指数日 K 内联拉取（腾讯 sh000300/sh000001）
└── blindtest_replay.py    # Task 7：CLI（--run/--score/--report/--up-baseline）
tests/investment_engine/
├── test_truth.py          # Task 2
├── test_dataset.py        # Task 3
├── test_replay.py         # Task 4
├── test_score.py          # Task 5
└── test_up_baseline.py    # Task 6
evals/blindtest/           # Task 7/8 产出：results.jsonl（推理留档，供 M2 复用）
logs/m1-baseline-<date>.md # Task 8 产出：基线命中率报告
```

---

## Task 1: 指数日 K 补拉脚本与执行

**Files:**
- Create: `scripts/fetch_index_klines.py`

设计决策：指数走腾讯接口（`_normalize_code` 会误判指数市场前缀，故内联构造 `sh000300`/`sh000001` 请求）；落库别名 `IDX000300`/`IDX000001`，避免与个股裸码混淆（000001.SZ 平安银行）；拉 120 根保证真值规则的 20 日 lookback。

- [ ] **Step 1: 写脚本**

```python
#!/usr/bin/env python
"""补拉指数日 K 入 K 线缓存（M1 盲测真值/基准依赖）。

腾讯 _normalize_code 按"6 开头判 sh"会把指数 000300 误判为 sz000300，
这里内联构造 sh 前缀请求绕开；落库用 IDX 别名防与个股裸码混淆。

用法: python scripts/fetch_index_klines.py
"""
from __future__ import annotations

import json
import sys
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from qing_investment.kline_cache import init_db, save_klines

INDEXES = {"IDX000300": "sh000300", "IDX000001": "sh000001"}  # 沪深300 / 上证指数
DAYS = 120


def fetch_index_tencent(full_code: str, days: int = DAYS) -> list[dict]:
    end = datetime.now()
    start = end - timedelta(days=days + 20)
    url = (
        "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param="
        f"{full_code},day,{start:%Y-%m-%d},{end:%Y-%m-%d},{days + 20},qfq"
    )
    with urllib.request.urlopen(url, timeout=15) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    stock_data = data.get("data", {}).get(full_code, {})
    klines = stock_data.get("qfqday", []) or stock_data.get("day", [])
    result = []
    prev_close = None
    for k in klines:
        try:
            close = float(k[2])
            row = {
                "code": full_code, "date": k[0],
                "open": float(k[1]), "close": close,
                "high": float(k[3]), "low": float(k[4]),
                "volume": float(k[5]) if len(k) > 5 else 0.0,
                "turnover": None, "amplitude": None,
                "pct_change": (close / prev_close - 1.0) * 100 if prev_close else None,
            }
            result.append(row)
            prev_close = close
        except (IndexError, TypeError, ValueError):
            continue
    return result


def main() -> int:
    init_db()
    for alias, full_code in INDEXES.items():
        kl = fetch_index_tencent(full_code)
        if not kl:
            print(f"[FAIL] {alias} ({full_code}) 未取到数据")
            return 1
        save_klines(alias, kl)
        last = kl[-1]
        print(f"[OK] {alias}: {len(kl)} 根, {kl[0]['date']} ~ {last['date']}, 最后收盘 {last['close']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: 执行并验证**

Run: `.venv/bin/python scripts/fetch_index_klines.py`
Expected: 两行 `[OK]`，各 ~120 根，覆盖窗口前至少 25 个交易日；沪深300 与上证的收盘点位在合理量级（数千点）。再用 coverage 验证：

```bash
.venv/bin/python -c "
import sys; sys.path.insert(0, 'src')
from investment_engine.backtest.history import coverage
cov = coverage()
print('IDX000300', cov.get('IDX000300'))
print('IDX000001', cov.get('IDX000001'))
"
```
Expected: 两个别名都有 (start, end)，start ≤ 2026-03-30，end = 2026-08-07。

- [ ] **Step 3: Commit（经用户确认）**

```bash
git add scripts/fetch_index_klines.py
git commit -m "feat(blindtest): 指数日 K 补拉脚本（腾讯 sh 前缀绕开 _normalize_code 误判）"
```

---

## Task 2: 机械真值标签 truth.py

**Files:**
- Create: `src/investment_engine/blindtest/__init__.py`、`src/investment_engine/blindtest/truth.py`
- Test: `tests/investment_engine/test_truth.py`

规则（spec 冻结版，按序匹配）：`r20 ≤ -8%` 或（`r5 ≤ -4%` 且 `vol_trend ≥ 1.5`）→ 恐慌；`r20 ≤ -3%` 或 `pos20 ≤ 0.35` → 调整；`r20 ≥ +4%` 且 `pos20 ≥ 0.6` → 主升；其余 → 震荡。特征需 i≥24（vol_trend 用 i-24..i-5），不足返回 None。

- [ ] **Step 1: 写失败测试**

```python
# tests/investment_engine/test_truth.py
"""机械真值标签测试（合成 K 线构造已知走势）。"""
from investment_engine.blindtest.truth import (
    STAGES, compute_features, label_day, label_series,
)


def _klines(closes, vols=None) -> list[dict]:
    vols = vols or [1000.0] * len(closes)
    return [
        {"date": f"2026-05-{i + 1:02d}", "open": c, "high": c * 1.01, "low": c * 0.99,
         "close": c, "volume": v, "turnover": None, "amplitude": None, "pct_change": None}
        for i, (c, v) in enumerate(zip(closes, vols))
    ]


class TestComputeFeatures:
    def test_insufficient_lookback_returns_none(self):
        klines = _klines([10.0] * 24)
        assert compute_features(klines, 23) is None

    def test_flat_market(self):
        klines = _klines([10.0] * 30)
        f = compute_features(klines, 29)
        assert abs(f["r20"]) < 1e-9
        assert 0.0 <= f["pos20"] <= 1.0
        assert abs(f["vol_trend"] - 1.0) < 1e-9

    def test_rally(self):
        closes = [10.0] * 24 + [10.0 + 0.1 * i for i in range(6)]  # 末 5 日连涨
        klines = _klines(closes)
        f = compute_features(klines, 29)
        assert f["r5"] > 0
        assert f["pos20"] > 0.9


class TestLabelDay:
    def test_panic_by_r20(self):
        assert label_day({"r20": -0.09, "r5": -0.01, "pos20": 0.5, "vol_trend": 1.0}) == "恐慌"

    def test_panic_by_volume_crash(self):
        assert label_day({"r20": -0.02, "r5": -0.05, "pos20": 0.5, "vol_trend": 1.6}) == "恐慌"

    def test_pullback(self):
        assert label_day({"r20": -0.04, "r5": -0.01, "pos20": 0.5, "vol_trend": 1.0}) == "调整"
        assert label_day({"r20": 0.01, "r5": 0.0, "pos20": 0.3, "vol_trend": 1.0}) == "调整"

    def test_uptrend(self):
        assert label_day({"r20": 0.05, "r5": 0.01, "pos20": 0.7, "vol_trend": 1.0}) == "主升"

    def test_rangebound_default(self):
        assert label_day({"r20": 0.01, "r5": 0.0, "pos20": 0.5, "vol_trend": 1.0}) == "震荡"

    def test_vol_trend_none_neutral(self):
        """量能缺失时量能条件不触发。"""
        assert label_day({"r20": -0.02, "r5": -0.05, "pos20": 0.5, "vol_trend": None}) == "调整"


class TestLabelSeries:
    def test_series_skips_lookback_prefix(self):
        klines = _klines([10.0] * 30)
        rows = label_series(klines)
        assert len(rows) == 30 - 24  # 前 24 日 lookback 不足
        assert rows[0]["date"] == "2026-05-25"
        assert all(r["label"] in STAGES for r in rows)
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/pytest tests/investment_engine/test_truth.py -v`
Expected: FAIL，`ModuleNotFoundError`

- [ ] **Step 3: 实现**

```python
# src/investment_engine/blindtest/__init__.py
"""M1 盲测 eval：历史回放 + 双对比评分。"""
```

```python
# src/investment_engine/blindtest/truth.py
"""机械真值标签：用指数日 K 可计算特征给每个交易日贴市场阶段标签。

规则（spec 冻结版，按序匹配，先中先得）：
1. r20 ≤ -8% 或（r5 ≤ -4% 且 vol_trend ≥ 1.5）→ 恐慌
2. r20 ≤ -3% 或 pos20 ≤ 0.35 → 调整
3. r20 ≥ +4% 且 pos20 ≥ 0.6 → 主升
4. 其余 → 震荡
"""
from __future__ import annotations

STAGES = ("主升", "震荡", "调整", "恐慌")

_MIN_LOOKBACK = 24  # vol_trend 需要 i-24..i-5


def compute_features(klines: list[dict], i: int) -> dict | None:
    """klines 升序；计算第 i 日的特征。lookback 不足返回 None。"""
    if i < _MIN_LOOKBACK or i >= len(klines):
        return None
    close = klines[i]["close"]
    r20 = close / klines[i - 20]["close"] - 1.0
    r5 = close / klines[i - 5]["close"] - 1.0
    window = klines[i - 19 : i + 1]
    hi = max(k["high"] for k in window)
    lo = min(k["low"] for k in window)
    pos20 = (close - lo) / (hi - lo) if hi > lo else 0.5
    recent_vol = [k["volume"] or 0.0 for k in klines[i - 4 : i + 1]]
    prior_vol = [k["volume"] or 0.0 for k in klines[i - 24 : i - 4]]
    prior_mean = sum(prior_vol) / len(prior_vol)
    vol_trend = (sum(recent_vol) / len(recent_vol)) / prior_mean if prior_mean > 0 else None
    return {"r20": r20, "r5": r5, "pos20": pos20, "vol_trend": vol_trend}


def label_day(f: dict) -> str:
    if f["r20"] <= -0.08 or (f["r5"] <= -0.04 and f["vol_trend"] is not None and f["vol_trend"] >= 1.5):
        return "恐慌"
    if f["r20"] <= -0.03 or f["pos20"] <= 0.35:
        return "调整"
    if f["r20"] >= 0.04 and f["pos20"] >= 0.6:
        return "主升"
    return "震荡"


def label_series(klines: list[dict]) -> list[dict]:
    """全序列标注：[{"date", "label", "r20", "pos20", "r5", "vol_trend"}]，跳过 lookback 前缀。"""
    rows = []
    for i in range(len(klines)):
        f = compute_features(klines, i)
        if f is None:
            continue
        rows.append({"date": klines[i]["date"], "label": label_day(f), **f})
    return rows


def load_truth(db_path=None, index_code: str = "IDX000300") -> dict[str, str]:
    """从缓存读指数日 K，返回 {date: label}。"""
    from investment_engine.backtest.history import get_klines_range

    klines = get_klines_range(index_code, "2000-01-01", "2999-12-31", db_path=db_path)
    return {r["date"]: r["label"] for r in label_series(klines)}
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/pytest tests/investment_engine/test_truth.py -v`
Expected: 9 passed

- [ ] **Step 5: 校准检查（spec 规定的一次性校准步）**

```bash
.venv/bin/python -c "
import sys, collections; sys.path.insert(0, 'src')
from investment_engine.blindtest.truth import label_series
from investment_engine.backtest.history import get_klines_range
kl = get_klines_range('IDX000300', '2000-01-01', '2999-12-31')
rows = [r for r in label_series(kl) if '2026-04-27' <= r['date'] <= '2026-08-07']
print(len(rows), collections.Counter(r['label'] for r in rows))
"
```
Expected: 窗口内 ~71 行，无单一类别占比 >80%。若退化（如全部"震荡"），按窗口 r20/pos20 分位数微调阈值一次，更新本步骤与 truth.py docstring 记录两版阈值，然后冻结。

- [ ] **Step 6: Commit（经用户确认）**

```bash
git add src/investment_engine/blindtest/__init__.py src/investment_engine/blindtest/truth.py tests/investment_engine/test_truth.py
git commit -m "feat(blindtest): 机械真值标签（指数 K 线四分类规则）"
```

---

## Task 3: 每日数据包 dataset.py

**Files:**
- Create: `src/investment_engine/blindtest/dataset.py`
- Test: `tests/investment_engine/test_dataset.py`

数据包内容（prompt 唯一输入）：指数近 60 日摘要、stock_pool 当日量价、方向池（仅 id+name，排除时变的 current_stage）、产业链知识库（现版，标注日期）、术语词典、10 框架索引。防泄漏断言：无未来日期、无 UP/青枫浦/博主。

- [ ] **Step 1: 写失败测试**

```python
# tests/investment_engine/test_dataset.py
"""每日数据包构建与防泄漏测试。"""
import tempfile
from pathlib import Path

import pytest

from qing_investment.kline_cache import init_db, save_klines
from investment_engine.blindtest.dataset import (
    LeakageError, assert_no_leakage, build_daily_pack, pack_to_prompt, trading_days,
)


def _klines(code: str, closes: list[float]) -> list[dict]:
    return [
        {"code": code, "date": f"2026-06-{i + 1:02d}", "open": c, "high": c * 1.02,
         "low": c * 0.98, "close": c, "volume": 1000 + i * 10,
         "turnover": 1.5, "amplitude": 4.0, "pct_change": 0.5}
        for i, c in enumerate(closes)
    ]


class TestTradingDays:
    def setup_method(self):
        self.db = Path(tempfile.gettempdir()) / f"test_ds_{id(self)}.db"
        init_db(db_path=self.db)
        save_klines("002371", _klines("002371", [10.0] * 30), db_path=self.db)

    def teardown_method(self):
        self.db.unlink(missing_ok=True)

    def test_days_from_cache(self):
        days = trading_days("2026-06-01", "2026-06-30", db_path=self.db)
        assert days[0] == "2026-06-01" and len(days) == 30


class TestAssertNoLeakage:
    def test_future_date_rejected(self):
        with pytest.raises(LeakageError, match="2026-08-01"):
            assert_no_leakage("截至 2026-07-01 数据。参考 2026-08-01 走势", "2026-07-01")

    def test_up_words_rejected(self):
        for w in ("UP", "青枫浦", "博主"):
            with pytest.raises(LeakageError):
                assert_no_leakage(f"某 {w} 观点", "2026-07-01")

    def test_clean_text_passes(self):
        assert_no_leakage("2026-07-01 收盘综述：量能 1.2 万亿", "2026-07-01")


class TestBuildDailyPack:
    def setup_method(self):
        self.db = Path(tempfile.gettempdir()) / f"test_ds2_{id(self)}.db"
        init_db(db_path=self.db)
        save_klines("002371.SZ", _klines("002371.SZ", [10.0 + i * 0.1 for i in range(30)]), db_path=self.db)
        save_klines("IDX000300", _klines("IDX000300", [4000.0 + i for i in range(30)]), db_path=self.db)

    def teardown_method(self):
        self.db.unlink(missing_ok=True)

    def test_pack_truncates_at_day(self):
        pack = build_daily_pack("2026-06-15", config_dir=Path("config/stock_monitor"), db_path=self.db)
        assert pack["date"] == "2026-06-15"
        idx = pack["index"]["IDX000300"]
        assert idx[-1]["d"] == "2026-06-15"  # 数据截至当日，无未来
        assert len(idx) == 15

    def test_pack_stock_entry_fields(self):
        pack = build_daily_pack("2026-06-15", config_dir=Path("config/stock_monitor"), db_path=self.db)
        s = next(x for x in pack["stocks"] if x["code"] == "002371")
        assert set(s) == {"code", "name", "direction", "close", "pct", "turnover", "pos20"}

    def test_direction_pool_has_no_time_varying_fields(self):
        pack = build_daily_pack("2026-06-15", config_dir=Path("config/stock_monitor"), db_path=self.db)
        for d in pack["directions"]:
            assert set(d) == {"id", "name"}  # current_stage 等时变字段不得进入

    def test_prompt_passes_leakage_assertion(self):
        pack = build_daily_pack("2026-06-15", config_dir=Path("config/stock_monitor"), db_path=self.db)
        text = pack_to_prompt(pack)
        assert_no_leakage(text, "2026-06-15")  # 自身产出必须过自家断言
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/pytest tests/investment_engine/test_dataset.py -v`
Expected: FAIL，`ModuleNotFoundError`

- [ ] **Step 3: 实现**

```python
# src/investment_engine/blindtest/dataset.py
"""盲测每日数据包构建：prompt 的唯一输入，只含当日可得的客观数据。

防泄漏：pack_to_prompt 产出必须过 assert_no_leakage（无未来日期、无 UP 指称）。
时变字段（direction_pool.current_stage 等）一律不进包。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

from investment_engine.backtest.history import get_klines_range, list_trading_days

FORBIDDEN_RE = re.compile(r"UP|青枫浦|博主")
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
INDEX_CODES = ("IDX000300", "IDX000001")
_INDEX_LOOKBACK = 60
_STOCK_ZONE_DAYS = 20

_REPO = Path(__file__).resolve().parents[3]


class LeakageError(ValueError):
    """数据包含未来信息或来源指称，禁止送入盲测 prompt。"""


def assert_no_leakage(text: str, day: str) -> None:
    m = FORBIDDEN_RE.search(text)
    if m:
        raise LeakageError(f"prompt 含来源指称 {m.group(0)!r}")
    for d in DATE_RE.findall(text):
        if d > day:
            raise LeakageError(f"prompt 含未来日期 {d}（当日 {day}）")


def trading_days(start: str, end: str, db_path=None) -> list[str]:
    return list_trading_days(start, end, db_path)


def _pos20(klines: list[dict]) -> float | None:
    if len(klines) < _STOCK_ZONE_DAYS:
        return None
    window = klines[-_STOCK_ZONE_DAYS:]
    hi = max(k["high"] for k in window)
    lo = min(k["low"] for k in window)
    if hi <= lo:
        return 0.5
    return round((window[-1]["close"] - lo) / (hi - lo), 4)


def _compact_bars(klines: list[dict], n: int) -> list[dict]:
    return [
        {"d": k["date"], "c": k["close"], "pct": k.get("pct_change"), "vol": k.get("volume")}
        for k in klines[-n:]
    ]


def _load_directions(config_dir: Path) -> list[dict]:
    raw = yaml.safe_load((config_dir / "direction_pool.yaml").read_text(encoding="utf-8")) or {}
    return [
        {"id": d.get("id"), "name": d.get("name")}
        for d in raw.get("directions", []) or []
        if d.get("id")
    ]


def _load_chains() -> list[dict]:
    from investment_engine.industry_chain.store import list_chains, load_chain

    chains = []
    for cid in list_chains():
        c = load_chain(cid)
        # last_verified 等日期字段可能晚于回放日 → 泄漏断言会拦截，一律剔除
        chains.append({
            "chain_id": c["chain_id"], "name": c["name"], "thesis": c["thesis"],
            "segments": [{"id": s["id"], "name": s["name"]} for s in c["segments"]],
            "mappings": [
                {"code": m["code"], "name": m["name"], "segment": m["segment"],
                 "elasticity": m["elasticity"], "cert_status": m.get("cert_status")}
                for m in c["mappings"]
            ],
        })
    return chains


def _load_patterns_index() -> list[dict]:
    raw = yaml.safe_load((_REPO / "framework" / "reasoning-patterns.yaml").read_text(encoding="utf-8"))
    return [
        {"pattern_id": p["pattern_id"], "name": p["name"], "trigger": p.get("trigger", [])}
        for p in raw.get("patterns", [])
    ]


def _load_glossary() -> str:
    return (_REPO / "framework" / "up-glossary.md").read_text(encoding="utf-8")


def build_daily_pack(day: str, *, config_dir: Path, db_path=None) -> dict:
    """组装某日数据包（只含截至当日的数据）。"""
    index = {}
    for code in INDEX_CODES:
        bars = get_klines_range(code, "2000-01-01", day, db_path=db_path)
        index[code] = _compact_bars(bars, _INDEX_LOOKBACK)

    from qing_investment.monitor.context import load_monitor_config

    cfg = load_monitor_config(config_dir)
    stocks = []
    for s in (cfg.stock_pool or {}).get("stocks", []):
        code = s.get("code")
        if not code:
            continue
        bars = get_klines_range(code, "2000-01-01", day, db_path=db_path)
        if not bars or bars[-1]["date"] != day:
            continue
        last = bars[-1]
        stocks.append({
            "code": code.split(".")[0], "name": s.get("name", ""),
            "direction": s.get("direction", ""),
            "close": last["close"], "pct": last.get("pct_change"),
            "turnover": last.get("turnover"), "pos20": _pos20(bars),
        })

    return {
        "date": day,
        "index": index,
        "stocks": stocks,
        "directions": _load_directions(config_dir),
        "chains": _load_chains(),
        "glossary": _load_glossary(),
        "patterns": _load_patterns_index(),
    }


def pack_to_prompt(pack: dict) -> str:
    """序列化为 prompt 正文。产出必须能过 assert_no_leakage。"""
    header = (
        f"今天是 {pack['date']}。以下是截至今日收盘的客观数据。"
        "注意：产业链知识库与方向池为最新版静态快照（不含任何时变状态字段）。\n\n"
    )
    body = json.dumps(
        {k: v for k, v in pack.items() if k != "glossary"},
        ensure_ascii=False, separators=(",", ":"),
    )
    text = header + body + "\n\n## 术语词典\n" + pack["glossary"]
    assert_no_leakage(text, pack["date"])  # 出厂自检
    return text
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/pytest tests/investment_engine/test_dataset.py -v`
Expected: 7 passed。`last_verified` 剔除与 header 无日期化已在上方代码处理；若仍有其他字段触发泄漏断言（如实踩到新的未来日期来源），定位后剔除该字段——**以断言通过为准修正，不得放松断言本身。**

- [ ] **Step 5: Commit（经用户确认）**

```bash
git add src/investment_engine/blindtest/dataset.py tests/investment_engine/test_dataset.py
git commit -m "feat(blindtest): 每日数据包构建与防泄漏断言"
```

---

## Task 4: DeepSeek 回放 replay.py

**Files:**
- Create: `src/investment_engine/blindtest/replay.py`
- Test: `tests/investment_engine/test_replay.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/investment_engine/test_replay.py
"""DeepSeek 回放测试（mock client，不触网）。"""
import json
from types import SimpleNamespace

import pytest

from investment_engine.blindtest.replay import (
    SYSTEM_PROMPT, build_messages, parse_result, run_replay,
)


def _fake_client(payload: str):
    """构造 openai 兼容的假 client。"""
    msg = SimpleNamespace(content=payload)
    choice = SimpleNamespace(message=msg)
    completions = SimpleNamespace(create=lambda **kw: SimpleNamespace(choices=[choice]))
    chat = SimpleNamespace(completions=completions)
    return SimpleNamespace(chat=chat)


GOOD_JSON = json.dumps({
    "market_stage": "震荡",
    "stage_reason": "指数缩量横盘",
    "directions": [{"direction_id": "mlcc_super_cycle", "reason": "涨价", "stocks": ["002371"]}],
    "used_patterns": ["upstream_cycle"],
}, ensure_ascii=False)


class TestBuildMessages:
    def test_system_prompt_has_contract(self):
        assert "market_stage" in SYSTEM_PROMPT and "主升" in SYSTEM_PROMPT

    def test_messages_shape(self):
        msgs = build_messages("PACK_TEXT")
        assert msgs[0]["role"] == "system" and msgs[1]["role"] == "user"
        assert "PACK_TEXT" in msgs[1]["content"]


class TestParseResult:
    def test_plain_json(self):
        r = parse_result(GOOD_JSON)
        assert r["market_stage"] == "震荡"
        assert r["directions"][0]["direction_id"] == "mlcc_super_cycle"

    def test_fenced_json(self):
        assert parse_result(f"```json\n{GOOD_JSON}\n```")["market_stage"] == "震荡"

    def test_bad_stage_rejected(self):
        bad = json.dumps({"market_stage": "牛市", "directions": []})
        with pytest.raises(ValueError, match="market_stage"):
            parse_result(bad)

    def test_over_limit_truncated(self):
        payload = json.dumps({
            "market_stage": "主升",
            "directions": [{"direction_id": f"d{i}", "stocks": ["1", "2", "3"]} for i in range(5)],
        })
        r = parse_result(payload)
        assert len(r["directions"]) == 3
        assert len(r["directions"][0]["stocks"]) == 2

    def test_garbage_rejected(self):
        with pytest.raises(ValueError):
            parse_result("我觉得今天不错")


class TestRunReplay:
    def test_resume_skips_done_days(self, tmp_path, monkeypatch):
        out = tmp_path / "results.jsonl"
        out.write_text(
            json.dumps({"date": "2026-06-01", "ok": True, "result": {}, "raw": ""}) + "\n",
            encoding="utf-8",
        )
        calls = []

        def fake_pack(day, **kw):
            return "PACK"

        def fake_call(messages, **kw):
            calls.append(messages)
            return GOOD_JSON

        monkeypatch.setattr(
            "investment_engine.blindtest.replay.pack_to_prompt", lambda pack: pack
        )
        monkeypatch.setattr(
            "investment_engine.blindtest.replay.build_daily_pack", fake_pack
        )
        monkeypatch.setattr(
            "investment_engine.blindtest.replay.call_deepseek", fake_call
        )
        stats = run_replay(["2026-06-01", "2026-06-02"], config_dir="x", out_path=out)
        assert stats["skipped"] == 1 and stats["done"] == 1
        assert len(calls) == 1  # 只跑了新的一天
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/pytest tests/investment_engine/test_replay.py -v`
Expected: FAIL，`ModuleNotFoundError`

- [ ] **Step 3: 实现**

```python
# src/investment_engine/blindtest/replay.py
"""盲测推理回放：逐日组装 prompt 调 DeepSeek，JSONL 落盘，断点续跑。"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from investment_engine.blindtest.dataset import build_daily_pack, pack_to_prompt
from investment_engine.blindtest.truth import STAGES

DEFAULT_MODEL = "deepseek-chat"
_BASE_URL = "https://api.deepseek.com"
_MAX_DIRECTIONS = 3
_MAX_STOCKS_PER_DIR = 2

SYSTEM_PROMPT = """你是一个执行已验证方法论的市场分析引擎。基于给定的当日客观数据，独立完成市场复盘判断。
要求：
1. 每个判断必须声明所用的数据项；不得引用任何人物的言论或观点。
2. 可参考给定的推理框架索引（patterns）与术语词典组织推理，在 used_patterns 中登记实际用到的框架 id。
3. 严格输出 JSON（不要输出其他文字）：
{"market_stage": "主升|震荡|调整|恐慌（四选一）",
 "stage_reason": "一句话依据",
 "directions": [{"direction_id": "从给定方向池选择，1-3个", "reason": "一句话依据", "stocks": ["该方向下给定股票池中的代码，每方向1-2个"]}],
 "used_patterns": ["pattern_id"]}
4. 没有把握的方向可以不选，宁缺毋滥。"""


def build_messages(pack_text: str) -> list[dict]:
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": pack_text},
    ]


def _default_client():
    from openai import OpenAI

    key = os.environ.get("DEEPSEEK_API_KEY")
    if not key:
        raise RuntimeError("缺少 DEEPSEEK_API_KEY 环境变量")
    return OpenAI(api_key=key, base_url=_BASE_URL)


def call_deepseek(messages: list[dict], *, model: str = DEFAULT_MODEL,
                  max_retries: int = 3, client=None) -> str:
    client = client or _default_client()
    last_err: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            resp = client.chat.completions.create(
                model=model, messages=messages, temperature=0,
                response_format={"type": "json_object"},
            )
            return resp.choices[0].message.content
        except Exception as e:  # noqa: BLE001 - 重试后如实记录
            last_err = e
            if attempt < max_retries:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"DeepSeek 调用失败（{max_retries} 次）: {last_err}")


def parse_result(raw: str) -> dict:
    """解析模型输出为规范结构；fence 容忍、字段校验、超限截断。"""
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"输出非 JSON: {raw[:80]!r}") from e
    stage = data.get("market_stage")
    if stage not in STAGES:
        raise ValueError(f"market_stage 非法: {stage!r}")
    directions = []
    for d in (data.get("directions") or [])[:_MAX_DIRECTIONS]:
        if not isinstance(d, dict) or not d.get("direction_id"):
            continue
        directions.append({
            "direction_id": str(d["direction_id"]),
            "reason": str(d.get("reason", "")),
            "stocks": [str(s).split(".")[0] for s in (d.get("stocks") or [])[:_MAX_STOCKS_PER_DIR]],
        })
    return {
        "market_stage": stage,
        "stage_reason": str(data.get("stage_reason", "")),
        "directions": directions,
        "used_patterns": [str(p) for p in (data.get("used_patterns") or [])],
    }


def _done_dates(out_path: Path) -> set[str]:
    if not out_path.exists():
        return set()
    done = set()
    for line in out_path.read_text(encoding="utf-8").splitlines():
        try:
            done.add(json.loads(line)["date"])
        except (json.JSONDecodeError, KeyError):
            continue
    return done


def run_replay(days: list[str], *, config_dir, out_path: Path, db_path=None,
               model: str = DEFAULT_MODEL, client=None, sleep_s: float = 0.5) -> dict:
    """逐日回放。已完成日期跳过（断点续跑）；单日失败记 error 继续。"""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    done = _done_dates(out_path)
    stats = {"done": 0, "skipped": 0, "error": 0}
    with out_path.open("a", encoding="utf-8") as fh:
        for day in days:
            if day in done:
                stats["skipped"] += 1
                continue
            try:
                pack = build_daily_pack(day, config_dir=Path(config_dir), db_path=db_path)
                text = pack_to_prompt(pack)  # 内含防泄漏断言
                raw = call_deepseek(build_messages(text), model=model, client=client)
                result = parse_result(raw)
                fh.write(json.dumps(
                    {"date": day, "ok": True, "result": result, "raw": raw},
                    ensure_ascii=False) + "\n")
                stats["done"] += 1
            except Exception as e:  # noqa: BLE001 - 单日失败不阻断全量
                fh.write(json.dumps(
                    {"date": day, "ok": False, "error": str(e)[:200]},
                    ensure_ascii=False) + "\n")
                stats["error"] += 1
            fh.flush()
            time.sleep(sleep_s)
    return stats
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/pytest tests/investment_engine/test_replay.py -v`
Expected: 9 passed

- [ ] **Step 5: Commit（经用户确认）**

```bash
git add src/investment_engine/blindtest/replay.py tests/investment_engine/test_replay.py
git commit -m "feat(blindtest): DeepSeek 回放（JSON 契约 + 断点续跑）"
```

---

## Task 5: 评分 score.py

**Files:**
- Create: `src/investment_engine/blindtest/score.py`
- Test: `tests/investment_engine/test_score.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/investment_engine/test_score.py
"""盲测评分测试（合成记录 + 合成 K 线）。"""
import json
import tempfile
from pathlib import Path

from qing_investment.kline_cache import init_db, save_klines
from investment_engine.blindtest.score import (
    direction_scores, load_results, stage_accuracy, stock_scores,
)


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")


def _klines(code: str, closes: list[float]) -> list[dict]:
    return [
        {"code": code, "date": f"2026-06-{i + 1:02d}", "open": c, "high": c, "low": c,
         "close": c, "volume": 100, "turnover": 1.0, "amplitude": 1.0, "pct_change": 0.0}
        for i, c in enumerate(closes)
    ]


class TestLoadResults:
    def test_only_ok_rows(self, tmp_path):
        p = tmp_path / "r.jsonl"
        _write_jsonl(p, [
            {"date": "d1", "ok": True, "result": {"market_stage": "震荡"}},
            {"date": "d2", "ok": False, "error": "x"},
        ])
        rows = load_results(p)
        assert len(rows) == 1 and rows[0]["date"] == "d1"


class TestStageAccuracy:
    def test_accuracy_and_by_label(self, tmp_path):
        p = tmp_path / "r.jsonl"
        _write_jsonl(p, [
            {"date": "d1", "ok": True, "result": {"market_stage": "主升"}},
            {"date": "d2", "ok": True, "result": {"market_stage": "震荡"}},
            {"date": "d3", "ok": True, "result": {"market_stage": "调整"}},
        ])
        truth = {"d1": "主升", "d2": "调整", "d3": "调整"}
        s = stage_accuracy(load_results(p), truth)
        assert s["samples"] == 3 and s["hits"] == 2
        assert abs(s["accuracy"] - 2 / 3) < 1e-9
        assert s["by_label"]["调整"]["samples"] == 2


class TestDirectionAndStockScores:
    def setup_method(self):
        self.db = Path(tempfile.gettempdir()) / f"test_score_{id(self)}.db"
        init_db(db_path=self.db)
        # 指数：平稳；个股 a 涨、个股 b 跌
        save_klines("IDX000300", _klines("IDX000300", [4000.0] * 12), db_path=self.db)
        save_klines("002371", _klines("002371", [10.0, 10, 10, 10, 10, 11, 11, 11, 11, 11, 11, 11]), db_path=self.db)
        save_klines("300054", _klines("300054", [10.0, 10, 10, 10, 10, 9, 9, 9, 9, 9, 9, 9]), db_path=self.db)

    def teardown_method(self):
        self.db.unlink(missing_ok=True)

    def _results(self, tmp_path):
        p = tmp_path / "r.jsonl"
        _write_jsonl(p, [
            {"date": "2026-06-01", "ok": True, "result": {
                "market_stage": "震荡",
                "directions": [{"direction_id": "semiconductor", "stocks": ["002371", "300054"]}],
            }},
        ])
        return load_results(p)

    def test_stock_scores(self, tmp_path):
        s = stock_scores(self._results(tmp_path), db_path=self.db, horizon=5)
        # 002371: +10% vs 指数 0 → 命中；300054: -10% → 不中
        assert s["samples"] == 2 and s["hits"] == 1

    def test_direction_scores(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "investment_engine.blindtest.score._direction_members",
            lambda config_dir, direction_id: ["002371", "300054"],
        )
        s = direction_scores(self._results(tmp_path), config_dir="x", db_path=self.db, horizon=5)
        # 等权 (10% + -10%)/2 = 0 → 超额 0，不记命中（严格 >0）
        assert s["samples"] == 1 and s["hits"] == 0
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/pytest tests/investment_engine/test_score.py -v`
Expected: FAIL，`ModuleNotFoundError`

- [ ] **Step 3: 实现**

```python
# src/investment_engine/blindtest/score.py
"""盲测评分：阶段一致率 + 方向/标的 5 日相对沪深300 超额。"""
from __future__ import annotations

import json
from pathlib import Path

from investment_engine.backtest.history import get_klines_range
from investment_engine.backtest.hit_rate import forward_return

BENCH_CODE = "IDX000300"


def load_results(path) -> list[dict]:
    rows = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if r.get("ok"):
            rows.append(r)
    return rows


def stage_accuracy(results: list[dict], truth: dict[str, str]) -> dict:
    """truth: {date: label}。只在有真值的日期上评分。"""
    hits = 0
    by_label: dict[str, dict] = {}
    samples = 0
    for r in results:
        label = truth.get(r["date"])
        if label is None:
            continue
        samples += 1
        bucket = by_label.setdefault(label, {"samples": 0, "hits": 0})
        bucket["samples"] += 1
        if r["result"].get("market_stage") == label:
            hits += 1
            bucket["hits"] += 1
    for b in by_label.values():
        b["accuracy"] = b["hits"] / b["samples"] if b["samples"] else None
    return {
        "samples": samples, "hits": hits,
        "accuracy": hits / samples if samples else None,
        "by_label": by_label,
    }


def _forward(db_path, code: str, day: str, horizon: int) -> float | None:
    klines = get_klines_range(code, day, "2999-12-31", db_path=db_path)
    return forward_return(klines, day, horizon)


def _direction_members(config_dir, direction_id: str) -> list[str]:
    from qing_investment.monitor.context import load_monitor_config

    cfg = load_monitor_config(Path(config_dir))
    return [
        s["code"] for s in (cfg.stock_pool or {}).get("stocks", [])
        if s.get("direction") == direction_id and s.get("code")
    ]


def direction_scores(results: list[dict], *, config_dir, db_path=None,
                     bench_code: str = BENCH_CODE, horizon: int = 5) -> dict:
    hits = samples = 0
    details = []
    for r in results:
        for d in r["result"].get("directions", []):
            members = _direction_members(config_dir, d["direction_id"])
            rets = [
                v for v in (_forward(db_path, c, r["date"], horizon) for c in members)
                if v is not None
            ]
            bench = _forward(db_path, bench_code, r["date"], horizon)
            if not rets or bench is None:
                continue
            dir_ret = sum(rets) / len(rets)
            hit = (dir_ret - bench) > 0
            samples += 1
            hits += int(hit)
            details.append({"date": r["date"], "direction_id": d["direction_id"],
                            "dir_ret": dir_ret, "bench_ret": bench, "hit": hit})
    return {"samples": samples, "hits": hits,
            "hit_rate": hits / samples if samples else None, "details": details}


def stock_scores(results: list[dict], *, db_path=None,
                 bench_code: str = BENCH_CODE, horizon: int = 5) -> dict:
    hits = samples = 0
    details = []
    for r in results:
        bench = _forward(db_path, bench_code, r["date"], horizon)
        if bench is None:
            continue
        for d in r["result"].get("directions", []):
            for code in d.get("stocks", []):
                ret = _forward(db_path, code, r["date"], horizon)
                if ret is None:
                    continue
                hit = (ret - bench) > 0
                samples += 1
                hits += int(hit)
                details.append({"date": r["date"], "code": code,
                                "ret": ret, "bench_ret": bench, "hit": hit})
    return {"samples": samples, "hits": hits,
            "hit_rate": hits / samples if samples else None, "details": details}
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/pytest tests/investment_engine/test_score.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit（经用户确认）**

```bash
git add src/investment_engine/blindtest/score.py tests/investment_engine/test_score.py
git commit -m "feat(blindtest): 阶段一致率与方向/标的超额评分"
```

---

## Task 6: vs UP 对照 up_baseline.py

**Files:**
- Create: `src/investment_engine/blindtest/up_baseline.py`
- Test: `tests/investment_engine/test_up_baseline.py`

设计决策：UP 文档按文件名 `26-MM-DD` token 定位；抽取用同一 DeepSeek client（该路径不涉盲测，UP 内容合法输入）； verdict 四分类：AI对UP对 / AI对UP错 / AI错UP对（毕业信心证据）/ 都错（回炉引擎⓪ 候选）。

- [ ] **Step 1: 写失败测试**

```python
# tests/investment_engine/test_up_baseline.py
"""vs UP 对照测试。"""
import json
from types import SimpleNamespace

from investment_engine.blindtest.up_baseline import (
    build_comparison, find_up_docs, parse_up_view, pick_sample_days,
)


def _fake_client(payload: str):
    msg = SimpleNamespace(content=payload)
    choice = SimpleNamespace(message=msg)
    completions = SimpleNamespace(create=lambda **kw: SimpleNamespace(choices=[choice]))
    return SimpleNamespace(chat=SimpleNamespace(completions=completions))


class TestPickSampleDays:
    def test_stratified_and_deterministic(self):
        truth = {f"2026-06-{i:02d}": label for i, label in enumerate(
            ["主升"] * 10 + ["震荡"] * 10 + ["调整"] * 5 + ["恐慌"] * 5, start=1)}
        days = pick_sample_days(truth, n=10)
        assert len(days) == 10
        assert days == pick_sample_days(truth, n=10)  # 确定性
        labels = {truth[d] for d in days}
        assert len(labels) >= 3  # 分层覆盖


class TestFindUpDocs:
    def test_match_by_date_token(self, tmp_path):
        (tmp_path / "复盘：26-06-15：缩量.md").write_text("x", encoding="utf-8")
        (tmp_path / "复盘：26-06-16：放量.md").write_text("y", encoding="utf-8")
        docs = find_up_docs("2026-06-15", up_dir=tmp_path)
        assert len(docs) == 1 and "06-15" in docs[0].name

    def test_no_doc_returns_empty(self, tmp_path):
        assert find_up_docs("2026-06-20", up_dir=tmp_path) == []


class TestParseUpView:
    def test_valid(self):
        raw = json.dumps({"stage": "调整", "directions": ["半导体"], "mentioned": True})
        v = parse_up_view(raw)
        assert v["stage"] == "调整" and v["mentioned"] is True

    def test_unmentioned(self):
        raw = json.dumps({"stage": None, "directions": [], "mentioned": False})
        assert parse_up_view(raw)["mentioned"] is False


class TestBuildComparison:
    def test_verdict_classes(self):
        results = [
            {"date": "d1", "ok": True, "result": {"market_stage": "主升", "directions": []}},
            {"date": "d2", "ok": True, "result": {"market_stage": "调整", "directions": []}},
        ]
        truth = {"d1": "主升", "d2": "震荡"}
        up_views = {"d1": {"stage": "主升", "mentioned": True},
                    "d2": {"stage": "主升", "mentioned": True}}
        rows = build_comparison(results, truth, up_views)
        assert rows[0]["verdict"] == "AI对UP对"
        assert rows[1]["verdict"] == "都错"
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/pytest tests/investment_engine/test_up_baseline.py -v`
Expected: FAIL，`ModuleNotFoundError`

- [ ] **Step 3: 实现**

```python
# src/investment_engine/blindtest/up_baseline.py
"""vs UP 对照（诊断信息，不进命中率）：抽样日抽取 UP 当日结论，三方对照。

注意：本模块处理 UP 原文，属"参考对比"路径，与盲测推理路径物理隔离
（UP 内容只进本模块的抽取 prompt，不进 replay 的盲测 prompt）。
"""
from __future__ import annotations

import json
import random
from pathlib import Path

from investment_engine.blindtest.truth import STAGES

UP_DIR = Path("sources/raw/财经")

EXTRACT_PROMPT = """从以下复盘文本中抽取作者当日对市场的结论，严格输出 JSON：
{"stage": "主升|震荡|调整|恐慌（最接近的一个；未明确判断则为 null）",
 "directions": ["作者看好的方向/板块（最多3个，无则空列表）"],
 "mentioned": true/false（文本是否包含对当日市场的实质判断）}
只输出 JSON。

文本：
"""


def pick_sample_days(truth: dict[str, str], n: int = 10, seed: int = 42) -> list[str]:
    """按真值标签分层抽样，确定性（固定 seed）。"""
    by_label: dict[str, list[str]] = {}
    for d, label in sorted(truth.items()):
        by_label.setdefault(label, []).append(d)
    rng = random.Random(seed)
    picked: list[str] = []
    labels = sorted(by_label, key=lambda l: -len(by_label[l]))
    while len(picked) < n and any(by_label.values()):
        for label in labels:
            pool = by_label.get(label) or []
            if pool and len(picked) < n:
                picked.append(pool.pop(rng.randrange(len(pool))))
    return sorted(picked)


def find_up_docs(day: str, up_dir: Path = UP_DIR) -> list[Path]:
    """day='2026-06-15' → 文件名含 '26-06-15' 的文档。"""
    token = day[2:]
    if not up_dir.exists():
        return []
    return sorted(p for p in up_dir.iterdir() if token in p.name)


def parse_up_view(raw: str) -> dict:
    text = raw.strip().strip("`")
    if text.lower().startswith("json"):
        text = text[4:].strip()
    data = json.loads(text)
    stage = data.get("stage")
    if stage is not None and stage not in STAGES:
        stage = None
    return {
        "stage": stage,
        "directions": [str(d) for d in (data.get("directions") or [])][:3],
        "mentioned": bool(data.get("mentioned")),
    }


def extract_up_view(doc_text: str, *, client=None, model: str = "deepseek-chat") -> dict:
    from investment_engine.blindtest.replay import call_deepseek

    raw = call_deepseek(
        [{"role": "user", "content": EXTRACT_PROMPT + doc_text[:8000]}],
        model=model, client=client,
    )
    return parse_up_view(raw)


def build_comparison(results: list[dict], truth: dict[str, str],
                     up_views: dict[str, dict]) -> list[dict]:
    """三方对照：AI vs 真值 vs UP。verdict 四分类。"""
    rows = []
    by_date = {r["date"]: r for r in results}
    for day, up in sorted(up_views.items()):
        r = by_date.get(day)
        label = truth.get(day)
        if r is None or label is None:
            continue
        ai_stage = r["result"].get("market_stage")
        ai_ok = ai_stage == label
        up_ok = up.get("stage") is not None and up["stage"] == label
        if ai_ok and up_ok:
            verdict = "AI对UP对"
        elif ai_ok and not up_ok:
            verdict = "AI对UP错"
        elif not ai_ok and up_ok:
            verdict = "AI错UP对"  # 毕业信心反例
        else:
            verdict = "都错"  # 回炉引擎⓪ 候选
        rows.append({
            "date": day, "truth": label, "ai_stage": ai_stage,
            "up_stage": up.get("stage"), "up_directions": up.get("directions", []),
            "verdict": verdict,
        })
    return rows
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/pytest tests/investment_engine/test_up_baseline.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit（经用户确认）**

```bash
git add src/investment_engine/blindtest/up_baseline.py tests/investment_engine/test_up_baseline.py
git commit -m "feat(blindtest): vs UP 抽样对照（诊断路径，与盲测隔离）"
```

---

## Task 7: CLI 与 1 日 dry-run e2e

**Files:**
- Create: `scripts/blindtest_replay.py`

- [ ] **Step 1: 写 CLI**

```python
#!/usr/bin/env python
"""M1 盲测回放 CLI：--run 推理 / --score 评分 / --report 报告 / --up-baseline 对照。

用法:
  DEEPSEEK_API_KEY=... python scripts/blindtest_replay.py --run [--days N]
  python scripts/blindtest_replay.py --score --report
  DEEPSEEK_API_KEY=... python scripts/blindtest_replay.py --up-baseline [--up-days 10]
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

DEFAULT_OUT = Path("evals/blindtest/results.jsonl")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="M1 盲测回放")
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--score", action="store_true")
    parser.add_argument("--report", action="store_true")
    parser.add_argument("--up-baseline", action="store_true")
    parser.add_argument("--days", type=int, default=None, help="只跑前 N 个交易日（dry-run 用）")
    parser.add_argument("--up-days", type=int, default=10)
    parser.add_argument("--model", default="deepseek-chat")
    parser.add_argument("--start", default="2026-04-27")
    parser.add_argument("--end", default="2026-08-07")
    parser.add_argument("--config-dir", default="config/stock_monitor")
    parser.add_argument("--db", default="infra/data/kline_cache.db")
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    args = parser.parse_args(argv)

    from investment_engine.blindtest.dataset import trading_days
    from investment_engine.blindtest.truth import load_truth

    db = Path(args.db)
    out = Path(args.out)
    truth = load_truth(db_path=db)
    days = [d for d in trading_days(args.start, args.end, db) if truth.get(d)]
    if args.days:
        days = days[: args.days]
    print(f"测试集: {len(days)} 个交易日（{days[0] if days else '-'} ~ {days[-1] if days else '-'}）")

    if args.run:
        from investment_engine.blindtest.replay import run_replay

        stats = run_replay(days, config_dir=Path(args.config_dir), out_path=out,
                           db_path=db, model=args.model)
        print("回放:", stats)

    if args.score or args.report:
        from investment_engine.blindtest.score import (
            direction_scores, load_results, stage_accuracy, stock_scores,
        )

        results = load_results(out)
        stage = stage_accuracy(results, truth)
        dirs = direction_scores(results, config_dir=args.config_dir, db_path=db)
        stocks = stock_scores(results, db_path=db)
        print(f"阶段一致率: {_pct(stage['accuracy'])} (n={stage['samples']})")
        print(f"方向超额命中率: {_pct(dirs['hit_rate'])} (n={dirs['samples']})")
        print(f"标的超额命中率: {_pct(stocks['hit_rate'])} (n={stocks['samples']})")
        if args.report:
            report = _render_report(args, days, stage, dirs, stocks)
            rpt = Path(f"logs/m1-baseline-{date.today():%Y%m%d}.md")
            rpt.write_text(report, encoding="utf-8")
            print(f"报告: {rpt}")

    if args.up_baseline:
        from investment_engine.blindtest.score import load_results
        from investment_engine.blindtest.up_baseline import (
            build_comparison, extract_up_view, find_up_docs, pick_sample_days,
        )

        results = load_results(out)
        sample = pick_sample_days({d: truth[d] for d in days if d in truth}, n=args.up_days)
        views = {}
        for day in sample:
            docs = find_up_docs(day)
            if not docs:
                print(f"  [跳过] {day} 无 UP 当日文档")
                continue
            text = "\n\n".join(d.read_text(encoding="utf-8") for d in docs)
            views[day] = extract_up_view(text, model=args.model)
            print(f"  [{day}] UP stage={views[day]['stage']}")
        rows = build_comparison(results, truth, views)
        comp = Path(f"logs/m1-up-comparison-{date.today():%Y%m%d}.md")
        comp.write_text(_render_comparison(rows), encoding="utf-8")
        print(f"对照表: {comp}（{len(rows)} 天）")
    return 0


def _pct(v) -> str:
    return f"{v:.1%}" if v is not None else "N/A"


def _render_report(args, days, stage, dirs, stocks) -> str:
    lines = [
        f"# M1 盲测基线报告（{date.today():%Y-%m-%d}）",
        "",
        f"- 模型: {args.model}；窗口: {args.start} ~ {args.end}（{len(days)} 交易日）",
        "- 盲测约束: prompt 仅含当日可得客观数据，UP 言论不进 prompt（机械断言通过）",
        "",
        "## 主判据（vs 市场真值）",
        "",
        "| 指标 | 命中率 | 样本数 |",
        "|---|---|---|",
        f"| 市场阶段一致率 | {_pct(stage['accuracy'])} | {stage['samples']} |",
        f"| 方向 5 日超额命中率 | {_pct(dirs['hit_rate'])} | {dirs['samples']} |",
        f"| 标的 5 日超额命中率 | {_pct(stocks['hit_rate'])} | {stocks['samples']} |",
        "",
        "## 分环境段（按真值标签）",
        "",
        "| 阶段 | 样本 | 一致率 |",
        "|---|---|---|",
    ]
    for label, b in sorted(stage["by_label"].items()):
        lines.append(f"| {label} | {b['samples']} | {_pct(b['accuracy'])} |")
    lines += [
        "",
        "## Caveat",
        "",
        "- 单窗口 71 日，结论是基线而非毕业判据；",
        "- 板块资金流/涨停池无历史缓存，未进数据包；知识库为 2026-08-08 现版快照；",
        "- DeepSeek 知识截止与窗口的重叠情况见报告生成时的核查记录；",
        "- vs UP 对照见 logs/m1-up-comparison-*.md（诊断信息，不进命中率）。",
    ]
    return "\n".join(lines)


def _render_comparison(rows) -> str:
    lines = [
        "# M1 vs UP 对照表（诊断用，不进命中率）",
        "",
        "| 日期 | 真值 | AI | UP | verdict |",
        "|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r['date']} | {r['truth']} | {r['ai_stage']} | {r['up_stage'] or '-'} | {r['verdict']} |"
        )
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: dry-run（1 日真实调用）**

前置：`DEEPSEEK_API_KEY` 需已在环境中（没有则向用户要）。

Run: `DEEPSEEK_API_KEY=... .venv/bin/python scripts/blindtest_replay.py --run --days 1`
Expected: `回放: {'done': 1, 'skipped': 0, 'error': 0}`；`evals/blindtest/results.jsonl` 一行，`ok: true`，result 含四选一阶段。若 error，读 JSONL 里的 error 字段排查（key/网络/解析）。

- [ ] **Step 3: 1 日评分冒烟**

Run: `.venv/bin/python scripts/blindtest_replay.py --score --days 1`
Expected: 打印三项指标（n 可能为 0/1，流程不报错即可）。

- [ ] **Step 4: Commit（经用户确认）**

```bash
git add scripts/blindtest_replay.py evals/blindtest
git commit -m "feat(blindtest): 盲测回放 CLI 与 1 日 dry-run e2e"
```

---

## Task 8: 全量跑批 + 基线报告 + 验收

**Files:**
- Create: `logs/m1-baseline-<date>.md`（报告）、`logs/m1-up-comparison-<date>.md`（对照表）

- [ ] **Step 1: 全量回放（71 日，约 10-20 分钟）**

Run: `DEEPSEEK_API_KEY=... .venv/bin/python scripts/blindtest_replay.py --run`
Expected: `done + skipped = 71`，error ≤ 5%（超出则读 JSONL error 字段排查后重跑，断点续跑）。

- [ ] **Step 2: 评分 + 报告**

Run: `.venv/bin/python scripts/blindtest_replay.py --score --report`
Expected: 生成 `logs/m1-baseline-<date>.md`，三项指标齐全、分环境段非空。

- [ ] **Step 3: vs UP 对照**

Run: `DEEPSEEK_API_KEY=... .venv/bin/python scripts/blindtest_replay.py --up-baseline`
Expected: 生成对照表；UP 文档缺失的日期如实打印"跳过"。

- [ ] **Step 4: 知识截止核查**

查 DeepSeek 官方文档（https://api-docs.deepseek.com/）确认 deepseek-chat 当前版本的知识截止日期；若晚于 2026-04，在报告 Caveat 加一行"模型可能见过窗口内信息，命中率偏高估计"。把核查结论写进报告。

- [ ] **Step 5: 全量回归**

Run: `.venv/bin/pytest tests/investment_engine -v` + `PYTHONPATH=third_party/chanpy .venv/bin/pytest tests/ -q`
Expected: investment_engine 全绿；全仓失败集仍 ⊆ 基线失败集（4 个环境型失败）。

- [ ] **Step 6: Commit（经用户确认）**

```bash
git add evals/blindtest logs/m1-baseline-*.md logs/m1-up-comparison-*.md
git commit -m "test(m1): 全量盲测回放与基线命中率报告"
```

---

## 自查记录（写计划后已执行）

**Spec 覆盖：** 测试集/数据包 → Task 3；真值规则（含校准步）→ Task 2；指数补拉 → Task 1；推理契约/防泄漏/断点续跑 → Task 4；三项评分 → Task 5；vs UP 对照 → Task 6+8；报告（分环境段、caveat、知识截止核查）→ Task 7+8。无遗漏。

**Placeholder 扫描：** 所有代码任务含完整实现与测试；Task 1/7/8 为命令型任务含确切命令与预期输出。无 TBD/TODO。

**类型一致性：** `get_klines_range/forward_return` 签名与 M0 backtest 模块一致；`build_daily_pack(day, *, config_dir, db_path)` / `run_replay(days, *, config_dir, out_path, db_path, model, client, sleep_s)` / `load_results(path)` / `stage_accuracy(results, truth)` / `direction_scores(results, *, config_dir, db_path, bench_code, horizon)` / `stock_scores(results, *, db_path, bench_code, horizon)` / `pick_sample_days(truth, n, seed)` / `find_up_docs(day, up_dir)` / `extract_up_view(text, *, client, model)` / `build_comparison(results, truth, up_views)` 在定义任务与使用任务间一致。

**已知风险（如实声明）：**
1. DeepSeek 知识截止若晚于 2026-04，盲测结论偏高估计——Task 8 Step 4 核查并在报告标注；
2. 真值规则是机械近似，与 UP 语境的"冰点/混沌"等细颗粒度状态不完全对齐——M1 先建基线，口径迭代留给 M2 归因；
3. 指数 fetch 走腾讯接口，若当日接口变更导致 Task 1 失败，降级方案：东财 push2his（secid=1.000300），执行时按报错处理；
4. UP 文档日期 token 依赖文件命名习惯，抽样日可能缺文档——如实跳过并在对照表注明。
