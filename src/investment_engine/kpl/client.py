"""KPL 私有 API HTTP 客户端（协议见 docs/design/kpl-api-inventory.md）。

UA 等请求头常量提取自 2026-08-10 抓包实样
（temp/kpl_capture/extracted_api/request_headers.txt）。
成功响应 errcode 为字符串 "0"；鉴权失败响应未实测过，按 msg 关键词尽力判定。
"""

from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request

API_URL = ("https://{subdomain}.longhuvip.com/w1/api/index.php"
           "?apiv=w47&PhoneOSNew=1&VerSion=6.2.20.5")

# 2026-08-10 抓包实样 UA（apphwhq 请求头，kaipanla 6.2.20.5）
USER_AGENT = ("Mozilla/5.0 (Linux; Android 16; 23116PN5BC Build/BP2A.250605.031.A3; wv) "
              "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/150.0.7871.181 "
              "Mobile Safari/537.36;kaipanla 6.2.20.5")

# 鉴权失败 msg 关键词（未实测，尽力判定；无法归类时统一 KplError）
AUTH_HINTS = ("登录", "登陆", "过期", "token", "Token")


class KplError(Exception):
    """KPL API 调用失败（网络重试耗尽 / 业务错误码）。"""


class KplAuthError(KplError):
    """鉴权失败（token 疑似失效），需按接口清单重新抓包。"""


class KplClient:
    """单入口 form 编码 POST；body 必带 UserID/Token/DeviceID。"""

    def __init__(self, user_id: str, token: str, device_id: str,
                 timeout: float = 10.0, retries: int = 2):
        self.user_id = user_id
        self.token = token
        self.device_id = device_id
        self.timeout = timeout
        self.retries = retries

    @classmethod
    def from_env(cls) -> "KplClient":
        """读 KPL_USER_ID/KPL_TOKEN/KPL_DEVICE_ID（大小写均可，沿用项目惯例）。"""

        def _get(name: str) -> str | None:
            return os.environ.get(name) or os.environ.get(name.lower())

        missing = [n for n in ("KPL_USER_ID", "KPL_TOKEN", "KPL_DEVICE_ID") if not _get(n)]
        if missing:
            raise KplError(f"缺少环境变量: {', '.join(missing)}"
                           f"（.env 需配置小写 kpl_user_id/kpl_token/kpl_device_id）")
        return cls(str(_get("KPL_USER_ID")), str(_get("KPL_TOKEN")),
                   str(_get("KPL_DEVICE_ID")))

    def post(self, subdomain: str, c: str, a: str, params: dict | None = None) -> dict:
        body = {"c": c, "a": a, "UserID": self.user_id, "Token": self.token,
                "DeviceID": self.device_id, **(params or {})}
        req = urllib.request.Request(
            API_URL.format(subdomain=subdomain),
            data=urllib.parse.urlencode(body).encode("utf-8"),
            headers={"User-Agent": USER_AGENT,
                     "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                     "Accept": "application/json"},
            method="POST")
        payload: dict | None = None
        last_err: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    payload = json.loads(resp.read().decode("utf-8"))
                break
            except Exception as e:  # 网络/HTTP/JSON 错误统一重试
                last_err = e
                if attempt < self.retries:
                    time.sleep(1.0 * (attempt + 1))
        if payload is None:
            raise KplError(f"POST {subdomain} c={c} a={a} 重试{self.retries}次后仍失败: {last_err}")
        errcode = str(payload.get("errcode", "0"))
        if errcode != "0":
            msg = str(payload.get("msg") or payload.get("Message") or "")
            if any(h in msg for h in AUTH_HINTS):
                raise KplAuthError(
                    f"鉴权失败 errcode={errcode} msg={msg}；token 疑似失效，"
                    f"按 docs/design/kpl-api-inventory.md 的 Reqable 流程重抓")
            raise KplError(f"业务错误 errcode={errcode} msg={msg} (c={c} a={a})")
        return payload
