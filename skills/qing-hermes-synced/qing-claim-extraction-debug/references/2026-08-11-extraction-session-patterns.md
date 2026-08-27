# 2026-08-11 Extraction Session Patterns

## Session 概览

- **早盘 0906**（充电专属，dynamic 1235112348132311063）：29 条 claims
  （claim-20260811-001 ~ -029），market-cycle×4, methodology×8, operation×4,
  sector-theme×7, stock-view×2, catalyst×3, macro×1
- **新日期首条提取**：`knowledge/claims/` 无 claim-20260811*.yaml → 直接
  `cp step3_yaml/claim-2026-08-11-output.yaml knowledge/claims/claim-20260811-001.yaml`
  （不同于同日多来源的 tail 追加；新日期 = 新文件，编号从 001 起）
- 预检查确认：已有 claims 全部来自 8/10（0856 早盘 22 条 + 2213 复盘 24 条），
  8/11 内容未覆盖 → 可提取

## Gate 1 新坑：subject 含 Latin "+"

8/10 记录过 `/`（情形A/B），8/11 新增 **`+` 同样触发多主题校验**：

- `新题材筛选模型：超跌+事件催化+一字定方向` → ❌ 改 `超跌事件催化一字定方向` 通过

规律：subject 里 `/`、`+`、`、` 都触发多主题校验。**写 subject 时先自查这三个字符**，
避免 Gate 1 首轮失败（还要清缓存重跑，浪费时间）。

## Gate 2 NON_COMPANY 追加（10 片段）— 科技/非科技方向对比句式

本批次全是**方向对比句式**（"不是靠科技...而是靠非科技"），与前几批"Xx科技公司名"
模式不同——这里的"科技/非科技"是**方向名词**，复盘/早盘几乎必现：

```
前提是科技 / 指数不是靠科技 / 而是靠非科技 / 为代表的科技
流卡位而非科技 / 的形态是非科技 / 式更可能是科技 / 而不是科技
能是资金在科技 / 给出非科技
```

**规律**：含"科技/非科技/智能/人工智能/有限"的方向对比长句式，Gate 2 失败时
**整批错误列表补入 NON_COMPANY**（不是逐条改 statement）——补集合比改文本快且一劳永逸。
注意 `为代表的科技` 这类 5 字片段必须与报错完全一致（完整正则匹配片段）。

## 8/11 早盘与 8/10 复盘的关联

- 影视连续两天出现：8/10 复盘 claim-042/043（北京文化《欢迎来龙餐馆》点映逆跌），
  8/11 早盘 claim-010~013 判"预期前置打满→事件当天只剩兑现"——discover 自动挂
  supersedes（011 supersedes 010-042/043/036）与 contradicts（010 contradicts 042）
- 爱丽家居停牌判断演进：8/10 早盘 007（非外力扰动）→ 8/10 复盘 030（外力扰动型）
  → 8/11 早盘 009（单只停牌难扭转情绪）——三天三变，discover 关系链完整记录

## 同步管线

- discover --all-missing：29 条 → 后台 ~13min，**53 条关系**
- migrate：增量 107/107（含 8/10 的 46 条 + 8/11 的 29 条 + 历史补充）
- Qdrant --force-recreate：**3460 claims**，integrity 10/10
- Agent 重启验证：`curl /health` → `{"status":"ok"}`；Qdrant points_count=3460
