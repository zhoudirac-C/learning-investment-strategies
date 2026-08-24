---
date: 2026-08-24
type: pattern-patch
status: implemented（2026-08-24，见下方实施记录）
source: 2026-08-24 毕业判分方向命中率 28.6%（n=14）逐样本归因
related:
  - logs/graduation-2026-08-24.md（毕业判分：方向超额 28.6% vs 线 60%）
  - logs/m1-lp-ab-20260815.md（方向指标在单边窗口饱和，本提案不解决该口径问题）
---

# 盲判优化提案：方向同簇限选（相关簇分散）

## 模式内容

收盘盲判 directions 输出（每日 2 条）**不得属于同一相关簇**。簇的判定依据 =
是否共享同一核心催化 / 同一产业链景气（行情同涨同跌），而非字面行业分类。

当前方向池（`config/stock_monitor/direction_pool.yaml`，45 方向）参考分簇：

- **C1 AI 硬件链**（PCB/材料/光通信/算力/半导体/存储/消费电子/数据中心电源）：
  pcb_ai_chain、ccL_resin_upstream、copper_foil_hvlp4、tungsten_pcb_drill、
  cipb_power_substrate、mlcc_super_cycle、aramid_ai_fiber、optical_communication、
  switch_800g_domestic、computing_network_super_node、waic_supernode_catalyst、
  memory_nor、chip_specialty、semiconductor_silicon_wafer、electronic_gas_wf6、
  leadframe_upcycle、equipment_packaging_catchup、sk_hynix_adr、edge_ai_endpoint、
  aidc_power_supply
- **C2 能源电力**：green_power_ai_electric、photovoltaic_low_recovery、
  lithium_battery_separator_upcycle
- **C3 大宗周期**：coke_coal_upcycle、copper_aluminum_shortage、small_metal_chemical、
  upstream_scarce_price_rise、polyester_filament_refill、tire_offshore_transfer
- **C4 医药**：pharmaceutical_innovation、ai4s_pharma
- **C5 金融**：securities_bottom、broker_finance
- **C6 消费农业**：pig_farming_hedge、cheese_domestic_sub
- **C7 主题事件/其他**：commercial_aerospace、robot_observation、shipbuilding_boom、
  typhoon_drainage、film_industry_event、mid_report_performance、kcb_ai_policy、
  ai_applications_rotation、ai_equity_investment、cybersecurity_mapping

自由文本方向名（如「5G概念」「存储芯片」）按语义归簇（此二例均属 C1）。

## 触发与动作

- 触发：生成 directions 时，两条候选方向属于同一簇。
- 动作：保留 reason 证据更强的一条；第二条从其它簇中选当日证据最强者。
  若其它簇无合格候选，允许只输出 1 条并在 reason 注明「同簇限选，无其它簇合格候选」。
- reason 中需用一句话写明簇归属判断（如「同属 C1 AI 硬件簇，取证据更强者」）。

## 证据

2026-08-07~08-14 已结算 12 个方向样本逐条拆解（`evals/shadow/predictions/`），
总命中率 33.3%（毕业判分口径 28.6%，n=14 含 08-13/08-14 第二条记录）：

- **簇内集中暴露**：10/12 样本属 C1 AI 硬件簇。08-12 同选 pcb/光通信/存储、
  08-14 同选 5G/存储，两日该簇整体回调，**5 个样本全 miss**——同一赌注被重复计票。
- **剔除这两日**，其余样本命中率 4/7 ≈ 57%，接近 60% 毕业线。
- **边际 miss 占比高**：|超额|<1.5% 的贴线样本 5 例（-0.1/-0.6/-1.3/-1.4/-1.7），
  二元命中率对其无区分度；均值口径 12 样本平均超额 +0.08%——无 edge 但非系统性失效。
- 结论：当前低分主因是同簇集中暴露在回调日被放大计票，而非逐条方向逻辑失效。

## 证伪

- 若后续窗口反复出现「同簇双选且两条均显著跑赢基准」（≥3 次），说明强趋势行情中
  同簇集中贡献正收益，本规则应降级为「趋势市豁免」或撤回。
- 窗口验证期内若「簇分散日」命中率不高于「同簇集中日」，说明分散无收益，本提案关闭。

## 数据需求

无新通道。方向池现有 45 方向已可按上表分簇；需在 prompt 中给出自由文本方向名的
归簇示例（附 1~2 个即可）。

## validation

窗口验证：自应用日起 10 个交易日内逐日记录 directions 簇分布：

1. 同簇双选出现次数（目标 0，除非注明「无其它簇合格候选」）；
2. 到期结算后比较「簇分散日 vs 同簇集中日」的方向超额命中率；
3. ≥8 天合规且分散日命中率不低于集中日 → 转正挂入 prompt 规则；
   合规率 <50% 或分散日显著更差 → 回滚关闭。

## 实施记录（2026-08-24）

1. **prompt 规则27**：盘后 `blindtest/replay.py` SYSTEM_PROMPT 与盘前
   `shadow/premarket.py` PREMARKET_SYSTEM_PROMPT 同步加入规则27（同簇限选 +
   参考分簇表 + 自由文本归簇示例）；两路共用 validate_result，规则必须对称，
   否则确定性校验会打回模型从未被告知的规则。
2. **确定性校验**：`validate_result` 新增规则27 检查——池内 id 精确归簇、
   自由文本按高精度别名归簇（长词优先，防「铜箔」被「铜」截胡），同簇多选即违规
   打回重写；无法归簇的自由文本不拦（宁漏不误）。违规记录随 `validation`
   字段落盘 predictions，直接喂给本提案 validation 的合规率统计。
3. **版本**：PROMPT_VERSION v10.1 → v11（premarket 共享同一常量）。
4. **测试**：`test_validate_result.py` 新增 TestDirectionClusterLimit（6 例，
   含 08-12/08-14 真实违规回归）；`test_daily.py`/`test_premarket.py` 版本断言
   与规则27 关键词断言。tests/investment_engine 431 passed（
   test_qing_review 的「退潮期（调整期）」未映射失败为 cron 数据文件新增标签
   所致，与本改动无关，另行处理）。
5. **冻结**：自 v11 起 prompt 冻结至窗口验证结束（10 个交易日，2026-09-08 前后），
   届时按 validation 条款验收转正或回滚。
