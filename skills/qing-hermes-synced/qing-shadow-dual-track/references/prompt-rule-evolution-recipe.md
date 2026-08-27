# 盲判 Prompt 规则演进操作手册（v9→v10→v10.1 实战沉淀）

来源：2026-08-21 三次演进（规则25 宏观三条件 / 规则23b 催化兑现覆盖 / 规则26 点位幻觉校验 + factcheck 反向提取）。

## 演进流程（每次加规则的固定套路）

1. **根因定位**：盲判 vs UP 对比（或 fact_errors）→ 判定缺口类型：数据源缺失（不可纯 prompt 解）/ 推理模式未覆盖（走提案制）/ 规则优先级瑕疵 / 契约表达位不足。
2. **TDD**：先在 `tests/investment_engine/test_validate_result.py`（或对应测试文件）写失败测试，Red 确认后实现。
3. **三层实现**（机械校验类规则缺一不可）：
   - prompt 规则正文：`src/investment_engine/blindtest/replay.py` 的 SYSTEM_PROMPT 末尾追加「N. 规则名：触发条件 + 必须做什么 + 禁止什么」；
   - 机械校验：模块级 `_XXX_HINTS` 词元组（**必须在模块级定义，勿插进函数体**——曾两次把常量误插函数内导致 IndentationError）+ `validate_result()` 内的违规检测块（pack 缺数据时跳过 = 不强制）；
   - 版本号：`PROMPT_VERSION` bump，并同步更新 `tests/investment_engine/test_daily.py` 和 `test_premarket.py` 里钉版本的断言（否则全量测试必挂这俩）。
4. **真实数据回归**：用当日真实 prediction JSON + 真实 pack 结构跑一次校验函数，验证「该抓的抓到、不该抓的不误报」。误报时收紧过滤词（如 factcheck 反向提取首版误报「但昨日涨停」「上方且涨停」，加连接词包含过滤后归零）。
5. **提交**：只 add 相关文件；skill 文档同步版本说明。

## 已知坑

- **factcheck `_CLAIM_TMPL` 用 `.format(name=...)`**：模板里量词必须写 `{{0,10}}` 双花括号转义，改成正则字面量 `{0,10}` 会 KeyError: '0,10'。
- **机械校验的豁免设计**：规则15 成交额阈值有台阶锚定豁免（±7%）、规则26 点位校验有量能语境豁免（文本含亿/万手/家/% 则跳过）——每条硬规则都要想清楚合法表述长什么样，否则 retry 循环打不过。
- **prompt 规则编号顺序**：插入新规则时用 patch 替换整段，曾出现「25 排在 24 前」的乱序。

## 全量测试跑法

`pytest tests/ --ignore=tests/chan_engine` 约 700 用例需 **16 分钟**，前台 60s/500s 必超时——必须 `terminal(background=True, notify_on_complete=True)` 跑，结果重定向到文件后查尾部。`tests/chan_engine/test_adapter_chanpy.py` 因缺 `Chan` 模块收集报错为预存问题，排除即可。预存失败基线（2026-08-21）：qing_review 未映射标签、buy_signal_e2e、pre_fetch_klines×3（本机 cache ready 触发 SKIP），均与盲判无关。

## 版本历史速查

| 版本 | 内容 |
|---|---|
| v8 | 规则18-22 试点前基础 |
| v9 | UP 五条推理思路试点 + 规则18机械化 + volume_series |
| v10 | 规则25 宏观三条件（宏观vs AI证伪定性）+ 规则23b 催化兑现覆盖 |
| v10.1 | 规则26 指数点位幻觉校验（±10% 容差）+ factcheck 反向提取幻觉个股声明 |
| v11 | 规则27 方向同簇限选（C1-C7 分簇表，2026-08-24 方向聚簇提案落地）——当前版本 |
