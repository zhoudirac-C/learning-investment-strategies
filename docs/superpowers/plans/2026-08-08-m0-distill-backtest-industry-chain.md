# M0：方法论蒸馏 + 回测基建 + 产业链知识库 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 落地 v2.1 方案的 M0 里程碑——把 UP 推理模式改写为来源中立方法论（带 validation 区块），新建离线回测基建跑出信号命中率，并把 3 篇存量产业链深度研究迁移为结构化、可校验、带保鲜期的产业链知识库。

**Architecture:** 新建 `src/investment_engine/` 包（与 `qing_investment` 平级，只 import 调用、不修改其代码），三个子模块：`industry_chain`（chain.yaml schema+读写+迁移解析）、`distill`（来源中立模式校验）、`backtest`（历史区间数据访问+命中率统计）。两个 CLI 脚本放 `scripts/`。知识资产落盘到 `framework/` 与 `knowledge/industry-chains/`。

**Tech Stack:** Python 3.11+ / PyYAML / SQLite（复用 `qing_investment.kline_cache` 的 `infra/data/kline_cache.db`）/ pytest（仓库惯例：无 conftest，`setup_method` + `db_path` 注入隔离）。

**调研确认的关键事实（写代码前必读）：**

| 依赖 | 确认结果 |
|---|---|
| K 线缓存 | `qing_investment/kline_cache.py`：表 `stocks_kline(code, trade_date, open, high, low, close, volume, turnover, amplitude, pct_change)`，PK `(code, trade_date)`；`get_klines(code, days)` 只支持"最近 N 日"，**无区间查询**（本计划新建）；读路径纯 SQLite 无网络，可离线回放 |
| 规则引擎 | `qing_investment/monitor/rules/__init__.py`：`BuySignalRuleEngine().evaluate(config: dict, quote_snapshot: dict) -> list[RuleAlert]`，纯函数无 I/O；`quote_snapshot = {"source": ..., "quotes": [{"code": "1.600519"(secid格式), "name", "latest", "open", "high", "low", "volume", "amount", "pct_change", "turnover_rate"}]}`（见 `monitor/tests/test_e2e.py:38` 的 `mock_quote_snapshot`）；config dict 模式见同文件 `mock_config`（:86） |
| 配置加载 | `qing_investment/monitor/context/__init__.py:1094` `load_monitor_config(path) -> MonitorConfig(config_dir, positions, watchlist, strategy_pack, direction_pool, stock_pool)`；标的池新结构：`config/stock_monitor/stock_pool.yaml` 的 `stocks[].{code: "000636.SZ", name, direction, entry.{primary_zone, hard_stop}}` |
| reasoning-patterns.yaml | 2250 行，顶层 `updated_at/version/merge_note` + `patterns:` 10 项（upstream_cycle:5, mainline_identification:331, sector_rotation:835, macro_transmission:1137, sentiment_cycle:1416, technical_timing:1617, earnings_analysis:1759, ai_industry_chain:1900, operation_strategy:2046, others:2167）；每项字段 `pattern_id/name/description/source_raw[]/applicable_themes[]/reasoning_chain[{step,name,question,UP_logic,evidence_sources[]}]/risk_factors[]/confidence_indicators[]/examples[]/merged_from[]`；`UP_logic` 只出现在 reasoning_chain 步骤内 |
| 深度研究 3 篇 | `docs/标的深度研究/方向一：长鑫存储产业链全景梳理-20260518.md`（212 行，六赛道+投资视角总结）、`方向二：国产算力产业链与Token经济学深度梳理-20260518.md`（273 行，八层+投资视角总结）、`方向三：AI基础设施与能源转型产业链梳理-20260518.md`（224 行，四产业链+投资视角总结）；结构一致：blockquote 背景+一句话核心逻辑→分章（`## 一、赛道一：…`/`### 2.1 刻蚀设备`）→章内标的表格（列含 标的/代码/核心产品/关系或竞争地位/弹性评估⭐）→末尾投资视角总结章 |
| claims 卡 | `knowledge/claims/claim-*.yaml` 446 张，顶层 `claims:` 列表，字段见 `qing_investment/claim_schema.py`（17 必填） |
| evals/ | 全部 md 契约，无 runner；M0 不动 evals |
| 案例库 | `knowledge/cases/` 实际案例仅 2 篇——基准率检索样本不足，M0 不依赖，验收报告须如实记录此缺口 |
| Pre-flight | `src/investment_engine/`、`knowledge/industry-chains/`、`framework/up-glossary.md`、`scripts/migrate_industry_chains.py`、`scripts/backtest_buy_signals.py` **均不存在**（2026-08-08 确认），全部新建 |
| 术语词典 | UP 概念（冰点/炸板率/缩容炒作等）散布 `framework/market-cycle-framework.md`（597 行）等，M0 提取客观数据定义 |

**Git 纪律：** 每个任务的 commit 步骤在执行时须经用户确认后运行（项目规则：不主动 git mutation）。commit message 遵循 `feat(scope): ...` / `test(scope): ...` 惯例。

---

## 文件结构

```
src/investment_engine/
├── __init__.py                     # Task 1
├── industry_chain/
│   ├── __init__.py                 # Task 1
│   ├── schema.py                   # Task 2：chain.yaml 校验器
│   ├── store.py                    # Task 3：knowledge/industry-chains/ 读写
│   └── migrate.py                  # Task 4：深度研究 md → chain dict 解析器
├── distill/
│   ├── __init__.py                 # Task 1
│   └── pattern_schema.py           # Task 6：来源中立推理模式校验器
└── backtest/
    ├── __init__.py                 # Task 1
    ├── history.py                  # Task 12：区间 K 线查询 + 历史 quote_snapshot 重建
    └── hit_rate.py                 # Task 13：前向收益 + 命中率汇总
scripts/
├── migrate_industry_chains.py      # Task 5：迁移 CLI
└── backtest_buy_signals.py         # Task 14：回测 CLI
knowledge/industry-chains/          # Task 5 产出（数据）
├── changxin-dram/{chain.yaml, research.md}
├── domestic-compute/{chain.yaml, research.md}
└── ai-infra-energy/{chain.yaml, research.md}
framework/
├── reasoning-patterns-v2.1-up-anchored.yaml  # Task 7：改写前备份当前版
├── reasoning-patterns.yaml                   # Task 7-10：来源中立改写（原地）
└── up-glossary.md                            # Task 11：术语词典（新建）
tests/investment_engine/
├── test_industry_chain_schema.py   # Task 2
├── test_industry_chain_store.py    # Task 3
├── test_migrate.py                 # Task 4
├── test_pattern_schema.py          # Task 6
├── test_history.py                 # Task 12
└── test_hit_rate.py                # Task 13
logs/                               # Task 15：回测报告与验收（logs/ 已在仓库中）
```

---

## Task 1: 包骨架与冒烟测试

**Files:**
- Create: `src/investment_engine/__init__.py`
- Create: `src/investment_engine/industry_chain/__init__.py`
- Create: `src/investment_engine/distill/__init__.py`
- Create: `src/investment_engine/backtest/__init__.py`
- Test: `tests/investment_engine/test_smoke.py`

注意：**不要**在 `tests/investment_engine/` 下放 `__init__.py`——pytest prepend 模式会把它注册为 `investment_engine` 包，遮蔽 `src/investment_engine`（与仓库 tests 平铺无 __init__ 惯例一致，参照 `tests/chan_engine/`）。

- [ ] **Step 1: 写冒烟测试**

```python
# tests/investment_engine/test_smoke.py
"""包骨架冒烟测试。"""


def test_package_importable():
    import investment_engine  # noqa: F401
    import investment_engine.industry_chain  # noqa: F401
    import investment_engine.distill  # noqa: F401
    import investment_engine.backtest  # noqa: F401


def test_qing_investment_still_importable():
    """红线：不修改 qing_investment，其导入必须保持正常。"""
    import qing_investment  # noqa: F401
    from qing_investment.monitor.rules import BuySignalRuleEngine  # noqa: F401
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/pytest tests/investment_engine/test_smoke.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'investment_engine'`

- [ ] **Step 3: 建包骨架**

四个 `__init__.py` 内容均为单行 docstring：

```python
# src/investment_engine/__init__.py
"""AI 炒股投资系统编排层（v2.1 M0）。只调用 qing_investment，不修改它。"""
```

```python
# src/investment_engine/industry_chain/__init__.py
"""产业链知识库：chain.yaml schema、读写、存量深度研究迁移。"""
```

```python
# src/investment_engine/distill/__init__.py
"""方法论蒸馏：UP 推理模式的来源中立改写与校验。"""
```

```python
# src/investment_engine/backtest/__init__.py
"""离线回测：历史区间数据访问与信号命中率统计。"""
```

`tests/investment_engine/__init__.py` 为空文件。

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/pytest tests/investment_engine/test_smoke.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit（经用户确认）**

```bash
git add src/investment_engine tests/investment_engine
git commit -m "feat(investment_engine): 新建编排层包骨架（v2.1 M0）"
```

---

## Task 2: chain.yaml 校验器

**Files:**
- Create: `src/investment_engine/industry_chain/schema.py`
- Test: `tests/investment_engine/test_industry_chain_schema.py`

设计决策：`chain_id` 与 `segments[].id` 用 ASCII slug（`[a-z0-9-]+`，目录名安全），中文名存 `name`；`mappings[].segment` 必须引用已定义的 segment id；`elasticity ∈ {core, elastic, concept}`；日期一律 `YYYY-MM-DD` 字符串，允许 `None`（待补字段如实为空，不许编造）。

- [ ] **Step 1: 写失败测试**

```python
# tests/investment_engine/test_industry_chain_schema.py
"""chain.yaml schema 校验器测试。"""
import pytest

from investment_engine.industry_chain.schema import ChainSchemaError, validate_chain


def _valid_chain() -> dict:
    return {
        "chain_id": "changxin-dram",
        "name": "长鑫存储产业链",
        "thesis": "长鑫IPO融资扩产 → 资本开支扩大 → 设备/材料采购增加 → 封测配套需求提升",
        "last_verified": "2026-05-18",
        "segments": [
            {"id": "seg-01", "name": "刻蚀设备", "value_share": None, "barrier": None,
             "landscape": None, "growth": None, "status": "扩产招标中", "last_verified": "2026-05-18"},
            {"id": "seg-02", "name": "CMP材料", "value_share": None, "barrier": None,
             "landscape": None, "growth": None, "status": None, "last_verified": None},
        ],
        "mappings": [
            {"code": "002371", "name": "北方华创", "segment": "seg-01",
             "relation": "刻蚀/PECVD/PVD设备批量导入长鑫产线", "cert_status": None,
             "order_evidence": None, "elasticity": "core",
             "elasticity_reason": "刻蚀+薄膜沉积全平台", "last_verified": "2026-05-18"},
            {"code": "300054", "name": "鼎龙股份", "segment": "seg-02",
             "relation": "CMP抛光垫在长鑫晶圆平坦化制程大规模量产", "cert_status": "已供货",
             "order_evidence": None, "elasticity": "elastic",
             "elasticity_reason": None, "last_verified": "2026-05-18"},
        ],
    }


class TestValidateChain:
    def test_valid_chain_passes(self):
        assert validate_chain(_valid_chain()) == _valid_chain()

    def test_missing_required_field_rejected(self):
        chain = _valid_chain()
        del chain["thesis"]
        with pytest.raises(ChainSchemaError, match="thesis"):
            validate_chain(chain)

    def test_bad_chain_id_rejected(self):
        chain = _valid_chain()
        chain["chain_id"] = "长鑫存储"  # 非 ASCII slug
        with pytest.raises(ChainSchemaError, match="chain_id"):
            validate_chain(chain)

    def test_mapping_segment_must_exist(self):
        chain = _valid_chain()
        chain["mappings"][0]["segment"] = "seg-99"
        with pytest.raises(ChainSchemaError, match="seg-99"):
            validate_chain(chain)

    def test_bad_elasticity_rejected(self):
        chain = _valid_chain()
        chain["mappings"][0]["elasticity"] = "⭐⭐⭐⭐"
        with pytest.raises(ChainSchemaError, match="elasticity"):
            validate_chain(chain)

    def test_bad_code_rejected(self):
        chain = _valid_chain()
        chain["mappings"][0]["code"] = "002371.SZ"  # 必须是 6 位数字
        with pytest.raises(ChainSchemaError, match="code"):
            validate_chain(chain)

    def test_bad_date_rejected(self):
        chain = _valid_chain()
        chain["last_verified"] = "20260518"
        with pytest.raises(ChainSchemaError, match="last_verified"):
            validate_chain(chain)

    def test_duplicate_segment_id_rejected(self):
        chain = _valid_chain()
        chain["segments"].append(dict(chain["segments"][0]))
        with pytest.raises(ChainSchemaError, match="重复"):
            validate_chain(chain)

    def test_none_dates_allowed(self):
        """待补字段允许 None（诚实留空），不得报错。"""
        chain = _valid_chain()
        chain["segments"][0]["value_share"] = None
        chain["mappings"][0]["order_evidence"] = None
        assert validate_chain(chain) == chain
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/pytest tests/investment_engine/test_industry_chain_schema.py -v`
Expected: FAIL，`ModuleNotFoundError`（schema.py 不存在）

- [ ] **Step 3: 实现校验器**

```python
# src/investment_engine/industry_chain/schema.py
"""产业链知识库 chain.yaml 的 schema 校验。

schema 定义见 investment-learning-project/ai-stock-investment-plan.md 第五节。
设计原则：待补字段允许 None（诚实留空），但结构与枚举必须合法。
"""
from __future__ import annotations

import re

ELASTICITY_LEVELS = ("core", "elastic", "concept")

REQUIRED_CHAIN_FIELDS = ("chain_id", "name", "thesis", "segments", "mappings", "last_verified")
REQUIRED_SEGMENT_FIELDS = ("id", "name")
REQUIRED_MAPPING_FIELDS = ("code", "name", "segment", "relation", "elasticity")

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_CODE_RE = re.compile(r"^\d{6}$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class ChainSchemaError(ValueError):
    """chain.yaml 结构或取值不合法。"""


def _check_date(value, where: str, errors: list[str]) -> None:
    if value is None:
        return
    if not isinstance(value, str) or not _DATE_RE.match(value):
        errors.append(f"{where}: 日期必须为 'YYYY-MM-DD' 字符串，得到 {value!r}")


def validate_chain(data: dict) -> dict:
    """校验 chain.yaml 解码后的 dict。合法原样返回，不合法抛 ChainSchemaError。"""
    if not isinstance(data, dict):
        raise ChainSchemaError("chain.yaml 顶层必须是 mapping")

    errors: list[str] = []
    for field in REQUIRED_CHAIN_FIELDS:
        if field not in data:
            errors.append(f"缺必填字段: {field}")
    if errors:
        raise ChainSchemaError("; ".join(errors))

    if not _SLUG_RE.match(str(data["chain_id"])):
        errors.append(f"chain_id 必须是小写字母/数字/连字符 slug，得到 {data['chain_id']!r}")
    _check_date(data.get("last_verified"), "last_verified", errors)

    segments = data.get("segments") or []
    segment_ids: set[str] = set()
    for i, seg in enumerate(segments):
        if not isinstance(seg, dict):
            errors.append(f"segments[{i}]: 必须是 mapping")
            continue
        for field in REQUIRED_SEGMENT_FIELDS:
            if field not in seg:
                errors.append(f"segments[{i}]: 缺 {field}")
        sid = seg.get("id")
        if sid is not None:
            if not _SLUG_RE.match(str(sid)):
                errors.append(f"segments[{i}].id 必须是 slug，得到 {sid!r}")
            if sid in segment_ids:
                errors.append(f"segments[{i}]: id 重复 {sid!r}")
            segment_ids.add(sid)
        _check_date(seg.get("last_verified"), f"segments[{i}].last_verified", errors)

    for i, m in enumerate(data.get("mappings") or []):
        if not isinstance(m, dict):
            errors.append(f"mappings[{i}]: 必须是 mapping")
            continue
        for field in REQUIRED_MAPPING_FIELDS:
            if field not in m:
                errors.append(f"mappings[{i}]: 缺 {field}")
        code = str(m.get("code", ""))
        if code and not _CODE_RE.match(code):
            errors.append(f"mappings[{i}]: code 必须是 6 位数字字符串，得到 {m.get('code')!r}")
        seg = m.get("segment")
        if seg is not None and seg not in segment_ids:
            errors.append(f"mappings[{i}]: segment {seg!r} 不在 segments 定义中")
        elasticity = m.get("elasticity")
        if elasticity is not None and elasticity not in ELASTICITY_LEVELS:
            errors.append(f"mappings[{i}]: elasticity 必须 ∈ {ELASTICITY_LEVELS}，得到 {elasticity!r}")
        _check_date(m.get("last_verified"), f"mappings[{i}].last_verified", errors)

    if errors:
        raise ChainSchemaError("; ".join(errors))
    return data
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/pytest tests/investment_engine/test_industry_chain_schema.py -v`
Expected: 9 passed

- [ ] **Step 5: Commit（经用户确认）**

```bash
git add src/investment_engine/industry_chain/schema.py tests/investment_engine/test_industry_chain_schema.py
git commit -m "feat(industry_chain): chain.yaml schema 校验器"
```

---

## Task 3: 产业链知识库读写层

**Files:**
- Create: `src/investment_engine/industry_chain/store.py`
- Test: `tests/investment_engine/test_industry_chain_store.py`

设计决策：`base_dir` 依赖注入（同 `kline_cache` 的 `db_path` 测试隔离惯例）；默认目录 = `repo_root()/knowledge/industry-chains`（`qing_investment.paths.repo_root`，`paths.py:7` 已确认）；**save 时强制过校验器**（坏数据永远落不了盘）。

- [ ] **Step 1: 写失败测试**

```python
# tests/investment_engine/test_industry_chain_store.py
"""产业链知识库读写测试。"""
import tempfile
from pathlib import Path

import pytest
import yaml

from investment_engine.industry_chain.schema import ChainSchemaError
from investment_engine.industry_chain.store import (
    chain_dir, default_base_dir, list_chains, load_chain, save_chain,
)


def _chain(chain_id: str = "test-chain") -> dict:
    return {
        "chain_id": chain_id,
        "name": "测试产业链",
        "thesis": "需求爆发 → 产能倾斜 → 涨价轮动",
        "last_verified": "2026-08-08",
        "segments": [
            {"id": "seg-01", "name": "上游材料", "value_share": None, "barrier": None,
             "landscape": None, "growth": None, "status": "涨价中", "last_verified": None},
        ],
        "mappings": [
            {"code": "000001", "name": "测试标的", "segment": "seg-01", "relation": "供货",
             "cert_status": None, "order_evidence": None, "elasticity": "elastic",
             "elasticity_reason": None, "last_verified": None},
        ],
    }


class TestStore:
    def setup_method(self):
        self.base = Path(tempfile.mkdtemp(prefix="ichain_test_"))

    def teardown_method(self):
        import shutil
        shutil.rmtree(self.base, ignore_errors=True)

    def test_save_then_load_roundtrip(self):
        save_chain(_chain(), base_dir=self.base)
        loaded = load_chain("test-chain", base_dir=self.base)
        assert loaded["chain_id"] == "test-chain"
        assert loaded["segments"][0]["name"] == "上游材料"

    def test_save_writes_yaml_and_validates(self):
        save_chain(_chain(), base_dir=self.base)
        path = chain_dir("test-chain", base_dir=self.base) / "chain.yaml"
        assert path.exists()
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert raw["thesis"].startswith("需求爆发")

    def test_save_rejects_invalid_chain(self):
        bad = _chain()
        bad["mappings"][0]["segment"] = "seg-99"
        with pytest.raises(ChainSchemaError):
            save_chain(bad, base_dir=self.base)
        assert not (chain_dir("test-chain", base_dir=self.base) / "chain.yaml").exists()

    def test_chain_id_mismatch_rejected(self):
        """URL 路径 id 与文件内 chain_id 必须一致，防张冠李戴。"""
        chain = _chain("a-chain")
        with pytest.raises(ChainSchemaError, match="mismatch|不一致"):
            save_chain(chain, base_dir=self.base, expect_id="b-chain")

    def test_load_missing_raises(self):
        with pytest.raises(FileNotFoundError):
            load_chain("no-such-chain", base_dir=self.base)

    def test_load_also_validates(self):
        """落盘后被手改坏的文件，读出时也要拦住。"""
        save_chain(_chain(), base_dir=self.base)
        path = chain_dir("test-chain", base_dir=self.base) / "chain.yaml"
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        raw["mappings"][0]["elasticity"] = "垃圾值"
        path.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
        with pytest.raises(ChainSchemaError):
            load_chain("test-chain", base_dir=self.base)

    def test_list_chains(self):
        save_chain(_chain("chain-a"), base_dir=self.base)
        save_chain(_chain("chain-b"), base_dir=self.base)
        assert list_chains(base_dir=self.base) == ["chain-a", "chain-b"]

    def test_default_base_dir_points_to_repo(self):
        assert default_base_dir().as_posix().endswith("knowledge/industry-chains")
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/pytest tests/investment_engine/test_industry_chain_store.py -v`
Expected: FAIL，`ModuleNotFoundError`

- [ ] **Step 3: 实现 store**

```python
# src/investment_engine/industry_chain/store.py
"""knowledge/industry-chains/ 的读写。save/load 双向强制 schema 校验。"""
from __future__ import annotations

from pathlib import Path

import yaml

from investment_engine.industry_chain.schema import ChainSchemaError, validate_chain


def default_base_dir() -> Path:
    from qing_investment.paths import repo_root

    return repo_root() / "knowledge" / "industry-chains"


def _base(base_dir: Path | None) -> Path:
    return Path(base_dir) if base_dir is not None else default_base_dir()


def chain_dir(chain_id: str, *, base_dir: Path | None = None) -> Path:
    return _base(base_dir) / chain_id


def save_chain(
    chain: dict,
    *,
    base_dir: Path | None = None,
    expect_id: str | None = None,
) -> Path:
    """校验通过后落盘 chain.yaml；返回写入路径。"""
    if expect_id is not None and chain.get("chain_id") != expect_id:
        raise ChainSchemaError(
            f"chain_id 不一致: 文件内 {chain.get('chain_id')!r}，期望 {expect_id!r}"
        )
    validate_chain(chain)
    out_dir = chain_dir(chain["chain_id"], base_dir=base_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "chain.yaml"
    path.write_text(
        yaml.safe_dump(chain, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return path


def load_chain(chain_id: str, *, base_dir: Path | None = None) -> dict:
    path = chain_dir(chain_id, base_dir=base_dir) / "chain.yaml"
    if not path.exists():
        raise FileNotFoundError(f"产业链不存在: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return validate_chain(data)


def list_chains(*, base_dir: Path | None = None) -> list[str]:
    base = _base(base_dir)
    if not base.exists():
        return []
    return sorted(
        p.name for p in base.iterdir()
        if p.is_dir() and (p / "chain.yaml").exists()
    )
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/pytest tests/investment_engine/test_industry_chain_store.py -v`
Expected: 8 passed

- [ ] **Step 5: Commit（经用户确认）**

```bash
git add src/investment_engine/industry_chain/store.py tests/investment_engine/test_industry_chain_store.py
git commit -m "feat(industry_chain): 知识库读写层（双向 schema 校验）"
```

---

## Task 4: 深度研究 md → chain dict 解析器

**Files:**
- Create: `src/investment_engine/industry_chain/migrate.py`
- Test: `tests/investment_engine/test_migrate.py`

解析规则（基于 3 篇实地调研的结构事实）：
- **thesis**：匹配 `一句话核心逻辑` 所在行，取其后的文本，剥离 markdown 强调符号；
- **segment**：`## 一、xxx`（一级章节）或 `### 2.1 xxx`（子章节）触发新 segment，子章节优先；含"投资视角总结/总结/风险"的尾章跳过；segment id 按出现顺序生成 `seg-01, seg-02, ...`，中文名存 `name`；
- **标的表格**：识别连续 `|...|` 行，首行为表头。列定位（按表头关键词）：代码列含"代码"；名称列含"标的"或"股票"；关系列含"关系"或"核心逻辑"或"竞争地位"；认证列含"认证"或"供货状态"；弹性列含"弹性"；
- **elasticity 映射**：⭐⭐⭐⭐⭐/⭐⭐⭐⭐ → `core`，⭐⭐⭐ → `elastic`，⭐⭐ 及以下或无星 → `concept`；
- **cert_status**：认证列文本含"已供货"→ `"已供货"`，含"测试"→ `"测试中"`，否则 None；
- 表格中 **加粗标记（`**北方华创**`）** 剥离。

- [ ] **Step 1: 写失败测试**

```python
# tests/investment_engine/test_migrate.py
"""深度研究 md 解析器测试（合成样例仿方向一结构）。"""
from investment_engine.industry_chain.migrate import elasticity_from_stars, parse_research_md

SAMPLE_MD = """# 方向X：测试产业链全景梳理（深度版）

> 背景：测试背景。
>
> **一句话核心逻辑**：需求爆发 → 产能倾斜 → 涨价轮动 → 全链受益。本次梳理按"上游→中游"展开。

---

## 一、赛道一：上游材料（弹性最大）

| 标的 | 代码 | 核心产品 | 与链主关系 | 弹性评估 |
|---------|------|---------|-----------|---------|
| **雅克科技** | 002409 | 前驱体 | 占采购量15%-20% | ⭐⭐⭐⭐⭐ |
| 兴发集团 | 600141 | 电子级硫酸 | 供应商 | ⭐⭐⭐ |

**投资要点**：略。

## 二、赛道二：中游设备

### 2.1 刻蚀设备

| 标的 | 代码 | 核心产品 | 与链主关系 | 认证状态 | 弹性评估 |
|------|------|---------|-----------|---------|---------|
| 北方华创 | 002371 | 刻蚀设备 | 批量导入产线 | 已供货 | ⭐⭐⭐⭐ |
| 麦捷科技 | 300319 | 配套元件 | 导入中 | 测试中 | ⭐⭐ |

## 七、投资视角总结

### 7.1 核心标的 vs 高弹性标的

| 层级 | 标的 |
|------|------|
| 核心 | 雅克科技 |
"""


class TestElasticityFromStars:
    def test_five_star_is_core(self):
        assert elasticity_from_stars("⭐⭐⭐⭐⭐") == "core"

    def test_four_star_is_core(self):
        assert elasticity_from_stars("⭐⭐⭐⭐") == "core"

    def test_three_star_is_elastic(self):
        assert elasticity_from_stars("⭐⭐⭐") == "elastic"

    def test_low_or_empty_is_concept(self):
        assert elasticity_from_stars("⭐⭐") == "concept"
        assert elasticity_from_stars("") == "concept"


class TestParseResearchMd:
    def setup_method(self):
        self.chain = parse_research_md(
            SAMPLE_MD, chain_id="test-chain", name="测试产业链", verified="2026-05-18"
        )

    def test_thesis_extracted(self):
        assert self.chain["thesis"].startswith("需求爆发")

    def test_segments_from_sections(self):
        names = [s["name"] for s in self.chain["segments"]]
        assert "赛道一：上游材料（弹性最大）" in names
        assert "刻蚀设备" in names  # 子章节优先于"赛道二：中游设备"
        assert not any("总结" in n for n in names)  # 尾章跳过

    def test_segment_ids_are_slugs(self):
        ids = [s["id"] for s in self.chain["segments"]]
        assert ids == ["seg-01", "seg-02", "seg-03"]

    def test_mappings_extracted(self):
        mappings = {m["code"]: m for m in self.chain["mappings"]}
        assert set(mappings) == {"002409", "600141", "002371", "300319"}
        yake = mappings["002409"]
        assert yake["name"] == "雅克科技"  # 加粗已剥离
        assert yake["elasticity"] == "core"
        assert "15%-20%" in yake["relation"]

    def test_subsection_ownership(self):
        """子章节表格归属子章节 segment，不是父章节。"""
        mappings = {m["code"]: m for m in self.chain["mappings"]}
        seg_by_id = {s["id"]: s for s in self.chain["segments"]}
        assert seg_by_id[mappings["002371"]["segment"]]["name"] == "刻蚀设备"

    def test_cert_status(self):
        mappings = {m["code"]: m for m in self.chain["mappings"]}
        assert mappings["002371"]["cert_status"] == "已供货"
        assert mappings["300319"]["cert_status"] == "测试中"
        assert mappings["002409"]["cert_status"] is None  # 无认证列

    def test_summary_tables_skipped(self):
        """投资视角总结章的表格（无代码列）不得产生 mappings。"""
        codes = [m["code"] for m in self.chain["mappings"]]
        assert len(codes) == 4  # 总结表里的"雅克科技"不会重复进来

    def test_output_passes_schema(self):
        from investment_engine.industry_chain.schema import validate_chain

        assert validate_chain(self.chain) is self.chain
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/pytest tests/investment_engine/test_migrate.py -v`
Expected: FAIL，`ModuleNotFoundError`

- [ ] **Step 3: 实现解析器**

```python
# src/investment_engine/industry_chain/migrate.py
"""把 docs/标的深度研究 的 md 报告解析为 chain dict（过 schema 校验）。

解析规则见 v2.1 计划 Task 4。散文形式的 value_share/barrier/landscape
不在源文档表格里，迁移后如实为 None，由 5.5 节的维护分工补齐。
"""
from __future__ import annotations

import re

STAR_RE = re.compile(r"⭐")
SECTION_RE = re.compile(r"^##\s+[一二三四五六七八九十]+、\s*(.+?)\s*$")
SUBSECTION_RE = re.compile(r"^###\s+\d+(?:\.\d+)?\s+(.+?)\s*$")
ROW_RE = re.compile(r"^\|(.+)\|\s*$")
BOLD_RE = re.compile(r"\*\*([^*]+)\*\*")
THESIS_RE = re.compile(r"一句话核心逻辑[*\s：:]*(.+?)\s*$")
SKIP_WORDS = ("总结", "风险", "操作手册", "催化")


def elasticity_from_stars(text: str) -> str:
    n = len(STAR_RE.findall(text or ""))
    if n >= 4:
        return "core"
    if n == 3:
        return "elastic"
    return "concept"


def _clean(cell: str) -> str:
    cell = BOLD_RE.sub(r"\1", cell)
    return cell.strip().strip("*").strip()


def _split_row(line: str) -> list[str]:
    return [_clean(c) for c in line.strip().strip("|").split("|")]


def _is_separator_row(cells: list[str]) -> bool:
    return all(set(c) <= set("-: ") for c in cells)


def _find_col(header: list[str], *keywords: str) -> int | None:
    for i, h in enumerate(header):
        if any(k in h for k in keywords):
            return i
    return None


def _cert_from(text: str) -> str | None:
    if "已供货" in text:
        return "已供货"
    if "测试" in text:
        return "测试中"
    return None


def parse_research_md(
    text: str,
    *,
    chain_id: str,
    name: str,
    verified: str,
) -> dict:
    """解析深度研究 md，返回过 schema 的 chain dict。"""
    thesis = ""
    for ln in text.splitlines():
        m = THESIS_RE.search(ln)
        if m:
            thesis = _clean(m.group(1))
            break

    segments: list[dict] = []
    mappings: list[dict] = []
    current_seg_id: str | None = None
    skip_section = False
    seen_codes: set[str] = set()

    def new_segment(seg_name: str) -> None:
        nonlocal current_seg_id
        seg_id = f"seg-{len(segments) + 1:02d}"
        segments.append({
            "id": seg_id, "name": seg_name, "value_share": None, "barrier": None,
            "landscape": None, "growth": None, "status": None, "last_verified": None,
        })
        current_seg_id = seg_id

    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]

        m = SECTION_RE.match(line)
        if m:
            title = m.group(1).strip()
            skip_section = any(w in title for w in SKIP_WORDS)
            current_seg_id = None if skip_section else current_seg_id
            if not skip_section:
                new_segment(title)
            i += 1
            continue

        m = SUBSECTION_RE.match(line)
        if m and not skip_section:
            title = m.group(1).strip()
            if not any(w in title for w in SKIP_WORDS):
                new_segment(title)
            i += 1
            continue

        if ROW_RE.match(line) and not skip_section and current_seg_id:
            header = _split_row(line)
            code_col = _find_col(header, "代码")
            if code_col is not None:
                name_col = _find_col(header, "标的", "股票", "名称")
                rel_col = _find_col(header, "关系", "核心逻辑", "竞争地位", "逻辑")
                cert_col = _find_col(header, "认证", "供货状态")
                ela_col = _find_col(header, "弹性")
                i += 1
                while i < len(lines) and ROW_RE.match(lines[i]):
                    cells = _split_row(lines[i])
                    i += 1
                    if _is_separator_row(cells) or len(cells) <= code_col:
                        continue
                    code = cells[code_col]
                    if not re.fullmatch(r"\d{6}", code) or code in seen_codes:
                        continue
                    seen_codes.add(code)

                    def cell(col: int | None) -> str:
                        return cells[col] if col is not None and col < len(cells) else ""

                    mappings.append({
                        "code": code,
                        "name": cell(name_col),
                        "segment": current_seg_id,
                        "relation": cell(rel_col),
                        "cert_status": _cert_from(cell(cert_col)),
                        "order_evidence": None,
                        "elasticity": elasticity_from_stars(cell(ela_col)),
                        "elasticity_reason": None,
                        "last_verified": verified,
                    })
                continue
        i += 1

    chain = {
        "chain_id": chain_id,
        "name": name,
        "thesis": thesis,
        "last_verified": verified,
        "segments": segments,
        "mappings": mappings,
    }

    from investment_engine.industry_chain.schema import validate_chain

    return validate_chain(chain)
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/pytest tests/investment_engine/test_migrate.py -v`
Expected: 10 passed

- [ ] **Step 5: Commit（经用户确认）**

```bash
git add src/investment_engine/industry_chain/migrate.py tests/investment_engine/test_migrate.py
git commit -m "feat(industry_chain): 深度研究 md → chain 解析器"
```

---

## Task 5: 迁移 CLI 与存量 3 篇迁移

**Files:**
- Create: `scripts/migrate_industry_chains.py`
- Create（产出）: `knowledge/industry-chains/changxin-dram/{chain.yaml, research.md}`
- Create（产出）: `knowledge/industry-chains/domestic-compute/{chain.yaml, research.md}`
- Create（产出）: `knowledge/industry-chains/ai-infra-energy/{chain.yaml, research.md}`

- [ ] **Step 1: 写 CLI**

```python
#!/usr/bin/env python
"""把 docs/标的深度研究 的存量报告迁移为产业链知识库（v2.1 M0）。

用法: python scripts/migrate_industry_chains.py [--dry-run]
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from investment_engine.industry_chain.migrate import parse_research_md
from investment_engine.industry_chain.store import default_base_dir, save_chain

RESEARCH_DIR = Path(__file__).resolve().parent.parent / "docs" / "标的深度研究"

# (chain_id, name, 源文件名, last_verified)
SOURCES = [
    ("changxin-dram", "长鑫存储产业链", "方向一：长鑫存储产业链全景梳理-20260518.md", "2026-05-18"),
    ("domestic-compute", "国产算力产业链", "方向二：国产算力产业链与Token经济学深度梳理-20260518.md", "2026-05-18"),
    ("ai-infra-energy", "AI基础设施与能源转型产业链", "方向三：AI基础设施与能源转型产业链梳理-20260518.md", "2026-05-18"),
]


def main(argv: list[str] | None = None) -> int:
    dry_run = "--dry-run" in (argv or sys.argv[1:])
    base = default_base_dir()
    for chain_id, name, filename, verified in SOURCES:
        src = RESEARCH_DIR / filename
        text = src.read_text(encoding="utf-8")
        chain = parse_research_md(text, chain_id=chain_id, name=name, verified=verified)
        n_seg, n_map = len(chain["segments"]), len(chain["mappings"])
        print(f"[{chain_id}] segments={n_seg} mappings={n_map} thesis={chain['thesis'][:40]}...")
        if n_map == 0:
            print(f"  !! 警告: {filename} 未解析到任何标的，检查解析规则")
            continue
        if dry_run:
            continue
        save_chain(chain, base_dir=base, expect_id=chain_id)
        shutil.copy2(src, base / chain_id / "research.md")
        print(f"  -> 已写入 {base / chain_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: dry-run 验证解析**

Run: `.venv/bin/python scripts/migrate_industry_chains.py --dry-run`
Expected: 三条输出，`mappings` 均 > 0（方向一预期 ~25+，方向二 ~20+，方向三 ~15+；为 0 或明显偏少则回 Task 4 修解析规则）

- [ ] **Step 3: 正式迁移并抽查产出**

Run: `.venv/bin/python scripts/migrate_industry_chains.py`
然后：
```bash
.venv/bin/python -c "
import sys; sys.path.insert(0, 'src')
from investment_engine.industry_chain.store import list_chains, load_chain
print(list_chains())
c = load_chain('changxin-dram')
print(c['thesis'][:60])
print([s['name'] for s in c['segments']][:6])
print([m['name'] for m in c['mappings']][:8])
"
```
Expected: `['ai-infra-energy', 'changxin-dram', 'domestic-compute']`；长鑫链 segments 含"赛道一：股权关联方""刻蚀设备"等；mappings 含 兆易创新/北方华创/雅克科技。**人工抽查 3 个标的与原文表格一致**（打开 `knowledge/industry-chains/changxin-dram/research.md` 对照）。

- [ ] **Step 4: Commit（经用户确认）**

```bash
git add scripts/migrate_industry_chains.py knowledge/industry-chains
git commit -m "feat(industry_chain): 迁移存量 3 篇深度研究入产业链知识库"
```

---

## Task 6: 来源中立推理模式校验器

**Files:**
- Create: `src/investment_engine/distill/pattern_schema.py`
- Test: `tests/investment_engine/test_pattern_schema.py`

设计决策：校验器是"来源中立"的机械保证——`steps[].action` 与 `falsification[]` 中**禁止出现** `UP|青枫浦|博主`；`validation` 区块三子字段（`historical_hit_rate / applicable_regime / known_failures`）必须存在，值允许 `null` 或 `"pending-m1"`（LLM 类模式的命中率待 M1 盲测回填，如实标注）。

- [ ] **Step 1: 写失败测试**

```python
# tests/investment_engine/test_pattern_schema.py
"""来源中立推理模式校验器测试。"""
import pytest

from investment_engine.distill.pattern_schema import PatternSchemaError, validate_pattern


def _valid_pattern() -> dict:
    return {
        "pattern_id": "upstream_cycle",
        "name": "上游涨价周期分析框架",
        "description": "当上游出现涨价信号时使用……",
        "trigger": [
            "上游核心品类出现涨价函或现货价连续上行（数据特征，非谁说了什么）",
            "主线核心资产进入高位轮动",
        ],
        "data_requirements": [
            {"name": "环节价值量", "channel": "研报 / knowledge/industry-chains"},
            {"name": "涨价函与现货价", "channel": "公告 / 生意社等公开价格源"},
        ],
        "steps": [
            {"step": 1, "name": "确认涨价真实性",
             "question": "涨价是个别行为还是行业性？",
             "action": "核对涨价函数量、现货价曲线与库存数据，三者至少两者同向才进入下一步",
             "data": ["涨价函与现货价"]},
        ],
        "falsification": ["现货价连续 2 周回落", "下游龙头公开抵制或去库存"],
        "validation": {
            "historical_hit_rate": None,
            "applicable_regime": None,
            "known_failures": [],
            "confidence_indicators": ["多家厂商同步涨价", "库存低位"],
        },
        "applicable_themes": ["MLCC", "存储"],
        "source_raw": ["sources/raw/财经/复盘：26-05-31：xxx.md"],
        "examples": [],
        "merged_from": [],
    }


class TestValidatePattern:
    def test_valid_pattern_passes(self):
        assert validate_pattern(_valid_pattern()) == _valid_pattern()

    def test_missing_field_rejected(self):
        p = _valid_pattern()
        del p["trigger"]
        with pytest.raises(PatternSchemaError, match="trigger"):
            validate_pattern(p)

    def test_up_reference_in_action_rejected(self):
        """来源中立的核心机械保证：action 不得引用 UP。"""
        p = _valid_pattern()
        p["steps"][0]["action"] = "按 UP 的判断，涨价周期启动"
        with pytest.raises(PatternSchemaError, match="UP"):
            validate_pattern(p)

    def test_up_reference_in_falsification_rejected(self):
        p = _valid_pattern()
        p["falsification"] = ["博主转谨慎"]
        with pytest.raises(PatternSchemaError):
            validate_pattern(p)

    def test_up_reference_in_trigger_rejected(self):
        p = _valid_pattern()
        p["trigger"] = ["UP 看好程度上升"]
        with pytest.raises(PatternSchemaError):
            validate_pattern(p)

    def test_source_raw_may_keep_traceability(self):
        """source_raw 保留溯源是允许的（校验不查它）。"""
        p = _valid_pattern()
        p["source_raw"] = ["sources/raw/财经/复盘：26-05-31：UP 原文.md"]
        assert validate_pattern(p) == p

    def test_validation_subfields_required(self):
        p = _valid_pattern()
        del p["validation"]["known_failures"]
        with pytest.raises(PatternSchemaError, match="known_failures"):
            validate_pattern(p)

    def test_hit_rate_pending_m1_allowed(self):
        p = _valid_pattern()
        p["validation"]["historical_hit_rate"] = "pending-m1"
        assert validate_pattern(p) == p

    def test_step_data_must_reference_requirement(self):
        p = _valid_pattern()
        p["steps"][0]["data"] = ["不存在的数据项"]
        with pytest.raises(PatternSchemaError, match="不存在的数据项"):
            validate_pattern(p)

    def test_data_requirement_needs_channel(self):
        p = _valid_pattern()
        p["data_requirements"] = [{"name": "环节价值量"}]
        with pytest.raises(PatternSchemaError, match="channel"):
            validate_pattern(p)
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/pytest tests/investment_engine/test_pattern_schema.py -v`
Expected: FAIL，`ModuleNotFoundError`

- [ ] **Step 3: 实现校验器**

```python
# src/investment_engine/distill/pattern_schema.py
"""来源中立推理模式的 schema 校验（v2.1 引擎⓪ 的机械保证）。

核心规则：
- 决策字段（trigger/steps[].action/falsification）禁止出现 UP/青枫浦/博主——
  触发条件必须是客观数据特征，不是"谁说了什么"；
- source_raw 保留溯源，不受此限；
- validation 区块三子字段必须存在，historical_hit_rate 允许 null / 数值 / "pending-m1"。
"""
from __future__ import annotations

import re

REQUIRED_FIELDS = (
    "pattern_id", "name", "description", "trigger",
    "data_requirements", "steps", "falsification", "validation",
)
VALIDATION_FIELDS = ("historical_hit_rate", "applicable_regime", "known_failures")
REQUIRED_STEP_FIELDS = ("step", "name", "question", "action")
FORBIDDEN_RE = re.compile(r"UP|青枫浦|博主")


class PatternSchemaError(ValueError):
    """推理模式结构或取值不合法。"""


def _check_neutral(value, where: str, errors: list[str]) -> None:
    texts: list[str] = []
    if isinstance(value, str):
        texts.append(value)
    elif isinstance(value, list):
        texts.extend(str(v) for v in value)
    for t in texts:
        m = FORBIDDEN_RE.search(t)
        if m:
            errors.append(f"{where}: 决策字段必须来源中立，禁止出现 {m.group(0)!r}（{t[:30]}…）")


def validate_pattern(data: dict) -> dict:
    if not isinstance(data, dict):
        raise PatternSchemaError("模式顶层必须是 mapping")

    errors: list[str] = []
    for field in REQUIRED_FIELDS:
        if field not in data:
            errors.append(f"缺必填字段: {field}")
    if errors:
        raise PatternSchemaError("; ".join(errors))

    _check_neutral(data.get("trigger"), "trigger", errors)
    _check_neutral(data.get("falsification"), "falsification", errors)

    req_names: set[str] = set()
    for i, req in enumerate(data.get("data_requirements") or []):
        if not isinstance(req, dict) or "name" not in req:
            errors.append(f"data_requirements[{i}]: 缺 name")
            continue
        if not req.get("channel"):
            errors.append(f"data_requirements[{i}] ({req['name']}): 缺 channel")
        req_names.add(req["name"])

    for i, step in enumerate(data.get("steps") or []):
        for field in REQUIRED_STEP_FIELDS:
            if field not in step:
                errors.append(f"steps[{i}]: 缺 {field}")
        _check_neutral(step.get("action", ""), f"steps[{i}].action", errors)
        for ref in step.get("data") or []:
            if ref not in req_names:
                errors.append(f"steps[{i}].data: {ref!r} 不在 data_requirements 中")

    validation = data.get("validation") or {}
    for field in VALIDATION_FIELDS:
        if field not in validation:
            errors.append(f"validation: 缺 {field}")
    rate = validation.get("historical_hit_rate")
    if rate is not None and rate != "pending-m1" and not isinstance(rate, (int, float)):
        errors.append(f"validation.historical_hit_rate 必须是 null / 数值 / 'pending-m1'，得到 {rate!r}")

    if errors:
        raise PatternSchemaError("; ".join(errors))
    return data


def validate_patterns_file(data: dict) -> dict:
    """校验整份 reasoning-patterns.yaml（顶层含 patterns 列表）。"""
    patterns = (data or {}).get("patterns")
    if not isinstance(patterns, list) or not patterns:
        raise PatternSchemaError("patterns 必须是非空列表")
    for p in patterns:
        validate_pattern(p)
    return data
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/pytest tests/investment_engine/test_pattern_schema.py -v`
Expected: 10 passed

- [ ] **Step 5: Commit（经用户确认）**

```bash
git add src/investment_engine/distill/pattern_schema.py tests/investment_engine/test_pattern_schema.py
git commit -m "feat(distill): 来源中立推理模式校验器"
```

---

## Task 7: 备份 + upstream_cycle 完整改写（改写范式示例）

**Files:**
- Create: `framework/reasoning-patterns-v2.1-up-anchored.yaml`（当前版备份，git mv 语义用 cp）
- Modify: `framework/reasoning-patterns.yaml`（patterns[0] upstream_cycle，行 5-330）

改写映射规则（适用于本任务及 Task 8-10 全部框架）：

| 原字段 | 新字段 | 规则 |
|---|---|---|
| `description` | `description` | 原样保留（语义匹配要用），仅删除其中"UP/博主"指称 |
| `reasoning_chain[].UP_logic` | `steps[].action` | 改写为来源中立的祈使句：把"UP 认为/UP 会看"改为"核对/比较/计算 X 数据"；保留推理实质，去掉人 |
| `reasoning_chain[].question` | `steps[].question` | 原样保留 |
| `reasoning_chain[].evidence_sources` | `data_requirements` | 去重合并为 `{name, channel}`；每步用 `steps[].data` 引用 |
| （新增） | `trigger` | 从 description 的"何时使用"部分提炼为客观数据特征列表 |
| `risk_factors` | `falsification` | 转写为可观察的证伪条件（"风险是 X"→"X 数据出现 Y 特征时判失效"） |
| `confidence_indicators` | `validation.confidence_indicators` | 原样保留 |
| （新增） | `validation.historical_hit_rate / applicable_regime / known_failures` | 初值 `null / null / []`；LLM 类模式标 `"pending-m1"` |
| `source_raw / applicable_themes / examples / merged_from` | 同名保留 | 溯源与检索信息不动；examples 内嵌的 UP_logic 属历史档案，**不改**（校验器只查顶层决策字段） |

- [ ] **Step 1: 备份当前版**

```bash
cp framework/reasoning-patterns.yaml framework/reasoning-patterns-v2.1-up-anchored.yaml
```

- [ ] **Step 2: 改写 upstream_cycle**

读 `framework/reasoning-patterns.yaml` 行 5-330，按映射规则改写。改写后条目骨架（内容以原文为准展开，以下是必须遵守的结构与风格约束，**字段完整、action 为祈使句**）：

```yaml
  - pattern_id: upstream_cycle
    name: 上游涨价周期分析框架
    description: （原文保留，去 UP 指称）
    trigger:
      - （客观数据特征，如"上游核心品类出现涨价函或现货价连续上行"）
    data_requirements:
      - name: 环节价值量与 BOM 结构
        channel: 研报 / knowledge/industry-chains
      # …按原文 evidence_sources 去重展开
    steps:
      - step: 1
        name: （原名保留）
        question: （原 question 保留）
        action: （UP_logic 的来源中立改写，祈使句）
        data: [（引用 data_requirements 的 name）]
    falsification:
      - （risk_factors 转写为可观察条件）
    validation:
      historical_hit_rate: pending-m1
      applicable_regime: null
      known_failures: []
      confidence_indicators: （原文保留）
    applicable_themes: （原文保留）
    source_raw: （原文保留）
    examples: （原文保留，不改）
    merged_from: （原文保留）
```

注意：上游涨价周期框架是"涨价链"核心，其 data_requirements 必须有一条指向产业链知识库（`knowledge/industry-chains`），落实 v2.1 第五节"模式提供推理步骤，知识库提供事实"。

- [ ] **Step 3: 校验**

```bash
.venv/bin/python -c "
import sys, yaml; sys.path.insert(0, 'src')
from investment_engine.distill.pattern_schema import validate_pattern
data = yaml.safe_load(open('framework/reasoning-patterns.yaml', encoding='utf-8'))
validate_pattern(data['patterns'][0])
print('upstream_cycle OK')
"
```
Expected: `upstream_cycle OK`（其余 9 个框架此时尚未改写，只校验 patterns[0]）

- [ ] **Step 4: Commit（经用户确认）**

```bash
git add framework/reasoning-patterns.yaml framework/reasoning-patterns-v2.1-up-anchored.yaml
git commit -m "refactor(distill): upstream_cycle 来源中立改写 + 改写前备份"
```

---

## Task 8: 改写 mainline_identification / sector_rotation / macro_transmission

**Files:**
- Modify: `framework/reasoning-patterns.yaml`（patterns[1] 行 331-834，patterns[2] 行 835-1136，patterns[3] 行 1137-1415）

- [ ] **Step 1: 按 Task 7 映射规则改写三个框架**

各框架的针对性要点（执行时先读原文再动笔）：
- `mainline_identification`（市场主线识别）：trigger 用"板块成交额占比/涨幅持续性/龙头股梯队完整度"等量能数据；UP 的"主线三信号"类判断改写为对这三个数据项的核对步骤；
- `sector_rotation`（板块轮动与扩散）：这是 BOM 扩散所在框架——`data_requirements` 必须含 `knowledge/industry-chains` 通道；扩散筛选四问（价值量增幅/供给壁垒/位置/订单验证）写成对知识库字段的查询步骤；
- `macro_transmission`（宏观传导链）：trigger 用宏观数据发布/汇率利率变动等客观事件。

- [ ] **Step 2: 校验三个框架**

```bash
.venv/bin/python -c "
import sys, yaml; sys.path.insert(0, 'src')
from investment_engine.distill.pattern_schema import validate_pattern
data = yaml.safe_load(open('framework/reasoning-patterns.yaml', encoding='utf-8'))
for i in (1, 2, 3):
    validate_pattern(data['patterns'][i])
    print(data['patterns'][i]['pattern_id'], 'OK')
"
```
Expected: 三行 OK

- [ ] **Step 3: Commit（经用户确认）**

```bash
git add framework/reasoning-patterns.yaml
git commit -m "refactor(distill): mainline/rotation/macro 三框架来源中立改写"
```

---

## Task 9: 改写 sentiment_cycle / technical_timing / earnings_analysis

**Files:**
- Modify: `framework/reasoning-patterns.yaml`（patterns[4] 行 1416-1616，patterns[5] 行 1617-1758，patterns[6] 行 1759-1899）

- [ ] **Step 1: 按映射规则改写三个框架**

针对性要点：
- `sentiment_cycle`（情绪周期）：trigger 与 steps 引用术语词典的客观定义（冰点/炸板率/缩容炒作，见 Task 11 产物 `framework/up-glossary.md`）；若 Task 11 未完成，先用文中定义、完成后再对齐；
- `technical_timing`（技术择时）：数据通道指 K 线缓存（`infra/data/kline_cache.db`）；
- `earnings_analysis`（业绩拆解）：数据通道指 `financial_reports` 表（`get_financial_reports`，`kline_cache.py:260`）。

- [ ] **Step 2: 校验（同 Task 8 Step 2，索引 4/5/6）**
Expected: 三行 OK

- [ ] **Step 3: Commit（经用户确认）**

```bash
git add framework/reasoning-patterns.yaml
git commit -m "refactor(distill): sentiment/technical/earnings 三框架来源中立改写"
```

---

## Task 10: 改写 ai_industry_chain / operation_strategy / others + 全量校验

**Files:**
- Modify: `framework/reasoning-patterns.yaml`（patterns[7] 行 1900-2045，patterns[8] 行 2046-2166，patterns[9] 行 2167-2250）

- [ ] **Step 1: 按映射规则改写三个框架**

针对性要点：
- `ai_industry_chain`（AI 产业链传导）：与 Task 5 迁移的三个 chain 直接挂钩——`data_requirements` 首条必须是 `{"name": "AI 产业链结构与标的映射", "channel": "knowledge/industry-chains"}`；
- `operation_strategy`（操作策略与仓位）：仓位规则必须与 v2.1 文档一致（仓位% = 单笔风险上限% ÷ 止损幅度%；三层上限 10%/20%/30%），不得自创；
- `others`：剩余独立模式逐条判断——能来源中立化的改写，纯 UP 个人习惯无法客观化的，`validation.known_failures` 注明"依赖信息层，待能力边界标注"。

- [ ] **Step 2: 全量校验（M0 验收判据之一）**

```bash
.venv/bin/python -c "
import sys, yaml; sys.path.insert(0, 'src')
from investment_engine.distill.pattern_schema import validate_patterns_file
data = yaml.safe_load(open('framework/reasoning-patterns.yaml', encoding='utf-8'))
validate_patterns_file(data)
print('全部', len(data['patterns']), '个框架通过来源中立校验')
"
```
Expected: `全部 10 个框架通过来源中立校验`

- [ ] **Step 3: 头部 metadata 更新**

把 `framework/reasoning-patterns.yaml` 头部改为：

```yaml
updated_at: '2026-08-08'
version: 3.0-source-neutral
merge_note: 将116个单raw模式聚合为10个通用推理框架，并优化description以支持语义匹配
distill_note: v3.0 来源中立改写（v2.1 引擎⓪）——trigger/steps/falsification 不含 UP 指称，
  validation 区块随回测与盲测回填；UP 锚定版备份见 reasoning-patterns-v2.1-up-anchored.yaml。
```

改完重跑 Step 2 的全量校验确认仍通过。

- [ ] **Step 4: Commit（经用户确认）**

```bash
git add framework/reasoning-patterns.yaml
git commit -m "refactor(distill): 10 框架全部来源中立化，version 3.0"
```

---

## Task 11: UP 术语词典

**Files:**
- Create: `framework/up-glossary.md`

- [ ] **Step 1: 写词典（完整内容如下，术语定义依据 `framework/market-cycle-framework.md`、`sector-diffusion-framework.md` 及 reasoning-patterns 原文；执行时对读一遍原文件核对表述）**

````markdown
# UP 术语词典（来源中立版）

> v2.1 引擎⓪ 产物：UP 的概念体系与方法论骨架解耦——概念是描述市场的语言，谁都能用；
> 每个术语给出**客观数据定义**与**数据通道**，推理引擎按定义计算，不依赖 UP 本人的使用方式。

| 术语 | 客观数据定义 | 数据通道 |
|---|---|---|
| 冰点 | 情绪周期极值点：全市场涨停家数、连板高度、成交额同步处近期（如 20 日）最低区间 | 东财涨停池 + 成交额（K 线缓存 / market_sentiment） |
| 炸板率 | 当日触及涨停后打开未回封家数 ÷ 当日触及涨停总家数 | 东财涨停池/炸板数据 |
| 缩容炒作 | 成交额萎缩环境下，资金集中于极少数题材/小市值标的，板块内上涨家数占比显著下降 | 板块成交额占比 + 上涨家数占比 |
| 高低切 | 主线核心高位滞涨时，资金流向同产业链低位环节的切换；识别特征：核心滞涨 + 低位环节放量启动 | 产业链知识库环节映射 + 各环节代表标的量价 |
| 活口 | 板块强分歧日中仍封住涨停或收阳的板块内个股 | 涨停池 + 个股日 K |
| 承接 | 急跌/分歧时下方买盘力量的观察：下杀后分时拉回幅度与量能配合 | 分时/日 K 量价（K 线缓存） |
| 分歧 | 主线内部涨跌不一、炸板率抬升、核心放量滞涨的交易日状态 | 炸板率 + 核心标的量价 |
| 逼空 | 主线连续缩量上涨、分歧日少、踏空资金被动追高的单边状态 | 板块指数量价 + 炸板率 |
| 扩散 | 主线赚钱效应从核心环节向同产业链其他环节蔓延（三阶段：核心→同链低位→小市值题材） | 产业链知识库 + 各环节涨幅/量能排序 |
| 外溢 | 资金离开主线核心流向非主线方向；与"主线否定"的区别：核心是否同步破位 | 主线核心标的量价 vs 非主线板块资金流 |

## 使用规则

1. 推理模式引用术语时，以本表定义为准，不允许自由发挥；
2. 定义依赖的数据通道缺失时，报告标注"该术语本轮不可判定"，不得编造数值；
3. 新术语加入须经盲测期归因（概念误用型）驱动，先加定义再使用。
````

- [ ] **Step 2: 交叉核对**

逐一打开 `framework/market-cycle-framework.md` 与 `framework/sector-diffusion-framework.md`，核对 10 个术语的定义与仓库原有用法不冲突；有冲突的以"客观可计算"为准修订词典条目（仓库原文多为定性描述，词典是给机器用的客观化版本）。

- [ ] **Step 3: Commit（经用户确认）**

```bash
git add framework/up-glossary.md
git commit -m "docs(distill): UP 术语词典（来源中立客观定义）"
```

---

## Task 12: 历史区间数据访问与 quote_snapshot 重建

**Files:**
- Create: `src/investment_engine/backtest/history.py`
- Test: `tests/investment_engine/test_history.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/investment_engine/test_history.py
"""历史区间数据访问测试（db_path 注入隔离，同 test_kline_cache 惯例）。"""
import tempfile
from pathlib import Path

from qing_investment.kline_cache import init_db, save_klines
from investment_engine.backtest.history import (
    build_quote_snapshot, coverage, get_klines_range, list_trading_days, quote_from_kline,
)


def _klines(code: str, dates: list[str], base: float = 10.0) -> list[dict]:
    return [
        {"code": code, "date": d, "open": base, "high": base + 0.5, "low": base - 0.5,
         "close": base + i * 0.1, "volume": 1000, "turnover": 1.5,
         "amplitude": 5.0, "pct_change": 1.0}
        for i, d in enumerate(dates)
    ]


class TestHistory:
    def setup_method(self):
        self.db_path = Path(tempfile.gettempdir()) / f"test_hist_{id(self)}.db"
        init_db(db_path=self.db_path)
        save_klines("002371", _klines("002371", ["2026-07-01", "2026-07-02", "2026-07-03"]), db_path=self.db_path)
        save_klines("603986", _klines("603986", ["2026-07-02", "2026-07-03"], base=100.0), db_path=self.db_path)

    def teardown_method(self):
        self.db_path.unlink(missing_ok=True)

    def test_get_klines_range(self):
        rows = get_klines_range("002371", "2026-07-01", "2026-07-02", db_path=self.db_path)
        assert [r["date"] for r in rows] == ["2026-07-01", "2026-07-02"]
        assert rows[0]["close"] == 10.0

    def test_get_klines_range_empty(self):
        assert get_klines_range("999999", "2026-07-01", "2026-07-02", db_path=self.db_path) == []

    def test_list_trading_days_uses_cache_presence(self):
        """交易日由缓存里实际存在的日期决定，不需要交易日历。"""
        days = list_trading_days("2026-07-01", "2026-07-31", db_path=self.db_path)
        assert days == ["2026-07-01", "2026-07-02", "2026-07-03"]

    def test_coverage(self):
        cov = coverage(db_path=self.db_path)
        assert cov["002371"] == ("2026-07-01", "2026-07-03")
        assert cov["603986"] == ("2026-07-02", "2026-07-03")

    def test_quote_from_kline_matches_rule_engine_contract(self):
        """重建的 quote 必须符合 test_e2e mock_quote_snapshot 的字段契约。"""
        kline = _klines("603986", ["2026-07-03"], base=100.0)[0]
        q = quote_from_kline("603986.SH", "兆易创新", kline)
        assert q["code"] == "1.603986"      # 沪市 secid
        assert q["name"] == "兆易创新"
        assert q["latest"] == kline["close"]
        assert q["turnover_rate"] == 1.5

    def test_secid_market_prefix(self):
        kline = _klines("002371", ["2026-07-03"])[0]
        assert quote_from_kline("002371.SZ", "北方华创", kline)["code"] == "0.002371"
        assert quote_from_kline("600519.SH", "贵州茅台", kline)["code"] == "1.600519"

    def test_build_quote_snapshot(self):
        klines = _klines("002371", ["2026-07-03"])
        snapshot = build_quote_snapshot([quote_from_kline("002371.SZ", "北方华创", klines[0])])
        assert "quotes" in snapshot and len(snapshot["quotes"]) == 1
        assert snapshot["source"] == "kline_cache_backtest"


class TestSnapshotFeedsRuleEngine:
    """重建快照必须能被真实 BuySignalRuleEngine 消费（行为测试，驱动字段补全）。"""

    def setup_method(self):
        self.db_path = Path(tempfile.gettempdir()) / f"test_hist_eng_{id(self)}.db"
        init_db(db_path=self.db_path)

    def teardown_method(self):
        self.db_path.unlink(missing_ok=True)

    def test_snapshot_accepted_by_engine(self):
        from qing_investment.monitor.rules import BuySignalRuleEngine

        save_klines("002371", _klines("002371", ["2026-07-03"]), db_path=self.db_path)
        kline = get_klines_range("002371", "2026-07-03", "2026-07-03", db_path=self.db_path)[0]
        snapshot = build_quote_snapshot([quote_from_kline("002371.SZ", "北方华创", kline)])
        alerts = BuySignalRuleEngine().evaluate(
            {"watchlist": {"stocks": []}, "stock_pool": {"stocks": []}, "positions": {"accounts": []}},
            snapshot,
        )
        assert isinstance(alerts, list)  # 不报错、类型正确即通过
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/pytest tests/investment_engine/test_history.py -v`
Expected: FAIL，`ModuleNotFoundError`

- [ ] **Step 3: 实现 history.py**

```python
# src/investment_engine/backtest/history.py
"""按日期区间的历史数据访问（kline_cache 只支持"最近 N 日"，这里补区间查询）。

读路径纯 SQLite，无网络，可完全离线回放。
quote 字段契约对齐 monitor/tests/test_e2e.py 的 mock_quote_snapshot：
{"code": "1.600519"(secid), "name", "latest", "open", "high", "low",
 "volume", "amount", "pct_change", "turnover_rate"}。
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

_DEFAULT_DB = Path("infra/data/kline_cache.db")

_KLINE_COLS = (
    "trade_date AS date, open, high, low, close, volume, turnover, amplitude, pct_change"
)


def _connect(db_path: Path | None) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path or _DEFAULT_DB))
    conn.row_factory = sqlite3.Row
    return conn


def get_klines_range(
    code: str, start: str, end: str, db_path: Path | None = None
) -> list[dict]:
    """按日期区间取日 K（含首尾），date 升序。code 用缓存里的裸码（'002371'）。"""
    bare = code.split(".")[0]
    sql = (
        f"SELECT {_KLINE_COLS} FROM stocks_kline "
        "WHERE code = ? AND trade_date BETWEEN ? AND ? ORDER BY trade_date"
    )
    with _connect(db_path) as conn:
        rows = conn.execute(sql, (bare, start, end)).fetchall()
    return [dict(r) for r in rows]


def list_trading_days(start: str, end: str, db_path: Path | None = None) -> list[str]:
    """回测可用交易日 = 缓存里实际存在数据的日期（免交易日历）。"""
    sql = "SELECT DISTINCT trade_date FROM stocks_kline WHERE trade_date BETWEEN ? AND ? ORDER BY trade_date"
    with _connect(db_path) as conn:
        return [r[0] for r in conn.execute(sql, (start, end)).fetchall()]


def coverage(db_path: Path | None = None) -> dict[str, tuple[str, str]]:
    """各标的缓存日期范围 {code: (min_date, max_date)}。"""
    sql = "SELECT code, MIN(trade_date), MAX(trade_date) FROM stocks_kline GROUP BY code"
    with _connect(db_path) as conn:
        return {r[0]: (r[1], r[2]) for r in conn.execute(sql).fetchall()}


def _secid(code: str) -> str:
    """'600519.SH'/'600519' → '1.600519'；'002371.SZ' → '0.002371'。"""
    bare = code.split(".")[0]
    market = "1" if bare.startswith(("5", "6", "9")) else "0"
    return f"{market}.{bare}"


def quote_from_kline(code: str, name: str, kline: dict) -> dict:
    """由单日 K 线重建规则引擎可消费的 quote 条目。"""
    return {
        "code": _secid(code),
        "name": name,
        "latest": kline["close"],
        "open": kline["open"],
        "high": kline["high"],
        "low": kline["low"],
        "volume": kline["volume"],
        "amount": None,  # K 线表无成交额字段，如实为 None
        "pct_change": kline.get("pct_change"),
        "turnover_rate": kline.get("turnover"),
        "trade_date": kline["date"],
    }


def build_quote_snapshot(quotes: list[dict]) -> dict:
    return {"source": "kline_cache_backtest", "quotes": quotes}
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/pytest tests/investment_engine/test_history.py -v`
Expected: 9 passed。若 `test_snapshot_accepted_by_engine` 因引擎还读了 quote 其他字段而失败，读 `rules/__init__.py` 的 `_evaluate_candidates` 补字段到 `quote_from_kline`（K 线没有的字段给 None），不得改 qing_investment。

- [ ] **Step 5: Commit（经用户确认）**

```bash
git add src/investment_engine/backtest/history.py tests/investment_engine/test_history.py
git commit -m "feat(backtest): 历史区间 K 线查询与 quote_snapshot 重建"
```

---

## Task 13: 命中率统计

**Files:**
- Create: `src/investment_engine/backtest/hit_rate.py`
- Test: `tests/investment_engine/test_hit_rate.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/investment_engine/test_hit_rate.py
"""命中率统计测试。"""
from investment_engine.backtest.hit_rate import forward_return, summarize


def _klines(closes: list[float]) -> list[dict]:
    return [
        {"date": f"2026-07-{i + 1:02d}", "close": c, "open": c, "high": c, "low": c,
         "volume": 100, "turnover": 1.0, "amplitude": 1.0, "pct_change": 0.0}
        for i, c in enumerate(closes)
    ]


class TestForwardReturn:
    def test_basic(self):
        klines = _klines([10.0, 10.5, 11.0, 11.5, 12.0, 12.5])
        assert forward_return(klines, "2026-07-01", 5) == 12.5 / 10.0 - 1.0

    def test_insufficient_data_returns_none(self):
        klines = _klines([10.0, 10.5])
        assert forward_return(klines, "2026-07-01", 5) is None

    def test_unknown_date_returns_none(self):
        klines = _klines([10.0])
        assert forward_return(klines, "2026-08-01", 5) is None


class TestSummarize:
    def test_hit_rate_and_avg(self):
        records = [
            {"code": "a", "date": "d1", "returns": {5: 0.10, 10: 0.20}},
            {"code": "b", "date": "d1", "returns": {5: -0.05, 10: 0.05}},
            {"code": "c", "date": "d2", "returns": {5: 0.02, 10: None}},  # 10日数据不足
        ]
        stats = summarize(records, horizons=(5, 10))
        assert stats[5]["samples"] == 3
        assert stats[5]["hits"] == 2
        assert abs(stats[5]["hit_rate"] - 2 / 3) < 1e-9
        assert abs(stats[5]["avg_return"] - (0.10 - 0.05 + 0.02) / 3) < 1e-9
        assert stats[10]["samples"] == 2  # None 不计入样本

    def test_empty_records(self):
        stats = summarize([], horizons=(5,))
        assert stats[5]["samples"] == 0
        assert stats[5]["hit_rate"] is None
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/pytest tests/investment_engine/test_hit_rate.py -v`
Expected: FAIL，`ModuleNotFoundError`

- [ ] **Step 3: 实现 hit_rate.py**

```python
# src/investment_engine/backtest/hit_rate.py
"""信号命中率统计：信号日收盘 → 第 horizon 个交易日收盘的收益与汇总。"""
from __future__ import annotations


def forward_return(klines: list[dict], signal_date: str, horizon: int) -> float | None:
    """信号日（含）之后第 horizon 个交易日收盘价 / 信号日收盘价 - 1。数据不足返回 None。"""
    dates = [k["date"] for k in klines]
    if signal_date not in dates:
        return None
    i = dates.index(signal_date)
    j = i + horizon
    if j >= len(klines):
        return None
    base = klines[i]["close"]
    if not base:
        return None
    return klines[j]["close"] / base - 1.0


def summarize(records: list[dict], horizons: tuple[int, ...] = (5, 10, 20)) -> dict:
    """records: [{"code", "date", "returns": {horizon: float | None}}]。

    返回 {horizon: {"samples", "hits", "hit_rate", "avg_return"}}；
    returns 为 None 的（数据不足）不计入该 horizon 样本。
    """
    stats: dict[int, dict] = {}
    for h in horizons:
        values = [r["returns"][h] for r in records if r.get("returns", {}).get(h) is not None]
        hits = sum(1 for v in values if v > 0)
        stats[h] = {
            "samples": len(values),
            "hits": hits,
            "hit_rate": hits / len(values) if values else None,
            "avg_return": sum(values) / len(values) if values else None,
        }
    return stats
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/pytest tests/investment_engine/test_hit_rate.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit（经用户确认）**

```bash
git add src/investment_engine/backtest/hit_rate.py tests/investment_engine/test_hit_rate.py
git commit -m "feat(backtest): 信号前向收益与命中率统计"
```

---

## Task 14: 回测 CLI scripts/backtest_buy_signals.py

**Files:**
- Create: `scripts/backtest_buy_signals.py`

设计决策：标的池取 `stock_pool.yaml`（新结构，`stocks[].code/name`）；config dict 由 `load_monitor_config` 的各 yaml 组装（`{"watchlist": ..., "stock_pool": ..., "positions": ..., "strategy_pack": ...}`）；每个回测日只用**截至当日**的 K 线（防未来函数）；个股当日无缓存数据则跳过。

- [ ] **Step 1: 写 CLI**

```python
#!/usr/bin/env python
"""买入信号历史回测（v2.1 M0）：离线回放 BuySignalRuleEngine，统计命中率。

用法:
  python scripts/backtest_buy_signals.py --start 2026-03-01 --end 2026-07-31 \
      [--horizons 5,10,20] [--config-dir config/stock_monitor] \
      [--db infra/data/kline_cache.db] [--output logs/backtest_buy_signals_<date>.md]

只读 K 线缓存与配置 yaml，无网络调用；数据缺失如实标注，不编造。
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from investment_engine.backtest.history import (
    build_quote_snapshot, coverage, get_klines_range, list_trading_days, quote_from_kline,
)
from investment_engine.backtest.hit_rate import forward_return, summarize
from qing_investment.monitor.context import load_monitor_config
from qing_investment.monitor.rules import BuySignalRuleEngine

_LOOKBACK_DAYS = 60  # 重建快照时给引擎的截至当日历史窗口


def load_universe(config_dir: Path) -> list[dict]:
    """标的池：stock_pool.yaml（新结构）。返回 [{"code": "000636.SZ", "name": ...}]。"""
    cfg = load_monitor_config(config_dir)
    pool = cfg.stock_pool or {}
    return [
        {"code": s["code"], "name": s.get("name", "")}
        for s in pool.get("stocks", [])
        if s.get("code")
    ]


def build_engine_config(config_dir: Path) -> dict:
    cfg = load_monitor_config(config_dir)
    return {
        "watchlist": cfg.watchlist or {},
        "stock_pool": cfg.stock_pool or {},
        "positions": cfg.positions or {},
        "strategy_pack": cfg.strategy_pack or {},
    }


def run_backtest(
    config_dir: Path,
    db_path: Path,
    start: str,
    end: str,
    horizons: tuple[int, ...] = (5, 10, 20),
) -> dict:
    engine = BuySignalRuleEngine()
    config = build_engine_config(config_dir)
    universe = load_universe(config_dir)
    days = list_trading_days(start, end, db_path)
    cov = coverage(db_path)

    records: list[dict] = []
    skipped: dict[str, int] = {}
    for day in days:
        quotes, kline_map = [], {}
        for stock in universe:
            bare = stock["code"].split(".")[0]
            lo, hi = cov.get(bare, (None, None))
            if lo is None or not (lo <= day <= hi):
                skipped[bare] = skipped.get(bare, 0) + 1
                continue
            hist = get_klines_range(bare, lo, day, db_path)[-_LOOKBACK_DAYS:]
            if not hist or hist[-1]["date"] != day:
                skipped[bare] = skipped.get(bare, 0) + 1
                continue
            quotes.append(quote_from_kline(stock["code"], stock["name"], hist[-1]))
            kline_map[bare] = hist
        if not quotes:
            continue
        alerts = engine.evaluate(config, build_quote_snapshot(quotes))
        for alert in alerts:
            bare = alert.stock_code.split(".")[-1]
            klines = kline_map.get(bare)
            if not klines:
                # 信号票的前向收益需要完整区间，单独取
                full = get_klines_range(bare, day, end, db_path)
                klines = (kline_map.get(bare) or []) + full
            records.append({
                "code": alert.stock_code,
                "name": alert.stock_name,
                "date": day,
                "price": alert.price,
                "trigger": alert.trigger,
                "returns": {h: forward_return(klines, day, h) for h in horizons},
            })

    stats = summarize(records, horizons)
    return {
        "params": {"start": start, "end": end, "horizons": horizons,
                   "universe_size": len(universe), "trading_days": len(days)},
        "signals": records,
        "stats": {str(h): s for h, s in stats.items()},
        "skipped_no_data": skipped,
    }


def render_report(result: dict) -> str:
    p = result["params"]
    lines = [
        f"# 买入信号回测报告（{p['start']} ~ {p['end']}）",
        "",
        f"- 标的池: {p['universe_size']} 只（stock_pool.yaml）",
        f"- 回测交易日: {p['trading_days']} 天（以缓存实际数据为准）",
        f"- 信号总数: {len(result['signals'])}",
        "",
        "| horizon | 样本数 | 命中(收益>0) | 命中率 | 平均收益 |",
        "|---|---|---|---|---|",
    ]
    for h, s in result["stats"].items():
        rate = f"{s['hit_rate']:.1%}" if s["hit_rate"] is not None else "N/A"
        avg = f"{s['avg_return']:.2%}" if s["avg_return"] is not None else "N/A"
        lines.append(f"| {h}日 | {s['samples']} | {s['hits']} | {rate} | {avg} |")
    if result["skipped_no_data"]:
        lines += ["", "## 数据缺口（如实标注）", ""]
        for code, n in sorted(result["skipped_no_data"].items()):
            lines.append(f"- {code}: {n} 个交易日无缓存数据")
    lines += ["", "> 数据时间戳: K线缓存 infra/data/kline_cache.db；本报告不构成投资建议。"]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="买入信号历史回测")
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--horizons", default="5,10,20")
    parser.add_argument("--config-dir", default="config/stock_monitor")
    parser.add_argument("--db", default="infra/data/kline_cache.db")
    parser.add_argument("--output", default=None)
    args = parser.parse_args(argv)

    horizons = tuple(int(x) for x in args.horizons.split(","))
    result = run_backtest(
        Path(args.config_dir), Path(args.db), args.start, args.end, horizons
    )
    report = render_report(result)
    out = Path(args.output) if args.output else Path(
        f"logs/backtest_buy_signals_{date.today():%Y%m%d}.md"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    print(f"信号数: {len(result['signals'])}; 报告: {out}")
    print(json.dumps(result["stats"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: 合成数据端到端验证**

```bash
.venv/bin/python -c "
import sys, tempfile; sys.path.insert(0, 'src')
from pathlib import Path
from qing_investment.kline_cache import init_db, save_klines
db = Path(tempfile.gettempdir()) / 'bt_smoke.db'
init_db(db_path=db)
kl = [{'code': '000636', 'date': f'2026-07-{d:02d}', 'open': 10, 'high': 10.5,
       'low': 9.5, 'close': 10 + i * 0.1, 'volume': 1000, 'turnover': 1.0,
       'amplitude': 5.0, 'pct_change': 1.0} for i, d in enumerate(range(1, 20))]
save_klines('000636', kl, db_path=db)
from scripts.backtest_buy_signals import run_backtest  # 若 import 失败则用 runpy 跑 CLI
r = run_backtest(Path('config/stock_monitor'), db, '2026-07-01', '2026-07-19')
print('signals:', len(r['signals']), 'stats:', r['stats'])
"
```
Expected: 正常运行不报错；signals 数 ≥ 0（合成数据大概率不出候选信号，**为 0 也是合法结果**，本步验证的是管线跑通）；stats 含 5/10/20 三个键。若 `from scripts...import` 失败（scripts 非包），改用 `runpy.run_path` 或直接在 CLI 层验证：
`PYTHONPATH=src .venv/bin/python scripts/backtest_buy_signals.py --start 2026-07-01 --end 2026-07-19 --db /tmp/bt_smoke.db`

- [ ] **Step 3: Commit（经用户确认）**

```bash
git add scripts/backtest_buy_signals.py
git commit -m "feat(backtest): 买入信号离线回测 CLI（补上被引用但不存在的脚本）"
```

---

## Task 15: 真实数据回测 + validation 回填 + M0 验收

**Files:**
- Create: `logs/backtest_buy_signals_<date>.md`（回测报告）
- Modify: `framework/reasoning-patterns.yaml`（technical_timing / operation_strategy 的 validation 回填）
- Create: `logs/m0-acceptance.md`

- [ ] **Step 1: 查缓存覆盖，定回测窗口**

```bash
.venv/bin/python -c "
import sys; sys.path.insert(0, 'src')
from investment_engine.backtest.history import coverage
cov = coverage()
print('标的数:', len(cov))
import collections
ranges = collections.Counter(cov.values())
for r, n in ranges.most_common(10):
    print(r, n)
"
```
Expected: 输出各标的缓存日期范围。取多数标的共同覆盖的区间作回测窗口；若共同区间太短（< 40 个交易日），如实记录"缓存覆盖不足，回测窗口受限"，不得用网络补数据（本任务离线）。

- [ ] **Step 2: 跑真实回测**

Run: `.venv/bin/python scripts/backtest_buy_signals.py --start <窗口起点> --end <窗口终点>`
Expected: 生成 `logs/backtest_buy_signals_<date>.md`；报告含三个 horizon 的命中率与数据缺口标注。

- [ ] **Step 3: validation 区块回填**

对 `framework/reasoning-patterns.yaml`：
- `technical_timing` 与 `operation_strategy` 中与买入信号机械可验的部分，`validation.historical_hit_rate` 回填实测值（注明样本数与窗口，如 `"0.55 (n=20, 2026-03~07, 5日前向)"`）；
- 其余 LLM 推理类模式保持 `"pending-m1"`；
- 回填后重跑全量校验（Task 10 Step 2 命令）确认仍通过。

- [ ] **Step 4: 写 M0 验收报告**

`logs/m0-acceptance.md`，内容逐项对照 v2.1 验收标准：

```markdown
# M0 验收报告（<日期>）

## 验收标准对照（v2.1 第十四节）
| 标准 | 结果 | 证据 |
|---|---|---|
| 10 个框架全部带 validation 区块 | ✅/❌ | 全量校验输出 |
| 回放能跑出命中率 | ✅/❌ | logs/backtest_buy_signals_<date>.md |
| 产业链知识库 schema 落地并迁移 3 篇 | ✅/❌ | knowledge/industry-chains/ + 校验通过 |
| 术语词典 | ✅/❌ | framework/up-glossary.md |

## 如实记录的缺口
- LLM 推理类模式的 historical_hit_rate 为 pending-m1（待盲测 eval）；
- knowledge/cases/ 案例库实际仅 2 篇，基准率检索样本不足（影响 M3 假设置信度）；
- 缓存覆盖范围：<实际>，回测窗口受限程度：<实际>；
- 回测信号样本数 n=<实际>，n 过小则命中率仅作参考不作结论。
```

- [ ] **Step 5: 全量回归**

Run: `.venv/bin/pytest tests/investment_engine -v` + `.venv/bin/pytest tests/ -x -q`（确认未碰坏任何现有测试）
Expected: 全部通过

- [ ] **Step 6: Commit（经用户确认）**

```bash
git add framework/reasoning-patterns.yaml logs/backtest_buy_signals_*.md logs/m0-acceptance.md
git commit -m "test(m0): 真实数据回测与 M0 验收报告"
```

---

## 自查记录（写计划后已执行）

**Spec 覆盖（v2.1 M0 四项内容）：** 推理模式来源中立改写 → Task 6-10；术语词典 → Task 11；回测脚本新建 → Task 12-14（15 真实跑）；产业链 schema 落地+迁移 3 篇 → Task 2-5。无遗漏。

**Placeholder 扫描：** 所有代码任务含完整实现与完整测试；内容改写任务（7-10）含映射规则表+结构骨架+逐框架要点+机械校验兜底；Task 11 含词典全文。无 TBD/TODO。

**类型一致性：** `quote` 字段（code=secid/latest/turnover_rate）对齐 `test_e2e.py:38` mock；`load_monitor_config` 属性名（watchlist/stock_pool/positions/strategy_pack）对齐 `context/__init__.py:1118`；`validate_chain/save_chain/parse_research_md/validate_pattern/get_klines_range/forward_return/summarize` 签名在定义任务与使用任务间一致。已知薄弱点（执行时以行为测试驱动修正）：BuySignalRuleEngine 内部对 config/quote 的更多字段读取——Task 12 Step 4 已给出处置规则（补字段到 quote_from_kline，不改 qing_investment）。

**已知风险（如实声明）：**
1. K 线缓存的历史覆盖范围未跑过 Step 1 前不确定，回测窗口可能受限 → Task 15 Step 1 先查覆盖再定窗口；
2. `stock_pool.yaml` 标的数少（新结构），信号样本可能很少 → 验收报告如实标 n；
3. examples 内嵌 UP_logic 保留属有意为之（历史档案），校验器只约束顶层决策字段——若 M1 盲测发现 LLM 会读 examples 被带偏，届时再决定是否剥离。
