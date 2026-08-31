"""期货行情异动检测测试（T15）。"""
import json
import tempfile
from pathlib import Path

from investment_engine.chain_tracker.futures import (
    FUTURES_CHAIN_MAP, detect_anomalies, parse_sina_nf,
)

# 实测新浪 hq.sinajs.cn nf_ 响应格式（2026-08-29 真实采样改造）
SINA_SAMPLE = (
    'var hq_str_nf_CU0="铜连续,010000,109200.000,109300.000,108150.000,0.000,'
    '108560.000,108580.000,108570.000,0.000,108620.000,9,2,214972.000,57753,'
    '沪,铜,2026-08-29,1,,,,,,,,,108840.763,0.000,0,0.000,0";\n'
    'var hq_str_nf_J0="焦炭连续,230000,2160.500,2208.500,2153.000,0.000,'
    '2203.000,2205.000,2204.000,0.000,2149.500,2,7,66191.000,35313,'
    '连,焦炭,2026-08-28,1,,,,,,,,,2185.747,0.000,0,0.000,0";\n'
)


class TestParseSinaNf:
    def test_parse_fields(self):
        quotes = parse_sina_nf(SINA_SAMPLE)
        assert set(quotes) == {"CU0", "J0"}
        cu = quotes["CU0"]
        assert cu["name"] == "铜连续"
        assert cu["last"] == 108570.0
        assert cu["prev_settle"] == 108620.0
        assert cu["date"] == "2026-08-29"
        assert cu["change_pct"] == round((108570.0 - 108620.0) / 108620.0 * 100, 3)

    def test_skips_zero_prev_settle(self):
        raw = 'var hq_str_nf_XX0="测试,0,1.0,1.0,1.0,0,1.0,1.0,1.0,0,0.000,0,0,0,0,沪,测,2026-08-29,1";'
        quotes = parse_sina_nf(raw)
        assert quotes == {}

    def test_change_pct_positive(self):
        j = parse_sina_nf(SINA_SAMPLE)["J0"]
        assert j["change_pct"] == round((2204.0 - 2149.5) / 2149.5 * 100, 3)
        assert j["change_pct"] > 2.5  # 够触发默认阈值


class TestDetectAnomalies:
    def setup_method(self):
        self.dir = Path(tempfile.mkdtemp(prefix="chain_futures_test_"))
        self.state_path = self.dir / "futures_state.json"

    def _detect(self, quotes, **kw):
        kw.setdefault("state_path", self.state_path)
        kw.setdefault("date", "2026-08-31")
        kw.setdefault("window", "10:30")
        return detect_anomalies(quotes, **kw)

    def test_triggers_above_threshold_and_maps_chain(self):
        quotes = parse_sina_nf(SINA_SAMPLE)  # J0 +2.53%
        items = self._detect(quotes, threshold_pct=2.0)
        assert len(items) == 1
        assert items[0]["source"] == "futures"
        assert items[0]["chain_ids"] == FUTURES_CHAIN_MAP["J0"][1]
        assert "焦炭" in items[0]["title"]
        assert items[0]["info_id"] == "futures:J0:2026-08-31:10:30"

    def test_below_threshold_silent(self):
        items = self._detect({"CU0": {"name": "铜连续", "last": 108570.0,
                                      "prev_settle": 108620.0}},
                             threshold_pct=2.0)
        assert items == []

    def test_same_day_realert_requires_bigger_move(self):
        big = {"J0": {"name": "焦炭连续", "last": 2204.0, "prev_settle": 2149.5}}
        items1 = self._detect(big, threshold_pct=2.0, window="10:00")
        assert len(items1) == 1
        # 同幅度不重复告警
        items2 = self._detect(big, threshold_pct=2.0, window="10:30")
        assert items2 == []
        # 幅度扩大 ≥1pp 才再告警
        bigger = {"J0": {"name": "焦炭连续", "last": 2250.0, "prev_settle": 2149.5}}
        items3 = self._detect(bigger, threshold_pct=2.0, window="11:00")
        assert len(items3) == 1

    def test_new_day_resets(self):
        big = {"J0": {"name": "焦炭连续", "last": 2204.0, "prev_settle": 2149.5}}
        self._detect(big, threshold_pct=2.0, date="2026-08-30")
        items = self._detect(big, threshold_pct=2.0, date="2026-08-31")
        assert len(items) == 1

    def test_state_persisted(self):
        big = {"J0": {"name": "焦炭连续", "last": 2204.0, "prev_settle": 2149.5}}
        self._detect(big, threshold_pct=2.0)
        state = json.loads(self.state_path.read_text(encoding="utf-8"))
        assert "J0" in state
