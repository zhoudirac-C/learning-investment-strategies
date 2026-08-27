# 2026-08-03 Extraction Session Patterns

## Session 概览

- **早盘 0857**（充电专属）：15 条 claims（claim-20260803-001 ~ -015），C2 单 session
- **盘中 0957/1304/1418**（三条）：11 条 claims（-016 ~ -026），合并进当日 -001.yaml → 当日共 26 条
- 编号续编规则验证通过：新批次从已有最大号 +1（001-015 → 016 起），无重复 ID

## Gate 2 NON_COMPANY 实战记录

### 早盘（15 条）— 一次性 14 个片段

误报全部来自"科技"语境词（正则 2-5字+科技 后缀）：

```
核心框架是科技 / 如果理解科技 / 的反弹是让科技 / 大金融与科技 /
重新走强而科技 / 形态本质是科技 / 绿被定性为科技 / 且它与科技 /
维持非科技 / 宇树科技 / 器人看宇树科技 / 前置对全球科技 / 对全球科技
```

**关键教训**：第一轮只加了 "宇树科技" 和 "对全球科技"，重跑后仍报
"器人看宇树科技" 和 "前置对全球科技" —— 报错片段是正则完整匹配
（5 字前缀+科技），必须加与报错完全一致的完整片段。见
qing-claim-extraction-debug §13。

### 盘中（11 条）— 韩股无 A 股代码

```
以及三星电子 / 三星电子和SK海力士 / 三星电子、SK海力士 /
三星电子能否守住 / 三星电子均跌
```

三星电子、SK海力士是韩股（无 6 位 A 股代码）→ NON_COMPANY。
宇树科技 8/10 才申购（未上市）→ NON_COMPANY。均非假阳性，是真公司。

## 同日多来源合并（已验证流程）

```
start(第一条 raw) → 一次 session 写全部 3 条 raw 的 claims（每条各自 source_path）
→ Gate 1/2/3 → step3 YAML → Python yaml 合并进 claim-20260803-001.yaml
→ gate_validate_claims.py 全文件验证（26 条全过）→ done 拒绝清理 → rm -rf session
```

- Gate 1 不校验 source_path 唯一性，一个 session 可混多条 raw
- `done` 拒绝清理因为 step3 YAML 未移走（已知行为）→ 直接 `rm -rf temp/claims/<session>`
- 合并用 `yaml.safe_load` + `extend` + `safe_dump(allow_unicode=True, sort_keys=False, width=1000)`，
  之后 gate_validate 验证格式未被破坏

## 同步管线（服务端模式手动分步）

Qdrant 服务端模式（port 6333, RocksDB）下不需要停任何进程：

```
discover --all-missing（15+11 条：早盘 28 relations，盘中 17 relations 含 2 contradicts）
→ migrate_claims_to_neo4j.py（增量 MERGE）
→ index_claims_to_qdrant_monitored.py（增量，3129 → 3140 claims，integrity 通过）
→ Agent 被杀 → 手动重启 uvicorn → health ok → MCP 检索验证新 claim
```

两次索引后 Agent 都被 `_kill_agent_if_running()` 杀掉且无 systemd 守护不自动重启，
必须手动拉起（详见 qing-pipeline-ops §二 新增两条坑）。

## 其他

- discover 关系亮点：claim-20260803-013（双情形预案）supersedes claim-20260731-009；
  claim-20260803-024（等待克制）contradicts claim-20260731-018（加仓参与反弹）——同日
  观点演进链在 discover 阶段自动发现，无需手工维护
- 盘中 1304 是长文本（韩股分析+A股轮动+操作纪律），拆出 9 条 claim，颗粒度按
  "每个独立定性判断一条"执行

## 复盘补充（2213 晚间复盘，027-044）

### Session 概览

- **复盘 2213**（充电专属）：18 条 claims（claim-20260803-027 ~ -044），
  market-cycle×4, sector-theme×6, stock-view×3, methodology×1, operation×4
- 合并进当日 -001.yaml → **当日共 44 条**（早盘 15 + 盘中 11 + 复盘 18），
  编号续编再次验证：015 → 016 → 026 → 027 起，无重复

### Gate 1 两个新坑（见 SKILL.md §15）

1. **subject 含 '+' 被拒**（多主题嫌疑）：情形A/B 的 subject 写
   "量能回升+强者恒强" 被拒，改成 "量能回升与强者恒强" 通过。
   写 subject 时一律用"与/及"代替 `+`。
2. **Gate 1 缓存**：修改 step1_raw.json 后 continue 仍报**相同错误列表**
   （第 2 次），`rm -f gate1_result.json` 后才重跑。改 step 产物后
   gate1/gate2/gate3 缓存都要清。

### 复盘 NON_COMPANY 追加（13 片段）

```text
资金从科技 / 号框架定位科技 / 体是今天科技 / 应用与智能 / 拆解科技 /
这构成科技 / 配网智能 / 龙头向企业智能 / 代搭载触觉智能 / 短期来看科技 /
给出明日科技 / 位补涨切回科技 / 重心应回到科技
```

全是"科技/智能"语境词（"配网智能化""企业智能体""触觉智能"等被拆成
2-5字+科技/智能 匹配）。累计三次提取（早盘/盘中/复盘）NON_COMPANY 已扩
~32 个片段——"科技/智能"后缀是稳定假阳性源，新提取若再遇可先查此模式。

### 同步管线第三次验证

- discover：33 relations（含 1 contradicts：043 情形B量能萎缩 vs
  claim-20260723-030 情形B重新放量）
- migrate 44/44 → monitored 索引 3158 claims → **Agent 第三次被杀** →
  手动重启 → MCP 检索验证 044 命中
- 结论固化：每次索引后 `curl localhost:8000/health` 必查，被杀即重启，
  无 systemd 守护不会自动恢复
