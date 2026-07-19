# Task 6/7 评审修复复核（C-1 / I-1 / M-1 / M-2）

> 复核对象：`.superpowers/sdd/task-6-7-review-fix.md` 声明的全部修复。
> 方法：所有验证命令独立重跑、所有文件独立重读；机械校验与证伪脚本为复核人
> 自写（`/tmp/rereview_check.py`、`/tmp/rereview_fork.py`），未使用修复方 scratch。
> 复核时间 2026-07-19；无 git 写操作；third_party/chanpy 未触碰（mtime 复核）。

## 总结论：**Approved**

4 项缺陷全部修复且经独立验证；修复方两处"偏离评审建议"的决定经独立推演与
暴力枚举证实成立。遗留 2 处报告文档陈旧行（Minor，不阻塞，见末节）。

---

## 1. pytest 全绿 ✅

```
$ PYTHONPATH=src:third_party/chanpy .venv/bin/python -m pytest tests/chan_engine/ -q
146 passed in 1.35s
```

## 2. bi-002 / bi-003 bars 机械校验 ✅（复核人自写脚本全量核）

`/tmp/rereview_check.py` 输出（两条均全过）：

- **bars 合法性**：h≥max(o,c)、l≤min(o,c)，bi-002/003 全过；26 条全量复核亦无非法 bar。
- **无相邻包含**：标准包含合并（方向合并取极值）前后序列等长等值，两案均 OK。
- **分型恰好落在设计 idx**：bi-003 = `[(1,down),(5,up)]`；bi-002 = `[(1,up),(5,down)]`；
  全序列无多余分型（逐三 K 线扫描，顶=中间高最高且低最高 / 底=中间低最低且高最低）。
- **两分型不共用 K 线、中间有独立 K 线**：两案均为 span{0,1,2} 与 span{4,5,6}，
  共用集合为空，bar3 独立（新笔口径满足）。
- **头注数值与 bars 一致**：
  - bi-003：底@1 三根合并高 max(12.3,11.0,11.2)=**12.3**（口径 A，左肩 bar0 抬高），
    底中间高 **11.0**（口径 B），顶@5 合并高 **11.4** → A：11.4<12.3 不成笔 /
    B：11.4>11.0 成笔，与头注（bi-003.yaml:6-9）一致。
  - bi-002：顶@1 三根合并低 min(10.4,11.0,10.8)=**10.4**（口径 A，左肩 bar0 压低），
    顶中间低 **11.0**（口径 B），底@5 中间低 **10.5** → A：10.5>10.4 不成笔 /
    B：10.5<11.0 成笔，与头注（bi-002.yaml:5-9）一致。
- fx 位置 1/5、`bi: []` expect、claim_refs（claim-20070905-001-b）两案均未变；
  bi-002 的 fx type 镜像为 up/down 已在修复报告与头注中显式披露，属改造设计而非暗改。

## 3. 真实适配器复跑 ✅（关键验收项，复核人重跑）

```
bi-002 chanpy(strict) bi= [] fx= []
bi-002 czsc           bi= [(1,5,DOWN,False)] fx= [(5,DOWN,False)]
bi-002 chanpy-half    [(1, 5)]
bi-002 chanpy-loss    [(1, 5)]
bi-003 chanpy(strict) bi= [] fx= []
bi-003 czsc           bi= [(1,5,UP,False)]   fx= [(5,UP,False)]
bi-003 chanpy-half    [(1, 5)]
bi-003 chanpy-loss    [(1, 5)]
```

- chanpy strict（默认，`ChanConfig.py:26` bi_fx_check=strict）两案 bi=[] —— 与 expect 一致；
  同输入仅把 `bi_fx_check` 调宽为 half/loss 即画出 (1,5)，**证明 strict 拒绝唯一来自
  分型区间检查**，而非分型缺失/共用 K 线——A/B 判别场景真实走到。
- czsc 两案画出 (1,5) 方向正确（口径 B 行为），与 expect 的分歧成为校准矩阵真信号。
- czsc fx 仅 [(5,...)] 属适配器 docstring 已记录的已知归一差异（fx_list 不含首笔起始
  分型）；**修复前 czsc 产出的多余 `fx idx=2 up`（合并污染）已消失**。

## 4. 全量 CLI + 偏差明细抽查 ✅

```
$ PYTHONPATH=src:third_party/chanpy .venv/bin/python -m chan_engine.harness.report \
    --cases src/chan_engine/spec/cases --out /tmp/rereview.md
退出码 0；chanpy: PASS 0 / FAIL 26 / ERROR 0；czsc: PASS 5 / FAIL 21 / ERROR 0（与修复前统计口径一致）
```

- BI-002/003 × chanpy（/tmp/rereview.md:133-138,150-155）：仅剩"缺 fx"（无笔则无 fx 的
  已知归一方式），bi 表无偏差（[]=[]），无任何多余元素。
- BI-002/003 × czsc（:140-148,157-165）：缺首 fx（已知差异）+ 多 (1,5) 笔（口径 B 真信号），
  无 idx=2 合并污染。
- BSP-001 × czsc（:见报告 BSP-001 节）：修复前的 `fx idx=31 sure 期望 True 实际 False`、
  `bi (26,31) sure 期望 True 实际 False` 噪声**已消失**；残余差异为缺 fx idx=1（已知
  归一）与 zs 区间/起点分歧（18.3/20.2@6-21 vs 18.3/20.6@1-31，Task 9 校准素材），
  与 I-1 无关。

## 5. I-1：12 处 sure 翻转 + 标注 ✅

程序化 dump 6 文件 fx/bi 全表逐条核对：

- bsp-001/003（7 fx / 6 bi）、bsp-002/004（9 fx / 8 bi）、bc-001/002（11 fx / 10 bi）：
  **每条末位 fx 与末位 bi 均 `sure: false`（共 12 处）**；其余全部 `sure: true`，
  且与"已被后续反向笔确认"语义自洽（每个非末位分型/笔之后均存在反向笔），无误改。
- `.superpowers/sdd/task-7c-report.md:88-91` 歧义节#3 已加"【已按裁定统一，2026-07-19】"
  标注，引用 seg 族在先裁定（task-7-report 追加节）并声明原约定不再适用。
- 顶层键复核：6 文件均仅 case_id/claim_refs/bars/expect，bsp/zs 表完整未动。

## 6. M-2：description 键清零 ✅

`grep ^description: src/chan_engine/spec/cases/` → 零结果。采取"移除"方案符合评审
"移除或纳入文档"二选一建议；内容与头注重复，无信息损失。

## 7. 合规：改动范围 ✅

以评审时间（2026-07-19 09:54）为界 `find -newermt` 全仓扫描：

- 被触碰文件恰好为：bi-002/bi-003.yaml、bsp-001..004/bc-001..002.yaml（共 8 个用例）、
  `.superpowers/sdd/` 下 review/fix/7c-report 三个 md。
- harness/model/case_io/builders 全部 .py、mtime 均在评审之前，无改动；
  third_party/ 无任何新改动；未做任何 git 写操作。

## 8. 两项"偏离评审建议"决定的独立裁定

### 8a. bi-003 右肩→左肩：**修复方主张成立，偏离正当** ✅

评审原建议"保留右肩抬高合并高、消除吞并"。复核人独立推演（三分支穷举）：
在"右肩高 h2 > 反弹顶合并高"的设计约束下，考察 bar2 的后续 bar3：

1. **bar3 被 bar2 包含**（h3<h2 且 l3>l2）→ 混入未处理包含（原案即死于此）；
2. **bar3 包含 bar2**（h3≥h2）→ 与 h2>反弹顶合并高矛盾，不可能；
3. **bar3 严格低于 bar2**（h3<h2 且 l3<l2）→ 此时 bar2 高过 bar1（底分型肩）与
   bar3、低也高过两者 → **bar2 自成顶分型**，多出多余分型；且 fx@1 与 fx@2 共用
   bar1/bar2、零独立 K 线，不能充当设计顶。

评审建议中"抬高反弹腿各 bar 低点"恰落入分支 1（必成包含）。三分支均死 →
右肩版不可实现。**暴力枚举佐证**（`/tmp/rereview_fork.py`，5 档价格网格全枚举
6-bar 序列、放宽到旧笔口径允许顶@4）：满足"无包含+无多余分型+口径B放行+
右肩高于反弹顶"的序列 **0 条**。

左肩改造保住了判别本质：口径 A 的"整个分型区间"合并高被 bar0=12.3 抬高，
口径 B 只读底中间 K 线 11.0 —— A 拒 / B 放行的对立读数真实存在（见第 2/3 节）。
fx 位置、expect、claim_refs 不变，设计意图保留。

### 8b. bi-002 改用途（两口径一致不成笔 → 向下笔判别样本）：**不可实现性证明成立，改造有效** ✅

- 不可实现性：向上笔"两口径一致不成笔"要求口径 B 也否决，即顶中间高 ≤ 底中间高
  h1；但底分型右肩必高于底中间（h2>h1≥顶合并高），回到 8a 同一三分支死局。
  故**口径 B 对任何可构造的相邻分型恒放行，"两口径一致不成笔"样本不存在**——
  证明成立。且该结论本身即 ADR-001 仲裁证据（课 77 区间条件只在口径 A 下有牙齿），
  已写入 bi-002.yaml:13-20 头注，证据价值不低于原设计。
- 改造有效性：新样本为 BI-003 镜像（顶@1→底@5，A：10.5>10.4 不成笔 / B：10.5<11.0
  成笔），第 2/3 节已实证两实现真实走到向下笔区间判别（chanpy strict 拒、half/loss
  放行 (1,5,down)、czsc 放行），claim_refs 不变，镜像理由与翻转预案（ADR 改判 B 时
  expect 如何翻转）均在头注写明。

## 9. 遗留项（Minor，不阻塞 Approved）

1. `task-7c-report.md:14-15` 构造方法节仍写"末条笔/分型由尾部反向 K 线完成确认
   （sure: true）"，与修复后 YAML 状态（末位 sure:false）不符；歧义节#3 的标注已
   声明原约定作废，但建议顺手修订该行使文档自洽。
2. `task-7c-report.md:17-18` 仍写"每条用例带额外顶层键 description"，M-2 移除后
   该句已失实，建议删除或改为"曾携带、已移除"。

## 附：复核产物

- 机械校验脚本 `/tmp/rereview_check.py`；右肩不可实现证伪脚本 `/tmp/rereview_fork.py`；
  全量报告 `/tmp/rereview.md`（均未入仓）。
