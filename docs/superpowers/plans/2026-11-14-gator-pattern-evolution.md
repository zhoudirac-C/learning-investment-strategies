# gator-pattern-evolution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立 `gator-pattern-evolution` Skill，让主库全部鳄鱼增量 claim 能进入分类、人工复核、批准写回和持续 backlog 追踪闭环，并修复第 56 章失效来源。

**Architecture:** 用 `src/investment_engine/pattern_eval/gator_evolution.py` 承担 claims 加载、待办查询、提案校验、五类写回、来源修复、幂等与原子落盘；现有分类脚本复用同一加载器。CLI 只做参数解析，Skill 只做编排和人工判断，第三方目录始终只读。

**Tech Stack:** Python 3.11、PyYAML、ruamel.yaml、pytest、现有 `scripts/evolve_gator_patterns.py`、Markdown Agent Skills。

**设计依据：** `docs/superpowers/specs/2026-11-14-gator-pattern-evolution-design.md`。

**Git 约束：** 不自动 commit/push；只有用户另行明确要求时才执行 Git 写操作。每个任务结束用 `git status --short` 检查范围，不触碰已有的两个 xueqiu 数据文件修改。

---

## 文件结构

- Create: `src/investment_engine/pattern_eval/gator_evolution.py` — claims 加载、backlog、提案执行与落盘。
- Create: `scripts/apply_gator_pattern_evolution.py` — 薄 CLI。
- Create: `tests/test_gator_pattern_evolution_apply.py` — 单元和临时文件集成测试。
- Modify: `scripts/evolve_gator_patterns.py` — 复用兼容加载器。
- Modify: `tests/test_pattern_prompt_policy.py:230` — 固定数量基线改为既有 ID 防丢失、允许新增。
- Create: `skills/gator-pattern-evolution/SKILL.md` — 触发与编排。
- Create: `skills/gator-pattern-evolution/references/review-and-writeback.md` — 提案和复核契约。
- Create: `framework/proposals/20261114-gator-ch56-provenance-repair.yaml` — 第 56 章真实待审修复提案。
- Modify: `framework/reasoning-patterns-gator.yaml` — 仅在用户批准上述提案后由写回器修改。
- Modify: `infra/data/gator_pattern_evolution/state.json` — 仅在真实分类/批准执行时修改。
- Modify: `docs/design/gator-pattern-evolution-design.md` — 旧 P2/P4 状态指向新实现。

### Task 1: 兼容主库 claim 格式并建立 backlog 查询

**Files:**
- Create: `src/investment_engine/pattern_eval/gator_evolution.py`
- Create: `tests/test_gator_pattern_evolution_apply.py`
- Modify: `scripts/evolve_gator_patterns.py:81-100`

- [ ] **Step 1: 写加载器和 backlog 的失败测试**

创建 `tests/test_gator_pattern_evolution_apply.py`：

```python
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from investment_engine.pattern_eval import gator_evolution as ge


def _write_claim(
    claims_dir: Path,
    claim_id: str,
    *,
    source_date: str = "2026-11-12",
    up_id: str | None = "gator-ecyu-0001",
    school: str | None = None,
    container: str = "single",
    topic: str = "测试主题",
) -> dict:
    claims_dir.mkdir(parents=True, exist_ok=True)
    claim = {
        "id": claim_id,
        "source_path": "sources/raw/gator.md",
        "source_date": source_date,
        "up_id": up_id,
        "topic": topic,
        "statement": "测试观点",
        "evidence_quote": "鳄鱼原文证据",
    }
    if school is not None:
        claim["school"] = school
    if up_id is not None:
        claim["up_id"] = up_id
    else:
        claim.pop("up_id")
    if container == "list":
        data = [claim]
    elif container == "claims":
        data = {"claims": [claim]}
    else:
        data = claim
    (claims_dir / f"{claim_id}.yaml").write_text(
        yaml.safe_dump(data, allow_unicode=True), encoding="utf-8"
    )
    return claim


def _base_pattern() -> dict:
    return {
        "pattern_id": "gator-ch56-bottom-cycle",
        "school": "gator",
        "name": "底部周期",
        "chapter": 56,
        "description": "旧描述",
        "trigger": ["旧触发"],
        "steps": ["旧步骤"],
        "thresholds": ["旧阈值"],
        "table_rules": [],
        "falsification": [],
        "computable": True,
        "core": True,
        "source_ref": "",
        "source_dates": ["2026-10-15"],
        "source_path": "sources/raw/gator.md",
        "provenance": "third_party/gator-method",
        "validation": {},
    }


def _environment(tmp_path: Path) -> dict:
    repo_root = tmp_path
    claims_dir = repo_root / "knowledge/claims"
    source = repo_root / "sources/raw/gator.md"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("鳄鱼原文证据", encoding="utf-8")
    _write_claim(claims_dir, "claim-a", source_date="2026-11-11")
    _write_claim(claims_dir, "claim-b", source_date="2026-11-12")
    patterns_path = repo_root / "framework/reasoning-patterns-gator.yaml"
    patterns_path.parent.mkdir(parents=True, exist_ok=True)
    patterns_path.write_text(
        yaml.safe_dump(
            {
                "version": "1.1-draft",
                "school": "gator",
                "evolution_log": [],
                "patterns": [_base_pattern()],
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    state_path = repo_root / "infra/data/gator_pattern_evolution/state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(
            {
                "processed_claim_ids": ["claim-a", "claim-b", "claim-ghost"],
                "classifications": {
                    "claim-a": {
                        "category": "reinforce",
                        "pattern_id": "gator-ch56-bottom-cycle",
                    },
                    "claim-b": {"category": "irrelevant", "pattern_id": None},
                    "claim-ghost": {"category": "reinforce", "pattern_id": None},
                },
            }
        ),
        encoding="utf-8",
    )
    proposal_path = repo_root / "framework/proposals/20261114-gator-test.yaml"
    proposal_path.parent.mkdir(parents=True, exist_ok=True)
    return {
        "repo_root": repo_root,
        "claims_dir": claims_dir,
        "patterns_path": patterns_path,
        "state_path": state_path,
        "proposal_path": proposal_path,
    }


def _write_proposal(env: dict, decisions: list[dict], *, status: str = "approved") -> None:
    env["proposal_path"].write_text(
        yaml.safe_dump(
            {
                "proposal_id": "20261114-gator-test",
                "school": "gator",
                "status": status,
                "source_report": "reports/gator-pattern-evolution-20261022.md",
                "generated_at": "2026-11-14T00:00:00+08:00",
                "approved_by": "test-user",
                "approved_at": "2026-11-14T01:00:00+08:00",
                "decisions": decisions,
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )


def _apply(env: dict, *, dry_run: bool = False) -> dict:
    return ge.apply_gator_evolution(
        env["proposal_path"],
        patterns_path=env["patterns_path"],
        state_path=env["state_path"],
        claims_dir=env["claims_dir"],
        repo_root=env["repo_root"],
        dry_run=dry_run,
    )


def test_load_gator_claims_supports_single_containers_and_up_id(tmp_path):
    claims_dir = tmp_path / "claims"
    _write_claim(claims_dir, "claim-single")
    _write_claim(claims_dir, "claim-list", school="gator", up_id=None, container="list")
    _write_claim(claims_dir, "claim-container", school="gator", up_id=None, container="claims")
    _write_claim(claims_dir, "claim-other", up_id="other")

    loaded = ge.load_gator_claims(claims_dir)

    assert sorted(c["id"] for c in loaded) == ["claim-container", "claim-list", "claim-single"]
    assert next(c for c in loaded if c["id"] == "claim-single")["_claim_file"] == "claim-single.yaml"


def test_list_pending_separates_review_unclassified_orphans_and_drifts(tmp_path):
    env = _environment(tmp_path)
    doc = yaml.safe_load(env["patterns_path"].read_text(encoding="utf-8"))
    doc["patterns"][0]["drift_flag"] = [
        {"claim_id": "claim-old", "resolution": "pending", "conflict_quote": "旧阈值"}
    ]
    env["patterns_path"].write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")

    pending = ge.list_pending(
        patterns_path=env["patterns_path"],
        state_path=env["state_path"],
        claims_dir=env["claims_dir"],
    )

    assert [x["claim_id"] for x in pending["pending_review"]] == ["claim-a", "claim-b"]
    assert pending["unclassified_claim_ids"] == []
    assert pending["orphan_claim_ids"] == ["claim-ghost"]
    assert pending["unresolved_drifts"][0]["claim_id"] == "claim-old"
    _write_claim(env["claims_dir"], "claim-new", source_date="2026-11-13")
    pending = ge.list_pending(
        patterns_path=env["patterns_path"],
        state_path=env["state_path"],
        claims_dir=env["claims_dir"],
    )
    assert pending["unclassified_claim_ids"] == ["claim-new"]
```

- [ ] **Step 2: 运行测试，确认因模块不存在而失败**

Run: `.venv/bin/pytest tests/test_gator_pattern_evolution_apply.py -v`  
Expected: FAIL，导入 `investment_engine.pattern_eval.gator_evolution` 失败。

- [ ] **Step 3: 实现加载器与 backlog 查询**

创建 `src/investment_engine/pattern_eval/gator_evolution.py`：

```python
from __future__ import annotations

import copy
import difflib
import io
import json
import re
import tempfile
from datetime import date, datetime
from pathlib import Path

import yaml
from ruamel.yaml import YAML

GATOR_UP_ID = "gator-ecyu-0001"
TERMINAL_REVIEW_STATES = {"applied", "reviewed-irrelevant", "rejected"}
STATUS_ACTIONS = {
    "irrelevant": "reviewed-irrelevant",
    "rejected": "rejected",
    "observing": "observing",
}
RULE_ACTIONS = {"reinforce", "refine", "contradict", "new_theme", "repair_provenance"}
REFINE_FIELDS = {"description", "trigger", "steps", "thresholds", "table_rules", "falsification"}
CANDIDATE_FIELDS = {
    "slug", "name", "description", "trigger", "steps", "thresholds",
    "table_rules", "falsification", "computable", "core", "validation",
}


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _norm(value: object) -> str:
    return " ".join(str(value or "").split())


def load_gator_claims(claims_dir: Path) -> list[dict]:
    claims_dir = Path(claims_dir)
    result = []
    for path in sorted(claims_dir.glob("claim-*.yaml")):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(data, dict) and isinstance(data.get("claims"), list):
            claims = data["claims"]
        elif isinstance(data, list):
            claims = data
        elif isinstance(data, dict) and data.get("id"):
            claims = [data]
        else:
            claims = []
        for claim in claims:
            if not isinstance(claim, dict):
                continue
            if claim.get("school") != "gator" and claim.get("up_id") != GATOR_UP_ID:
                continue
            item = dict(claim)
            item["_claim_file"] = path.name
            result.append(item)
    return result


def _claim_map(claims_dir: Path) -> dict[str, dict]:
    claims = load_gator_claims(claims_dir)
    return {c["id"]: c for c in claims if c.get("id")}


def _load_patterns(patterns_path: Path):
    rt = YAML()
    rt.width = 4096
    return rt, rt.load(Path(patterns_path).read_text(encoding="utf-8"))


def list_pending(*, patterns_path: Path, state_path: Path, claims_dir: Path) -> dict:
    doc = yaml.safe_load(Path(patterns_path).read_text(encoding="utf-8"))
    state = json.loads(Path(state_path).read_text(encoding="utf-8"))
    claims = _claim_map(claims_dir)
    review = state.get("review_status", {})
    classifications = state.get("classifications", {})
    pending_review = []
    for claim_id, classification in sorted(classifications.items()):
        if claim_id not in claims:
            continue
        status = review.get(claim_id, {}).get("status", "pending-review")
        if status in TERMINAL_REVIEW_STATES:
            continue
        claim = claims[claim_id]
        pending_review.append({
            "claim_id": claim_id,
            "source_date": str(claim.get("source_date", "")),
            "topic": claim.get("topic", ""),
            "review_status": status,
            **classification,
        })
    state_ids = set(state.get("processed_claim_ids", [])) | set(classifications)
    unresolved = []
    for pattern in doc.get("patterns", []):
        for drift in pattern.get("drift_flag", []) or []:
            if drift.get("resolution") == "pending":
                unresolved.append({"pattern_id": pattern.get("pattern_id"), **drift})
    return {
        "pending_review": pending_review,
        "unclassified_claim_ids": sorted(set(claims) - set(classifications)),
        "orphan_claim_ids": sorted(state_ids - set(claims)),
        "unresolved_drifts": unresolved,
        "counts": {
            "pending_review": len(pending_review),
            "unclassified": len(set(claims) - set(classifications)),
            "orphans": len(state_ids - set(claims)),
            "unresolved_drifts": len(unresolved),
        },
    }
```

在 `scripts/evolve_gator_patterns.py` 的第三方 import 区块（`import yaml` 之后）加入：

```python
from investment_engine.pattern_eval.gator_evolution import load_gator_claims
```

将原 `iter_gator_claims()` 整个函数替换为：

```python
def iter_gator_claims() -> list[dict]:
    return load_gator_claims(CLAIMS_DIR)
```

- [ ] **Step 4: 运行 Task 1 测试与现有分类脚本冒烟测试**

Run: `.venv/bin/pytest tests/test_gator_pattern_evolution_apply.py -v`  
Expected: 2 passed。

Run: `.venv/bin/python -c "from scripts.evolve_gator_patterns import iter_gator_claims; xs=iter_gator_claims(); assert len(xs) >= 212; print(len(xs), xs[-1]['id'])"`  
Expected: 数量至少 212，最后一条为当前按文件排序后的鳄鱼 claim；不再只有 49 条。

- [ ] **Step 5: 检查改动范围**

Run: `git status --short`  
Expected: 仅本任务文件、设计/计划文档和原有 xueqiu 修改；不 commit。

### Task 2: 用 TDD 实现审批写回器

**Files:**
- Modify: `src/investment_engine/pattern_eval/gator_evolution.py`
- Modify: `tests/test_gator_pattern_evolution_apply.py`

- [ ] **Step 1: 追加审批、五类动作、修复与重放失败测试**

在测试文件末尾追加：

```python
def _decision(action: str, claim_id: str = "claim-a", **extra) -> dict:
    base = {
        "action": action,
        "claim_id": claim_id,
        "pattern_id": "gator-ch56-bottom-cycle",
        "evidence_quote": "鳄鱼原文证据",
    }
    base.update(extra)
    return base


def _candidate() -> dict:
    return {
        "slug": "margin-bottom-signals",
        "name": "融资余额磨底信号",
        "description": "两个以上日期确认的磨底观察规则",
        "trigger": ["融资余额连续变化"],
        "steps": ["比较不同日期的融资方向"],
        "thresholds": ["至少两个来源日期"],
        "table_rules": [],
        "falsification": ["后续证据否定磨底"],
        "computable": False,
        "core": False,
        "validation": {},
    }


def test_unapproved_proposal_is_rejected_without_writes(tmp_path):
    env = _environment(tmp_path)
    _write_proposal(env, [_decision("reinforce")], status="pending-review")
    before = {k: env[k].read_bytes() for k in ("patterns_path", "state_path", "proposal_path")}
    with pytest.raises(ValueError, match="approved"):
        _apply(env, dry_run=True)
    assert before == {k: env[k].read_bytes() for k in before}


def test_reinforce_dry_run_apply_and_replay_are_idempotent(tmp_path):
    env = _environment(tmp_path)
    _write_proposal(env, [_decision("reinforce")])
    before = {k: env[k].read_bytes() for k in ("patterns_path", "state_path", "proposal_path")}
    preview = _apply(env, dry_run=True)
    assert "source_claims" in preview["diff"]
    assert before == {k: env[k].read_bytes() for k in before}

    _apply(env)
    doc = yaml.safe_load(env["patterns_path"].read_text(encoding="utf-8"))
    pattern = doc["patterns"][0]
    assert pattern["source_claims"] == ["claim-a"]
    assert pattern["source_dates"] == ["2026-10-15", "2026-11-11"]
    assert pattern["local_evidence_count"] == 1
    assert doc["version"] == "1.2-draft"
    assert len(doc["evolution_log"]) == 1
    state = json.loads(env["state_path"].read_text(encoding="utf-8"))
    assert state["review_status"]["claim-a"]["status"] == "applied"

    settled = {k: env[k].read_bytes() for k in ("patterns_path", "state_path", "proposal_path")}
    _apply(env)
    assert settled == {k: env[k].read_bytes() for k in settled}


def test_refine_checks_whitelist_quotes_and_logs_once(tmp_path):
    env = _environment(tmp_path)
    bad = _decision("refine", set={"name": "不允许"}, conflict_quote="旧阈值")
    _write_proposal(env, [bad])
    with pytest.raises(ValueError, match="禁止修改"):
        _apply(env)

    good = _decision("refine", set={"thresholds": ["新阈值"]}, conflict_quote="旧阈值")
    _write_proposal(env, [good])
    _apply(env)
    doc = yaml.safe_load(env["patterns_path"].read_text(encoding="utf-8"))
    assert doc["patterns"][0]["thresholds"] == ["新阈值"]
    assert doc["patterns"][0]["trigger"] == ["旧触发"]
    change = doc["evolution_log"][0]["changes"][0]
    assert change["before"]["thresholds"] == ["旧阈值"]
    assert change["after"]["thresholds"] == ["新阈值"]


def test_contradict_only_records_unresolved_drift(tmp_path):
    env = _environment(tmp_path)
    _write_proposal(env, [_decision("contradict", conflict_quote="旧阈值")])
    _apply(env)
    doc = yaml.safe_load(env["patterns_path"].read_text(encoding="utf-8"))
    pattern = doc["patterns"][0]
    assert pattern["thresholds"] == ["旧阈值"]
    assert pattern["drift_flag"][0]["resolution"] == "pending"
    assert pattern["drift_flag"][0]["claim_id"] == "claim-a"
    pending = ge.list_pending(
        patterns_path=env["patterns_path"], state_path=env["state_path"], claims_dir=env["claims_dir"]
    )
    assert len(pending["unresolved_drifts"]) == 1


def test_new_theme_requires_two_dates_and_assigns_next_chapter(tmp_path):
    env = _environment(tmp_path)
    _write_proposal(env, [{"action": "new_theme", "claim_ids": ["claim-a"], "candidate_pattern": _candidate()}])
    with pytest.raises(ValueError, match="两个不同"):
        _apply(env)

    _write_proposal(env, [{"action": "new_theme", "claim_ids": ["claim-a", "claim-b"], "candidate_pattern": _candidate()}])
    _apply(env)
    doc = yaml.safe_load(env["patterns_path"].read_text(encoding="utf-8"))
    created = doc["patterns"][-1]
    assert created["pattern_id"] == "gator-ch57-margin-bottom-signals"
    assert created["chapter"] == 57
    assert created["school"] == "gator"
    assert created["source_claims"] == ["claim-a", "claim-b"]
    assert created["local_evidence_count"] == 2
    assert created["provenance"] == "local-gator-evolution"
    assert "slug" not in created
    state = json.loads(env["state_path"].read_text(encoding="utf-8"))
    assert state["review_status"]["claim-b"]["status"] == "applied"
    settled = {k: env[k].read_bytes() for k in ("patterns_path", "state_path", "proposal_path")}
    _apply(env)
    assert settled == {k: env[k].read_bytes() for k in settled}


def test_status_only_decisions_do_not_change_rule_version(tmp_path):
    env = _environment(tmp_path)
    decisions = [
        _decision("irrelevant"),
        _decision("observing", claim_id="claim-b", note="等待第二日期"),
    ]
    _write_proposal(env, decisions)
    _apply(env)
    doc = yaml.safe_load(env["patterns_path"].read_text(encoding="utf-8"))
    assert doc["version"] == "1.1-draft"
    assert doc["evolution_log"] == []
    state = json.loads(env["state_path"].read_text(encoding="utf-8"))
    assert state["review_status"]["claim-a"]["status"] == "reviewed-irrelevant"
    assert state["review_status"]["claim-b"]["status"] == "observing"


def test_repair_provenance_removes_only_broken_source(tmp_path):
    env = _environment(tmp_path)
    doc = yaml.safe_load(env["patterns_path"].read_text(encoding="utf-8"))
    doc["patterns"][0]["source_path"] = "sources/third_party/missing-ch56.md"
    env["patterns_path"].write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")
    decision = {
        "action": "repair_provenance",
        "pattern_id": "gator-ch56-bottom-cycle",
        "claim_ids": ["claim-a", "claim-b"],
        "reason": "broken-source-path",
        "provenance": "local-gator-evolution",
    }
    _write_proposal(env, [decision])
    _apply(env)
    repaired = yaml.safe_load(env["patterns_path"].read_text(encoding="utf-8"))["patterns"][0]
    assert "source_path" not in repaired
    assert repaired["provenance"] == "local-gator-evolution"
    assert repaired["source_claims"] == ["claim-a", "claim-b"]
    assert repaired["source_raw"] == ["sources/raw/gator.md"]
    assert repaired["thresholds"] == ["旧阈值"]


def test_replay_after_state_write_failure_does_not_double_apply(tmp_path, monkeypatch):
    env = _environment(tmp_path)
    _write_proposal(env, [_decision("reinforce")])
    original_write = ge._atomic_write

    def fail_state(path, text):
        if Path(path) == env["state_path"]:
            raise OSError("simulated state failure")
        original_write(path, text)

    monkeypatch.setattr(ge, "_atomic_write", fail_state)
    with pytest.raises(OSError, match="simulated"):
        _apply(env)
    monkeypatch.setattr(ge, "_atomic_write", original_write)
    _apply(env)
    doc = yaml.safe_load(env["patterns_path"].read_text(encoding="utf-8"))
    assert doc["version"] == "1.2-draft"
    assert len(doc["evolution_log"]) == 1
    assert doc["patterns"][0]["source_claims"] == ["claim-a"]
```

- [ ] **Step 2: 运行新增测试，确认执行函数缺失**

Run: `.venv/bin/pytest tests/test_gator_pattern_evolution_apply.py -v`  
Expected: 新测试因 `apply_gator_evolution` 或写回辅助函数不存在而 FAIL；Task 1 的 2 条测试仍通过。

- [ ] **Step 3: 实现提案校验、写回、序列化与原子落盘**

在 `gator_evolution.py` 末尾追加：

```python
def _dump_rt(rt: YAML, doc: dict) -> str:
    buf = io.StringIO()
    rt.dump(doc, buf)
    return buf.getvalue()


def _atomic_write(path: Path, text: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_name = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as tmp:
            tmp.write(text)
            tmp_name = tmp.name
        Path(tmp_name).replace(path)
    finally:
        if tmp_name and Path(tmp_name).exists():
            Path(tmp_name).unlink()


def _decision_claim_ids(decision: dict) -> list[str]:
    if decision.get("claim_ids") is not None:
        return list(decision["claim_ids"])
    return [decision["claim_id"]] if decision.get("claim_id") else []


def _decision_key(decision: dict) -> str:
    candidate = decision.get("candidate_pattern", {})
    identity = {
        "action": decision.get("action"),
        "claim_ids": sorted(_decision_claim_ids(decision)),
        "pattern_id": decision.get("pattern_id"),
        "slug": candidate.get("slug"),
    }
    return json.dumps(identity, ensure_ascii=False, sort_keys=True)


def _logged_keys(doc: dict) -> set[str]:
    return {
        change["decision_key"]
        for entry in doc.get("evolution_log", []) or []
        for change in entry.get("changes", []) or []
        if change.get("decision_key")
    }


def _claims_for(decision: dict, claims: dict[str, dict], repo_root: Path) -> list[dict]:
    ids = _decision_claim_ids(decision)
    if not ids:
        raise ValueError("decision 缺 claim_id/claim_ids")
    result = []
    for claim_id in ids:
        if claim_id not in claims:
            raise ValueError(f"未知 claim_id: {claim_id}")
        claim = claims[claim_id]
        source = claim.get("source_path")
        if not source or not (repo_root / source).exists():
            raise ValueError(f"{claim_id}: 原文路径不存在: {source}")
        if not _norm(claim.get("evidence_quote")):
            raise ValueError(f"{claim_id}: 缺 evidence_quote")
        result.append(claim)
    return result


def validate_gator_document(doc: dict, repo_root: Path, *, allow_broken: set[str] | None = None) -> None:
    allow_broken = allow_broken or set()
    patterns = doc.get("patterns")
    if not isinstance(patterns, list) or not patterns:
        raise ValueError("patterns 必须是非空列表")
    ids = [p.get("pattern_id") for p in patterns]
    if len(ids) != len(set(ids)):
        raise ValueError("pattern_id 重复")
    for pattern in patterns:
        pid = pattern.get("pattern_id")
        for field in ("school", "name", "chapter", "description", "trigger", "steps", "validation"):
            if field not in pattern:
                raise ValueError(f"{pid}: 缺字段 {field}")
        if pattern["school"] != "gator":
            raise ValueError(f"{pid}: school 必须为 gator")
        source = pattern.get("source_path")
        if source and pid not in allow_broken and not (repo_root / source).exists():
            raise ValueError(f"{pid}: source_path 不存在: {source}")
        source_claims = pattern.get("source_claims", []) or []
        if str(pattern.get("provenance", "")).startswith("local-gator-evolution") and not source_claims:
            raise ValueError(f"{pid}: 本地演进 pattern 缺 source_claims")
        if source_claims and pattern.get("local_evidence_count") != len(set(source_claims)):
            raise ValueError(f"{pid}: local_evidence_count 与 source_claims 不一致")
        if not isinstance(pattern.get("drift_flag", []), list):
            raise ValueError(f"{pid}: drift_flag 必须是列表")


def _validate_decision(decision: dict, doc: dict, claims: dict[str, dict], repo_root: Path, logged: set[str]) -> None:
    action = decision.get("action")
    if action not in RULE_ACTIONS and action not in STATUS_ACTIONS:
        raise ValueError(f"未知 action: {action}")
    decision_claims = _claims_for(decision, claims, repo_root)
    patterns = {p["pattern_id"]: p for p in doc["patterns"]}
    key = _decision_key(decision)
    if key in logged:
        return
    if action in STATUS_ACTIONS:
        if action in {"rejected", "observing"} and not decision.get("note"):
            raise ValueError(f"{action} 必须填写 note")
        return
    pid = decision.get("pattern_id")
    if action != "new_theme" and pid not in patterns:
        raise ValueError(f"未知 pattern_id: {pid}")
    if action in {"reinforce", "refine", "contradict"}:
        quote = _norm(decision.get("evidence_quote"))
        if not quote or quote not in _norm(decision_claims[0].get("evidence_quote")):
            raise ValueError("evidence_quote 不是 claim 原文的子串")
    if action in {"refine", "contradict"}:
        conflict = _norm(decision.get("conflict_quote"))
        if not conflict or conflict not in _norm(_dump_rt(YAML(), patterns[pid])):
            raise ValueError("conflict_quote 未命中目标 pattern 原文")
    if action == "refine":
        changes = decision.get("set")
        if not isinstance(changes, dict) or not changes:
            raise ValueError("refine 缺非空 set")
        forbidden = set(changes) - REFINE_FIELDS
        if forbidden:
            raise ValueError(f"禁止修改字段: {sorted(forbidden)}")
    if action == "new_theme":
        candidate = decision.get("candidate_pattern")
        if not isinstance(candidate, dict) or set(candidate) != CANDIDATE_FIELDS:
            raise ValueError(f"candidate_pattern 字段必须精确为 {sorted(CANDIDATE_FIELDS)}")
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", candidate["slug"]):
            raise ValueError("candidate_pattern.slug 必须为 kebab-case")
        if len({str(c.get("source_date")) for c in decision_claims}) < 2:
            raise ValueError("new_theme 至少需要两个不同 source_date")
    if action == "repair_provenance":
        if decision.get("reason") != "broken-source-path":
            raise ValueError("repair_provenance 只接受 broken-source-path")
        if not str(decision.get("provenance", "")).startswith("local-gator-evolution"):
            raise ValueError("repair_provenance 必须写本地 provenance")
        source = patterns[pid].get("source_path")
        if key not in logged and (not source or (repo_root / source).exists()):
            raise ValueError("repair_provenance 要求现有 source_path 已失效")


def _add_evidence(pattern: dict, claims: list[dict]) -> None:
    claim_ids = sorted(set(pattern.get("source_claims", []) or []) | {c["id"] for c in claims})
    dates = sorted(set(pattern.get("source_dates", []) or []) | {str(c["source_date"]) for c in claims})
    raw = sorted(set(pattern.get("source_raw", []) or []) | {c["source_path"] for c in claims})
    pattern["source_claims"] = claim_ids
    pattern["source_dates"] = dates
    pattern["source_raw"] = raw
    pattern["local_evidence_count"] = len(claim_ids)


def _set_review(state: dict, claim_ids: list[str], status: str, proposal_id: str, note: str = "") -> None:
    review = state.setdefault("review_status", {})
    for claim_id in claim_ids:
        existing = review.get(claim_id, {})
        if (existing.get("status") == status and existing.get("proposal_id") == proposal_id
                and existing.get("note", "") == note):
            continue
        review[claim_id] = {
            "status": status,
            "proposal_id": proposal_id,
            "updated_at": _now(),
            "note": note,
        }


def _next_version(version: str) -> str:
    match = re.fullmatch(r"(\d+)\.(\d+)(-draft)?", version)
    if not match:
        raise ValueError(f"不支持的版本格式: {version}")
    return f"{match.group(1)}.{int(match.group(2)) + 1}{match.group(3) or ''}"


def _apply_rule_decision(decision: dict, doc: dict, claims: dict[str, dict], repo_root: Path) -> dict:
    action = decision["action"]
    decision_claims = _claims_for(decision, claims, repo_root)
    patterns = {p["pattern_id"]: p for p in doc["patterns"]}
    pid = decision.get("pattern_id")
    before = None
    if action in {"refine", "repair_provenance"}:
        tracked = ("source_path", "provenance", "description", "trigger", "steps", "thresholds", "table_rules", "falsification")
        before = {key: copy.deepcopy(patterns[pid].get(key)) for key in tracked if key in patterns[pid]}
    if action == "new_theme":
        candidate = copy.deepcopy(decision["candidate_pattern"])
        slug = candidate.pop("slug")
        chapter = max(int(p["chapter"]) for p in doc["patterns"]) + 1
        pid = f"gator-ch{chapter:02d}-{slug}"
        pattern = {
            "pattern_id": pid,
            "school": "gator",
            "name": candidate.pop("name"),
            "chapter": chapter,
            "description": candidate.pop("description"),
            "trigger": candidate.pop("trigger"),
            "steps": candidate.pop("steps"),
            "thresholds": candidate.pop("thresholds"),
            "table_rules": candidate.pop("table_rules"),
            "falsification": candidate.pop("falsification"),
            "computable": candidate.pop("computable"),
            "core": candidate.pop("core"),
            "source_ref": "",
            "source_dates": [],
            "source_raw": [],
            "provenance": "local-gator-evolution",
            "validation": candidate.pop("validation"),
        }
        doc["patterns"].append(pattern)
        patterns[pid] = pattern
        _add_evidence(pattern, decision_claims)
    elif action == "repair_provenance":
        pattern = patterns[pid]
        pattern.pop("source_path", None)
        pattern["provenance"] = decision["provenance"]
        _add_evidence(pattern, decision_claims)
    else:
        pattern = patterns[pid]
        if action in {"reinforce", "refine"}:
            _add_evidence(pattern, decision_claims)
        if action == "refine":
            for key, value in decision["set"].items():
                pattern[key] = copy.deepcopy(value)
        if action == "contradict":
            claim = decision_claims[0]
            pattern.setdefault("drift_flag", []).append({
                "claim_id": claim["id"],
                "source_date": str(claim["source_date"]),
                "quote": decision["evidence_quote"],
                "conflict_quote": decision["conflict_quote"],
                "resolution": "pending",
            })
    change = {
        "decision_key": _decision_key(decision),
        "action": action,
        "pattern_id": pid,
        "claim_ids": sorted(c["id"] for c in decision_claims),
    }
    if before is not None:
        change["before"] = before
        change["after"] = {key: copy.deepcopy(patterns[pid].get(key)) for key in before}
    return change


def _diff(label: str, before: str, after: str) -> str:
    return "".join(difflib.unified_diff(
        before.splitlines(keepends=True), after.splitlines(keepends=True),
        fromfile=f"{label} (before)", tofile=f"{label} (after)",
    ))


def apply_gator_evolution(
    proposal_path: Path,
    *,
    patterns_path: Path,
    state_path: Path,
    claims_dir: Path,
    repo_root: Path,
    dry_run: bool = False,
) -> dict:
    proposal_path = Path(proposal_path)
    patterns_path = Path(patterns_path)
    state_path = Path(state_path)
    repo_root = Path(repo_root)
    original_patterns = patterns_path.read_text(encoding="utf-8")
    original_state = state_path.read_text(encoding="utf-8")
    original_proposal = proposal_path.read_text(encoding="utf-8")
    proposal_data = yaml.safe_load(original_proposal)
    if proposal_data.get("school") != "gator":
        raise ValueError("提案 school 必须为 gator")
    if proposal_data.get("status") not in {"approved", "applied"}:
        raise ValueError("提案必须为 approved（applied 仅用于幂等重放）")
    if not proposal_data.get("approved_by") or not proposal_data.get("approved_at"):
        raise ValueError("approved 提案缺 approved_by/approved_at")
    decisions = proposal_data.get("decisions")
    if not isinstance(decisions, list) or not decisions:
        raise ValueError("提案缺非空 decisions")

    claims = _claim_map(claims_dir)
    rt, doc = _load_patterns(patterns_path)
    logged = _logged_keys(doc)
    repair_ids = {d.get("pattern_id") for d in decisions if d.get("action") == "repair_provenance"}
    validate_gator_document(doc, repo_root, allow_broken=repair_ids)
    for decision in decisions:
        _validate_decision(decision, doc, claims, repo_root, logged)

    state = json.loads(original_state)
    proposal_rt = YAML()
    proposal_rt.width = 4096
    proposal_doc = proposal_rt.load(original_proposal)
    proposal_id = proposal_data["proposal_id"]
    report = {"applied": [], "skipped": [], "changes": [], "version": doc.get("version")}
    for decision in decisions:
        key = _decision_key(decision)
        claim_ids = _decision_claim_ids(decision)
        action = decision["action"]
        if action in STATUS_ACTIONS:
            status = STATUS_ACTIONS[action]
            _set_review(state, claim_ids, status, proposal_id, decision.get("note", ""))
            report["applied"].append(key)
            continue
        if key in logged:
            _set_review(state, claim_ids, "applied", proposal_id)
            report["skipped"].append({"decision_key": key, "reason": "已写回，仅修复复核状态"})
            continue
        change = _apply_rule_decision(decision, doc, claims, repo_root)
        report["changes"].append(change)
        report["applied"].append(key)
        _set_review(state, claim_ids, "applied", proposal_id)

    if report["changes"]:
        version = _next_version(doc["version"])
        doc["version"] = version
        doc["updated_at"] = _now()
        doc.setdefault("evolution_log", []).append({
            "version": version,
            "date": date.today().isoformat(),
            "proposal_id": proposal_id,
            "approved_by": proposal_data["approved_by"],
            "applied_at": _now(),
            "changes": report["changes"],
        })
        report["version"] = version
    validate_gator_document(doc, repo_root)

    if proposal_doc.get("status") != "applied":
        proposal_doc["status"] = "applied"
        proposal_doc["applied_at"] = _now()
    proposal_doc["applied_pattern_version"] = report["version"]
    patterns_text = _dump_rt(rt, doc)
    state_text = json.dumps(state, ensure_ascii=False, indent=2) + "\n"
    proposal_text = _dump_rt(proposal_rt, proposal_doc)
    report["diff"] = (
        _diff(str(patterns_path), original_patterns, patterns_text)
        + _diff(str(state_path), original_state, state_text)
        + _diff(str(proposal_path), original_proposal, proposal_text)
    )
    if not dry_run:
        if patterns_text != original_patterns:
            _atomic_write(patterns_path, patterns_text)
        if state_text != original_state:
            _atomic_write(state_path, state_text)
        if proposal_text != original_proposal:
            _atomic_write(proposal_path, proposal_text)
    return report
```

- [ ] **Step 4: 运行全部写回测试并修复实现问题**

Run: `.venv/bin/pytest tests/test_gator_pattern_evolution_apply.py -v`  
Expected: 全部 PASS；若 new_theme 构造或路径参数有错误，按测试修正，不放宽测试的审批、证据或幂等要求。

- [ ] **Step 5: 检查生产文件未受测试影响**

Run: `git status --short -- framework/reasoning-patterns-gator.yaml infra/data/gator_pattern_evolution/state.json`  
Expected: 无输出；测试只写 `tmp_path`。

### Task 3: 添加薄 CLI 并验证真实 backlog

**Files:**
- Create: `scripts/apply_gator_pattern_evolution.py`

- [ ] **Step 1: 创建 CLI**

```python
#!/usr/bin/env python3
"""查询鳄鱼规则演进待办，或应用用户已批准的演进提案。"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from investment_engine.pattern_eval.gator_evolution import (
    apply_gator_evolution,
    list_pending,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("proposal", nargs="?")
    parser.add_argument("--patterns", default=str(REPO_ROOT / "framework/reasoning-patterns-gator.yaml"))
    parser.add_argument("--state", default=str(REPO_ROOT / "infra/data/gator_pattern_evolution/state.json"))
    parser.add_argument("--claims-dir", default=str(REPO_ROOT / "knowledge/claims"))
    parser.add_argument("--repo-root", default=str(REPO_ROOT))
    parser.add_argument("--list-pending", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if args.list_pending:
        if args.proposal:
            parser.error("--list-pending 不接受 proposal")
        report = list_pending(
            patterns_path=Path(args.patterns),
            state_path=Path(args.state),
            claims_dir=Path(args.claims_dir),
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    if not args.proposal:
        parser.error("需要 proposal，或使用 --list-pending")
    report = apply_gator_evolution(
        Path(args.proposal),
        patterns_path=Path(args.patterns),
        state_path=Path(args.state),
        claims_dir=Path(args.claims_dir),
        repo_root=Path(args.repo_root),
        dry_run=args.dry_run,
    )
    print(f"[version] {report['version']}")
    print(f"[applied] {len(report['applied'])}")
    print(f"[skipped] {len(report['skipped'])}")
    if args.dry_run:
        print(report["diff"])
        print("[dry-run] 未落盘")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: 验证 CLI 帮助和真实只读 backlog**

Run: `.venv/bin/python scripts/apply_gator_pattern_evolution.py --help`  
Expected: 显示 `--list-pending`、`--patterns`、`--state`、`--claims-dir`、`--dry-run`。

Run: `.venv/bin/python scripts/apply_gator_pattern_evolution.py --list-pending > /tmp/gator-pending.json && .venv/bin/python -c "import json; d=json.load(open('/tmp/gator-pending.json')); print(d['counts']); assert 'pending_review' in d and 'unresolved_drifts' in d"`  
Expected: 输出真实四类计数；命令只读，不改 state。

- [ ] **Step 3: 验证真实输入未改**

Run: `git status --short -- framework/reasoning-patterns-gator.yaml infra/data/gator_pattern_evolution/state.json`  
Expected: 无输出。

### Task 4: 修正路由测试的固定 51 条基线

**Files:**
- Modify: `tests/test_pattern_prompt_policy.py:230-246`

- [ ] **Step 1: 固化真实 51 个基线 ID，并增加允许追加的回归测试**

在 `test_real_gator_patterns_keep_ids_order_and_validation()` 前加入：

```python
GATOR_BASELINE_IDS = [
    "gator-ch01-stop-falling-5-signals",
    "gator-ch02-mainline-3-buy-points",
    "gator-ch03-mainline-horse-race",
    "gator-ch04-position-sizing",
    "gator-ch05-take-profit",
    "gator-ch06-long-short-response",
    "gator-ch07-defense-vs-offense",
    "gator-ch08-scissors-divergence",
    "gator-ch09-offense-defense-sectors",
    "gator-ch10-bull-4-taboos",
    "gator-ch11-secondary-pullback-6-steps",
    "gator-ch12-hedge-3-levels",
    "gator-ch13-four-buy-points",
    "gator-ch14-decline-depth-left-buy",
    "gator-ch15-false-bottom-rules",
    "gator-ch16-decision-6-steps",
    "gator-ch17-three-kinds-of-money",
    "gator-ch18-trading-system-3-investors",
    "gator-ch19-stop-profit-loss-winrate",
    "gator-ch20-emotion-cycle-themes",
    "gator-ch21-industry-cycle-3-turns",
    "gator-ch22-fundamental-framework",
    "gator-ch23-liquidity-fund-behavior",
    "gator-ch24-blackswan-response",
    "gator-ch25-three-kills-defense",
    "gator-ch26-ta-core-thresholds",
    "gator-ch27-longterm-allocation",
    "gator-ch28-five-system-articles",
    "gator-ch29-shortterm-cash-defense",
    "gator-ch30-shortterm-stock-picking",
    "gator-ch31-dog-walking-gap",
    "gator-ch32-longterm-trapped-3-steps",
    "gator-ch33-weak-band-2-styles",
    "gator-ch37-shortterm-leader-system",
    "gator-ch38-margin-stock-picking",
    "gator-ch39-herd-collapse-bull-end",
    "gator-ch40-market-echelon-decline-4types",
    "gator-ch41-longge-behavior-3-states",
    "gator-ch42-main-contradiction-ai-bubble",
    "gator-ch43-emotion-rhythm-3-waves",
    "gator-ch44-insight-soul-sector",
    "gator-ch45-index-sector-mismatch",
    "gator-ch46-signal-two-faces",
    "gator-ch47-longge-3-axes",
    "gator-ch48-pig-cycle-3-signals",
    "gator-ch49-bottom-structure-2-types",
    "gator-ch50-mainline-replacement",
    "gator-ch51-usbond-asset-choice",
    "gator-ch52-risk-appetite-self",
    "gator-ch53-ai-market-reading-module",
    "gator-ch56-2026-10-16-10-22",
]
```

将现有 `assert len(patterns) == 51` 替换为：

```python
    assert [p["pattern_id"] for p in patterns[: len(GATOR_BASELINE_IDS)]] == GATOR_BASELINE_IDS
    assert len(patterns) >= len(GATOR_BASELINE_IDS)
    assert len({p["pattern_id"] for p in patterns}) == len(patterns)
```

将 `assert len(admitted) == 51` 替换为：

```python
    assert len(admitted) == len(patterns)
```

在 `test_real_gator_patterns_keep_ids_order_and_validation()` 后追加：

```python
def test_gator_baseline_allows_approved_additive_patterns():
    patterns = _load_real_patterns("reasoning-patterns-gator.yaml")
    current_ids = [p["pattern_id"] for p in patterns]
    additive = deepcopy(patterns) + [deepcopy(patterns[-1]) | {"pattern_id": "gator-ch57-test-additive"}]

    admitted = filter_production_patterns(additive)

    assert current_ids[: len(GATOR_BASELINE_IDS)] == GATOR_BASELINE_IDS
    assert [p["pattern_id"] for p in admitted[: len(current_ids)]] == current_ids
    assert admitted[-1]["pattern_id"] == "gator-ch57-test-additive"
```

- [ ] **Step 2: 运行路由测试**

Run: `.venv/bin/pytest tests/test_pattern_prompt_policy.py -v`  
Expected: 全部 PASS；新增测试验证追加合法 pattern 不会被既有基线误伤。

### Task 5: 创建并压力验证 gator-pattern-evolution Skill

**Files:**
- Create: `skills/gator-pattern-evolution/SKILL.md`
- Create: `skills/gator-pattern-evolution/references/review-and-writeback.md`

- [ ] **Step 1: 先运行无 Skill 的 baseline 场景**

派发一个不读取本计划和新 Skill 的子 Agent，只提供以下场景：

```text
仓库已有 framework/reasoning-patterns-gator.yaml 和 scripts/evolve_gator_patterns.py。
本周没有新增 claim，但 state.classifications 中仍有未复核项。
请“更新鳄鱼交易体系”。要求不得修改任何文件，只说明你准备怎么做。
```

记录 baseline 是否出现以下失败：把零新增当零待办、直接写 YAML、写第三方目录、跳过用户审批、只看 LLM 分类而不读原文。预期至少暴露一项，作为 Skill 的 RED 证据。

- [ ] **Step 2: 创建主 Skill**

创建 `skills/gator-pattern-evolution/SKILL.md`：

```markdown
---
name: gator-pattern-evolution
description: Use when 用户要求更新鳄鱼交易体系、处理鳄鱼增量观点、复核鳄鱼规则周报、写回 gator patterns、推进规则演进，或提到给55章鳄鱼体系添砖加瓦。
---

# Gator Pattern Evolution

## 目标

把后续鳄鱼观点沉淀到本地规则库。复用现有 claim 和五分类管线；不重新提炼55章，不直接修改第三方镜像。

## 资产边界

- 第三方基线只读：`sources/third_party/gator-method/`
- 本地规则主库：`framework/reasoning-patterns-gator.yaml`
- 分类状态：`infra/data/gator_pattern_evolution/state.json`
- 审批提案：`framework/proposals/`
- 分类脚本：`scripts/evolve_gator_patterns.py`
- 写回脚本：`scripts/apply_gator_pattern_evolution.py`

## 执行顺序

1. 新原文先走现有 claim 提取和门禁。鳄鱼身份接受 `school: gator` 或 `up_id=gator-ecyu-0001`；新增 claims 后执行 discover → Neo4j → Qdrant → Agent 重载。
2. 运行分类脚本获取五分类。不得把 `processed_claim_ids` 当成已审核或已写回。
3. 运行 `.venv/bin/python scripts/apply_gator_pattern_evolution.py --list-pending`，同时检查待复核、未分类、孤立记录和未解决漂移。本周零新增不等于零待办。
4. 对每条候选读取 claim 的 `evidence_quote`、原文路径和完整目标 pattern；LLM 分类与 top-3 只是建议。
5. 按 `references/review-and-writeback.md` 生成待审提案。缺证据、单源新主题、parse_error 不得写成可执行规则变更。
6. 用户明确批准后，将提案置为 approved 并填批准人/时间；先运行 `--dry-run`，展示 diff。
7. 只有用户明确要求执行写回，才运行不带 `--dry-run` 的命令。不得自行伪造批准，不自动 commit/push。
8. 验证测试、证据引用和待办；需要时重启 Agent 清 pattern 缓存。

## 五类决策

- reinforce：只追加 claims、日期和本地证据数。
- refine：只改批准的白名单字段，保留前后 diff。
- contradict：只登记未解决 drift，不自动裁决。
- new_theme：至少两个不同 source_date，批准后才新增章节。
- irrelevant：只关闭复核状态，不改规则。

## 必须停止

- 缺鳄鱼身份、原文路径或原文引文。
- 要求绕过人工复核、批准或 dry-run。
- 要求修改 `sources/third_party/gator-method/`。
- 要求自动解决矛盾或把单日观点直接升级为规则。
- dry-run 报未知引用、失效路径、非法字段或证据不一致。

详细提案格式、状态与验收见 `references/review-and-writeback.md`。
```

- [ ] **Step 3: 创建复核与写回参考**

创建 `skills/gator-pattern-evolution/references/review-and-writeback.md`，必须完整写入以下契约，不省略字段：

1. 提案顶层：`proposal_id/school/status/source_report/generated_at/approved_by/approved_at/decisions`；执行后为 `applied/applied_at/applied_pattern_version`。
2. 通用单 claim decision：`action/claim_id/evidence_quote`；pattern 动作另有 `pattern_id`，refine/contradict 另有 `conflict_quote`，refine 另有 `set`。
3. new_theme：`claim_ids + candidate_pattern`，候选字段精确为 `slug/name/description/trigger/steps/thresholds/table_rules/falsification/computable/core/validation`。
4. repair_provenance：`pattern_id/claim_ids/reason: broken-source-path/provenance`，仅修失效来源，不改规则内容。
5. 状态动作：irrelevant → reviewed-irrelevant；rejected/observing 必须附 note；其他成功 decision → applied。
6. refine 白名单仅为 `description/trigger/steps/thresholds/table_rules/falsification`；禁止改 ID、章节、school、validation。
7. 命令示例使用真实文件名 `framework/proposals/20261114-gator-ch56-provenance-repair.yaml`，分别展示 `--dry-run` 和批准后的执行。
8. 验收清单：原文引文是 claim 子串、双侧冲突引文、至少两个日期、dry-run 三文件不变、重放不重复、非空 source_path 存在、local_evidence_count 等于去重 source_claims 数、未解决 drift 持续出现在 backlog。

- [ ] **Step 4: 用相同场景加载新 Skill 复测**

派发新子 Agent，明确先读取 `skills/gator-pattern-evolution/SKILL.md` 和参考文件，再给予相同场景。预期它必须先列 backlog、拒绝直接写文件、要求提案和用户批准，并指出第三方目录只读。若仍出现 baseline 失败，修订 Skill 后重新复测。

- [ ] **Step 5: 验证 Skill 元数据**

Run: `.venv/bin/python -c "from pathlib import Path; import yaml; p=Path('skills/gator-pattern-evolution/SKILL.md'); s=p.read_text(); front=yaml.safe_load(s.split('---')[1]); assert front['name']=='gator-pattern-evolution'; assert 'qing' not in front['name']; print(front)"`  
Expected: 输出正确名称和触发描述。

### Task 6: 生成第 56 章真实修复提案并设置审批检查点

**Files:**
- Create: `framework/proposals/20261114-gator-ch56-provenance-repair.yaml`
- Modify after separate approval: `framework/reasoning-patterns-gator.yaml`
- Modify after separate approval: `infra/data/gator_pattern_evolution/state.json`

- [ ] **Step 1: 创建待审提案，不修改规则库**

创建 `framework/proposals/20261114-gator-ch56-provenance-repair.yaml`：

```yaml
proposal_id: 20261114-gator-ch56-provenance-repair
school: gator
status: pending-review
source_report: reports/gator-pattern-evolution-20261022.md
generated_at: '2026-11-14T00:00:00+08:00'
approved_by: null
approved_at: null
decisions:
- action: repair_provenance
  pattern_id: gator-ch56-2026-10-16-10-22
  reason: broken-source-path
  provenance: local-gator-evolution（2026-10-22用户批准第56章；2026-11-14仅修复来源）
  claim_ids:
  - claim-20261016-004-d
  - claim-20261016-004-h
  - claim-20261019-003-k
  - claim-20261020-006
  - claim-20261020-007
  - claim-20261021-008-a
  - claim-20261021-008-c
  - claim-20261021-008-d
  - claim-20261021-008-e
  - claim-20261021-008-f
  - claim-20261021-008-g
  - claim-20261021-008-h
  - claim-20261021-009-d
  - claim-20261022-005
  note: 只删除失效第三方source_path并补真实claims证据，不改变第56章规则内容
```

这 14 个 ID 已逐一核实存在，`up_id` 均为 `gator-ecyu-0001`，source_date 覆盖 2026-10-16 至 2026-10-22，原文路径均存在；其中三个主库单 claim 没有 school 字段，由兼容加载器按 up_id 识别。

- [ ] **Step 2: 在临时副本上验证真实修复提案**

复制生产 YAML、state 和提案到 `/tmp/gator-ch56-rehearsal/`，仅在临时提案中改为 approved 并填测试批准人，然后使用临时 `--patterns/--state/--repo-root` 和真实只读 claims 执行 dry-run。为让临时 repo_root 下的原文路径可解析，在 `/tmp/gator-ch56-rehearsal/` 下创建指向仓库 `sources/` 的符号链接；不复制或修改秘密文件。

Run（由执行 Agent 用 Python 创建副本和临时批准文件后执行）：

```bash
.venv/bin/python scripts/apply_gator_pattern_evolution.py \
  /tmp/gator-ch56-rehearsal/proposal.yaml \
  --patterns /tmp/gator-ch56-rehearsal/patterns.yaml \
  --state /tmp/gator-ch56-rehearsal/state.json \
  --repo-root /tmp/gator-ch56-rehearsal \
  --dry-run
```

Expected: 预览只删除 ch56 的失效 `source_path`，补本地 provenance、14 个 source_claims、相应 source_dates/source_raw/local_evidence_count 和 evolution_log；trigger/steps/thresholds/table_rules/falsification/validation 不变。生产文件不变。

- [ ] **Step 3: 暂停并请求真实写回批准**

向用户展示临时 dry-run 摘要，并明确询问是否批准 `20261114-gator-ch56-provenance-repair`。在用户回复批准前，不把生产提案改为 approved，不执行生产写回，不宣称 Task 6 完成。

- [ ] **Step 4: 用户批准后才执行生产写回**

用户明确批准后，将生产提案的 `status/approved_by/approved_at` 按真实信息更新，先对生产路径执行 `--dry-run` 并核对，再执行：

```bash
.venv/bin/python scripts/apply_gator_pattern_evolution.py \
  framework/proposals/20261114-gator-ch56-provenance-repair.yaml
```

Expected: ch56 内容不变、来源修复、版本只递增一次；state 只追加这 14 个 claim 的 applied 复核状态。随后运行全部新增测试和 `tests/test_pattern_prompt_policy.py`。

### Task 7: 更新旧文档并做端到端验收

**Files:**
- Modify: `docs/design/gator-pattern-evolution-design.md`
- Modify if approved: `framework/reasoning-patterns-gator.yaml`
- Modify if approved: `infra/data/gator_pattern_evolution/state.json`

- [ ] **Step 1: 更新旧设计状态**

将 `docs/design/gator-pattern-evolution-design.md` 顶部仍描述 P2 影子期的状态替换为指向以下事实的说明：

```markdown
> 状态：P2 分类能力保留；主库单 claim/up_id 兼容、P4 审批写回与 backlog 由
> `skills/gator-pattern-evolution/` 和 `scripts/apply_gator_pattern_evolution.py` 承接。
> 书面设计见 `docs/superpowers/specs/2026-11-14-gator-pattern-evolution-design.md`。
> 第三方 `sources/third_party/gator-method/` 仍为只读基线，不接收本地增量章节。
> 所有生产写回仍须用户批准；脚本存在不等于自动获准写规则。
```

保留该文档作为历史设计和五分类依据，不把 P4 是否完成写成早于真实验收的结论。

- [ ] **Step 2: 运行新增与相关测试**

Run:

```bash
.venv/bin/pytest \
  tests/test_gator_pattern_evolution_apply.py \
  tests/test_pattern_prompt_policy.py \
  tests/monitor/test_gator_rules.py \
  tests/test_bilibili_notify_gator_hook.py -v
```

Expected: 全部 PASS，无跳过新增测试。

- [ ] **Step 3: 运行项目标准测试**

Run: `.venv/bin/pytest`  
Expected: 标准 non-live 测试通过。若存在失败，先确认是否由本改动引起；本改动引起的必须修复，既有无关失败须保留证据并明确报告，不能宣称全绿。

- [ ] **Step 4: 验证真实只读场景**

Run: `.venv/bin/python scripts/apply_gator_pattern_evolution.py --list-pending > /tmp/gator-pending-final.json`  
随后用 Python 断言输出包含 `pending_review/unclassified_claim_ids/orphan_claim_ids/unresolved_drifts/counts`，并确认加载器覆盖至少 212 条现有鳄鱼 claims。不得自动运行全量 LLM 重分类或把 163 条历史未处理 claim 直接写成规则。

- [ ] **Step 5: 检查最终文件和纪律**

Run: `git status --short`  
确认没有第三方目录改动，没有测试临时文件进入仓库，没有 staged gitignored 文件，没有触碰两个既有 xueqiu 修改。除非用户明确要求，不执行 commit。

Run: `.venv/bin/python -c "from pathlib import Path; import yaml; d=yaml.safe_load(Path('framework/reasoning-patterns-gator.yaml').read_text()); missing=[p['pattern_id'] for p in d['patterns'] if p.get('source_path') and not Path(p['source_path']).exists()]; print(missing)"`  
Expected: 若用户已批准 Task 6 则为 `[]`；若尚未批准，只允许列出已报告的 `gator-ch56-2026-10-16-10-22`，并明确 Task 6 仍待审批，不能标记整个计划完成。
