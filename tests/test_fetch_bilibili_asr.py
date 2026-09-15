"""tests for fetch_bilibili_up_v2 的 ASR 接入（T2）—— fake 网络，不触网。"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import fetch_bilibili_up_v2 as fb


@pytest.fixture(autouse=True)
def _redirect_original_dir(tmp_path, monkeypatch):
    out = tmp_path / "bilibili_raw"
    out.mkdir()
    monkeypatch.setattr(fb, "original_dir", lambda: out)
    return out


def _video_item() -> dict:
    return {
        "id_str": "123456",
        "type": "DYNAMIC_TYPE_AV",
        "basic": {},
        "modules": {
            "module_author": {
                "name": "测试UP", "mid": "1",
                "pub_time": "2026-08-16 10:00", "pub_ts": "1786000000",
            },
            "module_dynamic": {
                "desc": {"text": "周一计划，牛来！"},
                "major": {"archive": {
                    "bvid": "BV1bEbD6PE8F", "title": "周一计划",
                    "cover": "http://x.example.com/cover.jpg",
                    "duration_text": "05:33", "desc": "简介",
                }},
            },
            "module_stat": {
                "like": {"count": 1}, "comment": {"count": 2}, "forward": {"count": 0},
            },
        },
    }


# ── save_dynamic_to_file ─────────────────────────────────────────

def test_save_video_always_writes_bvid():
    """有正文的视频动态也必须写 - BV号： 行（回归：此前只在无正文时写）。"""
    fp = fb.save_dynamic_to_file(_video_item(), "uid1", "123456")
    content = fp.read_text(encoding="utf-8")
    assert "周一计划，牛来！" in content
    assert "- BV号：BV1bEbD6PE8F" in content


def test_save_with_asr_section():
    fp = fb.save_dynamic_to_file(
        _video_item(), "uid1", "123456",
        asr_text="同花顺冲高回落，13.5 减仓",
        asr_meta={"model": "xiaomi/mimo-v2.5", "duration": "05:33"},
    )
    content = fp.read_text(encoding="utf-8")
    assert "## 视频转写" in content
    assert "> 模型：xiaomi/mimo-v2.5 | 时长：05:33 | 转写时间：" in content
    assert "同花顺冲高回落，13.5 减仓" in content
    # 转写段在 ## 原文 之后、## 视频封面 之前
    assert content.index("## 原文") < content.index("## 视频转写") < content.index("## 视频封面")


def test_save_asr_failure_marker_still_lands():
    """ASR 失败时 raw 正常落盘，仅记 [ASR失败: ...] 标注。"""
    fp = fb.save_dynamic_to_file(
        _video_item(), "uid1", "123456",
        asr_text="[ASR失败: 转写不可用，详见 stderr 日志]",
        asr_meta={"model": "xiaomi/mimo-v2.5", "duration": "05:33"},
    )
    content = fp.read_text(encoding="utf-8")
    assert "[ASR失败:" in content
    assert "## 互动数据" in content  # 其余段落不受影响


def test_save_no_asr_no_section():
    fp = fb.save_dynamic_to_file(_video_item(), "uid1", "123456")
    content = fp.read_text(encoding="utf-8")
    assert "## 视频转写" not in content


# ── run() 接入 ───────────────────────────────────────────────────

def _fake_feed(items: list[dict]) -> dict:
    return {"code": 0, "data": {"items": items}}


def test_run_video_calls_asr(tmp_path, monkeypatch):
    monkeypatch.setattr(fb, "fetch_dynamic_list", lambda uid, sess, offset="": _fake_feed([_video_item()]))
    monkeypatch.setattr(fb, "build_index", lambda: None)
    monkeypatch.setattr(fb, "asr_mod", SimpleNamespace(check_ffmpeg=lambda: True))

    calls = []

    def fake_maybe_asr(item, sessdata, cfg, dynamic_id=""):
        calls.append(dynamic_id)
        return "转写正文", {"model": "m", "duration": "05:33"}

    monkeypatch.setattr(fb, "maybe_asr_video", fake_maybe_asr)

    saved = fb.run(
        "uid1", "sess", {}, tmp_path / "state.json",
        enable_ocr=False, enable_comment=False,
        enable_asr=True, asr_cfg={"enabled": True},
    )
    assert calls == ["123456"]
    assert len(saved) == 1
    content = saved[0].read_text(encoding="utf-8")
    assert "## 视频转写" in content
    assert "转写正文" in content


def test_run_no_asr_skips(tmp_path, monkeypatch):
    monkeypatch.setattr(fb, "fetch_dynamic_list", lambda uid, sess, offset="": _fake_feed([_video_item()]))
    monkeypatch.setattr(fb, "build_index", lambda: None)
    monkeypatch.setattr(fb, "asr_mod", SimpleNamespace(check_ffmpeg=lambda: True))

    def fail_if_called(*a, **kw):
        raise AssertionError("--no-asr 时不应调用 ASR")

    monkeypatch.setattr(fb, "maybe_asr_video", fail_if_called)
    saved = fb.run(
        "uid1", "sess", {}, tmp_path / "state.json",
        enable_ocr=False, enable_comment=False, enable_asr=False,
    )
    assert len(saved) == 1
    content = saved[0].read_text(encoding="utf-8")
    assert "## 视频转写" not in content
    assert "- BV号：BV1bEbD6PE8F" in content  # raw 仍完整落盘


def test_run_asr_disabled_when_ffmpeg_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(fb, "fetch_dynamic_list", lambda uid, sess, offset="": _fake_feed([_video_item()]))
    monkeypatch.setattr(fb, "build_index", lambda: None)
    monkeypatch.setattr(fb, "asr_mod", SimpleNamespace(check_ffmpeg=lambda: False))

    def fail_if_called(*a, **kw):
        raise AssertionError("ffmpeg 缺失时不应调用 ASR")

    monkeypatch.setattr(fb, "maybe_asr_video", fail_if_called)
    saved = fb.run(
        "uid1", "sess", {}, tmp_path / "state.json",
        enable_ocr=False, enable_comment=False,
        enable_asr=True, asr_cfg={"enabled": True},
    )
    assert len(saved) == 1


# ── 回填 ─────────────────────────────────────────────────────────

def _make_raw_md(path: Path, item: dict) -> Path:
    content = "\n".join([
        "---",
        'dynamic_type: "视频"',
        "---",
        "",
        "## 原文",
        "",
        "周一计划，牛来！",
        "",
        "## 互动数据",
        "",
        "- 点赞：1",
        "",
        "<!--",
        "## 原始API数据",
        "",
        "```json",
        json.dumps(item, ensure_ascii=False),
        "```",
        "-->",
    ])
    path.write_text(content, encoding="utf-8")
    return path


def test_backfill_inserts_asr_section(tmp_path, monkeypatch):
    raw_dir = tmp_path / "bilibili_raw"
    md = _make_raw_md(raw_dir / "2026-08-16-1000-视频-周一计划.md", _video_item())

    monkeypatch.setattr(
        fb, "asr_mod",
        SimpleNamespace(asr_video=lambda item, cfg, sess: "回填转写文本"),
    )
    updated = fb.backfill_video_asr("sess", {"enabled": True, "model": "m"})
    assert updated == [md]

    content = md.read_text(encoding="utf-8")
    assert "## 视频转写" in content
    assert "回填转写文本" in content
    # 插在 ## 原文 之后、## 互动数据 之前
    assert content.index("## 原文") < content.index("## 视频转写") < content.index("## 互动数据")

    # 幂等：已有转写段的文件不再处理
    updated2 = fb.backfill_video_asr("sess", {"enabled": True, "model": "m"})
    assert updated2 == []


def test_backfill_skips_failed_asr(tmp_path, monkeypatch):
    raw_dir = tmp_path / "bilibili_raw"
    md = _make_raw_md(raw_dir / "v.md", _video_item())
    monkeypatch.setattr(fb, "asr_mod", SimpleNamespace(asr_video=lambda *a: ""))
    updated = fb.backfill_video_asr("sess", {"enabled": True, "model": "m"})
    assert updated == []
    assert "## 视频转写" not in md.read_text(encoding="utf-8")


def test_extract_embedded_item(tmp_path):
    raw_dir = tmp_path / "bilibili_raw"
    md = _make_raw_md(raw_dir / "v.md", _video_item())
    item = fb._extract_embedded_item(md.read_text(encoding="utf-8"))
    assert item["id_str"] == "123456"
    assert fb._extract_embedded_item("no json here") is None
