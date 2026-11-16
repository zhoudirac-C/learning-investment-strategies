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
        "topic": topic,
        "statement": "测试观点",
        "evidence_quote": "鳄鱼原文证据",
    }
    if school is not None:
        claim["school"] = school
    if up_id is not None:
        claim["up_id"] = up_id
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
        "# 保留这条格式注释\n"
        + yaml.safe_dump(
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


def _write_proposal(
    env: dict, decisions: list[dict], *, status: str = "approved"
) -> None:
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


def _file_bytes(env: dict) -> dict:
    return {
        key: env[key].read_bytes()
        for key in ("patterns_path", "state_path", "proposal_path")
    }


def test_load_gator_claims_supports_single_containers_and_up_id(tmp_path):
    claims_dir = tmp_path / "claims"
    _write_claim(claims_dir, "claim-single")
    _write_claim(
        claims_dir, "claim-list", school="gator", up_id=None, container="list"
    )
    _write_claim(
        claims_dir,
        "claim-container",
        school="gator",
        up_id=None,
        container="claims",
    )
    _write_claim(claims_dir, "claim-other", up_id="other")

    loaded = ge.load_gator_claims(claims_dir)

    assert sorted(claim["id"] for claim in loaded) == [
        "claim-container",
        "claim-list",
        "claim-single",
    ]
    assert next(claim for claim in loaded if claim["id"] == "claim-single")[
        "_claim_file"
    ] == "claim-single.yaml"


def test_list_pending_separates_review_unclassified_orphans_and_drifts(tmp_path):
    env = _environment(tmp_path)
    doc = yaml.safe_load(env["patterns_path"].read_text(encoding="utf-8"))
    doc["patterns"][0]["drift_flag"] = [
        {"claim_id": "claim-old", "resolution": "pending", "conflict_quote": "旧阈值"},
        {"claim_id": "claim-resolved", "resolution": "resolved"},
    ]
    env["patterns_path"].write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")

    pending = ge.list_pending(
        patterns_path=env["patterns_path"],
        state_path=env["state_path"],
        claims_dir=env["claims_dir"],
    )

    assert [item["claim_id"] for item in pending["pending_review"]] == [
        "claim-a",
        "claim-b",
    ]
    assert pending["unclassified_claim_ids"] == []
    assert pending["orphan_claim_ids"] == ["claim-ghost"]
    assert [item["claim_id"] for item in pending["unresolved_drifts"]] == ["claim-old"]
    assert pending["counts"] == {
        "pending_review": 2,
        "unclassified": 0,
        "orphans": 1,
        "unresolved_drifts": 1,
    }

    _write_claim(env["claims_dir"], "claim-new", source_date="2026-11-13")
    state = json.loads(env["state_path"].read_text(encoding="utf-8"))
    state["review_status"] = {
        "claim-a": {"status": "applied"},
        "claim-b": {"status": "observing"},
        "claim-review-ghost": {"status": "rejected"},
    }
    env["state_path"].write_text(json.dumps(state), encoding="utf-8")

    pending = ge.list_pending(
        patterns_path=env["patterns_path"],
        state_path=env["state_path"],
        claims_dir=env["claims_dir"],
    )

    assert [item["claim_id"] for item in pending["pending_review"]] == ["claim-b"]
    assert pending["pending_review"][0]["review_status"] == "observing"
    assert pending["unclassified_claim_ids"] == ["claim-new"]
    assert pending["orphan_claim_ids"] == ["claim-ghost", "claim-review-ghost"]


def test_claim_map_rejects_duplicate_claim_ids(tmp_path):
    env = _environment(tmp_path)
    claim_path = env["claims_dir"] / "claim-a.yaml"
    duplicate = yaml.safe_load(claim_path.read_text(encoding="utf-8"))
    (env["claims_dir"] / "claim-z-duplicate.yaml").write_text(
        yaml.safe_dump(duplicate, allow_unicode=True), encoding="utf-8"
    )

    with pytest.raises(ValueError, match="重复 claim_id: claim-a"):
        ge.list_pending(
            patterns_path=env["patterns_path"],
            state_path=env["state_path"],
            claims_dir=env["claims_dir"],
        )


def test_list_pending_does_not_migrate_legacy_id_by_file_stem(tmp_path):
    claims_dir = tmp_path / "claims"
    _write_claim(claims_dir, "claim-x")
    patterns_path = tmp_path / "patterns.yaml"
    patterns_path.write_text(yaml.safe_dump({"patterns": []}), encoding="utf-8")
    state_path = tmp_path / "state.json"
    state_path.write_text(
        json.dumps(
            {
                "processed_claim_ids": ["claim-x-a", "claim-x"],
                "classifications": {
                    "claim-x-a": {
                        "category": "reinforce",
                        "pattern_id": "gator-legacy",
                    },
                    "claim-x": {"category": "irrelevant", "pattern_id": None},
                },
                "review_status": {
                    "claim-x-a": {"status": "applied"},
                    "claim-x": {"status": "observing"},
                },
            }
        ),
        encoding="utf-8",
    )

    pending = ge.list_pending(
        patterns_path=patterns_path,
        state_path=state_path,
        claims_dir=claims_dir,
    )

    assert pending["orphan_claim_ids"] == ["claim-x-a"]
    assert pending["unclassified_claim_ids"] == []
    assert len(pending["pending_review"]) == 1
    current = pending["pending_review"][0]
    assert current["claim_id"] == "claim-x"
    assert current["category"] == "irrelevant"
    assert current["pattern_id"] is None
    assert current["review_status"] == "observing"


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
        "validation": {"status": "unvalidated"},
    }


def test_unapproved_proposal_is_rejected_without_writes(tmp_path):
    env = _environment(tmp_path)
    _write_proposal(env, [_decision("reinforce")], status="pending-review")
    before = _file_bytes(env)
    with pytest.raises(ValueError, match="approved"):
        _apply(env, dry_run=True)
    assert _file_bytes(env) == before

    _write_proposal(env, [_decision("reinforce")])
    proposal = yaml.safe_load(env["proposal_path"].read_text(encoding="utf-8"))
    proposal["approved_by"] = None
    env["proposal_path"].write_text(yaml.safe_dump(proposal), encoding="utf-8")
    before = _file_bytes(env)
    with pytest.raises(ValueError, match="approved_by"):
        _apply(env, dry_run=True)
    assert _file_bytes(env) == before


def test_reinforce_dry_run_apply_and_replay_are_idempotent(tmp_path):
    env = _environment(tmp_path)
    _write_proposal(env, [_decision("reinforce")])
    before = _file_bytes(env)

    preview = _apply(env, dry_run=True)

    assert "source_claims" in preview["diff"]
    assert "review_status" in preview["diff"]
    assert _file_bytes(env) == before

    _apply(env)
    doc = yaml.safe_load(env["patterns_path"].read_text(encoding="utf-8"))
    pattern = doc["patterns"][0]
    assert pattern["source_claims"] == ["claim-a"]
    assert pattern["source_dates"] == ["2026-10-15", "2026-11-11"]
    assert pattern["source_raw"] == ["sources/raw/gator.md"]
    assert pattern["local_evidence_count"] == 1
    assert doc["version"] == "1.2-draft"
    assert len(doc["evolution_log"]) == 1
    assert env["patterns_path"].read_text(encoding="utf-8").startswith("# 保留这条格式注释\n")
    state = json.loads(env["state_path"].read_text(encoding="utf-8"))
    assert state["review_status"]["claim-a"]["status"] == "applied"
    proposal = yaml.safe_load(env["proposal_path"].read_text(encoding="utf-8"))
    assert proposal["status"] == "applied"
    assert proposal["applied_pattern_version"] == "1.2-draft"

    settled = _file_bytes(env)
    _apply(env)
    assert _file_bytes(env) == settled


def test_unknown_references_and_bad_evidence_reject_whole_batch(tmp_path):
    env = _environment(tmp_path)
    decisions = [
        _decision("reinforce"),
        _decision("reinforce", claim_id="claim-missing"),
    ]
    _write_proposal(env, decisions)
    before = _file_bytes(env)
    with pytest.raises(ValueError, match="未知 claim_id"):
        _apply(env)
    assert _file_bytes(env) == before

    _write_proposal(env, [_decision("reinforce", pattern_id="gator-missing")])
    before = _file_bytes(env)
    with pytest.raises(ValueError, match="未知 pattern_id"):
        _apply(env)
    assert _file_bytes(env) == before

    _write_proposal(env, [_decision("reinforce", evidence_quote="伪造引文")])
    before = _file_bytes(env)
    with pytest.raises(ValueError, match="evidence_quote"):
        _apply(env)
    assert _file_bytes(env) == before


def test_broken_source_path_is_not_skipped(tmp_path):
    env = _environment(tmp_path)
    doc = yaml.safe_load(env["patterns_path"].read_text(encoding="utf-8"))
    doc["patterns"][0]["source_path"] = "sources/third_party/missing-ch56.md"
    env["patterns_path"].write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")
    _write_proposal(env, [_decision("reinforce")])
    before = _file_bytes(env)

    with pytest.raises(ValueError, match="source_path 不存在"):
        _apply(env, dry_run=True)

    assert _file_bytes(env) == before


def test_refine_checks_whitelist_quotes_and_logs_once_per_batch(tmp_path):
    env = _environment(tmp_path)
    bad = _decision("refine", set={"name": "不允许"}, conflict_quote="旧阈值")
    _write_proposal(env, [bad])
    before = _file_bytes(env)
    with pytest.raises(ValueError, match="禁止修改"):
        _apply(env)
    assert _file_bytes(env) == before

    _write_proposal(
        env,
        [
            _decision("refine", set={"thresholds": ["新阈值"]}, conflict_quote="旧阈值"),
            _decision("reinforce", claim_id="claim-b"),
        ],
    )
    _apply(env)
    doc = yaml.safe_load(env["patterns_path"].read_text(encoding="utf-8"))
    pattern = doc["patterns"][0]
    assert pattern["thresholds"] == ["新阈值"]
    assert pattern["trigger"] == ["旧触发"]
    assert pattern["source_claims"] == ["claim-a", "claim-b"]
    assert doc["version"] == "1.2-draft"
    assert len(doc["evolution_log"]) == 1
    assert len(doc["evolution_log"][0]["changes"]) == 2
    change = doc["evolution_log"][0]["changes"][0]
    assert change["before"]["thresholds"] == ["旧阈值"]
    assert change["after"]["thresholds"] == ["新阈值"]
    assert "name" not in change["after"]


def test_refine_replay_after_clause_removal_is_byte_identical(tmp_path):
    env = _environment(tmp_path)
    _write_proposal(
        env,
        [_decision("refine", set={"thresholds": ["新阈值"]}, conflict_quote="旧阈值")],
    )
    _apply(env)
    settled = _file_bytes(env)

    report = _apply(env)

    assert report["changes"] == []
    assert len(report["skipped"]) == 1
    assert _file_bytes(env) == settled


def test_refine_state_write_failure_recovers_without_reapplying(tmp_path, monkeypatch):
    env = _environment(tmp_path)
    _write_proposal(
        env,
        [_decision("refine", set={"thresholds": ["新阈值"]}, conflict_quote="旧阈值")],
    )
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
    assert doc["patterns"][0]["thresholds"] == ["新阈值"]
    state = json.loads(env["state_path"].read_text(encoding="utf-8"))
    assert state["review_status"]["claim-a"]["status"] == "applied"
    proposal = yaml.safe_load(env["proposal_path"].read_text(encoding="utf-8"))
    assert proposal["status"] == "applied"
    assert proposal["applied_pattern_version"] == "1.2-draft"

    settled = _file_bytes(env)
    _apply(env)
    assert _file_bytes(env) == settled


def test_contradict_only_records_unresolved_drift(tmp_path):
    env = _environment(tmp_path)
    _write_proposal(env, [_decision("contradict", conflict_quote="不存在的旧规则")])
    before = _file_bytes(env)
    with pytest.raises(ValueError, match="conflict_quote"):
        _apply(env)
    assert _file_bytes(env) == before

    _write_proposal(env, [_decision("contradict", conflict_quote="旧阈值")])
    _apply(env)
    doc = yaml.safe_load(env["patterns_path"].read_text(encoding="utf-8"))
    pattern = doc["patterns"][0]
    assert pattern["thresholds"] == ["旧阈值"]
    assert pattern["trigger"] == ["旧触发"]
    assert "source_claims" not in pattern
    assert pattern["drift_flag"][0]["resolution"] == "pending"
    assert pattern["drift_flag"][0]["claim_id"] == "claim-a"
    pending = ge.list_pending(
        patterns_path=env["patterns_path"],
        state_path=env["state_path"],
        claims_dir=env["claims_dir"],
    )
    assert len(pending["unresolved_drifts"]) == 1
    assert [item["claim_id"] for item in pending["pending_review"]] == ["claim-b"]


def test_new_theme_requires_two_real_dates_and_assigns_next_chapter(tmp_path):
    env = _environment(tmp_path)
    _write_proposal(
        env,
        [{"action": "new_theme", "claim_ids": ["claim-a"], "candidate_pattern": _candidate()}],
    )
    before = _file_bytes(env)
    with pytest.raises(ValueError, match="两个不同"):
        _apply(env)
    assert _file_bytes(env) == before

    _write_claim(env["claims_dir"], "claim-no-date", source_date="")
    _write_proposal(
        env,
        [
            {
                "action": "new_theme",
                "claim_ids": ["claim-a", "claim-no-date"],
                "candidate_pattern": _candidate(),
            }
        ],
    )
    before = _file_bytes(env)
    with pytest.raises(ValueError, match="source_date"):
        _apply(env)
    assert _file_bytes(env) == before

    _write_proposal(
        env,
        [
            {
                "action": "new_theme",
                "claim_ids": ["claim-a", "claim-b"],
                "candidate_pattern": _candidate(),
            }
        ],
    )
    _apply(env)
    doc = yaml.safe_load(env["patterns_path"].read_text(encoding="utf-8"))
    created = doc["patterns"][-1]
    assert created["pattern_id"] == "gator-ch57-margin-bottom-signals"
    assert created["chapter"] == 57
    assert created["school"] == "gator"
    assert created["source_claims"] == ["claim-a", "claim-b"]
    assert created["source_dates"] == ["2026-11-11", "2026-11-12"]
    assert created["local_evidence_count"] == 2
    assert created["provenance"] == "local-gator-evolution"
    assert created["validation"] == {"status": "unvalidated"}
    assert "source_path" not in created
    assert "slug" not in created
    state = json.loads(env["state_path"].read_text(encoding="utf-8"))
    assert state["review_status"]["claim-b"]["status"] == "applied"

    settled = _file_bytes(env)
    _apply(env)
    assert _file_bytes(env) == settled


def test_status_only_decisions_do_not_change_rule_file_or_version(tmp_path):
    env = _environment(tmp_path)
    _write_claim(env["claims_dir"], "claim-c", source_date="2026-11-13")
    decisions = [
        _decision("irrelevant"),
        _decision("rejected", claim_id="claim-b", note="人工否定归类"),
        _decision("observing", claim_id="claim-c", note="等待第二日期"),
    ]
    _write_proposal(env, decisions)
    rules_before = env["patterns_path"].read_bytes()
    _apply(env)

    assert env["patterns_path"].read_bytes() == rules_before
    doc = yaml.safe_load(rules_before)
    assert doc["version"] == "1.1-draft"
    assert doc["evolution_log"] == []
    state = json.loads(env["state_path"].read_text(encoding="utf-8"))
    assert state["review_status"]["claim-a"]["status"] == "reviewed-irrelevant"
    assert state["review_status"]["claim-b"]["status"] == "rejected"
    assert state["review_status"]["claim-c"]["status"] == "observing"

    settled = _file_bytes(env)
    _apply(env)
    assert _file_bytes(env) == settled


def test_applied_status_only_replay_preserves_historical_pattern_version(tmp_path):
    env = _environment(tmp_path)
    status_proposal_path = env["proposal_path"]
    _write_proposal(
        env, [_decision("observing", claim_id="claim-a", note="继续观察")]
    )
    _apply(env)
    status_proposal = yaml.safe_load(status_proposal_path.read_text(encoding="utf-8"))
    assert status_proposal["applied_pattern_version"] == "1.1-draft"

    env["proposal_path"] = (
        env["repo_root"] / "framework/proposals/20261115-gator-reinforce.yaml"
    )
    _write_proposal(env, [_decision("reinforce", claim_id="claim-b")])
    later_proposal = yaml.safe_load(env["proposal_path"].read_text(encoding="utf-8"))
    later_proposal["proposal_id"] = "20261115-gator-reinforce"
    env["proposal_path"].write_text(
        yaml.safe_dump(later_proposal, allow_unicode=True), encoding="utf-8"
    )
    _apply(env)
    doc = yaml.safe_load(env["patterns_path"].read_text(encoding="utf-8"))
    assert doc["version"] == "1.2-draft"

    env["proposal_path"] = status_proposal_path
    before = _file_bytes(env)
    _apply(env)

    status_proposal = yaml.safe_load(status_proposal_path.read_text(encoding="utf-8"))
    assert status_proposal["applied_pattern_version"] == "1.1-draft"
    assert _file_bytes(env) == before


def test_rejected_and_observing_require_reason(tmp_path):
    env = _environment(tmp_path)
    for action in ("rejected", "observing"):
        _write_proposal(env, [_decision(action)])
        before = _file_bytes(env)
        with pytest.raises(ValueError, match="note"):
            _apply(env)
        assert _file_bytes(env) == before


def test_repair_provenance_removes_only_broken_source(tmp_path):
    env = _environment(tmp_path)
    decision = {
        "action": "repair_provenance",
        "pattern_id": "gator-ch56-bottom-cycle",
        "claim_ids": ["claim-a", "claim-b"],
        "reason": "broken-source-path",
        "provenance": "local-gator-evolution",
    }
    _write_proposal(env, [decision])
    before = _file_bytes(env)
    with pytest.raises(ValueError, match="已失效"):
        _apply(env)
    assert _file_bytes(env) == before

    doc = yaml.safe_load(env["patterns_path"].read_text(encoding="utf-8"))
    original_validation = doc["patterns"][0]["validation"]
    doc["patterns"][0]["source_path"] = "sources/third_party/missing-ch56.md"
    env["patterns_path"].write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")
    _apply(env)

    repaired_doc = yaml.safe_load(env["patterns_path"].read_text(encoding="utf-8"))
    repaired = repaired_doc["patterns"][0]
    assert "source_path" not in repaired
    assert repaired["provenance"] == "local-gator-evolution"
    assert repaired["source_claims"] == ["claim-a", "claim-b"]
    assert repaired["source_raw"] == ["sources/raw/gator.md"]
    assert repaired["source_dates"] == ["2026-10-15", "2026-11-11", "2026-11-12"]
    assert repaired["local_evidence_count"] == 2
    assert repaired["thresholds"] == ["旧阈值"]
    assert repaired["validation"] == original_validation
    assert repaired_doc["version"] == "1.2-draft"

    settled = _file_bytes(env)
    _apply(env)
    assert _file_bytes(env) == settled


def test_applied_repair_replay_preserves_historical_pattern_version(tmp_path):
    env = _environment(tmp_path)
    doc = yaml.safe_load(env["patterns_path"].read_text(encoding="utf-8"))
    doc["patterns"][0]["source_path"] = "sources/third_party/missing-ch56.md"
    env["patterns_path"].write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")
    repair_proposal_path = env["proposal_path"]
    _write_proposal(
        env,
        [
            {
                "action": "repair_provenance",
                "pattern_id": "gator-ch56-bottom-cycle",
                "claim_ids": ["claim-a", "claim-b"],
                "reason": "broken-source-path",
                "provenance": "local-gator-evolution",
            }
        ],
    )
    _apply(env)
    repair_proposal = yaml.safe_load(repair_proposal_path.read_text(encoding="utf-8"))
    assert repair_proposal["applied_pattern_version"] == "1.2-draft"

    _write_claim(env["claims_dir"], "claim-c", source_date="2026-11-13")
    env["proposal_path"] = (
        env["repo_root"] / "framework/proposals/20261115-gator-general.yaml"
    )
    _write_proposal(env, [_decision("reinforce", claim_id="claim-c")])
    later_proposal = yaml.safe_load(env["proposal_path"].read_text(encoding="utf-8"))
    later_proposal["proposal_id"] = "20261115-gator-general"
    env["proposal_path"].write_text(
        yaml.safe_dump(later_proposal, allow_unicode=True), encoding="utf-8"
    )
    _apply(env)
    later_doc = yaml.safe_load(env["patterns_path"].read_text(encoding="utf-8"))
    assert later_doc["version"] == "1.3-draft"

    env["proposal_path"] = repair_proposal_path
    before = _file_bytes(env)
    report = _apply(env)

    assert report["applied"] == []
    assert len(report["skipped"]) == 1
    repair_proposal = yaml.safe_load(repair_proposal_path.read_text(encoding="utf-8"))
    assert repair_proposal["applied_pattern_version"] == "1.2-draft"
    assert _file_bytes(env) == before


def test_duplicate_decision_in_one_batch_is_not_double_applied(tmp_path):
    env = _environment(tmp_path)
    decision = _decision("reinforce")
    _write_proposal(env, [decision, dict(decision)])

    _apply(env)

    doc = yaml.safe_load(env["patterns_path"].read_text(encoding="utf-8"))
    assert doc["patterns"][0]["source_claims"] == ["claim-a"]
    assert len(doc["evolution_log"]) == 1
    assert len(doc["evolution_log"][0]["changes"]) == 1
    assert doc["version"] == "1.2-draft"


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
    state = json.loads(env["state_path"].read_text(encoding="utf-8"))
    assert state["review_status"]["claim-a"]["status"] == "applied"
    proposal = yaml.safe_load(env["proposal_path"].read_text(encoding="utf-8"))
    assert proposal["status"] == "applied"

    settled = _file_bytes(env)
    _apply(env)
    assert _file_bytes(env) == settled


def test_cli_help_list_pending_and_dry_run(tmp_path):
    import subprocess
    import sys

    env = _environment(tmp_path)
    script = Path(__file__).resolve().parents[1] / "scripts/apply_gator_pattern_evolution.py"
    common = [
        "--patterns",
        str(env["patterns_path"]),
        "--state",
        str(env["state_path"]),
        "--claims-dir",
        str(env["claims_dir"]),
        "--repo-root",
        str(env["repo_root"]),
    ]

    help_result = subprocess.run(
        [sys.executable, str(script), "--help"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert help_result.returncode == 0, help_result.stderr
    for option in ("--list-pending", "--patterns", "--state", "--claims-dir", "--repo-root", "--dry-run"):
        assert option in help_result.stdout

    listed = subprocess.run(
        [sys.executable, str(script), "--list-pending", *common],
        check=False,
        capture_output=True,
        text=True,
    )
    assert listed.returncode == 0, listed.stderr
    assert json.loads(listed.stdout)["counts"]["pending_review"] == 2

    _write_proposal(env, [_decision("reinforce")])
    before = _file_bytes(env)
    preview = subprocess.run(
        [sys.executable, str(script), str(env["proposal_path"]), "--dry-run", *common],
        check=False,
        capture_output=True,
        text=True,
    )
    assert preview.returncode == 0, preview.stderr
    assert "[dry-run] 未落盘" in preview.stdout
    assert "source_claims" in preview.stdout
    assert _file_bytes(env) == before
