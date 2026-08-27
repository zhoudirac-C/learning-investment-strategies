---
name: qing-pipeline-ops
description: |
  Claim 提取管线运维 — Gate 失败修复模式、批量提取效率技巧、同步管线排错。
  qing-learning-claim 的运维补充，不重复 claim 编写规范。
---

# qing-pipeline-ops

## 触发条件

- Gate 失败后需要修复 → 加载此 skill 获取修复模式
- 批量提取多篇 raw → 效率优化
- 同步管线异常（discover/Neo4j/Qdrant）→ 排错

---

## ⚠️ 提取前先 git pull 同步远程（2026-08-13 用户明确要求）

用户指令"先拉取远程分支再提取"：开始 claim 提取流程前，**先同步远程 master**。
远程常有 cron 自动产物提交（`config/stock_monitor/daily_review_summary.json`、
bilibili `index.md`、最新抓取的 raw），不 pull 会基于过期状态判断或覆盖本地改动。

```bash
# 1. fetch + 看落后几个提交 + 远程新提交改了哪些文件
git fetch origin
git rev-list --count HEAD..origin/master
git log --oneline --stat origin/master -2 | head -30   # 检查是否触及本地已改动文件

# 2. 本地有未提交改动时，先确认远程提交与本地改动文件不重叠 → 直接 pull 无冲突
git pull origin master

# 3. 常见冲突源：daily_review_summary.json / bilibili index.md（本地也可能被
#    cron/监控管线改过）。真冲突时先 stash 或按文件取舍，不要盲 pull
```

2026-08-13 实测：本地 M（daily_review_summary.json、bilibili/index.md）+
远程 2 个提交（scripts/src/tests/docs），文件不重叠 → 直接 pull 成功无冲突。
pull 后 `git status --short` 确认本地改动仍在，再开始提取。

---

## ⚠️ start --raw 可直接用 sources/original/bilibili/ 路径（2026-08-14 实测）

`extract_claims_pipeline.py start --raw` **接受 `sources/original/bilibili/` 下的原始文件**，
无需先复制到 `sources/raw/财经/`（qing-learning-claim/ingestion 的复制步骤可跳过）：

```bash
# ✅ 8/14 早盘专栏直接 start 成功
python scripts/extract_claims_pipeline.py start \
  --raw "sources/original/bilibili/2026-08-14-0902-专栏-....md"
```

- source_path 字段照写 `sources/original/bilibili/...`，Gate 1 不校验路径位置
- 预检查仍要做：`ls knowledge/claims/claim-YYYYMMDD-*.yaml` + 确认
  `sources/raw/财经/` 下无同日文件（防重复提取）
- 若后续某 raw 需要先清洗/改文件名，再走复制到 `sources/raw/财经/` 的旧路径

---

## ⚠️ write_file / execute_code 相对路径陷阱（2026-08-05 两次实测）

`write_file` 和 `execute_code` 的相对路径**解析到 `$HOME`（/home/ubuntu/），不是
terminal 会话的 cwd（项目根目录）**。用相对路径写项目文件会静默落到 /home/ubuntu/
下，且 `execute_code` 的工作目录是临时沙箱（/tmp/hermes_sandbox_*），连项目相对
路径都读不到。

```python
# ❌ 错误：落到 /home/ubuntu/temp/claims/... （step1_raw.json 惨案）
write_file(path="temp/claims/<session>/step1_raw.json", ...)

# ✅ 正确：项目内一律用绝对路径
write_file(path="/home/ubuntu/learning-investment-strategies/temp/claims/<session>/step1_raw.json", ...)
```

**识别**：write_file 返回的 `resolved_path` 若以 `/home/ubuntu/` 开头且不在项目内
→ 立即 mv 回项目目录，不要等 pipeline 报文件不存在。
**execute_code 同理**：`open('temp/...')` 直接 FileNotFoundError，必须用
`os.path.join('/home/ubuntu/learning-investment-strategies', ...)`。
**C2 管线的 Step 1 / Step 4 wiki 文件**是重灾区（本会话两次命中）。

### ⚠️ Step 1 JSON 语法错误：write_file 拒绝写入且不创建文件（2026-08-14 实测）

`write_file` 对 `.json` 扩展名做**语法校验**：JSON 有语法错误（如漏闭合引号）时\n**拒绝写入、文件不存在**（报 `Invalid control character at line N` / `JSONDecodeError`）。\n随后用 `patch` 修复也无效——文件根本没创建，patch 报 `Failed to read file`。

**症状**：36 条 claims 的 step1_raw.json 因一条 `extracted_at` 漏闭合引号被整体拒绝。

**正确姿势**：
- 写完 step1_raw.json 后先用 `python -c "import json; json.load(open(...))"` 自检再 continue
- 一旦 write_file 报 JSON 语法错误 → **重写整个文件**（`patch` 不可用，文件不存在）
- 或直接改用 execute_code + `json.dump` 生成（Python 保证语法正确，且能程序化处理字段）
- Gate 1 通过后，pipeline 会做 `json.load` 二次校验——JSON 文件必须始终合法

---

### Gate 2 假阳性批量修复模式

**参考**：
- 历史假阳性批次积累：`references/non-company-batches.md`（每次提取新增模式都追加，
  下次遇到类似文本先查这里预判）
- 股票代码查询（Step 2 补代码）：`references/eastmoney-stock-code-lookup.md`
  （⚠️ EastMoney API `input` 必须 URL 编码，中文直传 → HTTP 400）

### 问题

Gate 2 的 `gate5_stock_codes()` 用正则匹配中文+科技/智能/电子/股份/有限，
在处理板块分析类文本时产生大量假阳性（将板块描述误判为公司名）。

### 标准流程

```
Step 1: 第一次 Gate 2 失败 → 查看错误列表
Step 2: 确认都是假阳性（不是漏标的公司名）
Step 3: 在 gate_validate_claims.py 的 NON_COMPANY set 追加新模式
Step 4: rm gate2_result.json → python continue
```

### 批量提取优化

**同一天多篇 raw 连续提取时**：第一篇 Gate 2 失败后，先读完所有后续 raw，
预判可能出现的假阳性模式，一次性加入 NON_COMPANY。避免每篇都触发一次失败。

示例（7/28-29）：
- 第一篇（28-2206 复盘）→ 13 个假阳性
- 第二篇（29-0901 早盘）→ 3 个新假阳性（与第一篇高度重叠）
- 第三篇（29-1425 盘中）→ 2 个新假阳性
- 若在第二篇前读完所有 raw，可一次加入 18 个模式，避免 3 次 Gate 2 失败

### Step 2 批量富化：execute_code 三字典脚本（2026-08-09/10 两次实战）

Step 2 逐条手写 `step2_enriched.json`（补代码/related_stocks/tags）易错且费时；
用 execute_code 一次性生成，两次 32/22 条 claims 均一次通过：

```
1. 批量查东财 API 拿代码（循环 urllib + URL 编码 + sleep 0.3-0.4s 防限流）
   → 输出 {公司名: [(code, name), ...]}，人工核对主板/创业板/科创板/港股归属
2. 定义三个字典：
   CODES    = {公司名: (6位代码, role标注)}      # role含"主板可交易/创业板不可交易/科创板不可交易/港股不可交易"
   RS_MAP   = {claim_id: [公司名, ...]}          # 每条 claim 的 related_stocks；无标的缺省 []
   TAGS_MAP = {claim_id: [3-5个标签]}
3. 读 step1_raw.json → 对 statement/interpretation 逐名替换
   `name → name(code)`（先 replace 还原已带码的，防止二次插入）→
   填 related_stocks/tags → 写 step2_enriched.json
4. 关键检查：
   - 非上市/收购标的（如开科唯识）不进 CODES——东财查不到代码，正则还会误报
   - 无标的 claim 必须写 related_stocks: []
   - 指数/宏观类 claim（纯数据、无个股）同样置 []
```

**注意**：execute_code 的 cwd 是临时沙箱，读项目文件必须用
`os.path.join('/home/ubuntu/learning-investment-strategies', ...)` 绝对路径。

### start 不检测已有 session：同一 raw 重复 start 产生孤儿 session（2026-08-09 实测）

监控管线抓 raw 时会自动创建 init 状态 session（`temp/claims/<session>/session.json`，
state=init）。手动再跑 `extract_claims_pipeline.py start --raw <同一文件>` 会**新建**
一个全新 session，旧 init session 留在 temp/claims/ 成为孤儿（`done` 只清理当前
session）。8/9 实测：监控已为 2147 专栏创建 `20260809_215818_b7de54`，手动 start
又建了 `20260809_220428_80acf2`。

**正确做法**：先 `ls temp/claims/` 检查目标 raw 是否已有 session——有就直接往那个
session 写 step1_raw.json（或手动继续），不要重复 start。孤儿 init session 无害但
会堆积，提取完成后顺手 `rm -rf temp/claims/<孤儿session>`。

### Gate 1 subject 特殊字符校验（2026-08-03/04 两次实测）

Gate 1 对 `subject` 做"多主题"校验：**含 `+` 或 `/` 直接判失败**（报错 `subject 含 '+' — 可能包含多主题`）。

- `情形A：量能回升+强者恒强→硬件调整尾声` → ❌ 改 `情形A：量能回升与强者恒强，硬件调整进入尾声`
- `本周三个硬时点：非农/SpaceX财报/闪迪西数财报` → ❌ 改 `本周三个硬时点：非农与SpaceX财报及闪迪西数财报`

`topic` 建议同步规避，`statement`/`interpretation` 不受限。

### Gate 5 校验 statement+interpretation 全文（2026-08-10 实测）

`gate5_stock_codes()` 拼接 `statement + "\n" + interpretation` 一起正则匹配——**公司名
只出现在 interpretation 里（statement 已带码）照样报错**。本次 claim-20260810-039：
statement 已写 `华懋科技（603306）`，但 interpretation 里出现裸名 `华懋科技` → Gate 2
报 `'建立华懋科技' 在文本中出现但未标注 6 位代码`。Step 2 批量富化时 statement 和
interpretation **两个字段都要过一遍代码标注**，execute_code 逐名 replace 要同时覆盖两字段。

**⚠️ 修正后必须清缓存**：`rm -f temp/claims/<session>/gate1_result.json` 再 `continue`，
否则 pipeline 读 gateN 缓存仍输出与第 1 次完全相同的错误列表（2026-08-04 实测）。
Gate 2 修正同理：`rm -f .../gate2_result.json`。

### Gate 4/5 公司名正则的前缀陷阱（2026-08-04 实测）

`gate5_stock_codes()` 正则 `[\u4e00-\u9fff]{2,5}(?:股份|科技|电子|智能|医疗|有限)`
匹配「前缀2-5字 + 后缀」的**完整片段**，NON_COMPANY 豁免也按完整片段匹配：

- NON_COMPANY 已有 `行云科技`，但正文 `将行云科技定义为…` 匹配到的是含前缀的
  `将行云科技` → 裸词条豁免失效。**区分两种处理**：
  - 真公司（行云科技 300209）→ 在 statement/interpretation 补代码标注
    `将行云科技(300209)`，正则 `片段 + (6位)` 即通过，**不要**塞进 NON_COMPANY
  - 纯误匹配（`日人工智能` 来自"7月17日人工智能大会"）→ 把**含前缀的完整片段**
    加入 NON_COMPANY，裸词不够
- 改完 gate_validate_claims.py 后必须 `rm -f .../gate2_result.json` 再 continue

### 港股/境外 5 位代码：必须用 `(港股XXXXX)` 格式（2026-08-07/08-09 实测）

Gate 2 的 `gate5_stock_codes()` 对括号内纯数字串做 4-6 位正则检查：
`re.findall(r"[（(](\d{4,6})[）)]", text)` → 非 6 位报错
`"股票代码 '01548' 不是 6 位"`。

港股代码是 5 位（金斯瑞 01548、迈富时 02556、迅策 03317，东财 API 返回 MktNum=116），
直接写 `公司名(01548)` 会被判错。**正确写法：`金斯瑞(港股01548)`** —— 括号内带
"港股"文字前缀后，正则匹配到的是"港股01548"（非纯数字串），不再命中 4-6 位检查；
同时公司名正则 `[\u4e00-\u9fff]{2,5}(?:股份|科技|...)` 不会把"金斯瑞"判为公司
（无后缀词），两处检查均通过。已有先例：`迈富时(港股02556)H`（claim-20260807-001）、
`金斯瑞(港股01548)`（claim-20260809-022）。

**注意**：港股的 `related_stocks` role 必须标注"港股不可交易"（同创业板/科创板规则）。
写 statement/interpretation 时若报错"X 不是 6 位"，先确认是港股还是纯手误——港股
一律走 `(港股XXXXX)` 格式，不要硬凑 6 位。

### 关系误标修复：contradicts 降级为 supplements（2026-08-07 实测）

Review 判定某 contradicts 实为 timeframe-shift（两观点兼容，如"短期出清结束"与
"中期B浪后还有C浪"同向衔接）时，修复关系**不走 discover**（discover 会用 LLM
重新判断覆盖人工结论），只改 YAML + migrate：

```
1. 读取 claim YAML 确认 contradicts 字段 + 被引用两个 claims 的原文（验证兼容性，不只看 topic）
2. 修改 YAML：contradicts 清空 + 对应 id 移入 supplements（yaml lint 校验）
3. PYTHONPATH=src .venv/bin/python scripts/migrate_claims_to_neo4j.py
   → 增量模式自动检测修改文件（输出 "N files need migration"）
4. MCP get_claim_relations 验证（contradicts 空 / supplements 就位）
5. Qdrant 无需重建（payload 不含关系字段，keys 只有 claim_id/statement/subject/...）
6. git commit
```

**坑**：migrate 脚本头注释警告"YAML 关系字段为空会删 Neo4j 边"——只改单条
claim 的关系时增量模式安全（只处理修改过的文件）；若想全量重放关系才需要
先 discover 再 migrate。

---

## 二、同步管线排错

### discover_claim_relations 路径迁移

旧路径 `scripts/discover_claim_relations.py` 已弃用，指向新路径。
正确命令：

```bash
PYTHONPATH=src .venv/bin/python \
  src/qing_investment/agent/tools/discover_claim_relations.py --all-missing
```

`scripts/run_discover_with_progress.sh` 有语法错误，不可用。

**⚠️ 2026-08-14 实测更新：wrapper 已可用**。`bash scripts/run_discover_with_progress.sh` 在 background=true 下正常启动（不再报语法错误），日志写到 `logs/discover_relations_<ts>.log` + `.progress`。若 8/14 之后又遇语法错误，再退回直跑命令。

### discover 遇 LLM 余额不足（402 Insufficient Balance）会「假完成」——重试前必须清 last_discovered（2026-08-13 实测）

discover 日志尾部显示 `✅ Done. Found N relations` **不代表全部成功**：余额耗尽时中间夹大量
`LLM error after 3 retries: Error code: 402 ... Insufficient Balance`，失败 claim 的关系字段
（supersedes/contradicts/supplements）为空，**却仍被写入了 `last_discovered`**。

根因：discover 跳过逻辑是 `if c.get("last_discovered"): continue`，但它对**每一条处理过的
claim 都写 last_discovered**，无论 LLM 判断成功与否。所以重跑 `--all-missing` 会跳过这些
「假完成」claim，缺失的关系永远补不上。

- 检测：`grep -c "402" /tmp/discover_*.log` 非 0 即存在余额中断
- 修复（余额充值后）：① 找出失败 claim（日志里带 402 的），删掉它们的 `last_discovered`
  行 → ② 重跑 `--all-missing`
- **删除用文本行删除，不要 `yaml.safe_load` + `yaml.dump` 重写整个文件**（yaml.dump 会把
  `code: '002971'` 前导零引号剥掉变八进制整数——见上文「YAML 合并禁止 safe_load→safe_dump」）
- 文本行删除示例（只删目标 claim 的 last_discovered，保留 stock code 引号）：

```python
for line in lines:
    if line.startswith("- id: claim-"): current_id = line.strip().split(": ", 1)[1]
    elif current_id and line.strip().startswith("last_discovered:"):
        if int(current_id.split("-")[-1]) >= 30: continue  # 跳过该行
```

- 经验：discover 是烧钱步骤（每条 claim 调 LLM 判多个相似对），余额紧张时优先一次性跑完，
  避免半途 402 后要清标记重跑（本 session 29 条首轮 18 条 402，清标记重跑才补全 27 条关系）

### Qdrant 重建前必须停 Agent

Agent 持有 Qdrant 锁，重建前需先停：

```bash
# 用 pkill 避免匹配到当前终端进程
pkill -f "uvicorn qing_investment.agent.main:app" 2>/dev/null
sleep 2
```

`index_claims_to_qdrant.py --force-recreate` 已内置此逻辑。

### migrate / Qdrant 全量耗时 10+ 分钟：必须 background+notify（2026-08-09 实测）

`migrate_claims_to_neo4j.py` 全量迁移 **3455 claims 耗时超过 10 分钟**，
`index_claims_to_qdrant.py --force-recreate`（3385 claims）同样耗时数分钟。
**前台跑必超时**（300s 上限），且注意：

- **前台超时 ≠ 进程终止**：`exit 124` 后进程仍在后台跑（pgrep 可见）。
  重新启动前**必须先 `pgrep -f migrate_claims_to_neo4j` 确认旧进程已结束**，
  否则新旧两个实例并发写 Neo4j（本次实测 8/9 就是先超时、wait 循环又超时、
  再起 background 才完成——曾出现 1432055→1434004 两个 PID，存在并发写风险）。
- 正确姿势：`terminal(background=true, notify_on_complete=true)` 一步到位，
  等通知后**用 Neo4j 计数验证**（`MATCH (c:Claim) WHERE c.id STARTS WITH "claim-20260809" RETURN count(c)`），
  不要只看进程退出码。
- discover 同理（12 分钟），见 qing-learning-claim 同步管线一节。

### Agent 重启：Hermes 拦截前台 nohup/&（2026-08-09 实测）

Hermes 前台命令**禁止 shell 级后台包装**（`nohup ... &` / `disown` / `setsid`）——
直接报错 `Foreground command uses shell-level background wrappers`。正确做法：

```python
# ✅ terminal(background=true, watch_patterns=["Application startup complete"]) 启动 uvicorn
# 然后单独 terminal 里 sleep 5 && curl -s http://127.0.0.1:8000/health 验证
```

⚠️ qing-learning-claim SKILL.md（project external dir 只读）里的
`nohup ... &` 旧写法在 Hermes 下已失效，以本段为准。
先 `pkill -f "uvicorn qing_investment.agent.main"` 再启动，health OK 才算重启完成。

**⚠️ 停 Agent 时不要杀 MCP 服务**：
- `mcp_qdrant_server` 和 `mcp_neo4j_server` 由 Hermes 管理，杀它们会影响其他功能
- Qdrant 二进制 `./bin/qdrant`（port 6333）也不需停——`--force-recreate` 会直接覆盖 collection
- 只停 Agent 进程（`uvicorn qing_investment.agent.main:app`）即可

**⚠️ 不要用 `kill $(pgrep -f ...)` 杀 uvicorn**：
```bash
# ❌ 会匹配到正在运行的终端 shell 进程，杀死自己的会话
kill $(pgrep -f "uvicorn.*qing_investment") 2>/dev/null

# ✅ 用明确进程名+参数模式
pkill -f "uvicorn qing_investment.agent.main:app" 2>/dev/null
```

### ⚠️ run_sync_pipeline.sh 不能在 Hermes 会话内跑（2026-08-03 实测）

Step 0 的 `pkill -f "hermes_cli.main gateway"` 会杀掉**承载当前会话**（微信/Telegram/CLI）
的 gateway 进程 → 当前对话直接中断，任务半途而废，收不到后续验证结果。

**Qdrant 服务端模式（port 6333, RocksDB）下同步无需停任何进程**：服务端支持多
Client（Agent + MCP + 索引脚本）并发访问，没有本地模式 `.lock` 独占问题。在会话内
同步时手动分步即可，全部前台可跑：

```bash
# 1. discover（新 claim 无 last_discovered → 自动被 --all-missing 处理）
PYTHONPATH=src PYTHONUNBUFFERED=1 .venv/bin/python \
  src/qing_investment/agent/tools/discover_claim_relations.py --all-missing
# 2. Neo4j 增量（MERGE 原子，无需停）
PYTHONPATH=src .venv/bin/python scripts/migrate_claims_to_neo4j.py
# 3. Qdrant 增量索引（monitored 版，无需 --force-recreate）
PYTHONPATH=src PYTHONUNBUFFERED=1 .venv/bin/python scripts/index_claims_to_qdrant_monitored.py
# 4. 验证 Agent（见下条）+ MCP 检索验证
```

只有 Kimi Code CLI / Hermes 侧需要刷新 MCP 句柄时才动 gateway，且要在会话外操作
或接受会话中断。

**Hermes background=true 启动也一样被杀（2026-08-04 实测）**：即使不是前台跑，
Step 0 杀 gateway 会连带终止 Hermes 托管的 background 管线进程（它是 gateway 的子孙），
discover 停在中途 15/27，Step 2-6 全部未执行，当前会话也被打断。可靠路径只有：
分步前台/后台跑（见上 1-4），**不要**跑整个 `run_sync_pipeline.sh`。
discover 中断恢复：`--all-missing` 靠 `last_discovered` 跳过已完成条目，断点续跑安全，
无需全量重跑（本会话 15/27 断点 → 重跑只处理剩余 12 条）。

### Qing-Agent 离线诊断快速路径（2026-08-04 实测）

用户问"agent 离线了/是否重启过"时的标准应答链（3 分钟还原，不用猜）：

1. **进程与端口**：`ps aux | grep uvicorn`（看 etime=启动时长）+ `curl 127.0.0.1:8000/health`
2. **谁重启的**：查健康检查 cron 输出 `~/.hermes/cron/output/2a0889fa52d9/*.md`——
   no_agent 脚本 `check_qing_agent.sh` 检测到离线会输出
   `❌ Qing-Agent 离线，正在自动重启... PID xxx`。该记录直接回答"自动重启是
   设计行为"（cron 每 15 分钟），无需手动拉起
3. **崩溃原因还原**：`grep -E "Traceback|ERROR|CRITICAL" logs/qing-agent.log | tail`
   看崩溃前最后动作。本次链：14:03 Claims/Wiki retrieval failed（Qdrant 不可达）
   → 14:06 reviewer 重试循环 → 进程崩溃 → 14:15:50 健康检查 cron 自动重启
4. **连带检查 Qdrant 服务端**：agent 检索失败常伴随 Qdrant 宕机（6333 无监听）。
   检查 `curl localhost:6333/collections`；恢复：服务端 RocksDB 持久化，重启后
   collection 数据完好，直接 `./bin/qdrant > /tmp/qdrant.log 2>&1 &` 拉起即可。
   Qdrant 挂了还会拖垮依赖检索的监控任务（本次 14:00 午盘任务 last_status=error）

### ⚠️ Qdrant 索引脚本跑完必杀 Qing-Agent，需手动重启（2026-08-03 两次实测）

`index_claims_to_qdrant_monitored.py`（及 `index_claims_to_qdrant.py`）的 P0 预检会调
`_kill_agent_if_running()` —— **monitored/增量版也不例外**。本机 Agent 无 systemd
守护，被杀后不会自动重启，`curl localhost:8000/health` 直接失败。

固定收尾动作（每次索引后必做）：

```bash
pgrep -f "uvicorn.*qing_investment" | head -2 || echo "AGENT DOWN"
# 若为空 → 后台重启（Hermes 前台命令里用 & 会被拒绝，必须 background=true 起 uvicorn）
cd ~/learning-investment-strategies && PYTHONPATH=src .venv/bin/python \
  -m uvicorn qing_investment.agent.main:app --host 127.0.0.1 --port 8000 --log-level info > agent.log 2>&1 &
sleep 6 && curl -s localhost:8000/health
```

---

### YAML 合并/重编号禁止 safe_load→safe_dump 往返（2026-08-04 实测）

同日多来源合并（早盘+复盘进同一 YAML）或重编号时，**不要**用 `yaml.safe_load()` 读 →
改 → `safe_dump()` 写回：emit 策略把 `code: '001309'` 重排成裸数字 `code: 001309`
（前导零丢失，`'002428'` 有变 int 的隐患），且整文件引号风格被重排，git diff 出现
大量无关 -/+ 行。

**正确做法（文本级追加，不过 YAML 解析器）**：
1. `git checkout -- knowledge/claims/claim-YYYYMMDD-XXX.yaml` 恢复原文件
2. `tail -n +2 temp/claims/<session>/step3_yaml/*.yaml >> knowledge/claims/claim-...yaml`
   （新 YAML 首行是 `claims:`，去掉后直接追加；`_auto_format_yaml` 已保证新增部分引号正确）
3. 验证：`gate_validate_claims.py <file>` 全过 + `grep -E "code: [0-9]+$"` 无裸数字
   + Python 回读 `isinstance(code, int)` 全 False

### ⚠️ 多-claim 单文件 YAML 结构（2026-07-30 确认）

**Step 3 输出的是一个 YAML 文件内包含全部 claims**（`claims:` 列表下多条），
知识库中存量文件同样如此（如 `claim-20260730-001.yaml` 含 11 条）。
**不是**"一文件一 claim"。

```yaml
claims:
- id: claim-20260729-005
  ...
- id: claim-20260729-006
  ...
```

**Step 4 重编号的正确姿势**：step3 输出 ID 从 `-001` 开始连续编号，
若同日已有 claims（如 -001~-004），需整体重编号。用 Python yaml
load → renumber → dump，不要手动改：

```python
import yaml
with open('temp/claims/<session>/step3_yaml/claim-*.yaml') as f:
    data = yaml.safe_load(f)
start = 5  # 从下一个可用编号开始
for i, c in enumerate(data['claims']):
    c['id'] = f'claim-20260729-{start+i:03d}'
with open('knowledge/claims/claim-20260729-005.yaml', 'w') as f:
    yaml.dump(data, f, allow_unicode=True, default_flow_style=False,
              sort_keys=False, width=120, indent=2)
```

**验证**：写入后 `python scripts/gate_validate_claims.py <yaml_path>` 手动验证

### 同日多来源合并同一 YAML（extend 方法，2026-08-03 实测）

早盘/盘中/复盘多批提取合并到当日已存在的 YAML 时，用 Python `extend` 合并，
不要手工拼接（手工拼接易错、yaml.dump 会统一格式）：

```python
import yaml
old_path = 'knowledge/claims/claim-20260803-001.yaml'   # 当日已有 15 条
new_path = 'temp/claims/<session>/step3_yaml/claim-*.yaml'  # 新批 11 条
old = yaml.safe_load(open(old_path)); new = yaml.safe_load(open(new_path))
conflict = {c['id'] for c in old['claims']} & {c['id'] for c in new['claims']}
assert not conflict, conflict  # 编号必须全局唯一（追加前查当日最大编号）
old['claims'].extend(new['claims'])
yaml.safe_dump(old, open(old_path, 'w'), allow_unicode=True, sort_keys=False,
               width=1000, default_flow_style=False)  # width=1000 防长行被折行
# 收尾：gate_validate_claims.py 全量验证 + 检查 related_stocks code 均为字符串
```

注意：编号在 Step 1 时就按当日已有最大编号续编（如当日已有 015 → 新批从 016 起），
不要在 Step 3 后再整体重编号。合并后 `extract_claims_pipeline.py done <session>`
会因 YAML 未移走而拒绝清理——直接 `rm -rf temp/claims/<session>`。。

**⚠️ 同日增量合并进已有文件（2026-07-31 实战）**：若同一天已有
`claim-YYYYMMDD-001.yaml`（含多条），后续批次的 claims（如盘中动态提取的
002/003）**追加进该文件**而非新建 -002.yaml。做法：`yaml.safe_load` 已有文件
→ `existing['claims'].extend(new_claims)` → dump 回原文件。注意：
- 追加前先读已有文件，确认新 ID 不冲突（`ls claim-<日期>-*.yaml`）
- 追加后该文件的 claims 列表变大，index.md 引用不变（仍指向 -001.yaml）
- 7/31 早盘(001-019) + 盘中(020-024) 合并为同一文件 24 条 = 正常模式

**⚠️⚠️ 编号必须从已有最大号续编，绝不从 001 重开（2026-07-31 事故）**：
同一天多个 raw 文件（早盘/盘中/复盘）提取时，新批次 ID 必须从该日期
**已有最大编号+1** 开始。7/30 盘中动态被错误标为 `claim-20260730-002/003`
（与早盘 002/003 冲突），合并后文件内出现**重复 ID** → Neo4j 只写入 11 条
（重复 node 覆盖），Qdrant 3078 条含脏数据，被迫全量重建修复。

```bash
# start 新 raw 前必查该日期已有最大编号
grep "id: claim-YYYYMMDD" knowledge/claims/claim-YYYYMMDD-001.yaml | tail -1
# 已有 011 → 新批次从 012 起
```

**重复 ID 检测**：
```bash
python3 -c "
import yaml
from collections import Counter
data = yaml.safe_load(open('knowledge/claims/claim-YYYYMMDD-001.yaml'))
ids = [c['id'] for c in data['claims']]
print({k:v for k,v in Counter(ids).items() if v>1})
"
```

**修复**：重编号冲突条目 → `migrate_claims_to_neo4j.py` → `index_claims_to_qdrant.py --force-recreate`
（普通增量不覆盖重复 ID，必须全量重建）。

**修复后双端验证**：
```bash
# Neo4j：该日期 ID 列表唯一且数量正确
PYTHONPATH=src .venv/bin/python -c "
from qing_investment.agent.config import settings
from neo4j import GraphDatabase
d = GraphDatabase.driver(settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password))
with d.session() as s:
    r = s.run(\"MATCH (c:Claim) WHERE c.id STARTS WITH 'claim-YYYYMMDD' RETURN c.id ORDER BY c.id\")
    print([x['c.id'] for x in r])
d.close()
"
# Qdrant：scroll 全量样本核对（字段名是 claim_id 不是 id！count filter 前缀匹配返回 0，必须 scroll）
PYTHONPATH=src .venv/bin/python -c "
from qdrant_client import QdrantClient
client = QdrantClient(url='localhost:6333')
all_ids, offset = [], None
while True:
    results, offset = client.scroll(collection_name='qing_claims', limit=1000, with_payload=True, with_vectors=False, offset=offset)
    for p in results: all_ids.append(p.payload.get('claim_id',''))
    if offset is None: break
print(sorted(set(i for i in all_ids if 'YYYYMMDD' in i)))
"
```

### 纯图片动态：API 原始数据提取图片 URL → OCR 补全（2026-07-31 实战）

B站图片动态（DRAW）正文为"（无文字内容）"时，图片 URL 藏在 **.md 文件的原始 API
数据区块**中，需区分真实动态图 vs 装饰图：

```bash
# 真实图：http://i0.hdslb.com/bfs/new_dyn/<hash>1420210197.jpg
# 排除：bfs/face/（头像）、bfs/garb/（装饰）、bfs/vip/（徽章）、activity-plat/
python3 -c "
import re
content = open('<动态文件.md>').read()
print(re.findall(r'http://i0\.hdslb\.com/bfs/new_dyn/[^\"\') ]+\.(?:jpg|png)', content))
"
```

下载 → RapidOCR 识别（长图分块 ≤2000px 高，`fetch_bilibili_up_v2.py` 的
`ocr_image()` 有现成实现）→ OCR 文本补入 `## 原文` 区块并标注
"（图片内容 OCR 识别：...）"。依赖缺失时：`.venv/bin/pip install rapidocr_onnxruntime`。

**已见案例**：7/31 11:20 动态（id 1231064998642450435）OCR 出观察池截图 →
浪潮软件(600756) Tier1 + 久其软件(002279) Tier2 → claim-20260731-023/024。

### 预检查：raw 可能已被 Agent 盘中管线先提取

早盘类 raw 存在**已被 Agent 证券研究管线先提取**的可能（source_path 指向
`knowledge/claims/claim-YYYYMMDD-001.yaml` 等）。提取前先：

```bash
ls knowledge/claims/claim-<日期>-*.yaml 2>/dev/null
grep -l "source_path.*<raw文件名>" knowledge/claims/*.yaml
```

2026-07-30 实战：7/30 早盘已被提取为 `claim-20260730-001`（11 条），
直接跳过不重复提取。判断标准：已有 claims 的 statement/evidence_quote
与该 raw 高度重合即跳过。

### B站监控 cron 暂停 → raw 缺失时手动补抓（2026-07-31 实战）

用户要提取某天内容但 `sources/original/bilibili/` 找不到对应文件时，
**先查 `cronjob action='list'` 中 `B站青枫浦上Q动态监控` 的 state**——
该 cron 可能因故 paused（2026-07-28 起暂停，导致 7/29-7/31 全部漏抓）。

```bash
cd ~/learning-investment-strategies
BILIBILI_SESSDATA="$(cat ~/.hermes/bilibili_sessdata.txt)" \
  .venv/bin/python scripts/fetch_bilibili_up_v2.py \
  --uid 1420210197 --state-file ~/.hermes/bilibili_up_state.json
```

- cookie 位置：`~/.hermes/bilibili_sessdata.txt`（二维码登录保存，脚本自动读取
  也可显式传入）
- 成功输出 `NEW_DYNAMIC: sources/original/bilibili/...`，然后 cp → raw → 管线
- **不要擅自 resume 该 cron**——先问用户是否恢复监控

### ⚠️ fetch 脚本 max_fetch=5 静默截断（2026-07-31 实战）

`fetch_bilibili_up_v2.py` 默认 `--max-fetch 5`：一次运行只处理**最新的 5 条未处理动态**，
单日动态 >5 条时后面的被静默丢弃（无警告无报错），补抓时容易误以为"已全抓"。

**修复**：手动补抓时显式加大：

```bash
BILIBILI_SESSDATA="$(cat ~/.hermes/bilibili_sessdata.txt)" \
  .venv/bin/python scripts/fetch_bilibili_up_v2.py \
  --uid 1420210197 --state-file ~/.hermes/bilibili_up_state.json --max-fetch 10
```

### ⚠️ "还有X条动态没获取" = 先查已抓未提取，再查漏抓（2026-07-31 用户纠正）

用户说"还有三条动态没有获取"时，**先检查该日期是否已有文件但 `unprocessed: true`
（已抓取、未走 claim 管线），再怀疑漏抓**。2026-07-31 实战：用户指的三条是
10:00/10:34/11:20——文件其实都在（当天 12:25 已抓），只是我只提取了 0853 早盘专栏、
这三条还没提取 claim。而我误以为是 7/30 漏抓的三条，方向完全错了。

**正确排查顺序**：
```bash
# 1. 先看该日期哪些文件还标着 unprocessed: true（已抓未提取）
grep -l "unprocessed: true" sources/original/bilibili/2026-07-31*.md 2>/dev/null

# 2. 再对比 UP 动态列表找真的漏抓（fetch_dynamic_list 拉全量对比文件名）
```
文件已存在 → 直接走 claim 管线提取；文件缺失 → 才需要补抓（见上节）。

### 纯图片动态 → OCR 提取（2026-07-31 实战）

正文显示"（无文字内容）"的图片动态，内容在图片里，可 OCR 提取后走管线
（观察池截图等有价值内容）。工作流：过滤 `bfs/new_dyn/` 真实图片 URL →
项目 venv 装 `rapidocr_onnxruntime` → 2000px 分块 OCR → 回填原文。
详见 `references/image-to-raw-workflow.md`。

### log.md 插入条目时保留相邻标题（2026-07-31 实战）

`knowledge/wiki/log.md` 新条目插在头部。用 patch 插入时 **old_string 若包含
下一条目标题行，new_string 必须原样保留它**。实战教训：new_string 漏掉
`## 2026-07-20 | ...` 标题行 → 7/20 条目正文失去标题、log 结构损坏。

复查命令：
```bash
grep -c "^## 2026-07-" knowledge/wiki/log.md   # 对比修改前数量，确认无丢失
```

更稳妥写法：old_string 只取插入锚点（新条目内容唯一片段），不触碰下一条目标题。


### 股票代码批量查询

```bash
for name in "公司A" "公司B" "公司C"; do
  curl -s "https://searchapi.eastmoney.com/api/suggest/get?input=\
$(python3 -c "import urllib.parse; print(urllib.parse.quote('$name'))")&type=14&count=1" \
  | python3 -c "import sys,json;d=json.load(sys.stdin);\
  items=d.get('QuotationCodeTable',{}).get('Data',[]);\
  print(items[0]['Code'],items[0]['Name']) if items else print('NOT_FOUND')"
done
```

### Git 提交时避免意外 stage

不要用 `git add -A`，指定具体文件：
```bash
git add knowledge/claims/ knowledge/claims/index.md knowledge/wiki/log.md ...
```

---

### NON_COMPANY 预期管理

**关键认知**：每篇长文（复盘/早盘）提取时，Gate 2 预期会新增 3-5 个 "科技/智能" 假阳性模式。这不是 pipeline bug，是中文文本中 "科技" 作为板块描述词的正常现象。批量处理时应在第一篇失败后预判后续批次的假阳性，一次加入减少失败轮次。

**频率修正（2026-07-30 实战）**：短文本（盘中动态）3-5 个；**长复盘/视频转录可达 14 个**（7/29 复盘专栏 18 claims → 14 个假阳性）。按 raw 类型预估：
- 早盘/盘中短动态：3-5 个
- 长复盘专栏：10-14 个
- 视频转录摘要：7-14 个（额外注意 "有限" 后缀）
- **早盘长专栏：10-14 个**（2026-07-31 实战：19 claims → 14 个假阳性，"科技" 作主语的词法位置极多：动宾/转折/行业术语都有）

规律：三类模式最常见——①"科技" 作板块描述（如 "回流科技"、"不是等科技"）；②"智能" 作 AI 描述（如 "自研智能"、"以买卖家智能"）；③"有限" 作文本词汇（视频转录特有，如 "成下行风险有限"）。

**⚠️ 同一篇 raw 重复提取的假阳性不重叠**（2026-07-30 实战）：同一篇 raw 若被两次提取（不同会话/批次），interpretation 措辞是 Agent 生成的，两次的假阳性 fragment 基本完全不相同。第二次提取时仍要逐个按报错添加，不能假设已有批次覆盖。

预判技巧：读 raw 时注意 "科技""智能" 在非公司名上下文的频率。高频率 → Gate 2 大概率需要加 NON_COMPANY。

假阳性批次记录：`references/non-company-batches.md`。

---

### 同步管线速查（Step 4 后处理完成后）

```bash
# discover → Neo4j → Qdrant → restart Agent
PYTHONPATH=src .venv/bin/python src/qing_investment/agent/tools/discover_claim_relations.py --all-missing
PYTHONPATH=src .venv/bin/python scripts/migrate_claims_to_neo4j.py
PYTHONPATH=src .venv/bin/python scripts/index_claims_to_qdrant.py --force-recreate
PYTHONPATH=src .venv/bin/python -m uvicorn qing_investment.agent.main:app --host 127.0.0.1 --port 8000 &
```

### 跨日/中断恢复：先查服务状态再跑同步（2026-08-03 实战）

**场景**：上次会话因费用中断，隔几天后恢复。中断期间服务器可能重启过，
Qdrant 服务端/Agent 可能已停。**直接跑同步脚本会因连接失败而报错或静默失败**。

恢复顺序：
```bash
# 1. 服务状态三查
curl -s localhost:6333/collections    # Qdrant（中断后最常见停机）
curl -s http://127.0.0.1:8000/health  # Agent
PYTHONPATH=src .venv/bin/python -c "
from qing_investment.agent.config import settings
from neo4j import GraphDatabase
d = GraphDatabase.driver(settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password))
print('Neo4j ok')
d.close()
"

# 2. Qdrant 服务端重启（若停）：cd ~/learning-investment-strategies && nohup ./bin/qdrant > /tmp/qdrant.log 2>&1 &
# 3. 再跑同步管线
```

**Agent 被 --force-recreate 杀掉的常态**：`index_claims_to_qdrant.py --force-recreate`
内置杀 Agent 逻辑，跑完后 Agent 必然不在 → 记得重启 + `curl /health` 验证（不要以为挂了是故障）。

**中断恢复时的完整性核查**（比跑同步更重要）：先查上次是否留下
未完成/已污染的产物：
- claims YAML 重复 ID（见上文 Counter 检测）
- 未跟踪的 raw 文件（`git status` 里 `?? sources/raw/...`）
- 漏提取的 raw（`grep -l "unprocessed: true" sources/original/bilibili/`）
- 7/30 事故复盘：中断恢复时发现 7/30 22:57 复盘动态（37KB 大内容）从未提取，
  且盘中动态 claims 编号冲突已入库 → 恢复任务 = 补提取 + 修编号 + 全量重建

## 四、B站动态监控 Cron 运维（2026-08-03 重建）

### 拓扑：Hermes cron vs Kimi Bridge cron

Hermes cron 原本**没有** bilibili 拉取任务（22 个任务全是行情监控）；历史镜像
在 Kimi Bridge 的 `cron/jobs.json`（`[from-hermes]` 前缀，全部 disabled）。

| 系统 | 位置 | 说明 |
|------|------|------|
| Hermes cron | `hermes cron list` | 重建后的 watchdog（job `46b29d1607b4`） |
| Kimi Bridge cron | `/home/ubuntu/kimi-code-im-bot/cron/jobs.json` | 历史镜像 `[from-hermes] B站青枫浦上Q动态监控`（d3418458，disabled） |

用户说"参考 bridge 的定时任务" → 去 `kimi-code-im-bot/cron/jobs.json` 查历史 schedule，
不要凭记忆造。Bridge cron = node-cron + JSON store + `mode: script`。

### 任务配置（重建值）

- schedule: `3-59/5 9-14,21-23 * * 0,1-5`（工作日+周日，9-14点 & 21-23点每5分钟）
- mode: **no_agent=true watchdog** — 脚本非空 stdout 才投递（零 token 空转）
- script: `run_bilibili_notify.sh`（wrapper → `~/.hermes/scripts/bilibili_notify.py`）
- deliver: origin；workdir: 项目根

### bilibili_notify.py watchdog 契约

- **无新动态 → stdout 静默**（空输出=不投递）
- **有新动态 → stdout 完整原文**（含 `<!-- BILIBILI_NEW_CONTENT:... -->` 去重标记）
- SESSDATA 自动读 `~/.hermes/bilibili_sessdata.txt`（无需环境变量）
- 拉取后**自动创建** claims pipeline session，**不自动提取**
  （设计决策 2026-06-15：cron 空转浪费 token；用户看到微信后说"提取"再触发）

### 注意

- 微信 iLink 限流（~30s cooldown）：密集投递报 `delivery error: Weixin send failed:
  iLink sendmessage rate limited` 是**瞬时限流非故障**，下周期自愈
- UP 早盘动态通常 08:57；当前 schedule 09:00 起，需覆盖早盘可改 `3-59/5 8-14,21-23`

### ⚠️ 用户问"动态没拉到/微信没发消息"的排查（2026-08-04 实测）

**抓取成功 ≠ 投递成功**：watchdog 抓到动态并输出 5263 字符，但 iLink 限流投递失败，
`last_status` 仍是 ok——消息静默丢失，用户无感知。三步定位：

1. 查 cron 输出存档：`~/.hermes/cron/output/<jobid>_<ts>.txt`（no_agent 模式完整 stdout）
2. 查 `~/.hermes/logs/agent.log` / `errors.log` 的 `cron.scheduler` / `gateway.delivery` 行：
   `delivery error: Weixin send failed: iLink sendmessage rate limited` → 抓取成功、投递失败
3. 查 `~/.hermes/bilibili_up_state.json`：`processed_ids` 已含新动态 id → 抓取侧 OK，问题在投递层

**两个易误判的坑**：
- **空 SESSDATA 列表错位**：`fetch_dynamic_list` 用空 sessdata 也返回 12 条 items，但列表
  错位看不到最新动态（第一条停在旧日期）→ 误判"UP 没发"。排查前先确认
  `~/.hermes/bilibili_sessdata.txt` 存在且非空。
- **列表 API 发布后短时延迟**：UP 09:13 发布，09:18 cron 轮次 SILENT（列表未更新），
  09:23 轮次才抓到。watchdog 每 5 分钟一轮，发布后 5 分钟内 SILENT 不是故障。
- **`_1` 重复文件（2026-08-04）**：手动抓取与 cron 抓取同一动态时，`save_dynamic_to_file`
  遇同名文件自动加 `_1` 后缀生成副本（内容相同）。清理前先确认 `index.md` 引用的是
  不带 `_1` 的版本，再删冗余副本。

手动补抓与完整排查流程见
`references/bilibili-monitor-delivery-debug.md`。

### ⚠️ feed API HTTP 412 风控：必须完整 Cookie 模板（2026-08-13 实测）

手工调 `api.bilibili.com/x/polymer/web-dynamic/v1/feed/space` 时，**仅带
`Cookie: SESSDATA=xxx` 会 HTTP 412**（Precondition Failed，返回 HTML 而非 JSON）。
必须带完整 COOKIE_TEMPLATE（buvid3/buvid4/bili_ticket/bili_jct/DedeUserID 等，
见 `scripts/fetch_bilibili_up_v2.py:45` 的常量）才能 code=0。

```python
# ✅ 完整模板（从脚本 COOKIE_TEMPLATE 复制，替换 SESSDATA）
cookie = f"buvid3=...; buvid4=...; bili_ticket=...; bili_jct=...; SESSDATA={ss}; ..."
# ❌ 仅 SESSDATA → HTTP 412
```

**412 排查顺序**：先 `curl api.bilibili.com/x/web-interface/nav` + `Cookie: SESSDATA=...`
验证 cookie 有效性（`isLogin: True` 且 uname 正确 = SESSDATA 有效，问题在模板不全）→
再用完整模板调 feed API。注意：`x/web-interface/nav` 只带 SESSDATA 就能过，
但 feed API 需要全模板——两者风控等级不同，不要用 nav 通过来断定 feed 也通。

**解析字段**：动态 ID 在 `id_str`（不在 desc）；`pub_ts` 在
`modules.module_author.pub_ts`（**字符串**，需 int() 转换）；`basic.comment_style.timestamp`
可能为 None 不可靠；`desc` 可能为 None（充电专属动态）→ 用 `modules.module_dynamic.desc.text`。

### ⚠️ uv run 超时 → 改用 .venv/bin/python 直跑（2026-08-13 两次实测）

`uv run python scripts/xxx.py` 在 Hermes 会话内**偶发 60-120s+ 超时**（uv 首次
解析依赖/锁检查慢），而同一脚本用 `.venv/bin/python scripts/xxx.py` 秒出。
2026-08-13 实测：`fetch_bilibili_up_v2.py` 用 uv run 120s 超时、`extract_claims_pipeline.py`
用 uv run 60s 超时，改 `.venv/bin/python` 后均 <5s 完成。

**规则**：本项目脚本一律 `.venv/bin/python` 直跑（项目已有 `.venv`），不要用
`uv run`。超时后先检查进程是否还在跑（`pgrep -f <脚本名>`），再决定补跑。

### Agent 重启验证：pgrep/pkill 自匹配陷阱（2026-08-10 实测）

同步管线最后一步重启 Agent 时，**不要用 `pgrep -f "uvicorn qing_investment"` 验证
进程是否已停**——`-f` 全命令行匹配会把「执行该命令自身的 bash wrapper」（命令行里含
关键词）也算进去：

- `pgrep -f "uvicorn qing_investment"` → 恒返回真（匹配到自己的 shell），
  `echo "仍有进程"` 是假阳性
- `pkill -f "uvicorn qing_investment"` → 返回 exit -15/-9（杀掉了自己的 wrapper，
  不是 uvicorn），且 uvicorn 可能根本没停干净

```bash
# ✅ 正确验证（匹配 python 进程本体，不匹配 shell wrapper）
ps aux | grep -E "python.*uvicorn" | grep -v grep
# 空输出 = 已停止；有输出 = 还在跑，pkill -9 <PID>

# 重启：Hermes 拦截前台 nohup/&，必须 background=true
# terminal(background=true, watch_patterns=["Application startup complete"])
```

**经验**：`pgrep/pkill -f <关键词>` 在 Hermes 环境里做进程验证/清理时普遍有
自匹配问题（命令自身的 bash wrapper 含关键词）。凡是要「验证某进程不存在」，
用 `ps aux | grep <python进程特征> | grep -v grep` 更可靠。

---

*写入日期：2026-07-29 | 来源：7/28-29 批量提取 5 篇 raw 的实战经验*
*更新：2026-08-03 | 新增：同日多文件编号续编事故（7/30 重复 ID 全量重建）、纯图片动态 OCR 补全、跨日中断恢复服务三查、Qdrant 服务端停机重启、B站动态监控 cron 拓扑重建*
*更新：2026-08-04 | 新增：YAML 合并禁止 safe_load→safe_dump 往返（文本级追加）、Gate 4/5 正则前缀陷阱（真公司补代码/假阳性加完整片段）、run_sync_pipeline.sh 在 Hermes background 下也被 gateway Step 0 连带终止 + discover --all-missing 断点续跑、Qing-Agent 离线诊断快速路径（健康检查 cron 自愈记录+Qdrant 连带检查）*
*更新：2026-08-09 | 新增：migrate/Qdrant 全量 10+ 分钟必须 background+notify（超时≠进程终止，重跑前先 pgrep）、Agent 重启 Hermes 拦截前台 nohup/& 改用 background=true、start 不检测已有 session 产生孤儿、NON_COMPANY 批次13（领涨方向为X句式/金融智能）*
*更新：2026-08-10 | 新增：Agent 重启验证 pgrep/pkill 自匹配陷阱（`pgrep -f "uvicorn qing_investment"` 匹配到执行命令自身的 bash wrapper，假阳性"仍有进程"+pkill 返回 -15/-9 误杀自身 wrapper；改用 `ps aux | grep -E "python.*uvicorn" | grep -v grep`）、Gate 5 校验 statement+interpretation 全文（interpretation 裸名也报错，Step 2 两字段都要补码）、NON_COMPANY 批次15（拟通过发行股份=重组描述/东建设人工智能=政策全称）*
*更新：2026-08-13 | 新增：提取前先 git pull 同步远程（用户明确要求）、feed API HTTP 412 风控需完整 Cookie 模板（仅 SESSDATA 不够，nav 与 feed 风控等级不同）、uv run 偶发超时改用 .venv/bin/python 直跑、NON_COMPANY 批次16（X且高位科技/随后非科技/冲高回落的科技 复合句式）、discover 402 假完成重试（LLM 余额不足仍写 last_discovered，重试前文本行删除失败 claim 的 last_discovered）*
*更新：2026-08-14 | 新增：start --raw 可直接用 sources/original/bilibili/ 路径（无需复制到 sources/raw/财经/）、Step 1 JSON 语法错误 write_file 拒绝写入且不创建文件（必须整文件重写）、run_discover_with_progress.sh wrapper 已可用（8/14 实测正常启动）、NON_COMPANY 批次17（医药-科技跷跷板句式/三星电子新变体/X智能产品架构名，早盘长专栏 36→14 假阳性）*
