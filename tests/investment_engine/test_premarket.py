"""早盘盘前盲判测试（mock LLM，不触网）。"""
import json
import tempfile
from pathlib import Path

import pytest

from qing_investment.kline_cache import init_db, save_index_klines, save_klines
from investment_engine.shadow import premarket as pm


def _klines(code: str, closes: list[float]) -> list[dict]:
    return [
        {"code": code, "date": f"2026-06-{i + 1:02d}", "open": c, "high": c * 1.02,
         "low": c * 0.98, "close": c, "volume": 1000 + i * 10,
         "turnover": 1.5, "amplitude": 4.0, "pct_change": 0.5}
        for i, c in enumerate(closes)
    ]


def _overnight(day: str) -> dict:
    return {"date": day, "fetched_at": f"{day}T08:20:00",
            "themes": [{"id": "ai", "name": "AI算力",
                        "stocks": [{"symbol": "NVDA", "name": "英伟达",
                                    "price": 120.0, "prev_close": 115.0,
                                    "pct_change": 4.35, "secid": "105.NVDA",
                                    "earnings_note": ""}]}],
            "errors": [], "note": "涨跌幅为昨夜美股收盘数据"}


class TestPremarketPrompt:
    def test_prompt_passes_leakage_assertion(self):
        """盘前 prompt 边界=预测日，含隔夜外盘仍须过防泄漏。"""
        db = Path(tempfile.gettempdir()) / f"test_pre_{id(self)}.db"
        init_db(db_path=db)
        save_index_klines("sh000300", _klines("IDX000300", [4000.0 + i for i in range(30)]),
                          db_path=db)
        save_klines("002371.SZ", _klines("002371.SZ", [10.0 + i * 0.1 for i in range(30)]),
                    db_path=db)

        pack = pm.build_daily_pack("2026-06-15", config_dir=Path("config/stock_monitor"),
                                   db_path=db)
        overnight = _overnight("2026-06-16")
        text = pm._pack_to_premarket_prompt(pack, "2026-06-16", overnight)
        assert "2026-06-16" in text  # 边界日期=预测日
        assert "英伟达" in text and "4.35" in text  # 隔夜外盘已注入
        assert "2026-06-17" not in text  # 无未来日期

    def test_prompt_without_overnight(self):
        """隔夜外盘缺失时不注入该块，仍可出 prompt。"""
        db = Path(tempfile.gettempdir()) / f"test_pre2_{id(self)}.db"
        init_db(db_path=db)
        save_index_klines("sh000300", _klines("IDX000300", [4000.0 + i for i in range(30)]),
                          db_path=db)
        pack = pm.build_daily_pack("2026-06-15", config_dir=Path("config/stock_monitor"),
                                   db_path=db)
        text = pm._pack_to_premarket_prompt(pack, "2026-06-16", None)
        assert "overnight_us" not in text


class TestPremarketPromptVersion:
    def test_prompt_version_is_v10(self):
        """pattern-patch 2026-08-21：版本号 v9→v10（规则25 宏观三条件 + 规则23b 催化兑现覆盖）。"""
        assert pm.PROMPT_VERSION == "v10.1"

    def test_premarket_prompt_contains_discipline_rules(self):
        """v6 新增纪律规则关键词须出现在盘前 prompt（B1/B2/A2-A5/C5引用/C8降级）。"""
        text = pm.PREMARKET_SYSTEM_PROMPT
        assert "±15%" in text  # B1 证据-结论一致性硬约束（v8 校准后重定）
        assert "环比前日_pct" in text and "并列" in text  # v8 规则9 形态/环比并列口径
        assert "数据缺失，信息差风险" in text  # B2(c)/C8 降级标注
        assert "冲量滑落" in text and "scenarios" in text  # A2 形态禁判
        assert "量从哪来" in text  # A3 量能源头
        assert "反弹修复段" in text and "补缺回踩" in text  # A4 位置决定意义
        assert "守住前日量级" in text and "24000 亿以上算放量" in text  # A5 相对口径
        assert "promotion_rate" in text and "晋级率" in text  # C5 梯队引用/A8 折算
        assert "forming/divergence" in text  # v7 规则17 顶部结构信号引用

    def test_premarket_prompt_contains_v9_up_patterns(self):
        """v9 规则18-22（2026-08-21 三方对比提案）关键词须在盘前 prompt。"""
        text = pm.PREMARKET_SYSTEM_PROMPT
        assert "三信号见底清单" in text and "强势股" in text and "多杀多" in text  # 规则18
        assert "宽度修复" in text and "谁在涨" in text  # 规则19 宽度/强度两步
        assert "下台阶" in text  # 规则20 量能台阶锚定
        assert "防御方向默认退潮" in text  # 规则21 弱市防御禁止顺延
        assert "个股级验证节点" in text  # 规则22 watch_next 首条
        assert "催化溯源" in text and "无显性催化" in text  # 规则23 方向催化溯源
        assert "外力/内生归因前置" in text and "外部链条检验结论" in text  # 规则24


class TestRunPredictPremarket:
    def test_no_prev_day_returns_no_data(self):
        db = Path(tempfile.gettempdir()) / f"test_pre3_{id(self)}.db"
        init_db(db_path=db)
        rec = pm.run_predict_premarket("2026-06-01", config_dir="config/stock_monitor",
                                       db_path=db)
        assert rec["status"] == "no_data"

    def test_skips_completed(self, monkeypatch, tmp_path):
        db = Path(tempfile.gettempdir()) / f"test_pre4_{id(self)}.db"
        init_db(db_path=db)
        save_index_klines("sh000300", _klines("IDX000300", [4000.0 + i for i in range(30)]),
                          db_path=db)
        pred_dir = Path(tmp_path)
        (pred_dir / "2026-06-16-pre.json").write_text(
            json.dumps({"date": "2026-06-16", "status": "pending_maturity"}),
            encoding="utf-8")
        rec = pm.run_predict_premarket("2026-06-16", config_dir="config/stock_monitor",
                                       db_path=db, pred_dir=pred_dir)
        assert rec["status"] == "skipped"


class TestPremarketDataBlocks:
    """批次 P1/P2 接线：missing 进正文 + target_day 传递 + catalysts 可见。"""

    def _db(self, name: str) -> Path:
        db = Path(tempfile.gettempdir()) / f"{name}_{id(self)}.db"
        init_db(db_path=db)
        save_index_klines("sh000300", _klines("IDX000300", [4000.0 + i for i in range(30)]),
                          db_path=db)
        # list_trading_days 以个股 K 线为准，run_predict_premarket 找前一交易日需要
        save_klines("002371.SZ", _klines("002371.SZ", [10.0 + i * 0.1 for i in range(30)]),
                    db_path=db)
        return db

    def _empty_roots(self) -> dict:
        roots = {}
        for key, sub in (("kpl_root", None), ("em_root", "lhb"), ("lp_root", None),
                         ("ic_root", None), ("research_root", None),
                         ("ff_root", None), ("ia_root", None)):
            root = Path(tempfile.mkdtemp())
            if key == "kpl_root":
                for d in ("emotion", "news", "lhb"):
                    (root / d).mkdir(parents=True)
            elif key == "research_root":
                for d in ("notices", "reports"):
                    (root / d).mkdir(parents=True)
            elif sub:
                (root / sub).mkdir(parents=True)
            roots[key] = root
        roots["vh_path"] = Path(tempfile.mkdtemp()) / "no_vh.json"  # 隔离真实 volume_history.json
        return roots

    def test_missing_block_in_prompt_body(self):
        """v6 规则 11(c) 依赖 missing 块：盘前 prompt 正文必须带数据缺失清单。"""
        db = self._db("test_pre_missing")
        roots = self._empty_roots()
        pack = pm.build_daily_pack("2026-06-15", config_dir=Path("config/stock_monitor"),
                                   db_path=db, **roots)
        assert pack.get("missing")  # 空数据根下必有缺失块
        text = pm._pack_to_premarket_prompt(pack, "2026-06-16", None)
        assert '"missing"' in text
        assert "kpl_emotion" in text
        db.unlink(missing_ok=True)

    def test_catalysts_in_prompt(self):
        """target_day 触发 catalysts 扫描：(prev_day, target_day] 区间催化进盘前正文。"""
        db = self._db("test_pre_cat")
        roots = self._empty_roots()
        (roots["research_root"] / "notices" / "2026-06-16.json").write_text(
            json.dumps([{"code": "600664", "name": "哈药股份",
                         "title": "哈药股份:签订重大合同公告",
                         "type": "临时公告", "date": "2026-06-16", "url": ""}],
                       ensure_ascii=False), encoding="utf-8")
        pack = pm.build_daily_pack("2026-06-15", config_dir=Path("config/stock_monitor"),
                                   db_path=db, target_day="2026-06-16", **roots)
        assert pack["catalysts_since_prev_day"][0]["title"] == "哈药股份:签订重大合同公告"
        text = pm._pack_to_premarket_prompt(pack, "2026-06-16", None)
        assert "catalysts_since_prev_day" in text
        assert "哈药股份:签订重大合同公告" in text
        db.unlink(missing_ok=True)

    def test_run_predict_premarket_passes_target_day(self, monkeypatch, tmp_path):
        """盘前建包调用点必须把预测目标日传给 build_daily_pack。"""
        db = self._db("test_pre_td")
        captured = {}

        def _fake_build(day, **kw):
            captured.update(kw)
            return {"date": day, "glossary": ""}

        monkeypatch.setattr(pm, "build_daily_pack", _fake_build)
        monkeypatch.setattr(pm, "call_deepseek", lambda *a, **kw: "{}")
        monkeypatch.setattr(pm, "parse_result", lambda raw: {})
        rec = pm.run_predict_premarket(
            "2026-06-16", config_dir="config/stock_monitor", db_path=db,
            pred_dir=Path(tmp_path), overnight_root=Path(tmp_path) / "ovn")
        assert captured.get("target_day") == "2026-06-16"
        assert rec["date"] == "2026-06-16"
        db.unlink(missing_ok=True)

    def _run_with_pack(self, monkeypatch, tmp_path, pack, gm):
        db = self._db("test_pre_gm")
        captured = {}
        monkeypatch.setattr(pm, "build_daily_pack", lambda day, **kw: dict(pack))
        monkeypatch.setattr(pm, "_pack_to_premarket_prompt",
                            lambda p, target, ovn: captured.update(p) or "text")
        monkeypatch.setattr(pm, "call_deepseek", lambda *a, **kw: "{}")
        monkeypatch.setattr(pm, "parse_result", lambda raw: {})
        monkeypatch.setattr("investment_engine.global_macro.load_global_macro",
                            lambda day, **kw: gm)
        rec = pm.run_predict_premarket(
            "2026-06-16", config_dir="config/stock_monitor", db_path=db,
            pred_dir=Path(tmp_path), overnight_root=Path(tmp_path) / "ovn")
        db.unlink(missing_ok=True)
        return rec, captured

    def test_overnight_macro_overrides_stale_block(self, monkeypatch, tmp_path):
        """2026-08-21 盘前宏观口径修正：今晨 {day}.json（隔夜全貌）覆盖 pack 内
        prev_day 宏观块（对「隔夜」问题晚一天），fetched_at 不进包。"""
        pack = {"date": "2026-06-15", "glossary": "",
                "global_macro": {"date": "2026-06-13", "美债收益率": {"10Y": {"yield": 4.70}}},
                "missing": ["global_macro"]}
        gm = {"date": "2026-06-16", "fetched_at": "2026-06-16T09:10:00",
              "美债收益率": {"10Y": {"yield": 4.65}}}
        _, captured = self._run_with_pack(monkeypatch, tmp_path, pack, gm)
        assert captured["global_macro"] == {"date": "2026-06-16",
                                            "美债收益率": {"10Y": {"yield": 4.65}}}
        assert "global_macro" not in captured.get("missing", [])  # 数据已在场，摘掉缺失登记

    def test_overnight_macro_absent_keeps_prev_block(self, monkeypatch, tmp_path):
        """今晨文件缺失（如代理故障）时沿用 prev_day 块降级，missing 登记不动。"""
        pack = {"date": "2026-06-15", "glossary": "",
                "global_macro": {"date": "2026-06-13", "美债收益率": {"10Y": {"yield": 4.70}}}}
        _, captured = self._run_with_pack(monkeypatch, tmp_path, pack, None)
        assert captured["global_macro"]["date"] == "2026-06-13"
