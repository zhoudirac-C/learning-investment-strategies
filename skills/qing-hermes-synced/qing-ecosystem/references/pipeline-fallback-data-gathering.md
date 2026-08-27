# Pipeline Fallback: Manual Data Gathering When Pre-Run Fails

## 场景

预运行脚本异常（如报 `集合竞价后 分析服务异常`）时，自动数据管线无法提供分析所需中间数据。在此情况下，**不放弃**，直接绕过失败管线，独立采集数据产生分析报告。

## 管线故障自愈路径

```
预运行脚本失败
    ↓
Step 1: 读取本地知识源（Neo4j claims / 文件系统 .yaml）
    ↓
Step 2: 全局指数数据（akshare 或 Sina API）
    ↓
Step 3: 板块强弱数据（akshare.stock_sector_spot）
    ↓
Step 4: 个股实时行情（Sina API curl, 非 akshare 全量拉取）
    ↓
Step 5: 融合 UP 框架 claims 输出分析报告
```

---

## Step 1: 读取本地知识源（离线可用）

### Neo4j（优先）

```python
# Neo4j MCP 工具
mcp__neo4j__get_recent_claims(days=7)   # 最近7天所有观点
mcp__neo4j__search_claims_graph("科技")  # 关键词精确匹配
mcp__neo4j__get_claim_relations("claim-xxx")  # 关系查询
```

### 文件系统（最终降级）

```bash
# 获取最新 claims
ls ~/learning-investment-strategies/knowledge/claims/claim-2026*.yaml | tail -50

# 读取每个 .yaml 的 subject + statement 字段获取 UP 最新观点
```

### Qdrant 语义搜索（可能失败）

```python
mcp__qdrant__search_claims("查询")
# 已知故障: huggingface-hub 版本冲突 → 不需要动代码
# 降级: 使用 Neo4j + 文件系统替代
```

---

## Step 2: 全局指数数据

### akshare 1.18.64（当前版本）

| 函数 | 用途 | 说明 |
|------|------|------|
| `ak.index_global_spot_em()` | 全球指数 | 含美股道指/标普/纳指 + 恒生 + 日经等 |
| `ak.stock_zh_index_spot_em()` | A股全市场指数 | 列名中文: 名称, 最新价, 涨跌幅, 成交额 |
| `ak.stock_hk_index_spot_em()` | 港股指数 | — |

```python
import akshare as ak
df = ak.stock_zh_index_spot_em()
target = ['上证指数','深证成指','创业板指','科创50','沪深300','上证50','中证500','中证1000']
mask = df['名称'].isin(target)
print(df[mask][['名称','最新价','涨跌幅','成交额']])

global_df = ak.index_global_spot_em()
# 查找美股/恒生关键指数
print(global_df[global_df['名称'].str.contains('道琼斯|纳斯达克|标普|恒生', na=False)])
```

### Sina API（快速，无akshare依赖）

先安装 iconv 用于 GBK→UTF-8 转码：
```bash
sudo apt install -y iconv 2>/dev/null || true  # 通常已预装
```

**⚠️ URL 前缀**：不加 `s_`！Sina API 有两个端点：
- `s_sh000001`（旧版，有预计算涨跌额）— 文档不一致
- `sh000001`（新版，**无预计算**，返原始定价）— **推荐，始终可用**

```bash
# 指数批量查询（注意：sh=上交所, sz=深交所，不加 s_）
curl -s 'https://hq.sinajs.cn/list=sh000001,sz399001,sz399006,sh000688,sh000300,sh000016,sh000905' \
  -H 'Referer: https://finance.sina.com.cn' -H 'User-Agent: Mozilla/5.0' | iconv -f GBK -t UTF-8//IGNORE
```

**实际返回格式**（0-indexed CSV，需自行计算涨跌幅）：

```javascript
var hq_str_sh000001="上证指数,3812.1618,3796.2814,3864.3671,3864.6002,3743.3601,0,0,735021925,1396517619564,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,2026-07-21,15:30:36,00,"
var hq_str_sz399001="深证成指,13656.085,13610.231,14264.291,14264.797,13364.407,0.000,0.000,83591133533,1560575057534.151,0,0.000,0,0.000,0,0.000,0,0.000,0,0.000,0,0.000,0,0.000,0,0.000,0,0.000,0,0.000,2026-07-21,15:00:03,00"
var hq_str_sz399006="创业板指,3469.223,3443.102,3685.969,3687.147,3373.040,0.000,0.000,25892240565,741575473541.900,0,0.000,0,0.000,0,0.000,0,0.000,0,0.000,0,0.000,0,0.000,0,0.000,0,0.000,0,0.000,2026-07-21,15:00:03,00"
var hq_str_sh000688="科创50,1747.4897,1718.6895,1903.1613,1904.8579,1663.8498,0,0,19512745,213055050259,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,2026-07-21,15:35:40,00,"
```

**指数字段映射（0-indexed CSV）**：

| 索引 | 字段 | 示例 | 说明 |
|------|------|------|------|
| 0 | 名称 | 上证指数 | — |
| 1 | 开盘价 | 3812.1618 | — |
| 2 | **昨收价** | 3796.2814 | 计算涨跌幅的基准 |
| 3 | **当前价/收盘价** | 3864.3671 | — |
| 4 | 最高价 | 3864.6002 | 当日最高 |
| 5 | 最低价 | 3743.3601 | 当日最低 |
| 6-7 | 未使用 | 0 | — |
| 8 | 成交量(手) | 735021925 | — |
| 9 | 成交额(元) | 1396517619564 | 向上取万亿 |
| 10-29 | 未使用 | 0 | — |
| 30 | 日期 | 2026-07-21 | — |
| 31 | 时间 | 15:30:36 | — |

**涨跌幅计算**：`(当前价 - 昨收价) / 昨收价 × 100%`

```python
# Python 解析
parts = result.split('"')[1].split(',')
name = parts[0]
current, prev_close = float(parts[3]), float(parts[2])
pct = (current - prev_close) / prev_close * 100
volume_hand = int(parts[8])          # 成交量（手）
amount_yuan = float(parts[9])        # 成交额（元）
```

---

## Step 3: 板块强弱数据

### ✅ ak.stock_sector_spot() — 优先使用

```python
df = ak.stock_sector_spot()  # 返回 49 个行业板块
# 列: 板块, 涨跌幅, 公司家数, 总成交额, 平均价格, 涨跌额, ...

# 涨幅 TOP20
df.sort_values('涨跌幅', ascending=False)[['板块','涨跌幅','公司家数','总成交额']].head(20)

# 跌幅 TOP10
df.sort_values('涨跌幅', ascending=True)[['板块','涨跌幅','公司家数']].head(10)
```

### ❌ 不推荐: ak.stock_board_industry_spot_em()

在 akshare 1.18.64 中，此函数返回单板 item/value 长格式，非全板块排名。确认 API 版本支持全列表前，用 `stock_sector_spot()` 替代。

### ⚠️ 降级策略：当板块 API 和 Sina 行业排名 API 全部不可用时

**典型场景**（2026-07-23 复盘案例）：akshare `stock_sector_spot()` 超时 / Sina 行业排名 API 返回 404 (`Service not found`) / EastMoney 板块 API 被限流。三条路由同时失败。

**替代方案：从个股涨幅/跌幅 TOP20 推断板块轮动**

```bash
# 全 A 股涨幅前 20
curl -s 'https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData?page=1&num=20&sort=changepercent&asc=0&node=hs_a' \
  -H 'Referer: https://vip.stock.finance.sina.com.cn'

# 全 A 股跌幅前 20
curl -s 'https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData?page=1&num=20&sort=changepercent&asc=1&node=hs_a' \
  -H 'Referer: https://vip.stock.finance.sina.com.cn'
```

**返回 JSON 结构**：数组，每项含 `{code, name, changepercent, trade, amount, ...}`
**注意**：`num` 最大 100 条；`node=hs_a` 是沪深全 A；需要 `-H 'Referer: https://vip.stock.finance.sina.com.cn'` 否则被限流。

**手动归类推断法**（只适用于极端分化行情）：

```python
# 步骤：
# 1. 拉取涨幅/跌幅前 20
# 2. 对每只个股，通过代码前缀 + 名称判断所属板块
#    - 300/688 开头 + "电气" → 电力设备
#    - 688 + "华虹/燕东/甬矽" → 半导体/封测
#    - 002/300 + "游戏/传媒" → 游戏/AI应用
# 3. 统计板块出现频次 → 推断资金方向
#
# 2026-07-23 案例：
# 涨幅榜：中能电气(+20%) 和顺电气(+20%) 双杰电气(+20%) 金冠股份(+20%)
#   → 电力设备4只涨停 → 全市场共识方向
# 跌幅榜：华虹宏力(-12.6%) 燕东微(-10.5%) 甬矽电子(-9.4%) 汇成股份(-9.4%) 盛科通信(-8.6%)
#   → 半导体/封测5只暴跌 → 全面退潮
# 结论：资金从科技流向电力 = 风格大切换
```

**适用边界**：
- ✅ 只在极端分化行情下有效（涨停潮 vs 跌停潮并存）
- ❌ 不适用于温和震荡市（板块涨跌 ±2% 以内）
- ❌ 无法量化非极端板块的温和变化
- 推断结果应标注"推测"标签，避免作为精确数据使用

## Step 4: 个股实时行情

### ❌ 不推荐: ak.stock_zh_a_spot_em()

拉取全市场 5000+ 只股票数据，耗时 >60 秒，不适用于实时场景。

### ✅ Sina API 批量查询（推荐）

```bash
# 编码: sz=深交所, sh=上交所
# GBK 编码处理：直接 curl 后 iconv 转码
curl -s 'https://hq.sinajs.cn/list=sz002409,sz002812,sh600519,sz002281,sz002371,sh600584,sz300308,sz300502,sz001309' \
  -H 'Referer: https://finance.sina.com.cn' -H 'User-Agent: Mozilla/5.0' \
  | iconv -f GBK -t UTF-8//IGNORE
```

**返回字段对照（0-indexed CSV）**: 与指数格式一致

**返回字段对照（1-indexed CSV）**:

| 索引 | 字段 | 示例 |
|------|------|------|
| 0 | 名称 | 雅克科技 |
| 1 | 开盘价 | 149.110 |
| 2 | 昨收价 | 145.000 |
| 3 | **当前价** | 146.050 |
| 4 | 最高价 | 150.000 |
| 5 | 最低价 | 142.120 |
| 8 | 成交量 | 6868672 |
| 9 | 成交额(元) | 1008214176.900 |

**涨跌幅计算**: `(当前价 - 昨收价) / 昨收价 × 100%`

### 编码问题

Sina API 返回 GBK 编码中文，部分乱码不影响的字段：数值索引（1-9）不受影响。纯数值解析无需转码。

---

## Step 5: 融合 UP 框架输出报告

### 从 claims 提取每日核心框架

```python
for claim in recent_claims:
    if claim.claim_type == 'operation':
        # 操作纪律 → 直接引用（如"防守为主"）
    elif claim.claim_type == 'market-cycle':
        # 大盘阶段判断（如"底部结构消失"）
    elif claim.claim_type == 'sector-theme':
        # 板块方向锚定（如"抗跌四线索"）
```

### 情景推演交叉验证

UP 每日 claims 中常有情景推演（如情景A/B/C），与实时数据交叉验证：

| 情景条件 | 实时验证指标 |
|----------|-------------|
| 易中天高开后守住 | 中际旭创/天孚通信/新易盛当前涨跌幅 |
| 指数缩量企稳 | 上证成交额 vs 前日同期对比 |
| 科技补跌收敛 | 科创50涨跌幅 + 电子器件板块涨跌幅 |
| 护盘拉抬冲高回落 | 金融/权重板块 vs 科技板块走势分化度 |

**核心纪律**：即使情景A条件初步满足，也需连续2-3日验证才视为趋势反转。一日强反弹不构成入场理由——"老手死于抄底"。

### 📊 监控引擎输出集成（收盘复盘）

当监控引擎（`stock_monitor.py`/`hermes_stock_monitor_agent.py`）运行成功时，会在脚本上下文（Hermes cron 的 `## Script Output`）提供中间数据。这些数据应作为分析起点而非重头获取：

| 监控输出字段 | 分析用途 |
|-------------|---------|
| 已发送提醒 / 被去重压制 | 当日提醒频次→判断市场波动率 |
| 持仓复盘(代码/成本/盈亏) | 直接引用持仓盈亏，不需重新计算 |
| 龙虎榜(全市场61只/持仓命中/净买TOP5) | 资金流向锚点，不需二次查 |
| 板块汇总(OCS/CCL/memory等方向) | 板块维度的资金信号方向 |

**集成方式**：

```python\n# 在收盘复盘中直接将 Script Output 数据作为已知事实引用\n# 不需要通过 Sina API 重新查龙虎榜数据\n# 重点做三件事：\n# 1. 龙虎榜净买TOP5 → 方向确认（如光迅+1.24亿=OCS方向吸筹）\n# 2. 龙虎榜持仓命中 → 标的验证（如雅克+6744万=CCL涨价逻辑兑现）\n# 3. 板块汇总 → 与 Sina API 个股行情交叉比对\n```\n\n**典型输出结构**（2026-07-21 示例）：\n\n```\n已发送提醒：17        # 活跃市场，非冷清日\n被去重压制：40        # 波动触发较多，说明分歧大\n持仓：恩捷 +4.19%     # 直接引用浮盈\n龙虎榜：德明利-10.53亿、光迅+1.24亿、雅克+6744万  # 资金方向锚点\n```\n\n---\n\n## 扩展：双重故障场景 SOP（脚本超时 + push2 断连）\n\n### 场景特征\n\n| 故障 | 表现 | 逆转条件 |\n|------|------|---------|\n| 脚本超时 | `Script timed out after 300s: qing_stock_monitor_agent.py` | 不逆转——cron 强制 300s 含 wrapper 缓冲 1900s，已持续不一致（2026-07 起） |\n| push2 系统性下行 | `Remote end closed without response` 出现在 **所有** 东财 API（指数/板块/个股均报错） | 非自主恢复；持续数小时至数天 |\n\n**关键判断**：若 `update_index_klines_intraday.sh`（no_agent 脚本）在同一时段也报 `Remote end closed`，则 push2 是系统性故障而非单脚本重试耗尽。此时 **不重试** push2，直接走 Sina/腾讯链。\n\n### 采集流水线（双重故障）\n\n```\n脚本超时 + push2 下行\n    │\n    ├─ 1. Neo4j claims（离线，最快）\n    │    mcp__neo4j__get_recent_claims(days=7)\n    │\n    ├─ 2. 指数行情 → Sina §Step2（已验证最稳定）\n    │\n    ├─ 3. 板块排行 → 东财 curl 重试一次（仍有 `Remote end closed` 则放弃）\n    │    → 换：通过 watchlist.yaml 配置逐一查 Sina 个股行情，手动合成板块强度\n    │\n    ├─ 4. 观察池行情 → Sina 批量 API（≤30 只/次）\n    │    ↓ 代码见下方 §fetch_sina_batch\n    │\n    ├─ 5. 涨跌/涨停统计 → 跳过（push2 挂时无法获取）\n    │    → 换：用振幅推断（见 §指数振幅推断规则）\n    │\n    └─ 6. 输出报告 → 开头标注：\"脚本超时 + push2 下行，手工采集降级\"\n```\n\n### fetch_sina_batch — 就绪 Python 函数（2026-07-27 验证通过）\n\n```python\nimport urllib.request\n\ndef fetch_sina_batch(sz_codes=None, sh_codes=None):\n    \"\"\"\n    Sina 批量查价。sz_codes/sh_codes 输入数字代码列表，自动加 sh/sz 前缀。\n    返回 dict: {raw_code: {name, open, prev_close, current, high, low, chg_pct, vol, amount}}\n    \"\"\"\n    codes = []\n    if sz_codes: codes.extend(f'sz{c}' for c in sz_codes)\n    if sh_codes: codes.extend(f'sh{c}' for c in sh_codes)\n    if not codes: return {}\n\n    url = f'https://hq.sinajs.cn/list={\",\".join(codes)}'\n    req = urllib.request.Request(url, headers={'Referer': 'https://finance.sina.com.cn'})\n    resp = urllib.request.urlopen(req, timeout=10).read().decode('gbk')\n    lines = resp.strip().split('\\n')\n\n    results = {}\n    for line in lines:\n        if not line.strip(): continue\n        parts = line.split(',')\n        if len(parts) < 9: continue\n        try:\n            # 从 var hq_str_sz002409=\"... 中提取 ref\n            ref = parts[0].split('=')[-1].strip().strip('\"').strip(\"'\")\n            raw_code = ref[-6:] if len(ref) >= 6 else ref\n            name = parts[0].split('\"')[-2] if '\"' in parts[0] else ''\n            open_p = float(parts[1]) if parts[1] else None\n            prev_close = float(parts[2]) if parts[2] else None\n            current = float(parts[3]) if parts[3] else None\n            high = float(parts[4]) if parts[4] else None\n            low = float(parts[5]) if parts[5] else None\n            chg_pct = round((current/prev_close - 1)*100, 2) if current and prev_close else None\n            results[raw_code] = {'name': name, 'open': open_p, 'prev_close': prev_close,\n                                 'current': current, 'high': high, 'low': low,\n                                 'chg_pct': chg_pct, 'vol': parts[8], 'amount': parts[9]}\n        except (ValueError, IndexError):\n            continue\n    return results\n```\n\n### 指数振幅 → 市场活跃度推断（push2 挂时代替涨停/上涨家数）\n\n| 信号 | 推论 |\n|------|------|\n| 创业板振幅 ≥3% + 涨幅 ≥+2% | 成长放量做多，超 60% 个股上涨 |\n| 科创50振幅 ≥5% + 涨幅 <1% | 科技严重分歧，内部高切低，不适合追涨 |\n| 上证振幅 <1.5% + 涨幅 <+1% | 权重弱势，指数靠个股行情托底 |\n| 深成指振幅 ≥2% + 涨幅 ≥+1.5% | 成长方向放量有效 |\n\n> 上述规则基于 2026-07 多次双重故障场景验证（脚本超时 + push2 下行时唯一可用的活跃度代理指标）。\n\n---\n\n### 🚨 完全黑障：Sina 排行 + EastMoney push2 同时挂掉

**典型场景**（2026-07-27 复盘案例）：
- Sina Market_Center（`json_v2.php/Market_Center?name=hs_a`）返回 `"Invalid service name"`
- Sina Change_Page 同样返回 `"Invalid service name"`
- EastMoney push2 全部返回 `Empty reply from server`（HTTP 52）
- akshare EM 后端同样 Connection aborted

**唯一可用入口**：Sina `hq.sinajs.cn` 单品报价（完全独立于排名API）

```bash
# 唯一幸存的数据通道
curl -s 'https://hq.sinajs.cn/list=sz000636,sz300750,sz002812,...' \
  -H 'Referer: https://finance.sina.com.cn'
```

**应对策略**：按照板块分组手动选股，批量查询 → 见专用参考文档：
[Total Blackout: Sector Proxy via Sina hq.sinajs.cn](total-blackout-sector-proxy.md)

**验证步骤**（全链路存活检查）：
```bash
# 1. 检查 Sina 行情存活
curl -s 'https://hq.sinajs.cn/list=sh000001' -H 'Referer: https://finance.sina.com.cn' | head -c 100
# ✅ hq.sinajs.cn 几乎从不挂

# 2. 检查 Sina 排名存活（大概率挂）
curl -s 'https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center?name=hs_a&num=5&sort=changepercent&asc=0' -H 'Referer: https://finance.sina.com.cn' | head -c 100
# ❌ 返回 {"__ERROR":3,...} → 排名API不可用

# 3. 检查 EastMoney push2 存活（大概率挂）
curl -s 'https://push2.eastmoney.com/api/qt/ulist.np/get?fltt=2&secids=1.000001&fields=f2,f3' -H 'Referer: https://quote.eastmoney.com'
# ❌ Empty reply → push2 被限流
```

## 已知陷阱

| 陷阱 | 表现 | 原因 | 规避 |
|------|------|------|------|
| akshare 版本差异 | API 名称/参数/返回值不符 | 不同版本接口不同 | 运行前 `python3 -c "import akshare; print(akshare.__version__)"` |
| stock_zh_a_spot_em 超时 | 单次拉取 >60s | 全市场 5000+ 股票数据 | 用 Sina API curl 替代 |
| Qdrant 搜索失败 | huggingface-hub 版本冲突 | 编码依赖版本不匹配 | 降级到 Neo4j + 文件系统 |
| stock_board 系列格式 | 返回 item/value 长格式 | API 返回单板聚合数据 | 用 stock_sector_spot() 替代 |
| Sina API 编码 | 中文显示乱码 | GBK 编码 | 数值字段不受影响 |
| EastMoney API 空响应 | curl 返回空/exit=52 | IP 或 User-Agent 被限流 | 切换 Sina API；curl 需同时加 `-H 'Referer: https://finance.sina.com.cn' -H 'User-Agent: Mozilla/5.0'` |
| TDX/Pytdx 依赖缺失 | `ModuleNotFoundError: No module named 'pytdx'` | pip 未安装 pytdx | `pip install pytdx -q`；安装后可用 `python3 -c 'import pytdx; print(\"OK\")'` 验证；首次可能需 2-3 次重试 |
