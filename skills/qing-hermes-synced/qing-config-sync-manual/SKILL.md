---
name: qing-config-sync-manual
description: |
  手动维护监控配置的补充技能（qing-stock-monitor-update 的外部只读限制下使用）。
  覆盖：①券商持仓截图 OCR → positions.yaml 更新 ②strategy_pack/direction_pool 手动同步规范
  ③ETF 加入 watchlist 的验证链路。
  Use when: "更新持仓"（发截图）、"同步 strategy_pack"、"更新 direction_pool"、"加ETF到watchlist"
---

# qing-config-sync-manual

> 背景：`qing-stock-monitor-update` 位于项目 `skills.external_dirs`，自主策展只读。
> 本技能承载 2026-08-11 会话沉淀的手动配置维护流程，作为补充。
> 涉及项目路径：`~/learning-investment-strategies/config/stock_monitor/`

## 一、持仓截图 OCR → positions.yaml 更新

**触发**：用户发券商 App 持仓截图（MEDIA 图片）要求更新持仓。

### 标准流程

1. **图片定位**：`/home/ubuntu/.hermes/cache/images/img_*.jpg`
2. **OCR 提取**（rapidocr，项目 venv）：
   ```python
   from rapidocr_onnxruntime import RapidOCR
   import cv2
   img = cv2.imread('<path>')
   img2 = cv2.resize(img, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)  # 2x 放大提精度
   cv2.imwrite('/tmp/x_2x.jpg', img2)
   ocr = RapidOCR(); result, _ = ocr('/tmp/x_2x.jpg')
   # 按 y 坐标分桶 + x 排序输出，恢复表格布局
   ```
3. **解读券商 App 布局**（大同/华宝已验证，格式相同）：
   - 每只持仓两行：行1 = 名称 | 当日盈亏额 | 持仓数量 | **成本价**；行2 = 市值 | 当日盈亏率 | 可用数量 | **现价**
   - 注意区分：**行1第4列=成本，行2第4列=现价**（不要搞反）
4. **三方交叉验证（必做）**：
   - 市值公式：`市值 = 数量 × 现价`（用截图内数字，能定位哪列是现价）
   - 盈亏公式：`盈亏额 = 数量 × (现价 - 成本)`、`盈亏率 = (现价-成本)/成本`
   - 实时行情：腾讯 `https://qt.gtimg.cn/q=<市场字母+代码>`（**GBK 解码**：`.decode('gbk', errors='replace')`），东财 push2 批量接口易空返回，优先腾讯
   - 代码核实：东财 searchapi `https://searchapi.eastmoney.com/api/suggest/get?input=<名>&type=14&count=2`
5. **更新 positions.yaml**：
   - `updated_at` 改为当日；新账户追加 `accounts[].broker` 块
   - 注意成本可能变化（做 T 摊低）→ 以截图为准更新
   - 可用 < 持仓时（挂单/冻结）按持仓总量记录并向用户提示
   - **positions.yaml 是 gitignored 私有文件，只改本地，不进 git**

### 陷阱
- OCR 读"成本/现价"两列常混淆 → 用市值=数量×现价反推验证
- ETF 显示简称（如"科创半导"）≠ 基金全称 → 用代码+搜索确认
- 截图时点 vs 当前时点现价不同 → 验证公式用截图内数字，实时行情只验证代码正确性

## 二、strategy_pack / direction_pool 手动同步

**触发**：用户要求"同步更新 strategy_pack/direction_pool"（MCP 检索 → 差异报告 → 用户确认 → 执行）。

### strategy_pack.yaml 字段规则

| 字段 | 规则 |
|---|---|
| `updated_at` | 当前日期 |
| `source_claims` | 顶部追加最新 claim 文件（保留历史） |
| `market_framework.current_stage` | **顶部追加**最新定调段落（保留历史段落） |
| `market_framework.up_quote` | **全量替换**为最新 UP 原话 |
| `market_framework.core_question` | 全量替换 |
| `market_framework.key_assumptions` | 顶部追加 `- 【框架升级 日期】…` |
| `direction_priority` | 顶部插入最新方向，旧方向保留 |
| `market_gate_rules.volume_checks` | 追加新 check + 更新 note（保留旧 check） |

### direction_pool.yaml 字段规则

| 字段 | 规则 |
|---|---|
| `updated_at` | `'YYYY-MM-DD'` |
| 头部 `# ⚠️` 时间线 | **顶部追加**（最新在上） |
| 新方向 | 文件尾部追加完整条目（id/name/current_stage/industry_chain/diffusion_path/pre_condition/note） |
| 已有方向 | 只改 `pre_condition.market` + 追加 note |
| 降级 | `current_stage: monitor_only`，**不删除** |

### 陷阱（2026-08-11 实战）
1. **patch 错目标**：direction_pool 多个方向 pre_condition 结构相同，模糊 old_string 会命中错误方向
   （本次把 PCB 内容写进 ccL_resin_upstream）。修复：patch 前 `awk '/- id: <目标>/,/^  note:/'` 定位行号，
   用唯一上下文；改后 python yaml 加载确认目标变了。
2. **新标的代码必须核实**：曾把 600732 爱旭股份（光伏）误当交换机标的。东财 searchapi 逐个核实。
3. **验证三步**：YAML 合法性加载 + `python3 scripts/validate_config.py` + `collect_quote_targets` 确认 secid。
4. **只改系统消费的字段**（消费方映射见 qing-stock-monitor-update §references/config-field-consumer-map.md）。

## 三、ETF 加入 watchlist

- **行情链路已验证**：`stock_code_to_secid` 支持 588xxx.SH / 159xxx.SZ（ETF 与股票同 secid 格式），
  tdx fetcher 可直接拉 ETF 行情（价格×10 缩放）
- `collect_quote_targets` 从 `position_rows`（positions.yaml）+ `watchlist_stock_rows` 收集，`seen_secids` 去重——
  持仓 ETF 无需重复入 watchlist 也能被 poll 监控；入 watchlist 仅为 theme 分组（role: holding_etf）
- 校验：`python3 scripts/validate_watchlist.py`（0 ❌ 0 ⚠️）+ `collect_quote_targets` 确认目标包含 ETF secid

### 陷阱（2026-08-17 实测）
1. **⚠️ 追加 theme 的位置**：watchlist.yaml 顶层键顺序是 `themes:` → **`avoid_and_reduce:`（在 themes 之后）**。用文本把新 theme 追加到**文件末尾**会落进 avoid_and_reduce 的 mapping → YAML 报 `expected <block end>, but found '-'`。**必须插到 `\navoid_and_reduce:` 之前**（`text.rfind("\navoid_and_reduce:")` 定位），追加后 `yaml.safe_load` 验证 themes 数量 + avoid_and_reduce 保留。
2. **collect_quote_targets 返回 dict**（key=`名称(代码)`，value=secid 如 `0.159516`），不是 list——确认 ETF 入 poll 用 `[k for k in t if 'ETF' in k or code in k]`，别按 list 解包。
3. 新 theme 至少需要 `id/name/up_positioning/note/stocks`（stocks 里 `role: holding_etf`、`priority: 持仓-券商名`、`lifecycle.stage: holding`、`linked_claims` 绑 UP claims），无 stocks 的观察 theme 可省（参考 securities_bottom）。

## 四、Qdrant 服务端模式重建（2026-08-24 实测；qing-learning-sync 坑1"必须全停"已过时）

qing-learning-sync 是外部只读 skill，此经验沉淀在此。Qdrant 仅服务端模式（`./bin/qdrant`, port 6333, RocksDB）后：

- **重建无需停 Qing-Agent / Hermes gateway / MCP**：
  `PYTHONPATH=src .venv/bin/python scripts/index_claims_to_qdrant.py --force-recreate --skip-agent-kill`
- `--skip-agent-kill` 必加——脚本默认杀 uvicorn Agent，是旧 local 模式遗留逻辑
- delete_collection 走 HTTP 到 6333，无 `.qdrant_data/.lock` 文件锁问题；Agent 无需重启即读新数据（health ok）
- 规模参考：3938 claims 约 60s。验证：Qdrant `points_count` == Neo4j `MATCH (c:Claim) count` + integrity check 512 维通过
- "必须全停进程"仅适用于旧 Qdrant local 模式
- 运维坑：execute_code 里长任务会 300s 超时且只杀外层 shell，**内层 python 进程仍在跑**——先 `pgrep -af` 确认再决定是等待还是重启；后台跑用 `setsid nohup ... < /dev/null &` + 日志文件轮询

## 相关参考

- `qing-stock-monitor-update`（外部只读，技能库中无 references 副本时从项目 `skills/` 目录读取）
- `qing-learning-sync`：discover → Neo4j → Qdrant → Agent 重启（claims 入库后的同步管线）
