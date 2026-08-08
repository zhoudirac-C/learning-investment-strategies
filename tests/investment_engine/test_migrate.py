"""深度研究 md 解析器测试（合成样例仿方向一结构）。"""
from investment_engine.industry_chain.migrate import elasticity_from_stars, parse_research_md

SAMPLE_MD = """# 方向X：测试产业链全景梳理（深度版）

> 背景：测试背景。
>
> **一句话核心逻辑**：需求爆发 → 产能倾斜 → 涨价轮动 → 全链受益。本次梳理按"上游→中游"展开。

---

## 一、赛道一：上游材料（弹性最大）

| 标的 | 代码 | 核心产品 | 与链主关系 | 弹性评估 |
|---------|------|---------|-----------|---------|
| **雅克科技** | 002409 | 前驱体 | 占采购量15%-20% | ⭐⭐⭐⭐⭐ |
| 兴发集团 | 600141 | 电子级硫酸 | 供应商 | ⭐⭐⭐ |

**投资要点**：略。

## 二、赛道二：中游设备

### 2.1 刻蚀设备

| 标的 | 代码 | 核心产品 | 与链主关系 | 认证状态 | 弹性评估 |
|------|------|---------|-----------|---------|---------|
| 北方华创 | 002371 | 刻蚀设备 | 批量导入产线 | 已供货 | ⭐⭐⭐⭐ |
| 麦捷科技 | 300319 | 配套元件 | 导入中 | 测试中 | ⭐⭐ |

## 七、投资视角总结

### 7.1 核心标的 vs 高弹性标的

| 层级 | 标的 |
|------|------|
| 核心 | 雅克科技 |
"""


class TestElasticityFromStars:
    def test_five_star_is_core(self):
        assert elasticity_from_stars("⭐⭐⭐⭐⭐") == "core"

    def test_four_star_is_core(self):
        assert elasticity_from_stars("⭐⭐⭐⭐") == "core"

    def test_three_star_is_elastic(self):
        assert elasticity_from_stars("⭐⭐⭐") == "elastic"

    def test_low_or_empty_is_concept(self):
        assert elasticity_from_stars("⭐⭐") == "concept"
        assert elasticity_from_stars("") == "concept"


class TestParseResearchMd:
    def setup_method(self):
        self.chain = parse_research_md(
            SAMPLE_MD, chain_id="test-chain", name="测试产业链", verified="2026-05-18"
        )

    def test_thesis_extracted(self):
        assert self.chain["thesis"].startswith("需求爆发")

    def test_segments_from_sections(self):
        names = [s["name"] for s in self.chain["segments"]]
        assert "赛道一：上游材料（弹性最大）" in names
        assert "刻蚀设备" in names  # 子章节优先于"赛道二：中游设备"
        assert not any("总结" in n for n in names)  # 尾章跳过

    def test_segment_ids_are_slugs(self):
        ids = [s["id"] for s in self.chain["segments"]]
        assert ids == ["seg-01", "seg-02", "seg-03"]

    def test_mappings_extracted(self):
        mappings = {m["code"]: m for m in self.chain["mappings"]}
        assert set(mappings) == {"002409", "600141", "002371", "300319"}
        yake = mappings["002409"]
        assert yake["name"] == "雅克科技"  # 加粗已剥离
        assert yake["elasticity"] == "core"
        assert "15%-20%" in yake["relation"]

    def test_subsection_ownership(self):
        """子章节表格归属子章节 segment，不是父章节。"""
        mappings = {m["code"]: m for m in self.chain["mappings"]}
        seg_by_id = {s["id"]: s for s in self.chain["segments"]}
        assert seg_by_id[mappings["002371"]["segment"]]["name"] == "刻蚀设备"

    def test_cert_status(self):
        mappings = {m["code"]: m for m in self.chain["mappings"]}
        assert mappings["002371"]["cert_status"] == "已供货"
        assert mappings["300319"]["cert_status"] == "测试中"
        assert mappings["002409"]["cert_status"] is None  # 无认证列

    def test_summary_tables_skipped(self):
        """投资视角总结章的表格（无代码列）不得产生 mappings。"""
        codes = [m["code"] for m in self.chain["mappings"]]
        assert len(codes) == 4  # 总结表里的"雅克科技"不会重复进来

    def test_output_passes_schema(self):
        from investment_engine.industry_chain.schema import validate_chain

        assert validate_chain(self.chain) is self.chain
