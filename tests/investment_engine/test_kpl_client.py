"""kpl/client.py 单元测试（mock transport，不碰真实网络）。"""

from __future__ import annotations

import json
import urllib.parse
from unittest import mock

import pytest

from investment_engine.kpl.client import (
    API_URL,
    KplAuthError,
    KplClient,
    KplError,
)


def _fake_response(payload: dict):
    resp = mock.MagicMock()
    resp.read.return_value = json.dumps(payload).encode("utf-8")
    resp.__enter__.return_value = resp
    return resp


class TestFromEnv:
    @pytest.fixture(autouse=True)
    def _clean_env(self, monkeypatch):
        for name in ("KPL_USER_ID", "kpl_user_id", "KPL_TOKEN", "kpl_token",
                     "KPL_DEVICE_ID", "kpl_device_id"):
            monkeypatch.delenv(name, raising=False)

    def test_missing_env_raises(self):
        with pytest.raises(KplError, match="缺少环境变量"):
            KplClient.from_env()

    def test_lowercase_env_accepted(self, monkeypatch):
        monkeypatch.setenv("kpl_user_id", "u1")
        monkeypatch.setenv("kpl_token", "t1")
        monkeypatch.setenv("kpl_device_id", "d1")
        client = KplClient.from_env()
        assert (client.user_id, client.token, client.device_id) == ("u1", "t1", "d1")


class TestPost:
    def test_url_body_headers(self):
        client = KplClient("u", "t", "d")
        with mock.patch("urllib.request.urlopen",
                        return_value=_fake_response({"errcode": "0", "X": 1})) as m:
            out = client.post("apphwhq", "Index", "GetInfo", {"View": "3"})
        assert out["X"] == 1
        req = m.call_args[0][0]
        assert req.full_url == API_URL.format(subdomain="apphwhq")
        body = urllib.parse.parse_qs(req.data.decode("utf-8"))
        assert body["c"] == ["Index"] and body["a"] == ["GetInfo"]
        assert body["UserID"] == ["u"] and body["Token"] == ["t"]
        assert body["DeviceID"] == ["d"] and body["View"] == ["3"]
        assert "kaipanla" in req.get_header("User-agent")
        # H5 头必须带（收盘后 GetInfo 无此头会降级为空信息流）
        assert req.get_header("Referer") == "https://apppage.longhuvip.com/"
        assert req.get_header("X-requested-with") == "com.aiyu.kaipanla"

    def test_business_error(self):
        client = KplClient("u", "t", "d", retries=0)
        payload = {"errcode": "100", "msg": "bad param"}
        with mock.patch("urllib.request.urlopen", return_value=_fake_response(payload)):
            with pytest.raises(KplError, match="100"):
                client.post("apphwhq", "Index", "GetInfo")

    def test_auth_error_mapped(self):
        client = KplClient("u", "t", "d", retries=0)
        payload = {"errcode": "401", "msg": "登录已过期"}
        with mock.patch("urllib.request.urlopen", return_value=_fake_response(payload)):
            with pytest.raises(KplAuthError):
                client.post("apphwhq", "Index", "GetInfo")

    def test_retry_exhausted_raises(self):
        client = KplClient("u", "t", "d", retries=1)
        with mock.patch("urllib.request.urlopen", side_effect=OSError("boom")), \
                mock.patch("time.sleep"):
            with pytest.raises(KplError, match="重试"):
                client.post("apphwhq", "Index", "GetInfo")
