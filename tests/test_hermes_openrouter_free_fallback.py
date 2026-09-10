"""tests for scripts/hermes_openrouter_free_fallback.py"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from hermes_openrouter_free_fallback import (  # noqa: E402
    apply_updates,
    build_fallback_entries,
    filter_eligible,
    rank_models,
    sync_available_models,
)


def _model(mid, ctx=100000, created=1, tools=True, modality="text->text",
           prompt="0", completion="0", slug=None):
    return {
        "id": mid,
        "canonical_slug": slug or mid.removesuffix(":free"),
        "created": created,
        "context_length": ctx,
        "architecture": {"modality": modality},
        "pricing": {"prompt": prompt, "completion": completion},
        "supported_parameters": ["tools"] if tools else ["temperature"],
    }


class TestFilterEligible:
    def test_keeps_free_text_tool_models(self):
        models = [_model("a/x:free")]
        assert [m["id"] for m in filter_eligible(models, default_id="")] == ["a/x:free"]

    def test_drops_paid(self):
        models = [_model("a/x", prompt="0.001")]
        assert filter_eligible(models, default_id="") == []

    def test_drops_paid_completion(self):
        models = [_model("a/x", completion="0.0001")]
        assert filter_eligible(models, default_id="") == []

    def test_drops_non_text_output(self):
        # 音频/图像输出模型（如 google/lyria preview）即使价格为 0 也不可作为 agent fallback
        models = [_model("google/lyria", modality="text->audio")]
        assert filter_eligible(models, default_id="") == []

    def test_drops_no_tools(self):
        models = [_model("a/x:free", tools=False)]
        assert filter_eligible(models, default_id="") == []

    def test_drops_small_context(self):
        models = [_model("a/x:free", ctx=8192)]
        assert filter_eligible(models, default_id="", min_context=32768) == []

    def test_drops_current_default(self):
        models = [_model("a/x:free"), _model("b/y:free")]
        ids = [m["id"] for m in filter_eligible(models, default_id="a/x:free")]
        assert ids == ["b/y:free"]


class TestRankModels:
    def test_sort_by_context_then_created_desc(self):
        """无 benchmark 数据时退化为 context/created 排序。"""
        models = [
            _model("a/old-big:free", ctx=1000000, created=1),
            _model("b/small:free", ctx=200000, created=99),
            _model("c/new-big:free", ctx=1000000, created=2),
        ]
        ids = [m["id"] for m in rank_models(models)]
        assert ids == ["c/new-big:free", "a/old-big:free", "b/small:free"]

    def test_intelligence_beats_context(self):
        """智力优先：有 AA 智力分的小模型排在没有分的大模型前面。"""
        models = [
            _model("a/big-noscore:free", ctx=1000000, slug="a/big-noscore-20260101"),
            _model("b/small-smart:free", ctx=200000, slug="b/small-smart-20260101"),
        ]
        bench = {"b/small-smart-20260101": {"intelligence_index": 20.0,
                                            "agentic_index": 10.0}}
        ids = [m["id"] for m in rank_models(models, bench)]
        assert ids == ["b/small-smart:free", "a/big-noscore:free"]

    def test_intelligence_desc_then_agentic_tiebreak(self):
        models = [
            _model("a/low:free", slug="a/low-1"),
            _model("b/tie-weak-agent:free", slug="b/tie-weak-1"),
            _model("c/tie-strong-agent:free", slug="c/tie-strong-1"),
            _model("d/high:free", slug="d/high-1"),
        ]
        bench = {
            "a/low-1": {"intelligence_index": 10.0, "agentic_index": 5.0},
            "b/tie-weak-1": {"intelligence_index": 20.0, "agentic_index": 3.0},
            "c/tie-strong-1": {"intelligence_index": 20.0, "agentic_index": 9.0},
            "d/high-1": {"intelligence_index": 30.0, "agentic_index": 1.0},
        }
        ids = [m["id"] for m in rank_models(models, bench)]
        assert ids == ["d/high:free", "c/tie-strong-agent:free",
                       "b/tie-weak-agent:free", "a/low:free"]

    def test_none_intelligence_treated_as_unscored(self):
        """benchmark 条目存在但 intelligence_index 为 None → 视为无分。"""
        models = [
            _model("a/null-score:free", slug="a/null-1"),
            _model("b/scored:free", slug="b/scored-1"),
        ]
        bench = {"a/null-1": {"intelligence_index": None, "agentic_index": 1.1},
                 "b/scored-1": {"intelligence_index": 5.0, "agentic_index": 1.0}}
        ids = [m["id"] for m in rank_models(models, bench)]
        assert ids == ["b/scored:free", "a/null-score:free"]


class TestBuildFallbackEntries:
    def test_entry_shape(self):
        entries = build_fallback_entries([_model("a/x:free"), _model("b/y:free")],
                                         provider="custom_nex-n25",
                                         base_url="https://openrouter.ai/api/v1")
        assert entries == [
            {"provider": "custom_nex-n25",
             "base_url": "https://openrouter.ai/api/v1",
             "model": "a/x:free"},
            {"provider": "custom_nex-n25",
             "base_url": "https://openrouter.ai/api/v1",
             "model": "b/y:free"},
        ]


class TestSyncAvailableModels:
    def test_unions_with_existing(self):
        prov = {"available_models_json": [{"id": "a/x:free", "name": "a/x:free"}]}
        sync_available_models(prov, ["a/x:free", "b/y:free"])
        ids = [m["id"] for m in prov["available_models_json"]]
        assert ids == ["a/x:free", "b/y:free"]

    def test_noop_when_all_present(self):
        prov = {"available_models_json": [{"id": "a/x:free", "name": "a/x:free"}]}
        assert sync_available_models(prov, ["a/x:free"]) is False

    def test_creates_list_when_missing(self):
        prov = {}
        assert sync_available_models(prov, ["a/x:free"]) is True
        assert prov["available_models_json"] == [{"id": "a/x:free", "name": "a/x:free"}]


class TestApplyUpdates:
    def _cfg(self):
        return {
            "model": {"default": "nex-agi/nex-n2.5-pro:free"},
            "providers": {"custom_nex-n25": {
                "base_url": "https://openrouter.ai/api/v1",
                "available_models_json": [{"id": "nex-agi/nex-n2.5-pro:free",
                                           "name": "nex-agi/nex-n2.5-pro:free"}],
            }},
            "fallback_providers": [
                {"provider": "custom_glm", "base_url": "https://x", "model": "glm"},
                {"provider": "custom_nex-n25", "base_url": "https://openrouter.ai/api/v1",
                 "model": "old/stale:free"},
            ],
        }

    def test_replaces_managed_keeps_user_entries(self):
        cfg = self._cfg()
        changed = apply_updates(cfg, [_model("a/x:free"), _model("b/y:free")],
                                provider="custom_nex-n25")
        assert changed is True
        fb = cfg["fallback_providers"]
        # 用户自己的条目保留，受管条目整体替换并置于最前
        assert fb[0]["model"] == "a/x:free"
        assert fb[1]["model"] == "b/y:free"
        assert fb[2] == {"provider": "custom_glm", "base_url": "https://x", "model": "glm"}
        assert len(fb) == 3
        # default 也并入 provider 的可用模型列表
        ids = [m["id"] for m in cfg["providers"]["custom_nex-n25"]["available_models_json"]]
        assert ids == ["nex-agi/nex-n2.5-pro:free", "a/x:free", "b/y:free"]

    def test_idempotent(self):
        cfg = self._cfg()
        apply_updates(cfg, [_model("a/x:free")], provider="custom_nex-n25")
        assert apply_updates(cfg, [_model("a/x:free")], provider="custom_nex-n25") is False

    def test_missing_provider_raises(self):
        cfg = self._cfg()
        del cfg["providers"]["custom_nex-n25"]
        with pytest.raises(KeyError):
            apply_updates(cfg, [_model("a/x:free")], provider="custom_nex-n25")


class TestSelectFallbacks:
    """探测结果影响最终排序：probe-ok > 未探测 > probe-failed，组内保持传入顺序。"""

    def _ranked(self):
        return [_model("a/1:free"), _model("b/2:free"), _model("c/3:free"),
                _model("d/4:free"), _model("e/5:free")]

    def test_probe_failed_drops_to_bottom(self):
        from hermes_openrouter_free_fallback import select_fallbacks
        probes = {"b/2:free": {"ok": False, "status": 429},
                  "a/1:free": {"ok": True, "status": 200}}
        ids = [m["id"] for m in select_fallbacks(self._ranked(), probes, count=3)]
        assert ids == ["a/1:free", "c/3:free", "d/4:free"]

    def test_probe_ok_keep_intel_order(self):
        from hermes_openrouter_free_fallback import select_fallbacks
        probes = {"c/3:free": {"ok": True}, "a/1:free": {"ok": True}}
        ids = [m["id"] for m in select_fallbacks(self._ranked(), probes, count=2)]
        assert ids == ["a/1:free", "c/3:free"]

    def test_all_probes_failed_falls_back_to_intel_order(self):
        from hermes_openrouter_free_fallback import select_fallbacks
        probes = {"a/1:free": {"ok": False}, "b/2:free": {"ok": False},
                  "c/3:free": {"ok": False}, "d/4:free": {"ok": False},
                  "e/5:free": {"ok": False}}
        ids = [m["id"] for m in select_fallbacks(self._ranked(), probes, count=2)]
        assert ids == ["a/1:free", "b/2:free"]

    def test_prefer_lifts_within_ok_group(self):
        from hermes_openrouter_free_fallback import select_fallbacks
        probes = {"a/1:free": {"ok": True}, "b/2:free": {"ok": True}}
        ids = [m["id"] for m in select_fallbacks(self._ranked(), probes, count=2,
                                                 prefer=["b/2:free"])]
        assert ids == ["b/2:free", "a/1:free"]

    def test_prefer_does_not_rescue_failed(self):
        """置顶名单里的模型探测失败时照样沉底。"""
        from hermes_openrouter_free_fallback import select_fallbacks
        probes = {"b/2:free": {"ok": False}, "a/1:free": {"ok": True}}
        ids = [m["id"] for m in select_fallbacks(self._ranked(), probes, count=2,
                                                 prefer=["b/2:free"])]
        assert ids == ["a/1:free", "c/3:free"]


class TestProbeModel:
    def _fake_response(self):
        import io
        resp = io.BytesIO(b'{"choices":[{"message":{"content":"pong"}}]}')
        resp.status = 200
        resp.__enter__ = lambda s: s
        resp.__exit__ = lambda *a: False
        return resp

    def test_ok(self, monkeypatch):
        from hermes_openrouter_free_fallback import probe_model
        monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: self._fake_response())
        r = probe_model("https://x/v1", "sk-key", "a/x:free")
        assert r["ok"] is True and r["status"] == 200 and r["latency_ms"] >= 0

    def test_sends_agentic_harness_headers(self, monkeypatch):
        """部分免费模型按 harness gate（无 Referer 403），探测须模拟 Hermes。"""
        from hermes_openrouter_free_fallback import probe_model
        seen = {}

        def capture(req, *a, **k):
            seen.update(dict(req.header_items()))
            return self._fake_response()
        monkeypatch.setattr("urllib.request.urlopen", capture)
        probe_model("https://x/v1", "sk-key", "a/x:free")
        assert seen.get("Http-referer") == "https://hermes-agent.nousresearch.com"
        assert seen.get("X-title") == "Hermes Agent"

    def test_rate_limited(self, monkeypatch):
        import urllib.error
        from hermes_openrouter_free_fallback import probe_model

        def raise429(*a, **k):
            raise urllib.error.HTTPError("u", 429, "Too Many", {}, None)
        monkeypatch.setattr("urllib.request.urlopen", raise429)
        r = probe_model("https://x/v1", "sk-key", "a/x:free")
        assert r["ok"] is False and r["status"] == 429

    def test_network_error(self, monkeypatch):
        import urllib.error
        from hermes_openrouter_free_fallback import probe_model

        def raise_timeout(*a, **k):
            raise urllib.error.URLError("timed out")
        monkeypatch.setattr("urllib.request.urlopen", raise_timeout)
        r = probe_model("https://x/v1", "sk-key", "a/x:free")
        assert r["ok"] is False and r["status"] is None


class TestResolveApiKey:
    def test_from_env(self, monkeypatch):
        from hermes_openrouter_free_fallback import resolve_api_key
        monkeypatch.setenv("CUSTOM_NEX_N25_API_KEY", "sk-test")
        prov = {"key_env": "CUSTOM_NEX_N25_API_KEY"}
        assert resolve_api_key(prov) == "sk-test"

    def test_from_inline_api_key(self, monkeypatch):
        from hermes_openrouter_free_fallback import resolve_api_key
        monkeypatch.delenv("CUSTOM_NEX_N25_API_KEY", raising=False)
        assert resolve_api_key({"api_key": "sk-inline"}) == "sk-inline"

    def test_missing_returns_none(self, monkeypatch):
        from hermes_openrouter_free_fallback import resolve_api_key
        monkeypatch.delenv("CUSTOM_NEX_N25_API_KEY", raising=False)
        assert resolve_api_key({"key_env": "CUSTOM_NEX_N25_API_KEY"}) is None
