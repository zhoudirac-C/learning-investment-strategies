# Qing-Agent 60日K线拉取不可靠 → 本地批量拉取兜底

## 问题

Qing-Agent v4 `/chat` 端点理论上会对含 6 位代码的消息自动拉取 90 日 K 线（见 `references/qing-agent-chat-realtime-data.md`）。但实际可靠性不足：

- **2026-06-09 实测**：18 只标的（全部上海/深圳主板），只有 三一重工(600031) 成功拉取到 K 线数据
- 其余 17 只全部拉取失败（无声降级，无 K 线数据注入 prompt）
- 根因不明，可能是腾讯 K 线 API 的格式兼容性问题

**结论**：不要依赖 Qing-Agent 自动拉取 K 线。应先用本地脚本批量拉取，再喂给 Qing-Agent。

## 解决方案：本地批量拉取 + 结构化文本注入

### Step 1：用 `batch_kline_analysis.py` 拉取

```bash
cd ~/learning-investment-strategies
PYTHONPATH=src .venv/bin/python scripts/batch_kline_analysis.py
```

该脚本：
- 从 `STOCKS` 字典读取标的列表（代码→名称映射）
- 调用腾讯 API 拉取实时行情 + 60 日 K 线
- 计算 60 日回撤幅度、MA20、高低点
- 输出 JSON（等待后处理）

### Step 2：也可直接用 execute_code 内联拉取

当脚本导入复杂时（如 Python path 问题），直接在 `execute_code` 中写内联代码拉取，使用：
- 实时行情：`http://qt.gtimg.cn/q=sh600031,sz000425,...`（GB2312 编码）
- 60日K线：`https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=sh600031,day,2026-04-01,2026-06-09,60,qfq`
- K 线格式：`qfqday` 数组，每元素为 `[date, open, close, high, low, volume]`

**关键注意**：K 线 API 的 code 参数必须带 `sh`/`sz` 前缀（如 `sh600031`），而实时行情 API 的 key 返回的是纯数字（无前缀）。

### Step 3：结构化文本注入 Qing-Agent

将回撤数据按 UP 选股逻辑分组（🔥低位回撤>30%、🟡中低位 20-30%、🟠中位 10-20%、🔴高位 <10%），作为纯文本注入 Qing-Agent 的 `/chat` message。

示例格式：
```
以下是18只主板标的的60日K线回撤数据（已通过腾讯API拉取）。
请基于UP选股逻辑'找低位+调整充分+有业绩的方向'进行分析。

🔥低位(回撤>30%)：
600893 航发动力 | 39.33 | -36.9% 🔥低位
000534 万泽股份 | 31.38 | -34.1% 🔥低位
...

🟡中低位(回撤20-30%)：
002709 天赐材料 | 46.51 | -27.8%
...

🟠中位(回撤10-20%)：
600031 三一重工 | 19.56 | -13.2%
...

🔴高位(回撤<10%)：
601100 恒立液压 | 119.20 | -3.0%
```

### 为什么这比让 Qing-Agent 自己拉更可靠

1. **确定性**：腾讯 API 直接调用，不经过 Qing-Agent 的代码路径
2. **可见性**：拉取结果可预先验证（看 K 线条数、是否有异常值）
3. **效率**：18 只票批量拉取约 6 秒（含 0.3s 频率控制），Qing-Agent 逐只拉可能更慢
4. **分类注入**：按回撤分四档，让 Qing-Agent 直接在"筛选"阶段开始分析，而非在"拉数据"阶段浪费时间

## 适用场景

- 用户要求基于 UP "找低位"逻辑筛选多个方向的多只标的
- Qing-Agent 返回"无 K 线数据，无法分析"时
- 需要批量对比 10+ 标的的 60 日回撤数据时
