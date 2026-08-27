# 2026-08-02 复盘提取实战模式（25 claims）

来源：8.2（复盘）充电专属专栏 cv52013305，单文件 25 条 claims。
Gate 1/2/3 全过，一次修正后通过。

## 1. B站 feed 时间字段坑（提取前核对）

`modules.module_author.pub_time` 返回**相对时间**（"53分钟前"），不能用于日期过滤。
必须用 `pub_ts`（Unix 时间戳）：

```python
from datetime import datetime, timezone, timedelta
tz = timezone(timedelta(hours=8))
dt = datetime.fromtimestamp(int(author["pub_ts"]), tz)
day = dt.strftime('%Y-%m-%d')
```

无 SESSDATA 时 feed API 偶发返回 `items: 0`（限流/风控），带 `~/.hermes/bilibili_sessdata.txt`
的 SESSDATA 调用 `fetch_dynamic_list(uid, sessdata, offset=...)` 稳定。

## 2. 充电专属专栏正文提取

复盘专栏 `DYNAMIC_TYPE_ARTICLE` + `is_only_fans: true`：
- 动态 API `major.article` 只有 title/desc/covers/id/jump_url/label，desc 是"请将App客户端升级至最新版本后观看"
- 文章 API `/x/article/viewinfo` 返回 -404
- 正解：`https://www.bilibili.com/read/cv{article_id}` + SESSDATA cookie，
  从 `window.__INITIAL_STATE__` 的 `detail.modules` 提取
- 模块索引：0=TITLE、1=AUTHOR、2=CONTENT（`module_content.paragraphs`，62 段中 45 段有文字）
- ⚠️ 不是所有 module 都有 `module_content`（TITLE/AUTHOR/COPYRIGHT/BOTTOM/STAT 为 None），
  遍历时必须 `if not pc: continue` 防御

## 3. Gate 2 annotate 正则 lookahead bug

自动标注代码时负向前瞻过宽会漏标：

```python
# ❌ (?![（(]) 跳过"名字后跟中文括号"的正常情况 → 捷成股份漏标
re.compile(name + '(?![（(])')
# ✅ 只跳过已带数字代码的情况
re.compile(re.escape(name) + r'(?!\s*[（(]\d{5,6}[）)])')
```

排查：`re.findall(r"([\u4e00-\u9fff]{2,5}(?:股份|科技|电子|智能|医疗|有限))", text)`
预扫描所有未带 `(\d{6})` 的名字。

## 4. 港股/未上市代码处理

Gate 2 `code_refs = re.findall(r"[（(](\d{4,6})[）)]", text)` + `len(code) != 6` 报错：
- 港股 5 位（金蝶国际 00268、明略科技 02718）→ related_stocks 不放、文本不标 `(00268)`
- 公司名（明略科技）加入 `NON_COMPANY`（注释标"港股"），文本保留名字不标码
- 东财 API 判定：`MktNum=116` → 港股；`1` → 沪市；`0` → 深市

## 5. NON_COMPANY 新假阳（8/2 复盘）

```
月是杀科技 / 下跌前三为电子 / 信号是下周科技 / 资金入场时科技 / 不收敛且非科技 / 三是科技
智能视频智能 / 物联智能 / 全球电子 / 低成本具身智能 / 及经明略科技 / 二是明略科技 / 为明略科技 / 明略科技
```
"智能视频、智能物联"这类**业务板块描述**（富瀚微归因）和"具身智能"术语是高频假阳来源。

## 6. Step 4 落盘惯例

- **单日单文件**：`knowledge/claims/claim-YYYYMMDD-001.yaml`（内含当日全部 claims，
  7/31=24条、8/2=25条），不是每条一个文件
- 移动：`cp temp/claims/<session>/step3_yaml/claim-YYYY-MM-DD-output.yaml knowledge/claims/claim-YYYYMMDD-001.yaml`
- 编号核对 = 确认该日期文件不存在，不是找最大编号
- 移动后 `python scripts/gate_validate_claims.py <yaml>` 手动验证
- Gate 2 修完 NON_COMPANY 后必须 `rm -f gate2_result.json` 再 continue
