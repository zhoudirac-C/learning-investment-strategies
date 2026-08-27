# 动态提取覆盖检查（"今天有没有动态没提取claim"）

2026-08-06 实测。回答这类问题的标准工作流 + 坑位。

## 工作流
1. 拉今日 B站动态列表（用脚本自己的 fetch 函数，别裸 curl——412）
   ```python
   import sys; sys.path.insert(0, 'scripts')
   from fetch_bilibili_up_v2 import fetch_dynamic_list
   sess = open('/home/ubuntu/.hermes/bilibili_sessdata.txt').read().strip()
   resp = fetch_dynamic_list('1420210197', sess)   # code==0 才成功
   items = resp['data']['items']
   ```
2. 对比 `sources/original/bilibili/YYYY-MM-DD-*.md` 原始文件（下载即留档）
3. 核对 claims 覆盖: 对每条今日动态的 source_path / dynamic_id，
   在 `knowledge/claims/*.yaml` 里 grep
4. git log 权威记录: `git log --oneline --since="YYYY-MM-DD 00:00" | grep 提取`——
   提交信息带"提取N条claims"

## ⚠️ 坑位
- **SESSDATA 在 `~/.hermes/bilibili_sessdata.txt`，不在 .env**
  （`BILIBILI_SESSDATA` env 是空的）——二维码登录把 SESSDATA 写入该文件，
  读取后 `tr -d ' \r\n'` 再传
- 裸 curl feed API 会 412（需完整 cookie 模板，bili_ticket 硬编码会过期）——
  用脚本函数绕开
- **当前 API 版本响应结构**（2026-08 实测）:
  - 动态 ID 在 `items[].id_str`（`desc` 是 None！`desc.dynamic_id` 不存在）
  - `modules.module_author.pub_ts` 是**字符串**，需 `int()` 再 fromtimestamp
  - DRAW 类型动态 `modules.module_dynamic.desc` 为 None，正文在 `major.draw`；
    纯图内容走 OCR（已有 rapidocr 路径）
  - `it.get('modules')` / `it.get('desc')` 可能返回 None → 一律 `or {}` 防御，
    否则 AttributeError 断在中间
- **单日多条 claims 合并在一个 YAML 文件**（claim-20260806-001.yaml 含 18 条
  claims 001-018）——数文件数≠数 claims，要 `grep -c 'id: claim-YYYYMMDD-'`
  文件内部
- 复盘报告/对话里引用的 claim-004 等是**当日短编号**，完整 ID 是
  claim-YYYYMMDD-004，别误判缺失

## 漏提检测：卡在 init 的提取会话
- `temp/claims/<session>/` 目录只有 `session.json`（无 step1/2/3 产物）
  + session.json 里 `state: init` + `attempts_step1: 0` → **C2 管线从未执行**
- 典型场景: 动态下载成功（有 .md）+ 会话创建成功，但 Step1 没跑 →
  claims 库无对应来源
- 修复: 按 qing-learning-claim 流程对该 raw 文件跑 `extract_claims_pipeline.py` 补提，
  完成后走完整同步（discover→Neo4j→Qdrant→重启 Agent）
