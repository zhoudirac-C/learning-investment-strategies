# 2026-08-19 提取会话模式（早盘专栏 + 3 条盘中动态，当日 4 文件 001-070）

## 当日概况

| 文件 | 内容 | 编号 | 条数 |
|------|------|------|------|
| claim-20260819-001.yaml | 09:01 早盘专栏（充电专属，动态 1238079642295861257） | 001-024 | 24 |
| claim-20260819-002.yaml | 09:59 盘中图片动态（1238094644582023189） | 025-029 | 5 |
| claim-20260819-003.yaml | 12:03 午盘图片动态（1238126539049009161） | 030-036 | 7 |
| claim-20260819-004.yaml | 14:11 尾盘图片动态（1238159528701198355） | 037-042 | 6 |

单日四文件惯例再次验证：**新 raw 永远新文件（cp 非追加），编号跨文件连续**。
当次任务一次处理多条动态时：每条动态单独 `start` 一个 session，各写各的 YAML，
最后一起 git commit + 一起同步管线（discover 可合并跑完再 migrate）。

## 关键新技巧：充电专属专栏手动拉取正文

### 症状
动态列表能拿到 article id（如 52467573），但两个接口都拿不到正文：

```bash
# ❌ 动态详情接口：article.desc 只有 "请将App客户端升级至最新版本后观看"
# ❌ 文章详情接口 /x/article/view?id=52467573：data.content 也是同样 18 字占位符
```

### 正确姿势
用 `scripts/fetch_bilibili_up_v2.py` 里的 `fetch_article_content(article_id, sessdata)`：
- 走 `https://www.bilibili.com/read/cv{id}` 页面 HTML
- 正则抓 `window.__INITIAL_STATE__` 里的 `detail.modules[].module_content.paragraphs[].text.nodes[].word.words`
- 返回拼接好的全文（本次 5332 字）

```bash
export BILIBILI_SESSDATA=$(cat ~/.hermes/bilibili_sessdata.txt)
PYTHONPATH=src .venv/bin/python -c "
import sys; sys.path.insert(0, 'scripts')
from fetch_bilibili_up_v2 import fetch_article_content
print(fetch_article_content('52467573', '$BILIBILI_SESSDATA'))"
```

### 落盘 raw 惯例
手动拉到的全文按既有 frontmatter 模板写 `sources/original/bilibili/2026-08-19-0901-专栏-*.md`
（含 dynamic_id/pub_time/is_only_fans: true），之后走正常 C2 管线提取。
文件名用标题首段截断，注意与 cron 自动抓取的命名风格保持一致。

## NON_COMPANY 批次 19（早盘专栏 14 条科技假阳 + 盘中 2 条）

早盘专栏"科技"是主题词，本批次一次性加 14 条（全部是"X+科技"句式）：

```
尤其高估值科技 / 回调但科技 / 要还是因为科技 / 涨的主因是科技 / 抢先手说明科技 /
否承接决定科技 / 则证明科技 / 明资金对于科技 / 越说明科技 / 这决定了科技 /
不在科技 / 此时不在科技 / 机器人链但科技 / 包括长鑫科技
```

盘中动态追加 2 条：
```
亏损风险有限 / 指数跌幅有限
```

印证 §10 规律：**每个 raw 类型有自己的句式**——早盘专栏"科技"语境最重，
但 8/19 这批复盘的"二浪回调时科技"等 4 条（见 8/18 复盘批）与早盘不重叠。

## Gate 2 新报错模式：statement 有代码但 related_stocks 为空

### 症状
```
statement 中标注了 A 股代码但 related_stocks 为空
```

### 根因
Step 2 批量补代码时只做了 `公司名(6位代码)` 文本标注，但 `related_stocks` 列表
没同步配置（013/022 案例：statement 提到天洋新材(603330) 但 rs_cfg 缺该 id）。

### 排查
```python
import json, re
d = json.load(open('.../step2_enriched.json'))
pat = re.compile(r'\((\d{6})\)')
for c in d:
    codes = set()
    for f in ['statement','evidence_quote','interpretation']:
        codes.update(pat.findall(c[f]))
    missing = codes - {r['code'] for r in c.get('related_stocks',[])}
    if missing: print(c['id'], '缺:', missing)
```

### Fix
给该 claim 补 related_stocks（含 code/name/role），删 gate2 缓存重跑。

## 置顶评论也是 claim 源（图片动态）

09:59 图片动态的**置顶评论**（"这个地方可以抄一波了"）被提取为独立 claim
（028，operation 类，confidence: medium）。图片动态 raw 文件里置顶评论在
`## 置顶评论` 段，**不要漏看**——UP 的置顶评论常是比正文更积极的信号，
可与正文形成张力（028 正文说"不着急抄"但置顶说"可以抄一波"）。

## 时间语义注意

12:03 动态说"建议大家在10点20附近抄底"——发布时间晚于建议时点，是**盘后/午间
对上午窗口的总结**，不是未来的操作指令。解读时注意：claim 的 timeframe 标
intraday 但执行窗口可能已过，后续引用时要标注"窗口已过，执行看后续"。
