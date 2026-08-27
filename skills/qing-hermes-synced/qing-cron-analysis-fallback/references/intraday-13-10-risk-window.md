# 13:10 午后风险窗口分析 — 数据源速查与报告结构（2026-08-06 实测）

A 股 13:10 午后风险窗口 cron — 与 10:00 盘面确认、14:00 午盘监控、14:50 尾盘监控、17:00 复盘并列的盘中分析时点。任务框架固定为 4 部分：
1. 午后开盘15分钟走势判断
2. 早盘回调/反弹延展性评估
3. 下午重点观察指标
4. 操作提示（条件性建议，非买卖指令）

---

## 数据源速查（本会话实测可用）

### 1. 指数/个股实时行情 — Tencent qt.gtimg.cn ★★★★★（首选）
```
curl -s "https://qt.gtimg.cn/q=sh000001,sz399001,sz399006,sh000688,sh000300,sz002812" | iconv -f GBK -t UTF-8
```

**⚠️ 字段位置（2026-08-27 13:15 实测校准）** — 之前版本标注有误，以下为准：

| 字段索引 | 含义 | 备注 |
|---------|------|------|
| 1 | 名称 | GBK 编码，可能有乱码 |
| 2 | 代码 | 纯数字 |
| **3** | **最新价（现价）** | ← **不是字段3=最新价，是字段3**（之前误写"字段3=最新价"） |
| **4** | **今开（开盘价）** | ← 之前误标为"昨收"，**已修正** |
| **5** | **昨收价** | ← 之前误标为"今开"，**已修正** |
| 6 | 成交量(手) | |
| 7 | 内盘 | |
| 8 | 外盘 | |
| **30** | **时间戳** | 格式 `YYYYMMDDHHmmss`，如 `20260827131518` |
| **31** | **涨跌额**（元） | |
| **32** | **涨跌幅%** | 含百分号或纯数字，需 `.strip('%')` |
| **33** | **最高价** | |
| **34** | **最低价** | |
| 35 | 成交明细 | 格式 "最新价/成交量/成交额"，含/分隔 |

**推荐解析方式**：字段分隔符是 `~`；用 Python 解码 `gbk` 而非 `GB2312`（gbk 是 superset，覆盖率更高）：
```python
import re
with open('/tmp/raw.txt','rb') as f:
    data = f.read().decode('gbk', errors='replace')
for line in data.split('\n'):
    m = re.match(r'v_(\w+)="(.*)";?', line)
    if not m: continue
    fs = m.group(2).split('~')
    if len(fs) < 35: continue
    cur=float(fs[3]); opn=float(fs[4]); pre=float(fs[5])
    # 高/低/涨跌% 取自 33/34/32
```

- 本会话（2026-08-27 13:15）一次调用即全部成功，19 个标的（10 指数 + 9 持仓品种）全部解析成功。
- **陷阱**：脚本层 `fetch_quotes_with_fallback(targets)` 的签名是 `targets: dict[str,str]`（code→name 映射），不接受 `timeout` 参数；且 TDX 解析器不认识"上证指数"这种中文名会抛 `TdxSymbolError`。直接 curl qt.gtimg.cn 绕过所有框架层问题，是最快路径。

### 2. 板块涨跌排名 — Tencent mktHs/rank ★★★★（东财 push2 失效时的可靠替代）
```
# 涨幅榜
curl -s "https://proxy.finance.qq.com/ifzqgtimg/appstock/app/mktHs/rank?l=20&p=1&t=01/averatio" -H "Referer: https://gu.qq.com/"
# 跌幅榜（d=down 参数）
curl -s "https://proxy.finance.qq.com/ifzqgtimg/appstock/app/mktHs/rank?l=20&p=1&t=01/averatio&d=down" -H "Referer: https://gu.qq.com/"
```
返回 JSON `data[].bd_name`（板块名）+ `bd_zdf`（涨跌幅）+ `nzg_name`（领涨股）。
本会话东财 push2 clist 连续失败（`Remote end closed connection` / 空响应），此接口稳定可用。

### 3. 涨停/跌停/炸板池 — EastMoney push2ex ★★★★★（情绪数据）
```
# 涨停池（含连板分布！）
curl -s "https://push2ex.eastmoney.com/getTopicZTPool?ut=7eea3edcaed734bea9cbfc24409ed989&dpt=wz.ztzt&Pageindex=0&pagesize=100&sort=fbt%3Aasc&date=20260806"
# 跌停池
curl -s "https://push2ex.eastmoney.com/getTopicDTPool?ut=7eea3edcaed734bea9cbfc24409ed989&dpt=wz.ztzt&Pageindex=0&pagesize=50&sort=fund%3Aasc&date=20260806"
# 炸板池
curl -s "https://push2ex.eastmoney.com/getTopicZBPool?ut=7eea3edcaed734bea9cbfc24409ed989&dpt=wz.ztzt&Pageindex=0&pagesize=50&sort=fbt%3Aasc&date=20260806"
```
- `data.tc` = 总数（如涨停61家）；`data.pool[].lbc` = 连板数 → 可算连板高度分布（本会话：10板×1, 5板×1, 4板×2, 3板×8, 2板×8, 1板×41）
- `data.pool[].fund` = 封单金额；`n` = 股票名
- 注意：date=YYYYMMDD，ut/dpt 参数固定；这是情绪信号（涨停/炸板/连板）最可靠来源，比从脚本抄更准。

### 4. 全市场涨跌家数 — Sina ★★（本会话 sort 参数失效）
- `https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeStockCount?node=hs_a` → 返回总家数（如 5537），**仅可验证总量**
- `getHQNodeData` 的 `sort=changepercent&asc=0` 参数本会话**失效**（返回全为涨），涨跌家数统计不可靠 → 降级用涨停/跌停池 + 板块排名推断情绪，或直接声明不可得

### 5. 东财 push2 板块榜（常规首选，本会话失败）
`https://push2.eastmoney.com/api/qt/clist/get?...&fs=m:90+t:2&fields=f2,f3,f12,f14&fltt=2&invt=2`
本会话 python urllib + curl 均失败（连接关闭/空响应），重试 3 次无效。**失败时直接切 Tencent mktHs/rank（§2），不要死磕。**

---

## 13:10 分析框架（4 部分）

### 一、午后开盘15分钟走势判断
对比午盘脚本数据 vs 13:15-13:20 实时快照：
- 指数方向（上证/创业板/深成指）、是否守住早盘支撑位
- 涨停/跌停家数变化（退潮 or 维持）
- 核心结论格式："午后没有走 X 也没有走 Y，而是 Z（如缩量阴跌式弱稳）"

### 二、早盘回调/反弹延展性评估
- 早盘热点（脚本主线）午后承接情况：用实时个股价验证（华为链/MLCC/半导体设备逐一核对）
- 判断句式："早盘'等回踩'判断被验证 / 主线内部结构恶化 / X 韧性最强"

### 三、下午重点观察指标
| 指标 | 阈值/信号 |
|------|-----------|
| 指数支撑 | 上证/全A 关键位（如 3864/5833），触及次数 |
| 权重拖累 | 单日大跌权重股（如宁德 -4.91%）是否收窄 |
| 量能 | 是否守住 3.5万亿 警戒线 |
| 情绪 | 高位连板股（10板）午后是否断板 |
| 跷跷板 | 资源-科技切换是否延续 |

### 四、操作提示（条件性建议）
按"情形 | 触发条件 | 建议动作"表格组织，必须含：失效条件 + 纪律红线。**任何基于脚本价格的介入区间，先核对实时价（见 SKILL.md 类型C子模式），不符则声明失效。**

---

## 本会话关键输出特征（可复用）

- 顶部标注数据时间戳（如 13:19-13:20 腾讯实时）
- **数据完整性警告段**：脚本个股价格失真 → 3 个标的全错 → 所有基于脚本价格的操作计划失效 → 以实时价重校准
- 结论前置：4-6 条核心结论，含一条明确的数据质量声明
- 指数支撑/压力、量能、情绪、主线、风险、反向质疑均以实时数据为准重建，不照抄脚本

---

## 2026-08-27 13:15 新补充分析技巧：`开-%` vs `现-%` 回补信号

### 动机

传统盘中分析只看"现-%"（现价 vs 昨收的涨跌幅），忽略了**竞价阶段的信号**。2026-08-27 下午盘面分析中，"竞价低开 → 午后翻红"是关键结构信号，用 `开-%` 与 `现-%` 的差值（回补幅度）可以量化"多头回流强度"。

### 核心公式

```
开-% = (开盘价 - 昨收) / 昨收 × 100   # 竞价/开盘的情绪方向
现-% = (现价 - 昨收) / 昨收 × 100     # 当前实时涨跌幅
回补 = 现-% - 开-%                     # 正 = 多头回流，负 = 空头加剧
```

### 字段来源（qt.gtimg.cn）

- 昨收 = 字段 5（注意：之前版本误标为字段 4，见上方校准）
- 开盘价 = 字段 4
- 现价 = 字段 3
- 最高价 = 字段 33
- 最低价 = 字段 34

### 解读规则

| 信号 | 条件 | 含义 |
|------|------|------|
| **多头反转** | `开-% < 0 且 现-% > 0` | 竞价恐慌被午后资金吃干，真实多头回流 |
| **空头加剧** | `开-% > 0 且 现-% < 0` | 高开低走，主力出货 |
| **弱势延续** | `回补 < -1%` | 比开盘价还弱，继续偏弱 |
| **强势延续** | `回补 > +2%` | 比开盘价强很多，需防冲高回落 |

### 应用示例（2026-08-27 13:15 实测）

| 品种 | 开-% | 现-% | 回补 | 信号 |
|------|------|------|------|------|
| 科创50 | -0.90% | +2.21% | **+3.11** | 最强多头反转 |
| 科创芯片ETF | -1.03% | +3.02% | **+4.05** | 极强多头回流 |
| AI ETF 华富 | -1.10% | +2.20% | **+3.30** | 强反转 |
| 上证50 | -0.01% | +0.47% | +0.48 | 中性偏弱 |
| 恩捷股份 | +0.00% | -1.72% | **-1.72** | 高位出货信号 |

### 操作启发

1. **回补 > +3% 的品种**说明早盘竞价是被错杀，当前是多头的战场 — 但追高需谨慎（科创板+3~4% 时已偏高）
2. **回补 < -1% 的品种**是日内独立走弱信号，即使大盘涨也别碰（如恩捷股份）
3. **回补幅度最大的板块**就是当日最强主线，回补最小的板块是当日最弱方向
4. 这个指标对 ETF 特别有效（ETF 是板块集合信号，比单只股票噪声少）

### 代码模板（可直接复用）

```python
import re
with open('/tmp/tencent_raw.txt','rb') as f:
    data = f.read().decode('gbk', errors='replace')

for line in data.split('\n'):
    m = re.match(r'v_(\w+)="(.*)";?', line.strip())
    if not m: continue
    fs = m.group(2).split('~')
    if len(fs) < 35: continue
    try:
        cur=float(fs[3]); opn=float(fs[4]); pre=float(fs[5])
    except: continue
    opn_chg = (opn-pre)/pre*100
    cur_chg = (cur-pre)/pre*100
    rebound = cur_chg - opn_chg
    # 判断信号
    if opn_chg < 0 and cur_chg > 0 and rebound > 2:
        print(f"{fs[1]}: 多头反转, 回补{rebound:.2f}个百分点")
```
