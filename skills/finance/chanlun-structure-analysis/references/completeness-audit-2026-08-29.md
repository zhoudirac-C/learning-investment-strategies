# 缠论 skill 完整性审查（2026-08-29 课程×代码五方复核）

对照课程讲义 `docs/learning/chanlun-course-notes.md` ↔ wiki `knowledge/wiki/投资方法论/缠论.md`
↔ SKILL.md ↔ references ↔ `src/chan_engine/` 代码五方审计的完整证据与修复路线图。

## 缺陷清单（P0 / P1）

### P0 结构
1. **双份 skill 并存且 references 不同步**：
   - 本地 `~/.hermes/skills/finance/chanlun-structure-analysis/`（8 个 references，活跃副本）
   - repo `learning-investment-strategies/skills/finance/chanlun-structure-analysis/`（仅 4 个 references，缺 chan-engine-* 文件）
   - SKILL.md 两份 md5 相同（163 行），但裸名 `skill_view('chanlun-structure-analysis')` 报 Ambiguous；
     repo 侧引用的 chan-engine-* reference 是死链
2. **课程进度声明不一致**：SKILL.md 称"P4 讲义+四面板图解已授，5 题待答"，但 course-notes.md 正文只到 P3，
   P4 仅有预告行、无讲义正文/检验题 → P4 内容可能只在会话记录里，需 session_search 找回补档
3. **引擎状态 reference 过期**：`references/chan-engine-m7-multitf.md`（8/28 快照）称"M7 v1.2 未实施/G1-G4 缺失"，
   但代码已实现：G1/G2（core/trend.py 走势类型状态机）、G3（core/backchi.py:93 背驰前提校验）、
   G4（core/backchi.py:219 二买 bstype=2）；8/29 已切换 M7-5 → 以代码为准，真欠项仅 G8 同级别分解/G10 小转大

### P0 理论缺口
4. **小转大无判定口径**：`chan_analysis.py:317` 只打印"小转大候选（须人工与大级别背驰确认）"；
   teaching-figures 只画过示意面板。wiki §6.3 理论已齐：小级别背驰→大级别转折的**必要条件**
   = 最后次级别中枢出现第三类买卖点（无充分条件）。引擎 G10 欠缺 → 报告不可断言小转大
5. **中阴阶段零覆盖**：wiki §3.4（走势类型死亡→新生间模糊期，必先出现大一级别中枢，健康震荡须落在
   前中枢范围、回到第二中枢=不健康）未入 SKILL/教学/引擎输出

### P1 文档-实现脱节
6. **SKILL 正文缺线段层**：管线描述仍是"分型→笔→中枢→背驰"；引擎实际是"分型→笔→线段(L0)→段中枢→
   走势类型"。segments.py 自建分组规则：最小段=3笔/同向扩展创极值/残笔不成段/sure 透传
7. **教学文档仍引用旧函数链**：SKILL.md 概念教学节、teaching-figures.md 用 merge_inclusion→find_fractals→
   find_bi→identify_zhongshu（M7-5 后不在执行路径，仅教学参考）
8. **输出契约未要求显式"背驰前提"字段**：G3 已实现但报告不展示前提是否满足（有趋势？c 段创新高？）

### 覆盖度结论（对照课程 P1-P6）
- ✅ P3 中枢级别 / P4 背驰（除小转大）/ P5 三类买卖点 / 资金管理纪律（T+1、分批挂单、防守线）
- ⚠️ P2 均线系统"退居辅助"未在 SKILL 正文说明；中阴/小转大缺失（见上）

## 修复路线图（顺序 1→8，用户未拍板=暂不实施）

1. 双份归一：以本地为权威，同步 repo 镜像 references（或确认 external_dirs 注册后删除旧镜像）
2. P4 讲义补档：session_search 找回 → patch 拼接进 course-notes.md（**勿 write_file 整文件覆盖**，
   覆盖过一次 P1/P2 的历史教训）
3. 小转大判定流程入 SKILL 背驰节：小级别背驰 → 查最后次级别中枢是否出三类买卖点 → 出=大级别转折候选；
   不出=正常震荡不升级
4. 中阴入 SKILL 输出惯例：仓位性质新增「中阴/待定」标签：走势类型死亡后未确立新生 = 等大级别中枢出现，
   震荡不健康（回到第二中枢）即降级
5. 更新 chan-engine-m7-multitf.md 状态（G1-G4 已实现、M7-5 已切换）
6. SKILL 管线描述补线段层 + 旧函数链降级为"仅教学参考"
7. 输出契约加"背驰前提"字段（G3 已实现，强制标注前提是否满足）
8. 可选：P2"均线退居辅助"一句说明补入正文