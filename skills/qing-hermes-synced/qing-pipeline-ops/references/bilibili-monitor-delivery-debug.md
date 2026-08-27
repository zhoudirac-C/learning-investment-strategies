# B站监控投递失败排查（2026-08-04 实战）

## 场景

用户问"今天的 bilibili 早盘动态有拉取到吗？没有微信没有发消息"。
B站监控 cron（job 46b29d1607b4，`run_bilibili_notify.sh` watchdog，每 5 分 9-14/21-23 点）在跑且 `last_status: ok`，但 `sources/original/bilibili/` 下没有当日文件。

## 三步定位

1. **先查抓取侧**：`ls sources/original/bilibili/ | grep <日期>`。无文件 ≠ 没抓到——先看 state 再下结论。
2. **查 cron 侧**（关键）：
   - `~/.hermes/cron/output/<jobid>_<ts>.txt` — cron 完整输出存档（no_agent 模式的 stdout）
   - `~/.hermes/logs/agent.log` 与 `~/.hermes/logs/errors.log` 中 `cron.scheduler` / `gateway.delivery` 行
3. **判定**：agent.log 出现 `delivery error: Weixin send failed: iLink sendmessage rate limited; cooldown active for 30.0s` → **抓取成功、投递失败**。job 状态仍显示 ok，消息被静默丢弃。

## 核心事实

1. **抓取成功 ≠ 投递成功**。watchdog 输出非空 → Hermes 投递微信；iLink 限流（`sendmessage rate limited`，cooldown 30s）时投递失败但 `last_status` 仍是 ok——静默丢消息，用户无感知。日志还会出现 `falling back to standalone`（兜底路径也可能失败）。
2. **B站列表 API 发布后短时延迟**：UP 09:13 发布，09:18 cron 轮次 SILENT（列表 API 未返回新动态），09:23 轮次才抓到（输出 5263 字符）。watchdog 每 5 分钟一轮，下一轮会补上——**发布后 5 分钟内 SILENT 不是故障**。
3. **空 SESSDATA 列表错位**：`fetch_dynamic_list` 用空 sessdata 也返回 12 条 items，但列表错位——第一条停在旧日期，看不到最新动态。用正确 sessdata 才能看到新动态。排查"没抓到"先确认 `~/.hermes/bilibili_sessdata.txt` 存在且非空（监控脚本从该文件读，env `BILIBILI_SESSDATA` 优先）。
4. **state 文件** `~/.hermes/bilibili_up_state.json`：`processed_ids` / `last_dynamic_id` 已包含新 id → 说明脚本已处理过（抓取侧 OK），问题在投递层。注意 state 不含 sessdata（单独文件存）。

## 手动补抓流程

```python
import sys
sys.path.insert(0, '/home/ubuntu/.hermes/scripts')
from fetch_bilibili_up_v2 import (fetch_dynamic_list, fetch_dynamic_detail,
                                  fetch_up_comment, save_dynamic_to_file)
sess = open('/home/ubuntu/.hermes/bilibili_sessdata.txt').read().strip()
data = fetch_dynamic_list('1420210197', sess)
item = [it for it in data['data']['items'] if it['id_str'] == did][0]
detail = fetch_dynamic_detail(did, sess)
path = save_dynamic_to_file(item, '1420210197', did, detail_data=detail,
                            is_only_fans=True, sessdata=sess)
```

注意：
- 手动 `save_dynamic_to_file` 会**覆盖** cron 已存的同名文件（mtime 变新）——排查时序以 cron output 时间戳为准，别被文件 mtime 误导。
- **`_1` 重复文件**：若 cron 已先保存同名文件，手动补抓（或第二次 cron 轮次）会生成 `..._1.md` 副本（内容相同）。index.md 引用的是不带 `_1` 的版本，补抓后检查 `ls sources/original/bilibili/ | grep <日期>` 有无 `_1.md`，有则删除，避免双份入库。
- `fetch_up_comment` 可能抛 `'NoneType' object is not iterable`，不影响主体保存。
- `module_author.pub_ts` 可能是 str，需 `int(ts)` 转换再 fromtimestamp。
- 列表 API 返回结构：`data['data']['items']`，每条 `id_str` / `type`（`DYNAMIC_TYPE_ARTICLE`=专栏）/ `modules.module_author.pub_ts` / `modules.module_dynamic.desc`。

## 其他

- 手动校验内容完整性：`read_file` 读保存的 md，确认 frontmatter + 原文完整。
- 投递失败后补发：直接用文本把核心内容推给用户即可；根治方向是监控脚本加重试或投递失败告警。
