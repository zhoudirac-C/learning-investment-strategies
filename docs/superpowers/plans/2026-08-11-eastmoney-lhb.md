# 东财龙虎榜日榜接入 实施计划

对应 spec：`docs/superpowers/specs/2026-08-11-eastmoney-lhb.md`（2026-08-11 已确认）
创建：2026-08-11

## 任务

- [x] T1 `src/investment_engine/eastmoney_lhb.py`：`_get_json`（urllib，可 monkeypatch）/
  `fetch_daily_list` / `fetch_seats` / `fetch_lhb`（组装+容错+sleep 0.15s）/ `save_lhb`
  + `tests/investment_engine/test_eastmoney_lhb.py`（fake HTTP：清单解析、席位解析、
  空披露容忍、单股席位失败不阻断、落盘往返）
- [x] T2 `scripts/eastmoney_lhb_fetch.py`（--date/--out-root/--force，幂等，退出码 0/1）
  + `tests/investment_engine/test_eastmoney_lhb_fetch.py`（编排：成功、幂等跳过、失败退出码）
- [x] T3 `blindtest/dataset.py`：`build_daily_pack` 加 `em_root=None`，`_load_lhb` 东财优先
  （source 标注、|net_amt| 排序、条目/席位封顶）、KPL 回退、双缺失标注；
  `test_dataset.py` 增补三种情形
- [x] T4 cron 17:50（改前备份 crontab）+ spec 验收项 3/4 实测（08-10 实拉核对 70 只、
  拼包 source=eastmoney 且防泄漏过）+ 全量 pytest + 文档收尾（spec 状态转 done）

## 执行记录

| 任务 | commit | 结果 |
|---|---|---|
| T1 | f9a7949 | 6 passed |
| T2 | 2b24410 | 3 passed |
| T3 | 11dc0a9 | 全量 192 passed |
| T4 | 见本次 commit | 08-10 实拉 70 只与东财网页口径一致；拼包 source=eastmoney、20 条目入包、prompt 63,014 字符、防泄漏断言通过；crontab 已加 17:50（备份 /tmp/crontab.bak.20260811b） |
