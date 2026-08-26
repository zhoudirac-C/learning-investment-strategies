# chanlun-quant M5 适配器补偿实施计划（BSP-004 多类型买卖点 + ZS-003 跨 seg 九段升级）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 落地 M4 评估（`docs/design/chanlun-m4-patch-assessment.md` §2/§3）经 UP 2026-08-02 拍板批准的两项 B 类（适配器层）补偿：

1. **BSP-004 × chanpy**：bsp 提取循环由「只取 `bsp.type[0]`」改为「按 distinct `main_type()` 逐条出记录」，补上三买「二三类重合」（课21，`claim-20070109-001-b`）。chanpy 内部已算出 `types=[T2, T3B]` 合并于同一 `CBS_Point`，丢失点在适配器提取层（`adapter_chanpy.py:272`）。
2. **ZS-003 × chanpy**：复合 B 补偿——「跨 seg 延伸试探 + 九段升级」单函数后处理；延伸只作升级判定的内部试探，**唯一落改门控 = 延伸后范围内笔数 ≥9 且 3 子中枢重合区间成立**，落改 `zd/zg/end_idx/level=2`（课33，`claim-20070302-001-b`）。

**验收门**（M4 报告 §2/§3 原文给定，硬约束）：

- M5-1：测试全绿 + BSP-004 chanpy 列 FAIL→PASS + 其余 23 个 chanpy PASS 用例输出逐字节不变（半径实证=0，全语料多类型 bsp 仅 BSP-004 一例）。
- M5-2：测试全绿 + ZS-003 chanpy 列 FAIL→PASS + **bsp-002/bsp-004/seg-005 三用例输出逐字节不变**（延伸试探触发集合中门控不通过的 3 个）。
- 收官矩阵：`chanpy 25 PASS / FAIL 6`（23+2；剩余 6 项 FAIL = BC-002/BSP-003 recursion 覆盖、SEG-004/005 永久降级、GOLD-001/002 recursion 箱体代理覆盖，全部有归属）、`czsc 25`、`recursion 18` 两列不动。

**Architecture:** 两项均为 B 类补偿：全部代码改动落在 `src/chan_engine/harness/adapter_chanpy.py`（+ 对应测试文件）。`third_party/chanpy/` vendor 源码、`adapter_czsc.py`、`src/chan_engine/core/`（recursion 层）、`spec/` 用例与 expect **零改动**。TDD（Red→Green）；校准门（31 用例 × 3 实现矩阵）为硬约束。

**Tech Stack:** Python 3.11（`.venv/bin/python`）、`PYTHONPATH=src:third_party/chanpy`、pytest、`chan_engine.harness.report`。

**权威输入（实施前必读）：**

- `docs/design/chanlun-m4-patch-assessment.md` §2（BSP-004）、§3（ZS-003）——根因/探针实证/半径/验收门原文
- `docs/design/chanlun-quant-engine.md` 附录 C.2（level 归一约定）/C.4（zs 表构造口径）/C.5（已知偏差清单两 🔧 行）
- 参照实现：`src/chan_engine/harness/adapter_czsc.py:201-247`（`_apply_nine_bi_upgrade`，M2-3 先例）、`:108-125`（`_bi_low_high`/`_has_overlap_strict`）
- 补偿先例：`adapter_chanpy.py:261-268`（M2-3 末位笔 bsp 过滤，同为 B 类）

## Global Constraints

- **vendor 只读**：不改 `third_party/chanpy/` 与 czsc（pip 0.10.12）任何源码；补偿全部在适配器层（B 类定义）。
- 最小 diff：不动与本任务无关的代码；不改 `adapter_czsc.py`、`core/`、`spec/` 下任何文件。
- TDD：先写失败测试（Red）再实现（Green）；禁止先实现后补测。
- 测量性校准矩阵一律 `--out /tmp/m5-*.md`；**不重生成** `docs/design/chanlun-calibration-report.md`（`report.py --version` 仅支持 M1/M2/M3，新增 M5 版本段需扩展 report.py，属另一立项，留 UP 拍板）。
- 运行前缀统一：`PYTHONPATH=src:third_party/chanpy .venv/bin/python`（py3.11）。
- 禁止 git 提交类操作（只读 git 可用），除非用户显式授权。
- 开工基线（2026-08-26 实测）：`198 passed`；矩阵 `chanpy 23 PASS / FAIL 8`、`czsc 25 / 6`、`recursion 18 / 13`。
- 探针/快照脚本只放 `/tmp/m5_*`，不进 git、不进 tests/。
- pytest 退出码判断不要接管道后 `&&`（`| tail` 会吃掉退出码），单独跑或用 `${PIPESTATUS[0]}`（仓规）。

---

### Task M5-0: 基线确认 + 全量快照（逐字节比对基准）

**Files:**
- Create: `/tmp/m5_snapshot.py`（快照脚本，不进 git）
- Create: `/tmp/m5-baseline-charts.json`（基线快照）

**Interfaces:**
- Consumes: `chan_engine.spec.case_io.load_case(path) -> Case`（`Case.bars: list[Bar]`、`Case.case_id`）；`ChanPyAdapter().run(bars) -> NormalizedChart`；`NormalizedChart{fx, bi, seg, zs, bsp}` 元素均为 dataclass（`spec/model.py:45-108`，`dataclasses.asdict` 可用；`Direction` 为 Enum，json 序列化需 `default=str`）。
- Produces: 全量 31 用例（26 case + 5 golden）chanpy 归一五表 JSON 快照，供 M5-1/M5-2 后 diff。

- [ ] **Step 1: 写快照脚本**

写 `/tmp/m5_snapshot.py`：

```python
"""M5 快照：dump 全量用例的 chanpy 归一五表为 JSON（基线/回归逐字节比对用）。

用法: PYTHONPATH=src:third_party/chanpy .venv/bin/python /tmp/m5_snapshot.py <out.json>
"""
import dataclasses
import glob
import json
import sys

from chan_engine.harness.adapter_chanpy import ChanPyAdapter
from chan_engine.spec.case_io import load_case

out_path = sys.argv[1]
data = {}
paths = sorted(glob.glob("src/chan_engine/spec/cases/*.yaml")) + sorted(
    glob.glob("src/chan_engine/spec/golden/*.yaml")
)
for path in paths:
    case = load_case(path)
    chart = ChanPyAdapter().run(case.bars)
    data[case.case_id] = {
        table: [dataclasses.asdict(x) for x in getattr(chart, table)]
        for table in ("fx", "bi", "seg", "zs", "bsp")
    }
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=1, default=str)
print(f"snapshot -> {out_path} ({len(data)} cases)")
```

- [ ] **Step 2: 生成基线快照 + 复核基线**

```bash
PYTHONPATH=src:third_party/chanpy .venv/bin/python /tmp/m5_snapshot.py /tmp/m5-baseline-charts.json
PYTHONPATH=src:third_party/chanpy .venv/bin/python -m pytest tests/chan_engine/ -q
PYTHONPATH=src:third_party/chanpy .venv/bin/python -m chan_engine.harness.report --cases src/chan_engine/spec/cases --golden src/chan_engine/spec/golden --out /tmp/m5-baseline-report.md
```

Expected: 快照 31 cases；`198 passed`；矩阵 `chanpy: PASS 23 / FAIL 8 / ERROR 0`、`czsc: PASS 25 / FAIL 6`、`recursion: PASS 18 / FAIL 13`。任一不符 → 停止，先查环境漂移再动工。

---

### Task M5-1: BSP-004 三买「二三类重合」——多 main_type 提取（TDD）

**Files:**
- Modify: `tests/chan_engine/test_adapter_chanpy.py`（新增 2 个测试）
- Modify: `src/chan_engine/harness/adapter_chanpy.py`（新增 `_distinct_main_types` 辅助 + BSP 提取循环 :264-278 改造 + 模块 docstring BSP 行 :25-26 更新）

**Interfaces:**
- Consumes: chanpy `CBS_Point.type: list[BSP_TYPE]`（`BuySellPoint/BS_Point.py:11`）；`BSP_TYPE.main_type()` 返回 `self.value[0]` 即 `'1'/'2'/'3'` 字符（`Common/CEnum.py:66-76`），外层 `int()` 转换与现状一致；`BSP_TYPE` 含 `T1/T1P/T2/T2S/T3A/T3B` 六成员。
- Produces: BSP-004 chanpy bsp 表 = `[一买@26, 二买@36, 三买@36]`（同 idx 两条记录表达二三类重合，与 expect 一致）。

- [ ] **Step 1（Red）: 写失败测试**

在 `tests/chan_engine/test_adapter_chanpy.py` 末尾新增（文件头 import 区追加 `from pathlib import Path`、`from chan_engine.spec.case_io import load_case`、`from chan_engine.harness.adapter_chanpy import _distinct_main_types`，以及 `from Common.CEnum import BSP_TYPE`）：

```python
_CASES_DIR = Path(__file__).resolve().parents[2] / "src" / "chan_engine" / "spec" / "cases"


class TestMultiMainTypeBsp:
    """M5-1：同笔多类型买卖点按 distinct main_type 逐条出记录（课21 二三类重合）。

    依据：M4 评估 §2——chanpy 内部已算出 bsp@klu36 types=[T2, T3B]，
    旧提取口径 bsp.type[0] 丢弃 T3B。
    """

    def test_bsp004_second_and_third_buy_coincide(self):
        case = load_case(_CASES_DIR / "bsp-004.yaml")
        chart = make_adapter().run(case.bars)
        assert [(b.idx, b.bstype, b.dir, b.level, b.sure) for b in chart.bsp] == [
            (26, 1, Direction.UP, 1, True),
            (36, 2, Direction.UP, 1, True),
            (36, 3, Direction.UP, 1, True),
        ]

    def test_distinct_main_types_dedup(self):
        """同 main_type 去重（T1/T1P 理论可同挂一笔，M4-2 评审提示）；保持原顺序。"""
        assert _distinct_main_types([BSP_TYPE.T2, BSP_TYPE.T3B]) == [2, 3]
        assert _distinct_main_types([BSP_TYPE.T1, BSP_TYPE.T1P]) == [1]
        assert _distinct_main_types([BSP_TYPE.T3A]) == [3]
```

Run: `PYTHONPATH=src:third_party/chanpy .venv/bin/python -m pytest tests/chan_engine/test_adapter_chanpy.py -q`
Expected: 新测试 FAIL（`_distinct_main_types` ImportError / BSP-004 断言缺三买@36），既有 198 不受影响（`test_bsp_dir_is_operation_direction` 等单类型断言即防重复发射的回归哨兵）。

- [ ] **Step 2（Green）: 改 adapter_chanpy.py**

(a) 模块 docstring :25-26 的 BSP 行改为：

```
- BSP：bstype 按 ``bsp.type`` 逐 distinct ``main_type()`` 出一条（M5-1：同笔
  多类型合并场景如二买+三买 T2+T3B 各出一条，课21 二三类重合；同 main_type
  去重）；dir = 操作方向（ADR-006）；level 恒 1（单级别输入）。
```

(b) 在 `_apply_positional_sure` 之后新增辅助函数：

```python
def _distinct_main_types(bsp_type_list) -> list[int]:
    """``bsp.type``（BSP_TYPE 列表）→ distinct main_type int 列表，保持原顺序。

    chanpy 把同笔多个买卖点合并进同一 CBS_Point（如二买+三买重合 T2+T3B，
    课21 / claim-20070109-001-b），多类型信息保留在 type 列表中；归一表按
    每个 distinct main_type 出一条 BSPoint（M5-1，M4 评估 §2 UP 批准的
    B 类补偿）。同 main_type 去重（T1/T1P 理论可同挂一笔，M4-2 评审提示）。
    """
    seen: list[int] = []
    for t in bsp_type_list:
        mt = int(t.main_type())
        if mt not in seen:
            seen.append(mt)
    return seen
```

(c) BSP 提取循环（:264-278）改造——`chart.bsp.append(...)` 单条改为按 distinct main_type 逐条：

```python
        for bsp in kl.bs_point_lst.getSortedBspList():
            bi_idx = bsp.bi.idx
            # 跳过基于未确认笔（末位笔）的 bsp：chart.bi[bi_idx].sure=False
            if bi_idx < len(chart.bi) and not chart.bi[bi_idx].sure:
                continue
            for bstype in _distinct_main_types(bsp.type):
                chart.bsp.append(
                    BSPoint(
                        idx=bsp.klu.idx,
                        bstype=bstype,
                        dir=Direction.UP if bsp.is_buy else Direction.DOWN,  # 操作方向（ADR-006）
                        level=1,
                        sure=True,  # 买卖点形成即确认
                        source=SOURCE,
                    )
                )
```

- [ ] **Step 3: 测试转绿 + 全量单测回归**

Run: `PYTHONPATH=src:third_party/chanpy .venv/bin/python -m pytest tests/chan_engine/ -q`
Expected: `200 passed`（198+2）。

- [ ] **Step 4: 矩阵 + 快照比对（验收门逐项核）**

```bash
PYTHONPATH=src:third_party/chanpy .venv/bin/python -m chan_engine.harness.report --cases src/chan_engine/spec/cases --golden src/chan_engine/spec/golden --out /tmp/m5-after-m51.md
PYTHONPATH=src:third_party/chanpy .venv/bin/python /tmp/m5_snapshot.py /tmp/m5-current-charts.json
diff /tmp/m5-baseline-charts.json /tmp/m5-current-charts.json
```

Expected: 矩阵 `chanpy 24 PASS / FAIL 7`（BSP-004 翻 PASS），czsc 25 / recursion 18 不变；快照 diff **唯一差异 = BSP-004 的 bsp 表多一条三买@36**，其余 30 用例逐字节一致。任何额外差异 → 回退本 Task 改动，查明再继续。

- [ ] **Step 5: 提交**（需用户当场授权 git）

```bash
git add src/chan_engine/harness/adapter_chanpy.py tests/chan_engine/test_adapter_chanpy.py
git commit -m "feat(chan-engine): M5-1 适配器补偿——同笔多类型 bsp 按 distinct main_type 逐条出记录（BSP-004 二三类重合）"
```

---

### Task M5-2: ZS-003 跨 seg 延伸试探 + 九段升级（TDD）

**Files:**
- Modify: `tests/chan_engine/test_adapter_chanpy.py`（新增 1 个测试类 2 个测试）
- Modify: `src/chan_engine/harness/adapter_chanpy.py`（`_extract` 签名加 `bars` 参数 + `ChanPySession` 记录 bars + 新增 `_bi_low_high`/`_has_overlap_strict`/`_apply_nine_bi_upgrade_with_extension` + zs 提取循环后调用 + 相关注释/docstring 更新）

**Interfaces:**
- Consumes: czsc 参照实现 `adapter_czsc.py:201-247`（九段升级分组/重合演算）与 `:108-125`（笔极值/严格重叠辅助，口径对齐源）；M4 报告 §3 探针演算（ZS-003：延伸试探 end 17→41、范围内笔数 3→9（bi1..bi9）、3 子中枢 [16.0,17.0]/[16.5,18.0]/[16.2,17.8]、重合 [16.5,17.0] 与 expect 逐字段一致）。
- Produces: ZS-003 chanpy zs 表 = `[{zd:16.5, zg:17.0, start_idx:5, end_idx:41, level:2, sure:True}]`；bsp-002/bsp-004/seg-005 三用例（延伸试探触发但门控不通过）输出逐字节不变。
- 已知约束：`_extract(self, chan)` 当前拿不到 `bars`（九段升级需笔极值，即 bars 的 h/l）；`ChanPySession.push` 逐 bar 投喂时顺手记录即可，`_extract` 仅有两个调用点（`ChanPySession.chart` :154、`run` 经 session.chart :181），签名变更封闭在本文件内（grep 已确认 tests/ 与其他模块无 `_extract` 引用）。

- [ ] **Step 1（Red）: 写失败测试**

在 `tests/chan_engine/test_adapter_chanpy.py` 追加：

```python
class TestNineBiUpgradeCrossSeg:
    """M5-2：跨 seg 延伸试探 + 九段升级（课33，claim-20070302-001-b）。

    依据：M4 评估 §3——chanpy zs 受 seg 切分限制（ZS-003 止步 end=17、
    仅 3 笔），纯移植 czsc _apply_nine_bi_upgrade 零触发；补偿为复合形态，
    唯一落改门控=延伸后范围内笔数≥9 且 3 子中枢重合区间成立。
    """

    def test_zs003_upgrades_to_level2(self):
        case = load_case(_CASES_DIR / "zs-003.yaml")
        chart = make_adapter().run(case.bars)
        assert [(z.zd, z.zg, z.start_idx, z.end_idx, z.level, z.sure) for z in chart.zs] == [
            (16.5, 17.0, 5, 41, 2, True),
        ]

    def test_extension_probe_gate_keeps_other_cases_unchanged(self):
        """延伸试探触发集内门控不通过的用例：zs 表逐字段不变（bsp-002/bsp-004
        的 expect zs 即基线值，M4 §2 实证 bsp-004 zs 表一致）。"""
        for cid in ("bsp-002", "bsp-004"):
            case = load_case(_CASES_DIR / f"{cid}.yaml")
            chart = make_adapter().run(case.bars)
            assert [(z.zd, z.zg, z.start_idx, z.end_idx, z.level, z.sure) for z in chart.zs] == [
                (18.3, 20.2, 6, 21, 1, True),
            ], f"{cid} zs 表被门控外落改"
```

（seg-005 无 zs expect，其逐字节不变由 Step 4 快照 diff 兜底，不进单测断言。）

Run: `PYTHONPATH=src:third_party/chanpy .venv/bin/python -m pytest tests/chan_engine/test_adapter_chanpy.py -q`
Expected: `test_zs003_upgrades_to_level2` FAIL（当前 zs={16.0, 17.0, 5, 17, 1}）；门控守护测试 PASS（未实现时无改动）。

- [ ] **Step 2（Green）: 改 adapter_chanpy.py**

(a) `ChanPySession` 记录投喂 bars（:143-150）——`__init__` 加 `self._bars: list[Bar] = []`，`push` 末尾加 `self._bars.append(bar)`；`chart()` 改为 `return adapter._extract(self._chan, self._bars)`；类 docstring 补一句「同时记录投喂 bars 供九段升级后处理取笔极值（M5-2）」。

(b) `_extract` 签名改为 `_extract(self, chan: CChan, bars: list[Bar])`（唯一外部调用点是 `ChanPySession.chart`，已随 (a) 改）。

(c) zs 提取循环中 `level=1` 行注释（:255）改为 `level=1,  # 单级别恒 1；九段升级后处理（下方）可升 2`。

(d) zs 提取循环（:248-259）之后、BSP 提取之前插入调用与实现：

```python
        _apply_nine_bi_upgrade_with_extension(chart.zs, chart.bi, bars)
```

```python
def _bi_low_high(bi: Bi, bars: list[Bar]) -> tuple[float, float]:
    """笔的极值（与 czsc 适配器 _bi_low_high 同口径；两适配器刻意各自持有
    小辅助函数保持独立，先例：_apply_positional_sure 双份持有）。

    上升笔：low=起点 K 线 low，high=终点 K 线 high；下降笔反之。
    """
    if bi.dir is Direction.UP:
        return float(bars[bi.start_idx].l), float(bars[bi.end_idx].h)
    return float(bars[bi.end_idx].l), float(bars[bi.start_idx].h)


def _has_overlap_strict(low1: float, high1: float, low2: float, high2: float) -> bool:
    """严格重叠（不含边界），对齐 chanpy has_overlap(equal=False)。"""
    return high2 > low1 and high1 > low2


def _apply_nine_bi_upgrade_with_extension(
    zs_list: list[ZhongShu], bi_table: list[Bi], bars: list[Bar]
) -> None:
    """跨 seg 延伸试探 + 九段升级（课33，claim-20070302-001-b；M5-2，
    M4 评估 §3 UP 批准的复合 B 补偿）。

    chanpy 中枢受 seg 切分限制不跨 seg 延伸（ZS.combine :118），九段升级
    在单 seg 内永不触发（全语料实测 zs 内笔数最多 3）。补偿口径（与 M4-3
    探针演算一致）：

    1. **延伸试探**：自 zs.end_idx 起按 bi_table 顺序逐笔与 [zd,zg] 判严格
       重叠，重叠则试探性延展 end；遇未确认笔（sure=False，位置约定下即
       末位笔）或首笔不重叠即停（对齐 M2-3 czsc 延伸口径）。
    2. **门控（唯一落改条件）**：试探后范围内笔数 ≥9，且前 9 笔分 3 组
       （每组 3 笔）子中枢各自成立（sub_zg > sub_zd），且 3 子中枢重合区间
       成立（max(sub_zd) < min(sub_zg)）。
    3. **落改**：zd/zg = 重合区间，end_idx = 试探终点，level = 2；门控不
       通过则 zs 逐字段不变——延伸只是升级判定的内部试探，不单独落改
       （bsp-002/bsp-004/seg-005 触发试探但门控不通过，输出逐字节不变，
       M4 §3 半径实证）。
    """
    for zs in zs_list:
        if zs.level != 1:
            continue
        # 1. 延伸试探（不落改）
        probe_end = zs.end_idx
        for bi in bi_table:
            if bi.end_idx <= zs.end_idx:
                continue  # 已在范围内的笔跳过（归一笔表首尾相接）
            if not bi.sure:
                break  # 末位未确认笔不延伸（对齐 M2-3 czsc 口径）
            low, high = _bi_low_high(bi, bars)
            if not _has_overlap_strict(zs.zd, zs.zg, low, high):
                break  # 首笔不重叠即停（延伸连续语义）
            probe_end = bi.end_idx
        # 2. 门控：范围内笔数 ≥9 且 3 子中枢重合
        in_range = [
            bi
            for bi in bi_table
            if bi.start_idx >= zs.start_idx and bi.end_idx <= probe_end
        ]
        if len(in_range) < 9:
            continue
        nine_bis = in_range[:9]
        sub_ranges: list[tuple[float, float]] = []
        for i in range(0, 9, 3):
            lows, highs = [], []
            for bi in nine_bis[i : i + 3]:
                low, high = _bi_low_high(bi, bars)
                lows.append(low)
                highs.append(high)
            sub_zd, sub_zg = max(lows), min(highs)
            if sub_zg <= sub_zd:
                break  # 子中枢不成立
            sub_ranges.append((sub_zd, sub_zg))
        if len(sub_ranges) != 3:
            continue
        level2_zd = max(r[0] for r in sub_ranges)
        level2_zg = min(r[1] for r in sub_ranges)
        if level2_zg <= level2_zd:
            continue
        # 3. 落改
        zs.zd = level2_zd
        zs.zg = level2_zg
        zs.end_idx = probe_end
        zs.level = 2
```

(e) 模块 docstring 补 zs 口径行（在 BSP 行附近）：`- ZS：chanpy normal 模式直取（seg 内构造）；M5-2 起叠加「跨 seg 延伸试探+九段升级」后处理（门控=延伸后范围内笔数≥9 且 3 子中枢重合，课33）。`

- [ ] **Step 3: 测试转绿 + 全量单测回归**

Run: `PYTHONPATH=src:third_party/chanpy .venv/bin/python -m pytest tests/chan_engine/ -q`
Expected: `202 passed`（200+2）。

- [ ] **Step 4: 矩阵 + 快照比对（验收门逐项核）**

```bash
PYTHONPATH=src:third_party/chanpy .venv/bin/python -m chan_engine.harness.report --cases src/chan_engine/spec/cases --golden src/chan_engine/spec/golden --out /tmp/m5-after-m52.md
PYTHONPATH=src:third_party/chanpy .venv/bin/python /tmp/m5_snapshot.py /tmp/m5-current-charts.json
diff /tmp/m5-baseline-charts.json /tmp/m5-current-charts.json
```

Expected: 矩阵 `chanpy 25 PASS / FAIL 6`（BSP-004 + ZS-003 翻 PASS），czsc 25 / recursion 18 不变；快照 diff 仅两处预期差异（BSP-004 bsp +1 条；ZS-003 zs 改 level=2），**bsp-002/bsp-004/seg-005 逐字节不变**（M4 §3 验收门原文）。任何额外差异 → 回退本 Task，查明再继续。

- [ ] **Step 5: 提交**（需用户当场授权 git）

```bash
git add src/chan_engine/harness/adapter_chanpy.py tests/chan_engine/test_adapter_chanpy.py
git commit -m "feat(chan-engine): M5-2 适配器补偿——跨 seg 延伸试探+九段升级（ZS-003 level=2）"
```

---

### Task M5-3: 收官——文档同步 + progress 落账

**Files:**
- Modify: `docs/design/chanlun-quant-engine.md`（附录 C.4 chanpy zs 行 + C.5 表两 🔧 行 + C.5 后"M4 评估登记"段）
- Modify: `docs/design/chanlun-m4-patch-assessment.md`（§2/§3 UP 决策行各追加一句）
- Modify: `.superpowers/sdd/progress.md`（追加 M5 状态行）

**Interfaces:**
- Consumes: M5-1/M5-2 完成态（矩阵 25/25/18、202 测试全绿、快照 diff 仅两处预期）。
- Produces: 文档与代码现状一致；progress.md 有 M5 收官行。

- [ ] **Step 1: 设计文档附录同步**

`docs/design/chanlun-quant-engine.md`：

(a) 附录 C.4 的 chanpy 行（"**chanpy**：`zs_algo=normal` 模式，在 seg 内部对反向笔构造……seg 切分限制延伸范围。"）末尾追加：`M5-2 起叠加「跨 seg 延伸试探 + 九段升级」后处理（adapter_chanpy.py，门控=延伸后范围内笔数≥9 且 3 子中枢重合，门控不过则逐字段不变）。`

(b) 附录 C.5 表两行状态更新：
- `| ZS-003 | 两实现 | 无九段升级 | chanpy seg 限制 / czsc 未实现 | 🔧 B 采纳（M4：chanpy 适配器补偿另立 M5；czsc 已修；recursion 未做） |` → 状态列改 `✅ chanpy M5-2 已补偿（2026-08-26）；czsc 已修；recursion 未做（ADR-010）`
- `| BSP-004 | chanpy | 三买缺（二三类重合） | 适配器只取 bsp.type[0]，chanpy 内部已算出 T2+T3B | 🔧 B 采纳（M4，另立 M5 实施） |` → 状态列改 `✅ M5-1 已补偿（2026-08-26）`

(c) C.5 后"M4 评估登记"段中"另 2 项 BSP-004/ZS-003 × chanpy 建议 B 适配器补偿，UP 已批准实施，另立 M5 里程碑，不动本附录"改为"另 2 项 BSP-004/ZS-003 × chanpy 建议 B 适配器补偿，UP 已批准并于 M5 实施完毕（plan：docs/superpowers/plans/2026-08-26-chanlun-quant-m5-adapter-compensation.md），上表两行已翻 ✅"。

- [ ] **Step 2: M4 报告 UP 决策行落账**

`docs/design/chanlun-m4-patch-assessment.md` §2/§3 两处 `- **UP 决策**：B 采纳——批准实施（2026-08-02 UP 确认），另立 M5 实施里程碑` 各追加：`；M5 已实施完毕（plan：docs/superpowers/plans/2026-08-26-chanlun-quant-m5-adapter-compensation.md）`。

- [ ] **Step 3: progress.md 追加 M5 状态**

`.superpowers/sdd/progress.md` 末尾追加（日期填实际完成日）：

```markdown
M5 适配器补偿 (plan: docs/superpowers/plans/2026-08-26-chanlun-quant-m5-adapter-compensation.md): done YYYY-MM-DD
  - M5-1: BSP-004 同笔多类型 bsp 按 distinct main_type 逐条出记录 → chanpy 列 FAIL→PASS（三买@36 二三类重合，课21）
  - M5-2: ZS-003 跨 seg 延伸试探+九段升级（门控=延伸后≥9笔且3子中枢重合）→ chanpy 列 FAIL→PASS（level=2 [16.5,17.0]）
  - 收官矩阵: chanpy 25 / czsc 25 / recursion 18（chanpy 剩余 6 FAIL 全部有归属：BC-002/BSP-003 recursion 覆盖、SEG-004/005 永久降级、GOLD-001/002 recursion 箱体代理）；单测 202 passed
  - 验收门: bsp-002/bsp-004/seg-005 及其余 chanpy PASS 用例快照逐字节不变（diff 仅 BSP-004/ZS-003 两处预期差异）
  - 正式校准报告未重生成（report.py --version 仅 M1/M2/M3，M5 版本段扩展另立项待 UP 拍板）
```

- [ ] **Step 4: 全量回归终验**

```bash
PYTHONPATH=src:third_party/chanpy .venv/bin/python -m pytest tests/chan_engine/ -q
PYTHONPATH=src:third_party/chanpy .venv/bin/python -m chan_engine.harness.report --cases src/chan_engine/spec/cases --golden src/chan_engine/spec/golden --out /tmp/m5-final.md
git status --short
```

Expected: `202 passed`；矩阵 25/25/18；`git status` 仅含本计划预期改动文件（adapter_chanpy.py、test_adapter_chanpy.py、两个设计文档、progress.md、本 plan），无 gitignored 文件、无 `third_party/chanpy/` 改动。

- [ ] **Step 5: 提交**（需用户当场授权 git）

```bash
git add docs/design/chanlun-quant-engine.md docs/design/chanlun-m4-patch-assessment.md .superpowers/sdd/progress.md docs/superpowers/plans/2026-08-26-chanlun-quant-m5-adapter-compensation.md
git commit -m "docs(chan-engine): M5 收官——附录 C.4/C.5 同步 + progress 落账"
```

---

## Self-Review 记录

- **Spec 覆盖**：M4 批准的两项 B ↔ M5-1（BSP-004）/M5-2（ZS-003）；验收门逐字继承 M4 报告 §2（198 全绿+BSP-004 翻转，注：基线 198 随本计划新增测试变为 200/202，PASS 用例不变性以快照 diff 核）与 §3（ZS-003 翻转 + bsp-002/bsp-004/seg-005 逐字节不变）。
- **占位符扫描**：无占位符；探针/快照/测试/实现均为完整可运行代码。
- **类型一致性**：`BSP_TYPE.main_type()` 返回 `self.value[0]`（`Common/CEnum.py:74-76`，str '1'/'2'/'3'），外层 `int()` 与现状 `adapter_chanpy.py:272` 一致；`_extract` 签名加 `bars` 的影响面已 grep 核实（仅 `ChanPySession.chart` 一处外部调用点）；`NormalizedChart` 五表元素均为 dataclass（`spec/model.py:45-108`），快照脚本 `dataclasses.asdict` 可用；`load_case` 接受路径对象（`case_io`）。
- **越界自查**：不改 vendor/czsc/core/spec；不重生成正式校准报告（report.py 无 M5 版本，留账 UP）；recursion 列 BSP-004/ZS-003 FAIL 属 ADR-010 哲学差异，czsc 列 BSP-004 FAIL 属 M4 永久降级，均不在本里程碑范围。
- **基线实证**：2026-08-26 开工前实测 `198 passed`、矩阵 23/25/18，BSP-004/ZS-003 的 chanpy 列当前 FAIL 已核（/tmp/m5-baseline-report.md）。
