# M3 前置：pattern validation 回填与提案机制 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 M1 盲测结果按 used_patterns 归因回填进 `framework/reasoning-patterns.yaml` 的 validation 区块，并建立"生成器 → 人工评审 → 执行器"的提案制回写机制。

**Architecture:** 新包 `src/investment_engine/pattern_eval/`（attribute / bucket / proposal / apply 四模块，纯函数优先）+ 两个 thin script。指标计算复用 `blindtest/score.py`（口径与 M1 基线一致）；apply 用 ruamel round-trip 保格式，双次 `pattern_schema` 校验。

**Tech Stack:** Python 3.13、PyYAML、ruamel.yaml（新增声明）、pytest。

**Spec:** `docs/superpowers/specs/2026-08-08-m3-pattern-validation-design.md`

**约束（用户明确要求）：**
- 不用 subagent；逐任务按给定 commit message 提交（已授权，不 push）
- 不改 `src/qing_investment/`；`tests/investment_engine/` 不放 `__init__.py`
- 测试用 `.venv/bin/pytest`；commit 前单独跑测试确认退出码（不要 `| tail` 后接 `&& git commit`）
- 不用 `git add -f`
- 分支 `feat/m3-pattern-validation` 已 checkout

**现状事实（实现依据，已核实）：**
- `score.py`：`load_results(path)` 只返回 `ok=True` 行；`stage_accuracy(results, truth)` 返回 `{samples, hits, accuracy, by_label{label:{samples,hits,accuracy}}}`；`direction_scores(results, *, config_dir, db_path=None, ...)` 与 `stock_scores(results, *, db_path=None, ...)` 返回 `{samples, hits, hit_rate, details}`
- `truth.load_truth(db_path=None, index_code="IDX000300")` 返回 `{date: label}`
- `pattern_schema.validate_patterns_file(data)` 校验整份 yaml（`historical_hit_rate` 只允许 null/数值/"pending-m1"）；ruamel 的 CommentedMap/CommentedSeq 是 dict/list 子类，可直接传入
- yaml 现值：`technical_timing`/`operation_strategy` 已是 0.5182（M0 回测）；其余 8 个 `pending-m1`；文件无任何注释
- ruamel.yaml 0.19.1 已在 .venv，但未声明进 pyproject（Task 4 补上）

---

### Task 1: attribute.py — per-pattern 指标归因

**Files:**
- Create: `src/investment_engine/pattern_eval/__init__.py`
- Create: `src/investment_engine/pattern_eval/attribute.py`
- Test: `tests/investment_engine/test_pattern_eval_attribute.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/investment_engine/test_pattern_eval_attribute.py
"""attribute：按 used_patterns 分组与 per-pattern 指标。"""

from investment_engine.pattern_eval.attribute import group_by_pattern, pattern_metrics


def _row(day, stage, patterns):
    return {"date": day, "ok": True,
            "result": {"market_stage": stage, "directions": [],
                       "used_patterns": patterns}}


def test_group_by_pattern_multi_attribution():
    results = [
        _row("2026-08-03", "震荡", ["sector_rotation", "mainline_identification"]),
        _row("2026-08-04", "震荡", ["sector_rotation"]),
        _row("2026-08-05", "震荡", []),               # 空列表不归因
        {"date": "2026-08-06", "ok": True, "result": {"market_stage": "震荡"}},  # 缺字段不归因
    ]
    grouped = group_by_pattern(results)
    assert set(grouped) == {"sector_rotation", "mainline_identification"}
    assert len(grouped["sector_rotation"]) == 2
    assert len(grouped["mainline_identification"]) == 1


def test_pattern_metrics_uses_scorers():
    results = [
        _row("2026-08-03", "震荡", ["sector_rotation"]),
        _row("2026-08-04", "调整", ["sector_rotation"]),
        _row("2026-08-05", "震荡", ["upstream_cycle"]),
    ]
    truth = {"2026-08-03": "震荡", "2026-08-04": "震荡", "2026-08-05": "调整"}

    def fake_direction(rs):
        return {"samples": len(rs) * 2, "hits": len(rs), "hit_rate": 0.5, "details": []}

    def fake_stock(rs):
        return {"samples": len(rs), "hits": 0, "hit_rate": 0.0, "details": []}

    metrics = pattern_metrics(results, truth=truth,
                              direction_scorer=fake_direction, stock_scorer=fake_stock)
    sr = metrics["sector_rotation"]
    assert sr["days_used"] == 2
    # 08-03 预测震荡=真值命中；08-04 预测调整≠震荡 → 1/2
    assert sr["stage"] == {"rate": 0.5, "n": 2}
    assert sr["direction"] == {"rate": 0.5, "n": 4}
    assert sr["stock"] == {"rate": 0.0, "n": 2}
    assert sr["regime"] == {"震荡": {"rate": 0.5, "n": 2}}
    uc = metrics["upstream_cycle"]
    assert uc["stage"] == {"rate": 0.0, "n": 1}   # 预测震荡≠调整
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/pytest tests/investment_engine/test_pattern_eval_attribute.py -q`
Expected: FAIL（ModuleNotFoundError: investment_engine.pattern_eval）

- [ ] **Step 3: 实现**

```python
# src/investment_engine/pattern_eval/__init__.py
"""M3 前置：盲测结果按模式归因、分桶与提案制回写。"""
```

```python
# src/investment_engine/pattern_eval/attribute.py
"""按 used_patterns 归因的 per-pattern 盲测指标（使用归因，不隔离单模式贡献）。"""
from __future__ import annotations

from investment_engine.blindtest.score import (
    direction_scores,
    stage_accuracy,
    stock_scores,
)


def group_by_pattern(results: list[dict]) -> dict[str, list[dict]]:
    """同日多模式共用时，当日归入每个模式；无 used_patterns 的日子不归因。"""
    grouped: dict[str, list[dict]] = {}
    for r in results:
        for pid in (r.get("result") or {}).get("used_patterns") or []:
            grouped.setdefault(pid, []).append(r)
    return grouped


def pattern_metrics(results: list[dict], *, truth: dict[str, str],
                    config_dir=None, db_path=None,
                    direction_scorer=None, stock_scorer=None) -> dict:
    """每个被使用模式的三指标 + 分环境段一致率，口径同 M1 基线。

    direction/stock scorer 可注入（测试用假 scorer，真实跑用 score.py）。
    """
    dir_score = direction_scorer or (
        lambda rs: direction_scores(rs, config_dir=config_dir, db_path=db_path))
    stk_score = stock_scorer or (
        lambda rs: stock_scores(rs, db_path=db_path))
    metrics = {}
    for pid, rs in sorted(group_by_pattern(results).items()):
        stage = stage_accuracy(rs, truth)
        direction = dir_score(rs)
        stock = stk_score(rs)
        metrics[pid] = {
            "days_used": len(rs),
            "stage": {"rate": stage["accuracy"], "n": stage["samples"]},
            "direction": {"rate": direction["hit_rate"], "n": direction["samples"]},
            "stock": {"rate": stock["hit_rate"], "n": stock["samples"]},
            "regime": {label: {"rate": b["accuracy"], "n": b["samples"]}
                       for label, b in stage["by_label"].items()},
        }
    return metrics
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/pytest tests/investment_engine/test_pattern_eval_attribute.py -q`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add src/investment_engine/pattern_eval/ tests/investment_engine/test_pattern_eval_attribute.py
git commit -m "feat(pattern-eval): 按 used_patterns 归因的 per-pattern 指标"
```

---

### Task 2: bucket.py — 宽松三桶分桶

**Files:**
- Create: `src/investment_engine/pattern_eval/bucket.py`
- Test: `tests/investment_engine/test_pattern_eval_bucket.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/investment_engine/test_pattern_eval_bucket.py
"""bucket：宽松三桶规则与主指标映射。"""

import pytest

from investment_engine.pattern_eval.bucket import (
    PRIMARY_METRIC, bucket_one, bucketize,
)


def test_primary_metric_covers_six_used_patterns():
    assert set(PRIMARY_METRIC) == {
        "sentiment_cycle", "mainline_identification", "sector_rotation",
        "upstream_cycle", "technical_timing", "ai_industry_chain",
    }


@pytest.mark.parametrize("kind,rate,n,expected", [
    ("stage", 0.70, 20, "达标"),      # 毕业线边界
    ("stage", 0.699, 20, "待观察"),
    ("stage", 0.70, 19, "待观察"),    # n 边界
    ("direction", 0.60, 20, "达标"),
    ("stock", 0.55, 20, "达标"),
    ("stock", 0.549, 20, "待观察"),
    ("stage", 0.499, 20, "证伪"),     # 50% 随机线以下
    ("direction", 0.50, 20, "待观察"),  # 恰好 50% 不证伪
    ("stage", None, 30, "待观察"),    # 无指标
])
def test_bucket_one_boundaries(kind, rate, n, expected):
    assert bucket_one(kind, rate, n) == expected


def test_bucketize_unused_and_unknown():
    metrics = {
        "sector_rotation": {
            "days_used": 25,
            "stage": {"rate": 0.6, "n": 25},
            "direction": {"rate": 0.62, "n": 50},
            "stock": {"rate": 0.5, "n": 50},
            "regime": {},
        },
        "brand_new_pattern": {   # 不在 PRIMARY_METRIC 的新模式
            "days_used": 3,
            "stage": {"rate": 1.0, "n": 3},
            "direction": {"rate": 1.0, "n": 6},
            "stock": {"rate": 1.0, "n": 6},
            "regime": {},
        },
    }
    out = bucketize(metrics, ["sector_rotation", "macro_transmission", "brand_new_pattern"])
    assert out["sector_rotation"] == {"bucket": "达标", "primary_metric": "direction"}
    assert out["macro_transmission"] == {"bucket": "unused", "note": "m1 未使用"}
    assert out["brand_new_pattern"]["bucket"] == "待观察"
    assert "无主指标映射" in out["brand_new_pattern"]["note"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/pytest tests/investment_engine/test_pattern_eval_bucket.py -q`
Expected: FAIL（ModuleNotFoundError / ImportError）

- [ ] **Step 3: 实现**

```python
# src/investment_engine/pattern_eval/bucket.py
"""宽松三桶分桶（阈值定义出处：spec 2026-08-08-m3-pattern-validation-design.md）。"""
from __future__ import annotations

# 主指标 = 各模式 steps 最终产出物对应的指标，决定桶归属
PRIMARY_METRIC = {
    "sentiment_cycle": "stage",
    "mainline_identification": "direction",
    "sector_rotation": "direction",
    "upstream_cycle": "direction",
    "technical_timing": "stock",
    "ai_industry_chain": "stock",
}
# 毕业线：阶段 70%/方向 60% 出自主计划 10.4；标的 55% 由本模块定义（spec 已录）
GRADUATION_LINE = {"stage": 0.70, "direction": 0.60, "stock": 0.55}
FALSIFY_LINE = 0.50   # 掷硬币水平以下才证伪
MIN_SAMPLES = 20

BUCKET_PASS = "达标"
BUCKET_WATCH = "待观察"
BUCKET_FAIL = "证伪"
BUCKET_UNUSED = "unused"


def bucket_one(metric_kind: str, rate: float | None, n: int) -> str:
    if rate is None or n < MIN_SAMPLES:
        return BUCKET_WATCH
    if rate < FALSIFY_LINE:
        return BUCKET_FAIL
    if rate >= GRADUATION_LINE[metric_kind]:
        return BUCKET_PASS
    return BUCKET_WATCH


def bucketize(metrics: dict, all_pattern_ids) -> dict:
    """{pattern_id: {bucket, primary_metric?}}；无指标模式标 unused。"""
    out = {}
    for pid in all_pattern_ids:
        m = metrics.get(pid)
        if m is None:
            out[pid] = {"bucket": BUCKET_UNUSED, "note": "m1 未使用"}
            continue
        kind = PRIMARY_METRIC.get(pid)
        if kind is None:
            out[pid] = {"bucket": BUCKET_WATCH, "note": "无主指标映射，仅记录指标"}
            continue
        out[pid] = {"bucket": bucket_one(kind, m[kind]["rate"], m[kind]["n"]),
                    "primary_metric": kind}
    return out
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/pytest tests/investment_engine/test_pattern_eval_bucket.py -q`
Expected: 12 passed

- [ ] **Step 5: Commit**

```bash
git add src/investment_engine/pattern_eval/bucket.py tests/investment_engine/test_pattern_eval_bucket.py
git commit -m "feat(pattern-eval): 宽松三桶分桶规则"
```

---

### Task 3: proposal.py — 提案生成器

**Files:**
- Create: `src/investment_engine/pattern_eval/proposal.py`
- Test: `tests/investment_engine/test_pattern_eval_proposal.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/investment_engine/test_pattern_eval_proposal.py
"""proposal：提案渲染（evidence 全量留档，changes 只含落库补丁）。"""
import yaml

from investment_engine.pattern_eval.proposal import build_proposal, write_proposal


def _fixtures():
    metrics = {
        "sector_rotation": {
            "days_used": 25,
            "stage": {"rate": 0.6, "n": 25},
            "direction": {"rate": 0.62, "n": 50},
            "stock": {"rate": 0.5, "n": 50},
            "regime": {"震荡": {"rate": 0.6, "n": 15}, "调整": {"rate": 0.6, "n": 10}},
        },
        "sentiment_cycle": {
            "days_used": 30,
            "stage": {"rate": 0.4, "n": 30},
            "direction": {"rate": 0.5, "n": 40},
            "stock": {"rate": 0.5, "n": 40},
            "regime": {"震荡": {"rate": 0.4, "n": 30}},
        },
        "technical_timing": {
            "days_used": 10,
            "stage": {"rate": 0.5, "n": 10},
            "direction": {"rate": 0.5, "n": 20},
            "stock": {"rate": 0.45, "n": 20},
            "regime": {},
        },
    }
    buckets = {
        "sector_rotation": {"bucket": "达标", "primary_metric": "direction"},
        "sentiment_cycle": {"bucket": "证伪", "primary_metric": "stage"},
        "technical_timing": {"bucket": "待观察", "primary_metric": "stock"},
        "others": {"bucket": "unused", "note": "m1 未使用"},
    }
    patterns = [
        {"pattern_id": "sector_rotation",
         "validation": {"historical_hit_rate": "pending-m1",
                        "applicable_regime": None, "known_failures": []}},
        {"pattern_id": "sentiment_cycle",
         "validation": {"historical_hit_rate": "pending-m1",
                        "applicable_regime": None, "known_failures": []}},
        {"pattern_id": "technical_timing",
         "validation": {"historical_hit_rate": 0.5182,
                        "applicable_regime": None, "known_failures": []}},
        {"pattern_id": "others",
         "validation": {"historical_hit_rate": "pending-m1",
                        "applicable_regime": None, "known_failures": ["已有条目"]}},
    ]
    window = {"start": "2026-04-27", "end": "2026-08-07", "scored_days": 69}
    return metrics, buckets, patterns, window


def test_changes_only_pending_patterns():
    metrics, buckets, patterns, window = _fixtures()
    proposal = build_proposal(metrics, buckets, patterns, window=window)
    ids = [c["pattern_id"] for c in proposal["changes"]]
    # technical_timing 已有实测值（M0 回测），不进 changes；others 未被使用不进
    assert ids == ["sentiment_cycle", "sector_rotation"]  # 按 pattern_id 排序


def test_change_payload_and_falsification_note():
    metrics, buckets, patterns, window = _fixtures()
    proposal = build_proposal(metrics, buckets, patterns, window=window)
    sr = next(c for c in proposal["changes"] if c["pattern_id"] == "sector_rotation")
    assert sr["set"]["validation.historical_hit_rate"] == 0.62  # 主指标 direction
    assert sr["set"]["validation.applicable_regime"] == {"震荡": 0.6, "调整": 0.6}
    assert "append_known_failures" not in sr                     # 达标桶不追加
    sc = next(c for c in proposal["changes"] if c["pattern_id"] == "sentiment_cycle")
    assert sc["set"]["validation.historical_hit_rate"] == 0.4    # 主指标 stage
    assert len(sc["append_known_failures"]) == 1                 # 证伪桶追加
    assert "0.4" in sc["append_known_failures"][0] or "40.0%" in sc["append_known_failures"][0]


def test_evidence_covers_all_patterns_including_unused():
    metrics, buckets, patterns, window = _fixtures()
    proposal = build_proposal(metrics, buckets, patterns, window=window)
    ev = proposal["evidence"]["metrics"]
    assert set(ev) == {"sector_rotation", "sentiment_cycle", "technical_timing", "others"}
    assert ev["others"] == {"bucket": "unused", "note": "m1 未使用"}
    assert ev["technical_timing"]["bucket"] == "待观察"  # 只进证据区
    assert "使用归因" in proposal["evidence"]["attribution"]
    assert proposal["source"] == "m1-blindtest"


def test_write_proposal(tmp_path):
    metrics, buckets, patterns, window = _fixtures()
    proposal = build_proposal(metrics, buckets, patterns, window=window)
    path = write_proposal(proposal, tmp_path)
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert loaded["proposal_id"] == proposal["proposal_id"]
    assert loaded["changes"] == proposal["changes"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/pytest tests/investment_engine/test_pattern_eval_proposal.py -q`
Expected: FAIL（ModuleNotFoundError）

- [ ] **Step 3: 实现**

```python
# src/investment_engine/pattern_eval/proposal.py
"""渲染 pattern validation 回写提案（人审界面）：evidence 全量留档，changes 只含落库补丁。"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import yaml

from investment_engine.pattern_eval.bucket import BUCKET_FAIL

PROPOSAL_SOURCE = "m1-blindtest"
ATTRIBUTION_NOTE = (
    "使用归因（同日多模式共用，未隔离单模式贡献）；"
    "分母只含成功解析出该模式的日子，与 M1 总体口径（含无效日）不同"
)


def _build_changes(metrics: dict, buckets: dict, patterns: list[dict]) -> list[dict]:
    current = {p["pattern_id"]: (p.get("validation") or {}) for p in patterns}
    changes = []
    for pid in sorted(metrics):
        m = metrics[pid]
        b = buckets[pid]
        v = current.get(pid)
        kind = b.get("primary_metric")
        if v is None or kind is None:
            continue
        if v.get("historical_hit_rate") != "pending-m1":
            continue  # 已有实测值（如 technical_timing 的 M0 回测 0.5182），不动
        rate = m[kind]["rate"]
        if rate is None:
            continue  # 无可评分样本，无数可写
        change = {
            "pattern_id": pid,
            "set": {
                "validation.historical_hit_rate": round(rate, 4),
                "validation.applicable_regime": (
                    {label: round(rb["rate"], 4)
                     for label, rb in m["regime"].items() if rb["rate"] is not None}
                    or None
                ),
            },
        }
        if b["bucket"] == BUCKET_FAIL:
            change["append_known_failures"] = [
                f"m1 盲测使用归因主指标 {rate:.1%}（n={m[kind]['n']}，"
                f"窗口见提案 evidence），低于 50% 随机线"
            ]
        changes.append(change)
    return changes


def build_proposal(metrics: dict, buckets: dict, patterns: list[dict], *,
                   window: dict) -> dict:
    evidence_metrics = {}
    for pid, b in buckets.items():
        m = metrics.get(pid)
        if m is None:
            evidence_metrics[pid] = {"bucket": b["bucket"], "note": b.get("note")}
        else:
            evidence_metrics[pid] = {
                **m, "primary_metric": b.get("primary_metric"), "bucket": b["bucket"],
            }
    return {
        "proposal_id": f"{dt.date.today():%Y%m%d}-pattern-validation-m1",
        "source": PROPOSAL_SOURCE,
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "evidence": {
            "window": window,
            "attribution": ATTRIBUTION_NOTE,
            "metrics": evidence_metrics,
        },
        "changes": _build_changes(metrics, buckets, patterns),
    }


def write_proposal(proposal: dict, out_dir=Path("framework/proposals")) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{proposal['proposal_id']}.yaml"
    path.write_text(yaml.safe_dump(proposal, allow_unicode=True, sort_keys=False),
                    encoding="utf-8")
    return path
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/pytest tests/investment_engine/test_pattern_eval_proposal.py -q`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/investment_engine/pattern_eval/proposal.py tests/investment_engine/test_pattern_eval_proposal.py
git commit -m "feat(pattern-eval): 回写提案生成器"
```

---

### Task 4: apply.py — 提案执行器

**Files:**
- Create: `src/investment_engine/pattern_eval/apply.py`
- Modify: `pyproject.toml`（dependencies 加 `ruamel.yaml`）
- Test: `tests/investment_engine/test_pattern_eval_apply.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/investment_engine/test_pattern_eval_apply.py
"""apply：守卫 + 双次 schema 校验 + 幂等 + dry-run。"""
import pytest
import yaml

from investment_engine.pattern_eval.apply import apply_proposal

PATTERNS_YAML = """\
patterns:
- pattern_id: sector_rotation
  name: 板块轮动
  description: d
  trigger: t
  data_requirements: []
  steps: []
  falsification: []
  validation:
    historical_hit_rate: pending-m1
    applicable_regime: null
    known_failures: []
- pattern_id: technical_timing
  name: 技术择时
  description: d
  trigger: t
  data_requirements: []
  steps: []
  falsification: []
  validation:
    historical_hit_rate: 0.5182
    applicable_regime: null
    known_failures: []
"""


def _write(tmp_path, changes):
    patterns_path = tmp_path / "patterns.yaml"
    patterns_path.write_text(PATTERNS_YAML, encoding="utf-8")
    proposal_path = tmp_path / "proposal.yaml"
    proposal_path.write_text(yaml.safe_dump(
        {"proposal_id": "t1", "changes": changes}, allow_unicode=True),
        encoding="utf-8")
    return patterns_path, proposal_path


def _change(pid, rate):
    return {"pattern_id": pid,
            "set": {"validation.historical_hit_rate": rate,
                    "validation.applicable_regime": {"震荡": rate}}}


def test_apply_sets_validation_fields(tmp_path):
    patterns_path, proposal_path = _write(tmp_path, [_change("sector_rotation", 0.62)])
    report = apply_proposal(proposal_path, patterns_path=patterns_path)
    assert report["applied"] == ["sector_rotation"]
    doc = yaml.safe_load(patterns_path.read_text(encoding="utf-8"))
    v = doc["patterns"][0]["validation"]
    assert v["historical_hit_rate"] == 0.62
    assert v["applicable_regime"] == {"震荡": 0.62}


def test_apply_idempotent_second_run_skips(tmp_path):
    patterns_path, proposal_path = _write(tmp_path, [_change("sector_rotation", 0.62)])
    apply_proposal(proposal_path, patterns_path=patterns_path)
    report = apply_proposal(proposal_path, patterns_path=patterns_path)
    assert report["applied"] == []
    assert report["skipped"][0]["pattern_id"] == "sector_rotation"
    assert "pending-m1" in report["skipped"][0]["reason"]


def test_apply_skips_pattern_with_real_rate(tmp_path):
    patterns_path, proposal_path = _write(tmp_path, [_change("technical_timing", 0.45)])
    report = apply_proposal(proposal_path, patterns_path=patterns_path)
    assert report["applied"] == []
    assert report["skipped"][0]["pattern_id"] == "technical_timing"
    doc = yaml.safe_load(patterns_path.read_text(encoding="utf-8"))
    assert doc["patterns"][1]["validation"]["historical_hit_rate"] == 0.5182


def test_apply_rejects_unknown_pattern(tmp_path):
    patterns_path, proposal_path = _write(tmp_path, [_change("no_such", 0.5)])
    with pytest.raises(ValueError, match="no_such"):
        apply_proposal(proposal_path, patterns_path=patterns_path)


def test_apply_rejects_forbidden_field(tmp_path):
    bad = {"pattern_id": "sector_rotation", "set": {"name": "改名"}}
    patterns_path, proposal_path = _write(tmp_path, [bad])
    with pytest.raises(ValueError, match="禁止修改"):
        apply_proposal(proposal_path, patterns_path=patterns_path)


def test_apply_appends_known_failures_once(tmp_path):
    ch = _change("sector_rotation", 0.4)
    ch["append_known_failures"] = ["m1 证伪条目"]
    patterns_path, proposal_path = _write(tmp_path, [ch])
    apply_proposal(proposal_path, patterns_path=patterns_path)
    doc = yaml.safe_load(patterns_path.read_text(encoding="utf-8"))
    assert doc["patterns"][0]["validation"]["known_failures"] == ["m1 证伪条目"]


def test_dry_run_does_not_write(tmp_path):
    patterns_path, proposal_path = _write(tmp_path, [_change("sector_rotation", 0.62)])
    report = apply_proposal(proposal_path, patterns_path=patterns_path, dry_run=True)
    assert report["applied"] == ["sector_rotation"]
    assert patterns_path.read_text(encoding="utf-8") == PATTERNS_YAML
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/pytest tests/investment_engine/test_pattern_eval_apply.py -q`
Expected: FAIL（ModuleNotFoundError）

- [ ] **Step 3: 实现 + 声明 ruamel 依赖**

```python
# src/investment_engine/pattern_eval/apply.py
"""提案执行器：结构 fail-fast → 当前值守卫（幂等）→ 应用 → 整文件再校验（ruamel 保格式）。"""
from __future__ import annotations

from pathlib import Path

import yaml
from ruamel.yaml import YAML

from investment_engine.distill.pattern_schema import validate_patterns_file

SETTABLE = ("historical_hit_rate", "applicable_regime")


def _guard(pattern: dict, change: dict) -> str | None:
    """返回 None 可应用；否则返回 SKIP 原因（当前值已变化 → 幂等跳过）。"""
    v = pattern.get("validation") or {}
    for key in (change.get("set") or {}):
        field = key.split(".")[-1]
        if field == "historical_hit_rate" and v.get(field) != "pending-m1":
            return f"historical_hit_rate 当前值 {v.get(field)!r}，非 pending-m1"
        if field == "applicable_regime" and v.get(field) is not None:
            return f"applicable_regime 当前值 {v.get(field)!r}，非 null"
    existing = v.get("known_failures") or []
    for item in change.get("append_known_failures") or []:
        if item in existing:
            return "known_failures 已含该条目"
    return None


def apply_proposal(proposal_path, *, patterns_path, dry_run: bool = False) -> dict:
    """应用提案。结构问题 fail-fast（不部分应用）；守卫不满足的条目 SKIP。"""
    proposal = yaml.safe_load(Path(proposal_path).read_text(encoding="utf-8"))
    patterns_file = Path(patterns_path)
    rt = YAML()  # round-trip 模式，保留未触碰部分的原始格式
    doc = rt.load(patterns_file.read_text(encoding="utf-8"))
    validate_patterns_file(doc)  # 应用前整文件校验

    changes = (proposal or {}).get("changes")
    if not isinstance(changes, list):
        raise ValueError("提案缺 changes 列表")
    patterns = {p["pattern_id"]: p for p in doc["patterns"]}
    # pass 1：结构校验，任一非法即整体拒绝
    for ch in changes:
        pid = ch.get("pattern_id")
        if pid not in patterns:
            raise ValueError(f"提案含未知 pattern_id: {pid!r}")
        for key in (ch.get("set") or {}):
            if key.split(".")[-1] not in SETTABLE:
                raise ValueError(f"{pid}: 禁止修改 {key!r}")

    report = {"applied": [], "skipped": []}
    for ch in changes:
        pid = ch["pattern_id"]
        reason = _guard(patterns[pid], ch)
        if reason:
            report["skipped"].append({"pattern_id": pid, "reason": reason})
            continue
        v = patterns[pid].setdefault("validation", {})
        for key, val in (ch.get("set") or {}).items():
            v[key.split(".")[-1]] = val
        for item in ch.get("append_known_failures") or []:
            v.setdefault("known_failures", []).append(item)
        report["applied"].append(pid)

    if not dry_run and report["applied"]:
        validate_patterns_file(doc)  # 应用后整文件校验，失败不落盘
        with patterns_file.open("w", encoding="utf-8") as f:
            rt.dump(doc, f)
    return report
```

`pyproject.toml` dependencies 加一行（按字母序放在 pyyaml 前）：

```toml
  "pytdx>=1.0",
  "ruamel.yaml>=0.18",
  "pyyaml>=6.0.1",
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/pytest tests/investment_engine/test_pattern_eval_apply.py -q`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add src/investment_engine/pattern_eval/apply.py tests/investment_engine/test_pattern_eval_apply.py pyproject.toml
git commit -m "feat(pattern-eval): 提案执行器（守卫 + 双次 schema 校验）"
```

---

### Task 5: CLI 脚本两个

**Files:**
- Create: `scripts/propose_pattern_validation.py`
- Create: `scripts/apply_pattern_proposal.py`
- Test: `tests/investment_engine/test_pattern_eval_scripts.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/investment_engine/test_pattern_eval_scripts.py
"""两个 CLI 的冒烟：argparse 解析 + 端到端走通（假数据）。"""
import json

import yaml


def _seed(tmp_path):
    results_path = tmp_path / "results.jsonl"
    rows = [
        {"date": "2026-08-03", "ok": True,
         "result": {"market_stage": "震荡", "directions": [],
                    "used_patterns": ["sector_rotation"]}},
    ]
    results_path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows),
                            encoding="utf-8")
    patterns_path = tmp_path / "patterns.yaml"
    patterns_path.write_text("""\
patterns:
- pattern_id: sector_rotation
  name: 板块轮动
  description: d
  trigger: t
  data_requirements: []
  steps: []
  falsification: []
  validation:
    historical_hit_rate: pending-m1
    applicable_regime: null
    known_failures: []
""", encoding="utf-8")
    return results_path, patterns_path


def test_propose_and_apply_end_to_end(tmp_path, monkeypatch):
    results_path, patterns_path = _seed(tmp_path)
    # 假 truth 与假 K 线评分，避免依赖真实缓存
    monkeypatch.setattr("investment_engine.blindtest.truth.load_truth",
                        lambda *a, **k: {"2026-08-03": "震荡"})
    monkeypatch.setattr(
        "investment_engine.blindtest.score.direction_scores",
        lambda rs, **k: {"samples": 2, "hits": 2, "hit_rate": 1.0, "details": []})
    monkeypatch.setattr(
        "investment_engine.blindtest.score.stock_scores",
        lambda rs, **k: {"samples": 1, "hits": 1, "hit_rate": 1.0, "details": []})

    from scripts.propose_pattern_validation import main as propose_main
    rc = propose_main(["--results", str(results_path),
                       "--patterns", str(patterns_path),
                       "--out-dir", str(tmp_path / "proposals")])
    assert rc == 0
    proposals = list((tmp_path / "proposals").glob("*.yaml"))
    assert len(proposals) == 1

    from scripts.apply_pattern_proposal import main as apply_main
    rc = apply_main([str(proposals[0]), "--patterns", str(patterns_path)])
    assert rc == 0
    doc = yaml.safe_load(patterns_path.read_text(encoding="utf-8"))
    assert doc["patterns"][0]["validation"]["historical_hit_rate"] == 1.0
```

注意：monkeypatch 打的是 `score.direction_scores`/`truth.load_truth` 的定义处——
`propose` 脚本与 `attribute.py` 都是按模块属性引用（`from ... import` 后在
`attribute.pattern_metrics` 内以默认参数延迟绑定），因此 patch 定义模块属性即可生效。
若实现时改为直接引用函数对象导致 patch 不生效，应在脚本内通过参数注入 scorer。

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/pytest tests/investment_engine/test_pattern_eval_scripts.py -q`
Expected: FAIL（ModuleNotFoundError: scripts.propose_pattern_validation）

- [ ] **Step 3: 实现**

```python
#!/usr/bin/env python
# scripts/propose_pattern_validation.py
"""生成 pattern validation 回写提案（M1 盲测结果回填）。

用法: .venv/bin/python scripts/propose_pattern_validation.py
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import yaml

from investment_engine.blindtest import score, truth as truth_mod
from investment_engine.pattern_eval.attribute import pattern_metrics
from investment_engine.pattern_eval.bucket import bucketize
from investment_engine.pattern_eval.proposal import build_proposal, write_proposal


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="生成 pattern validation 回写提案")
    parser.add_argument("--results", default="evals/blindtest/results.jsonl")
    parser.add_argument("--patterns", default="framework/reasoning-patterns.yaml")
    parser.add_argument("--config-dir", default="config/stock_monitor")
    parser.add_argument("--db", default="infra/data/kline_cache.db")
    parser.add_argument("--out-dir", default="framework/proposals")
    args = parser.parse_args(argv)

    results = score.load_results(args.results)
    truth = truth_mod.load_truth(Path(args.db))
    metrics = pattern_metrics(
        results, truth=truth, config_dir=Path(args.config_dir),
        db_path=Path(args.db),
        direction_scorer=lambda rs: score.direction_scores(
            rs, config_dir=Path(args.config_dir), db_path=Path(args.db)),
        stock_scorer=lambda rs: score.stock_scores(rs, db_path=Path(args.db)),
    )
    doc = yaml.safe_load(Path(args.patterns).read_text(encoding="utf-8"))
    buckets = bucketize(metrics, [p["pattern_id"] for p in doc["patterns"]])
    window = {"start": results[0]["date"], "end": results[-1]["date"],
              "scored_days": len(results)}
    proposal = build_proposal(metrics, buckets, doc["patterns"], window=window)
    path = write_proposal(proposal, Path(args.out_dir))
    print(f"[proposal] {path}")
    for pid, b in buckets.items():
        print(f"  {pid}: {b['bucket']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

```python
#!/usr/bin/env python
# scripts/apply_pattern_proposal.py
"""应用人工评审过的 pattern validation 提案（--dry-run 预览不落盘）。

用法: .venv/bin/python scripts/apply_pattern_proposal.py framework/proposals/<file>.yaml
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from investment_engine.pattern_eval.apply import apply_proposal


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="应用 pattern validation 提案")
    parser.add_argument("proposal")
    parser.add_argument("--patterns", default="framework/reasoning-patterns.yaml")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    report = apply_proposal(args.proposal, patterns_path=args.patterns,
                            dry_run=args.dry_run)
    print(f"[applied] {report['applied']}")
    for s in report["skipped"]:
        print(f"[skipped] {s['pattern_id']}: {s['reason']}")
    if args.dry_run:
        print("[dry-run] 未落盘")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

注意：脚本经 lambda 注入 scorer，monkeypatch `score.direction_scores` 定义处即生效；
`scripts/` 是包（有 `__init__.py`），测试可直接 `from scripts.xxx import main`。

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/pytest tests/investment_engine/test_pattern_eval_scripts.py -q`
Expected: 1 passed

- [ ] **Step 5: Commit**

```bash
git add scripts/propose_pattern_validation.py scripts/apply_pattern_proposal.py tests/investment_engine/test_pattern_eval_scripts.py
git commit -m "feat(pattern-eval): 提案生成/应用 CLI"
```

---

### Task 6: 真实数据跑通 + 人审 + 落库 + 回归

**Files:**
- Generate: `framework/proposals/<date>-pattern-validation-m1.yaml`
- Modify: `framework/reasoning-patterns.yaml`（仅 5 个 pending-m1 且被使用模式的 validation 三字段）

- [ ] **Step 1: 生成真实提案**

Run: `.venv/bin/python scripts/propose_pattern_validation.py`
Expected: 打印 `[proposal] framework/proposals/20260808-pattern-validation-m1.yaml` + 10 个模式的桶清单；6 个被使用模式指标齐全，4 个 unused 有标注

- [ ] **Step 2: dry-run 预览**

Run: `.venv/bin/python scripts/apply_pattern_proposal.py framework/proposals/20260808-pattern-validation-m1.yaml --dry-run`
Expected: applied 恰为 5 个模式（upstream_cycle / mainline_identification / sector_rotation / sentiment_cycle / ai_industry_chain），无 skipped

- [ ] **Step 3: 人工评审检查点**

向用户展示提案文件全文与 dry-run 输出，**等用户确认后再继续**。

- [ ] **Step 4: 正式应用**

Run: `.venv/bin/python scripts/apply_pattern_proposal.py framework/proposals/20260808-pattern-validation-m1.yaml`
Expected: applied 5 个，skipped 空

- [ ] **Step 5: 验证落库结果**

Run: `.venv/bin/python -c "
import yaml
from investment_engine.distill.pattern_schema import validate_patterns_file
d = yaml.safe_load(open('framework/reasoning-patterns.yaml'))
validate_patterns_file(d)
for p in d['patterns']:
    print(p['pattern_id'], (p.get('validation') or {}).get('historical_hit_rate'))
"`（需要先 `PYTHONPATH=src` 或从仓库根用 `.venv/bin/python -c` 加 `sys.path`——用 `PYTHONPATH=src .venv/bin/python -c "..."`）
Expected: 校验通过；5 个模式为新实测值；technical_timing/operation_strategy 保持 0.5182；macro_transmission/earnings_analysis/others 保持 pending-m1

- [ ] **Step 6: 幂等复核**

Run: 再次执行 Step 4 命令
Expected: applied 空，5 条全 SKIP（reason 含 "非 pending-m1"）

- [ ] **Step 7: 全量回归**

Run: `.venv/bin/pytest tests/investment_engine -q`
Expected: 114+26=140 passed（T1 2 + T2 12 + T3 4 + T4 7 + T5 1 = 26 新增；0 失败）

Run: `PYTHONPATH=third_party/chanpy .venv/bin/pytest tests/ -q`
Expected: 561+26=587 passed，仍只有 4 个基线环境型失败（test_evaluate_agent_vs_up×2、test_kimi_code_cli_short_output、test_pre_fetch_klines::test_fail_rate_exit_code）

- [ ] **Step 8: Commit**

```bash
git add framework/proposals/ framework/reasoning-patterns.yaml
git commit -m "chore(pattern-eval): M1 盲测结果回填 reasoning-patterns（提案人审后应用）"
```

注意：`framework/reasoning-patterns.yaml` 的 diff 应只含 5 个模式的 validation 三字段变化（ruamel 保格式）；若 diff 出现大面积重排，停下排查而不是直接提交。

---

## Self-Review 记录

- Spec 覆盖：①数据流→T1-T5；②主指标映射/③三桶→T2；④回写动作→T3/T4；⑤apply 安全→T4；⑥测试→各任务+T6 回归；提案格式→T3；CLI→T5；验收 4 条→T6。无缺口。
- Placeholder 扫描：无 TBD/TODO；所有代码步骤含完整代码。
- 类型一致性：`pattern_metrics` 返回 `{rate,n}` 结构 ↔ bucket 读 `m[kind]["rate"]/["n"]` ↔ proposal 读 `m["regime"]` 一致；`bucketize` 返回含 `primary_metric`（仅 mapped）↔ proposal `b.get("primary_metric")` 一致；apply 守卫字段名与 schema 三子字段一致。
- 已核实的坑写进步骤：monkeypatch 经 lambda 注入生效（T5）；ruamel 未声明依赖（T4 补 pyproject）；pytest 退出码不接管道（约束节）。
