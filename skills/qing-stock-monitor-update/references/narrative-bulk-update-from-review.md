# 从复盘文档批量更新 narrative 的参考手册

> 当用户要求"把复盘文档的市场数据提取到 watchlist 对应票的 technical_narrative 和 sector_narrative"时的执行参考。

---

## 数据提取清单（从复盘文档）

### 必须提取的数据

| 数据类型 | 来源位置 | 示例 |
|---------|---------|------|
| 指数收盘 | "附：今日关键数据速查"表 | 上证 4055.91(-0.31%) |
| 板块表现 | "提醒质量评估"中的进攻/防御组 | CPU链分化，ST得润+5%但万通-2.1% |
| 个股数据 | "附：今日关键数据速查"表 | 万通发展 15.83(-2.10%) |
| 持仓盈亏 | "漏报检查"中的持仓表 | 万通发展浮亏-2.3% |
| 板块强弱 | "误导性提醒"中的进攻组均涨幅 | 11:00 进攻组均涨幅 -1.246% |

### 可选提取的数据

- 去重合理性：被去重压制信号数（用于判断是否需要调整去重窗口）
- 漏报原因：positions.yaml 配置缺失、sector_groups 滞后、cron 执行失败
- 下一交易日观察条件：3条核心观察条件

---

## narrative 字段内容模板

### technical_narrative

```yaml
technical_narrative:
  trend: "{日期}{涨跌幅}{定性描述}"
  volume_character: "{放量/缩量/正常成交}{上涨/下跌/震荡}"
  key_levels:
  - "支撑：{价格}"
  - "压力：{价格}"
  pattern: "{技术形态}"
  note: "{日期}收盘{价格}{关键状态}，{板块context}"
```

**内容规范**：
- `trend` 必须包含具体日期和涨跌幅数字
- `note` 必须包含收盘价，持仓票必须包含成本线和盈亏比例
- `key_levels` 中的支撑/压力必须基于当日高低点和近期平台

### sector_narrative

```yaml
sector_narrative:
  relative_strength: "{板块组内位置}"
  money_flow: "{主力/游资/稳健资金}{流入/流出}"
  leader_follower: "{板块龙头/跟随/独立走势}"
  catalyst: "{催化事件}"
  risk: "{具体风险描述}"
```

**内容规范**：
- `relative_strength` 必须包含该票在所属板块组内的相对位置
- `risk` 必须包含当日观察到的具体风险，不能写泛泛的"市场风险"
- `money_flow` 基于当日成交量变化和板块资金流向判断

---

## 常见错误与修复

### 错误 1：换行缺失导致 YAML 解析失败

**症状**：`yaml.safe_load()` 返回 `technical_narrative: None`

**根因**：
```yaml
    invalidation_setup:
    - AI电源链整体走弱    technical_narrative:  # ← 缺少换行
```

**修复**：
```yaml
    invalidation_setup:
    - AI电源链整体走弱
    technical_narrative:  # ← 正确：有换行
```

### 错误 2：只更新了票的一个 theme 位置

**症状**：同一票在 `upstream_price_increase` 中更新了，但在 `mlcc_passive_cycle` 中仍是旧数据

**根因**：只按 `code` 匹配，未检查该票在哪些 theme 中出现

**修复**：先用 `grep -n "code: 000636.SZ"` 找出所有出现位置，逐一更新

### 错误 3：today_snapshot 数据与复盘文档不一致

**症状**：`today_snapshot.market_summary` 中的指数数据与复盘文档不同

**根因**：只更新了 narrative，忘记同步更新 today_snapshot

**修复**：将 today_snapshot 中的 market_summary、stocks_with_data、overall_action 全部用复盘文档数据重写

---

## 用户验证习惯（重要）

**用户不信任 AI 对文件位置的声明**，会通过 SSH 登录服务器直接检查文件。执行写入操作后：
1. 主动提供文件的绝对路径和关键内容摘要
2. 建议用户运行 `ls -la <路径>` 和 `git diff --stat` 自行验证
3. 不要假设用户会信任"已写入"的声明

---

## 快速验证命令

```bash
# 验证 YAML 格式
cd ~/learning-investment-strategies
python3 -c "import yaml; yaml.safe_load(open('config/stock_monitor/watchlist.yaml'))"

# 检查特定票的 narrative
grep -A 20 "code: 600246.SH" config/stock_monitor/watchlist.yaml | grep -E "trend:|relative_strength:"

# 检查 today_snapshot 数据
grep -A 5 "market_summary:" config/stock_monitor/watchlist.yaml

# 用户自助验证（推荐提示用户执行）
ls -la config/stock_monitor/watchlist.yaml
git diff --stat config/stock_monitor/
```
