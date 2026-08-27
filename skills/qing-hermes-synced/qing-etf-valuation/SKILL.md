---
name: qing-etf-valuation
description: |
  ETF/板块估值与选型研究：PE-TTM/动态PE/PEG 计算、子线→ETF proxy 映射、
  ETF 成分查证、按 UP 排序逻辑推导组合。触发词：板块PE是多少、动态PE、
  PEG比较、有没有XX ETF、ETF组合怎么配、光模块/PCB/国产算力ETF。
category: qing
---

# qing-etf-valuation

用户场景链：板块 PE 对比 → 动态 PE/PEG → "有没有光模块/PCB/国产算力/交换机 ETF？" → "按 UP 逻辑给 ETF 组合"。
完整工作流：**估值对比（TTM→动态→PEG）→ 子线→ETF proxy 映射 → 持仓验证 → 组合推导**。

## 数据源接口（按可靠性排序）

### 1. 腾讯行情 qt.gtimg.cn（实时/收盘，含 PE-TTM）— 首选
```bash
curl -s "https://qt.gtimg.cn/q=sz300308,sh600519" | iconv -f GBK -t UTF-8
# GBK 编码必须 iconv / decode('gbk')；支持逗号批量
```
字段（~ 分隔）：`f[3]` 现价、`f[4]` 昨收、`f[31]` 涨跌额、`f[32]` 涨跌幅%、`f[33]` 最高、`f[34]` 最低、`f[37]` 成交额(万)、`f[38]` 换手%、`f[39]` **PE-TTM**、`f[45]` 总市值(亿)。
**idx39 = PE-TTM 已校准**（茅台 20.60 / 工行 7.26，2026-08-14）。前缀：sh6xx/sz0/sz3；ETF sh51x/sh58x/sz15x。

### 2. 东财 datacenter-web：券商一致预期（动态 PE/PEG 数据源）
```bash
curl -s -A "Mozilla/5.0" -H "Referer: https://data.eastmoney.com/" \
  "https://datacenter-web.eastmoney.com/api/data/v1/get?reportName=RPT_WEB_RESPREDICT&columns=SECURITY_CODE,EPS1,EPS2,EPS3,EPS4,RATING_ORG_NUM&filter=(SECURITY_CODE%3D%22300308%22)&pageNumber=1&pageSize=1"
```
- `EPS1`(A 实际) / `EPS2-4`(E 预测) / `RATING_ORG_NUM` 覆盖机构数
- **动态PE = 现价 ÷ EPS2**；增速 = EPS2/EPS1−1；**PEG = 动态PE ÷ 增速百分数**（34÷200.5，不是 ÷2.005）；PEG(CAGR) = 动态PE ÷ (((EPS4/EPS1)^(1/3)−1)×100)
- 机构覆盖 <5 家预测不可靠（剑桥 2 家 PEG 0.06 失真）；25A EPS≤0 剔除（罗博特科）

### 3. 天天基金手机 API：ETF 前十大持仓（成分查证）
```bash
curl -s "https://fundmobapi.eastmoney.com/FundMNewApi/FundMNInverstPosition?FCODE=515880&deviceid=Wap&plat=Wap&product=EFund&version=2.0.0"
# → Datas.fundStocks: [{GPDM 代码, GPJC 名称, JZBL 占比%}]
```
只返回前十大；判断"标的在不在某 ETF"用 grep。旧接口 fundf10.eastmoney.com/FundArchivesDatas.aspx 已 404。

### 4. 东财 searchapi：代码 + ETF 关键词搜索
```bash
curl -s "https://searchapi.eastmoney.com/api/suggest/get?input=<URL编码>&type=14&count=8"
```
push2.eastmoney.com 云 IP 常被反爬（空响应）→ 实时数据一律走腾讯。

## 子线 → ETF proxy 映射表（2026-08-14 收盘实测）

| 目标子线 | 最优 ETF | 权重依据 |
|---|---|---|
| 光模块/CPO 纯度 | 通信ETF国泰 515880 | 新易盛15.6+旭创14.6+天孚6.3+光迅4.0 ≈ 40.5% |
| 光模块+存储 | 创业板AI 159381 | 光模块38.8% + 江波龙8.1% |
| 国产算力芯片 | AI ETF 159819/515070 | 寒武纪10.6+海光8.8 ≈ 19.4% |
| 交换机整机(紫光) | 云计算ETF 516510 / AI华富 515980 | 紫光 5.3% / 3.0% |
| 交换芯片(盛科) | 科创芯片设计 588780 | 盛科 2.8%（唯一含盛科的 ETF） |
| 晶圆制造 | 科创50 588000 / 科创芯片 588200 | 中芯7.4+华虹3.6=11.0% / 中芯7.6+华虹3.2=10.8% |
| 半导体宽基(稳定器) | 半导体ETF国联安 512480 | 兆易7.8+寒武纪7.2+北方华创5.5，成交11.98亿 |

**命名陷阱**：没有"光模块/PCB/半导体零部件 ETF"（searchapi 无结果）只能 proxy；"科创新材料ETF"(588010) 是材料（沪硅/安集/中船特气）不是设备零部件；同名 ETF 跟踪指数不同成分差异大（"AI ETF 含紫光"只有 515980 华富，159819 易方达没有）——必须逐个查证。

## ETF 选型标准流程

1. searchapi 关键词 → 候选 ETF 列表
2. fundmobapi 逐个查前十大 → 目标子线权重合计
3. 腾讯查流动性（成交≥1.5亿可用、≥5亿优）与近期涨幅（追高压力）
4. 剔除：成交<0.5亿（如 517800 0.04亿）、已大涨标的（如 515880 8/14 +3.6%）
5. 组合推导：按用户指定的框架逻辑（见下），不按风险偏好

## 用户偏好（8/16 明确纠正）

- **给 ETF 组合 = 按用户指定的分析框架（UP 排序/主线）配置权重，不是按风险偏好（"波动小"）配置**。用户原话："不是我要波动性小，我要按 UP 逻辑给组合"
- 组合每个成分标注 **UP 逻辑依据**（对应 claim/日期）：515980 30% = 紫光=8/16 证伪条件核心变量；588780 25% = 盛科 8/16 点名"订单转合同"；588200 20% = 晶圆制造=UP 8/14 排序第一
- 用户质疑框架本身（"UP 排序值得投资吗"）→ 用"**方向过滤器 vs 买入信号**"框架：排序定方向（有因果链✅有证伪条件✅）但缺定价锚（"估值合理"没阈值）、缺 P&L 归因 → 必须叠加估值锚（PEG）+ 量价确认（买阴不买阳）+ 分批建仓才是完整投资逻辑
- 结论给**唯一主推组合**，不抛 6 个选项（用户要求"直接给一个组合"）；排除方向要明说（设备整机 = UP 6/30"相对平庸"）

## 估值口径教训

- **TTM PE 与动态 PE 结论可反转**：CPO TTM 中位 128（贵）→ 2026E 动态 66.5 → PEG₁ 0.25（最便宜），因 2026 一致预期增速 166-200%
- 一致预期偏乐观（卖方惯例）；PEG 低基数失真（增速 500%+ 必须标机构数）；中位数与市值加权分开报（罗博特科 PE 1720 污染加权）

## UP 排序 claims 速查（组合推导依据）

- 8/14-022 科技强弱：算力租赁与AI应用 > 硬件；硬件内部国产链 > 海外链
- 8/14-032 半导体分板块：晶圆制造（壁垒最深/久期最优）> 设备零部件（弹性高于整机）> 设备整机（相对平庸，6/30-002-b）
- 8/13-014 存储是"点"；8/16-013 交换机分支新高=反弹转反转验证点，证伪=紫光/华勤不跟
