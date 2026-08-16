"""claim_buckets 双格式解析与五桶映射测试。"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from investment_engine.claim_buckets import (
    bucket_of, load_claims, parse_md_claims, parse_yaml_claims,
)

YAML_DOC = """\
claims:
- id: claim-20260701-001-a
  source_path: sources/raw/财经/2026-07-01-动态-盘中4108.md
  source_date: '2026-07-01'
  source_type: 动态
  claim_type: market-cycle
  subject: 上证4108满仓线
  timeframe: short-term
  statement: 收到4108理论上可以满仓。
  confidence: high
  status: active
- id: claim-20260701-001-b
  source_path: sources/research/gs-report.md
  source_date: '2026-07-01'
  source_type: 研报
  claim_type: sector-theme
  subject: 半导体设备
  timeframe: trend
  statement: 设备零部件景气延续。
  confidence: medium
  status: active
"""

MD_DOC = """\
# 历史全量 Claims

## claim: qing-2025-12-12-methodology-expectation-001

- id: `qing-2025-12-12-methodology-expectation-001`
- source_path: `sources/raw/财经/视频：25-12-12：预期管理.md`
- source_date: `2025-12-12`
- source_type: `视频`
- claim_type: `methodology`
- subject: `预期管理`
- timeframe: `permanent`
- statement: `交易系统的第一步是让收益预期回归理性。`
- confidence: `high`
- status: `active`
- links:
  - wiki_pages: `["knowledge/wiki/x.md"]`

## claim: qing-2026-05-16-research-pcb-001

- id: `qing-2026-05-16-research-pcb-001`
- source_path: `sources/raw/财经/研报：AI PCB.md`
- source_type: `研报`
- claim_type: `sector-theme`
- status: `superseded`

## 其他章节（非 claim 块，应忽略）

- id: `not-a-claim`
"""


def test_parse_yaml_claims(tmp_path):
    f = tmp_path / "claim-20260701-001.yaml"
    f.write_text(YAML_DOC, encoding="utf-8")
    claims = parse_yaml_claims(f)
    assert len(claims) == 2
    assert claims[0]["id"] == "claim-20260701-001-a"
    assert claims[0]["source_type"] == "动态"
    assert claims[1]["claim_type"] == "sector-theme"


def test_parse_md_claims(tmp_path):
    f = tmp_path / "2025-12-历史-claims.md"
    f.write_text(MD_DOC, encoding="utf-8")
    claims = parse_md_claims(f)
    assert [c["id"] for c in claims] == [
        "qing-2025-12-12-methodology-expectation-001",
        "qing-2026-05-16-research-pcb-001",
    ]
    assert claims[0]["source_type"] == "视频"
    assert claims[0]["status"] == "active"
    assert claims[1]["status"] == "superseded"


@pytest.mark.parametrize("st,sp,want", [
    ("研报", "sources/raw/财经/研报：AI PCB.md", "research"),
    ("机构研报（UP动态转发）", "sources/raw/财经/x.md", "research"),
    ("institution-report", "sources/raw/财经/x.md", "research"),
    ("动态", "sources/research/gs.md", "research"),  # path 优先判定 research
    ("公告", "sources/raw/财经/x.md", "announcement"),
    ("agent", "evals/shadow/predictions/x.json", "agent"),
    ("data", "infra/data/x.json", "data"),
    ("动态", "sources/raw/财经/x.md", "up"),
    ("bilibili_dynamic", "sources/original/bilibili/2026-07-08-x.md", "up"),
    ("视频", "sources/raw/财经/x.md", "up"),
    ("早盘", "sources/incoming/x.md", "up"),
    ("专栏", "/home/ubuntu/learning-investment-strategies/sources/raw/财经/x.md", "up"),
    ("专栏", "sources/chanlun/lesson_033.md", "up"),  # 缠论教材并入 up 桶
    ("未知类型", "somewhere/else.md", "other"),
    (None, None, "other"),
])
def test_bucket_of(st, sp, want):
    assert bucket_of(st, sp) == want


def test_parse_single_claim_yaml(tmp_path):
    """单 claim 字典结构（无顶层 claims 列表）也要能解析。"""
    f = tmp_path / "claim-20260105-001-a.yaml"
    f.write_text(
        "id: claim-20260105-001-a\n"
        "source_path: sources/raw/财经/x.md\n"
        "source_type: 早盘\n"
        "claim_type: market-cycle\n"
        "status: active\n",
        encoding="utf-8")
    claims = parse_yaml_claims(f)
    assert len(claims) == 1
    assert claims[0]["id"] == "claim-20260105-001-a"
    assert claims[0]["source_type"] == "早盘"


def test_load_claims_attaches_bucket(tmp_path):
    (tmp_path / "claim-a.yaml").write_text(YAML_DOC, encoding="utf-8")
    (tmp_path / "hist.md").write_text(MD_DOC, encoding="utf-8")
    claims, skipped = load_claims(tmp_path)
    assert skipped == 0
    assert len(claims) == 4
    by_id = {c["id"]: c["bucket"] for c in claims}
    assert by_id["claim-20260701-001-a"] == "up"
    assert by_id["claim-20260701-001-b"] == "research"
    assert by_id["qing-2025-12-12-methodology-expectation-001"] == "up"
    assert by_id["qing-2026-05-16-research-pcb-001"] == "research"


def test_load_claims_missing_dir(tmp_path):
    claims, skipped = load_claims(tmp_path / "nope")
    assert claims == [] and skipped == 0
