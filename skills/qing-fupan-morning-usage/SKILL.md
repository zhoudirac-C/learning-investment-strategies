---
name: qing-fupan-morning-usage
description: Use when the user asks how to use UP's daily 复盘 (evening review) or 早盘 (morning report), how to update direction_pool/stock_pool from UP content, or how the three-layer funnel (extract→diffuse→condition) works.
---

# qing-fupan-morning-usage

## 目标

把UP的复盘/早盘/动态转化为可操作的 direction_pool + stock_pool 更新，然后按条件等待入场，不追高。

## 必须理解的前提

### 核心矛盾

```
UP复盘点名标的 → 用户直接加watchlist → 次日已涨停 → 上不了车 → 困惑
```

**根因**：UP点名的个股往往是**信号确认**而非**起涨点**。从方向预判到个股点名之间通常有1-5天窗口，但点名本身往往在涨停前夜甚至涨停当天。

### UP输出的价值分层

| 价值 | 内容类型 | 操作 |
|------|---------|------|
| ⭐⭐⭐⭐⭐ | 大盘方向判断、操作纪律、仓位信号 | **立即执行**（如清仓/减仓） |
| ⭐⭐⭐⭐ | 板块方向预判、扩散路径推演、情绪周期定性 | **研究后等时机** |
| ⭐⭐ | 具体标的点名、产业新闻速递、机构研报线索 | **需二次加工**（找产业链上下游） |
| ⭐ | 大涨后个股复盘、翻倍股回顾 | **纯学习素材**，不要行动 |

---

## 流程总览：三层漏斗

```
UP复盘/早盘/动态
    │
    ├── 第一层：提取方向与阶段 → 更新 direction_pool
    │
    ├── 第二层：扩散产业链找低位 → 更新 stock_pool
    │
    └── 第三层：设置条件单，等三重条件同时满足 → 入场
```

---

## 第一层：提取方向与阶段 → direction_pool

### 从复盘提取

复盘文件路径：`sources/original/bilibili/`（按日期命名）

```yaml
# config/stock_monitor/direction_pool.yaml
# 新增或更新方向

directions:
  - id: unique_identifier
    name: 方向全称
    current_stage: 当前阶段
    industry_chain:  # 产业链结构
      upstream:
        - segment: 上游环节名
          stocks:
            - code: 000000.SZ
              name: 股票名
          pumped: false  # 还未大涨
      midstream:
        - segment: 中游环节名
          stocks:
            - code: 000000.SZ
              name: 股票名
          pumped: true   # UP点名时已涨
      downstream:
        - segment: 下游环节名
          stocks: []
          pumped: false
    diffusion_path:  # UP预测的扩散路线
      - "A→B→C"
    pre_condition:  # 入场前置条件（SectorGate + LLM双重检查）
      market: "全A量能>2.5万亿+非破位状态"
      sector: "板块首次分歧（连续上涨后1-2日调整）"
      timing: "非连续涨停日（涨停家数<板块内30%）"
```

### current_stage 阶段定义

| 阶段 | 含义 | 对应操作 |
|------|------|---------|
| `early_direction` | UP刚提出方向，尚未发酵 | 只研究不买，建产业链图谱 |
| `first_pump` | 方向内个股开始涨停 | 跟踪但不追，等分歧 |
| `diverging` | 板块出现分歧/回调 | **关注第一次分歧尾盘** |
| `resuming` | 分歧后修复走强 | 有底仓持有，无底仓等第二次分歧 |
| `ending` | 退潮/资金撤离 | 不再建仓 |

### 从复盘提取的速查表

| 复盘段落 | 提取到 direction_pool 什么字段 |
|---------|-------------------------------|
| "盘面定调" → 情绪阶段 | `pre_condition.market` 更新 |
| "情绪载体切换" → 核心标的变化 | `industry_chain` 各segment的 `pumped` 标记 |
| "三、当日大涨题材" | 新增 direction 或更新已有方向的 `industry_chain` |
| "扩散路径/展望" | `diffusion_path` + `current_stage` |
| "风险/外部条件" | `pre_condition` 补充 |

### 从早盘提取

早盘核心价值是**情绪方向确认**和**今日验证框架**，不是买入信号。

| 早盘内容 | 提取到 direction_pool | 操作 |
|---------|----------------------|------|
| "三看"框架（看多/看空/震荡） | 验证或修正 `current_stage` | 开盘后用这三个变量验证 |
| 情景推演（A/B/C） | 对应不同 `pre_condition` 分支 | 识别当前是哪种情景 |
| 机构研报/产业新闻 | 补充 `industry_chain` 中待研究的环节 | **记下来等回调研究**，不追 |
| "如果XX→则XX"的条件句 | 更新 `pre_condition` 的条件分支 | 条件触发后再评估 |

---

## 第二层：扩散产业链找低位 → stock_pool

### 核心原则：永远向前置一步

```
UP点名A（已涨了）
    ↓
你的工作：找A的产业链上下游 —— 谁还没涨？
```

### 产业链定位

```yaml
# config/stock_monitor/stock_pool.yaml
stocks:
  - code: 000636.SZ
    name: 风华高科
    direction: mlcc_super_cycle
    chain_position: midstream  # upstream | midstream | downstream
    human_note:  # 不进LLM，仅人类参考
      date: '2026-06-15'
      type: signal_confirmation  # direction_call | signal_confirmation
      context: "MLCC情绪核心候选，6/15涨停确认"
    entry:
      primary_zone: [57.8, 62.7]  # 介入价格区间
      method: "涨停回踩法"      # 方法说明
      hard_stop: 54.0            # 硬止损价
    pre_condition:                # LLM终判用入场条件
      sector_diverged: true      # 板块必须分歧过
      market_actionable: true    # 大盘必须可操作
      no_consecutive_limit_up: true  # 非连续涨停中
```

### 从6/16复盘看扩散示例

```
复盘点名的板块/标的        →    扩散到（谁还没涨？）
光芯片（永鼎涨停）         →    光芯片衬底：有研新材、云南锗业
MLCC（风华涨停）          →    上游陶瓷粉体：国瓷材料、超细镍粉：博迁新材
PCB油墨（容大感光彩涨）    →    PCB上游：生益科技、华正新材
玻璃基板（台积电首披露）   →    沃格光电（603773主板可交易）
3D打印（华曙高科+14.94%） →    主板无对标，跳过（688不能买）
液冷（订单业绩之年）       →    设备端（日本机床瓶颈）+ 组装方
```

---

## 第三层：条件单——三重过滤

### 错误的旧逻辑

```
价格入 entry_zone → 提醒买入
```

### 正确的条件链

**三个前置条件必须同时满足**才能考虑入场：

```
条件1：大盘可操作窗口
    └── 全A非破位 + 量能>2.5万亿 + 非清仓信号期
条件2：板块出现首次分歧
    └── 连续上涨后1-2日回调（不是退潮） + 缩量企稳
条件3：个股价格到位
    └── 价格在 primary_zone 内 + 缩量 + 非连续涨停中
```

### 从6/16复盘提取的条件示例

> **"接下来最好的节点，是AI科技出现第一次分歧回落的尾盘。"**
>
> → 条件1：大盘OK（全A 2连阳抬升底部）✅
> → 条件2：AI科技连续小高潮 → **等第一次分歧**
> → 条件3：等分歧尾盘再评估具体个股价格
> → 操作：分歧前不建仓，分歧尾盘评估后决定

### 等不到怎么办

**这是正常情况。** 强势主线经常不给充分回调就直接走二波。

```
UP点名的票不给回踩 → 放弃龙头 → 切产业链上游（还没涨的）
上游也不给回踩 → 放弃这个方向 → 等UP提下一个方向
宁可错过，不可追高
```

---

## 每日操作清单

### 复盘后（如22:00-23:00）

- [ ] 读"盘面定调"，判断情绪阶段 → 更新 `pre_condition.market`
- [ ] 读"重点板块"，识别2-3个主线方向 → 更新 direction_pool（新增或改 current_stage）
- [ ] 读"扩散路径/明日展望"，找还没涨的产业链环节 → 更新 industry_chain
- [ ] 更新 stock_pool：为低位标的设 entry_zone
- [ ] 检查已有持仓是否与UP最新判断一致

### 早盘前（8:30-9:00）

- [ ] 读"三看"框架 → 验证或修正 direction_pool 的 `current_stage`
- [ ] 检查昨晚设的 entry_zone 是否因隔夜消息需要调整
- [ ] 对每个方向，确认今天是"可以买"还是"继续等"
- [ ] 记下今日验证变量（什么信号确认/什么信号推翻）

### 盘中（监控引擎自动处理）

- 引擎监控 `pre_condition` 三个条件的满足情况
- 条件全满足时提醒，不全满足时静默

---

## Config 字段变更纪律

修改 `direction_pool.yaml` 或 `stock_pool.yaml` 后必须同步更新所有下游消费者：

```
config 变更
    ├── 更新对应的 strategy_pack.yaml（如有依赖条件）
    ├── 验证 format_agent_json_context() 能正确读取新字段
    ├── 重启 Qing-Agent（gunicorn reload）
    └── 记录变更到 daily_state.json
```

字段必须有一级代码消费方，见 `docs/config-data-contract.md` 完整映射表。

---

## 关键参考

- `docs/UP-usage-learning-guide.md` — 完整方法论（含5步发现法、产业链调查方法）
- `docs/UP-daily-verification-0608-0616.md` — 实证验证数据
- `docs/qing-agent-config-reconstruction.md` — direction_pool + stock_pool 架构设计
- `docs/config-data-contract.md` — 字段消费端映射和LLM可见性
- `config/stock_monitor/direction_pool.yaml` — 方向池（当前12个活跃方向）
- `config/stock_monitor/stock_pool.yaml` — 标的池（50+主板可交易标的）
- `config/stock_monitor/strategy_pack.yaml` — 监控策略包
