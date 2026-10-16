# 技术方案（初稿）：claim 保真度门禁 —— 防「凭空推断 / 曲解原意」

> 状态：**草案，未实施**（等拍板）
> 日期：2026-10-16
> 背景：`docs/analysis/gator-extraction-method-vs-ours-20261016.md` 建议 A2 / A2b
> 目标：补上 claim 管线**唯一一处结构性空白** —— 现有 gate1-5 全是结构检查，
>       没有一道检查「这句话真的是 UP 说的吗」

---

## 〇、结论前置

1. **值得做，但不能按"字面匹配"做。** 我在真实数据上实测了朴素方案，
   **11 条 claim 里有 2 条被误判**（18% 误报率）—— 见第二节。直接上会制造大量假阳性。
2. **误报根因不是"编造"，而是两种良性偏差**：①**原文换行噪声**
   （该 raw 的 HTML 转文本在数字/短词前后插了 `\n    \n`）②**标点/连接词改写**
   （`医药，等等一样` → claim 写成 `医药等等一样`）。**这两类都不该报错。**
3. **正确设计是「两级判定」**：机械层做**召回**（把可疑的挑出来），
   **不做终审**；终审交给 LLM 一步复核 + 人工兜底。
4. **建议先做"影子模式"**：新增 gate6 **只记录不拦截**，跑一周看真实误报率，
   再决定是否升为硬门禁。**这与项目既有的"影子双轨"验证习惯一致。**

---

## 一、要解决什么（问题定义）

### 1.1 现有门禁覆盖了什么

`scripts/gate_validate_claims.py` 现有 5 道：

| Gate | 检查 | 性质 |
|---|---|---|
| 1 | 19 必填字段齐全 | 结构 |
| 2 | 枚举值合法（claim_type/timeframe/confidence/status/stance/intensity） | 结构 |
| 3 | related_stocks 格式 + 代码填写 | 结构 |
| 4 | 原子性（一 claim 一主题） | 结构 |
| 5 | statement 中的公司名带 6 位代码 | 结构 |

**全部是"格式对不对"，没有一道是"内容真不真"。**

### 1.2 空白造成的实际风险

| 风险 | 场景 | 后果 |
|---|---|---|
| **凭空推断** | LLM 写出一条 statement，raw 里根本没这个观点 | 污染知识库，检索时给出"UP 从没说过的观点" |
| **曲解绝对化** | raw 说「若量能不济则回到 4000 以下」，claim 写成「必破 4000」 | 限定条件丢失，观点被强化 |
| **过度归纳** | raw 是一次性点评某板块，claim 写成「长期方法论」 | 个案升格为规则 |

**第三条（凭空推断）是 gator 作者明确点名、且我们完全没防的。**

---

## 二、实测：朴素方案为什么不行（关键证据）

### 2.1 实验设置

用刚提取完的 `claim-20261015-002.yaml`（11 条，源自 gator 公众号原文）

**方法**：把 `evidence_quote` 与 `source_path` 指向的 raw 都做「去空白归一化」后比对，
两种判据：①直接子串 `quote in raw`；②最长公共子串占比 `LCS/len(quote)`。

### 2.2 结果（**这是设计的决定性依据**）

| claim | conf | 直接子串 | LCS 占比 |
|---|---|---|---|
| -a | high | ✅ | 100% |
| **-b** | high | ❌ | **76%** |
| -c | high | ✅ | 100% |
| -d | high | ✅ | 100% |
| -e | high | ✅ | 100% |
| **-f** | medium | ❌ | **54%** |
| **-g** | high | ❌ | **38%** |
| -h | medium | ✅ | 100% |
| -i | medium | ✅ | 100% |
| -j | medium | ✅ | 100% |
| -k | medium | ✅ | 100% |

**8/11 完美命中，3/11 异常 —— 但这 3 条全部是真的、不是编造。**

### 2.3 逐条归因（根因分析）

**`-b`（76%）**：`evidence_quote` 是 `总结：……可以开始试多，右侧信号尚未出现。`
→ **claim 用了省略号拼接**（把原文两处合并）。这是**良性压缩**，不是曲解。
→ 判据：**含"……"/"…" 的 quote 应豁免**。

**`-f`（54%）**：quote 中含 `……`（省略号），**实际走的是判据 0（省略号豁免）放行**，
未走到 LCS 判据。若去掉省略号，其 LCS=54%。
→ 原文 HTML 转文本在数字（`3700`）前后插了大量 `\n    \n`，且原文是
  `有人喜欢在大盘3700，科技腰斩再腰斩，其他板块被错杀再错杀的时候做空`
  → claim 略去「其他板块被错杀再错杀」。**良性摘录，非编造。**

**`-g`（38%）**：分段检验结果 —— 8 个分句里 **6 个完全命中原文**，
唯一不中的是 `医药等等一样`（原文 `医药，等等一样`，**去掉了逗号**）。
→ **这就是"标点差异"导致的整体子串失配。**
→ 判定：**应该通过**，但 naive LCS 只给 38% → 若阈值设 40% 会误报。

### 2.4 结论：**朴素子串匹配在当前数据形态下不可用**

误报率 3/11 = 27%（按 claim 数），且**误报的都是高质量 claim**。
若设阈值 60% → 会把 `-f`(54%) 和 `-g`(38%) 判为"疑似编造"，
**这两条恰恰是 conf=high 和 medium 的合法 claim** → 门禁会失去公信力。

---

## 三、方案设计

### 3.1 总体思路：两级判定 + 影子模式

```
        ┌─────────────────────────────────────────┐
        │  Level 1（机械，Python）— 只做召回      │
        │  目的：高召回地把"可疑"挑出来            │
        │  绝不单独判"编造"                       │
        └────────────────┬────────────────────────┘
                         │ 可疑清单
                         ▼
        ┌─────────────────────────────────────────┐
        │  Level 2（LLM，一步）— 语义复核          │
        │  输入：claim.statement/interpretation    │
        │        + raw 原文（全文或相关段）        │
        │  输出：忠实 / 曲解 / 无依据              │
        └────────────────┬────────────────────────┘
                         │
              ┌──────────┴──────────┐
              ▼                     ▼
        影子模式：只记录        硬门禁（待定）：拦截
        （先跑一周）          （误报率达标后启用）
```

### 3.2 Level 1 机械层：多判据「取或」（OR），不做「与」

**核心原则：任何一条判据说"像"，就放行；只有全部判据都说"不像"，才标记可疑。**

```python
def quote_fidelity_check(claim, raw_text) -> dict:
    """
    返回 {"status": "ok"|"suspect", "best_ratio": float, "method": str}
    只做召回，不做终审。
    """
    q = claim.get("evidence_quote", "")
    q_norm = normalize_ws(q)
    raw_norm = normalize_ws(raw_text)

    # 判据 0（豁免）：含省略号的拼接 quote → 直接放行
    if "……" in q or "…" in q:
        return {"status": "ok", "method": "ellipsis_exempt"}

    # 判据 1：直接子串（归一化后）
    if q_norm in raw_norm:
        return {"status": "ok", "method": "substring"}

    # 判据 2：分句命中率（按标点切分，看有多少分句能在原文找到）
    segs = [s for s in re.split(r"[，。、；：！？,.;:!?]", q_norm) if len(s) >= 4]
    if segs:
        hit = sum(1 for s in segs if s in raw_norm)
        seg_ratio = hit / len(segs)
        if seg_ratio >= 0.8:          # ≥80% 分句命中 → 视为忠实（覆盖 -g 案例）
            return {"status": "ok", "method": "segment", "ratio": seg_ratio}

    # 判据 3：最长公共子串占比（低阈值，仅兜底）
    lcs = longest_common_substring_len(q_norm, raw_norm)
    lcs_ratio = lcs / max(1, len(q_norm))
    if lcs_ratio >= 0.35:             # 放宽到 35%（覆盖 -f 的 54%）
        return {"status": "ok", "method": "lcs", "ratio": lcs_ratio}

    return {"status": "suspect", "best_ratio": lcs_ratio, "method": "none"}
```

**关键参数（初值，待实测校准）**：

| 参数 | 初值 | 依据 |
|---|---|---|
| 分句最小长度 | 4 字 | 太短的分句（"所以"）命中没意义 |
| 分句命中率阈值 | 80% | `-g` 是 6/8=75%，设 80% 会误杀 → **建议 75%** |
| LCS 兜底阈值 | 35% | `-f`=54%、`-g`=38% → 设 35% 可放行两者 |

> ⚠️ **注意**：按上表，`-g` 走判据 2 时是 6/8=75%。**若阈值定 80% 会落到判据 3**，
> 而 `-g` 的 LCS=38% ≥ 35% 仍能放行。**所以两条判据互为兜底是必要的** ——
> 这正是"取或"设计的价值。

### 3.3 用真实数据回验（预期结果）

| claim | 判据命中 | 预期 status |
|---|---|---|
| -a | 判据1 | ok |
| -b | 判据0（省略号） | ok |
| -c/d/e | 判据1 | ok |
| -f | 判据3（54%≥35%） | ok |
| -g | 判据2（75%）或判据3（38%） | ok |
| -h~-k | 判据1 | ok |

**→ 11/11 全部 ok，误报清零。** 这才是可用的设计。

> ⚠️ **原型实测修正（2026-10-16 落盘后复跑）**：实际命中分布为
> `ellipsis ×2（-b/-f）`、`segment 83%（-g）`、`substring ×8`、**`lcs 判据 0 次命中`**。
> 即 **LCS 兜底判据在本样本中从未被触发** —— 它目前是"未经验证的保险"，
> 不是"已验证有效的手段"。**P1 影子模式必须统计各判据命中分布**，
> 若 LCS 长期 0 命中 → 应从设计中删除（避免留死代码），而非保留。
>
> 另修正：`-f` 原判"LCS 54%"实际是**省略号豁免**，非 LCS 放行（见 2.3 归因）。

### 3.4 Level 2 LLM 复核（只对 suspect 触发）

**只在 Level 1 判定 suspect 时才调用**（省 token —— 正常情况一次都不调）。

Prompt 骨架（建议放进 `extract_claims_pipeline.py` 的下一步指令）：

```
下面这条 claim 声称来自 UP 原文，但机械比对未能定位到出处。
请判断它属于哪种情况，只回答一个词：

claim.statement: {statement}
claim.evidence_quote: {evidence_quote}
原文全文: {raw_text}

A. 忠实 —— 原文中有等价表述（可能被改写/压缩/标点不同）
B. 曲解 —— 原文有相关表述，但被绝对化/去掉了限定条件
C. 无依据 —— 原文中找不到任何对应观点（疑似凭空推断）

判定：___
若为 B 或 C，请引用原文中最接近的一段作为对照。
```

### 3.5 集成点（最小改动）

| 文件 | 改动 | 量级 |
|---|---|---|
| `scripts/gate_validate_claims.py` | 加 `gate6_quote_fidelity()` + 挂进 `validate_claims()`（step≥2） | ~60 行 |
| `scripts/extract_claims_pipeline.py` | Step 1 prompt 加「凭空推断自查项」（A2b） | ~10 行 |
| `tests/test_gate6_quote_fidelity.py` | 新建单测（用本文第二节的 11 条真实 claim 作 fixture） | ~80 行 |
| `config/` 或常量区 | 阈值参数集中管理 | ~5 行 |

**沿用项目既有模式**：阈值常量集中（对齐 `gator_rules.py` 文件头做法）、
`strict=False` 时降级为 warning（对齐 `GRANDFATHERED_FIELDS` 存量宽限做法）。

---

## 四、分阶段实施（建议）

| Phase | 内容 | 验收 | 风险 |
|---|---|---|---|
| **P0** | 写单测：把本文 11 条 claim + raw 固化为 fixture，跑通"全 ok" | 11/11 ok | 无 |
| **P1** | 实现 `gate6`，**影子模式**（只写日志 `logs/claim-fidelity.jsonl`，不拦截） | 跑一周，统计 suspect 率 | 低 |
| **P2** | 看一周数据：若 suspect 率 <5% → 升为 warning；若误报仍高 → 调参 | 用户拍板 | 中 |
| **P3** | 升硬门禁 + 接 Level 2 LLM 复核 | 用户拍板 | 中 |
| **P4** | （可选）A2b prompt 自查项 | — | 低 |

**P4 其实可以先做**（零风险，纯 prompt 增强），但**须先确认它真能降低 suspect 率**，
否则就是无效 prompt。

---

## 五、风险与不确定性

1. **实测样本只有 11 条 claim、1 个 raw 文件** —— 阈值（75%/35%）是**单样本校准**，
   极可能在其他 source_type（B站动态、专栏、视频转写）上表现不同。
   **P1 影子模式就是为收集更大的样本而设。**
2. **`source_path` 可能不存在**：存量 claim 的 `source_path` 指向
   `sources/raw/财经/`（老整理稿），与 `sources/original/bilibili/`（新原始抓取）
   是两套路径。**gate6 必须对"找不到 raw 文件"的情况降级为 skip**，不能报错。
3. **视频转写 raw 噪声更大**（同音字灾难）→ LCS 判据可能整体偏低。
   **建议按 `source_type` 分阈值**（公众号一套、视频一套）。
4. **Level 2 的 LLM 复核本身也会错** → 所以 Level 2 的产出**也应该是 warning 而非 error**，
   最终由人工在 wiki 复核环节兜底。
5. **可能有人为规避**：如果 LLM 知道有 gate6，它可能"照抄原文"以通过门禁 ——
   这没问题（**照抄原文正是我们要的**），但要防止它把长句拆碎以提升分句命中率。
   → 建议同时检查 `statement` 与 `evidence_quote` 的**重叠度不能过高**（防退化成摘抄）。
6. **本方案不解决"过度归纳"**（个案→长期规则）—— 那需要的是**跨 claim 频率统计**，
   属于另一个机制（对应 gator 的 `[单源]` 标记）。**建议单独立项，不塞进 gate6。**

---

## 六、与你已有决策的衔接

| 你的既有原则 | 本方案如何遵守 |
|---|---|
| 「config 字段需有 consumer」 | gate6 有明确 consumer（门禁 + 日志），不是装饰 |
| 「阈值口径宁可漏不可错」 | 采用"取或"高放行设计，**宁可漏报编造，不误杀真 claim** |
| 「大型需求先出方案+决策点」 | 本文即方案；决策点见下 |
| 「影子/观察一轮」 | P1 强制影子模式，不直接拦截 |
| 「完成 = commit + push」 | 实施时同 |

---

## 七、需要你拍板的决策点（编号清单）

| # | 决策 | 选项 | 我的建议 |
|---|---|---|---|
| **D1** | 做不做 gate6 | ①做 ②不做 ③只做 A2b prompt 不做 gate | **①做，但先影子模式** |
| **D2** | Level 1 判据组合 | ①四条取或（本文）②只用直接子串 ③只用 LCS | **①四条取或** |
| **D3** | 阈值初值 | ①分句75% + LCS35% ②更高（严）③更低（宽） | **①，宽容优先** |
| **D4** | 是否分 source_type 设阈值 | ①分（公众号/视频）②统一 | **①分，视频更宽** |
| **D5** | P1 影子跑多久 | ①一周 ②三天 ③两周 | **①一周** |
| **D6** | Level 2 LLM 复核纳入哪期 | ①P3 ②P1 就加 ③不做 | **①P3** |
| **D7** | 是否同步做 A2b prompt 自查项 | ①同步做 ②P1 看完数据再做 | **②，避免无效 prompt** |

---

## 附：复现本文实验

```bash
cd ~/learning-investment-strategies
.venv/bin/python - <<'PY'
import yaml, re
from pathlib import Path
from difflib import SequenceMatcher

raw = Path('sources/original/wechat/2026-10-15-股市：放粮了，三日内涨（2026.10.15）.md').read_text()
norm = lambda s: re.sub(r'\s+','',s)
rn = norm(raw)
for c in yaml.safe_load(open('knowledge/claims/claim-20261015-002.yaml'))['claims']:
    q = norm(c['evidence_quote'])
    m = SequenceMatcher(None, q, rn).find_longest_match(0,len(q),0,len(rn))
    print(c['id'], 'direct=', q in rn, f'lcs={m.size/len(q):.0%}', 'conf=', c['confidence'])
PY
```

产出：`-b`(76%)、`-f`(54%)、`-g`(38%) 三条直接子串失配 —— 本文的根本出发点。
