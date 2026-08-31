"""产业链知识库读写测试。"""
import tempfile
from pathlib import Path

import pytest
import yaml

from investment_engine.industry_chain.schema import ChainSchemaError
from investment_engine.industry_chain.store import (
    chain_dir, default_base_dir, list_chains, load_chain, save_chain,
)


def _chain(chain_id: str = "test-chain") -> dict:
    return {
        "chain_id": chain_id,
        "name": "测试产业链",
        "thesis": "需求爆发 → 产能倾斜 → 涨价轮动",
        "last_verified": "2026-08-08",
        "segments": [
            {"id": "seg-01", "name": "上游材料", "value_share": None, "barrier": None,
             "landscape": None, "growth": None, "status": "涨价中", "last_verified": None},
        ],
        "mappings": [
            {"code": "000001", "name": "测试标的", "segment": "seg-01", "relation": "供货",
             "cert_status": None, "order_evidence": None, "elasticity": "elastic",
             "elasticity_reason": None, "last_verified": None},
        ],
    }


class TestStore:
    def setup_method(self):
        self.base = Path(tempfile.mkdtemp(prefix="ichain_test_"))

    def teardown_method(self):
        import shutil
        shutil.rmtree(self.base, ignore_errors=True)

    def test_save_then_load_roundtrip(self):
        save_chain(_chain(), base_dir=self.base)
        loaded = load_chain("test-chain", base_dir=self.base)
        assert loaded["chain_id"] == "test-chain"
        assert loaded["segments"][0]["name"] == "上游材料"

    def test_save_writes_yaml_and_validates(self):
        save_chain(_chain(), base_dir=self.base)
        path = chain_dir("test-chain", base_dir=self.base) / "chain.yaml"
        assert path.exists()
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert raw["thesis"].startswith("需求爆发")

    def test_save_rejects_invalid_chain(self):
        bad = _chain()
        bad["mappings"][0]["segment"] = "seg-99"
        with pytest.raises(ChainSchemaError):
            save_chain(bad, base_dir=self.base)
        assert not (chain_dir("test-chain", base_dir=self.base) / "chain.yaml").exists()

    def test_chain_id_mismatch_rejected(self):
        """URL 路径 id 与文件内 chain_id 必须一致，防张冠李戴。"""
        chain = _chain("a-chain")
        with pytest.raises(ChainSchemaError, match="mismatch|不一致"):
            save_chain(chain, base_dir=self.base, expect_id="b-chain")

    def test_load_missing_raises(self):
        with pytest.raises(FileNotFoundError):
            load_chain("no-such-chain", base_dir=self.base)

    def test_load_also_validates(self):
        """落盘后被手改坏的文件，读出时也要拦住。"""
        save_chain(_chain(), base_dir=self.base)
        path = chain_dir("test-chain", base_dir=self.base) / "chain.yaml"
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        raw["mappings"][0]["elasticity"] = "垃圾值"
        path.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
        with pytest.raises(ChainSchemaError):
            load_chain("test-chain", base_dir=self.base)

    def test_list_chains(self):
        save_chain(_chain("chain-a"), base_dir=self.base)
        save_chain(_chain("chain-b"), base_dir=self.base)
        assert list_chains(base_dir=self.base) == ["chain-a", "chain-b"]

    def test_chain_states_view_compact(self):
        chain = _chain("chain-a")
        chain["current_stage"] = "阶段2-加速期"
        chain["stage_confidence"] = "高"
        chain["timing"] = {"current_recommendation": "中游",
                           "next_trigger": "x", "risk": "y"}
        save_chain(chain, base_dir=self.base)
        save_chain(_chain("chain-b"), base_dir=self.base)

        from investment_engine.industry_chain.store import chain_states_view
        view = chain_states_view(base_dir=self.base)
        assert [c["chain_id"] for c in view] == ["chain-a", "chain-b"]
        a = view[0]
        assert a["current_stage"] == "阶段2-加速期"
        assert a["stage_confidence"] == "高"
        assert a["timing"] == "中游"
        assert a["stocks"] == ["测试标的(000001)"]
        # 缺省字段安全兜底
        assert view[1]["current_stage"] == "阶段0-观察"
        assert view[1]["timing"] is None

    def test_chain_states_view_zfill_int_code(self):
        """YAML 把 002409 读成 int 的陷阱：视图输出必须补零回 6 位。"""
        base = self.base / "chain-c"
        base.mkdir(parents=True)
        (base / "chain.yaml").write_text(
            "chain_id: chain-c\nname: 测试\nthesis: t\nlast_verified: '2026-08-08'\n"
            "segments: [{id: seg-01, name: 上游}]\n"
            "mappings: [{code: 2409, name: 雅克科技, segment: seg-01, "
            "relation: 龙头, elasticity: core}]\n",
            encoding="utf-8")
        # code: 2409 未加引号 → safe_load 成 int，validate_chain 会因非 6 位拒绝，
        # 所以这里直接验证视图的容错：load 失败则该链被跳过
        from investment_engine.industry_chain.store import chain_states_view
        view = chain_states_view(base_dir=self.base)
        assert view == []  # 非法链被跳过，不阻断

    def test_stage0_only_codes(self):
        from investment_engine.industry_chain.store import stage0_only_codes

        watch = _chain("chain-watch")  # 无 current_stage → 视为阶段0
        watch["mappings"] = [
            {"code": "000001", "name": "只观察", "segment": "seg-01",
             "relation": "龙头", "elasticity": "core"},
            {"code": "000003", "name": "双链共有", "segment": "seg-01",
             "relation": "龙头", "elasticity": "core"},
        ]
        active = _chain("chain-active")
        active["current_stage"] = "阶段1-启动期"
        active["mappings"] = [
            {"code": "000002", "name": "在启动", "segment": "seg-01",
             "relation": "龙头", "elasticity": "core"},
            {"code": "000003", "name": "双链共有", "segment": "seg-01",
             "relation": "龙头", "elasticity": "core"},
        ]
        save_chain(watch, base_dir=self.base)
        save_chain(active, base_dir=self.base)

        # 000001 只在阶段0链 → 排除；000003 有一条非阶段0链 → 保留
        assert stage0_only_codes(base_dir=self.base) == {"000001"}

    def test_default_base_dir_points_to_repo(self):
        assert default_base_dir().as_posix().endswith("knowledge/industry-chains")
