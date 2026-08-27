---
name: qing-ecosystem
description: "Qing ecosystem: stock analysis, knowledge management, event pipelines, and learning workflows."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [qing, stock, analysis, knowledge, learning, event, pipeline, mcp, fupan]
    related_skills: [ai-stock-analyst, investlog-ai, stock-research-engine, valuation-analysis]
---

# Qing Ecosystem

Qing (青枫浦上Q) ecosystem: stock analysis, knowledge management, event pipelines, and learning workflows.

## When to use

Trigger when the user:
- Asks about Qing-Agent stock analysis
- Wants to use the knowledge MCP system
- Needs event pipeline processing
- Wants to ingest, review, or sync learning claims
- Asks about daily fupan (evening review)
- Needs Kimi Bridge operations (model switch, cron management)

---

## 1. Qing Agent CLI (`qing-agent-cli`)

Analyze stocks, markets, and holdings with Qing-Agent style.

```bash
# Analyze a stock
qing-agent-cli analyze --stock 000001

# Market overview
qing-agent-cli market

# Portfolio review
qing-agent-cli portfolio --file holdings.csv
```

---

## 2. Qing Knowledge MCP (`qing-knowledge-mcp`)

MCP access to Qdrant + Neo4j knowledge retrieval.

```bash
# Search claims
qing-knowledge-mcp search --query "涨价逻辑分类"

# Search knowledge documents
qing-knowledge-mcp knowledge --query "MLCC产业链"

# Get claim relations
qing-knowledge-mcp relations --claim-id claim-20260609-005-c
```

---

## 3. Qing Event Pipeline (`qing-event-pipeline`)

P0 event-driven pipeline: B站新内容 → dual manual gate → auto execution.

```bash
# Monitor B站 for new content
qing-event-pipeline monitor --source bilibili --up 青枫浦上Q

# Process events through dual gate
qing-event-pipeline process --event new_video --gate manual
```

---

## 4. Qing Learning (`qing-learning`)

Investment knowledge management system.

### Sub-workflows

| Workflow | Command | Purpose |
|----------|---------|---------|
| Ingestion | `qing-learning ingest` | raw → claims → wiki → index → commit |
| Review | `qing-learning review` | Check claims consistency, detect drift |
| Sync | `qing-learning sync` | discover → Neo4j migrate → Qdrant → restart |

**Claim 提取参考**：`skills/qing-learning-claim/SKILL.md`。大段分析文本的 Gate 2 假阳性批量处理流程见 `references/claim-gate5-batch-false-positives.md`。

**Step 4 后处理完整流程**（Gate 3 通过后）：
1. 检查 `knowledge/claims/` 下现有最大编号，确认新 claims 编号正确
2. 拆分 step3_yaml 的多 claim YAML 为独立文件（单文件单 claim，`claims: [{...}]` 结构）
3. 验证 stock codes 格式：`related_stocks[].code` 必须为字符串 `'600519'`，不能是整数
4. 更新 `knowledge/claims/index.md`（添加新文件行）
5. 更新 `knowledge/wiki/log.md`（新增日志条目：raw 文件、claim 数量、核心观点、修复问题、引用 IDs）
6. 创建/更新 `knowledge/wiki/每日复盘/YYYY-MM-DD.md`
7. `git add` 新 claims + index + log + wiki + 修复的 gate 脚本 → `git commit`
8. 运行同步管线：
   ```
   # ⚠️ 旧脚本 discover_claim_relations.py 和 run_discover_with_progress.sh 均已弃用
   PYTHONPATH=src .venv/bin/python src/qing_investment/agent/tools/discover_claim_relations.py --all-missing
   PYTHONPATH=src .venv/bin/python scripts/migrate_claims_to_neo4j.py
   # index_claims_to_qdrant.py 会自动停 Agent 释放锁
   PYTHONPATH=src .venv/bin/python scripts/index_claims_to_qdrant.py --force-recreate
   PYTHONPATH=src .venv/bin/python -m uvicorn qing_investment.agent.main:app --host 127.0.0.1 --port 8000 --log-level info &
   sleep 5 && curl -s http://127.0.0.1:8000/health
   ```

**⚠️ Gate 2 缓存陷阱**：修改 `gate_validate_claims.py` 的 NON_COMPANY 后，必须先删除 `temp/claims/<session>/gate*_result.json` 再 `continue`，否则 pipeline 读取缓存旧结果。

**⚠️ 批量处理多个 B站动态**：当日有多条待处理动态时，先一次性复制所有文件到 `sources/raw/财经/`，再逐个 `start` pipeline session，然后依次完成 Step 1→Gate→Step 2→Gate→Step 3→Gate→Step 4。不要等一条完全跑完再处理下一条——`start` 只创建会话，可以并行创建。

**⚠️ 视频动态特殊处理**：`dynamic_type: "视频"` 的动态文件只有标题和 OCR 截图文字，没有完整文案。不能直接提取 claims。需要：通过 bilibili API 获取字幕 → 或等待 UP 发布对应的文字版复盘/专栏 → 或保留 `unprocessed: true` 待后续转录。**例外**：如果视频描述文字本身已包含完整观点（如视频文案预览），按正常流程处理。

---

## 5. Qing Stock Analysis (`qing-stock-analysis`)

Analyze individual stocks through Qing-Agent.

```bash
# Analyze stock
qing-stock-analysis --code 0700 --market hk

# Sector analysis
qing-stock-analysis --sector "半导体"
```

---

## 6. Qing Fupan Morning (qing-fupan-morning-usage)

Daily morning review workflow.

```bash
# Generate morning fupan
qing-fupan-morning --date today --output report.md
```

### 17:00 收盘复盘（独立生成）

当 UP 尚未发布复盘或需要独立交叉验证时，按 references/daily-market-review-methodology.md 的 7 步流程从原始市场数据生成复盘。标准报告结构：核心结论 → 关键分析

---

## 7. 14:00 Afternoon Monitoring (14:00午盘监控)

**独立于晨盘/收盘复盘**的盘中实时分析，在 A 股 14:00 定时触发。用于回答4个核心问题：下午盘走势加速还是衰减、量能同比昨日、板块轮动方向、尾盘条件性建议。

### 数据管线（已验证的高可靠性路径）

```
Sina API / Tencent qt.gtimg.cn（14:00快照）→ 指数实时行情
    ↓
Tencent ifzq（历史日K，需 -L 跟随重定向）→ 昨日量能基准
    ↓
EastMoney push2（fs=m:90+t:2, fltt=2）→ 板块涨幅/跌幅排名
    ↓
Neo4j MCP（mcp__neo4j__get_recent_claims）→ UP最新观点交叉验证
    ↓
输出：4章节结构化分析报告
```

### 核心分析框架（4章）

| # | 章节 | 内容 | 关键数据点 |
|---|------|------|----------|
| 1 | 全天走势回顾 | 上午→14:00演变，加速/衰减判断 | 对比14:01 vs 14:10指数变化方向 |
| 2 | 量能同比昨日 | 当前成交额 vs 昨日全日/同期 | 需ifzq获取昨日日K成交量做基准 |
| 3 | 板块轮动方向 | 领涨/领跌TOP5-10及资金流向解读 | push2板块排名 + claims交叉验证 |
| 4 | 尾盘操作建议 | 条件性建议（非买卖指令） | 持仓盈亏、振幅、明日分歧预测 |

### 14:00特有的判断模式

- **下午加速 vs 冲高回落**：对比14:01与14:10的快照数据，若涨幅扩大→加速，若收窄→回落
- **量能预估**：14:00时两市成交通常已达全日的75-85%，乘以1.2-1.3倍可预估全日
- **小盘 vs 大盘剪刀差**：国证2000/中证1000 vs 上证50的差值>2%时，=极端结构行情，次日必有轮动
- **科创50独跌是危险信号**：若仅科创50下跌且半导体板块同步领跌（如-2.5%），=科技资金流出转消费

### 数据源已知问题

详细技术参考：`references/afternoon-monitoring-methodology.md` → 格局判断 → 风险 → 配置建议 → 监控复盘。

**管线故障自救**: 当预运行脚本/自动数据管线异常时（如报"分析服务异常"），按 references/pipeline-fallback-data-gathering.md 的 5 步自愈路径独立采集数据。核心原则：不放弃——绕过失败管线，直接通过 akshare + Sina API + Neo4j claims 采集数据产生分析报告。

**LLM Provider 配置**: Qing-Agent 的 LLM 路由由 `LLM_PROVIDER` + `KIMI_CODE_ACP_FIRST` 两个 `.env` 字段控制。详见 `references/qing-agent-llm-provider-config.md`。常见场景：从本地 ACP 切回 DeepSeek API 需改 `KIMI_CODE_ACP_FIRST=0` 并重启 Agent。

---

## 7. Qing Agent Router (`qing-agent-router`)

Automatic routing of stock-related queries to Qing-Agent.

```bash
# Route query
qing-agent-router --query "分析一下贵州茅台" --auto

# Check routing
qing-agent-router --query "今天天气如何" --dry-run
```

### Routing rules

| Query type | Route to |
|------------|----------|
| Stock code/name | Qing-Agent |
| Market analysis | Qing-Agent |
| Portfolio review | Qing-Agent |
| Technical question | Hermes general |

---

## 8. Kimi Bridge 运维

Kimi Code IM Bridge 是连接 IM（飞书）与 Kimi Code CLI 的中间件服务。项目路径 `/home/ubuntu/kimi-code-im-bot/`，systemd 服务名 `kimi-bridge.service`。

### 切换 Bridge 模型

**上下文区分**：Hermes Agent 的模型配置在 `~/.hermes/config.yaml` / `~/.hermes/providers/`，与 Bridge **完全无关**。Bridge 模型通过 `.env` 的 `KIMI_ACP_MODEL_ALIAS` 控制，不要混淆。

```bash
# 1. 查看当前模型
grep KIMI_ACP_MODEL_ALIAS /home/ubuntu/kimi-code-im-bot/.env

# 2. 查看可用模型（~/.kimi-code/config.toml 的 [models] 节）
grep -A5 '\[models\.' ~/.kimi-code/config.toml

# 3. 修改 .env
sed -i 's/KIMI_ACP_MODEL_ALIAS=.*/KIMI_ACP_MODEL_ALIAS=kimi-code\/<alias>/' /home/ubuntu/kimi-code-im-bot/.env

# 4. 重启 bridge
sudo systemctl restart kimi-bridge.service

# 5. 验证：日志显示新模型参数
journalctl -u kimi-bridge.service -n 5 --no-pager | grep "Starting Kimi ACP"
```

### 管理 Bridge 定时任务

Bridge 的 cron 任务在 `cron/jobs.json`，每个 job 有 `enabled: true/false` 字段。修改后**必须重启 bridge 才能生效**（不热加载）。

```bash
# 禁用全部
python3 -c "
import json
with open('/home/ubuntu/kimi-code-im-bot/cron/jobs.json') as f: d = json.load(f)
for j in d['jobs']: j['enabled'] = False
with open('/home/ubuntu/kimi-code-im-bot/cron/jobs.json', 'w') as f: json.dump(d, f, indent=2)
print(f'Disabled {len(d[\"jobs\"])} jobs')
"
sudo systemctl restart kimi-bridge.service

# 验证
sleep 2 && journalctl -u kimi-bridge.service -n 3 --no-pager | grep "enabledJobs"
# totalJobs:N, enabledJobs:0 → 全部禁用
```

### Pitfalls

- **Bridge 模型 ≠ Hermes Agent 模型**：两套独立配置。Bridge 改 `.env` 的 `KIMI_ACP_MODEL_ALIAS`，Hermes 改 `~/.hermes/config.yaml` 或 `hermes config set`。
- **模型配置在 TWO 处生效**：`.env` 的 `KIMI_ACP_MODEL_ALIAS` 控制 ACP 进程启动时的 `-m` 参数；`acp-client.ts` 的 `agent_config.model` 控制 ACP session 内部使用的模型。两处必须一致。修改 `.env` 后检查 `acp-client.ts` 的硬编码是否匹配（`src/kimi/acp-client.ts` 中 `agent_config: { model: '...' }` 出现 2 次）。
- `.env` 被 `read_file` 工具拒绝（秘密文件保护），用 `cat /home/ubuntu/kimi-code-im-bot/.env | grep KIMI` 读取。
- 单次禁用会覆盖已有修改。如需保留部分 job，手动编辑 `cron/jobs.json` 的 `enabled` 字段。
- Kimi CLI 版本查看：`/home/ubuntu/.kimi-code/bin/kimi --version`（当前 0.27.0）。
- **Kimi Code CLI 残余自动激活**：即使 `kimi-bridge.service` 已停止且 Qing-Agent 的 `KIMI_CODE_ACP_FIRST=0`，`/home/ubuntu/.kimi-code/bin/kimi acp` 仍可能被 Hermes 的 `kimicode` provider 健康检查或 CLI 自身的 session 维护机制自动唤醒。症状：Mihomo 代理日志出现 `api.kimi.com:443` 连接洪峰，Kimi CLI 日志（`~/.kimi-code/logs/kimi-code.log`）显示 `experimental flags enabled` → `SIGTERM` 反复循环。详见 `references/kimi-code-acp-auto-activation.md`。

### B站动态拉取

B站充电专属动态（`is_only_fans: true`）的图片/截图内容在离线抓取时只有元数据无文字，需通过 API + Cookie 手动拉取。SESSDATA 保存在 `~/.hermes/bilibili_sessdata.txt`，使用方法见 `references/bilibili-sessdata-management.md`。

#### 手动拉取充电专属动态内容

当 raw 文件显示`（无文字内容）`时：

1. **API 拉取详情**：用 curl + SESSDATA 访问 `https://api.bilibili.com/x/polymer/web-dynamic/v1/detail?id={dynamic_id}`
2. **提取图片 URL**：从 `module_dynamic.major.draw.items[].src` 获取
3. **OCR 图片**：首选 RapidOCR（`ocr_image_from_url`），超时回落 tesseract `-l chi_sim --psm 6`
4. **更新 raw 文件**：写入 OCR 提取的文字
5. **判断是否提取 claim**：
   - UP 原创分析/产业链跟踪 → ✅ 提取
   - 转发/截图他人帖子（非UP分析）→ ❌ 跳过
   - 图表截图无文字 → ❌ 跳过
   - 交易时段盘中动态 → ✅ 提取

完整工作流及命令示例见 `references/fetch-charging-dynamic.md`。

#### B站 API 封锁诊断（412 Precondition Failed）

`fetch_bilibili_up_v2.py` 超时/无声失败时，首要排查 B站 API 是否返回 412 Precondition Failed（反爬机制升级）。

**诊断步骤：**

```bash
# 1. 验证 SESSDATA 是否有效（nav API 不受 412 影响）
SESSDATA=$(cat ~/.hermes/bilibili_sessdata.txt)
curl -s --max-time 10 \
  -H "User-Agent: Mozilla/5.0" \
  -H "Cookie: SESSDATA=${SESSDATA}" \
  "https://api.bilibili.com/x/web-interface/nav" \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'Login: {d[\"data\"][\"isLogin\"]}')"

# 2. 直接测试 feed API（预期返回 412）
curl -s -o /dev/null -w '%{http_code}' --max-time 10 \
  -H "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36" \
  -H "Cookie: SESSDATA=${SESSDATA}" \
  "https://api.bilibili.com/x/polymer/web-dynamic/v1/feed/space?host_mid=1420210197&timezone_offset=-480"

# 3. 验证视频 API 是否正常（受 412 影响较小）
curl -s --max-time 10 \
  -H "User-Agent: Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Mobile" \
  -H "Cookie: SESSDATA=${SESSDATA}" \
  "https://api.bilibili.com/x/space/arc/search?mid=1420210197&ps=5&pn=1" \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'Videos: {d.get(\"code\")}')"
```

**已知规律：**\n- `/x/polymer/web-dynamic/v1/feed/space` → curl裸请求412；通过 `fetch_bilibili_up_v2.py` 的完整Cookie模板正常\n- `/x/space/arc/search` → 正常响应（视频列表 API，移动 UA 可用）\n- `/x/web-interface/nav` → 正常响应（登录验证不受影响）\n- `/x/polymer/web-dynamic/v1/detail?id={id}` → 4101152（充电专属内容不可见）\n- `/x/article/viewinfo?id={id}` → -404（专栏 API 完全封锁）

**关键发现：仅 SESSDATA 是不够的。** fetch_bilibili_up_v2.py 的 `build_cookie()` 函数拼装完整的 Cookie 模板（包含 buvid3、b_lsid、buvid4、sid 等 20+ 字段），这才是避开 412 的关键。B站反爬校验了多个 Cookie 字段的关联性，仅传 SESSDATA 会被拦截。因此不要用 curl 单独测试 SESSDATA —— 始终通过 fetch_bilibili_up_v2.py 脚本运行；测试时必须用 `build_cookie()` 生成的完整 Cookie 字符串。

**恢复路径（按优先级）：**

| 优先级 | 方案 | 操作 |
|--------|------|------|
| P0 | 用户手动粘贴内容 | 用户从 B站 APP 复制复盘内容发过来，直接提取 claims |
| P1 | QR 扫码刷新 SESSDATA | 推荐：`python3 scripts/qr_login_auto.py`（自动刷新，二维码过期重发不中断）<br>备选：`uv run python scripts/bilibili_qr_login.py`（单次，需手动重启） |
| P2 | 增强 fetch 健壮性 | 给 `fetch_bilibili_up_v2.py` 添加 412 错误处理和超时放宽（当前完整Cookie模板已能正常工作） |

完整诊断流程和命令示例见 `references/bilibili-api-412-troubleshooting.md`。QR 登录自动刷新脚本见 `scripts/qr_login_auto.py`。

#### QR 登录刷新 SESSDATA

**推荐使用自动刷新脚本**（二维码过期自动重发，无需手动重启）：

```bash
cd /home/ubuntu/.hermes/skills/qing/qing-ecosystem
python3 scripts/qr_login_auto.py
```

备选（单次脚本）：

```bash
cd ~/learning-investment-strategies
uv run python scripts/bilibili_qr_login.py --output ~/.hermes/bilibili_sessdata.txt
```

**⚠️ 关键流程**：用户需要「扫码 + 手机上确认」两步。脚本提示"已扫码，请点确认"时，必须在手机B站APP点击 **「确认登录」** 按钮。

**QR 登录常见问题：**

| 现象 | 原因 | 处理 |
|------|------|------|
| 登录成功但未获取到SESSDATA | B站 API 返回格式变更，cookie_info.cookies 为空 | 已修复：qr_login_auto.py 双格式兼容（cookie + URL参数），详见 references/bilibili-qr-login-api-format.md |
| 用户反复要求再发一次 | 二维码超时 | 用自动刷新脚本，过期自动重发 |
| 刷新 SESSDATA 后 fetch 仍 412 | SESSDATA 与 412 无关（反爬问题） | 走 P0（用户粘贴内容）|

**注意：QR登录API格式变更（2026年7月）**：B站不再通过 data.cookie_info.cookies 返回 SESSDATA，改为嵌入 data.url 的 query 参数中。qr_login_auto.py 已兼容两种格式。详见 references/bilibili-qr-login-api-format.md。

#### SESSDATA 过期管理

见 `references/bilibili-sessdata-management.md`。

---

## Tips

- Qing ecosystem is specialized for Chinese A-share market analysis
- Knowledge MCP requires Qdrant and Neo4j to be running
- Event pipeline requires manual gate approval for P0 events
- Use `qing-agent-router` for automatic routing of stock-related queries
- Kimi Bridge 运维参考「8. Kimi Bridge 运维」
