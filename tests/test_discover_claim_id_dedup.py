"""Tests for discover_claim_relations `--claim-id` 跨文件重复 id 防护。

背景（2026-09-03 实测撞坏）：原 main() `--claim-id` 分支用 sorted(glob) 字典序匹配
第一个文件就 break，导致同一 claim-id 跨多个 YAML 文件存在时（如
claim-20260903-002-a 同时在 001.yaml 和 002.yaml），实际处理的是 001.yaml 里那条，
002.yaml 那条永远轮不到。同时 `write_results_to_yaml(force=True)` 会把已 commit
的真 supersedes/contradicts 覆盖掉——本次靠 git checkout 救回。

修复后行为：
- 1 个匹配 → 走老路径（处理唯一那个文件）
- >1 个匹配 → raise SystemExit 拒绝并列出全部文件路径
- 0 个匹配 → 打警告（与原行为兼容）

回归守护：本文件
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

import pytest


def _write_yaml(path: Path, claim_id: str, subject: str) -> None:
    """写一份最小合法 claim yaml。"""
    path.write_text(
        "claims:\n"
        f"- id: {claim_id}\n"
        f"  subject: {subject}\n"
        "  statement: test\n"
        "  source_date: '2026-09-03'\n",
        encoding="utf-8",
    )


@pytest.fixture
def fake_claims_dir(monkeypatch, tmp_path):
    """把 PROJECT_ROOT 重定向到临时目录，里面塞 2 个有重复 id 的 yaml。"""
    fake_root = tmp_path / "repo"
    claims_dir = fake_root / "knowledge" / "claims"
    claims_dir.mkdir(parents=True)

    _write_yaml(claims_dir / "claim-001.yaml", "claim-test-dup-a", "001 早盘那条")
    _write_yaml(claims_dir / "claim-002.yaml", "claim-test-dup-a", "002 盘中那条")
    _write_yaml(claims_dir / "claim-003.yaml", "claim-test-unique-a", "唯一一条")

    # patch PROJECT_ROOT（main 函数里直接 import 的引用）
    from qing_investment.agent.tools import discover_claim_relations as d
    monkeypatch.setattr(d, "PROJECT_ROOT", fake_root)
    return claims_dir


def _invoke_main_with_args(monkeypatch, args: list[str], fake_claims_dir: Path):
    """调 main()，拦截 process_claim/write_results_to_yaml 让它空跑。"""
    from qing_investment.agent.tools import discover_claim_relations as d
    monkeypatch.setattr(
        "sys.argv",
        ["discover_claim_relations.py"] + args,
    )

    # 空 stub：避免 LLM/Qdrant/Neo4j 真实调用
    monkeypatch.setattr(d, "QdrantClientWrapper", lambda *a, **kw: None)
    monkeypatch.setattr(d, "Neo4jClient", lambda *a, **kw: type("_N", (), {"close": staticmethod(lambda: None), "get_claim_evolution": staticmethod(lambda cid: None), "driver": None})())
    monkeypatch.setattr(d, "get_embedding_model", lambda *a, **kw: None)
    monkeypatch.setattr(d, "get_llm_client_with_fallback", lambda *a, **kw: None)
    monkeypatch.setattr(d, "process_claim", lambda *a, **kw: {"claim_id": "x", "supersedes": [], "contradicts": [], "supplements": [], "pairs": []})
    monkeypatch.setattr(d, "write_results_to_yaml", lambda *a, **kw: None)
    d.main()


def test_claim_id_unique_match_runs_normally(monkeypatch, fake_claims_dir, capsys):
    """恰好 1 个匹配 → 正常处理（to_process 加 1 项，不抛 SystemExit）。"""
    _invoke_main_with_args(monkeypatch, ["--claim-id", "claim-test-unique-a"], fake_claims_dir)
    # 没有 "❌ claim-id" 错误信息说明走了正常路径
    captured = capsys.readouterr()
    assert "❌ claim-id" not in captured.out
    # 至少打印了 "Processing 1 claims..."
    assert "Processing 1 claims" in captured.out


def test_claim_id_duplicate_match_raises_systemexit(monkeypatch, fake_claims_dir):
    """>1 个匹配 → raise SystemExit，且 exit message 含全部匹配文件路径 + --file 消歧提示。"""
    with pytest.raises(SystemExit) as exc_info:
        _invoke_main_with_args(monkeypatch, ["--claim-id", "claim-test-dup-a"], fake_claims_dir)

    msg = str(exc_info.value)
    # 必须包含两个匹配文件
    assert "claim-001.yaml" in msg
    assert "claim-002.yaml" in msg
    # 必须提示用户用 --file 消歧
    assert "--file" in msg
    # 不能静默走老路径（不打印 Processing）
    # （此处已经通过 raise SystemExit 验证）


def test_claim_id_no_match_warns_only(monkeypatch, fake_claims_dir, capsys):
    """0 个匹配 → 打印警告但不抛 SystemExit（与原行为兼容：空 to_process 自然走完）。"""
    _invoke_main_with_args(monkeypatch, ["--claim-id", "claim-not-exist-a"], fake_claims_dir)
    captured = capsys.readouterr()
    # 不该走多文件拒绝分支
    assert "❌ claim-id" not in captured.out
    # 不该打印 0 个 claim 的 Processing（因为 to_process 空会走 else 分支）
    # 实际 main() 在 to_process 为空时直接 return——这里不强求输出