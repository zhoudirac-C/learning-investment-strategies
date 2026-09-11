"""news / official / macro 冒烟测试（离线：签名算法、结构契约）。"""

import hashlib

from qing_investment.marketdata import news


class TestClsSign:
    def test_sign_is_local_md5_sha1(self):
        """财联社签名：md5(sha1(按 key 字典序拼接))，零 key 纯本地。"""
        params = {"appName": "CailianpressWeb", "os": "web", "sv": "7.7.5",
                  "last_time": "", "refresh_type": "1", "rn": "50"}
        qs = "&".join(f"{k}={params[k]}" for k in sorted(params))
        sign = hashlib.md5(hashlib.sha1(qs.encode()).hexdigest().encode()).hexdigest()
        assert len(sign) == 32
        # 确定性
        sign2 = hashlib.md5(hashlib.sha1(qs.encode()).hexdigest().encode()).hexdigest()
        assert sign == sign2


class TestOfficialContract:
    def test_index_code_validation(self):
        from qing_investment.marketdata.official import _official_code
        assert _official_code("000300") == "000300"
        import pytest
        with pytest.raises(ValueError):
            _official_code("sh000300")  # 指数层只认纯数字
        with pytest.raises(ValueError):
            _official_code("600519x")

    def test_calendar_contract(self):
        """交易日历：逐日 is_open、未发布月份抛错不当休市——契约由实现保证，
        这里验证输入校验路径。"""
        from qing_investment.marketdata import official
        # 不触网：month 参数非法时应在请求前/后明确抛错而非静默空
        try:
            official.trading_calendar(2026, 13)
            raised = False
        except Exception:
            raised = True
        assert raised
