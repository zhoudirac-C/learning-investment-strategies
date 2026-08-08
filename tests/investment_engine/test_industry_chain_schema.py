"""chain.yaml schema 校验器测试。"""
import pytest

from investment_engine.industry_chain.schema import ChainSchemaError, validate_chain


def _valid_chain() -> dict:
    return {
        "chain_id": "changxin-dram",
        "name": "长鑫存储产业链",
        "thesis": "长鑫IPO融资扩产 → 资本开支扩大 → 设备/材料采购增加 → 封测配套需求提升",
        "last_verified": "2026-05-18",
        "segments": [
            {"id": "seg-01", "name": "刻蚀设备", "value_share": None, "barrier": None,
             "landscape": None, "growth": None, "status": "扩产招标中", "last_verified": "2026-05-18"},
            {"id": "seg-02", "name": "CMP材料", "value_share": None, "barrier": None,
             "landscape": None, "growth": None, "status": None, "last_verified": None},
        ],
        "mappings": [
            {"code": "002371", "name": "北方华创", "segment": "seg-01",
             "relation": "刻蚀/PECVD/PVD设备批量导入长鑫产线", "cert_status": None,
             "order_evidence": None, "elasticity": "core",
             "elasticity_reason": "刻蚀+薄膜沉积全平台", "last_verified": "2026-05-18"},
            {"code": "300054", "name": "鼎龙股份", "segment": "seg-02",
             "relation": "CMP抛光垫在长鑫晶圆平坦化制程大规模量产", "cert_status": "已供货",
             "order_evidence": None, "elasticity": "elastic",
             "elasticity_reason": None, "last_verified": "2026-05-18"},
        ],
    }


class TestValidateChain:
    def test_valid_chain_passes(self):
        assert validate_chain(_valid_chain()) == _valid_chain()

    def test_missing_required_field_rejected(self):
        chain = _valid_chain()
        del chain["thesis"]
        with pytest.raises(ChainSchemaError, match="thesis"):
            validate_chain(chain)

    def test_bad_chain_id_rejected(self):
        chain = _valid_chain()
        chain["chain_id"] = "长鑫存储"  # 非 ASCII slug
        with pytest.raises(ChainSchemaError, match="chain_id"):
            validate_chain(chain)

    def test_mapping_segment_must_exist(self):
        chain = _valid_chain()
        chain["mappings"][0]["segment"] = "seg-99"
        with pytest.raises(ChainSchemaError, match="seg-99"):
            validate_chain(chain)

    def test_bad_elasticity_rejected(self):
        chain = _valid_chain()
        chain["mappings"][0]["elasticity"] = "⭐⭐⭐⭐"
        with pytest.raises(ChainSchemaError, match="elasticity"):
            validate_chain(chain)

    def test_bad_code_rejected(self):
        chain = _valid_chain()
        chain["mappings"][0]["code"] = "002371.SZ"  # 必须是 6 位数字
        with pytest.raises(ChainSchemaError, match="code"):
            validate_chain(chain)

    def test_bad_date_rejected(self):
        chain = _valid_chain()
        chain["last_verified"] = "20260518"
        with pytest.raises(ChainSchemaError, match="last_verified"):
            validate_chain(chain)

    def test_duplicate_segment_id_rejected(self):
        chain = _valid_chain()
        chain["segments"].append(dict(chain["segments"][0]))
        with pytest.raises(ChainSchemaError, match="重复"):
            validate_chain(chain)

    def test_none_dates_allowed(self):
        """待补字段允许 None（诚实留空），不得报错。"""
        chain = _valid_chain()
        chain["segments"][0]["value_share"] = None
        chain["mappings"][0]["order_evidence"] = None
        assert validate_chain(chain) == chain
