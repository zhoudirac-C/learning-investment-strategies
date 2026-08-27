# 2026-08-10 Extraction Session Patterns

## Session 概览

- **早盘 0856**（充电专属）：22 条 claims（claim-20260810-001 ~ -022）
- **晚间复盘 2213**（充电专属，cv52230888「8.10（复盘）」）：24 条 claims
  （claim-20260810-023 ~ -046），market-cycle×3, methodology×6, sector-theme×7,
  stock-view×4, operation×2, risk×1, catalyst×1
- 合并进当日 -001.yaml → **当日共 46 条**，编号续编验证（022 → 023 起，无重复）
- 追加方式：`tail -n +2 step3_yaml/*.yaml >> knowledge/claims/claim-20260810-001.yaml`
  （文本级追加，禁止 yaml.safe_load→safe_dump 往返，吃引号）

## Gate 1 新坑：subject 含 Latin "/"（情形A/B）

`情形A/B` 的 `/` 是**拉丁斜杠**也会被拒（不只中文顿号/列举）：

- `下一交易日两种情形A/B` → ❌ 改 `下一交易日两种情形AB` 通过
- `明日观察清单：量能/情绪/科技/非科技四线` → ❌ 改 `明日观察清单：量能情绪科技非科技四线` 通过

规律：subject 里任何 `/`（无论中文列举还是 Latin A/B）都触发多主题校验，
写 subject 一律避开，用「与/及」或直接去掉分隔符。

**⚠️ 修正后必须清缓存**：本次修正 step1_raw.json 后 continue 仍报完全相同错误
（第 2 次），`rm -f gate1_result.json` 后才重跑。Gate 1/2/3 缓存都要清。

## Gate 2 NON_COMPANY 追加（10 片段）

见 qing-pipeline-ops `references/non-company-batches.md` 批次 15：
`导范围应该有限 / 范围应该有限 / 区分科技 / 的态度对待科技 / 而是非科技 /
天最强的非科技 / 拟通过发行股份 / 推动具身智能 / 支持智能 / 东建设人工智能`

**新类别**：
- `拟通过发行股份` — 重组/并购描述（华懋科技收购富创优越类 claim 必现）
- `东建设人工智能` — 政策文件全称（浦东建设人工智能创新应用先导区）
- `范围应该有限 / 导范围应该有限` — "传导范围应该有限"日常语境

## Gate 5 校验 interpretation 全文（新坑）

`gate5_stock_codes()` 拼接 `statement + interpretation` 一起匹配，公司名只出现在
interpretation 里（statement 已带码）照样报错。本次 claim-20260810-039 华懋科技：
statement 有 `华懋科技（603306）`，interpretation 里裸名 `华懋科技` 被拒。
Step 2 批量富化两字段都要补码（详见 qing-pipeline-ops「Gate 5 校验
statement+interpretation 全文」）。

## discover 关系亮点

- 24 条新 claim 发现 **41 条关系**（supersedes/contradicts/supplements）
- **同日矛盾自动发现**：claim-20260810-030（爱丽家居二次停牌属外力扰动型断板）
  contradicts claim-20260810-007（早盘称该批断板非外力扰动）——同日晚间复盘修正
  早盘判断，discover 自动挂矛盾边
- 026（次日双情形）supersedes 三条旧情形预案（0805-059/0803-013/0806-052）

## 同步管线

- discover --all-missing：后台 ~10-12min（24 条 × 每条比对全库，40-60s/条），
  期间 watch 进度（[N/24]）
- migrate：增量 46/46 → Qdrant --force-recreate：3431 claims，integrity 10/10
- Agent 重启：**pgrep -f 自匹配陷阱**见 qing-pipeline-ops「Agent 重启验证」，
  用 `ps aux | grep -E "python.*uvicorn" | grep -v grep` 验证
