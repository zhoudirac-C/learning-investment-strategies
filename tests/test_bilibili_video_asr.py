"""tests for scripts/bilibili_video_asr.py — 全部 fake HTTP，不触网。"""

from __future__ import annotations

import json
import urllib.error
from pathlib import Path

import pytest

from scripts import bilibili_video_asr as asr


def _cfg(tmp_path: Path, **overrides) -> dict:
    cfg = json.loads(json.dumps(asr.DEFAULT_CONFIG))
    cfg["cost_guard"]["log_file"] = str(tmp_path / "asr_log.jsonl")
    cfg["retry"]["backoff_seconds"] = [0, 0, 0]  # 测试不等
    cfg.update(overrides)
    return cfg


def _video_item(bvid: str = "BV1bEbD6PE8F") -> dict:
    return {
        "modules": {
            "module_dynamic": {
                "major": {"archive": {"bvid": bvid, "title": "周一计划"}}
            }
        }
    }


# ── BV 提取 ──────────────────────────────────────────────────────

def test_extract_bvid_ok():
    assert asr.extract_bvid(_video_item()) == "BV1bEbD6PE8F"


def test_extract_bvid_missing():
    assert asr.extract_bvid({}) == ""
    assert asr.extract_bvid({"modules": {"module_dynamic": {"major": None}}}) == ""
    assert asr.extract_bvid({"modules": {"module_dynamic": {}}}) == ""


# ── cid / playurl 解析 ───────────────────────────────────────────

def test_fetch_cid(monkeypatch, tmp_path):
    monkeypatch.setattr(
        asr, "_get_json",
        lambda url, sessdata="", timeout=15: {"code": 0, "data": {"cid": 40962101101}},
    )
    assert asr.fetch_cid("BV1x", "sess", _cfg(tmp_path)) == "40962101101"


def test_fetch_cid_api_error(monkeypatch, tmp_path):
    monkeypatch.setattr(
        asr, "_get_json",
        lambda url, sessdata="", timeout=15: {"code": -404, "message": "啥都木有"},
    )
    with pytest.raises(RuntimeError, match="code=-404"):
        asr.fetch_cid("BV1x", "sess", _cfg(tmp_path))


def test_fetch_audio_url_picks_highest_bandwidth(monkeypatch, tmp_path):
    resp = {
        "code": 0,
        "data": {"dash": {"audio": [
            {"bandwidth": 64000, "baseUrl": "https://low.example.com/a.m4s"},
            {"bandwidth": 126000, "baseUrl": "https://high.example.com/a.m4s"},
        ]}},
    }
    monkeypatch.setattr(asr, "_get_json", lambda url, sessdata="", timeout=15: resp)
    url = asr.fetch_audio_url("BV1x", "123", "sess", _cfg(tmp_path))
    assert url == "https://high.example.com/a.m4s"


def test_fetch_audio_url_no_dash(monkeypatch, tmp_path):
    monkeypatch.setattr(
        asr, "_get_json",
        lambda url, sessdata="", timeout=15: {"code": 0, "data": {"dash": {"audio": []}}},
    )
    with pytest.raises(RuntimeError, match="dash"):
        asr.fetch_audio_url("BV1x", "123", "sess", _cfg(tmp_path))


# ── 下载重试 ─────────────────────────────────────────────────────

def test_download_audio_retry_then_success(monkeypatch, tmp_path):
    attempts = {"n": 0}

    class FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b"audio-bytes"

    def fake_urlopen(req, timeout=0):
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise TimeoutError("timeout")
        return FakeResp()

    monkeypatch.setattr(asr.urllib.request, "urlopen", fake_urlopen)
    dest = tmp_path / "a.m4s"
    asr.download_audio("https://x.example.com/a.m4s", "sess", dest, _cfg(tmp_path))
    assert dest.read_bytes() == b"audio-bytes"
    assert attempts["n"] == 3


def test_download_audio_exhausts_retries(monkeypatch, tmp_path):
    def fake_urlopen(req, timeout=0):
        raise TimeoutError("always")

    monkeypatch.setattr(asr.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(TimeoutError):
        asr.download_audio("https://x.example.com/a.m4s", "sess", tmp_path / "a.m4s", _cfg(tmp_path))


# ── ASR 响应解析 ─────────────────────────────────────────────────

def _write_mp3(path: Path) -> Path:
    path.write_bytes(b"fake-mp3")
    return path


def test_transcribe_single_ok(monkeypatch, tmp_path):
    monkeypatch.setattr(
        asr, "_post_json",
        lambda url, body, key, timeout=180: {
            "choices": [{"message": {"content": "同花顺冲高回落"}}]
        },
    )
    mp3 = _write_mp3(tmp_path / "a.mp3")
    text = asr._transcribe_single(mp3, _cfg(tmp_path), "key")
    assert text == "同花顺冲高回落"


def test_transcribe_single_429_retry(monkeypatch, tmp_path):
    calls = {"n": 0}

    def fake_post(url, body, key, timeout=180):
        calls["n"] += 1
        if calls["n"] == 1:
            raise urllib.error.HTTPError(url, 429, "rate limited", {}, None)
        return {"choices": [{"message": {"content": "ok"}}]}

    monkeypatch.setattr(asr, "_post_json", fake_post)
    mp3 = _write_mp3(tmp_path / "a.mp3")
    assert asr._transcribe_single(mp3, _cfg(tmp_path), "key") == "ok"
    assert calls["n"] == 2


def test_transcribe_single_timeout_exhausts(monkeypatch, tmp_path):
    def fake_post(url, body, key, timeout=180):
        raise TimeoutError("slow")

    monkeypatch.setattr(asr, "_post_json", fake_post)
    mp3 = _write_mp3(tmp_path / "a.mp3")
    with pytest.raises(TimeoutError):
        asr._transcribe_single(mp3, _cfg(tmp_path), "key")


def test_transcribe_single_403_no_retry(monkeypatch, tmp_path):
    calls = {"n": 0}

    def fake_post(url, body, key, timeout=180):
        calls["n"] += 1
        raise urllib.error.HTTPError(url, 403, "forbidden", {}, None)

    monkeypatch.setattr(asr, "_post_json", fake_post)
    mp3 = _write_mp3(tmp_path / "a.mp3")
    with pytest.raises(urllib.error.HTTPError):
        asr._transcribe_single(mp3, _cfg(tmp_path), "key")
    assert calls["n"] == 1  # 403 不重试


# ── 切段合并 ─────────────────────────────────────────────────────

def test_transcribe_segments_merged(monkeypatch, tmp_path):
    wav = tmp_path / "audio.wav"
    wav.write_bytes(b"wav")
    cfg = _cfg(tmp_path)
    cfg["audio"]["segment_seconds"] = 240

    monkeypatch.setattr(asr, "_probe_duration", lambda p: 500.0)
    seg1, seg2 = tmp_path / "seg1.wav", tmp_path / "seg2.wav"
    monkeypatch.setattr(asr, "_segment", lambda w, s, d: [seg1, seg2])
    monkeypatch.setattr(asr, "to_mp3", lambda w, dest, cfg=None: _write_mp3(dest))
    monkeypatch.setattr(asr, "resolve_api_key", lambda cfg: "key")

    seen = []

    def fake_single(mp3_path, cfg, key):
        seen.append(mp3_path.name)
        return f"文本{len(seen)}"

    monkeypatch.setattr(asr, "_transcribe_single", fake_single)
    text = asr.transcribe(wav, cfg)
    assert text == "文本1\n文本2"
    assert seen == ["seg1.mp3", "seg2.mp3"]


def test_transcribe_short_no_segment(monkeypatch, tmp_path):
    wav = tmp_path / "audio.wav"
    wav.write_bytes(b"wav")
    monkeypatch.setattr(asr, "_probe_duration", lambda p: 100.0)
    monkeypatch.setattr(asr, "resolve_api_key", lambda cfg: "key")
    monkeypatch.setattr(asr, "to_mp3", lambda w, dest, cfg=None: _write_mp3(dest))
    monkeypatch.setattr(asr, "_transcribe_single", lambda p, c, k: "全文")
    assert asr.transcribe(wav, _cfg(tmp_path)) == "全文"


# ── 成本日志 + 预算拦截 ───────────────────────────────────────────

def test_log_cost_and_budget(tmp_path):
    cfg = _cfg(tmp_path)
    assert asr._check_daily_budget(cfg) is True

    from datetime import datetime
    asr._log_cost({"ts": datetime.now().isoformat(), "cost_cny": 4.9, "status": "ok"}, cfg)
    assert asr._check_daily_budget(cfg) is True
    asr._log_cost({"ts": datetime.now().isoformat(), "cost_cny": 0.2, "status": "ok"}, cfg)
    assert asr._check_daily_budget(cfg) is False  # 5.1 > 5.0 上限

    lines = (tmp_path / "asr_log.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["cost_cny"] == 4.9


# ── 主入口：异常不抛出 ───────────────────────────────────────────

def test_asr_video_no_bvid_returns_empty(tmp_path):
    assert asr.asr_video({}, _cfg(tmp_path), "sess") == ""


def test_asr_video_disabled(tmp_path):
    cfg = _cfg(tmp_path, enabled=False)
    assert asr.asr_video(_video_item(), cfg, "sess") == ""


def test_asr_video_full_chain_exception_returns_empty(monkeypatch, tmp_path):
    def boom(*a, **kw):
        raise RuntimeError("cid 挂了")

    monkeypatch.setattr(asr, "fetch_cid", boom)
    monkeypatch.setattr(asr, "check_ffmpeg", lambda: True)
    result = asr.asr_video(_video_item(), _cfg(tmp_path), "sess")
    assert result == ""  # 不抛出

    log_lines = (tmp_path / "asr_log.jsonl").read_text(encoding="utf-8").splitlines()
    entry = json.loads(log_lines[-1])
    assert entry["status"] == "failed"
    assert "cid 挂了" in entry["error"]


def test_asr_video_budget_exceeded(monkeypatch, tmp_path):
    cfg = _cfg(tmp_path)
    from datetime import datetime
    asr._log_cost({"ts": datetime.now().isoformat(), "cost_cny": 99.0, "status": "ok"}, cfg)

    called = {"n": 0}
    monkeypatch.setattr(asr, "fetch_cid", lambda *a, **kw: called.update(n=1))
    monkeypatch.setattr(asr, "check_ffmpeg", lambda: True)
    assert asr.asr_video(_video_item(), cfg, "sess") == ""
    assert called["n"] == 0  # 预算超限后不再请求


def test_asr_video_happy_path(monkeypatch, tmp_path):
    monkeypatch.setattr(asr, "check_ffmpeg", lambda: True)
    monkeypatch.setattr(asr, "fetch_cid", lambda b, s, c=None: "123")
    monkeypatch.setattr(asr, "fetch_audio_url", lambda b, c, s, cfg=None: "https://x/a.m4s")
    monkeypatch.setattr(asr, "download_audio", lambda u, s, d, cfg=None: d.write_bytes(b"m4s") or d)
    monkeypatch.setattr(asr, "to_wav", lambda s, d, cfg=None: d.write_bytes(b"wav") or d)
    monkeypatch.setattr(asr, "_probe_duration", lambda p: 333.0)
    monkeypatch.setattr(asr, "transcribe", lambda w, cfg=None: "同花顺 T点 减仓")

    cfg = _cfg(tmp_path)
    text = asr.asr_video(_video_item(), cfg, "sess")
    assert text == "同花顺 T点 减仓"

    entry = json.loads((tmp_path / "asr_log.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert entry["status"] == "ok"
    assert entry["bvid"] == "BV1bEbD6PE8F"
    assert entry["duration_s"] == 333.0
    assert entry["cost_cny"] > 0


# ── API key 解析 ─────────────────────────────────────────────────

def test_resolve_api_key_from_env(monkeypatch, tmp_path):
    monkeypatch.setenv("CUSTOM_OPENROUTER_API_KEY", "sk-test-123")
    assert asr.resolve_api_key(_cfg(tmp_path)) == "sk-test-123"


def test_resolve_api_key_fallback_openrouter(monkeypatch, tmp_path):
    monkeypatch.delenv("CUSTOM_OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-fallback")
    assert asr.resolve_api_key(_cfg(tmp_path)) == "sk-fallback"
