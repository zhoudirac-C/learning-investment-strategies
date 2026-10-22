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

    monkeypatch.setattr(asr, "fetch_video_meta", boom)
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
    monkeypatch.setattr(asr, "fetch_video_meta", lambda *a, **kw: called.update(n=1))
    monkeypatch.setattr(asr, "check_ffmpeg", lambda: True)
    assert asr.asr_video(_video_item(), cfg, "sess") == ""
    assert called["n"] == 0  # 预算超限后不再请求


def test_asr_video_happy_path(monkeypatch, tmp_path):
    monkeypatch.setattr(asr, "check_ffmpeg", lambda: True)
    monkeypatch.setattr(asr, "fetch_video_meta", lambda b, s, c=None: {"cid": "123", "duration_ms": 333000})
    monkeypatch.setattr(
        asr, "fetch_audio_url",
        lambda b, c, s, cfg=None, expected_duration_ms=None: "https://x/a.m4s",
    )
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


def test_transcribe_single_refusal_treated_as_failure(monkeypatch, tmp_path):
    """模型返回拒答（而非转写）时应抛错触发重试。"""
    monkeypatch.setattr(
        asr, "_post_json",
        lambda url, body, key, timeout=180: {"choices": [{"message": {"content": "我无法直接接收或处理音频文件。我是文本AI，只能阅读文字。"}}]},
    )
    mp3 = _write_mp3(tmp_path / "a.mp3")
    with pytest.raises(RuntimeError, match="拒答"):
        asr._transcribe_single(mp3, _cfg(tmp_path), "key")


# ── 充电专属加固：设备 cookie / 请求头 / 试看识别 ──────────────

_FIXED_DEVICE = {"buvid3": "B3TESTinfoc", "b_nut": 1700000000}


def test_build_cookie_decodes_urlencoded(monkeypatch):
    monkeypatch.setattr(asr, "_ensure_device_cookies", lambda: dict(_FIXED_DEVICE))
    cookie = asr._build_cookie("abc%2C123%2Cdef")
    assert "SESSDATA=abc,123,def" in cookie
    assert "buvid3=B3TESTinfoc" in cookie
    assert "b_nut=1700000000" in cookie


def test_build_cookie_plain_unchanged(monkeypatch):
    monkeypatch.setattr(asr, "_ensure_device_cookies", lambda: dict(_FIXED_DEVICE))
    cookie = asr._build_cookie("abc,123,def")
    assert "SESSDATA=abc,123,def" in cookie


def test_build_cookie_empty(monkeypatch):
    monkeypatch.setattr(asr, "_ensure_device_cookies", lambda: dict(_FIXED_DEVICE))
    assert asr._build_cookie("") == ""


def test_device_cookies_persisted(monkeypatch, tmp_path):
    monkeypatch.setenv("BILIBILI_DEVICE_STATE", str(tmp_path / "dev.json"))
    d1 = asr._ensure_device_cookies()
    d2 = asr._ensure_device_cookies()
    assert d1 == d2
    assert d1["buvid3"].endswith("infoc")
    assert d1["b_nut"] > 0
    assert (tmp_path / "dev.json").exists()


def test_get_json_sends_browser_headers(monkeypatch, tmp_path):
    monkeypatch.setenv("BILIBILI_DEVICE_STATE", str(tmp_path / "dev.json"))
    monkeypatch.setattr(asr, "_ensure_device_cookies", lambda: dict(_FIXED_DEVICE))
    captured: dict = {}

    class FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b'{"code": 0}'

    def fake_urlopen(req, timeout=0):
        captured["headers"] = {k.lower(): v for k, v in req.header_items()}
        return FakeResp()

    monkeypatch.setattr(asr.urllib.request, "urlopen", fake_urlopen)
    asr._get_json("https://example.com/api", "s%2C1")
    h = captured["headers"]
    assert h["accept"] == "application/json, text/plain, */*"
    assert h["accept-language"] == "zh-CN,zh;q=0.9"
    assert h["origin"] == "https://www.bilibili.com"
    assert h["referer"] == "https://www.bilibili.com/"
    assert "SESSDATA=s,1" in h["cookie"]
    assert "buvid3=B3TESTinfoc" in h["cookie"]


def test_fetch_video_meta(monkeypatch, tmp_path):
    monkeypatch.setattr(
        asr, "_get_json",
        lambda url, sessdata="", timeout=15: {"code": 0, "data": {"cid": 40962101101, "duration": 4470}},
    )
    meta = asr.fetch_video_meta("BV1x", "sess", _cfg(tmp_path))
    assert meta == {"cid": "40962101101", "duration_ms": 4470000}


def test_fetch_audio_url_preview_mismatch_nonretryable(monkeypatch, tmp_path):
    calls = {"n": 0}

    def fake(url, sessdata="", timeout=15):
        calls["n"] += 1
        return {"code": 0, "data": {
            "timelength": 1299000,
            "dash": {"audio": [{"bandwidth": 1, "baseUrl": "https://x/a.m4s"}]},
        }}

    monkeypatch.setattr(asr, "_get_json", fake)
    with pytest.raises(asr.ChargePreviewError, match="试看"):
        asr.fetch_audio_url("BV1x", "123", "sess", _cfg(tmp_path), expected_duration_ms=4470000)
    assert calls["n"] == 1  # 试看判定不重试


def test_fetch_audio_url_timelength_close_enough_passes(monkeypatch, tmp_path):
    resp = {"code": 0, "data": {
        "timelength": 4469300,  # 容器时长与 view 时长差 700ms，属正常
        "dash": {"audio": [{"bandwidth": 1, "baseUrl": "https://x/a.m4s"}]},
    }}
    monkeypatch.setattr(asr, "_get_json", lambda url, sessdata="", timeout=15: resp)
    url = asr.fetch_audio_url("BV1x", "123", "sess", _cfg(tmp_path), expected_duration_ms=4470000)
    assert url == "https://x/a.m4s"


def test_asr_video_preview_only_logs_and_returns_empty(monkeypatch, tmp_path):
    monkeypatch.setattr(asr, "check_ffmpeg", lambda: True)
    monkeypatch.setattr(
        asr, "fetch_video_meta",
        lambda b, s, c=None: {"cid": "123", "duration_ms": 4470000},
    )

    def boom(b, c, s, cfg=None, expected_duration_ms=None):
        raise asr.ChargePreviewError("playurl 仅返回试看流")

    monkeypatch.setattr(asr, "fetch_audio_url", boom)
    assert asr.asr_video(_video_item(), _cfg(tmp_path), "sess") == ""

    entry = json.loads((tmp_path / "asr_log.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert entry["status"] == "preview_only"
    assert "试看" in entry["error"]


# ── 备选模型 fallback（主力 mimo 故障时逐段切换） ───────────────

_FALLBACK = "qwen/qwen3.8-omni-flash"


def _fallback_cfg(tmp_path: Path) -> dict:
    cfg = _cfg(tmp_path)
    cfg["fallback_model"] = _FALLBACK
    return cfg


def test_transcribe_fallback_when_primary_fails(monkeypatch, tmp_path):
    wav = tmp_path / "audio.wav"
    wav.write_bytes(b"wav")
    monkeypatch.setattr(asr, "_probe_duration", lambda p: 100.0)
    monkeypatch.setattr(asr, "to_mp3", lambda w, dest, cfg=None: _write_mp3(dest))
    monkeypatch.setattr(asr, "resolve_api_key", lambda cfg: "key")

    calls = []

    def fake_single(mp3_path, cfg, key):
        calls.append(cfg["model"])
        if cfg["model"] == "xiaomi/mimo-v2.5":
            raise asr.ChargePreviewError("'NoneType' object has no attribute 'strip'")
        return "备选转写文本"

    monkeypatch.setattr(asr, "_transcribe_single", fake_single)
    assert asr.transcribe(wav, _fallback_cfg(tmp_path)) == "备选转写文本"
    assert calls == ["xiaomi/mimo-v2.5", _FALLBACK]


def test_transcribe_primary_ok_skips_fallback(monkeypatch, tmp_path):
    wav = tmp_path / "audio.wav"
    wav.write_bytes(b"wav")
    monkeypatch.setattr(asr, "_probe_duration", lambda p: 100.0)
    monkeypatch.setattr(asr, "to_mp3", lambda w, dest, cfg=None: _write_mp3(dest))
    monkeypatch.setattr(asr, "resolve_api_key", lambda cfg: "key")

    calls = []

    def fake_single(mp3_path, cfg, key):
        calls.append(cfg["model"])
        return "主力转写文本"

    monkeypatch.setattr(asr, "_transcribe_single", fake_single)
    assert asr.transcribe(wav, _fallback_cfg(tmp_path)) == "主力转写文本"
    assert calls == ["xiaomi/mimo-v2.5"]


def test_transcribe_no_fallback_config_raises(monkeypatch, tmp_path):
    """未配置 fallback_model 时维持原行为：主力异常直接抛出。"""
    wav = tmp_path / "audio.wav"
    wav.write_bytes(b"wav")
    monkeypatch.setattr(asr, "_probe_duration", lambda p: 100.0)
    monkeypatch.setattr(asr, "to_mp3", lambda w, dest, cfg=None: _write_mp3(dest))
    monkeypatch.setattr(asr, "resolve_api_key", lambda cfg: "key")
    monkeypatch.setattr(
        asr, "_transcribe_single",
        lambda mp3_path, cfg, key: (_ for _ in ()).throw(asr.ChargePreviewError("null")),
    )
    cfg = _cfg(tmp_path)  # fallback_model 默认为 ""，不触发切换
    assert cfg.get("fallback_model", "") == ""
    with pytest.raises(asr.ChargePreviewError, match="null"):
        asr.transcribe(wav, cfg)


def test_transcribe_fallback_also_fails_raises_primary(monkeypatch, tmp_path):
    """备选也失败时抛主力异常（根因），而不是备选的异常。"""
    wav = tmp_path / "audio.wav"
    wav.write_bytes(b"wav")
    monkeypatch.setattr(asr, "_probe_duration", lambda p: 100.0)
    monkeypatch.setattr(asr, "to_mp3", lambda w, dest, cfg=None: _write_mp3(dest))
    monkeypatch.setattr(asr, "resolve_api_key", lambda cfg: "key")

    def fake_single(mp3_path, cfg, key):
        raise asr.ChargePreviewError(f"boom-{cfg['model']}")

    monkeypatch.setattr(asr, "_transcribe_single", fake_single)
    with pytest.raises(asr.ChargePreviewError, match="boom-xiaomi/mimo-v2.5"):
        asr.transcribe(wav, _fallback_cfg(tmp_path))
