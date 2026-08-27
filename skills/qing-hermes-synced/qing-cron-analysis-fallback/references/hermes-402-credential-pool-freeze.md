# Hermes cron LLM 层 402: credential_pool 冻结

2026-08-06 实测（17:00 收盘复盘 cron 失败 + 交互会话 16:18-18:30 持续中招）

## 症状
- cron 任务失败: `RuntimeError: HTTP 402: Insufficient Balance`
- 预跑脚本数据完整（龙虎榜/持仓/行情都在），失败发生在 **LLM 生成环节**
- 同一时段**所有**会话都可能中招（交互 gateway + cron），非单任务问题

## 关键诊断（先别下"没钱了"结论）
1. 余额查询: `curl -s https://api.deepseek.com/user/balance -H "Authorization: Bearer $KEY"`
   - `is_available: true` + 余额 > 0 → key 有钱
2. 直接 chat 实测（关键验证，余额 API 与计费状态可能短暂不一致）:
   ```bash
   curl -s https://api.deepseek.com/v1/chat/completions \
     -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
     -d '{"model":"deepseek-v4-flash","messages":[{"role":"user","content":"hi"}],"max_tokens":5}'
   ```
   - 200 → key 本身有效（非流式/流式/大请求都要测，本案例三种都通）
3. 若两者都通过但 Hermes 仍 402 → 查 credential_pool 状态:
   ```bash
   python3 -c "
   import json,time
   auth=json.load(open('/home/ubuntu/.hermes/auth.json'))
   for p,ents in auth.get('credential_pool',{}).items():
       for e in ents:
           print(p, e['last_status'], e.get('last_error_code'),
                 time.strftime('%H:%M:%S',time.localtime(e.get('last_status_at',0))))
   "
   ```
   `last_status: exhausted` + `last_error_code: 402` → key 被池子冻结，后续请求报
   `no available entries (all exhausted or empty)`

## 根因
- DeepSeek API **间歇性**返回 402（计费层抖动，不是真的没钱）——同一 key 同一模型，
  18:33 curl 成功、16:18-18:30 Hermes 持续 402
- Hermes `agent/credential_pool.py` 对任何 402 把 key 标记 exhausted，冻结 TTL：
  401=5min，429/402/其他=1h
- 冻结期内池子拒绝该 key，直到 TTL 到期或手动解冻

## 修复（解冻 key）
1. 备份: `cp ~/.hermes/auth.json ~/.hermes/auth.json.bak_$(date +%Y%m%d_%H%M%S)`
2. 清空 credential_pool 条目错误字段:
   ```python
   import json
   auth = json.load(open('/home/ubuntu/.hermes/auth.json'))
   for e in auth['credential_pool']['deepseek']:
       e['last_status']=None; e['last_status_at']=None
       e['last_error_code']=None; e['last_error_reason']=None; e['last_error_message']=None
   json.dump(auth, open('/home/ubuntu/.hermes/auth.json','w'), indent=1, ensure_ascii=False)
   ```
3. 重新触发 cron: `cronjob action=run`（无需重启 gateway，池子每次从 auth.json 读）
4. 验证输出文件: 新文件无 FAILED 标记、`last_status: ok`

## 排查要点
- config.yaml（`model.api_key` / `providers.deepseek.api_key`）与项目 `.env` 的 key 是同一个——
  比对前缀+长度即可，别打印全量
- 用户视角"没钱了"只是表象，先验证再下结论；但用户说"不用深究"时，尊重指示、
  快速给可执行动作（解冻 + 补跑）
- 备份文件模式 `auth.json.bak_*` 可复用；改完 auth.json 立即生效
