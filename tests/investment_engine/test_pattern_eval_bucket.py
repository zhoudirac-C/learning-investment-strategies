"""bucket：宽松三桶规则与主指标映射。"""

import pytest

from investment_engine.pattern_eval.bucket import (
    PRIMARY_METRIC, bucket_one, bucketize,
)


def test_primary_metric_covers_six_used_patterns():
    assert set(PRIMARY_METRIC) == {
        "sentiment_cycle", "mainline_identification", "sector_rotation",
        "upstream_cycle", "technical_timing", "ai_industry_chain",
    }


@pytest.mark.parametrize("kind,rate,n,expected", [
    ("stage", 0.70, 20, "达标"),      # 毕业线边界
    ("stage", 0.699, 20, "待观察"),
    ("stage", 0.70, 19, "待观察"),    # n 边界
    ("direction", 0.60, 20, "达标"),
    ("stock", 0.55, 20, "达标"),
    ("stock", 0.549, 20, "待观察"),
    ("stage", 0.499, 20, "证伪"),     # 50% 随机线以下
    ("direction", 0.50, 20, "待观察"),  # 恰好 50% 不证伪
    ("stage", None, 30, "待观察"),    # 无指标
])
def test_bucket_one_boundaries(kind, rate, n, expected):
    assert bucket_one(kind, rate, n) == expected


def test_bucketize_unused_and_unknown():
    metrics = {
        "sector_rotation": {
            "days_used": 25,
            "stage": {"rate": 0.6, "n": 25},
            "direction": {"rate": 0.62, "n": 50},
            "stock": {"rate": 0.5, "n": 50},
            "regime": {},
        },
        "brand_new_pattern": {   # 不在 PRIMARY_METRIC 的新模式
            "days_used": 3,
            "stage": {"rate": 1.0, "n": 3},
            "direction": {"rate": 1.0, "n": 6},
            "stock": {"rate": 1.0, "n": 6},
            "regime": {},
        },
    }
    out = bucketize(metrics, ["sector_rotation", "macro_transmission", "brand_new_pattern"])
    assert out["sector_rotation"] == {"bucket": "达标", "primary_metric": "direction"}
    assert out["macro_transmission"] == {"bucket": "unused", "note": "m1 未使用"}
    assert out["brand_new_pattern"]["bucket"] == "待观察"
    assert "无主指标映射" in out["brand_new_pattern"]["note"]
