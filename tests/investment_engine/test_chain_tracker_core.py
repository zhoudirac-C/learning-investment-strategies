"""tick 编排与 CLI 测试（T9）。全部离线注入，不触网不调真 LLM。"""
import json
import tempfile
from datetime import datetime
from pathlib import Path

import pytest

from investment_engine.chain_tracker.core import run_tick
from investment_engine.industry_chain.store import load_chain, save_chain

NOW = datetime(2026, 8, 31, 10, 30, 0)
DATE = "2026-08-31"


def _chain(chain_id: str, code: str, name: str, metric: str,
           stage: str = "阶段2-加速期") -> dict:
    return {
        "chain_id": chain_id,
        "name": f"{name}产业链",
        "thesis": "需求爆发 → 涨价",
        "last_verified": "2026-08-30",
        "segments": [{"id": "seg-mid", "name": "中游", "materials": [metric]}],
        "mappings": [{"code": code, "name": name, "segment": "seg-mid",
                      "relation": "龙头", "elasticity": "core"}],
        "current_stage": stage,
        "stage_confidence": "高",
        "timing": {"current_recommendation": "中游", "next_trigger": "x",
                   "risk": "y"},
        "tracking_metrics": [{"metric": metric, "current": "上涨",
                              "signal_direction": "上涨=确认"}],
        "falsification": ["价格连续2周回落"],
    }


def _reports() -> list[dict]:
    return [
        {"info_code": "AP001", "title": "生益科技：满产满销", "publish_date": DATE,
         "org": "测试证券", "stock_code": "600183", "stock_name": "生益科技",
         "industry_name": "电子", "pdf_url": ""},
        {"info_code": "AP002", "title": "铜价创阶段新高", "publish_date": DATE,
         "org": "测试证券", "stock_code": "", "stock_name": "",
         "industry_name": "有色", "pdf_url": ""},
        {"info_code": "AP003", "title": "某白酒公司点评", "publish_date": DATE,
         "org": "测试证券", "stock_code": "600519", "stock_name": "贵州茅台",
         "industry_name": "食品饮料", "pdf_url": ""},
    ]


def _notices() -> list[dict]:
    return [{"code": "300999", "name": "无关公司", "title": "股东大会决议公告",
             "type": "股东大会", "date": DATE,
             "url": "http://x/AN202608310001.html"}]


def _unchanged(messages, **kw):
    return json.dumps({
        "step1_verification": {"verified": True, "confidence": "中"},
        "step5_recommendation": {"stage_change": "unchanged",
                                 "new_stage": "阶段2-加速期", "timing": "", "action": ""},
        "verdict": "confirmed", "summary": "无实质变化",
    }, ensure_ascii=False)


def _forward(messages, **kw):
    return json.dumps({
        "step1_verification": {"verified": True, "confidence": "高"},
        "step5_recommendation": {"stage_change": "forward",
                                 "new_stage": "阶段3-分歧期",
                                 "timing": "下游", "action": "转向下游"},
        "verdict": "strengthening", "summary": "信号加强",
    }, ensure_ascii=False)


class TickCase:
    @pytest.fixture(autouse=True)
    def _setup(self):
        self.dir = Path(tempfile.mkdtemp(prefix="chain_core_test_"))
        self.chains_dir = self.dir / "chains"
        save_chain(_chain("test-chain-a", "600183", "生益科技", "FR8价格"),
                   base_dir=self.chains_dir)
        save_chain(_chain("copper-aluminum", "601899", "紫金矿业", "铜价",
                          stage="阶段1-启动期"), base_dir=self.chains_dir)
        self.research = self.dir / "research"
        (self.research / "reports").mkdir(parents=True)
        (self.research / "notices").mkdir(parents=True)
        (self.research / "reports" / f"{DATE}.json").write_text(
            json.dumps(_reports(), ensure_ascii=False), encoding="utf-8")
        (self.research / "notices" / f"{DATE}.json").write_text(
            json.dumps(_notices(), ensure_ascii=False), encoding="utf-8")
        self.tracking = self.dir / "tracking"
        self.kw = dict(date=DATE, now=NOW, offline=True,
                       base_dir=self.chains_dir, tracking_dir=self.tracking,
                       db_path=self.dir / "processed_items.db",
                       research_root=self.research,
                       fetch_futures_text=lambda url: "")


class TestTick(TickCase):
    def test_matched_items_llm_called_and_recorded(self):
        calls = []

        def call_fn(messages, **kw):
            calls.append(messages)
            return _unchanged(messages)

        summary = run_tick(call_fn=call_fn, **self.kw)
        assert summary["new_items"] == 4  # 3 研报 + 1 公告
        assert summary["llm_calls"] == 2  # 链A(生益) + 链B(铜价)
        assert summary["changes"] == []
        # 无变化 → 无日报（静默）
        assert not (self.tracking / f"daily_report_{DATE}.md").exists()
        # tick 日志始终落账
        ticks = (self.tracking / "ticks.jsonl").read_text(encoding="utf-8").strip()
        assert json.loads(ticks)["new_items"] == 4
        # 无关研报被记录为未匹配（不会反复喂 LLM）
        from investment_engine.chain_tracker.dedup import ProcessedItemsDB
        db = ProcessedItemsDB(self.dir / "processed_items.db")
        row = db.get("AP003")
        assert row["chain_id"] is None
        assert db.get("AP001")["chain_id"] == "test-chain-a"
        assert db.get("AP001")["llm_verdict"] == "confirmed"

    def test_empty_batch_silent(self):
        summary = run_tick(date="2026-08-30", now=NOW, offline=True,
                           base_dir=self.chains_dir, tracking_dir=self.tracking,
                           db_path=self.dir / "processed_items.db",
                           research_root=self.research,
                           fetch_futures_text=lambda url: "",
                           call_fn=lambda m, **k: pytest.fail("不应调 LLM"))
        assert summary["new_items"] == 0
        assert summary["llm_calls"] == 0
        assert not (self.tracking / "daily_report_2026-08-30.md").exists()

    def test_stage_change_writes_chain_and_report(self):
        summary = run_tick(call_fn=_forward, **self.kw)
        assert len(summary["changes"]) == 2
        a = load_chain("test-chain-a", base_dir=self.chains_dir)
        assert a["current_stage"] == "阶段3-分歧期"
        assert a["history"][-1]["stage"] == "阶段3-分歧期"
        assert a["history"][-1]["result"] == "待验证"
        report = (self.tracking / f"daily_report_{DATE}.md").read_text(encoding="utf-8")
        assert "test-chain-a" in report and "阶段3-分歧期" in report

    def test_idempotent_second_run(self):
        calls = []

        def call_fn(messages, **kw):
            calls.append(1)
            return _unchanged(messages)

        run_tick(call_fn=call_fn, **self.kw)
        summary2 = run_tick(call_fn=call_fn, **self.kw)
        assert summary2["new_items"] == 0
        assert summary2["llm_calls"] == 0
        assert len(calls) == 2  # 第一轮的 2 次，第二轮 0 次

    def test_no_llm_mode_defers_matched_items(self):
        summary = run_tick(no_llm=True, call_fn=lambda m, **k: pytest.fail("不应调 LLM"),
                           **self.kw)
        assert summary["llm_calls"] == 0
        assert summary["matched_pairs"] >= 2
        # 未记录 matched 项 → 下一轮真实跑仍会处理
        from investment_engine.chain_tracker.dedup import ProcessedItemsDB
        db = ProcessedItemsDB(self.dir / "processed_items.db")
        assert db.get("AP001") is None
        # 但未匹配项已记录（避免重复匹配开销）
        assert db.get("AP003") is not None

    def test_dry_run_no_writes(self):
        summary = run_tick(dry_run=True, call_fn=_forward, **self.kw)
        assert len(summary["changes"]) == 2
        a = load_chain("test-chain-a", base_dir=self.chains_dir)
        assert a["current_stage"] == "阶段2-加速期"  # 未回写
        assert "history" not in a
        from investment_engine.chain_tracker.dedup import ProcessedItemsDB
        assert ProcessedItemsDB(self.dir / "processed_items.db").count() == 0
        assert not (self.tracking / f"daily_report_{DATE}.md").exists()

    def test_futures_anomaly_flows_to_chain(self):
        sina = ('var hq_str_nf_CU0="铜连续,010000,112000.000,112000.000,108000.000,'
                '0.000,112000.000,112000.000,112000.000,0.000,108620.000,9,2,'
                '214972.000,57753,沪,铜,2026-08-31,1";')
        kw = dict(self.kw, fetch_futures_text=lambda url: sina)
        summary = run_tick(call_fn=_unchanged, **kw)
        futures_items = [i for i in summary["processed_ids"]
                         if str(i).startswith("futures:")]
        assert futures_items == ["futures:CU0:2026-08-31:10:30"]

    def test_llm_error_does_not_block_other_chains(self):
        def call_fn(messages, **kw):
            if "生益科技产业链" in messages[1]["content"]:
                raise RuntimeError("API down")
            return _unchanged(messages)

        summary = run_tick(call_fn=call_fn, **self.kw)
        assert summary["llm_errors"] == 1
        assert summary["llm_calls"] == 2
        from investment_engine.chain_tracker.dedup import ProcessedItemsDB
        db = ProcessedItemsDB(self.dir / "processed_items.db")
        # 失败的链不落账：留给下一 tick 自愈重试
        assert db.get("AP001") is None
        # 其他链正常落账
        assert db.get("AP002")["llm_verdict"] == "confirmed"
        # 下一轮重跑：AP001 会被重新处理（自愈）
        summary2 = run_tick(call_fn=_unchanged, **self.kw)
        assert summary2["llm_errors"] == 0
        assert ProcessedItemsDB(self.dir / "processed_items.db").get(
            "AP001")["llm_verdict"] == "confirmed"


def _evolving(messages, **kw):
    """unchanged + 附带 add_node 演化提案（两条链共用同一 fake）。"""
    return json.dumps({
        "step1_verification": {"verified": True, "confidence": "中"},
        "step5_recommendation": {"stage_change": "unchanged",
                                 "new_stage": "阶段2-加速期", "timing": "", "action": ""},
        "verdict": "strengthening", "summary": "有结构性增量",
        "logic_update": {"change_type": "add_node", "summary": "新增玻璃布供给节点",
                         "detail": {"metric": {"metric": "玻璃布Q-Glass供给",
                                               "current": "Nittobo主导",
                                               "signal_direction": "大陆切入=加强"}},
                         "rationale": "深度报告给出国产切入证据", "confidence": "中"},
    }, ensure_ascii=False)


class TestEvolutionProposals(TickCase):
    def _pending(self) -> list:
        path = self.tracking / "evolution_pending.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []

    def test_logic_update_lands_pending_report_audit(self):
        summary = run_tick(call_fn=_evolving, **self.kw)
        assert summary["changes"] == []          # 阶段不变
        assert len(summary["evolution_proposals"]) == 2  # 两条链各一条提案
        pending = self._pending()
        assert {p["chain_id"] for p in pending} == {"test-chain-a", "copper-aluminum"}
        pa = next(p for p in pending if p["chain_id"] == "test-chain-a")
        assert pa["proposal_id"] == "test-chain-a:add_node:玻璃布Q-Glass供给"
        assert pa["source_info_ids"] == ["AP001"]
        assert [e["info_id"] for e in pa["evidence"]] == ["AP001"]
        # 无阶段变化但有演化提案 → 日报写演化附节
        report = (self.tracking / f"daily_report_{DATE}.md").read_text(encoding="utf-8")
        assert "演化提案" in report
        assert "test-chain-a:add_node:玻璃布Q-Glass供给" in report
        # 日产出审计
        audit = json.loads(
            (self.tracking / f"evolution_{DATE}.json").read_text(encoding="utf-8"))
        assert len(audit) == 2
        # tick 日志带 evolution 字段
        tick = json.loads(
            (self.tracking / "ticks.jsonl").read_text(encoding="utf-8").strip())
        assert set(tick["evolution"]) == {p["proposal_id"] for p in pending}

    def test_second_run_no_duplicate(self):
        run_tick(call_fn=_evolving, **self.kw)
        summary2 = run_tick(call_fn=_evolving, **self.kw)
        assert summary2["new_items"] == 0      # 去重 DB 拦截
        assert summary2["evolution_proposals"] == []
        assert len(self._pending()) == 2       # 不重复占位

    def test_irrelevant_drops_logic_update(self):
        def call_fn(messages, **kw):
            out = json.loads(_evolving(messages))
            out["verdict"] = "irrelevant"
            return json.dumps(out, ensure_ascii=False)

        summary = run_tick(call_fn=call_fn, **self.kw)
        assert summary["evolution_proposals"] == []
        assert self._pending() == []
        assert not (self.tracking / f"daily_report_{DATE}.md").exists()

    def test_dry_run_preview_no_writes(self):
        summary = run_tick(dry_run=True, call_fn=_evolving, **self.kw)
        assert len(summary["evolution_proposals"]) == 2  # 预览可见
        assert self._pending() == []                      # 但不落账
        assert not (self.tracking / f"evolution_{DATE}.json").exists()
        assert not (self.tracking / f"daily_report_{DATE}.md").exists()
