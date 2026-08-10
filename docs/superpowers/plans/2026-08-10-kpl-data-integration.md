# KPL 数据接入（情绪+资讯）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 每日收盘后自动拉取 KPL（开盘啦）情绪快照与当日资讯全文，JSON/Markdown 落盘到 `infra/data/kpl/`。

**Architecture:** `src/investment_engine/kpl/` 三模块（client/emotion/news）+ `scripts/kpl_daily_fetch.py` thin 入口 + crontab 15:45。协议与接口细节见 `docs/design/kpl-api-inventory.md`，设计决策见 spec `docs/superpowers/specs/2026-08-10-kpl-data-integration-design.md`。

**Tech Stack:** 纯 stdlib（`urllib.request` / `html.parser`），pytest（`pythonpath=["src","."]` 已在 pyproject 配置）。

**执行约定（用户已授权/约束）：**
- 在 **master** 分支执行（KPL 系列文档均在 master）；逐任务 commit，不主动 push。
- 不用 subagent；不改 `src/qing_investment/`；tests 子目录不放 `__init__.py`；统一用 `.venv/bin/pytest`。
- **与 spec 的一处偏差（已核对仓库惯例）**：测试文件放 `tests/investment_engine/test_kpl_*.py`
  （investment_engine 模块的测试都集中在此子目录），不写 spec 里的扁平路径；spec 文档随本计划同 commit 修正。
- 测试实样来自真实抓包（2026-08-10 盘中，`temp/kpl_capture/extracted_api/`，该目录 gitignore）。

**关键实样事实（写代码前必读，纠正清单文档的两处臆测）：**
- `FKYDSixList` 是 **object 列表**：`{"StockID","StockName","zhangfu"}`，不是数组。
- `CWeatherVaneList` 是 **object**：`{"SZ": [[代码,名称,涨幅,板块]...], "XD": [...]}`（SZ=涨风向，XD=跌风向）。
- 成功响应 `errcode` 是**字符串** `"0"`；`DaBanList` 字段全为数字；`Day` 形如 `"2026-08-10"`。
- 不同 View 组合返回的块不同（周日样例有 `ErBanList`、盘中全量样例没有）——解析必须容忍缺块。
- 请求头实样（H5 变体，对 API 端点可用）已提取到 `temp/kpl_capture/extracted_api/request_headers.txt`，
  UA 常量：`Mozilla/5.0 (Linux; Android 16; 23116PN5BC Build/BP2A.250605.031.A3; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/150.0.7871.181 Mobile Safari/537.36;kaipanla 6.2.20.5`
- 资讯列表 `MsgTop.List[]`：`ID`(str)/`Title`/`ZhaiYao`/`Type`/`MsgType`(int)/`CreateTime`(str unix 本地时区)；
  全文 `Msg`：`ID`(int)/`Title`/`CreateTime`(int)/`MsgType`/`Stock[]`/`imgList[]`/`Content`(HTML)。

---

### Task 1: kpl 包骨架 + client.py（HTTP 层）

**Files:**
- Create: `src/investment_engine/kpl/__init__.py`
- Create: `src/investment_engine/kpl/client.py`
- Test: `tests/investment_engine/test_kpl_client.py`

- [ ] **Step 1: 写失败测试**

创建 `tests/investment_engine/test_kpl_client.py`：

```python
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
```

- [ ] **Step 2: 跑测试确认失败**

```bash
.venv/bin/pytest tests/investment_engine/test_kpl_client.py -v
```

预期：collection 阶段 `ModuleNotFoundError: No module named 'investment_engine.kpl'`。

- [ ] **Step 3: 实现包骨架与 client**

创建 `src/investment_engine/kpl/__init__.py`：

```python
"""KPL（开盘啦）私有 API 数据接入：情绪快照 + 资讯流。仅限个人研究用途。"""
```

创建 `src/investment_engine/kpl/client.py`：

```python
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
```

- [ ] **Step 4: 跑测试确认通过**

```bash
.venv/bin/pytest tests/investment_engine/test_kpl_client.py -v
```

预期：5 passed。

- [ ] **Step 5: Commit**

```bash
git add src/investment_engine/kpl/ tests/investment_engine/test_kpl_client.py
git commit -m "feat(kpl): HTTP 客户端——单入口 form POST + env 鉴权 + 错误分级"
```

---

### Task 2: emotion.py（情绪快照）

**Files:**
- Create: `src/investment_engine/kpl/emotion.py`
- Test: `tests/investment_engine/test_kpl_emotion.py`

- [ ] **Step 1: 写失败测试**

创建 `tests/investment_engine/test_kpl_emotion.py`（样本为 2026-08-10 盘中实样裁剪）：

```python
"""kpl/emotion.py 单元测试（实样裁剪自 2026-08-10 盘中抓包）。"""

from __future__ import annotations

import json

from investment_engine.kpl.emotion import fetch_snapshot, save_snapshot

# 真实响应裁剪：注意 FKYDSixList 是 object 列表、CWeatherVaneList 是 {SZ,XD}、
# 本样例无 ErBanList（验证缺块容忍）。errcode 已被 client 层消费，这里模拟 client 返回。
SAMPLE = {
    "BaceFaceList": [["医药", "0.96", 801045], ["并购重组", "0.44", 801250]],
    "FKYDSixList": [{"StockID": "300654", "StockName": "世纪天鸿", "zhangfu": "3.54%"}],
    "DaBanList": {"tZhangTing": 76, "lZhangTing": 74, "tFengBan": 85.3933,
                  "tDieTing": 5, "SZJS": 3470, "XDJS": 1965, "PPJS": 103,
                  "ZHQD": 60, "ZRZTJ": 0.294, "ZRLBJ": -0.532},
    "CWeatherVaneList": {"SZ": [["001258", "立新能源", 10.03, "绿色电力"]],
                         "XD": [["301251", "威尔高", -9.42, "印制电路板"]]},
    "PHBList": [["600721", "百花医药", 9.96, 1, "5连板", "医药", "医药;2|5连板;1"]],
    "Day": "2026-08-10",
    "errcode": "0",
}


class _FakeClient:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def post(self, subdomain, c, a, params=None):
        self.calls.append((subdomain, c, a, params))
        return self.payload


def test_fetch_snapshot_blocks_and_view():
    client = _FakeClient(SAMPLE)
    data = fetch_snapshot(client)
    # 全量 View 一次拉取
    assert client.calls == [("apphwhq", "Index", "GetInfo",
                             {"View": "2,3,4,5,7,8,9,10,11"})]
    assert data["date"] == "2026-08-10"
    assert data["fetched_at"]
    assert data["daban"]["tZhangTing"] == 76
    assert data["daban"]["tFengBan"] == 85.3933
    assert data["lianban"][0][4] == "5连板"
    assert data["erban"] == []  # 缺块给空列表
    assert data["fengkou"][0]["StockID"] == "300654"  # object 列表原样保留
    assert data["bankuai"][0] == ["医药", "0.96", 801045]
    assert data["fengxiang"]["SZ"][0][1] == "立新能源"  # {SZ,XD} 原样保留


def test_save_snapshot(tmp_path):
    data = {"date": "2026-08-10", "fetched_at": "2026-08-10T15:45:02",
            "daban": {"tZhangTing": 76}, "lianban": [], "erban": [],
            "fengkou": [], "bankuai": [], "fengxiang": {}}
    path = save_snapshot(data, tmp_path, "2026-08-10")
    assert path == tmp_path / "emotion" / "2026-08-10.json"
    loaded = json.loads(path.read_text())
    assert loaded == data  # 完整往返；ensure_ascii=False 中文不转义
```

- [ ] **Step 2: 跑测试确认失败**

```bash
.venv/bin/pytest tests/investment_engine/test_kpl_emotion.py -v
```

预期：`ModuleNotFoundError: No module named 'investment_engine.kpl.emotion'`（Task 1 已建包，报的是 emotion 模块缺失）。

- [ ] **Step 3: 实现 emotion.py**

创建 `src/investment_engine/kpl/emotion.py`：

```python
"""情绪快照：Index.GetInfo 全量 View 一次拉取 + 落盘。

六个块保留 API 原始结构（不过度归一化）：DaBanList=object、PHBList/ErBanList/
BaceFaceList=数组列表、FKYDSixList=object 列表、CWeatherVaneList={SZ,XD}。
不同 View 组合返回块不同，缺块给空默认值。
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

from investment_engine.kpl.client import KplClient

FULL_VIEW = "2,3,4,5,7,8,9,10,11"

# 响应块名 → (落盘 key, 缺块默认值)
BLOCKS = {
    "DaBanList": ("daban", dict),
    "PHBList": ("lianban", list),
    "ErBanList": ("erban", list),
    "FKYDSixList": ("fengkou", list),
    "BaceFaceList": ("bankuai", list),
    "CWeatherVaneList": ("fengxiang", dict),
}


def fetch_snapshot(client: KplClient) -> dict:
    """拉取全量情绪快照，返回 {date, fetched_at, 六个块}。"""
    resp = client.post("apphwhq", "Index", "GetInfo", {"View": FULL_VIEW})
    out = {
        "date": resp.get("Day") or date.today().isoformat(),
        "fetched_at": datetime.now().isoformat(timespec="seconds"),
    }
    for src_key, (dst_key, default_factory) in BLOCKS.items():
        val = resp.get(src_key)
        out[dst_key] = val if val is not None else default_factory()
    return out


def save_snapshot(data: dict, out_root: Path, day: str) -> Path:
    """写 <out_root>/emotion/<day>.json（ensure_ascii=False 便于人工审阅）。"""
    out_dir = Path(out_root) / "emotion"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{day}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return path
```

- [ ] **Step 4: 跑测试确认通过**

```bash
.venv/bin/pytest tests/investment_engine/test_kpl_emotion.py -v
```

预期：2 passed。

- [ ] **Step 5: Commit**

```bash
git add src/investment_engine/kpl/emotion.py tests/investment_engine/test_kpl_emotion.py
git commit -m "feat(kpl): 情绪快照拉取与落盘——六块原样保留，容忍缺块"
```

---

### Task 3: news.py（资讯流）

**Files:**
- Create: `src/investment_engine/kpl/news.py`
- Test: `tests/investment_engine/test_kpl_news.py`

- [ ] **Step 1: 写失败测试**

创建 `tests/investment_engine/test_kpl_news.py`：

```python
"""kpl/news.py 单元测试（实样裁剪自抓包；时间戳动态构造避免时区陷阱）。"""

from __future__ import annotations

import json
from datetime import date, datetime

from investment_engine.kpl.news import (
    fetch_day_news,
    fetch_list,
    html_to_text,
    save_news,
)

DAY = date(2026, 8, 10)


def _ts(d: date, hour: int) -> str:
    return str(int(datetime(d.year, d.month, d.day, hour).timestamp()))


def _list_payload(items):
    return {"MsgTop": {"List": items}, "errcode": "0"}


class _FakeClient:
    """按 (c, a) 分发：GetIndexList 返列表，ForumsMsgJX.GetInfo 返全文。"""

    def __init__(self, list_payload, full_by_id=None):
        self.list_payload = list_payload
        self.full_by_id = full_by_id or {}
        self.calls = []

    def post(self, subdomain, c, a, params=None):
        self.calls.append((subdomain, c, a, params))
        if a == "GetIndexList":
            return self.list_payload
        return {"Msg": self.full_by_id[params["MsgID"]], "errcode": "0"}


def test_html_to_text_strips_tags_and_collects_images():
    html = ('<p><strong>公司简介：</strong>宇树科技成立于2016年</p>'
            '<p><img src="https://appcdn.longhuvip.com/a.png" alt="image.png"/></p>'
            '<p>第二段</p>')
    text, images = html_to_text(html)
    assert "公司简介：宇树科技成立于2016年" in text
    assert "第二段" in text
    assert "<p>" not in text and "<strong>" not in text
    assert images == ["https://appcdn.longhuvip.com/a.png"]


def test_fetch_list_filters_by_day():
    items = [
        {"ID": "1", "Title": "当日", "CreateTime": _ts(DAY, 10)},
        {"ID": "2", "Title": "昨日", "CreateTime": _ts(date(2026, 8, 9), 10)},
        {"ID": "3", "Title": "无时间"},  # 缺 CreateTime 跳过
    ]
    client = _FakeClient(_list_payload(items))
    out = fetch_list(client, DAY)
    assert [i["ID"] for i in out] == ["1"]
    assert client.calls[0][:3] == ("apparticle", "IndexPlate", "GetIndexList")
    assert client.calls[0][3] == {"view": "1,2,3,4,6", "st": "2", "Type": "0"}


def test_fetch_day_news_pulls_full_text_per_item():
    items = [{"ID": "42", "Title": "t", "CreateTime": _ts(DAY, 9)},
             {"ID": "43", "Title": "t2", "CreateTime": _ts(DAY, 11)}]
    full = {"42": {"ID": 42, "Title": "t", "Content": "<p>a</p>"},
            "43": {"ID": 43, "Title": "t2", "Content": "<p>b</p>"}}
    client = _FakeClient(_list_payload(items), full)
    articles = fetch_day_news(client, DAY, pause=0)
    assert [a["ID"] for a in articles] == [42, 43]
    # 列表 1 次 + 全文 2 次
    assert [c[2] for c in client.calls].count("GetInfo") == 2


def test_save_news_layout(tmp_path):
    articles = [{
        "ID": 42174, "Title": "新股分析：宇树科技、绿控传动",
        "CreateTime": 1786266426, "MsgType": 18, "Stock": [],
        "imgList": ["https://appcdn.longhuvip.com/x.jpg", ""],
        "Content": "<p><strong>新股亮点</strong></p><p>正文</p>",
    }]
    out_dir = save_news(articles, tmp_path, "2026-08-10")
    assert out_dir == tmp_path / "news" / "2026-08-10"
    index = json.loads((out_dir / "index.json").read_text())
    assert index[0]["id"] == 42174
    assert index[0]["img_list"] == ["https://appcdn.longhuvip.com/x.jpg"]  # 空串被过滤
    md = (out_dir / "42174.md").read_text()
    assert md.startswith("---\n")
    assert 'title: "新股分析：宇树科技、绿控传动"' in md
    assert "# 新股分析：宇树科技、绿控传动" in md
    assert "新股亮点" in md and "<strong>" not in md
```

- [ ] **Step 2: 跑测试确认失败**

```bash
.venv/bin/pytest tests/investment_engine/test_kpl_news.py -v
```

预期：`ModuleNotFoundError: No module named 'investment_engine.kpl.news'`。

- [ ] **Step 3: 实现 news.py**

创建 `src/investment_engine/kpl/news.py`：

```python
"""资讯流：IndexPlate.GetIndexList 列表（按日过滤）+ ForumsMsgJX.GetInfo 全文 + 落盘。

已知限制：列表只拉单页（观察到的 st=2 组合一页覆盖多日，日常够用）；
若某日资讯超过一页可能漏，后续对照 App 再补分页。
"""

from __future__ import annotations

import json
import re
import time
from datetime import date, datetime
from html.parser import HTMLParser
from pathlib import Path

from investment_engine.kpl.client import KplClient

LIST_PARAMS = {"view": "1,2,3,4,6", "st": "2", "Type": "0"}


class _TextExtractor(HTMLParser):
    """极简 HTML→纯文本：丢标签留文本，段落标签换行，img 收集 src。"""

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.images: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "img":
            src = dict(attrs).get("src")
            if src:
                self.images.append(src)
        if tag in ("p", "br", "div", "li", "tr"):
            self.parts.append("\n")

    def handle_data(self, data):
        self.parts.append(data)

    def text(self) -> str:
        raw = "".join(self.parts)
        raw = re.sub(r"[ \t\r\f\v]+", " ", raw)
        return re.sub(r"\n\s*\n+", "\n\n", raw).strip()


def html_to_text(html: str) -> tuple[str, list[str]]:
    """返回 (纯文本, 正文 img src 列表)。"""
    parser = _TextExtractor()
    parser.feed(html or "")
    return parser.text(), parser.images


def fetch_list(client: KplClient, day: date) -> list[dict]:
    """拉列表并按 CreateTime（本地时区 unix）过滤出 day 当日条目。"""
    resp = client.post("apparticle", "IndexPlate", "GetIndexList", LIST_PARAMS)
    items = (resp.get("MsgTop") or {}).get("List") or []
    out = []
    for it in items:
        ts = it.get("CreateTime")
        if not ts:
            continue
        if datetime.fromtimestamp(int(ts)).date() == day:
            out.append(it)
    return out


def fetch_full(client: KplClient, msg_id) -> dict:
    resp = client.post("apparticle", "ForumsMsgJX", "GetInfo",
                       {"MsgID": str(msg_id), "Tag": "1"})
    return resp.get("Msg") or {}


def fetch_day_news(client: KplClient, day: date, pause: float = 0.5) -> list[dict]:
    """列表过滤当日 → 逐篇拉全文（篇间 pause 秒，降低风控暴露）。"""
    articles = []
    for item in fetch_list(client, day):
        articles.append(fetch_full(client, item["ID"]))
        time.sleep(pause)
    return articles


def save_news(articles: list[dict], out_root: Path, day: str) -> Path:
    """写 <out_root>/news/<day>/：index.json（meta 列表）+ 每篇 <ID>.md（frontmatter+正文）。"""
    out_dir = Path(out_root) / "news" / day
    out_dir.mkdir(parents=True, exist_ok=True)
    index = []
    for art in articles:
        text, content_images = html_to_text(art.get("Content") or "")
        img_list = [u for u in (art.get("imgList") or []) if u] or content_images
        meta = {
            "id": art.get("ID"),
            "title": art.get("Title") or "",
            "create_time": art.get("CreateTime"),
            "msg_type": art.get("MsgType"),
            "stocks": art.get("Stock") or [],
            "img_list": img_list,
        }
        frontmatter = "---\n" + "\n".join(
            f"{k}: {json.dumps(v, ensure_ascii=False)}" for k, v in meta.items()
        ) + "\n---\n\n"
        (out_dir / f"{meta['id']}.md").write_text(
            frontmatter + f"# {meta['title']}\n\n" + text + "\n", encoding="utf-8")
        index.append(meta)
    (out_dir / "index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return out_dir
```

- [ ] **Step 4: 跑测试确认通过**

```bash
.venv/bin/pytest tests/investment_engine/test_kpl_news.py -v
```

预期：4 passed。

- [ ] **Step 5: Commit**

```bash
git add src/investment_engine/kpl/news.py tests/investment_engine/test_kpl_news.py
git commit -m "feat(kpl): 资讯流——列表按日过滤 + 全文 HTML 转纯文本落盘"
```

---

### Task 4: scripts/kpl_daily_fetch.py（thin 入口）

**Files:**
- Create: `scripts/kpl_daily_fetch.py`
- Test: `tests/investment_engine/test_kpl_daily_fetch.py`

- [ ] **Step 1: 写失败测试**

创建 `tests/investment_engine/test_kpl_daily_fetch.py`：

```python
"""kpl_daily_fetch.py 入口编排测试（monkeypatch 掉网络层）。"""

from __future__ import annotations

import json

import pytest

from investment_engine.kpl.client import KplAuthError
from scripts import kpl_daily_fetch


@pytest.fixture
def fake_layers(monkeypatch):
    monkeypatch.setattr(kpl_daily_fetch.KplClient, "from_env",
                        classmethod(lambda cls: object()))
    monkeypatch.setattr(kpl_daily_fetch.emotion, "fetch_snapshot",
                        lambda client: {"date": "2026-08-10",
                                        "fetched_at": "2026-08-10T15:45:02",
                                        "daban": {"tZhangTing": 76, "tFengBan": 85.4},
                                        "lianban": [["600721", "百花医药", 9.96, 1,
                                                     "5连板", "医药", "医药;2"]],
                                        "erban": [], "fengkou": [], "bankuai": [],
                                        "fengxiang": {}})
    monkeypatch.setattr(kpl_daily_fetch.news, "fetch_day_news",
                        lambda client, day: [{"ID": 1, "Title": "t", "CreateTime": 1,
                                              "MsgType": 5, "Stock": [], "imgList": [],
                                              "Content": "<p>x</p>"}])


def test_run_success_and_idempotent(tmp_path, capsys, fake_layers):
    argv = ["--date", "2026-08-10", "--out-root", str(tmp_path)]
    assert kpl_daily_fetch.main(argv) == 0
    emotion_file = tmp_path / "emotion" / "2026-08-10.json"
    news_index = tmp_path / "news" / "2026-08-10" / "index.json"
    assert emotion_file.exists() and news_index.exists()
    assert json.loads(emotion_file.read_text())["daban"]["tZhangTing"] == 76
    # 第二次运行幂等跳过
    assert kpl_daily_fetch.main(argv) == 0
    assert "跳过" in capsys.readouterr().out


def test_auth_error_exit_code(tmp_path, monkeypatch, capsys, fake_layers):
    def _boom(client):
        raise KplAuthError("登录已过期")

    monkeypatch.setattr(kpl_daily_fetch.emotion, "fetch_snapshot", _boom)
    rc = kpl_daily_fetch.main(["--date", "2026-08-10", "--out-root", str(tmp_path)])
    assert rc == 3
    assert "登录已过期" in capsys.readouterr().err
```

- [ ] **Step 2: 跑测试确认失败**

```bash
.venv/bin/pytest tests/investment_engine/test_kpl_daily_fetch.py -v
```

预期：`ModuleNotFoundError: No module named 'scripts.kpl_daily_fetch'`。

- [ ] **Step 3: 实现入口脚本**

创建 `scripts/kpl_daily_fetch.py`：

```python
#!/usr/bin/env python
"""KPL 每日拉取入口（cron 工作日 15:45 调用）：情绪快照 + 当日资讯全文。

幂等：当日目标文件已存在则跳过对应部分，--force 覆盖重拉。
退出码：0 成功；1 拉取失败；2 配置缺失；3 鉴权失败（token 疑似失效，需重抓）。

手动: set -a && source .env && set +a && .venv/bin/python scripts/kpl_daily_fetch.py
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from investment_engine.kpl import emotion, news
from investment_engine.kpl.client import KplAuthError, KplClient, KplError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="KPL 每日数据拉取")
    parser.add_argument("--date", default=date.today().isoformat())
    parser.add_argument("--out-root", default="infra/data/kpl")
    parser.add_argument("--skip-emotion", action="store_true")
    parser.add_argument("--skip-news", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)

    day = datetime.strptime(args.date, "%Y-%m-%d").date()
    out_root = Path(args.out_root)
    try:
        client = KplClient.from_env()
    except KplError as e:
        print(f"[kpl] 配置错误: {e}", file=sys.stderr)
        return 2

    try:
        if not args.skip_emotion:
            target = out_root / "emotion" / f"{args.date}.json"
            if target.exists() and not args.force:
                print(f"[kpl] 情绪快照已存在，跳过: {target}")
            else:
                data = emotion.fetch_snapshot(client)
                path = emotion.save_snapshot(data, out_root, args.date)
                daban = data.get("daban") or {}
                print(f"[kpl] 情绪快照 → {path}  涨停={daban.get('tZhangTing')}"
                      f" 封板率={daban.get('tFengBan')}"
                      f" 连板数={len(data.get('lianban') or [])}")
        if not args.skip_news:
            target = out_root / "news" / args.date / "index.json"
            if target.exists() and not args.force:
                print(f"[kpl] 资讯已存在，跳过: {target.parent}")
            else:
                articles = news.fetch_day_news(client, day)
                out_dir = news.save_news(articles, out_root, args.date)
                print(f"[kpl] 资讯 → {out_dir}  共 {len(articles)} 篇")
    except KplAuthError as e:
        print(f"[kpl] {e}", file=sys.stderr)
        return 3
    except KplError as e:
        print(f"[kpl] 拉取失败: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: 跑测试确认通过**

```bash
.venv/bin/pytest tests/investment_engine/test_kpl_daily_fetch.py -v
```

预期：2 passed。随后跑全量 KPL 测试 + 既有 investment_engine 测试确认无回归：

```bash
.venv/bin/pytest tests/investment_engine/ -q
```

预期：全部 passed（KPL 新增 14 个 + 既有全绿）。

- [ ] **Step 5: Commit**

```bash
git add scripts/kpl_daily_fetch.py tests/investment_engine/test_kpl_daily_fetch.py
git commit -m "feat(kpl): 每日拉取入口——幂等 + 退出码分级 + 摘要输出"
```

---

### Task 5: .env 注入 token + 真实拉取验证（手动验收）

**Files:**
- Modify: `.env`（追加三个 key；gitignored，不进 commit）
- Create（临时，不入库）: `temp/kpl_capture/inject_env.py`

- [ ] **Step 1: 写提取脚本（token 不进对话、不进 git）**

创建 `temp/kpl_capture/inject_env.py`：

```python
"""从抓包文件提取 UserID/Token/DeviceID 追加进 .env（只打印脱敏确认）。

用法: python3 temp/kpl_capture/inject_env.py（mitmproxy 装在系统 Python，不在 .venv）
"""
import re
import urllib.parse
from pathlib import Path

from mitmproxy.io import FlowReader

ROOT = Path(__file__).resolve().parent.parent.parent
ENV = ROOT / ".env"
FLOWS = sorted((ROOT / "temp/kpl_capture").glob("kpl-flows-20260810*.mitm"))

found = {}
for f in FLOWS:
    with open(f, "rb") as fh:
        for flow in FlowReader(fh).stream():
            if not hasattr(flow, "request"):
                continue
            if "longhuvip" not in flow.request.pretty_host:
                continue
            params = urllib.parse.parse_qs(
                urllib.parse.urlsplit(flow.request.pretty_url).query)
            params.update(urllib.parse.parse_qs(
                flow.request.get_text(strict=False) or ""))
            if all(k in params for k in ("UserID", "Token", "DeviceID")):
                found = {k: params[k][0] for k in ("UserID", "Token", "DeviceID")}
    if found:
        break

assert found and re.fullmatch(r"[0-9a-f]{32}", found["Token"]), "未抓到有效 token"

existing = ENV.read_text() if ENV.exists() else ""
lines = []
for k, env_k in (("UserID", "kpl_user_id"), ("Token", "kpl_token"),
                 ("DeviceID", "kpl_device_id")):
    if re.search(rf"^{env_k}=", existing, re.M):
        print(f"{env_k} 已存在，跳过")
    else:
        lines.append(f"{env_k}={found[k]}")
if lines:
    with ENV.open("a") as fh:
        fh.write("\n# KPL 开盘啦（2026-08-10 抓包注入，失效需重抓，见 docs/design/kpl-api-inventory.md）\n")
        fh.write("\n".join(lines) + "\n")
print(f"完成：UserID={found['UserID']} Token={found['Token'][:6]}... DeviceID={found['DeviceID'][:8]}...")
```

运行（mitmproxy 装在系统 Python，不在 .venv，用系统 python3；若无 mitmproxy 模块则
改用 `mitmdump -nr <flows> -s <打印脚本>` 方式提取后手工追加——届时以实际报错为准调整）：

```bash
python3 -c "import mitmproxy" 2>/dev/null && python3 temp/kpl_capture/inject_env.py || echo "NEED_FALLBACK"
```

预期输出：`完成：UserID=6925216 Token=xxxxxx... DeviceID=xxxxxxxx...`（或部分 key 提示已存在）。
若输出 `NEED_FALLBACK`，用 mitmdump 脚本方式提取（参照 temp/kpl_capture/ 里现有脚本模式），
提取值通过 `read -s` 等方式写入 .env，全程不在终端回显完整 token。

- [ ] **Step 2: 真实拉取（今天 2026-08-10 已收盘，数据为当日终态）**

```bash
set -a && source .env && set +a && .venv/bin/python scripts/kpl_daily_fetch.py
```

预期输出形如：

```
[kpl] 情绪快照 → infra/data/kpl/emotion/2026-08-10.json  涨停=76 封板率=85.3933 连板数=N
[kpl] 资讯 → infra/data/kpl/news/2026-08-10  共 M 篇
```

- [ ] **Step 3: 人工核对落盘内容**

```bash
.venv/bin/python -c "
import json
d = json.load(open('infra/data/kpl/emotion/2026-08-10.json'))
print('块:', sorted(d.keys()))
print('daban 字段数:', len(d['daban']), '连板条数:', len(d['lianban']))
"
ls infra/data/kpl/news/2026-08-10/ | head -5
head -12 "$(ls infra/data/kpl/news/2026-08-10/*.md | head -1)"
```

预期：情绪 JSON 六块齐全（erban 盘中后可能非空）；md 文件 frontmatter + 可读正文。
与 App 对照：涨停数/封板率与 App 首页「打板情绪」一致。

- [ ] **Step 4: 本任务无 commit**

`.env` 与 `infra/data/` 均 gitignored；`temp/kpl_capture/` 整体 gitignored。确认无泄漏：

```bash
git status --short | grep -E '\.env|kpl_capture|infra/data' && echo "泄漏!" || echo "OK 无敏感文件入暂存"
```

---

### Task 6: crontab 挂载 + ops 文档更新

**Files:**
- Modify: `docs/tasks/kline-daily-fetch-ops.md`
- Modify: 本机 crontab（非仓库文件）

- [ ] **Step 1: 挂 crontab（15:45，接在 15:35 pre_fetch / 15:40 shadow 之后）**

```bash
crontab -l > /tmp/kpl_cron_backup.txt && cat /tmp/kpl_cron_backup.txt  # 先备份现样
(crontab -l; echo '45 15 * * 1-5 cd /Users/cong.zhou/Documents/quantitative/learning-investment-strategies && set -a && source .env && set +a && .venv/bin/python scripts/kpl_daily_fetch.py >> log/kpl_daily_fetch.log 2>&1') | crontab -
crontab -l | grep kpl_daily_fetch
```

预期：最后一行输出新挂载的 kpl_daily_fetch 任务。

- [ ] **Step 2: 更新 ops 文档**

修改 `docs/tasks/kline-daily-fetch-ops.md`：

- 「现状」节新增第三条：

````markdown
- **本机 crontab 另有 KPL 每日拉取任务**（2026-08-10 随 KPL 接入挂接）：
  ```
  45 15 * * 1-5 cd /Users/cong.zhou/Documents/quantitative/learning-investment-strategies && set -a && source .env && set +a && .venv/bin/python scripts/kpl_daily_fetch.py >> log/kpl_daily_fetch.log 2>&1
  ```
  工作日 15:45（shadow 之后 5 分钟）拉 KPL 情绪快照+当日资讯全文，落盘
  `infra/data/kpl/`（gitignored）。依赖 `.env` 的 `kpl_user_id/kpl_token/kpl_device_id`；
  token 失效时脚本退出码 3，日志有重抓指引（`docs/design/kpl-api-inventory.md`）。
````

- 「注销义务」节的 grep 模式改为：

```bash
crontab -l | grep -v 'pre_fetch_klines\|shadow_daily\|kpl_daily_fetch' | crontab -
```

- 「相关变更」节追加：

```markdown
- 2026-08-10：新增 KPL 每日拉取（15:45）；设计与接口见
  `docs/superpowers/specs/2026-08-10-kpl-data-integration-design.md`、
  `docs/design/kpl-api-inventory.md`。
```

- [ ] **Step 3: Commit**

```bash
git add docs/tasks/kline-daily-fetch-ops.md
git commit -m "docs(ops): KPL 每日拉取入 cron 登记与注销义务"
```

---

### Task 7: 收尾——全量测试 + spec 路径修正 + 计划勾选

**Files:**
- Modify: `docs/superpowers/specs/2026-08-10-kpl-data-integration-design.md`（测试路径对齐）
- Modify: 本计划文件（勾掉已完成的 checkbox）

- [ ] **Step 1: spec 测试路径修正**

把 spec 中「架构」树的三个测试文件路径与「测试」节的三处文件名从
`tests/test_kpl_*.py` 改为 `tests/investment_engine/test_kpl_*.py`，pytest 命令同步改。

- [ ] **Step 2: 全量测试**

```bash
.venv/bin/pytest tests/investment_engine/ -q
```

预期：全绿（含 KPL 新增 14 个用例）。

- [ ] **Step 3: 勾掉本计划已完成项并 commit**

```bash
git add docs/superpowers/specs/2026-08-10-kpl-data-integration-design.md docs/superpowers/plans/2026-08-10-kpl-data-integration.md
git commit -m "docs(kpl): 实施计划勾选完成 + spec 测试路径对齐仓库惯例"
```

---

## Self-Review 记录（计划落盘前已执行）

- **Spec 覆盖**：client/emotion/news/入口/cron/token/验收 → T1-T6 全覆盖；
  风险合规在 spec 已声明，计划 T5 用「token 不进对话不进 git」落实。
- **占位符**：无 TBD/TODO；所有代码完整给出。
- **类型一致**：`fetch_snapshot/save_snapshot(data, out_root, day)`、
  `fetch_list(client, day)`、`fetch_day_news(client, day, pause)`、
  `save_news(articles, out_root, day)`、`KplClient.post(subdomain, c, a, params)`、
  `main(argv)` 在测试与实现中签名一致；异常层级 `KplAuthError(KplError)` 一致。
- **已知限制如实标注**：资讯单页可能漏（news.py docstring）；鉴权失败特征未实测
  （client.py docstring）；st=2 语义未完全摸清（按计划观察）。
