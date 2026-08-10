# Shadow 数据包扩容 + 输出契约 v2 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans。Steps 用 checkbox 追踪。
> 本会话约束：不用 subagent；逐任务 commit（已授权）；push 等用户明说；不改 `src/qing_investment/`；`tests/` 子目录不放 `__init__.py`；`.venv/bin/pytest`。

**Goal:** 实施 spec `docs/superpowers/specs/2026-08-10-shadow-pack-contract-v2.md`（含 2026-08-11 查漏增补 D7/D8）。

**Architecture:** KPL 新增龙虎榜模块 → 每日拉取接线 → 盲判数据包加 emotion/news_titles/lhb 三块（可选、缺失标注）→ 输出契约 v2（新字段 + prompt_version）→ cron 推后 18 点档 → 指数扩容 → 术语词典补概念。

**Tech Stack:** Python（investment_engine）、pytest、本机 crontab。

---

### Task 1: `src/investment_engine/kpl/lhb.py` 龙虎榜模块

**Files:**
- Create: `src/investment_engine/kpl/lhb.py`
- Test: `tests/investment_engine/test_kpl_lhb.py`

注意：GetDay 响应体（br 压缩）未能从抓包文件离线还原，结构依接口清单第 5 节文档，解析防御式编写。

- [x] **Step 1: 写失败测试** `tests/investment_engine/test_kpl_lhb.py`

```python
"""kpl/lhb.py 单元测试（结构依接口清单第 5 节文档；响应体压缩未能离线还原实样）。"""

from __future__ import annotations

import json

from investment_engine.kpl.lhb import fetch_lhb, save_lhb

SAMPLE = {
    "errcode": "0",
    "Day": "2026-08-10",
    "NDay": "2026-08-07",
    "TList": [["1", "顶级游资"], ["4", "机构"]],
    "List": [{"StockID": "600664", "StockName": "哈药股份", "TypeName": "一线游资"}],
}
EMPTY = {"errcode": "0", "Day": "2026-08-07", "NDay": "2026-08-06",
         "TList": [["1", "顶级游资"]], "List": []}


class _FakeClient:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def post(self, subdomain, c, a, params=None):
        self.calls.append((subdomain, c, a, params))
        return self.payload


def test_fetch_lhb_fields():
    client = _FakeClient(SAMPLE)
    data = fetch_lhb(client)
    assert client.calls == [("applhb", "UserBusiness", "GetDay", None)]
    assert data["disclosure_day"] == "2026-08-10"
    assert data["prev_disclosure_day"] == "2026-08-07"
    assert data["tlist"] == [["1", "顶级游资"], ["4", "机构"]]
    assert len(data["list"]) == 1 and data["note"] == ""


def test_fetch_lhb_empty_list_tolerated():
    data = fetch_lhb(_FakeClient(EMPTY))
    assert data["list"] == [] and "非披露日" in data["note"]


def test_save_lhb(tmp_path):
    path = save_lhb(fetch_lhb(_FakeClient(SAMPLE)), tmp_path, "2026-08-10")
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert path.name == "2026-08-10.json"
    assert saved["list"][0]["StockID"] == "600664"
```

- [x] **Step 2: 跑测试确认失败**

Run: `.venv/bin/pytest tests/investment_engine/test_kpl_lhb.py -q`
Expected: FAIL（ModuleNotFoundError: investment_engine.kpl.lhb）

- [x] **Step 3: 实现** `src/investment_engine/kpl/lhb.py`

```python
"""龙虎榜游资榜：UserBusiness.GetDay（applhb 子域）拉取 + 落盘。

接口结构见 docs/design/kpl-api-inventory.md 第 5 节（2026-08-10 抓包记录）：
TList=分类列表（顶级/一线/知名/机构/庄股）、List=当日上榜明细、Day/NDay=披露日/上一披露日。
T 日收盘后披露——非披露日或披露未出时 List 为空，属正常：落盘 note 标注，不报错。
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

from investment_engine.kpl.client import KplClient


def fetch_lhb(client: KplClient) -> dict:
    """拉取龙虎榜游资榜，返回 {date, fetched_at, disclosure_day, prev_disclosure_day, tlist, list, note}。"""
    resp = client.post("applhb", "UserBusiness", "GetDay")
    items = resp.get("List") or []
    return {
        "date": date.today().isoformat(),
        "fetched_at": datetime.now().isoformat(timespec="seconds"),
        "disclosure_day": resp.get("Day") or "",
        "prev_disclosure_day": resp.get("NDay") or "",
        "tlist": resp.get("TList") or [],
        "list": items,
        "note": "" if items else "当日上榜明细为空（非披露日或披露未出）",
    }


def save_lhb(data: dict, out_root: Path, day: str) -> Path:
    """写 <out_root>/lhb/<day>.json。"""
    out_dir = Path(out_root) / "lhb"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{day}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return path
```

- [x] **Step 4: 跑测试确认通过**

Run: `.venv/bin/pytest tests/investment_engine/test_kpl_lhb.py -q`
Expected: 3 passed

- [x] **Step 5: Commit**

```bash
git add src/investment_engine/kpl/lhb.py tests/investment_engine/test_kpl_lhb.py
git commit -m "feat(kpl): 龙虎榜游资榜模块——GetDay 拉取+落盘，空披露容忍"
```

---

### Task 2: `kpl_daily_fetch.py` 接 lhb

**Files:**
- Modify: `scripts/kpl_daily_fetch.py`
- Test: `tests/investment_engine/test_kpl_daily_fetch.py`

- [x] **Step 1: 改测试（先红）**——fixture 加 lhb mock + 新用例

`tests/investment_engine/test_kpl_daily_fetch.py` 的 `fake_layers` fixture 内追加：

```python
    monkeypatch.setattr(kpl_daily_fetch.lhb, "fetch_lhb",
                        lambda client: {"date": "2026-08-10",
                                        "fetched_at": "2026-08-10T17:45:02",
                                        "disclosure_day": "2026-08-10",
                                        "prev_disclosure_day": "2026-08-07",
                                        "tlist": [], "list": [{"StockID": "600664"}],
                                        "note": ""})
```

文件末尾新增：

```python
def test_lhb_written_and_skip_flag(tmp_path, capsys, fake_layers):
    argv = ["--date", "2026-08-10", "--out-root", str(tmp_path)]
    assert kpl_daily_fetch.main(argv) == 0
    lhb_file = tmp_path / "lhb" / "2026-08-10.json"
    assert lhb_file.exists()
    assert json.loads(lhb_file.read_text())["list"][0]["StockID"] == "600664"
    argv2 = ["--date", "2026-08-11", "--out-root", str(tmp_path), "--skip-lhb"]
    assert kpl_daily_fetch.main(argv2) == 0
    assert not (tmp_path / "lhb" / "2026-08-11.json").exists()
```

Run: `.venv/bin/pytest tests/investment_engine/test_kpl_daily_fetch.py -q`
Expected: 新用例 FAIL（`kpl_daily_fetch.lhb` 属性不存在 / lhb 文件未生成）

- [x] **Step 2: 改脚本**

`scripts/kpl_daily_fetch.py`：
1. docstring 首行 `（cron 工作日 15:45 调用）：情绪快照 + 当日资讯全文` → `（cron 工作日 17:45 调用）：情绪快照 + 当日资讯全文 + 龙虎榜`；
2. import 行 `from investment_engine.kpl import emotion, news` → `from investment_engine.kpl import emotion, lhb, news`；
3. `--skip-news` 行后加 `parser.add_argument("--skip-lhb", action="store_true")`；
4. news 块之后（`try:` 内）加：

```python
        if not args.skip_lhb:
            target = out_root / "lhb" / f"{args.date}.json"
            if target.exists() and not args.force:
                print(f"[kpl] 龙虎榜已存在，跳过: {target}")
            else:
                data = lhb.fetch_lhb(client)
                path = lhb.save_lhb(data, out_root, args.date)
                tail = f"（{data['note']}）" if data["note"] else ""
                print(f"[kpl] 龙虎榜 → {path}  披露日={data['disclosure_day']}"
                      f" 上榜={len(data['list'])} 条{tail}")
```

- [x] **Step 3: 跑测试确认通过 + 全量**

Run: `.venv/bin/pytest tests/investment_engine/test_kpl_daily_fetch.py tests/investment_engine/test_kpl_lhb.py -q`
Expected: 全过

- [x] **Step 4: Commit**

```bash
git add scripts/kpl_daily_fetch.py tests/investment_engine/test_kpl_daily_fetch.py
git commit -m "feat(kpl): 每日拉取接龙虎榜（--skip-lhb 开关，emotion→news→lhb 顺序）"
```

---

### Task 3: 数据包三块扩展（`blindtest/dataset.py`）

**Files:**
- Modify: `src/investment_engine/blindtest/dataset.py`
- Test: `tests/investment_engine/test_dataset.py`

- [x] **Step 1: 写失败测试**——`test_dataset.py` 顶部 import 加 `json`，文件末尾加：

```python
class TestKplBlocks:
    def setup_method(self):
        self.db = Path(tempfile.gettempdir()) / f"test_ds3_{id(self)}.db"
        init_db(db_path=self.db)
        save_klines("IDX000300", _klines("IDX000300", [4000.0 + i for i in range(30)]),
                    db_path=self.db)
        self.kpl = Path(tempfile.mkdtemp())
        (self.kpl / "emotion").mkdir(parents=True)
        (self.kpl / "news" / "2026-06-30").mkdir(parents=True)
        (self.kpl / "lhb").mkdir(parents=True)
        (self.kpl / "emotion" / "2026-06-30.json").write_text(json.dumps({
            "daban": {"tZhangTing": 99, "tFengBan": 87.6},
            "lianban": [["600664", "哈药股份", 9.94, 0, "2连板", "医药", "创新药;2"]],
            "fengkou": [{"StockID": "002655", "StockName": "共达电声"}],
            "bankuai": [["医药", "1.61", 801045]],
        }, ensure_ascii=False), encoding="utf-8")
        (self.kpl / "news" / "2026-06-30" / "index.json").write_text(json.dumps([
            {"id": 1, "title": "测试资讯", "stocks": [{"StockID": "600664"}], "fetched": True},
        ], ensure_ascii=False), encoding="utf-8")
        (self.kpl / "lhb" / "2026-06-30.json").write_text(json.dumps({
            "disclosure_day": "2026-06-30", "list": [{"StockID": "600664"}], "note": "",
        }, ensure_ascii=False), encoding="utf-8")

    def teardown_method(self):
        self.db.unlink(missing_ok=True)

    def test_blocks_present(self):
        pack = build_daily_pack("2026-06-30", config_dir=Path("config/stock_monitor"),
                                db_path=self.db, kpl_root=self.kpl)
        assert pack["emotion"]["daban"]["tZhangTing"] == 99
        assert pack["emotion"]["bankuai"] == [["医药", "1.61"]]
        assert pack["emotion"]["fengkou_stocks"] == ["共达电声"]
        assert pack["news_titles"]["items"][0]["stocks"] == ["600664"]
        assert pack["lhb"]["count"] == 1
        assert "missing" not in pack
        pack_to_prompt(pack)  # 过防泄漏断言

    def test_missing_blocks_annotated(self):
        pack = build_daily_pack("2026-06-29", config_dir=Path("config/stock_monitor"),
                                db_path=self.db, kpl_root=self.kpl)
        assert pack["missing"] == ["kpl_emotion", "kpl_news_titles", "kpl_lhb"]
        assert "emotion" not in pack
```

Run: `.venv/bin/pytest tests/investment_engine/test_dataset.py::TestKplBlocks -q`
Expected: FAIL（build_daily_pack 无 kpl_root 参数）

- [x] **Step 2: 实现**——dataset.py：

a) `_INDEX_LOOKBACK` 常量区后加：

```python
KPL_ROOT = _REPO / "infra" / "data" / "kpl"
_NEWS_TITLE_CAP = 60
_LHB_ITEM_CAP = 20
```

b) `_load_glossary` 之后加三个加载器：

```python
def _load_emotion(day: str, kpl_root: Path) -> dict | None:
    """KPL 情绪快照精选块；当日文件缺失返回 None。"""
    path = kpl_root / "emotion" / f"{day}.json"
    if not path.exists():
        return None
    d = json.loads(path.read_text(encoding="utf-8"))
    out: dict = {}
    if d.get("daban"):
        out["daban"] = d["daban"]
    if d.get("lianban"):
        out["lianban"] = d["lianban"]
    fengkou = [f["StockName"] for f in (d.get("fengkou") or [])
               if isinstance(f, dict) and f.get("StockName")]
    if fengkou:
        out["fengkou_stocks"] = fengkou
    bankuai = [[b[0], b[1]] for b in (d.get("bankuai") or [])
               if isinstance(b, (list, tuple)) and len(b) >= 2]
    if bankuai:
        out["bankuai"] = bankuai
    return out or None


def _load_news_titles(day: str, kpl_root: Path) -> dict | None:
    """当日资讯标题列表（不含全文），封顶 _NEWS_TITLE_CAP 条。"""
    path = kpl_root / "news" / day / "index.json"
    if not path.exists():
        return None
    items = json.loads(path.read_text(encoding="utf-8"))
    titles = []
    for it in items[:_NEWS_TITLE_CAP]:
        stocks = []
        for s in (it.get("stocks") or [])[:5]:
            if isinstance(s, dict):
                stocks.append(str(s.get("StockID") or s.get("Code") or s))
            else:
                stocks.append(str(s))
        titles.append({"t": str(it.get("title", "")), "stocks": stocks})
    out: dict = {"items": titles}
    if len(items) > _NEWS_TITLE_CAP:
        out["truncated"] = f"{_NEWS_TITLE_CAP}/{len(items)}"
    return out


def _load_lhb(day: str, kpl_root: Path) -> dict | None:
    """龙虎榜摘要：披露日 + 上榜明细（封顶 _LHB_ITEM_CAP 条，字段透传）。"""
    path = kpl_root / "lhb" / f"{day}.json"
    if not path.exists():
        return None
    d = json.loads(path.read_text(encoding="utf-8"))
    return {"disclosure_day": d.get("disclosure_day", ""),
            "count": len(d.get("list") or []),
            "items": (d.get("list") or [])[:_LHB_ITEM_CAP],
            "note": d.get("note", "")}
```

c) `build_daily_pack` 签名加 `kpl_root=None`，返回 dict 前改为：

```python
    pack = {
        "date": day,
        "index": index,
        "stocks": stocks,
        "directions": _load_directions(config_dir),
        "chains": _load_chains(),
        "glossary": _load_glossary(),
        "patterns": _load_patterns_index(),
    }
    root = Path(kpl_root) if kpl_root else KPL_ROOT
    blocks = {"emotion": _load_emotion(day, root),
              "news_titles": _load_news_titles(day, root),
              "lhb": _load_lhb(day, root)}
    missing = [f"kpl_{k}" for k, v in blocks.items() if v is None]
    for k, v in blocks.items():
        if v is not None:
            pack[k] = v
    if missing:
        pack["missing"] = missing
    return pack
```

- [x] **Step 3: 跑测试确认通过 + 全量**

Run: `.venv/bin/pytest tests/investment_engine/test_dataset.py -q`
Expected: 全过（含既有用例——既有用例不传 kpl_root，真实 KPL_ROOT 下无 2026-06 文件，走 missing 分支）

Run: `.venv/bin/pytest tests/investment_engine -q`
Expected: 全绿

- [x] **Step 4: Commit**

```bash
git add src/investment_engine/blindtest/dataset.py tests/investment_engine/test_dataset.py
git commit -m "feat(shadow): 盲判数据包接入 KPL 情绪/资讯标题/龙虎榜三块（可选，缺失如实标注）"
```

---

### Task 4: 输出契约 v2（`replay.py` + `predict.py`）

**Files:**
- Modify: `src/investment_engine/blindtest/replay.py`、`src/investment_engine/shadow/predict.py`
- Test: `tests/investment_engine/test_replay.py`

- [x] **Step 1: 写失败测试**——`test_replay.py` import 行加 `PROMPT_VERSION`，文件末尾加：

```python
GOOD_JSON_V2 = json.dumps({
    "market_stage": "震荡",
    "stage_reason": "缩量整理，封板率87.6%",
    "scenarios": [{"name": "A", "condition": "低开有承接", "conclusion": "反弹延续", "key": "承接"}],
    "watch_next": ["二板家数能否达13家"],
    "invalidation": ["情绪龙头集体断板"],
    "directions": [{"direction_id": "mlcc_super_cycle", "reason": "涨价",
                    "posture": "右侧确认", "stocks": ["002371"]}],
    "used_patterns": ["upstream_cycle"],
}, ensure_ascii=False)


class TestParseResultV2:
    def test_v2_fields(self):
        r = parse_result(GOOD_JSON_V2)
        assert r["scenarios"][0]["key"] == "承接"
        assert r["watch_next"] == ["二板家数能否达13家"]
        assert r["invalidation"] == ["情绪龙头集体断板"]
        assert r["directions"][0]["posture"] == "右侧确认"

    def test_v1_backward_compat(self):
        r = parse_result(GOOD_JSON)
        assert r["scenarios"] == [] and r["watch_next"] == [] and r["invalidation"] == []
        assert r["directions"][0]["posture"] == ""

    def test_invalid_posture_dropped(self):
        bad = json.loads(GOOD_JSON_V2)
        bad["directions"][0]["posture"] = "梭哈"
        r = parse_result(json.dumps(bad, ensure_ascii=False))
        assert r["directions"][0]["posture"] == ""

    def test_prompt_version_constant(self):
        assert PROMPT_VERSION == "v2"
```

Run: `.venv/bin/pytest tests/investment_engine/test_replay.py -q`
Expected: FAIL（ImportError: PROMPT_VERSION）

- [x] **Step 2: 实现**——replay.py：

a) `SYSTEM_PROMPT` 替换为 v2（原文整段替换）：

```python
PROMPT_VERSION = "v2"

SYSTEM_PROMPT = """你是一个执行已验证方法论的市场分析引擎。基于给定的当日客观数据，独立完成市场复盘判断。
要求：
1. 每个判断必须声明所用的数据项；不得引用任何人物的言论或观点。
2. 可参考给定的推理框架索引（patterns）与术语词典组织推理，在 used_patterns 中登记实际用到的框架 id。
3. 严格输出 JSON（不要输出其他文字）：
{"market_stage": "主升|震荡|调整|恐慌（四选一）",
 "stage_reason": "一句话依据（必须引用当日量能/情绪数据）",
 "scenarios": [{"name": "情形A", "condition": "触发条件", "conclusion": "应对结论", "key": "区分关键变量"}],
 "watch_next": ["下一交易日可观察、可证伪的验证变量"],
 "invalidation": ["本判断的失效条件"],
 "directions": [{"direction_id": "从给定方向池选择，1-3个", "reason": "一句话依据",
                "posture": "趋势|波段|右侧确认|回避（四选一）",
                "stocks": ["该方向下给定股票池中的代码，每方向1-2个"]}],
 "used_patterns": ["pattern_id"]}
4. 没有把握的方向可以不选，宁缺毋滥。scenarios 给 1-2 个互斥情形即可。"""
```

b) parse_result：常量与解析扩展——`_MAX_STOCKS_PER_DIR` 附近加：

```python
_POSTURES = ("趋势", "波段", "右侧确认", "回避")
_MAX_SCENARIOS = 3
_MAX_LIST = 5
```

directions 循环内 append 改为：

```python
        posture = str(d.get("posture", ""))
        directions.append({
            "direction_id": str(d["direction_id"]),
            "reason": str(d.get("reason", "")),
            "posture": posture if posture in _POSTURES else "",
            "stocks": [str(s).split(".")[0] for s in (d.get("stocks") or [])[:_MAX_STOCKS_PER_DIR]],
        })
```

return 前加 scenarios 解析，return 替换为：

```python
    scenarios = []
    for s in (data.get("scenarios") or [])[:_MAX_SCENARIOS]:
        if not isinstance(s, dict):
            continue
        scenarios.append({
            "name": str(s.get("name", "")),
            "condition": str(s.get("condition", "")),
            "conclusion": str(s.get("conclusion", "")),
            "key": str(s.get("key", "")),
        })
    return {
        "market_stage": stage,
        "stage_reason": str(data.get("stage_reason", "")),
        "scenarios": scenarios,
        "watch_next": [str(w) for w in (data.get("watch_next") or [])[:_MAX_LIST]],
        "invalidation": [str(w) for w in (data.get("invalidation") or [])[:_MAX_LIST]],
        "directions": directions,
        "used_patterns": [str(p) for p in (data.get("used_patterns") or [])],
    }
```

c) replay 记录写入处（约 127/132 行）的 JSON 加 `"prompt_version": PROMPT_VERSION`（执行时先读该段确认结构再改）。

d) `predict.py`：import 加 `PROMPT_VERSION`，`rec` 加 `"prompt_version": PROMPT_VERSION`：

```python
        rec = {"date": day, "result": result, "raw": raw,
               "prompt_version": PROMPT_VERSION,
               "stage_hit": None, "due_scores": None, "status": "pending_maturity"}
```

- [x] **Step 3: 跑测试确认通过 + 全量**

Run: `.venv/bin/pytest tests/investment_engine -q`
Expected: 全绿

- [x] **Step 4: Commit**

```bash
git add src/investment_engine/blindtest/replay.py src/investment_engine/shadow/predict.py tests/investment_engine/test_replay.py
git commit -m "feat(shadow): 输出契约 v2——情景树/验证变量/失效条件/方向定性 + prompt_version 标记"
```

---

### Task 5: cron 时序 + 文档 + KNOWN_DATA_GAPS + graduation 版本行

**Files:**
- Modify: `src/investment_engine/shadow/attribute.py`（KNOWN_DATA_GAPS）
- Modify: `src/investment_engine/shadow/graduation.py`（版本行）
- Modify: `docs/tasks/kline-daily-fetch-ops.md`、`docs/current-system-guide.md`、`scripts/shadow_daily.py`（docstring 时刻）
- 本机 crontab（非 git）
- Test: `tests/investment_engine/test_shadow_graduation_report.py`

- [x] **Step 1: 写失败测试**——`test_shadow_graduation_report.py` 末尾加：

```python
def test_report_has_version_note(tmp_path):
    pred_dir = _seed(tmp_path)
    out = run(pred_dir, weeks=8, out_dir=tmp_path / "logs", today=TODAY)
    text = out.read_text(encoding="utf-8")
    assert "prompt 版本" in text and "v1" in text
```

Run: `.venv/bin/pytest tests/investment_engine/test_shadow_graduation_report.py -q`
Expected: 新用例 FAIL

- [x] **Step 2: graduation.py 实现**——加函数并在报告说明节加一行：

```python
def version_spans(records: list[dict]) -> str:
    """prompt_version 分布（老记录无字段计 v1）。"""
    spans: dict[str, list[str]] = {}
    for r in records:
        spans.setdefault(r.get("prompt_version") or "v1", []).append(r["date"])
    return "；".join(f"{ver}: {min(ds)}~{max(ds)}（{len(ds)} 条）"
                     for ver, ds in sorted(spans.items()))
```

`render_report` 签名加 `version_note: str`，说明节加一行：
`f"- prompt 版本: {version_note}（v2=2026-08-11 契约升级；混窗期统计不自动切分，人读分段）",`
`run()` 调 `render_report` 处传 `version_note=version_spans(records)`。（执行时先读 load_records/render 调用点确认变量名。）

- [x] **Step 3: attribute.py KNOWN_DATA_GAPS**

```python
KNOWN_DATA_GAPS = ["板块资金流", "分时数据", "公告流"]
```

（移除已补的"涨停池/炸板率""涨跌家数"；"公告/新闻流"收窄为"公告流"——资讯标题已补。）

- [x] **Step 4: crontab 调整**

```bash
crontab -l   # 先读现状
# KPL: 45 15 → 45 17；shadow: 40 15 → 5 18
crontab -l | sed -e 's/^45 15 \* \* 1-5 \(.*kpl\)/45 17 * * 1-5 \1/' \
                 -e 's/^40 15 \* \* 1-5 \(.*shadow\)/5 18 * * 1-5 \1/' | crontab -
crontab -l   # 复核
```

（执行时以实际行内容为准逐行改，不盲套 sed。）

- [x] **Step 5: 文档同步**

- `docs/tasks/kline-daily-fetch-ops.md`：时序表 15:40 shadow→18:05、15:45 KPL→17:45，加变更记录行；
- `docs/current-system-guide.md`：架构图与 cron 表时刻同步，数据块说明加"情绪/资讯标题/龙虎榜入盲判包"；
- `scripts/shadow_daily.py` docstring：`cron 15:40 调用` → `cron 18:05 调用`。

- [x] **Step 6: 全量测试 + Commit**

Run: `.venv/bin/pytest tests/investment_engine -q`
Expected: 全绿

```bash
git add src/investment_engine/shadow/attribute.py src/investment_engine/shadow/graduation.py \
        tests/investment_engine/test_shadow_graduation_report.py \
        docs/tasks/kline-daily-fetch-ops.md docs/current-system-guide.md scripts/shadow_daily.py
git commit -m "chore(shadow): 复盘推后18点档（KPL 17:45/shadow 18:05）+ KNOWN_DATA_GAPS 更新 + 毕业报告版本行"
```

---

### Task 6: 指数扩容（D7）

**Files:**
- Modify: `scripts/fetch_index_klines.py`（INDEXES）、`src/investment_engine/blindtest/dataset.py`（INDEX_CODES）
- Test: `tests/investment_engine/test_dataset.py`

- [x] **Step 1: 写失败测试**——`test_dataset.py` import 加 `INDEX_CODES`，末尾加：

```python
def test_index_codes_expanded():
    assert set(INDEX_CODES) == {"IDX000300", "IDX000001", "IDX399006",
                                "IDX399001", "IDX000852"}
```

Run: `.venv/bin/pytest tests/investment_engine/test_dataset.py::test_index_codes_expanded -q`
Expected: FAIL

- [x] **Step 2: 实现**

`dataset.py`：`INDEX_CODES = ("IDX000300", "IDX000001", "IDX399006", "IDX399001", "IDX000852")`

`fetch_index_klines.py`：

```python
INDEXES = {"IDX000300": "sh000300", "IDX000001": "sh000001",
           "IDX399006": "sz399006", "IDX399001": "sz399001",
           "IDX000852": "sh000852"}  # 沪深300 / 上证 / 创业板指 / 深成指 / 中证1000
```

- [x] **Step 3: 测试 + 实拉回填**

Run: `.venv/bin/pytest tests/investment_engine/test_dataset.py -q`
Expected: 全过

Run: `.venv/bin/python scripts/fetch_index_klines.py`
Expected: 5 个指数拉取成功；随后 `sqlite3 infra/data/kline_cache.db "SELECT DISTINCT code FROM index_klines"` 类查询确认（以实际表结构为准）。

- [x] **Step 4: Commit**

```bash
git add scripts/fetch_index_klines.py src/investment_engine/blindtest/dataset.py tests/investment_engine/test_dataset.py
git commit -m "feat(shadow): 指数扩容——创业板指/深成指/中证1000 入盲判包（大小盘风格可见）"
```

---

### Task 7: 术语词典补 3 概念（D8）

**Files:**
- Modify: `framework/up-glossary.md`

- [x] **Step 1: 加 3 行（"外溢"行之后、"## 使用规则"之前）**

```markdown
| 晋级率 | 次日连板家数 ÷ 前日首板家数；经验参考值约 15%（经验参数，待回测验证，不作定律使用） | 涨停池/连板梯队（KPL 情绪快照） |
| 抱团 | 若干高位连板股脱离各自所属板块共振上涨，形成相互加持的资金集合；无产业基本面锚，个别断板则整体失去参照系 | 连板梯队及板块归属（KPL 情绪快照） |
| 断板/换龙 | 连板中断为断板；外力扰动型（停牌核查等）打断梯队并形成负反馈，内生换龙型（资金主动切换龙头）不杀场内情绪 | 连板梯队 + 公告/资讯 |
```

注意：行内不得出现 UP/博主/青枫浦 字样（会被防泄漏过滤整行剔除）。

- [x] **Step 2: 使用规则第 3 条放宽**（新术语由归因驱动，不限于概念误用型）

old: `3. 新术语加入须经盲测期归因（概念误用型）驱动，先加定义再使用。`
new: `3. 新术语加入须经盲测期归因驱动（任一归因类型），先加定义再使用。`

- [x] **Step 3: Commit**

```bash
git add framework/up-glossary.md
git commit -m "docs(glossary): 补打板节奏3概念——晋级率(经验参数待验证)/抱团/断板换龙（2026-08-10归因驱动）"
```

---

## Self-Review 记录

- Spec 覆盖：D1→T3、D2→T1/T2、D3→T4、D4→T5(cron+ops)、D5→T5(gaps)、D6→T5(graduation)、D7→T6、D8→T7。✅
- 占位符：无；所有代码完整。crontab 行内容执行时先读后改（已注明）。✅
- 一致性：missing 标签 `kpl_emotion/kpl_news_titles/kpl_lhb` 与测试断言一致；`PROMPT_VERSION` 在 replay 定义、predict 引用、test 断言一致；fixture mock 覆盖三个 fetch 函数（既有用例不破）。✅

## 执行记录（2026-08-11）

| Task | Commit | 结果 |
|---|---|---|
| T1 | 109ee24 | lhb 模块 3 测试过；GetDay 响应体 br 压缩未能离线还原实样，结构按接口清单文档防御式解析（已在模块 docstring 标注） |
| T2 | 33d1bc6 | 入口接线；fixture 补 lhb mock，6 测试过 |
| T3 | 92a96f3 | 三块加载器 + missing 标注；175 全绿 |
| T4 | 52a9fa7 | 契约 v2 + prompt_version；179 全绿 |
| T5 | 54af304 | crontab 实际调整（KPL 17:45 / shadow 18:05，备份 /tmp/crontab.bak.20260811）；KNOWN_DATA_GAPS 收窄；graduation 版本行；180 全绿 |
| T6 | d3eb716 | 5 指数回填成功（各 95 根 2026-03-24~08-10）；实盘拼包验证：5 指数+emotion+news_titles 在场、lhb 缺失正确标注、prompt 43,413 字符 |
| T7 | 53dbba7 | 3 概念进表并入包验证（无 UP 字样残留）；使用规则第 3 条放宽为任一归因类型驱动 |

偏差与说明：
- 三份处置提案 status 已转 done（随本 commit）。
- 2026-08-10 的盲判记录仍是 v1 契约产物；v2 首跑 = 2026-08-11 18:05 cron（或手动补跑）。
- token 用量：拼包正文 43,413 字符（含 5 指数×60 根+212 个股快照+三块新数据），单次调用量级正常。
