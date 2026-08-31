"""信息归一化与产业链匹配测试（T11 前置 + T11）。"""
from investment_engine.chain_tracker.items import (
    make_futures_item, normalize_notice, normalize_report,
)
from investment_engine.chain_tracker.matching import build_chain_index, match_items


def _chain() -> dict:
    return {
        "chain_id": "ai-pcb-ccl",
        "name": "AI PCB/CCL 产业链",
        "driver": "NVIDIA Rubin代际升级（M7→M8→M9）",
        "segments": [
            {"id": "seg-upstream", "name": "上游材料",
             "materials": ["铜箔(HVLP4)", "玻璃布(Q-Glass)", "树脂"]},
            {"id": "seg-midstream", "name": "中游CCL", "materials": ["覆铜板(CCL)"]},
        ],
        "mappings": [
            {"code": "002409", "name": "雅克科技", "segment": "seg-upstream"},
            {"code": "600183", "name": "生益科技", "segment": "seg-midstream"},
        ],
        "tracking_metrics": [
            {"metric": "FR8价格"},
            {"metric": "M8/M9认证进度"},
            {"metric": "玻璃布Q-Glass供给"},
            {"metric": "WF6 6N价格"},
            {"metric": "高端产能利用率"},
        ],
    }


def _report(**kw) -> dict:
    base = {"info_code": "AP1", "title": "无标题", "publish_date": "2026-08-31",
            "org": "测试证券", "stock_code": "", "stock_name": "",
            "industry_name": "电子", "pdf_url": "http://x"}
    base.update(kw)
    return base


class TestNormalize:
    def test_report_uses_info_code(self):
        item = normalize_report(_report(info_code="AP202608311234567890"))
        assert item["info_id"] == "AP202608311234567890"
        assert item["source"] == "report"
        assert item["published_at"] == "2026-08-31"

    def test_notice_id_from_url(self):
        item = normalize_notice({
            "code": "002409", "name": "雅克科技", "title": "对外投资公告",
            "type": "重大事项", "date": "2026-08-31",
            "url": "https://data.eastmoney.com/notices/detail/002409/AN202608311234567890.html",
        })
        assert item["info_id"] == "AN202608311234567890"
        assert item["stock_code"] == "002409"

    def test_notice_id_fallback_hash_when_url_lacks_an(self):
        item = normalize_notice({"code": "002409", "name": "雅克科技",
                                 "title": "某公告", "type": "其他",
                                 "date": "2026-08-31", "url": ""})
        assert item["info_id"].startswith("notice:")
        # 同输入幂等
        item2 = normalize_notice({"code": "002409", "name": "雅克科技",
                                  "title": "某公告", "type": "其他",
                                  "date": "2026-08-31", "url": ""})
        assert item["info_id"] == item2["info_id"]

    def test_futures_item(self):
        item = make_futures_item(symbol="CU0", name="铜", change_pct=3.2,
                                 last=112000.0, prev_settle=108620.0,
                                 date="2026-08-31", window="10:30",
                                 chain_ids=["copper-aluminum"])
        assert item["info_id"] == "futures:CU0:2026-08-31:10:30"
        assert item["source"] == "futures"
        assert item["chain_ids"] == ["copper-aluminum"]
        assert "铜" in item["title"]


class TestMatching:
    def setup_method(self):
        self.chains = [_chain()]
        self.index = build_chain_index(self.chains)

    def _matched_chains(self, item: dict) -> set[str]:
        return {cid for _, cid in match_items([item], self.index)}

    def test_stock_code_match(self):
        item = normalize_report(_report(stock_code="600183", stock_name="生益科技"))
        assert self._matched_chains(item) == {"ai-pcb-ccl"}

    def test_stock_name_in_title(self):
        item = normalize_report(_report(title="生益科技：订单排至2027"))
        assert "ai-pcb-ccl" in self._matched_chains(item)

    def test_latin_keyword_match(self):
        item = normalize_report(_report(title="FR8 价格再度上调，覆铜板景气延续"))
        assert "ai-pcb-ccl" in self._matched_chains(item)

    def test_material_noun_match(self):
        item = normalize_report(_report(title="铜箔加工费上调，高端 HVLP4 供不应求"))
        assert "ai-pcb-ccl" in self._matched_chains(item)

    def test_chinese_fragment_from_metric(self):
        item = normalize_report(_report(title="玻璃布供给紧张，Q-Glass 缺口扩大"))
        assert "ai-pcb-ccl" in self._matched_chains(item)

    def test_generic_stopword_does_not_match(self):
        # “WF6 6N价格” 的中文碎片“价格”是停用词，不能单独命中
        item = normalize_report(_report(title="白酒价格体系梳理"))
        assert self._matched_chains(item) == set()

    def test_unrelated_not_matched(self):
        item = normalize_report(_report(title="某医药公司股东大会决议公告"))
        assert self._matched_chains(item) == set()

    def test_generic_fragments_and_latin_stop_not_matched(self):
        # 泛化行业名词与 "AI" 不作关键词（实测 flooding 来源）
        chains = [
            {"chain_id": "robotics", "name": "机器人产业链", "driver": "Optimus + 物理AI",
             "segments": [{"id": "s1", "name": "下游应用",
                           "materials": ["工业", "服务应用"]}],
             "mappings": [], "tracking_metrics": [{"metric": "Optimus量产"}]},
        ]
        index = build_chain_index(chains)
        item = normalize_report(_report(title="2026年7月工业企业利润解读"))
        assert match_items([item], index) == []
        item2 = normalize_report(_report(title="端边侧AI SoC加速放量"))
        assert match_items([item2], index) == []

    def test_notice_keyword_only_title_not_matched(self):
        # 公告只做代码/名称匹配：标题里的关键词不构成命中
        item = normalize_notice({"code": "300999", "name": "无关公司",
                                 "title": "关于铜箔生产线对外投资的公告",
                                 "type": "重大事项", "date": "2026-08-31",
                                 "url": "x/AN20260831222.html"})
        assert self._matched_chains(item) == set()

    def test_notice_code_match(self):
        item = normalize_notice({"code": "002409", "name": "雅克科技",
                                 "title": "关于对外投资的公告", "type": "重大事项",
                                 "date": "2026-08-31", "url": "x/AN20260831111.html"})
        assert "ai-pcb-ccl" in self._matched_chains(item)

    def test_multi_chain_match(self):
        c2 = {"chain_id": "copper-aluminum", "name": "铜铝产业链", "driver": "铜缺口",
              "segments": [{"id": "s1", "name": "中游冶炼", "materials": ["电解铜"]}],
              "mappings": [{"code": "601899", "name": "紫金矿业", "segment": "s1"}],
              "tracking_metrics": [{"metric": "铜价"}]}
        index = build_chain_index([_chain(), c2])
        item = normalize_report(_report(title="铜价新高带动铜箔加工费上行"))
        matched = {cid for _, cid in match_items([item], index)}
        assert matched == {"ai-pcb-ccl", "copper-aluminum"}

    def test_futures_item_preassigned_chain(self):
        c2 = {"chain_id": "copper-aluminum", "name": "铜铝产业链", "driver": "铜缺口",
              "segments": [{"id": "s1", "name": "中游冶炼", "materials": ["电解铜"]}],
              "mappings": [{"code": "601899", "name": "紫金矿业", "segment": "s1"}],
              "tracking_metrics": [{"metric": "铜价"}]}
        index = build_chain_index([_chain(), c2])
        item = make_futures_item(symbol="CU0", name="铜", change_pct=3.0,
                                 last=1.0, prev_settle=1.0,
                                 date="2026-08-31", window="10:30",
                                 chain_ids=["copper-aluminum"])
        matched = {cid for _, cid in match_items([item], index)}
        assert matched == {"copper-aluminum"}

    def test_no_duplicate_pair_for_same_item_chain(self):
        item = normalize_report(_report(title="生益科技 FR8 覆铜板 铜箔"))
        pairs = match_items([item], self.index)
        keys = [(p[0]["info_id"], p[1]) for p in pairs]
        assert len(keys) == len(set(keys))
