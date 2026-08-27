# 2026-08-18 提取会话模式（早盘专栏 26 条 + 09:27 动态 4 条 + 午盘 13:31 动态 8 条）

## 来源与产物

- `claim-20260818-001.yaml`（早盘专栏 001-026，26 条：market-cycle×7, macro×2, methodology×1, sector-theme×10, stock-view×3, risk×3）
- `claim-20260818-002.yaml`（09:27 图片动态 027-030，4 条：technical-signal×1, macro×2, operation×1）
- `claim-20260818-003.yaml`（13:31 午盘图片动态 031-038，8 条：market-cycle×3, risk×1, operation×1, sector-theme×3）
- 编号跨文件全局延续（001→026，002→027-030，003→031-038）——与 §18"同日期多文件编号"惯例一致
- 单日多份 raw 的编号核对：**看当日所有 YAML 的最后一个 id +1**，不是文件序号+1（§18 再验证）

## NON_COMPANY 新增 12 片段（三个会话批次）

### 批次 1：早盘专栏（9 条）

```python
"做科技", "对科技", "因此科技", "高估值科技", "直接催化有限",
"今日开盘对科技", "线大涨就做科技", "鹰对高估值科技", "场直接催化有限",
```

### 批次 2：09:27 动态（1 条）

```python
"纪要偏鹰压科技",
```

### 批次 3：午盘 13:31 动态（2 条）

```python
"度大概率也有限", "调整幅度有限",
```

午盘假阳性来自"调整幅度有限"类判断句——"有限"后缀第 N 次出现（呼应 §21 的第六后缀规则），
午盘/复盘里"承接力度尚可，调整幅度有限"是高频句式，预判可提前加。

### 再次验证 §13 完整片段规则

第一次只加了词根（`做科技/对科技/因此科技/高估值科技/直接催化有限`），
重跑 Gate 2 仍报 `今日开盘对科技 / 线大涨就做科技 / 鹰对高估值科技 / 场直接催化有限`——
**正则贪心匹配的是 2-5 汉字 + 后缀的完整串**，报错文本即完整捕获串，必须原样加入。
词根 + 完整串一起加才通过（两次失败后成功，教训与 §13 完全一致）。

## 08-18 特有短语模式

早盘专栏"偏鹰压科技"类（FOMC 解读段）与"量缩价升"判断段是新的假阳性来源：
- `纪要偏鹰压科技` → 实际是"纪要偏鹰压（制）科技股"的连写
- `今日开盘对科技` / `线大涨就做科技` → "对科技股/做科技普涨预期"的宾语结构
- `鹰对高估值科技` → "偏鹰对高估值科技股是压力"

这些结构在宏观/技术分析型早盘中会重复出现（FOMC 纪要、量能判断、4000 点情形），
预判可提前加入 NON_COMPANY。

## B站动态核对（本次用脚本函数而非裸 curl）

核对动态 ID/时间用 `fetch_bilibili_up_v2.py` 内的 `fetch_dynamic_list(uid, sessdata)`：
```bash
export BILIBILI_SESSDATA=$(cat ~/.hermes/bilibili_sessdata.txt)
python3 -c "
import sys; sys.path.insert(0, 'scripts')
from fetch_bilibili_up_v2 import fetch_dynamic_list
d = fetch_dynamic_list('1420210197', '$BILIBILI_SESSDATA')
for it in d['data']['items']:
    mod = it.get('modules') or {}
    print(mod.get('module_author',{}).get('pub_time'), it.get('type'),
          it.get('id_str'), (mod.get('module_dynamic',{}).get('major',{}) or {}).get('article',{}) or {})
"
```
注意：feed items 的 `module_dynamic.desc` 可能为 None（专栏动态内容在 `major.article.title`），
`it.get('modules')` 也可能为 None，遍历需防御。API 响应含 `is_only_fans: true` = 充电专属。
