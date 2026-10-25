"""legacy 聚合 md claims → YAML 迁移器测试。

背景：knowledge/claims/ 下 3 个 2025-12~2026-05 的聚合 .md 文件共 36 条
claim（qing- 前缀，青枫浦上最早一层），从未进 discover/Neo4j/Qdrant 管线。
本转换器把它们转为标准 claim YAML（补 up_id/up_name/school），供
--all-missing discover 与下游同步消费。
"""
import textwrap

import pytest
import yaml

from scripts.migrate_md_claims_to_yaml import parse_md_blocks, md_to_claims

SAMPLE_MD = textwrap.dedent("""\
    # 历史全量 Claims

    ## claim: qing-2026-05-14-market-cycle-strong-divergence-001

    - id: `qing-2026-05-14-market-cycle-strong-divergence-001`
    - source_path: `sources/raw/财经/复盘：26-05-14：急跌调整与新周期酝酿.md`
    - source_date: `2026-05-14`
    - source_type: `复盘`
    - extracted_at: `2026-05-16`
    - claim_type: `market-cycle`
    - subject: `高位强分歧`
    - timeframe: `short-term`
    - statement: `5 月 14 日下跌被定义为急跌式调整。`
    - evidence_quote: `从性质看，本次下跌更偏向急跌式调整`
    - interpretation: `该 claim 将行情定位为筹码挤压。`
    - confidence: `high`
    - status: `active`
    - supersedes: `[]`
    - contradicts: `[]`
    - links:
      - wiki_pages: `["knowledge/wiki/每日复盘/2026-05-14.md"]`
      - methodology_pages: `["methodology/market-cycle.md"]`
      - cases: `[]`

    ## claim: qing-2026-05-15-operation-no-chase-confirm-001

    - id: `qing-2026-05-15-operation-no-chase-confirm-001`
    - source_path: `sources/raw/财经/视频：26-05-15：分析.md`
    - source_date: `2026-05-15`
    - source_type: `视频笔记`
    - extracted_at: `2026-05-16`
    - claim_type: `operation`
    - subject: `不追高`
    - timeframe: `short-term`
    - statement: `放量冲高不追，等回踩确认。`
    - evidence_quote: `不追单日冲高`
    - confidence: `medium`
    - status: `active`
    - supersedes: `[]`
    - contradicts: `[]`
    - links:
      - wiki_pages: `[]`
""")


def test_parse_md_blocks_finds_two_claims():
    blocks = parse_md_blocks(SAMPLE_MD)
    assert [b["id"] for b in blocks] == [
        "qing-2026-05-14-market-cycle-strong-divergence-001",
        "qing-2026-05-15-operation-no-chase-confirm-001",
    ]
    b0 = blocks[0]
    assert b0["claim_type"] == "market-cycle"
    assert b0["confidence"] == "high"
    assert b0["links"]["wiki_pages"] == ["knowledge/wiki/每日复盘/2026-05-14.md"]
    assert b0["links"]["cases"] == []


def test_md_to_claims_adds_up_identity_and_drops_empty_relations():
    claims = md_to_claims(SAMPLE_MD)
    assert len(claims) == 2
    c0 = claims[0]
    assert c0["up_id"] == "1420210197"
    assert c0["up_name"] == "青枫浦上Q"
    assert c0["school"] == "qing"
    # 空 supersedes/contradicts 不写入，交由 discover 回填
    assert "supersedes" not in c0 and "contradicts" not in c0
    assert "last_discovered" not in c0
    # YAML 可往返解析（转换产物必须过 parse_yaml_claims 通道）
    dumped = yaml.safe_dump({"claims": claims}, allow_unicode=True,
                            sort_keys=False, width=4096)
    loaded = yaml.safe_load(dumped)["claims"]
    assert loaded[1]["statement"] == "放量冲高不追，等回踩确认。"


def test_md_to_claims_skips_block_without_id():
    md = SAMPLE_MD + "\n## 附录说明\n\n- foo: `bar`\n"
    assert len(md_to_claims(md)) == 2


def test_roundtrip_through_parse_yaml_claims(tmp_path):
    from investment_engine.claim_buckets import parse_yaml_claims
    claims = md_to_claims(SAMPLE_MD)
    out = tmp_path / "legacy.yaml"
    out.write_text(yaml.safe_dump({"claims": claims}, allow_unicode=True,
                                  sort_keys=False, width=4096),
                   encoding="utf-8")
    parsed = parse_yaml_claims(out)
    assert len(parsed) == 2
    assert parsed[0]["id"].startswith("qing-2026-05-14")
