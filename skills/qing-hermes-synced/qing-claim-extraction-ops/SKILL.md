---
name: qing-claim-extraction-ops
description: |
  Claim 提取管线的运行级操作手册（执行层补充 skill，与只读的
  qing-learning-claim / qing-claim-extraction-debug 互补）。覆盖：
  提取前 git pull、uv run 超时改用 .venv/bin/python、股票代码必须
  API 查证、B站动态抓取 cookie 细节、会话复用/清理、同步管线分步后台跑。
  触发词：提取 claim 前、pipeline 超时、uv run、股票代码查证、抓取动态超时。
---

# qing-claim-extraction-ops

## 定位

`qing-learning-claim`（项目 repo，curator 只读）定义了 C2 提取管线本体；
`qing-claim-extraction-debug`（~/.hermes/skills/qing/，只读）定义 debug 模式。
本 skill 沉淀**执行层**的操作经验：每次跑提取时都会踩的运行细节。
若本 skill 与上述两个 skill 内容重复，以本 skill 的运行级结论为准（它更新）。

## 1. 提取前必做：git pull 远程分支（用户明确要求，2026-08-13）
**用户原话**："先拉去远程分支再提取"。

```bash
cd ~/learning-investment-strategies
git fetch origin && git pull origin master
```

- 远程可能有 cron 产物提交、gate_validate_claims.py 修复、新 raw 文件。
- 先检查 `git log --oneline HEAD..origin/master` 确认无冲突风险；
  本地未提交改动与远程改动文件不重叠时直接 merge。
- **拉取后再跑** `extract_claims_pipeline.py start`，避免基于过期代码/数据提取。

## 1b. 提取前必做：跨日期重复观点用语义搜索查（`ls` 同日期查不到）

`qing-learning-claim` 的预检查只查同日期文件（`ls knowledge/claims/claim-YYYYMMDD-*.yaml`），
但**方法论/纪律/框架类观点会被 UP 反复强调，跨日期重复提取是更隐蔽的坑**。

2026-08-13 写早盘动态 claim 前，用 `mcp__qdrant__search_claims` 对每条候选观点做语义检索，
确认这些已覆盖、不重复提取：
- "2.5万亿放量确认门槛" → 8/5、8/7、8/10 均有 claim
- "算力租赁国内高端算力近乎唯一来源" → 8/12-012
- "买阴不买阳 / 缺业绩承接不接飞刀" → 8/12-025
- CPI 四项数值 → 8/12-034~037（前日晚盘已提）

2026-08-16 周复盘专栏预检查新增命中（25 条里跳过 8 条重复观点）：
- "断板分性质（外力 vs 内生换龙）" → 8/7-009、8/10-031（本周只是应用该框架，不再提方法论）
- "尾盘抢筹把明天买盘提前消耗" → 8/6-024
- "散热链条技术拆解（TIM1/VC/顶盖/cage）" → 8/14-027（本周只提标的映射增量：中石科技做模块内部、鼎通/奕东做 cage 侧）
- "医药良性分化、机构低仓位+半年报催化、持续性更好" → 8/12-008、8/13-031
- "A股 AI 应用炒映射与题材、波段机会非趋势" → 8/10-045、8/11-046、8/12-010
- "交换机分支整体新高 = 反弹转反转必要条件" → 8/9-028、8/13-029（只提证伪条件增量：紫光+华勤不跟→反转说法收回）
- "中际旭创受让中石科技事件本体" → 8/14-026（只提 UP 判断增量：信息价值大于交易、散热从配套项变产能约束项）

**判别口径**：
- 定量事实/新数据点（"腾讯 Q2 资本开支 527 亿 +176%"）→ 提取（即便主题已有 claim）
- 定性判断/方法论/纪律（"唯一来源""买阴不买阳"）跨日期重复 → 跳过
- 同一数据点前一日已提 → 跳过，除非有新解读角度

**做法**：写 Step 1 前，对候选观点短语逐条 `mcp__qdrant__search_claims`（query 用观点核心词），
命中已有 claim 且语义一致即跳过。8/13 实战最终只提 18 条真正新增量（隔夜美股表现、
Coherent 反跌、半日 1.45 万亿阈值、算租映射清单、存储"点"定位、地产低价题材、百花医药严重异动、宇树上市、AI 扩散管制风险）。

## 1c. claims 覆盖核对（判断 raw 是否已提取过，2026-08-15 实测，用户纠正）

用户问「这些文件没提取过 claim？」时，**不要只信 source_path 精确匹配**，三个坑全踩过：
- claims 的 `source_path` 指向 `sources/original/bilibili/`（原始抓取目录），
  `sources/raw/财经/` 是处理副本——文件名/路径对不上会误判「未提取」
  （曾误判 244/250 个，实际 239/250 已提取，用户"不可能，我每天都提取"是对的）。
- claims 的 `source_date` 是**提取日，不是内容日**：1 月的内容在 5-7 月的 claims 里。
  按 source_date 按月统计会误判「1-4 月真空区」（实际全量分布 5月266/6月1036/7月1300/8月524，
  1-4 月内容大部分在 5-7 月的 claims 里）。
- 通用关键词法误报严重：「航天电子」「2.8万亿」「风格切换」在 claims 全文到处出现，
  命中 ≠ 该文件已提取。

**正确方法（独特词平衡法）**：合并所有 claim 的 subject+statement+evidence_quote 为
CLAIM_ALL；对每个候选文件提取**独特词**（文件名主体去 STOP 词后的 2-8 字中文词 +
内容带数字表述如 13连阳/60分钟底/2.8万亿）；任何独特词在 CLAIM_ALL ≥1 命中 = 有痕迹，
全部 0 命中 = 确定真空区。结论对方法极敏感——先抽 5-8 个文件用独特词人工核对校准再全量。
实测 1-4 月真空区 44 个 = 15 研报（外部内容，用户拍板不提取）+ 29 UP 观点（值得提取）。

## 1d. 批量写 yaml 必须安全写入（截断事故，2026-08-15）

`with open(f, "w") as fh: yaml.dump(...)` —— 若 `yaml.dump` 抛异常（如 NameError），
`open("w")` 已把文件**截断清空**（实测 reasoning-patterns.yaml 11 框架被截成 3936B/2 patterns，
git checkout 恢复）。正确模式：

```python
content = yaml.dump(yaml_data, allow_unicode=True, default_flow_style=False, sort_keys=False)
PATTERNS_FILE.write_text(content, encoding="utf-8")
```

任何批量写 yaml 的脚本（extract_reasoning_patterns.py 的 dump、临时批处理）都按此模式。

## 2. 所有 pipeline/抓取脚本用 `.venv/bin/python`，不要用 `uv run`

**症状**：`uv run python scripts/extract_claims_pipeline.py start` 卡 60s+ 超时；
`uv run python scripts/fetch_bilibili_up_v2.py` 120s 超时无输出。

**根因**：uv 首次初始化/锁解析开销大，脚本本身秒级完成。

**正确姿势**（本项目一律直跑 venv）：
```bash
.venv/bin/python scripts/extract_claims_pipeline.py start --raw "<路径>"
.venv/bin/python scripts/extract_claims_pipeline.py continue
.venv/bin/python scripts/gate_validate_claims.py <yaml路径>
.venv/bin/python scripts/build_indexes.py
```
注：项目 `python`（PATH 里）通常已指向 .venv，直接 `python scripts/...` 也等价——关键是**绝不用 uv run**。

### 2b. Gate 结果缓存坑的实操修复顺序

Gate 失败后修正 step 文件再 `continue`，若仍报**完全相同的旧错误** → 是
`gateN_result.json` 缓存（见 qing-learning-claim 已知坑点1）。实操：
1. 先本地复现校验确认已修好：动态加载 gate 模块跑 `gate5_stock_codes(claim)` 等，
   或改完直接 `python scripts/gate_validate_claims.py <step文件>` 看是否通过
2. 确认修好后 **删缓存再 continue**：`rm temp/claims/<session>/gateN_result.json`
3. 不要反复改文件重试 continue——pipeline 读的是缓存不是你的新文件

## 3. 股票代码必须东财 API 查证，禁止凭记忆填

2026-08-13 曾把**百花医药误写 600466**（实际 **600721**），靠 API 查证才发现。

```bash
curl -s "https://searchapi.eastmoney.com/api/suggest/get?input=<公司名URL编码>&type=14&count=1"
# → QuotationCodeTable.Data[0].Code
```

- **中文公司名必须 URL 编码**（2026-08-18 实测）：curl 直接拼中文 `input=长电科技` 返回空 JSON（`QuotationCodeTable` 缺失），shell 循环 50+ 个公司名全空。正确做法：用 Python `urllib.parse.quote()` 编码后请求，或直接 Python 脚本循环批量查（一次跑完，返回 `N/A` 属正常——未上市公司如苏州天迈查不到，不要据此判 API 故障）。
- 连板梯队/个股 claim 的公司名逐个查，不要批量脑补。
- **次新股带字母前缀（2026-08-19 实测）**：东财 suggest 返回的 `Name` 可能是
  `N宇树-W`（688836，上市首日）、`C频准`（688826，上市次日起 5 日内）等——
  与原文"宇树科技""频准激光"对不上。**用返回的 Code 判断标的，Name 以原文为准**：
  匹配逻辑 `if x.get("Name") == n` 会漏，应加 `startswith` 或直接取 `Data[0]` 再核对 code。
  非 A 股标的（铠侠 285A 日股、迈威尔美股）不进 related_stocks，公司名进 NON_COMPANY。
- 北交所标的（如创达新材 920012，京A）role 标注"北交所不可交易"（与创业板/科创板同类）。
- 查完核对市场归属：6 开头=沪主板(sh6)，0/3 开头=深（0 主板 sz0，3 创业板），
  688=科创板。非主板在 role 标注"不可交易"。
- 修正错误后若 Gate2 已跑过，必须 `rm temp/claims/<session>/gate2_result.json`
  再 `continue`（缓存不比较时间戳）。

## 4. B站动态抓取细节（fetch_bilibili_up_v2.py）

- **用户明确要求（2026-08-24）：拉取 UP 内容直接跑脚本，不要为此创建一次性 cron 任务**。
  即使内容可能未发布，也优先手动/按需重跑脚本，而非定时任务兜底。

- **SESSDATA 在 `~/.hermes/bilibili_sessdata.txt`，不在 .env**（.env 里 BILIBILI_SESSDATA 是空的）。
- 完整 cookie 模板（buvid3/b_nut/bili_ticket 等）才能过 feed API；
  只用 SESSDATA 裸 cookie 会 `HTTP 412 Precondition Failed`（风控）。
- `--check-only` 静默退出（无输出）≠ 成功，可能是 API 返回 items 空/风控；
  手动调 feed API 打印 `code/items/id_str/pub_ts` 核对最新动态 ID 与时间。
- 无新动态时脚本静默（空输出），属正常。**但注意区分**：uv 环境重建后首跑会卡在
  依赖下载（akshare/curl-cffi 等，输出被 tail 吞掉后看起来像"静默=无新动态"），
  实际 API 调用根本没执行。先用 `--check-only` 验证：输出 `CHECK: 发现 N 条新动态`
  才是真实结果；无输出时先重跑一次（依赖已缓存）再下结论。2026-08-24 实战：
  首跑静默误判"周复盘未发布"，用户指出有新动态后重跑即拉到 2 条。
- **视频+图片成对发布时，正文在图片动态里**：周复盘视频动态的 `## 原文` 只有标题
  +"一键三连"，完整复盘正文在同时段发布的图片动态 desc 中（2026-08-24：
  视频 00:00 仅标题，00:41 图片动态含全文）。提取时选正文长的那份 raw，
  视频动态只作来源记录。
- 图片动态若 `pics_count: 0` 且正文完整，直接以正文提取，无需截图/OCR。

### 4b. 充电专属**专栏**正文拉取：article API 返回空，必须 fetch_article_content（2026-08-19 实测）

**症状**：8/19 早盘专栏（dynamic `1238079642295861257`），两种常规路径都拿不到正文：
- `x/polymer/web-dynamic/v1/detail` → `major.article` 只有 `{covers, desc:"请将App客户端升级至最新版本后观看", id, title}`，**无正文**
- `x/article/view?id=<article_id>` → 同样返回"请将App客户端升级至最新版本后观看"

**正确路径**：`fetch_bilibili_up_v2.py` 的 `fetch_article_content(article_id, sessdata)`——抓 `https://www.bilibili.com/read/cv{article_id}` 页面 HTML，解析 `window.__INITIAL_STATE__` 里的 `detail.modules[].module_content.paragraphs[].text.nodes[].word.words`。这是**充电专属专栏的唯一正文途径**（文章 API 对充电文返回占位文案）。

**流程**（动态 detail → 文章 id → 正文 → 落盘 raw）：
```python
# 1. detail 拿文章 id（major.article.id，注意是纯数字，不是 cv 号）
# 2. 拉正文
from fetch_bilibili_up_v2 import fetch_article_content
content = fetch_article_content('52467573', sessdata)   # → 5332 字全文
# 3. 组装 frontmatter（source/dynamic_id/pub_time/is_only_fans: true）+ `## 原文` 落盘
#    sources/original/bilibili/2026-08-19-0901-专栏-<标题前几字>.md
```

**落盘命名惯例**：`YYYY-MM-DD-HHMM-专栏-<原文第一行截断>.md`（8/18 复盘、8/19 早盘均此格式）。**先落盘 raw 再 start 管线**（raw 是提取输入）。

## 5. 会话复用与清理

- 抓取脚本可能自动创建过 `temp/claims/<session>`（state: init，attempts_step1: 0）
  = 漏提。确认 `session.json` 的 raw_path 与目标一致：可复用，或新建会话（start）。
- 提取完成后 `done <session>` 若报"YAML 尚未移走"（因为用 cp 而非 mv），
  **直接 `rm -rf temp/claims/<session>`** 是正确做法。
- 编号冲突检查：`ls knowledge/claims/claim-YYYYMMDD-*.yaml` + `grep "^  id:"`，
  新 id 从已有最大编号 +1 起（同一天多份 raw 共用一个文件、多条 claim）。
- **write_file 写 step1_raw.json 会先做 JSON 语法校验**：缺闭合引号等语法错误时
  直接拒绝写入（"Refusing to write ... fails .json syntax validation"），报错带
  行列号（如 `line 367, column 42`）。此时文件**未创建**，需修复后整份重写，
  不要用 patch 去补（文件不存在 patch 会失败）。36 条大 JSON 建议先写小文件
  验证结构或用 execute_code 的 json.dump 生成，避免整份重写。

## 6. 同步管线：分步后台跑，勿跑整脚本

```bash
# 1. discover（新路径，后台；14条约3-5分钟）
PYTHONPATH=src .venv/bin/python src/qing_investment/agent/tools/discover_claim_relations.py --all-missing > /tmp/discover_xxx.log 2>&1 &
#    或 `bash scripts/run_discover_with_progress.sh`（同功能+进度条 [N/26]，日志更直观，2026-08-18 实测可用）
#    ⚠️ 该 wrapper 脚本不加载 .env → OPENROUTER_API_KEY 缺失报 ValueError（2026-08-24）。
#    两种修法：① export OPENROUTER_API_KEY=$(grep "^OPENROUTER_API_KEY=" .env | cut -d= -f2-) 后直跑
#    discover_claim_relations.py；② 或先 export 再跑 wrapper。ONNX embedding 加载失败的警告可忽略
#    （huggingface-hub 版本不匹配，自动降级 hash embedding，不影响 discover 结果）。
# 2. Neo4j migrate（增量模式，秒级-分钟级；日志"Found N YAML files, X need migration"）
PYTHONPATH=src .venv/bin/python scripts/migrate_claims_to_neo4j.py > /tmp/migrate_xxx.log 2>&1 &
#    ⚠️ migrate 可能静默挂起（2026-08-24：前台跑 300s 超时无输出、验证查询新 claim 返回空）。
#    完成判定不要靠 exit code，必须 Neo4j 直接查询验证：
#    python3 -c "from neo4j import GraphDatabase; d=GraphDatabase.driver('bolt://localhost:7687',auth=('neo4j','qingneo4j')); print(d.session().run(\"MATCH (c:Claim {id:'claim-XXX-a'}) RETURN c.id\").data())"
#    （密码是 config.py 默认 'qingneo4j'，不是 .env 里猜的值）。未入库则查脚本日志排障或分批重跑。
# 3. Qdrant 重建（服务端模式无需停进程；全量 3527 条约2-3分钟）
PYTHONPATH=src .venv/bin/python scripts/index_claims_to_qdrant.py --force-recreate > /tmp/qdrant_xxx.log 2>&1 &
# 4. 重启 Agent（先 pkill 再起，health 验证 200）
# ⚠️ Hermes 前台 shell 会拒绝 nohup/disown/setsid 包装 → 必须用 terminal(background=true)，
#    watch_patterns=["Application startup complete"] 等启动完成信号，再单独 curl health
```

- **勿跑** `run_sync_pipeline.sh` 整脚本（gateway 重启会连带杀子进程）。
- ⚠️ **migrate 与 index 有数据依赖，严禁并行（2026-08-16 实测）**：`index_claims_to_qdrant.py` 是从 **Neo4j** 读数据（`MATCH (c:Claim)`）而非直接扫 YAML 目录；若并行启动 migrate 与 index，index 的读取会先于 migrate 写入完成 → 新 claims 缺失。症状：index 日志显示条数 < migrate 后 Neo4j 实际条数，Qdrant scroll 按 claim_id 查新 id 命中 0（注意 payload key 是 `claim_id` 不是 `id`，且 match 是全词匹配需用完整 id）。修复：migrate 完成后**重跑** `index_claims_to_qdrant.py --force-recreate` 即可（幂等）。顺序必须：migrate 先完成 → 再 index。
- Qdrant 完成后用 `mcp__qdrant__search_claims` 验证新 claim 可检索；
  `mcp__neo4j__get_claim_relations` 验证关系边已入库。
- discover 回写 YAML（last_discovered/supersedes/supplements）后要**再 commit 一次**，
  与提取 commit 分开（用户偏好：ingest 完成先独立 commit）。

## 7. Gate 5 假阳性维护（新增模式登记）

2026-08-13 晚间复盘新增 3 条 NON_COMPANY 模式（科技类通用词）：
`万亿且高位科技` / `随后非科技` / `冲高回落的科技`。

2026-08-14 早盘专栏新增 14 条 NON_COMPANY 模式（36 条 claims）：
- **科技/电子/智能 板块通用词**：`时它能取代科技` / `取代科技` / `医药仍是科技` /
  `维持防守与科技` / `转进攻并与科技` / `医药与科技` / `对今天科技` /
  `绪健康构成科技` / `灵活组合的科技` / `先由电子` / `缺一个类似电子` /
  `模型厂商向智能` / `新款智能`
- **非 A 股**：`接投资三星电子`（三星电子为韩股，无 6 位 A 股代码 → NON_COMPANY）

2026-08-16 周复盘专栏新增 6 条 NON_COMPANY 模式（25 条 claims）：
- `权重科技` / `且权重与科技`（权重与科技同步，板块组合非公司）
- `金主线围绕科技`（资金主线围绕科技）
- `先创新高的科技`（创新高的科技分支）
- `汇兑损失与股份`（股份支付，非公司）
- `决定非科技`（非科技方向）

2026-08-18 早盘专栏新增 9 条 NON_COMPANY 模式（26 条 claims）：
- **⚠️ 必须加完整捕获串**（见 7e）：`今日开盘对科技` / `线大涨就做科技` /
  `鹰对高估值科技` / `场直接催化有限`（7 字完整串，不是短模式 `对科技`/`做科技`）
- 短模式辅助（可保留）：`做科技` / `对科技` / `因此科技` / `高估值科技` / `直接催化有限`
- 本次同时命中 1 条真漏标：`收购中石科技` → 补 `中石科技(300684)`（真公司，不能进 NON_COMPANY）

2026-08-18 盘中+复盘新增 6 条 NON_COMPANY 模式：
- 09:27 动态：`纪要偏鹰压科技`（"纪要偏鹰压科技"完整串）
- 13:31 午盘：`度大概率也有限` / `调整幅度有限`（"有限"被正则当公司后缀）
- 22:32 复盘：`二浪回调时科技` / `线强势之后科技` / `全线强势后科技` / `度可能弱于科技`

2026-08-19 早盘专栏新增 14 条 NON_COMPANY 模式（24 条 claims，Gate2 一次报 16 条）：
- **科技 板块通用词（完整捕获串，全加）**：`尤其高估值科技` / `回调但科技` /
  `要还是因为科技` / `涨的主因是科技` / `抢先手说明科技` / `否承接决定科技` /
  `则证明科技` / `明资金对于科技` / `越说明科技` / `这决定了科技` / `不在科技` /
  `此时不在科技` / `机器人链但科技` / `包括长鑫科技`
- 真漏标 2 条（非假阳性）：013/022 提到天洋新材但 related_stocks 空 → 补
  `天洋新材(603330)` 进 related_stocks（**Gate2 的"statement 标注了代码但 related_stocks 为空"报错
  = related_stocks 缺失，不是代码漏标**，两条都要查：代码标注 + related_stocks 结构）

2026-08-19 盘中两条图片动态（09:59 + 12:03）新增 1 条 NON_COMPANY 模式（12 条 claims）：
- `亏损风险有限`（12:03 动态 031 interpretation"亏损风险有限"——"有限"后缀被正则当公司名；
  与 8/18 午盘 `度大概率也有限/调整幅度有限` 同族，**"X有限"是高频假阳性后缀，批量出现时直接并入既有模式**）

2026-08-19 尾盘动态（14:11）+ 复盘专栏（22:43）新增 8 条 NON_COMPANY 模式（36 条 claims）：
- 尾盘 14:11（6 条 claims）：`指数跌幅有限`（"跌幅有限"同族，与 `调整幅度有限/亏损风险有限` 归并）
- 复盘 22:43（30 条 claims）：
  - **科技板块通用词**：`高度集中在科技` / `抛压在科技` / `抛压集中在科技` / `以及科技` / `它只是让科技`
  - **非 A 股/术语**：`用高压直流电子`（"高压直流电子屏蔽泵"技术术语）/ `迈威尔科技`（美股 MRVL，
    与 8/14 三星电子同族——**非 A 股公司名一律进 NON_COMPANY，不标 6 位 A 股代码**）

2026-08-24 周复盘新增 4 条 NON_COMPANY 模式（18 条 claims，Gate2 报错完整串）：
- `不是单纯的科技` / `财报是本周科技` / `资金明显从科技` / `于少数高位科技`
- 同场真漏标自查：深中华A(000017)/电连技术(300679)/飞龙股份(002536)/中际旭创(300308)/
  神奇制药(600613)/天孚通信(300394)/仕佳光子(688313) 均 API 查证后标注，无漏。

2026-08-24 晚间复盘新增 10 条 NON_COMPANY 模式（26 条 claims，Gate2 一次报 10 条）：
- **未上市标的名 + 通用词文本片段**：`购苏州岚创科技` / `收购岚创科技`（岚创科技=被收购标的
  非上市公司，同族：`旺实业发展有限` = 富的旺旺实业，均不进 related_stocks 不标代码）
- **科技/电子/智能/股份 板块通用词完整捕获串**：`中优先观察科技`（反弹中优先观察科技）/
  `海内外的科技`（海内外的科技巨头）/ `拟以发行股份`（拟以发行股份及支付现金，交易方式术语）/
  `户提供消费电子`（为客户提供消费电子精密金属）/ `务器等新型智能`（AI服务器等新型智能终端）/
  `天尾盘回流科技` / `尾盘回流科技`（尾盘回流科技，与 8/19 `抛压在科技` 同族）
- 真漏标自查：东山精密(002384) 在 statement 中漏标已补（l claim），无其他漏标。

维护流程：确认假阳性 → 编辑 `scripts/gate_validate_claims.py` NON_COMPANY 集合
（勿用 sed 全局替换）→ 删 gate2 缓存 → continue。登记模式时按 raw 类型归类，
参考 `qing-learning-claim` 的 `references/gate5-false-positive-patterns.md`。

## 7d. Gate5 报错 = 真漏标 + 假阳性混合，先分辨再统一修（2026-08-16 实战）

Gate2 失败的错误列表**同时混着真漏标和假阳性**，不能全部扔进 NON_COMPANY，
也不能全部当漏标补——先 grep 定位再分类：

- 8/16 周复盘 Gate2 一次报 7 条，其中 `若紫光股份` 是**真漏标**：claim-013 statement
  前半句"紫光股份(000938)和华勤技术(603296)跟涨"带了代码，后半句"若紫光股份、
  华勤技术始终不跟"漏了——同一句内重复出现时只标第一次，第二次出现被 annotate
  的 `if f"{name}({code})" not in text` 包含性检查跳过（文本里已有一次就不补第二次）
- 其余 6 条（权重科技/围绕科技/创新高的科技/汇兑损失与股份/决定非科技）是假阳性

**修复顺序**（缺一不可）：
1. `grep -n "<报错片段>" temp/claims/<session>/step2_enriched.json` 定位实际位置
2. 真漏标 → 补代码（execute_code 精准 replace）；假阳性 → 加 NON_COMPANY
3. `rm temp/claims/<session>/gate2_result.json`（缓存不比较时间戳）
4. `continue` 重跑 → Gate2 通过

**annotate 技法防漏**：statement/interpretation 里同一公司名出现多次时，
用 `replace` 全量替换即可全部标注（包含性检查只防重复标注同一处，不防漏标第二处）。
Step 2 生成后自检：遍历 STOCKS 全名，`f"{name}({code})" not in text` 报 missing 的，
区分"文本里根本没出现该名"（误报，可忽略）与"出现了但没带代码"（真漏标，必修）。

## 7e. NON_COMPANY 必须加「完整捕获串」而非短子串（2026-08-18 实战，首修失败）

`gate5_stock_codes()` 正则 `[\u4e00-\u9fff]{2,5}(?:股份|科技|电子|智能|医疗|有限)`
`re.findall` 捕获的是 **2-5 个汉字 + 2 字后缀的完整串（最长 7 字）**，
报错信息 `'{name}' 在文本中出现但未标注` 里的 name 就是完整串。

**坑**：往 NON_COMPANY 加短子串（如 `对科技`、`做科技`、`因此科技`、`高估值科技`）
**不生效**——因为 findall 返回的是上下文完整串（`今日开盘对科技`、`线大涨就做科技`、
`鹰对高估值科技`、`场直接催化有限`），集合里没有该完整串就继续报错。

**正确做法**：把 Gate2 报错列表里的**完整 name 原样**加进 NON_COMPANY（7 字串），
再删 gate2 缓存重跑。2026-08-18 流程：第一次只加短模式 → 仍报 4 条；补上 4 个
7 字完整串 → Gate 2 通过。判断标准：报错信息里 name 是什么，就加什么。

**参考**：`qing-learning-claim/references/gate5-false-positive-patterns.md`（模式库）

## 7b. Step 2 程序化 annotate：无重复标注技法（2026-08-14 早盘 36 条实测）

Step 2 用 execute_code 批量补代码时，用**包含性检查**代替正则负向前瞻
（debug §2 的 lookahead bug 根因是正则跳过"名字后跟中文括号"的正常情况）：

```python
STOCKS = {"中际旭创": ("300308", "创业板-不可交易"), ...}  # name -> (code, 板块role)
claim_stocks = {"001": [], "010": ["百花医药"], "026": ["中际旭创", "中石科技"], ...}

def annotate(text, names):
    for name in names:
        code = STOCKS[name][0]
        if f"{name}({code})" not in text:   # ✅ 已标注跳过，未标注替换
            text = text.replace(name, f"{name}({code})")
    return text

for c in claims:
    cid = c["id"].split("-")[-1]
    names = claim_stocks.get(cid, [])
    c["statement"] = annotate(c["statement"], names)
    c["interpretation"] = annotate(c["interpretation"], names)
    c["related_stocks"] = [{"code": STOCKS[n][0], "name": n, "role": STOCKS[n][1]} for n in names]
```

**要点**：
- 代码表一次批量查全（东财 searchapi 循环），不要逐个手查
- **东财 searchapi 全挂时的兜底：腾讯 smartbox**（2026-08-25 实测，东财 suggest 全部 ERR）：
  ```python
  import urllib.request, urllib.parse, re
  q = urllib.parse.quote(name)   # 必须先 quote！裸中文会 ascii 编码报错
  data = urllib.request.urlopen(f"https://smartbox.gtimg.cn/s3/?v=2&q={q}&t=all",
                                timeout=8).read().decode("utf-8")
  m = re.search(r'"(sz|sh|bj)~(\d{6})~', data)  # → 'sz~002837~英维克~ywk~GP-A' → 002837
  ```
  批量循环查 18 个公司名约 10s 内完成。返回格式 `v_hint="sz~002837~英维克~ywk~GP-A"`，
  第二个 `~` 分隔段即 6 位代码。（重要：东财 push2/datacenter 反爬断连是记忆中的已知坑，
  searchapi 同样会偶发失效——smartbox 是稳定的第二通道）
- **原文"板块内记录/映射"里的公司也要补**：raw 末尾列出的个股（如"板块内记录：
  澳洋健康、博济医药等"）即使不出现在 statement 主语中，也要进对应 claim 的
  related_stocks——它们是检索入口
- 无标的 claim 必须写 `related_stocks: []`（标记"已检查"）
- role 标注：`主板-可交易`（sh6/sz0）/ `创业板-不可交易` / `科创板-不可交易`，
  与用户只做主板的纪律一致（记忆：仅主板 sh6/sz0）

## 7c. 同日期多 raw：claim 编号跨文件延续 + wiki 同日追加段落（2026-08-14 实测）

一天有多份 raw（早盘 09:02 专栏 + 盘中 13:45 动态）时：
- **claim 文件分开**：早盘 → `claim-20260814-001.yaml`（001-036），盘中 → 新文件
  `claim-20260814-002.yaml`（**037-039 续号**，不是从 001 重排）。核对编号 = 看当日
  所有 YAML 的最后一个 id +1，不是"文件序号+1"（呼应 debug §18）
- **wiki 同日追加段落**：盘中动态**追加进当日 wiki 文件**（`knowledge/wiki/每日复盘/2026-08-14.md`），
  在"修复记录"段前插入 `# 2026-08-14 盘中动态（13:45 图片）` 新小节（`---` 分隔），
  不新建 wiki 文件——一个交易日一个 wiki file，多 raw 用 `#` 二级标题分段
- `sources/raw/财经/` 找不到当日文件时，检查 `sources/original/bilibili/`（两个目录都可能有）
- **同日续号实战（2026-08-25）**：早盘专栏 → claim-20260825-001.yaml（001-026），
  午盘动态 → claim-20260825-002.yaml（027-032 续号）。id 前缀仍用原日期序号
  （claim-20260825-027-a），文件按当日顺序编 002

## 7d. 同日续号冲突：Step1 新提 ID 必须从当日最大号+1 起（2026-08-25 复盘实战）

**事故**：8/25 晚间复盘提取时，Step 1 草稿直接用了 `claim-20260825-028-a` 起头，
但当日已有 claim-20260825-001.yaml（001-026）+ claim-20260825-002.yaml（027-032）——
**028-032 五个 ID 撞车**。因为流水线 `start` 只按 session 生成、不管日期全局号段，
Agent 在 Step 1 要自己核对当日已用最大号。

**正确做法（Step 1 写 before start）**：
```bash
# 提取前先查当日所有 YAML 的最后一个 id（跨文件！）
grep -h "id: claim-YYYYMMDD-" knowledge/claims/claim-YYYYMMDD-*.yaml | tail -1
# 新提取从 max+1 起编号
```

**若已撞号（Step 4 发现重复）**：不要重跑（Gate 已过、浪费），直接在
`step3_yaml/` 的 YAML 上批量重编号再移入正式目录：
```python
# 把 028-049 → 033-054（偏移 +5），正则替换 id 前缀，注意 statement/interpretation
# 里若引用了自己批次的 claim id（supersedes 等）也要同步换
import re
t = open('step3_yaml/xxx.yaml', encoding='utf-8').read()
t = re.sub(r'claim-20260825-(0\d\d|1\d\d)-a',
           lambda m: f'claim-20260825-{int(m.group(1))+5:03d}-a', t)
```
重编号后跑一次 `gate_validate_claims.py <yaml>` 确认一致性，再 move 进 knowledge/claims/。
（Gate 3 已过的文件改 id 不影响校验，但 topic/statement 里引用旧 id 会留下死链——重点查。）

## 7e. Gate 2 公司名正则误报 → NON_COMPANY 黑名单维护（2026-08-25 晚间复盘）

Gate 2 的公司名识别正则 `([\u4e00-\u9fff]{2,5}(?:股份|科技|电子|智能|医疗|有限))`
会把**通用词语尾**当公司名：8/25 晚间复盘报 5 个假阳性——「及产量释放有限」「偏光纤恰是科技」
「提供超高纯电子」「大概率要靠科技」「反弹靠科技」，全是 `XX科技/XX电子/XX有限` 的文本片段，
不是真公司。

**处理流程**（先判定再处理，避免误屏蔽真公司）：
1. 先复现确认是误报：`execute_code` 里跑同样的正则在 claim 文本上 findall，看命中串是不是
   通用词片段（「及产量释放有限」= 产量释放+有限，「恰是科技」= 科技板块上下文）。
   同时确认该串**确实没有**紧跟 6 位代码（真公司会写 `公司名(6位)`）。
2. 补进 `scripts/gate_validate_claims.py` 的 `NON_COMPANY` 集合（带日期注释段），
   格式与既有条目一致（截取命中的完整片段，不是完整句子）。
3. **改完脚本必须删 Gate 缓存再 continue**：`rm temp/claims/<session>/gate2_result.json`，
   否则 pipeline 读旧缓存仍报相同错误（参见 2b）。8/25 实测：不加这步，continue 一直吐同样的 5 条。
4. 历史命中扫描：`python scripts/gate_validate_claims.py --all` 复查存量（若怀疑影响面）。

**教训**：NON_COMPANY 是持续成长的列表（8/4 起每篇复盘都在加），这是**正常维护**不是 bug；
加条目时注释日期，方便日后回溯哪天的文本引入了它。

## 验证清单

```
☐ git pull 后再 start（用户强制）
☐ .venv/bin/python 直跑，无 uv run
☐ 股票代码逐个 API 查证
☐ Gate 3 通过 + 手动 gate_validate_claims.py 复验
☐ wiki/log/index 更新，build_indexes.py 重建
☐ 提取 commit + discover 回写 commit 分开
☐ discover→migrate→Qdrant→Agent 重启，health 200
```
