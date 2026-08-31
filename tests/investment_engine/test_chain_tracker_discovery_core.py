"""发现引擎编排与 CLI 流程测试（T16）。全部离线注入，不触网不调真 LLM。"""
import json
import tempfile
from datetime import datetime
from pathlib import Path

import pytest

from investment_engine.chain_tracker.dedup import ProcessedItemsDB
from investment_engine.chain_tracker.discovery_core import run_discovery
from investment_engine.chain_tracker.proposals import load_pending
from investment_engine.industry_chain.store import save_chain

NOW = datetime(2026, 8, 31, 10, 30, 0)
DATE = "2026-08-31"


def _chain(chain_id: str, code: str, name: str, metric: str) -> dict:
    return {
        "chain_id": chain_id,
        "name": f"{name}产业链",
        "thesis": "需求爆发 → 涨价",
        "last_verified": "2026-08-30",
        "segments": [{"id": "seg-mid", "name": "中游", "materials": [metric]}],
        "mappings": [{"code": code, "name": name, "segment": "seg-mid",
                      "relation": "龙头", "elasticity": "core"}],
        "current_stage": "阶段2-加速期",
        "stage_confidence": "高",
        "timing": {"current_recommendation": "中游", "next_trigger": "x",
                   "risk": "y"},
        "tracking_metrics": [{"metric": metric, "current": "上涨",
                              "signal_direction": "上涨=确认"}],
        "falsification": ["价格连续2周回落"],
    }


def _reports() -> list[dict]:
    return [
        # 候选：含触发词且不匹配已有链
        {"info_code": "AP101", "title": "固态电池产业链深度：硫化物电解质量产前夜",
         "publish_date": DATE, "org": "测试证券", "stock_code": "",
         "stock_name": "", "industry_name": "电新", "pdf_url": ""},
        {"info_code": "AP104", "title": "钠电池扩产专题：层状氧化物突围",
         "publish_date": DATE, "org": "测试证券", "stock_code": "",
         "stock_name": "", "industry_name": "电新", "pdf_url": ""},
        # 含触发词但匹配已有链（生益科技/FR8）→ 排除
        {"info_code": "AP102", "title": "生益科技：FR8涨价函点评",
         "publish_date": DATE, "org": "测试证券", "stock_code": "600183",
         "stock_name": "生益科技", "industry_name": "电子", "pdf_url": ""},
        # 无触发词 → 直接滤掉
        {"info_code": "AP103", "title": "某白酒公司点评",
         "publish_date": DATE, "org": "测试证券", "stock_code": "600519",
         "stock_name": "贵州茅台", "industry_name": "食品饮料", "pdf_url": ""},
    ]


def _notices() -> list[dict]:
    return [{"code": "300999", "name": "无关公司", "title": "股东大会决议公告",
             "type": "股东大会", "date": DATE,
             "url": "http://x/AN202608310001.html"}]


def _found(**over):
    base = {
        "proposals": [{
            "chain_id": "solid-state-battery", "name": "固态电池产业链",
            "driver": "硫化物电解质量产", "thesis": "技术突破→量产→重构",
            "chain": {"upstream": {"materials": ["硫化锂"], "stocks": []},
                      "midstream": {"materials": [], "stocks": []},
                      "downstream": {"materials": [], "stocks": []}},
            "current_stage": "阶段1-启动期", "timing": "上游材料",
            "confidence": "中", "source": "测试证券",
            "source_info_ids": ["AP101", "AP104"],
        }],
    }
    base.update(over)
    return json.dumps(base, ensure_ascii=False)


_NONE_FOUND = json.dumps({"proposals": []}, ensure_ascii=False)


def _found_carbon():
    return json.dumps({"proposals": [{
        "chain_id": "carbon-fiber", "name": "碳纤维产业链",
        "driver": "风电需求扩张", "thesis": "原丝→碳化→复材",
        "chain": {"upstream": {"materials": ["原丝"],
                               "stocks": ["吉林化纤", "光威复材"]},
                  "midstream": {"materials": [], "stocks": []},
                  "downstream": {"materials": [], "stocks": []}},
        "current_stage": "阶段2-加速期", "timing": "中游",
        "confidence": "中", "source": "测试证券",
        "source_info_ids": ["AP101"],
    }]}, ensure_ascii=False)


class DiscoveryCase:
    @pytest.fixture(autouse=True)
    def _setup(self):
        self.dir = Path(tempfile.mkdtemp(prefix="chain_disc_test_"))
        self.chains_dir = self.dir / "chains"
        save_chain(_chain("test-chain-a", "600183", "生益科技", "FR8价格"),
                   base_dir=self.chains_dir)
        save_chain(_chain("copper-aluminum", "601899", "紫金矿业", "铜价"),
                   base_dir=self.chains_dir)
        self.research = self.dir / "research"
        (self.research / "reports").mkdir(parents=True)
        (self.research / "notices").mkdir(parents=True)
        (self.research / "reports" / f"{DATE}.json").write_text(
            json.dumps(_reports(), ensure_ascii=False), encoding="utf-8")
        (self.research / "notices" / f"{DATE}.json").write_text(
            json.dumps(_notices(), ensure_ascii=False), encoding="utf-8")
        self.tracking = self.dir / "tracking"
        self.ff_empty = self.dir / "ff_empty"  # 不存在 → 板块触发源缺席
        self.kw = dict(date=DATE, now=NOW, offline=True,
                       base_dir=self.chains_dir, tracking_dir=self.tracking,
                       db_path=self.dir / "discovery_items.db",
                       research_root=self.research, sector_root=self.ff_empty)

    def db(self) -> ProcessedItemsDB:
        return ProcessedItemsDB(self.dir / "discovery_items.db")

    def pending_path(self) -> Path:
        return self.tracking / "proposals_pending.json"


class TestDiscoveryTick(DiscoveryCase):
    def test_end_to_end(self):
        captured = []

        def call_fn(messages, **kw):
            captured.append(messages)
            return _found()

        summary = run_discovery(call_fn=call_fn, **self.kw)
        assert summary["fetched"] == 5  # 4 研报 + 1 公告
        assert summary["candidates"] == 2  # AP101/AP104
        assert summary["llm_calls"] == 1
        assert [p["chain_id"] for p in summary["proposals"]] == ["solid-state-battery"]
        # pending + 日产出审计
        pending = load_pending(self.pending_path())
        assert pending[0]["chain_id"] == "solid-state-battery"
        assert pending[0]["proposed_at"] == DATE
        audit = json.loads((self.tracking / f"proposals_{DATE}.json")
                           .read_text(encoding="utf-8"))
        assert audit[0]["chain_id"] == "solid-state-battery"
        # prompt 不含被已有链匹配的研报标题
        user = captured[0][1]["content"]
        assert "FR8涨价函点评" not in user
        assert "AI" not in user or True  # 不约束
        # 落账：候选=proposed；匹配已有链=matched_existing；无触发词=NULL
        db = self.db()
        assert db.get("AP101")["llm_verdict"] == "proposed"
        assert db.get("AP102")["llm_verdict"] == "matched_existing"
        assert db.get("AP102")["chain_id"] == "test-chain-a"
        assert db.get("AP103")["llm_verdict"] is None
        # tick 日志
        ticks = (self.tracking / "discovery_ticks.jsonl").read_text(
            encoding="utf-8").strip()
        assert json.loads(ticks)["candidates"] == 2

    def test_empty_batch_silent(self):
        summary = run_discovery(
            date="2026-08-30", now=NOW, offline=True,
            base_dir=self.chains_dir, tracking_dir=self.tracking,
            db_path=self.dir / "discovery_items.db", research_root=self.research,
            sector_root=self.ff_empty,
            call_fn=lambda m, **k: pytest.fail("不应调 LLM"))
        assert summary["new_items"] == 0
        assert summary["llm_calls"] == 0
        assert not self.pending_path().exists()
        assert not (self.tracking / "proposals_2026-08-30.json").exists()

    def test_idempotent_second_run(self):
        calls = []

        def call_fn(messages, **kw):
            calls.append(1)
            return _found()

        run_discovery(call_fn=call_fn, **self.kw)
        summary2 = run_discovery(call_fn=call_fn, **self.kw)
        assert summary2["new_items"] == 0
        assert summary2["llm_calls"] == 0
        assert len(calls) == 1
        assert len(load_pending(self.pending_path())) == 1

    def test_duplicate_of_existing_chain_dropped(self):
        summary = run_discovery(
            call_fn=lambda m, **k: _found(proposals=[
                {"chain_id": "test-chain-a", "name": "换个名字", "driver": "d",
                 "thesis": "t", "chain": {}, "current_stage": "阶段1-启动期",
                 "timing": "", "confidence": "低", "source": "s"}]),
            **self.kw)
        assert summary["proposals"] == []
        assert len(summary["skipped_duplicates"]) == 1
        assert load_pending(self.pending_path()) == []

    def test_batch_split(self):
        calls = []

        def call_fn(messages, **kw):
            calls.append(1)
            return _NONE_FOUND

        summary = run_discovery(call_fn=call_fn, max_items_per_batch=1, **self.kw)
        assert summary["llm_calls"] == 2  # 2 候选 × 1 条/批
        assert len(calls) == 2

    def test_no_llm_mode_defers_candidates(self):
        summary = run_discovery(no_llm=True,
                                call_fn=lambda m, **k: pytest.fail("不应调 LLM"),
                                **self.kw)
        assert summary["llm_calls"] == 0
        assert summary["candidates"] == 2
        db = self.db()
        assert db.get("AP101") is None  # 候选不落账，留给真实跑
        assert db.get("AP103") is not None  # 非候选已记录

    def test_dry_run_no_writes(self):
        summary = run_discovery(dry_run=True, call_fn=lambda m, **k: _found(),
                                **self.kw)
        assert len(summary["proposals"]) == 1
        assert self.db().count() == 0
        assert not self.pending_path().exists()
        assert not (self.tracking / f"proposals_{DATE}.json").exists()

    def test_llm_error_not_recorded_then_retry(self):
        def boom(messages, **kw):
            raise RuntimeError("API down")

        summary = run_discovery(call_fn=boom, **self.kw)
        assert summary["llm_errors"] == 1
        assert self.db().get("AP101") is None  # 失败不落账
        # 下一轮自愈重试
        summary2 = run_discovery(call_fn=lambda m, **k: _found(), **self.kw)
        assert summary2["llm_errors"] == 0
        assert self.db().get("AP101")["llm_verdict"] == "proposed"

    def test_sector_anomaly_flows_into_candidates(self):
        """板块异动触发源（T17 补强）：无归属板块进候选，有归属板块不算。"""
        ff = self.dir / "fund_flow"
        ff.mkdir()
        (ff / f"{DATE.replace('-', '')}.json").write_text(json.dumps({
            "date": DATE,
            "industry": {"即时": []},
            "concept": {"即时": [
                # 无归属 → 候选
                {"行业": "供销社", "行业-涨跌幅": 3.06,
                 "领涨股": "辉隆股份", "领涨股-涨跌幅": 9.97},
                # 领涨股紫金矿业在 copper-aluminum 链 → matched_existing
                {"行业": "铜业", "行业-涨跌幅": 4.20,
                 "领涨股": "紫金矿业", "领涨股-涨跌幅": 5.0},
            ]},
        }, ensure_ascii=False), encoding="utf-8")

        summary = run_discovery(call_fn=lambda m, **k: _found(),
                                **dict(self.kw, sector_root=ff))
        assert summary["sector_anomalies"] == 2
        assert summary["candidates"] == 3  # AP101/AP104 + 供销社板块
        db = self.db()
        assert db.get(f"sector:{DATE}:concept:供销社")["llm_verdict"] == "proposed"
        cu = db.get(f"sector:{DATE}:concept:铜业")
        assert cu["llm_verdict"] == "matched_existing"
        assert cu["chain_id"] == "copper-aluminum"

    def test_evidence_accumulation(self):
        # 第一轮：提议落 pending（carbon-fiber，含标的 吉林化纤）
        run_discovery(call_fn=lambda m, **k: _found_carbon(), **self.kw)
        # 第二轮（次日）：新信息命中 pending 标的且含触发词——应挂为证据而非候选
        date2 = "2026-09-01"
        (self.research / "reports" / f"{date2}.json").write_text(json.dumps([
            {"info_code": "AP201", "title": "吉林化纤：碳纤维缺货警报",
             "publish_date": date2, "org": "测试证券", "stock_code": "",
             "stock_name": "吉林化纤", "industry_name": "化纤", "pdf_url": ""},
        ], ensure_ascii=False), encoding="utf-8")
        (self.research / "notices" / f"{date2}.json").write_text(
            "[]", encoding="utf-8")
        summary = run_discovery(
            date=date2, now=datetime(2026, 9, 1, 10, 30), offline=True,
            base_dir=self.chains_dir, tracking_dir=self.tracking,
            db_path=self.dir / "discovery_items.db", research_root=self.research,
            sector_root=self.ff_empty,
            call_fn=lambda m, **k: pytest.fail("证据命中不应再调 LLM"))
        assert summary["evidence_hits"] == 1
        assert summary["evidence"] == {"carbon-fiber": 1}
        assert summary["candidates"] == 0
        assert summary["llm_calls"] == 0
        p = load_pending(self.pending_path())[0]
        assert p["evidence"][0]["info_id"] == "AP201"
        assert p["last_evidence_at"] == date2
        db = self.db()
        assert db.get("AP201")["llm_verdict"] == "evidence"
        assert db.get("AP201")["chain_id"] == "carbon-fiber"
