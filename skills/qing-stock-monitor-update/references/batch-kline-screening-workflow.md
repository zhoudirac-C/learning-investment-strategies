# 批量K线筛选 + 介入点生成工作流

> 2026-06-09 首次实践。当用户问"推荐买入方向/标的"时，不应仅依赖 Qing-Agent 文字描述，应结合 60 日 K 线数据做量化筛选。

## 触发条件
- 用户问"可以买入的方向和标的"
- 用户要求"分析哪些票调整充分、位置低"
- 根据 UP 方向推荐生成具体 entry_points

## 四步工作流

### Step 1: 拉取 60 日 K 线
使用腾讯 K 线 API（复权日线），批量拉取时每只票间隔 0.3s：
```
url = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=sh600031,day,start,end,60,qfq"
```
返回 JSON → data[code]["qfqday"] → 每行 [date, open, close, high, low, volume]

### Step 2: UP 标准筛选
按 UP "低位+业绩+方向逻辑"过滤：
- 60日回撤 >30% → 🔥低位, 20-30% → 🟡中低位, <10% → 🔴高位排除
- UP 推荐的非科技方向（6/4+6/9）
- 主板-only（sh6/sz0）
- 排除 UP 明确规避的（科技、有色、机器人）

### Step 3: Qing-Agent 分析
将筛选结果（代码+现价+回撤%+位置标记）喂给 `/chat`，要求按 UP 逻辑排序。

### Step 4: 生成 entry_points
写入 `strategy_pack.yaml → entry_points`，必填字段：
- status/opportunity_pattern/entry_zone/entry_trigger/position_ratio
- invalidation/claim_basis/odds_analysis（upside_pct/downside_pct/odds_ratio）

### Step 5: 更新 watchlist
批量追加新标的到对应 theme 或新建 theme，`validate_config.py` 验证。

## 关键纪律
1. UP 全局纪律优先：突破 4120 前 entry_points 标 status=active 非 triggered
2. 赔率 < 2:1 不配置（不对称机会原则）
3. 不编造价格：entry_zone 基于实际 K 线高低点
4. 高弹性控仓：回撤>30% 的票仓位 0.5-1 成
