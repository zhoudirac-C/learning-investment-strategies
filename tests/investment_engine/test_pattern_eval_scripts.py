"""两个 CLI 的冒烟：argparse 解析 + 端到端走通（假数据）。"""
import json

import yaml


def _seed(tmp_path):
    results_path = tmp_path / "results.jsonl"
    rows = [
        {"date": "2026-08-03", "ok": True,
         "result": {"market_stage": "震荡", "directions": [],
                    "used_patterns": ["sector_rotation"]}},
    ]
    results_path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows),
                            encoding="utf-8")
    patterns_path = tmp_path / "patterns.yaml"
    patterns_path.write_text("""\
patterns:
- pattern_id: sector_rotation
  name: 板块轮动
  description: d
  trigger: t
  data_requirements: []
  steps: []
  falsification: []
  validation:
    historical_hit_rate: pending-m1
    applicable_regime: null
    known_failures: []
""", encoding="utf-8")
    return results_path, patterns_path


def test_propose_and_apply_end_to_end(tmp_path, monkeypatch):
    results_path, patterns_path = _seed(tmp_path)
    # 假 truth 与假 K 线评分，避免依赖真实缓存
    monkeypatch.setattr("investment_engine.blindtest.truth.load_truth",
                        lambda *a, **k: {"2026-08-03": "震荡"})
    monkeypatch.setattr(
        "investment_engine.blindtest.score.direction_scores",
        lambda rs, **k: {"samples": 2, "hits": 2, "hit_rate": 1.0, "details": []})
    monkeypatch.setattr(
        "investment_engine.blindtest.score.stock_scores",
        lambda rs, **k: {"samples": 1, "hits": 1, "hit_rate": 1.0, "details": []})

    from scripts.propose_pattern_validation import main as propose_main
    rc = propose_main(["--results", str(results_path),
                       "--patterns", str(patterns_path),
                       "--out-dir", str(tmp_path / "proposals")])
    assert rc == 0
    proposals = list((tmp_path / "proposals").glob("*.yaml"))
    assert len(proposals) == 1

    from scripts.apply_pattern_proposal import main as apply_main
    rc = apply_main([str(proposals[0]), "--patterns", str(patterns_path)])
    assert rc == 0
    doc = yaml.safe_load(patterns_path.read_text(encoding="utf-8"))
    assert doc["patterns"][0]["validation"]["historical_hit_rate"] == 1.0
