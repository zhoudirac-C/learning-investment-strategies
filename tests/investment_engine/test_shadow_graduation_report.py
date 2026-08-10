"""graduation 报告渲染与 run 入口、CLI 冒烟。"""
import json
from datetime import date

from investment_engine.shadow.graduation import run

TODAY = date(2026, 8, 9)


def _seed(tmp_path):
    pred_dir = tmp_path / "predictions"
    pred_dir.mkdir()
    rec = {"date": "2026-08-07", "status": "scored", "stage_hit": True,
           "due_scores": {"directions": {"samples": 2, "hits": 1, "hit_rate": 0.5}}}
    (pred_dir / "2026-08-07.json").write_text(
        json.dumps(rec, ensure_ascii=False), encoding="utf-8")
    return pred_dir


def test_run_writes_report(tmp_path):
    pred_dir = _seed(tmp_path)
    out = run(pred_dir, weeks=8, out_dir=tmp_path / "logs", today=TODAY)
    text = out.read_text(encoding="utf-8")
    assert out.name == "graduation-2026-08-09.md"
    assert "verdict: insufficient_data" in text          # 仅 1 周数据
    assert "阶段一致率: 100.0%（n=1）" in text
    assert "方向 5 日超额命中率: 50.0%（n=2）" in text
    assert "第三判据" in text and "不参与判定" in text
    assert "| 2026-08-03 |" in text                      # 分周明细行
    assert "解析跳过 0 条" in text


def test_run_no_data(tmp_path):
    out = run(tmp_path / "nonexistent", weeks=8,
              out_dir=tmp_path / "logs", today=TODAY)
    text = out.read_text(encoding="utf-8")
    assert "verdict: no_data" in text


def test_cli_smoke(tmp_path, capsys):
    pred_dir = _seed(tmp_path)
    from scripts.graduation_check import main
    rc = main(["--pred-dir", str(pred_dir),
               "--out-dir", str(tmp_path / "logs")])
    assert rc == 0
    out = capsys.readouterr().out
    assert "insufficient_data" in out
    assert (tmp_path / "logs").glob("graduation-*.md")


def test_report_has_version_note(tmp_path):
    pred_dir = _seed(tmp_path)
    out = run(pred_dir, weeks=8, out_dir=tmp_path / "logs", today=TODAY)
    text = out.read_text(encoding="utf-8")
    assert "prompt 版本" in text and "v1" in text
