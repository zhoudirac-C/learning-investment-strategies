# M2 影子双轨实施计划（每日盲判 + 收盘差异归因 + 提案制回写）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建成 M2 影子双轨管线——每个交易日收盘后 AI 盲出市场判断（阶段+方向+标的），阶段当日评分、方向/标的 T+5 回填，判错日由 DeepSeek 归因分类器产出四型归因与处置提案，提案制人工确认闭环，本机 cron 每日 15:40 运行。

**Architecture:** 新建 `src/investment_engine/shadow/` 子包（predict/maturity/attribute/status/daily 五模块），薄封装复用 M1 `blindtest`（dataset/replay/score/truth）与 M0 `backtest`（history/hit_rate）。设计全文见 `docs/superpowers/specs/2026-08-08-m2-shadow-dual-track-design.md`（**先读它**）。

**Tech Stack:** Python 3.11+ / openai 包（DeepSeek 端点）/ PyYAML / SQLite / pytest。

**调研已确认的关键事实（写代码直接用）：**

| 依赖 | 确认结果 |
|---|---|
| M1 复用接口 | `blindtest.dataset.build_daily_pack(day, *, config_dir, db_path)` / `pack_to_prompt(pack)`；`blindtest.replay.call_deepseek(messages, *, model, max_retries, client)` / `parse_result(raw)` / `DEFAULT_MODEL="deepseek-chat"`；`blindtest.truth.load_truth(db_path, index_code="IDX000300")` → {date: label}；`blindtest.score.direction_scores(results, *, config_dir, db_path, bench_code="IDX000300", horizon)` / `stock_scores(results, *, db_path, bench_code, horizon)`，results 形为 `[{"date","ok":True,"result"}]` |
| M0 复用接口 | `backtest.history.list_trading_days(start, end, db_path)` / `get_klines_range(code, start, end, db_path)` / `coverage(db_path)` |
| 指数新鲜度 | `scripts/fetch_index_klines.py` 的 `fetch_index_tencent(full_code)` 与 `INDEXES` 可直接 import（scripts 是包）；pre_fetch cron 不含指数 |
| 归因触发 | 当日 stage_miss（stage_hit=False）；T+5 到期 direction_miss（当日所有到期方向超额均值 ≤0）。同一 prediction 日两种触发可先后发生，attribution 文件用 `triggers` 列表合并 |
| API key | `.env` 里是小写 `deepseek_api_key`（M1 replay 已兼容）；cron 行需 `set -a; source .env; set +a` |
| pytest | `tests/investment_engine/` 无 `__init__.py`；`.venv/bin/pytest` |

**执行约束（用户指令）：** 不用 subagent、逐任务按本计划 commit message 提交（已授权）、不改 `src/qing_investment/`、分支 feat/m2-shadow（执行前 `git checkout -b feat/m2-shadow`）。

---

## 文件结构

```
src/investment_engine/shadow/
├── __init__.py            # Task 1
├── predict.py             # Task 1：盲判 + 当日 prediction 落盘
├── maturity.py            # Task 2：T+5 到期回填方向/标的超额
├── attribute.py           # Task 3：归因分类器 + 提案生成
├── status.py              # Task 4：完整性报告（4 周日历 + 提案统计）
└── daily.py               # Task 5：每日编排（判→评→回填→归因）
scripts/shadow_daily.py    # Task 6：cron 入口（指数新鲜度 + 就绪等待）
evals/shadow/predictions/  # 每日 prediction（Task 6 e2e 起产出）
evals/shadow/attributions/ # 归因记录
framework/proposals/       # 处置提案（status front-matter）
logs/shadow-status.md      # status 报告
tests/investment_engine/
├── test_predict.py        # Task 1
├── test_maturity.py       # Task 2
├── test_attribute.py      # Task 3
├── test_status.py         # Task 4
└── test_daily.py          # Task 5
```

---

## Task 1: 盲判 predict.py

**Files:**
- Create: `src/investment_engine/shadow/__init__.py`、`src/investment_engine/shadow/predict.py`
- Test: `tests/investment_engine/test_predict.py`

prediction 记录 schema（落盘 `evals/shadow/predictions/<date>.json`）：
`{"date", "result": {market_stage,...}, "raw", "stage_hit": null, "due_scores": null, "status": "pending_maturity"|"error"}`

- [ ] **Step 1: 写失败测试**

```python
# tests/investment_engine/test_predict.py
"""影子双轨盲判测试（mock client，不触网）。"""
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace

from investment_engine.shadow.predict import (
    has_fresh_data, prediction_path, run_predict,
)


def _fake_client(payload: str):
    msg = SimpleNamespace(content=payload)
    choice = SimpleNamespace(message=msg)
    completions = SimpleNamespace(create=lambda **kw: SimpleNamespace(choices=[choice]))
    return SimpleNamespace(chat=SimpleNamespace(completions=completions))


GOOD_JSON = json.dumps({
    "market_stage": "震荡", "stage_reason": "缩量横盘",
    "directions": [{"direction_id": "d1", "reason": "r", "stocks": ["002371"]}],
    "used_patterns": ["upstream_cycle"],
}, ensure_ascii=False)


class TestPredictionPath:
    def test_path_layout(self):
        p = prediction_path("2026-08-07", pred_dir=Path("/tmp/x"))
        assert p.name == "2026-08-07.json"


class TestHasFreshData:
    def test_fresh_when_cache_covers_day(self):
        from qing_investment.kline_cache import init_db, save_klines
        db = Path(tempfile.gettempdir()) / f"test_pred_{id(self)}.db"
        init_db(db_path=db)
        save_klines("002371", [{"code": "002371", "date": "2026-08-07", "open": 1,
                                "high": 1, "low": 1, "close": 1, "volume": 1,
                                "turnover": 1, "amplitude": 1, "pct_change": 1}], db_path=db)
        assert has_fresh_data("2026-08-07", db_path=db) is True
        assert has_fresh_data("2026-08-08", db_path=db) is False
        db.unlink(missing_ok=True)


class TestRunPredict:
    def setup_method(self):
        self.pred_dir = Path(tempfile.mkdtemp(prefix="pred_"))

    def teardown_method(self):
        import shutil
        shutil.rmtree(self.pred_dir, ignore_errors=True)

    def _run(self, monkeypatch, day="2026-08-07", **kw):
        monkeypatch.setattr(
            "investment_engine.shadow.predict.build_daily_pack", lambda d, **k: "PACK")
        monkeypatch.setattr(
            "investment_engine.shadow.predict.pack_to_prompt", lambda p: p)
        monkeypatch.setattr(
            "investment_engine.shadow.predict.call_deepseek",
            lambda m, **k: GOOD_JSON)
        return run_predict(day, config_dir="x", pred_dir=self.pred_dir, **kw)

    def test_writes_prediction(self, monkeypatch):
        r = self._run(monkeypatch)
        assert r["status"] == "pending_maturity"
        rec = json.loads(prediction_path("2026-08-07", pred_dir=self.pred_dir).read_text(encoding="utf-8"))
        assert rec["result"]["market_stage"] == "震荡"
        assert rec["stage_hit"] is None and rec["due_scores"] is None

    def test_idempotent_skip(self, monkeypatch):
        self._run(monkeypatch)
        r2 = self._run(monkeypatch)
        assert r2["status"] == "skipped"

    def test_error_status_retried(self, monkeypatch):
        # 先制造 error 记录
        path = prediction_path("2026-08-07", pred_dir=self.pred_dir)
        path.write_text(json.dumps({"date": "2026-08-07", "status": "error"}), encoding="utf-8")
        r = self._run(monkeypatch)
        assert r["status"] == "pending_maturity"  # error 日被重跑覆盖
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/pytest tests/investment_engine/test_predict.py -v`
Expected: FAIL，`ModuleNotFoundError`

- [ ] **Step 3: 实现**

```python
# src/investment_engine/shadow/__init__.py
"""M2 影子双轨：每日盲判 + 收盘差异归因 + 提案制回写。"""
```

```python
# src/investment_engine/shadow/predict.py
"""每日盲判：复用 blindtest 数据包与 DeepSeek 契约，prediction 按日落盘。"""
from __future__ import annotations

import json
from pathlib import Path

from investment_engine.blindtest.dataset import build_daily_pack, pack_to_prompt
from investment_engine.blindtest.replay import DEFAULT_MODEL, build_messages, call_deepseek, parse_result

PRED_DIR = Path("evals/shadow/predictions")


def prediction_path(day: str, pred_dir: Path = PRED_DIR) -> Path:
    return Path(pred_dir) / f"{day}.json"


def has_fresh_data(day: str, db_path=None) -> bool:
    """缓存最新交易日期 == day 才算就绪。"""
    from investment_engine.backtest.history import list_trading_days

    days = list_trading_days("2000-01-01", day, db_path)
    return bool(days) and days[-1] == day


def run_predict(day: str, *, config_dir, db_path=None, pred_dir: Path = PRED_DIR,
                model: str = DEFAULT_MODEL, client=None) -> dict:
    """对某日盲判。已完成日跳过（幂等）；error 日重跑覆盖。"""
    path = prediction_path(day, pred_dir)
    if path.exists():
        try:
            old = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            old = {}
        if old.get("status") not in (None, "error"):
            return {"status": "skipped", "date": day}

    try:
        pack = build_daily_pack(day, config_dir=Path(config_dir), db_path=db_path)
        text = pack_to_prompt(pack)  # 内含防泄漏断言
        raw = call_deepseek(build_messages(text), model=model, client=client)
        result = parse_result(raw)
        rec = {"date": day, "result": result, "raw": raw,
               "stage_hit": None, "due_scores": None, "status": "pending_maturity"}
    except Exception as e:  # noqa: BLE001 - 失败留 error 记录，次日重跑
        rec = {"date": day, "status": "error", "error": str(e)[:200]}

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
    return rec
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/pytest tests/investment_engine/test_predict.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit（经用户确认）**

```bash
git add src/investment_engine/shadow/__init__.py src/investment_engine/shadow/predict.py tests/investment_engine/test_predict.py
git commit -m "feat(shadow): 每日盲判与 prediction 落盘（复用 blindtest 契约）"
```

---

## Task 2: 到期回填 maturity.py

**Files:**
- Create: `src/investment_engine/shadow/maturity.py`
- Test: `tests/investment_engine/test_maturity.py`

到期判定：以缓存交易日为尺，prediction 日之后满 5 个交易日即到期。回填用 `blindtest.score`（构造单条 results 复用）。

- [ ] **Step 1: 写失败测试**

```python
# tests/investment_engine/test_maturity.py
"""到期回填测试（合成 K 线 + 合成 prediction）。"""
import json
import tempfile
from pathlib import Path

from qing_investment.kline_cache import init_db, save_klines
from investment_engine.shadow.maturity import due_predictions, run_maturity


def _klines(code: str, closes: list[float]) -> list[dict]:
    return [
        {"code": code, "date": f"2026-06-{i + 1:02d}", "open": c, "high": c, "low": c,
         "close": c, "volume": 100, "turnover": 1.0, "amplitude": 1.0, "pct_change": 0.0}
        for i, c in enumerate(closes)
    ]


def _write_pred(pred_dir: Path, day: str, stage="震荡") -> None:
    rec = {"date": day,
           "result": {"market_stage": stage,
                      "directions": [{"direction_id": "d1", "stocks": ["002371"]}],
                      "used_patterns": []},
           "raw": "", "stage_hit": True, "due_scores": None, "status": "pending_maturity"}
    (pred_dir / f"{day}.json").write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")


class TestMaturity:
    def setup_method(self):
        self.db = Path(tempfile.gettempdir()) / f"test_mat_{id(self)}.db"
        init_db(db_path=self.db)
        save_klines("IDX000300", _klines("IDX000300", [4000.0] * 12), db_path=self.db)
        save_klines("002371", _klines("002371", [10.0, 10, 10, 10, 10, 11, 11, 11, 11, 11, 11, 11]), db_path=self.db)
        self.pred_dir = Path(tempfile.mkdtemp(prefix="mat_"))

    def teardown_method(self):
        import shutil
        self.db.unlink(missing_ok=True)
        shutil.rmtree(self.pred_dir, ignore_errors=True)

    def test_due_only_after_5_trading_days(self):
        _write_pred(self.pred_dir, "2026-06-01")
        # 06-01 之后第 4 个交易日（06-05）：未到期
        assert due_predictions("2026-06-05", db_path=self.db, pred_dir=self.pred_dir) == []
        # 第 5 个交易日（06-06）：到期
        due = due_predictions("2026-06-06", db_path=self.db, pred_dir=self.pred_dir)
        assert len(due) == 1

    def test_run_maturity_writes_scores(self, monkeypatch):
        _write_pred(self.pred_dir, "2026-06-01")
        monkeypatch.setattr(
            "investment_engine.shadow.maturity._direction_members",
            lambda config_dir, direction_id: ["002371"],
        )
        stats = run_maturity("2026-06-06", config_dir="x", db_path=self.db, pred_dir=self.pred_dir)
        assert stats["scored"] == 1
        rec = json.loads((self.pred_dir / "2026-06-01.json").read_text(encoding="utf-8"))
        assert rec["status"] == "scored"
        assert rec["due_scores"]["stocks"]["hits"] == 1  # 002371 涨 10% vs 指数 0
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/pytest tests/investment_engine/test_maturity.py -v`
Expected: FAIL，`ModuleNotFoundError`

- [ ] **Step 3: 实现**

```python
# src/investment_engine/shadow/maturity.py
"""到期回填：prediction 满 5 个交易日后补方向/标的超额评分。"""
from __future__ import annotations

import json
from pathlib import Path

from investment_engine.backtest.history import list_trading_days
from investment_engine.blindtest.score import _direction_members, direction_scores, stock_scores
from investment_engine.shadow.predict import PRED_DIR

HORIZON = 5


def due_predictions(day: str, *, db_path=None, pred_dir: Path = PRED_DIR,
                    horizon: int = HORIZON) -> list[Path]:
    """找出截至 day 已到期的 prediction 文件（due_scores 尚未回填）。"""
    if not Path(pred_dir).exists():
        return []
    due = []
    for path in sorted(Path(pred_dir).glob("*.json")):
        try:
            rec = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if rec.get("status") != "pending_maturity" or rec.get("due_scores") is not None:
            continue
        pred_day = rec["date"]
        if pred_day >= day:
            continue
        days_between = list_trading_days(pred_day, day, db_path)
        if len(days_between) - 1 >= horizon:  # 不含 prediction 日本身
            due.append(path)
    return due


def run_maturity(day: str, *, config_dir, db_path=None, pred_dir: Path = PRED_DIR,
                 horizon: int = HORIZON) -> dict:
    """给到期 prediction 回填 due_scores，status 置 scored。"""
    stats = {"scored": 0}
    for path in due_predictions(day, db_path=db_path, pred_dir=pred_dir, horizon=horizon):
        rec = json.loads(path.read_text(encoding="utf-8"))
        results = [{"date": rec["date"], "ok": True, "result": rec["result"]}]
        dirs = direction_scores(results, config_dir=config_dir, db_path=db_path, horizon=horizon)
        stocks = stock_scores(results, db_path=db_path, horizon=horizon)
        rec["due_scores"] = {
            "directions": {k: v for k, v in dirs.items() if k != "details"},
            "stocks": {k: v for k, v in stocks.items() if k != "details"},
            "direction_details": dirs["details"],
        }
        rec["status"] = "scored"
        path.write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
        stats["scored"] += 1
    return stats
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/pytest tests/investment_engine/test_maturity.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit（经用户确认）**

```bash
git add src/investment_engine/shadow/maturity.py tests/investment_engine/test_maturity.py
git commit -m "feat(shadow): T+5 到期回填（方向/标的超额复用 blindtest.score）"
```

---

## Task 3: 归因分类器 attribute.py

**Files:**
- Create: `src/investment_engine/shadow/attribute.py`
- Test: `tests/investment_engine/test_attribute.py`

归因记录（`evals/shadow/attributions/<date>.json`）：`{"date", "triggers": [...], "types": [...], "analysis": "...", "proposal_refs": [...]}`。提案（`framework/proposals/<date>-<type>-<slug>.md`）front-matter 带 `status: open`。

- [ ] **Step 1: 写失败测试**

```python
# tests/investment_engine/test_attribute.py
"""归因分类器测试（mock client）。"""
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from investment_engine.shadow.attribute import (
    KNOWN_DATA_GAPS, parse_attribution, run_attribution,
)


def _fake_client(payload: str):
    msg = SimpleNamespace(content=payload)
    choice = SimpleNamespace(message=msg)
    completions = SimpleNamespace(create=lambda **kw: SimpleNamespace(choices=[choice]))
    return SimpleNamespace(chat=SimpleNamespace(completions=completions))


ATTR_JSON = json.dumps({
    "types": ["数据缺"],
    "analysis": "缺少板块资金流，无法验证主线强度",
    "proposals": [{"type": "data-channel", "title": "补板块资金流通道",
                   "action": "调研东财板块资金流接口并接入缓存"}],
}, ensure_ascii=False)


class TestParseAttribution:
    def test_valid(self):
        a = parse_attribution(ATTR_JSON)
        assert a["types"] == ["数据缺"]
        assert a["proposals"][0]["type"] == "data-channel"

    def test_bad_type_rejected(self):
        bad = json.dumps({"types": ["运气差"], "analysis": "", "proposals": []})
        with pytest.raises(ValueError, match="types"):
            parse_attribution(bad)

    def test_garbage_rejected(self):
        with pytest.raises(ValueError):
            parse_attribution("不是json")


class TestRunAttribution:
    def setup_method(self):
        self.attr_dir = Path(tempfile.mkdtemp(prefix="attr_"))
        self.prop_dir = Path(tempfile.mkdtemp(prefix="prop_"))

    def teardown_method(self):
        import shutil
        shutil.rmtree(self.attr_dir, ignore_errors=True)
        shutil.rmtree(self.prop_dir, ignore_errors=True)

    def test_writes_attribution_and_proposal(self, monkeypatch):
        monkeypatch.setattr(
            "investment_engine.shadow.attribute.call_deepseek",
            lambda m, **kw: ATTR_JSON)
        pred = {"date": "2026-08-07",
                "result": {"market_stage": "震荡", "directions": [], "used_patterns": []},
                "stage_hit": False}
        rec = run_attribution(
            "2026-08-07", trigger="stage_miss", pred=pred, score_info={"truth": "调整"},
            attr_dir=self.attr_dir, proposal_dir=self.prop_dir)
        assert rec["triggers"] == ["stage_miss"]
        assert rec["types"] == ["数据缺"]
        assert len(rec["proposal_refs"]) == 1
        prop = Path(rec["proposal_refs"][0])
        text = prop.read_text(encoding="utf-8")
        assert "status: open" in text and "data-channel" in text

    def test_second_trigger_merges(self, monkeypatch):
        monkeypatch.setattr(
            "investment_engine.shadow.attribute.call_deepseek",
            lambda m, **kw: ATTR_JSON)
        pred = {"date": "2026-08-07",
                "result": {"market_stage": "震荡", "directions": [], "used_patterns": []},
                "stage_hit": False}
        run_attribution("2026-08-07", trigger="stage_miss", pred=pred,
                        score_info={}, attr_dir=self.attr_dir, proposal_dir=self.prop_dir)
        rec = run_attribution("2026-08-07", trigger="direction_miss", pred=pred,
                              score_info={}, attr_dir=self.attr_dir, proposal_dir=self.prop_dir)
        assert rec["triggers"] == ["stage_miss", "direction_miss"]

    def test_known_gaps_listed(self):
        assert "板块资金流" in KNOWN_DATA_GAPS
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/pytest tests/investment_engine/test_attribute.py -v`
Expected: FAIL，`ModuleNotFoundError`

- [ ] **Step 3: 实现**

```python
# src/investment_engine/shadow/attribute.py
"""收盘差异归因：判错日 → DeepSeek 四型分类 → 归因记录 + 处置提案（提案制闭环）。"""
from __future__ import annotations

import json
import re
from pathlib import Path

from investment_engine.blindtest.replay import DEFAULT_MODEL, call_deepseek

ATTR_DIR = Path("evals/shadow/attributions")
PROPOSAL_DIR = Path("framework/proposals")

ATTRIBUTION_TYPES = ("数据缺", "步骤缺", "概念误用", "信息差")
PROPOSAL_TYPES = ("data-channel", "pattern-patch", "glossary-patch", "capability-boundary")
_TYPE_TO_PROPOSAL = {"数据缺": "data-channel", "步骤缺": "pattern-patch",
                     "概念误用": "glossary-patch", "信息差": "capability-boundary"}

# 盲判数据包当前结构性缺失的通道（M1 spec 已如实标注）
KNOWN_DATA_GAPS = ["板块资金流", "涨停池/炸板率", "涨跌家数", "分时数据", "公告/新闻流"]

ATTR_PROMPT = """你是方法论复盘归因员。AI 在没有参考任何人物言论的情况下独立做出了市场判断，事后证明判错了。
请做差异归因，严格输出 JSON：
{{"types": ["数据缺", "步骤缺", "概念误用", "信息差"],
  "analysis": "错因分析（必须引用具体数据项或推理步骤）",
  "proposals": [{{"type": "data-channel|pattern-patch|glossary-patch|capability-boundary",
                "title": "一句话", "action": "具体处置建议"}}]}}
归因口径：数据缺=推理所需数据没有采集通道；步骤缺=方法论缺环节；概念误用=术语/框架用错场景；信息差=依赖非公开渠道信息（不强求，标注能力边界即可）。
types 可多选；proposals 可为空列表。只输出 JSON。

【判错类型】{trigger}
【AI 判断】{ai_result}
【事后真值/评分】{score_info}
【当日在场数据】指数与个股 K 线量价、产业链知识库、术语词典、推理框架索引
【当日缺席数据（已知缺口）】{gaps}
"""


def parse_attribution(raw: str) -> dict:
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"归因输出非 JSON: {raw[:80]!r}") from e
    types = [t for t in (data.get("types") or []) if t in ATTRIBUTION_TYPES]
    if not types:
        raise ValueError(f"types 必须含四型之一: {data.get('types')!r}")
    proposals = []
    for p in (data.get("proposals") or []):
        if not isinstance(p, dict):
            continue
        ptype = p.get("type")
        if ptype not in PROPOSAL_TYPES:
            ptype = _TYPE_TO_PROPOSAL.get(types[0], "capability-boundary")
        proposals.append({"type": ptype, "title": str(p.get("title", ""))[:80],
                          "action": str(p.get("action", ""))[:500]})
    return {"types": types, "analysis": str(data.get("analysis", "")), "proposals": proposals}


def _slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:40] or "note"


def _write_proposals(day: str, attr: dict, proposal_dir: Path) -> list[str]:
    refs = []
    Path(proposal_dir).mkdir(parents=True, exist_ok=True)
    for p in attr["proposals"]:
        path = Path(proposal_dir) / f"{day}-{p['type']}-{_slug(p['title'])}.md"
        path.write_text(
            f"---\ndate: {day}\ntype: {p['type']}\nstatus: open\n"
            f"source: evals/shadow/attributions/{day}.json\n---\n\n"
            f"# {p['title']}\n\n## 分析\n\n{attr['analysis']}\n\n## 处置建议\n\n{p['action']}\n",
            encoding="utf-8",
        )
        refs.append(str(path))
    return refs


def run_attribution(day: str, *, trigger: str, pred: dict, score_info: dict,
                    attr_dir: Path = ATTR_DIR, proposal_dir: Path = PROPOSAL_DIR,
                    model: str = DEFAULT_MODEL, client=None) -> dict:
    """对判错日跑归因。同日消息合并 triggers；提案每次重新生成引用。"""
    prompt = ATTR_PROMPT.format(
        trigger=trigger,
        ai_result=json.dumps(pred.get("result", {}), ensure_ascii=False),
        score_info=json.dumps(score_info, ensure_ascii=False),
        gaps="、".join(KNOWN_DATA_GAPS),
    )
    raw = call_deepseek([{"role": "user", "content": prompt}], model=model, client=client)
    attr = parse_attribution(raw)

    path = Path(attr_dir) / f"{day}.json"
    triggers = [trigger]
    if path.exists():
        try:
            old = json.loads(path.read_text(encoding="utf-8"))
            triggers = list(dict.fromkeys(old.get("triggers", []) + [trigger]))
        except json.JSONDecodeError:
            pass
    refs = _write_proposals(day, attr, proposal_dir)
    rec = {"date": day, "triggers": triggers, "types": attr["types"],
           "analysis": attr["analysis"], "proposal_refs": refs}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
    return rec
```

注意：ATTR_PROMPT 含 `.format` 占位，其中 JSON 示例的大括号已用 `{{}}` 转义——照抄时留意。

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/pytest tests/investment_engine/test_attribute.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit（经用户确认）**

```bash
git add src/investment_engine/shadow/attribute.py tests/investment_engine/test_attribute.py
git commit -m "feat(shadow): 归因分类器与提案制闭环（四型 → proposals）"
```

---

## Task 4: 完整性报告 status.py

**Files:**
- Create: `src/investment_engine/shadow/status.py`
- Test: `tests/investment_engine/test_status.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/investment_engine/test_status.py
"""影子双轨完整性报告测试。"""
import json
import tempfile
from pathlib import Path

from investment_engine.shadow.status import collect_status, render_status


class TestCollectStatus:
    def setup_method(self):
        self.pred_dir = Path(tempfile.mkdtemp(prefix="sp_"))
        self.attr_dir = Path(tempfile.mkdtemp(prefix="sa_"))
        self.prop_dir = Path(tempfile.mkdtemp(prefix="spr_"))

    def teardown_method(self):
        import shutil
        for d in (self.pred_dir, self.attr_dir, self.prop_dir):
            shutil.rmtree(d, ignore_errors=True)

    def _pred(self, day, stage_hit=True, status="scored"):
        rec = {"date": day, "result": {"market_stage": "震荡"},
               "stage_hit": stage_hit, "due_scores": {}, "status": status}
        (self.pred_dir / f"{day}.json").write_text(json.dumps(rec), encoding="utf-8")

    def test_calendar_and_counts(self):
        self._pred("2026-08-03", stage_hit=True)
        self._pred("2026-08-04", stage_hit=False)
        (self.attr_dir / "2026-08-04.json").write_text(
            json.dumps({"date": "2026-08-04", "triggers": ["stage_miss"], "types": ["数据缺"]}),
            encoding="utf-8")
        (self.prop_dir / "2026-08-04-data-channel-x.md").write_text(
            "---\nstatus: open\n---\n", encoding="utf-8")
        s = collect_status(pred_dir=self.pred_dir, attr_dir=self.attr_dir,
                           proposal_dir=self.prop_dir)
        assert s["days_total"] == 2
        assert s["days_complete"] == 2  # 判对日无需归因；判错日已有归因
        assert s["proposals"]["open"] == 1

    def test_miss_without_attribution_is_incomplete(self):
        self._pred("2026-08-04", stage_hit=False)
        s = collect_status(pred_dir=self.pred_dir, attr_dir=self.attr_dir,
                           proposal_dir=self.prop_dir)
        assert s["days_complete"] == 0

    def test_render_contains_sections(self):
        self._pred("2026-08-03")
        s = collect_status(pred_dir=self.pred_dir, attr_dir=self.attr_dir,
                           proposal_dir=self.prop_dir)
        text = render_status(s)
        assert "影子双轨" in text and "提案" in text
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/pytest tests/investment_engine/test_status.py -v`
Expected: FAIL，`ModuleNotFoundError`

- [ ] **Step 3: 实现**

```python
# src/investment_engine/shadow/status.py
"""影子双轨完整性报告：4 周日历 + 提案 open/closed 统计。"""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

from investment_engine.shadow.attribute import ATTR_DIR, PROPOSAL_DIR
from investment_engine.shadow.predict import PRED_DIR

STATUS_PATH = Path("logs/shadow-status.md")


def _load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def collect_status(*, pred_dir: Path = PRED_DIR, attr_dir: Path = ATTR_DIR,
                   proposal_dir: Path = PROPOSAL_DIR) -> dict:
    days = []
    complete = 0
    for path in sorted(Path(pred_dir).glob("*.json")):
        rec = _load_json(path)
        if not rec.get("date"):
            continue
        day = rec["date"]
        stage_hit = rec.get("stage_hit")
        needs_attr = stage_hit is False
        has_attr = (Path(attr_dir) / f"{day}.json").exists()
        ok = (not needs_attr) or has_attr
        complete += int(ok)
        days.append({"date": day, "stage_hit": stage_hit, "status": rec.get("status"),
                     "attributed": has_attr, "complete": ok})

    proposals = {"open": 0, "applied": 0, "rejected": 0, "open_files": []}
    if Path(proposal_dir).exists():
        for p in sorted(Path(proposal_dir).glob("*.md")):
            m = re.search(r"status:\s*(\w+)", p.read_text(encoding="utf-8"))
            st = m.group(1) if m else "open"
            proposals[st] = proposals.get(st, 0) + 1
            if st == "open":
                proposals["open_files"].append(p.name)
    return {"days_total": len(days), "days_complete": complete,
            "days": days, "proposals": proposals}


def render_status(stats: dict) -> str:
    lines = [
        f"# 影子双轨完整性报告（{date.today():%Y-%m-%d}）",
        "",
        f"- 记录日数: {stats['days_total']}，完整: {stats['days_complete']}",
        f"- 提案: open {stats['proposals']['open']} / applied {stats['proposals'].get('applied', 0)} / rejected {stats['proposals'].get('rejected', 0)}",
        "",
        "| 日期 | 阶段判定 | 状态 | 归因 | 完整 |",
        "|---|---|---|---|---|",
    ]
    for d in stats["days"]:
        hit = {True: "对", False: "错", None: "-"}[d["stage_hit"]]
        lines.append(f"| {d['date']} | {hit} | {d['status']} | {'有' if d['attributed'] else '-'} | {'✅' if d['complete'] else '❌'} |")
    if stats["proposals"]["open_files"]:
        lines += ["", "## 待处理提案（open 置顶）", ""]
        lines += [f"- {n}" for n in stats["proposals"]["open_files"]]
    return "\n".join(lines)


def write_status(path: Path = STATUS_PATH, **kw) -> Path:
    stats = collect_status(**kw)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_status(stats), encoding="utf-8")
    return path
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/pytest tests/investment_engine/test_status.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit（经用户确认）**

```bash
git add src/investment_engine/shadow/status.py tests/investment_engine/test_status.py
git commit -m "feat(shadow): 完整性报告（4 周日历 + 提案统计）"
```

---

## Task 5: 每日编排 daily.py

**Files:**
- Create: `src/investment_engine/shadow/daily.py`
- Test: `tests/investment_engine/test_daily.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/investment_engine/test_daily.py
"""每日编排测试（全 mock）。"""
import json
import tempfile
from pathlib import Path

from investment_engine.shadow.daily import run


class TestDailyRun:
    def setup_method(self):
        self.root = Path(tempfile.mkdtemp(prefix="daily_"))
        self.pred_dir = self.root / "pred"
        self.attr_dir = self.root / "attr"
        self.prop_dir = self.root / "prop"

    def teardown_method(self):
        import shutil
        shutil.rmtree(self.root, ignore_errors=True)

    def _run(self, monkeypatch, **overrides):
        def fake_predict(day, **kw):
            rec = {"date": day, "result": {"market_stage": "震荡"}, "raw": "",
                   "stage_hit": None, "due_scores": None, "status": "pending_maturity"}
            pred_dir = Path(kw["pred_dir"])
            pred_dir.mkdir(parents=True, exist_ok=True)
            (pred_dir / f"{day}.json").write_text(json.dumps(rec), encoding="utf-8")
            return rec

        monkeypatch.setattr("investment_engine.shadow.daily.has_fresh_data",
                            overrides.get("fresh", lambda day, db_path=None: True))
        monkeypatch.setattr("investment_engine.shadow.daily.run_predict",
                            overrides.get("predict", fake_predict))
        monkeypatch.setattr("investment_engine.shadow.daily.load_truth",
                            overrides.get("truth", lambda **kw: {"2026-08-07": "震荡"}))
        monkeypatch.setattr("investment_engine.shadow.daily.run_maturity",
                            overrides.get("maturity", lambda day, **kw: {"scored": 0}))
        monkeypatch.setattr("investment_engine.shadow.daily.run_attribution",
                            overrides.get("attribute", lambda day, **kw: {"date": day}))
        return run("2026-08-07", config_dir="x",
                   pred_dir=self.pred_dir, attr_dir=self.attr_dir, proposal_dir=self.prop_dir)

    def test_no_data_exits_clean(self, monkeypatch):
        r = self._run(monkeypatch, fresh=lambda day, db_path=None: False)
        assert r["status"] == "no_data"

    def test_happy_path_stage_hit(self, monkeypatch):
        r = self._run(monkeypatch)
        assert r["status"] == "ok"
        assert r["stage_hit"] is True
        assert r["attributed"] is False  # 判对不归因

    def test_stage_miss_triggers_attribution(self, monkeypatch):
        r = self._run(monkeypatch, truth=lambda **kw: {"2026-08-07": "恐慌"})
        assert r["stage_hit"] is False
        assert r["attributed"] is True

    def test_prediction_error_propagates(self, monkeypatch):
        r = self._run(monkeypatch, predict=lambda day, **kw: {"date": day, "status": "error"})
        assert r["status"] == "predict_error"
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/pytest tests/investment_engine/test_daily.py -v`
Expected: FAIL，`ModuleNotFoundError`

- [ ] **Step 3: 实现**

```python
# src/investment_engine/shadow/daily.py
"""每日编排：数据就绪检查 → 盲判 → 当日阶段评分 → 到期回填 → 判错归因。"""
from __future__ import annotations

import json
from pathlib import Path

from investment_engine.blindtest.truth import load_truth
from investment_engine.shadow.attribute import ATTR_DIR, PROPOSAL_DIR, run_attribution
from investment_engine.shadow.maturity import run_maturity
from investment_engine.shadow.predict import PRED_DIR, has_fresh_data, prediction_path, run_predict


def _direction_missed(rec: dict) -> bool:
    """到期方向超额均值 ≤0 视为 direction_miss。"""
    details = (rec.get("due_scores") or {}).get("direction_details") or []
    if not details:
        return False
    excess = [d["dir_ret"] - d["bench_ret"] for d in details]
    return sum(excess) / len(excess) <= 0


def run(day: str, *, config_dir, db_path=None,
        pred_dir: Path = PRED_DIR, attr_dir: Path = ATTR_DIR,
        proposal_dir: Path = PROPOSAL_DIR, model: str = "deepseek-chat",
        client=None) -> dict:
    if not has_fresh_data(day, db_path=db_path):
        return {"date": day, "status": "no_data"}

    pred = run_predict(day, config_dir=config_dir, db_path=db_path,
                       pred_dir=pred_dir, model=model, client=client)
    if pred.get("status") == "error":
        return {"date": day, "status": "predict_error", "error": pred.get("error")}

    # 当日阶段评分（skipped 日读已有记录）
    rec_path = prediction_path(day, pred_dir)
    rec = json.loads(rec_path.read_text(encoding="utf-8"))
    if rec.get("stage_hit") is None:
        truth = load_truth(db_path=db_path)
        label = truth.get(day)
        if label is not None:
            rec["stage_hit"] = rec["result"].get("market_stage") == label
            rec_path.write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")

    # 到期回填 + 到期日的 direction_miss 归因
    mat = run_maturity(day, config_dir=config_dir, db_path=db_path, pred_dir=pred_dir)
    attributed = []

    if rec.get("stage_hit") is False:
        run_attribution(day, trigger="stage_miss", pred=rec,
                        score_info={"truth": load_truth(db_path=db_path).get(day)},
                        attr_dir=attr_dir, proposal_dir=proposal_dir,
                        model=model, client=client)
        attributed.append(day)

    # 到期且方向判错的往日归因
    if mat["scored"]:
        for path in sorted(Path(pred_dir).glob("*.json")):
            old = json.loads(path.read_text(encoding="utf-8"))
            if old.get("status") == "scored" and _direction_missed(old) \
                    and not (Path(attr_dir) / f"{old['date']}.json").exists():
                run_attribution(old["date"], trigger="direction_miss", pred=old,
                                score_info=old.get("due_scores") or {},
                                attr_dir=attr_dir, proposal_dir=proposal_dir,
                                model=model, client=client)
                attributed.append(old["date"])

    return {"date": day, "status": "ok", "stage_hit": rec.get("stage_hit"),
            "matured": mat["scored"], "attributed": bool(attributed),
            "attributed_days": attributed}
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/pytest tests/investment_engine/test_daily.py -v`
Expected: 4 passed（测试 fake_predict 已落盘最小记录，daily 编排直接可读）

- [ ] **Step 5: Commit（经用户确认）**

```bash
git add src/investment_engine/shadow/daily.py tests/investment_engine/test_daily.py
git commit -m "feat(shadow): 每日编排（判→评→回填→归因）"
```

---

## Task 6: cron 入口 scripts/shadow_daily.py + e2e

**Files:**
- Create: `scripts/shadow_daily.py`

- [ ] **Step 1: 写脚本**

```python
#!/usr/bin/env python
"""M2 影子双轨每日入口（cron 15:40 调用）。

自含：补当日指数 K → 等 K 线就绪（3 次 × 2 分钟）→ daily.run(当日)。
节假日/无新数据自然退出 0。手动补跑: python scripts/shadow_daily.py --date 2026-08-07
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from investment_engine.shadow.daily import run
from investment_engine.shadow.predict import has_fresh_data
from qing_investment.kline_cache import init_db
from scripts.fetch_index_klines import INDEXES, fetch_index_tencent
from qing_investment.kline_cache import save_klines


def ensure_indexes(db_path=None) -> None:
    for alias, full_code in INDEXES.items():
        kl = fetch_index_tencent(full_code)
        if kl:
            save_klines(alias, kl, db_path=db_path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="影子双轨每日任务")
    parser.add_argument("--date", default=date.today().isoformat())
    parser.add_argument("--config-dir", default="config/stock_monitor")
    parser.add_argument("--db", default="infra/data/kline_cache.db")
    parser.add_argument("--wait-retries", type=int, default=3)
    args = parser.parse_args(argv)

    db = Path(args.db)
    init_db(db_path=db)
    ensure_indexes(db_path=db)

    for attempt in range(1, args.wait_retries + 1):
        if has_fresh_data(args.date, db_path=db):
            break
        print(f"[wait] {args.date} 尚无新 K 线（{attempt}/{args.wait_retries}）")
        if attempt < args.wait_retries:
            time.sleep(120)
    else:
        print(f"[skip] {args.date} 无新数据（节假日或拉取失败），退出")
        return 0

    summary = run(args.date, config_dir=Path(args.config_dir), db_path=db)
    print("[daily]", summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: e2e（真实一日）**

前置：`.env` 有 `deepseek_api_key`。

Run: `set -a; source .env; set +a; .venv/bin/python scripts/shadow_daily.py --date 2026-08-07`
Expected: `[daily] {'date': '2026-08-07', 'status': 'ok', ...}`；`evals/shadow/predictions/2026-08-07.json` 生成且 stage_hit 非 None；若判错则同时有归因与提案。再跑一遍应 `status: skipped` 幂等（daily 返回 ok 且 stage_hit 不变、不重复调 API——看日志无新调用即可，或直接观察文件 mtime 不变）。

- [ ] **Step 3: 生成 status 报告**

```bash
.venv/bin/python -c "
import sys; sys.path.insert(0, 'src')
from investment_engine.shadow.status import write_status
print(write_status())
"
```
Expected: 输出 `logs/shadow-status.md` 路径，内容含当日行。

- [ ] **Step 4: Commit（经用户确认）**

```bash
git add scripts/shadow_daily.py evals/shadow logs/shadow-status.md
git commit -m "feat(shadow): cron 入口与首日 e2e（2026-08-07）"
```

---

## Task 7: cron 挂接 + ops 文档更新 + 全量回归

**Files:**
- Modify: `docs/tasks/kline-daily-fetch-ops.md`（登记新 cron 与注销命令）
- Modify: `framework/proposals/`（由 e2e 产出，若为空目录建 `.gitkeep`）

- [ ] **Step 1: 挂接 cron（工作日 15:40）**

```bash
(crontab -l 2>/dev/null; echo '40 15 * * 1-5 cd /Users/cong.zhou/Documents/quantitative/learning-investment-strategies && set -a && source .env && set +a && .venv/bin/python scripts/shadow_daily.py >> log/shadow_daily.log 2>&1') > /tmp/m2_cron && crontab /tmp/m2_cron && crontab -l
```
Expected: 两条任务（15:35 pre_fetch、15:40 shadow_daily）。若 `crontab` 命令挂住（本会话 16:10 曾发生一次，原因不明，文件方式重试即成功），改用写临时文件 `crontab /tmp/m2_cron` 形式——上方已是文件形式。

- [ ] **Step 2: 更新 ops 文档**

在 `docs/tasks/kline-daily-fetch-ops.md`「现状」节追加第二条 cron 的说明，并把「注销义务」命令改为：

```bash
crontab -l | grep -v 'pre_fetch_klines\|shadow_daily' | crontab -
```

- [ ] **Step 3: proposals 目录留位**

```bash
mkdir -p framework/proposals && touch framework/proposals/.gitkeep
```

- [ ] **Step 4: 全量回归**

Run: `.venv/bin/pytest tests/investment_engine -v` + `PYTHONPATH=third_party/chanpy .venv/bin/pytest tests/ -q`
Expected: investment_engine 全绿；全仓失败集 ⊆ 基线 4 个环境型失败。

- [ ] **Step 5: Commit（经用户确认）**

```bash
git add docs/tasks/kline-daily-fetch-ops.md framework/proposals/.gitkeep
git commit -m "chore(shadow): 每日 cron 挂接与 ops 文档更新"
```

---

## 自查记录（写计划后已执行）

**Spec 覆盖：** 盲判 → Task 1；当日阶段评分 → Task 5（编排内）；T+5 回填 → Task 2；归因分类器+提案 → Task 3；完整性报告 → Task 4；cron 入口（指数新鲜度+就绪等待）→ Task 6；cron 挂接+ops 注销义务 → Task 7。无遗漏。

**Placeholder 扫描：** 全部代码任务含完整实现与测试；命令型步骤含确切命令与预期。无 TBD/TODO。

**类型一致性：** `run_predict(day, *, config_dir, db_path, pred_dir, model, client)` / `due_predictions(day, *, db_path, pred_dir, horizon)` / `run_maturity(day, *, config_dir, db_path, pred_dir, horizon)` / `run_attribution(day, *, trigger, pred, score_info, attr_dir, proposal_dir, model, client)` / `collect_status(*, pred_dir, attr_dir, proposal_dir)` / `daily.run(day, *, config_dir, db_path, pred_dir, attr_dir, proposal_dir, model, client)` 在定义与使用处一致；复用接口（blindtest/backtest）签名已逐一对照 M0/M1 源码。

**已知风险（如实声明）：**
1. daily.py 编排里 mock 与落盘的配合（Task 5 Step 4 已给处置指引）；
2. cron 两条任务间隔 5 分钟，pre_fetch 超时未完成时 shadow 的就绪等待（3×2 分钟）兜底，仍失败则当日缺失、周报暴露——可接受；
3. 归因分类器对"步骤缺"的判断质量依赖 prompt 里 used_patterns 信息，M2 运行中如发现归因空泛，迭代 ATTR_PROMPT（属提案制下的正常运营动作）。
