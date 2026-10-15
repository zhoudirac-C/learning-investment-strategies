# gator-method（鳄鱼派方法论提炼库 · 只读参考）

> 来源：https://github.com/201901060324/gator-method
> 落盘时间：2026-10-15（commit 快照，非 git 跟踪，已移除 .git）
> **定位：第三方提炼参考库，非鳄鱼派 UP 原文。只读引用，不进 claim 管线。**

## 用途

- 双学派架构（`docs/design/dual-school-architecture.md`）中 gator 学派的 pattern/规则**提取原料**
- 50 章规则体系（`03-规则体系/`）+ 决策流程（`02-决策流程.md`）+ 703 篇行情对齐（`05-行情对齐/`）
- 每日日报（`07-每日日报/`）可作为我们 we-mp-rss 公众号抓取的**对照源**校验完整性

## 使用纪律

1. **禁止直接修改本目录** — 更新只走"上游仓库重新克隆覆盖"
2. **提 claim 时**：凡源自本目录的规则，claim 的 source_path 必须指向本目录路径，
   up_id 用 `gator-ecyu-0001` 但 provenance 标注 `third_party/gator-method`
   （后续用我们抓的公众号原文校验/替换）
3. **时效性**：部分规则带时间戳（如 20250710 融资盘选股法），引用时保留 source_date

## 上游跟踪

- 上游活跃（2026-10 仍在更新日报），建议**每月定期拉取覆盖一次**
- 关注方式：GitHub watch 仓库 201901060324/gator-method（release/commits 通知）
- 若上游发布新章节（55+ 章编号），同步触发 P3 的 pattern 增量提取
