# M4 预备：毕业判分器 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 读 `evals/shadow/predictions/*.json`，滚动 8 个自然周窗口聚合阶段一致率与方向超额命中率，对照主计划 10.4 毕业线输出判定报告。

**Architecture:** `src/investment_engine/shadow/graduation.py` 单模块（load → window → aggregate → judge → render → run，纯函数 + 一个组合入口）+ thin script `scripts/graduation_check.py`。窗口按 ISO 自然周的周一锚定；`today` 可注入便于测试。

**Tech Stack:** Python 3.13 标准库（json/datetime/pathlib/argparse）+ pytest，无新依赖。

**Spec:** `docs/superpowers/specs/2026-08-09-m4-graduation-check-design.md`

**约束（用户明确要求）：**
- 不用 subagent；逐任务按给定 commit message 提交（已授权，不 push）
- 不改 `src/qing_investment/`；`tests/investment_engine/` 不放 `__init__.py`
- 测试用 `.venv/bin/pytest`；commit 前单独跑测试确认退出码（不要 `| tail` 后接 `&& git commit`）
- 分支 `feat/m4-graduation-check` 已 checkout

**现状事实（实现依据，已核实）：**
- prediction 记录：`stage_hit`（bool|null）、`due_scores.directions/stocks`（`{samples,hits,hit_rate}`，仅 `status=="scored"` 有）、`status`（`pending_maturity/scored/error`）
- `.gitignore` 第 9-14 行：`logs/*` 忽略 + 4 条例外（`!logs/m0-acceptance.md` 等），新例外加在第 14 行后
- 真实数据现状：`evals/shadow/predictions/` 仅 2026-08-07 一天 → 真实跑 verdict 必为 `insufficient_data`

---

### Task 1: graduation.py 核心（load / window / aggregate / judge）

**Files:**
- Create: `src/investment_engine/shadow/graduation.py`
- Test: `tests/investment_engine/test_shadow_graduation.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/investment_engine/test_shadow_graduation.py
"""graduation：窗口聚合与毕业判定。"""
import json
from datetime import date

from investment_engine.shadow.graduation import (
    aggregate, judge, load_records, window_records, weekly_breakdown,
)

TODAY = date(2026, 8, 9)  # 周日；所在 ISO 周周一 = 2026-08-03


def _rec(day, *, stage_hit=None, status="scored", dirs=None):
    rec = {"date": day, "status": status, "stage_hit": stage_hit}
    if dirs is not None:
        rec["due_scores"] = {"directions": dirs}
    return rec


def _write(tmp_path, records):
    pred_dir = tmp_path / "predictions"
    pred_dir.mkdir()
    for r in records:
        (pred_dir / f"{r['date']}.json").write_text(
            json.dumps(r, ensure_ascii=False), encoding="utf-8")
    return pred_dir


def test_load_records_skips_bad_and_missing_date(tmp_path):
    pred_dir = _write(tmp_path, [_rec("2026-08-05", stage_hit=True)])
    (pred_dir / "bad.json").write_text("{not json", encoding="utf-8")
    (pred_dir / "nodate.json").write_text("{}", encoding="utf-8")
    records, skipped = load_records(pred_dir)
    assert len(records) == 1 and skipped == 2


def test_load_records_missing_dir(tmp_path):
    records, skipped = load_records(tmp_path / "nonexistent")
    assert records == [] and skipped == 0


def test_window_records_iso_weeks():
    # weeks=2 → 窗口起点周一 = 2026-08-03 - 7 天 = 2026-07-27
    records = [
        _rec("2026-07-26"),  # 窗口外（上一周周日）
        _rec("2026-07-27"),  # 窗口内（起点周一）
        _rec("2026-08-05"),  # 窗口内
    ]
    win = window_records(records, weeks=2, today=TODAY)
    assert [r["date"] for r in win] == ["2026-07-27", "2026-08-05"]


def test_aggregate_cross_day_sums():
    records = [
        _rec("2026-08-03", stage_hit=True,
             dirs={"samples": 2, "hits": 2, "hit_rate": 1.0}),
        _rec("2026-08-04", stage_hit=False,
             dirs={"samples": 2, "hits": 0, "hit_rate": 0.0}),
        _rec("2026-08-05", stage_hit=None, status="pending_maturity"),  # 不计
    ]
    stats = aggregate(records)
    assert stats["stage"] == {"rate": 0.5, "n": 2}
    assert stats["direction"] == {"rate": 0.5, "n": 4}


def test_weekly_breakdown_groups_by_monday():
    records = [
        _rec("2026-08-03", stage_hit=True, dirs={"samples": 1, "hits": 1}),
        _rec("2026-08-05", stage_hit=False, dirs={"samples": 1, "hits": 0}),
        _rec("2026-07-29", stage_hit=True, dirs={"samples": 2, "hits": 1}),
    ]
    weekly = weekly_breakdown(records)
    assert [w["week_start"].isoformat() for w in weekly] == ["2026-07-27", "2026-08-03"]
    assert weekly[0]["stage"] == {"rate": 1.0, "n": 1}
    assert weekly[1]["stage"] == {"rate": 0.5, "n": 2}
    assert weekly[1]["direction"] == {"rate": 0.5, "n": 2}


def _eight_week_records(stage_hit=True, dir_hits=2, dir_samples=2):
    """8 个连续自然周各一条已结算记录（2026-06-15 周一 ~ 2026-08-03 周）。"""
    from datetime import timedelta
    start = date(2026, 6, 15)
    return [
        _rec((start + timedelta(weeks=i) + timedelta(days=2)).isoformat(),
             stage_hit=stage_hit,
             dirs={"samples": dir_samples, "hits": dir_hits})
        for i in range(8)
    ]


def test_judge_graduated_when_8_weeks_above_lines():
    stats = aggregate(_eight_week_records())
    assert judge(stats, weeks=8, covered_weeks=8) == "graduated"


def test_judge_not_yet_when_below_line():
    stats = aggregate(_eight_week_records(stage_hit=False))
    assert judge(stats, weeks=8, covered_weeks=8) == "not_yet"


def test_judge_insufficient_when_fewer_weeks():
    stats = aggregate(_eight_week_records()[:7])
    assert judge(stats, weeks=8, covered_weeks=7) == "insufficient_data"


def test_judge_no_data():
    stats = aggregate([_rec("2026-08-05", status="pending_maturity")])
    assert judge(stats, weeks=8, covered_weeks=1) == "no_data"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/pytest tests/investment_engine/test_shadow_graduation.py -q`
Expected: FAIL（ModuleNotFoundError: investment_engine.shadow.graduation）

- [ ] **Step 3: 实现**

```python
# src/investment_engine/shadow/graduation.py
"""毕业判分：滚动 8 周窗口聚合 shadow 双轨指标，对照主计划 10.4 毕业线。

口径：跨日聚合分子分母（非日均值），与 M1 基线一致；窗口按 ISO 自然周
周一锚定；第三判据（假设证伪率）仓库中无可计算定义，本版本不参与判定。
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

PRED_DIR = Path("evals/shadow/predictions")
STAGE_LINE = 0.70
DIRECTION_LINE = 0.60
DEFAULT_WEEKS = 8

VERDICT_NO_DATA = "no_data"
VERDICT_INSUFFICIENT = "insufficient_data"
VERDICT_GRADUATED = "graduated"
VERDICT_NOT_YET = "not_yet"

CRITERION3_NOTE = (
    "第三判据（路径 A 假设证伪率 ≤ 历史基准 +10pct）：仓库中无可计算定义"
    "（待 M3 claims 分桶落地后定义），本版本不参与判定。"
)


def _monday(day: date) -> date:
    return day - timedelta(days=day.weekday())


def load_records(pred_dir) -> tuple[list[dict], int]:
    """读 predictions 目录；返回 (有效记录, 跳过条数)。目录不存在按空处理。"""
    records, skipped = [], 0
    pred_dir = Path(pred_dir)
    if not pred_dir.exists():
        return records, skipped
    for path in sorted(pred_dir.glob("*.json")):
        try:
            rec = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            skipped += 1
            continue
        if not rec.get("date"):
            skipped += 1
            continue
        records.append(rec)
    return records, skipped


def window_records(records: list[dict], *, weeks: int, today: date) -> list[dict]:
    """最近 weeks 个 ISO 自然周（含 today 所在周）内的记录。"""
    start = _monday(today) - timedelta(weeks=weeks - 1)
    return [r for r in records
            if _monday(date.fromisoformat(r["date"])) >= start]


def aggregate(records: list[dict]) -> dict:
    """两项指标跨日聚合；各自取 n（stage 次日可判，direction 需 5 交易日结算）。"""
    stage_hits = stage_n = 0
    dir_hits = dir_n = 0
    for r in records:
        hit = r.get("stage_hit")
        if hit is not None:
            stage_n += 1
            stage_hits += int(bool(hit))
        if r.get("status") == "scored":
            dirs = (r.get("due_scores") or {}).get("directions") or {}
            dir_n += dirs.get("samples", 0)
            dir_hits += dirs.get("hits", 0)
    return {
        "stage": {"rate": stage_hits / stage_n if stage_n else None, "n": stage_n},
        "direction": {"rate": dir_hits / dir_n if dir_n else None, "n": dir_n},
    }


def weekly_breakdown(records: list[dict]) -> list[dict]:
    """分周明细，按周一起始日升序。"""
    by_week: dict[date, list[dict]] = {}
    for r in records:
        by_week.setdefault(_monday(date.fromisoformat(r["date"])), []).append(r)
    return [{"week_start": ws, **aggregate(rs)}
            for ws, rs in sorted(by_week.items())]


def judge(stats: dict, *, weeks: int, covered_weeks: int) -> str:
    """按序判定：no_data → insufficient_data → graduated / not_yet。"""
    if stats["stage"]["n"] == 0 and stats["direction"]["n"] == 0:
        return VERDICT_NO_DATA
    if covered_weeks < weeks:
        return VERDICT_INSUFFICIENT
    stage_ok = (stats["stage"]["rate"] or 0) >= STAGE_LINE
    dir_ok = (stats["direction"]["rate"] or 0) >= DIRECTION_LINE
    return VERDICT_GRADUATED if (stage_ok and dir_ok) else VERDICT_NOT_YET
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/pytest tests/investment_engine/test_shadow_graduation.py -q`
Expected: 9 passed

- [ ] **Step 5: Commit**

```bash
git add src/investment_engine/shadow/graduation.py tests/investment_engine/test_shadow_graduation.py
git commit -m "feat(graduation): 窗口聚合与毕业判定核心"
```

---

### Task 2: render_report + run + CLI

**Files:**
- Modify: `src/investment_engine/shadow/graduation.py`（追加 render_report / run）
- Create: `scripts/graduation_check.py`
- Test: `tests/investment_engine/test_shadow_graduation_report.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/investment_engine/test_shadow_graduation_report.py
"""graduation 报告渲染与 run 入口、CLI 冒烟。"""
import json
from datetime import date

from investment_engine.shadow.graduation import run

TODAY = date(2026, 8, 9)


def _seed(tmp_path):
    pred_dir = tmp_path / "predictions"
    pred_dir.mkdir()
    rec = {"date": "2026-08-07", "status": "scored", "stage_hit": True,
           "due_scores": {"directions": {"samples": 2, "hits": 1, "hit_rate": 0.5}}}
    (pred_dir / "2026-08-07.json").write_text(
        json.dumps(rec, ensure_ascii=False), encoding="utf-8")
    return pred_dir


def test_run_writes_report(tmp_path):
    pred_dir = _seed(tmp_path)
    out = run(pred_dir, weeks=8, out_dir=tmp_path / "logs", today=TODAY)
    text = out.read_text(encoding="utf-8")
    assert out.name == "graduation-2026-08-09.md"
    assert "verdict: insufficient_data" in text          # 仅 1 周数据
    assert "阶段一致率: 100.0%（n=1）" in text
    assert "方向 5 日超额命中率: 50.0%（n=2）" in text
    assert "第三判据" in text and "不参与判定" in text
    assert "| 2026-08-03 |" in text                      # 分周明细行
    assert "解析跳过 0 条" in text


def test_run_no_data(tmp_path):
    out = run(tmp_path / "nonexistent", weeks=8,
              out_dir=tmp_path / "logs", today=TODAY)
    text = out.read_text(encoding="utf-8")
    assert "verdict: no_data" in text


def test_cli_smoke(tmp_path, capsys):
    pred_dir = _seed(tmp_path)
    from scripts.graduation_check import main
    rc = main(["--pred-dir", str(pred_dir),
               "--out-dir", str(tmp_path / "logs")])
    assert rc == 0
    out = capsys.readouterr().out
    assert "insufficient_data" in out
    assert (tmp_path / "logs").glob("graduation-*.md")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/pytest tests/investment_engine/test_shadow_graduation_report.py -q`
Expected: FAIL（ImportError: cannot import name 'run'）

- [ ] **Step 3: 实现**

`src/investment_engine/shadow/graduation.py` 末尾追加：

```python
def _fmt(m: dict) -> str:
    return "n=0" if m["n"] == 0 else f"{m['rate']:.1%}（n={m['n']}）"


def render_report(*, run_date: date, weeks: int, window_start: date,
                  stats: dict, weekly: list[dict], verdict: str,
                  skipped: int) -> str:
    lines = [
        f"# 毕业判定报告（{run_date}）",
        "",
        f"- 窗口: 最近 {weeks} 个自然周（{window_start} 起），覆盖 {len(weekly)} 周",
        f"- 阶段一致率: {_fmt(stats['stage'])}（毕业线 {STAGE_LINE:.0%}）",
        f"- 方向 5 日超额命中率: {_fmt(stats['direction'])}（毕业线 {DIRECTION_LINE:.0%}）",
        f"- **verdict: {verdict}**",
        "",
        "## 分周明细",
        "",
        "| 周起始 | 阶段一致率 | 方向超额 |",
        "|---|---|---|",
    ]
    for w in weekly:
        lines.append(
            f"| {w['week_start']} | {_fmt(w['stage'])} | {_fmt(w['direction'])} |")
    lines += [
        "",
        "## 说明",
        "",
        f"- {CRITERION3_NOTE}",
        "- 口径: 影子双轨每日盲判数据（非 M1 历史回放）；跨日聚合分子分母，非日均值。",
        f"- 解析跳过 {skipped} 条（坏 JSON 或缺 date）。",
    ]
    return "\n".join(lines) + "\n"


def run(pred_dir=PRED_DIR, *, weeks: int = DEFAULT_WEEKS,
        out_dir=Path("logs"), today: date | None = None) -> Path:
    """组合入口：读 → 窗口 → 聚合 → 判定 → 写 logs/graduation-<run_date>.md。"""
    run_date = today or date.today()
    records, skipped = load_records(pred_dir)
    win = window_records(records, weeks=weeks, today=run_date)
    stats = aggregate(win)
    weekly = weekly_breakdown(win)
    verdict = judge(stats, weeks=weeks, covered_weeks=len(weekly))
    window_start = _monday(run_date) - timedelta(weeks=weeks - 1)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"graduation-{run_date.isoformat()}.md"
    path.write_text(render_report(run_date=run_date, weeks=weeks,
                                  window_start=window_start, stats=stats,
                                  weekly=weekly, verdict=verdict,
                                  skipped=skipped), encoding="utf-8")
    return path
```

```python
#!/usr/bin/env python
# scripts/graduation_check.py
"""毕业判分：滚动 8 周窗口对照主计划 10.4 毕业线，写 logs/graduation-<date>.md。

用法: .venv/bin/python scripts/graduation_check.py
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from investment_engine.shadow.graduation import run


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="毕业判分（主计划 10.4 口径）")
    parser.add_argument("--pred-dir", default="evals/shadow/predictions")
    parser.add_argument("--weeks", type=int, default=8)
    parser.add_argument("--out-dir", default="logs")
    args = parser.parse_args(argv)

    path = run(Path(args.pred_dir), weeks=args.weeks, out_dir=Path(args.out_dir))
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("- **verdict"):
            print(line)
    print(f"[report] {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/pytest tests/investment_engine/test_shadow_graduation_report.py -q`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add src/investment_engine/shadow/graduation.py scripts/graduation_check.py tests/investment_engine/test_shadow_graduation_report.py
git commit -m "feat(graduation): 报告渲染、run 入口与 CLI"
```

---

### Task 3: 真实数据跑通 + gitignore 例外 + 回归

**Files:**
- Modify: `.gitignore`（加例外行）
- Generate: `logs/graduation-<today>.md`

- [ ] **Step 1: 真实数据跑**

Run: `.venv/bin/python scripts/graduation_check.py`
Expected: 输出 `- **verdict: insufficient_data**` 与报告路径（当前仅 2026-08-07 一天数据，覆盖 1 周 < 8 周）

- [ ] **Step 2: 手工核对报告数值**

Run: `cat logs/graduation-*.md`
核对：阶段一致率/方向超额与 `evals/shadow/predictions/2026-08-07.json` 的
`stage_hit`、`due_scores.directions` 一致；分周明细只有 2026-08-03 一行。

- [ ] **Step 3: .gitignore 加例外**

`.gitignore` 第 14 行 `!logs/shadow-status.md` 后追加一行：

```
!logs/graduation-*.md
```

- [ ] **Step 4: 全量回归**

Run: `.venv/bin/pytest tests/investment_engine -q`
Expected: 141+12=153 passed（T1 9 + T2 3 = 12 新增；0 失败）

Run: `PYTHONPATH=third_party/chanpy .venv/bin/pytest tests/ -q`
Expected: 589+12=601 passed，3 个基线环境型失败不变（test_evaluate_agent_vs_up×2、test_kimi_code_cli_short_output）

- [ ] **Step 5: Commit**

```bash
git add .gitignore logs/graduation-*.md
git commit -m "chore(graduation): 首期毕业判定报告与 logs 例外"
```

---

## Self-Review 记录

- Spec 覆盖：数据流→T1/T2；指标口径→T1 aggregate；判定规则（含窗口精确定义）→T1 judge + T3 真实验证；报告格式→T2；.gitignore 例外→T3；错误处理（坏 JSON/缺 date/目录不存在）→T1 测试；验收 3 条→T3。无缺口。
- Placeholder 扫描：无 TBD/TODO；所有代码步骤含完整代码。
- 类型一致性：`aggregate` 返回 `{stage:{rate,n}, direction:{rate,n}}` ↔ judge 读 `stats["stage"]["rate"]` ↔ render `_fmt` 读 `m["rate"]/m["n"]` 一致；`weekly_breakdown` 行含 `week_start` + 展开 aggregate ↔ render 读 `w["week_start"]/w["stage"]` 一致；`run(pred_dir, *, weeks, out_dir, today)` ↔ CLI/测试调用签名一致。
- 日期数学已核对：TODAY=2026-08-09 为周日，所在周周一 2026-08-03；weeks=2 窗口起点 2026-07-27；`_eight_week_records` 起点 2026-06-15 周一（2026-08-03 前 7 周），每周三一条共 8 周。
