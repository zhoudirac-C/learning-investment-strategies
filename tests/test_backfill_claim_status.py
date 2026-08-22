"""backfill_claim_status 的 status 生命周期回填规则测试。"""

from scripts.backfill_claim_status import plan_status_updates, rewrite_status_in_text


def _claims():
    return {
        "claim-a": {"id": "claim-a", "status": "active", "supersedes": ["claim-old"]},
        "claim-b": {"id": "claim-b", "status": "active", "contradicts": ["claim-con"]},
        "claim-old": {"id": "claim-old", "status": "active", "supersedes": []},
        "claim-con": {"id": "claim-con", "status": "active", "contradicts": []},
        "claim-done": {"id": "claim-done", "status": "superseded", "supersedes": []},
        "claim-c": {"id": "claim-c", "status": "active", "supersedes": ["claim-done", "claim-ghost"]},
    }


def test_supersedes_target_flipped_to_superseded():
    updates, _, _ = plan_status_updates(_claims())
    assert updates == {"claim-old": "superseded"}


def test_contradicts_only_target_not_flipped():
    _, review, _ = plan_status_updates(_claims())
    assert "claim-con" in review
    # 不出现在 updates 里
    updates, _, _ = plan_status_updates(_claims())
    assert "claim-con" not in updates


def test_already_superseded_is_idempotent():
    updates, _, _ = plan_status_updates(_claims())
    assert "claim-done" not in updates


def test_missing_target_reported_not_crash():
    _, _, missing = plan_status_updates(_claims())
    assert "claim-ghost" in missing


def test_rewrite_status_only_changes_target_block():
    text = (
        "claims:\n"
        "- id: claim-old\n"
        "  statement: 旧观点\n"
        "  status: active\n"
        "  supersedes: []\n"
        "- id: claim-new\n"
        "  statement: 新观点\n"
        "  status: active\n"
        "  supersedes: [\"claim-old\"]\n"
    )
    new_text, changed = rewrite_status_in_text(text, {"claim-old"}, "superseded")
    assert changed == {"claim-old"}
    lines = new_text.splitlines()
    assert lines[3] == "  status: superseded"
    # 非目标 claim 的 status 不动
    assert lines[7] == "  status: active"
    # 其余行原样
    assert lines[4] == "  supersedes: []"


def test_rewrite_status_quoted_active():
    text = "- id: claim-x\n  status: 'active'\n"
    new_text, changed = rewrite_status_in_text(text, {"claim-x"}, "superseded")
    assert changed == {"claim-x"}
    assert new_text.splitlines()[1] == "  status: superseded"


def test_rewrite_status_flat_format_no_dash():
    text = "id: claim-flat\nstatement: 旧\nstatus: active\n"
    new_text, changed = rewrite_status_in_text(text, {"claim-flat"}, "superseded")
    assert changed == {"claim-flat"}
    assert new_text.splitlines()[2] == "status: superseded"
