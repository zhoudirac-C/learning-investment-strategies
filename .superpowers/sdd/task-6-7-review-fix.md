# Task 6/7 评审修复报告（C-1 / I-1 / M-1 / M-2）

> 修复对象：`.superpowers/sdd/task-6-7-review.md`（2026-07-19 09:54）列出的
> 1 Critical + 1 Important + 2 Minor。执行范围仅 `src/chan_engine/spec/cases/*.yaml`
> 与 `task-7c-report.md` 标注，未动 harness/model/case_io 代码，无 git 写操作，
> third_party/chanpy 原样。

## 验证结果（修复后）

```
$ PYTHONPATH=src:third_party/chanpy .venv/bin/python -m pytest tests/chan_engine/ -q
146 passed in 1.34s

$ PYTHONPATH=src:third_party/chanpy .venv/bin/python -m chan_engine.harness.report \
    --cases src/chan_engine/spec/cases --out /tmp/chan_fix/calibration_after_fix.md
chanpy: PASS 0 / FAIL 26 / ERROR 0；czsc: PASS 5 / FAIL 21 / ERROR 0（CLI 端到端正常）
```

## C-1：bi-002 / bi-003 bars 重推

### 关键发现（修复过程中证明，直接影响 ADR-001）

**"两口径一致不成笔"样本在几何上不存在。** 底分型右肩按分型定义必高于底中间
K 线；若反弹顶低于底中间 K 线（口径 B 否决的唯一形态），则右肩到该顶之间
非包含合并即多出中间分型——口径 B（仅比分型中间 K 线）对任何可构造的相邻
分型恒放行。课 77 区间条件只在口径 A（整个分型区间，含肩部）下有牙齿。
**此结论是 ADR-001 仲裁的直接证据：若取口径 B，该条件形同虚设。**
评审修复建议（"保留右肩抬高合并高、压缩 bar2 振幅"）与此冲突，故按几何
可行性调整如下，提请复核裁定。

### BI-003（向上笔 A/B 判别，设计意图保留）

- 把"抬高合并高"从右肩（bar2，几何上必死）移到**左肩 bar0**（高 12.3）：
  右肩 bar2（11.2）低于顶@5（11.4），反弹腿单调上升 → 全程零包含、无多余
  分型、bar3 独立 K 线（新笔口径满足）、两分型不共用 K 线。
- **fx 位置（1/5）、expect、claim_refs 全部不变**；口径读数：A 11.4<12.3 不成笔 /
  B 11.4>11.0 成笔。
- 实证：chanpy strict（默认）bi=[]，同输入 `bi_fx_check=half/loss` 画出
  `(1,5,up)`——拒绝唯一来自区间检查；czsc 画出 `(1,5,up)`。判别场景两实现
  均真实走到（修复前评审实证：czsc 产出多余 `fx idx=2 up`、chanpy 遇不到判别）。

### BI-002（改造为向下笔 A/B 判别，BI-003 镜像）

- 原设计"两口径一致不成笔"依上述证明不可实现，改造为**向下笔判别样本**
  （顶@1 → 底@5；顶合并低由左肩 bar0=10.4 压低；A：底中间低 10.5 > 10.4
  不成笔 / B：10.5 < 11.0 成笔），同步验证两实现的**向下笔**区间检查。
- fx 位置（1/5）、bi: [] expect、claim_refs 不变（fx type 镜像为 up/down）。
- 实证：chanpy strict bi=[]（half/loss 画出 `(1,5,down)`）；czsc 画出 `(1,5,down)`。
- 头注已完整记录不可实现性证明与改造理由。

### 复跑对照（修复后 CLI 偏差明细）

- BI-002/003 × chanpy：仅剩"缺 fx"（适配器从笔端点推导 fx 的已知归一方式，
  无笔则无 fx），bi 表与 expect 一致（[]）；
- BI-002/003 × czsc：多 `(1,5)` 笔（口径 B 行为）+ 缺首 fx（已知归一差异）——
  A/B 分歧成为校准矩阵真信号，无合并污染。

## I-1：6 条末位 sure 口径统一

- bsp-001..004、bc-001..002 的末位 fx 与末位 bi 之后均无反向笔，按 seg 族
  在先裁定（task-7-report 追加节）全部改 `sure: false`，**共 12 处**。
- task-7c-report.md 歧义节#3 已标注"已按裁定统一"。
- 实证：BSP-001 × czsc 偏差明细中末位 sure 噪声消失（修复前为
  `fx idx=31 sure 期望 True 实际 False` 等）；× chanpy 剩余的 sure/dir 差异
  为已记录的实现语义差（is_sure=笔已完成 / BSP dir 待仲裁），属 Task 9 素材。

## M-1：bi-002 头注数值口径

- 头注已随 C-1 整体重写，新构造数值（10.4 / 10.5 / 11.0）经程序化校验与
  真实适配器双重复核，原"12.3 vs 12.5"问题随旧构造一并消除。

## M-2：description 顶层键

- 采取"移除"方案（保持 schema 窄口径、避免批次间格式漂移）：删除 7c 批次
  6 个文件的 `description` 顶层键；内容本就与头注重复，无信息损失。

## 交付文件

- 重写：`src/chan_engine/spec/cases/bi-002.yaml`、`bi-003.yaml`（bars + 头注）
- 编辑：`bsp-001..004.yaml`、`bc-001..002.yaml`（各 2 处 sure 翻转 + 删 description）
- 标注：`.superpowers/sdd/task-7c-report.md` 歧义节#3
- 校验 scratch（未入仓）：`/tmp/chan_fix/verify_bars.py`（包含/分型/区间 A/B
  独立断言）、`/tmp/chan_fix/adapter_check.py`（真实适配器对照）
