#!/usr/bin/env python
"""孕线 claim 合并：104 条（20260621-002~005）→ 28 条（20260621-006）。

规则：
- 同一规则/同一叙事的多句碎片合并为一条，保留全部 evidence_quote 原文（用「……」连接）。
- 新 claim 的 supersedes 列出被合并的旧 id；旧 claim status 改 superseded（保留原文可追溯）。
- 不改动其他 claim。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CLAIMS = ROOT / "knowledge" / "claims"
OLD_FILES = [CLAIMS / f"claim-20260621-00{i}.yaml" for i in (2, 3, 4, 5)]
NEW_FILE = CLAIMS / "claim-20260621-007.yaml"
SOURCE_PATH = "sources/raw/财经/视频：26-06-21：技术分析-孕线.md"

# (new_suffix, subject, statement, interpretation, tags, timeframe, intensity, [old ids])
SPEC = [
    (
        "a", "孕线定义与观察视角",
        "孕线又称母子线，观察视角从左到右、重点看第一根大K线，与从右向左观察第二根K线的吞没形态完全相反。核心判定是实体包裹实体：第一根大K线包裹第二根小K线，第二根的最高价必须小于第一根实体上端，最低价必须大于第一根实体下端。",
        "定义层：把观察顺序与实体包裹口径固定下来，是与吞没形态区分的第一道门。",
        ["孕线", "母子线", "K线形态", "实体包裹"], "permanent", "high",
        ["claim-20260621-002-a", "claim-20260621-002-b", "claim-20260621-002-c", "claim-20260621-002-l",
         "claim-20260621-002-m", "claim-20260621-002-n", "claim-20260621-003-b"],
    ),
    (
        "b", "看涨孕线的结构要件",
        "看涨孕线出现在下跌末端：第一根为大阴线或中阴线，第二根为实体更小的K线且被第一根实体包裹；第二根收小阳线的信号效果优于小阴线。",
        "给出看涨孕线的位置、第一根、第二根与颜色优劣四项要件，缺位置即不成立。",
        ["孕线", "看涨孕线", "底部反转"], "permanent", "high",
        ["claim-20260621-002-d", "claim-20260621-002-e", "claim-20260621-002-f", "claim-20260621-002-g"],
    ),
    (
        "c", "看涨孕线的市场叙事",
        "看涨孕线的叙事是：第一天收出实体极长的大阴线、空方占据绝对优势；第二天价格高开后全天在大阴线实体范围内小幅震荡、没有延续之前的下跌趋势，说明空方力量耗尽。",
        "叙事层解释「为什么会反转」：不是第二天涨得多，而是第一天的主导方在第二天失去了延续能力。",
        ["孕线", "看涨孕线", "力量衰竭"], "permanent", "high",
        ["claim-20260621-002-s", "claim-20260621-002-t", "claim-20260621-002-u", "claim-20260621-002-v",
         "claim-20260621-002-y"],
    ),
    (
        "d", "看跌孕线的结构要件",
        "看跌孕线出现在上涨末端：第一根为大阳线或中阳线，第二根为实体更小的K线且被第一根实体包裹；第二根收小阴线的信号效果优于小阳线。",
        "与看涨孕线镜像对称，位置换到上涨末端、颜色优劣相反。",
        ["孕线", "看跌孕线", "顶部反转"], "permanent", "high",
        ["claim-20260621-002-h", "claim-20260621-002-i", "claim-20260621-002-j", "claim-20260621-002-k"],
    ),
    (
        "e", "看跌孕线的市场叙事",
        "看跌孕线的叙事是：第一天收出实体极长的进攻型大阳线、多方占据绝对优势；第二天价格低开后全天在大阳线实体范围内小幅震荡、没有延续上涨趋势，代表多方力量完全耗尽且没有新资金跟进。",
        "与看涨孕线镜像：关键在于第二天是否延续，而不是单日涨跌。",
        ["孕线", "看跌孕线", "力量衰竭"], "permanent", "high",
        ["claim-20260621-002-o", "claim-20260621-002-p", "claim-20260621-002-q", "claim-20260621-002-r",
         "claim-20260621-002-x"],
    ),
    (
        "f", "孕线的本质：力量衰竭的早期预警",
        "孕线本质上是力量衰竭信号，属于反转的早期预警，而不是反转的确认。",
        "定性层：把孕线归入「预警」而非「信号」，决定了后续所有操作口径。",
        ["孕线", "力量衰竭", "反转预警"], "permanent", "high",
        ["claim-20260621-002-w", "claim-20260621-002-z"],
    ),
    (
        "g", "孕线与吞没的结构与强度对比",
        "吞没形态是第二根大K线包裹第一根小K线，代表力量爆发、趋势直接切换；孕线是第一根大K线包裹第二根小K线，代表力量收缩、市场犹豫。因此吞没的信号优先级高于孕线、化解难度也高于孕线，孕线的信号强度弱于吞没、化解难度低于吞没。",
        "两者虽然都是两根K线的包裹结构，但包裹方向相反，市场逻辑完全不同，不能互相替代。",
        ["孕线", "吞没形态", "形态对比"], "permanent", "high",
        ["claim-20260621-003-a", "claim-20260621-003-c", "claim-20260621-003-d", "claim-20260621-003-e",
         "claim-20260621-003-f", "claim-20260621-003-g", "claim-20260621-003-h", "claim-20260621-003-i"],
    ),
    (
        "h", "时态差：吞没是完成时，孕线是进行时",
        "吞没形态是反转的完成时，看到信号可以直接执行操作；孕线是反转的进行时，只能作为预警使用、不能直接进场交易。若把看跌孕线当执行信号立刻清仓容易踏空，若把看涨孕线当执行信号立刻抄底容易被套。",
        "时态差是孕线全部操作纪律的根源：它给的是反应时间，不是入场理由。",
        ["孕线", "吞没形态", "交易纪律"], "permanent", "high",
        ["claim-20260621-003-j", "claim-20260621-003-k", "claim-20260621-003-l", "claim-20260621-003-m",
         "claim-20260621-003-n"],
    ),
    (
        "i", "孕线是吞没的常见前奏",
        "孕线是吞没形态的常见前奏；学会孕线可以在吞没信号出现前 1 至 2 个交易日提前警惕，从而给交易者留出充足的反应和容错空间。",
        "这是孕线的核心使用价值：把确认时点提前，而不是替代确认。",
        ["孕线", "吞没形态", "提前预警"], "permanent", "high",
        ["claim-20260621-003-o", "claim-20260621-003-p", "claim-20260621-003-q"],
    ),
    (
        "j", "看跌孕线的化解条件",
        "看跌孕线出现后，若第三根K线高开高走收出大阳线、且收盘价站上第一根大阳线的最高点，代表多方力量重新恢复，看跌孕线信号完全失效。",
        "化解条件用第一根的最高点作为判定位，而不是第二根或盘中价。",
        ["孕线", "看跌孕线", "信号化解"], "short-term", "high",
        ["claim-20260621-003-r", "claim-20260621-003-s"],
    ),
    (
        "k", "看涨孕线的化解条件",
        "看涨孕线出现后，若第三根K线低开低走收出大阴线、且收盘价跌破第一根大阴线的最低点，代表空方力量重新恢复，看涨孕线信号完全失效。",
        "与看跌孕线镜像：以第一根的最低点作为失效判定位。",
        ["孕线", "看涨孕线", "信号化解"], "short-term", "high",
        ["claim-20260621-003-x", "claim-20260621-003-y"],
    ),
    (
        "l", "案例：东山精密(002384)看跌孕线被化解",
        "东山精密(002384)周线出现标准看跌孕线，但后续第三根周K线高开高走突破前高，看跌孕线被成功化解，原有上涨趋势延续，此时应当继续持有仓位。",
        "案例说明：形态成立不等于趋势反转，化解后的正确动作是维持原方向而非逆势操作。",
        ["孕线", "看跌孕线", "案例", "东山精密(002384)"], "permanent", "medium",
        ["claim-20260621-003-t", "claim-20260621-003-u", "claim-20260621-003-v", "claim-20260621-003-w"],
    ),
    (
        "m", "案例：贵州茅台(600519)看涨孕线被化解",
        "贵州茅台(600519)周线底部出现标准看涨孕线，但后续第三根周K线低开低走跌破前低，看涨孕线被成功化解，原有下跌趋势延续，交易者不能抄底，应继续观望或减仓。",
        "与前述看跌孕线案例互为镜像：化解方向决定延续还是反转。",
        ["孕线", "看涨孕线", "案例", "贵州茅台(600519)"], "permanent", "medium",
        ["claim-20260621-003-z", "claim-20260621-004-a", "claim-20260621-004-b", "claim-20260621-004-c"],
    ),
    (
        "n", "周期选择：日线不清晰时切周线",
        "日线波动较大时孕线形态不够清晰，切换到周线观察效果更好。",
        "周期是孕线识别的可调参数，不是固定用法。",
        ["孕线", "周期选择", "周线"], "permanent", "medium",
        ["claim-20260621-004-d"],
    ),
    (
        "o", "孕线的失效概率",
        "实战交易中接近小一半的孕线会被化解，约三分之一的孕线信号最终完全无效、价格继续沿原有趋势运行。这个概率数据是重要的风险提示，直接否定了看到孕线就直接交易的错误用法。",
        "用概率否定「见信号即交易」，为「等确认」提供量化依据。",
        ["孕线", "失效概率", "风险提示"], "permanent", "high",
        ["claim-20260621-004-e", "claim-20260621-004-f", "claim-20260621-005-t", "claim-20260621-005-u"],
    ),
    (
        "p", "孕线之后的确认信号清单",
        "看跌孕线之后可叠加看跌吞没、下跌缺口、高位流星线、上吊线、长黑K线等顶部信号确认反转成立；看涨孕线之后可叠加看涨吞没、上涨缺口、低位锤子线、倒锤子线、长红K线等底部信号确认反转成立。交易者可结合此前学过的单根K线多空判断方法，等明确的单根确认信号出现后再执行交易操作；必须叠加后续确认信号才能提升交易胜率。",
        "清单化的确认信号，是孕线与执行之间必须插入的一层。",
        ["孕线", "确认信号", "单根K线"], "short-term", "high",
        ["claim-20260621-004-g", "claim-20260621-004-h", "claim-20260621-004-i", "claim-20260621-004-k",
         "claim-20260621-005-v"],
    ),
    (
        "q", "孕线的观察与记录流程",
        "孕线出现后应先进入观察状态：记录信号的看涨或看跌属性，不立刻进行任何实际交易操作，保持原有仓位继续观察；出现后的前三天应持续跟踪走势，若第三天之后价格依然维持小幅震荡，应继续保持警惕状态、不提前进场交易。",
        "把「不交易」写成有步骤的流程，避免临场被形态说服。",
        ["孕线", "观察流程", "记录"], "short-term", "high",
        ["claim-20260621-004-j", "claim-20260621-004-l", "claim-20260621-004-m", "claim-20260621-004-p"],
    ),
    (
        "r", "第三日出现化解信号：取消预警",
        "若第三天直接出现高开高走或低开低走的化解信号，应立刻取消预警，恢复原有趋势的交易节奏。",
        "化解是主动作废，不是继续观望。",
        ["孕线", "化解", "预警取消"], "short-term", "high",
        ["claim-20260621-004-n"],
    ),
    (
        "s", "第三日出现确认信号：执行反转操作",
        "若第三天出现吞没、缺口、长黑、长红等反转确认信号，应立刻执行对应的反转交易操作。",
        "确认与化解构成第三日的二选一分支，动作相反且都要即时。",
        ["孕线", "确认信号", "执行"], "short-term", "high",
        ["claim-20260621-004-o"],
    ),
    (
        "t", "孕线的有效观察周期 3 至 5 个交易日",
        "孕线的有效观察周期为 3 至 5 个交易日；若 5 个交易日内未出现明确反转确认信号，孕线信号自动失效，价格将继续沿原有趋势运行。该规则填补了形态识别的模糊地带，不标准的孕线形态无需纠结是否完美，只要时间窗口内没有确认信号就自动失效，从而大幅降低主观判断误差。",
        "用时间窗口给信号设自动过期，避免「越看越像」的主观拖延。",
        ["孕线", "有效周期", "纪律"], "short-term", "high",
        ["claim-20260621-004-q", "claim-20260621-004-r", "claim-20260621-005-w", "claim-20260621-005-x",
         "claim-20260621-005-y"],
    ),
    (
        "u", "案例：半导体板块三段式力量切换",
        "半导体板块先收出一根进攻型大阳线，之后连续 3 根小K线全部被大阳线实体包裹，形成标准的多K线组合看跌孕线；到第五个交易日收出大阴线形成看跌吞没，反转正式完成。教学团队在 5 月 29 日半导体板块出现看跌吞没信号时提示全体交易者空仓，减仓后第二周周一收出大阴线、下跌趋势正式确认。大阳线进攻、多日孕线力量衰竭、看跌吞没空方反超的完整三段式叙事，信号强度远高于单一K线反转信号。",
        "案例的价值在三段式结构：进攻—衰竭—反超，每一段都有可观察的盘面证据。",
        ["孕线", "案例", "半导体", "三段式"], "permanent", "medium",
        ["claim-20260621-004-s", "claim-20260621-004-t", "claim-20260621-004-u", "claim-20260621-004-v",
         "claim-20260621-004-w", "claim-20260621-004-x", "claim-20260621-004-y"],
    ),
    (
        "v", "分仓节奏：孕线先减 20-30%，吞没确认后再减 80% 以上",
        "孕线信号出现后可先减仓 20% 至 30%；吞没确认信号出现后再减仓 80% 以上；剩余小部分仓位根据后续走势灵活处理。该分仓节奏既不会过早误判踏空，也不会过晚反应被套。",
        "把「预警—确认」映射为两段仓位动作，是孕线唯一给出的仓位口径。",
        ["孕线", "分仓", "减仓节奏"], "short-term", "high",
        ["claim-20260621-004-z", "claim-20260621-005-a", "claim-20260621-005-b", "claim-20260621-005-c"],
    ),
    (
        "w", "高阶操作：先减半仓，确认后清仓或反向",
        "孕线信号出现后应先减半仓，等吞没确认信号出现后再完成清仓、大幅减仓或反向开仓；上述操作是经验交易者应当养成的标准化交易习惯。",
        "与 20-30% 版本并存：仓位比例取决于持仓性质与风险预算，动作顺序一致。",
        ["孕线", "高阶操作", "减仓"], "short-term", "medium",
        ["claim-20260621-005-n", "claim-20260621-005-o", "claim-20260621-005-p"],
    ),
    (
        "x", "反转形态的三类常见变体",
        "反转形态有三类常见变体：①没有孕线过渡，大K线之后直接接吞没的快速反转，信号极强但留给交易者的反应时间很短；②大K线加孕线之后没有出现吞没、孕线被化解，原有趋势延续；③大K线加孕线之后接长黑或长红替代吞没完成反转，是实战中最理想的反转形态。",
        "三类变体覆盖了「无预警直接反转」「预警失效」「替代确认」三种真实路径。",
        ["孕线", "反转形态", "变体"], "permanent", "high",
        ["claim-20260621-005-d", "claim-20260621-005-e", "claim-20260621-005-f"],
    ),
    (
        "y", "多K线孕线与连续孕线",
        "实战中的孕线不一定只有两根K线，也可以是 3 至 4 根连续小K线全部被第一根大K线实体包裹，同样属于有效孕线组合；市场走势中也经常出现孕线被化解之后又生成新孕线组合的情况，交易者需要持续跟踪观察，不能仅凭单一信号下定论。",
        "形态可扩展到多根，但「被化解后又新生」意味着跟踪是连续的，不是一次性判定。",
        ["孕线", "多K线孕线", "连续信号"], "permanent", "medium",
        ["claim-20260621-005-g", "claim-20260621-005-h", "claim-20260621-005-i"],
    ),
    (
        "z", "与缠论包含关系的对应",
        "孕线对应缠论中的左包右K线包含关系，吞没对应右包左包含关系；缠论的包含规则更严格，需要把引线部分也纳入包裹范围，满足缠论标准的孕线是顶级的标准孕线。",
        "跨体系映射：同一图形在两套方法中的严格程度不同，缠论口径可用来筛「最标准」的孕线。",
        ["孕线", "缠论", "包含关系"], "permanent", "medium",
        ["claim-20260621-005-j", "claim-20260621-005-k", "claim-20260621-005-l", "claim-20260621-005-m"],
    ),
    (
        "aa", "孕线的容错价值高于交易价值",
        "孕线的容错设计价值远高于直接交易价值：核心作用是提前给交易者留出反应缓冲期，避免在趋势反转关键节点反应过慢，从而大幅降低牛熊切换阶段的踏空和套牢概率。",
        "定位层结论：孕线是风险管理工具，不是信号工具。",
        ["孕线", "容错", "风险管理"], "permanent", "high",
        ["claim-20260621-005-q", "claim-20260621-005-r", "claim-20260621-005-s"],
    ),
    (
        "ab", "组合形态：大K线加孕线与吞没",
        "大K线加孕线加吞没的组合是反转叙事最完整、操作节奏最清晰的形态。",
        "把三段式组合定为标准范式，与前文案例一致。",
        ["孕线", "组合形态", "吞没"], "permanent", "medium",
        ["claim-20260621-005-z"],
    ),
]

NEW_ID_PREFIX = "claim-20260621-007-"


def load_old() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for f in OLD_FILES:
        d = yaml.safe_load(f.read_text(encoding="utf-8"))
        items = d if isinstance(d, list) else (d.get("claims") or [d])
        for c in items:
            if isinstance(c, dict) and "id" in c:
                out[c["id"]] = c
    return out


def main() -> int:
    old = load_old()
    if len(old) != 104:
        print(f"expected 104 old claims, got {len(old)}", file=sys.stderr)
        return 1

    used: list[str] = []
    merged: list[dict] = []
    for suffix, subject, statement, interp, tags, tf, inten, olds in SPEC:
        missing = [o for o in olds if o not in old]
        if missing:
            print(f"missing old ids for {suffix}: {missing}", file=sys.stderr)
            return 1
        used.extend(olds)
        quotes = []
        for oid in olds:
            q = str(old[oid].get("evidence_quote", "")).strip()
            if q and q not in quotes:
                quotes.append(q)
        merged.append({
            "id": NEW_ID_PREFIX + suffix,
            "source_path": SOURCE_PATH,
            "up_id": "1420210197",
            "up_name": "青枫浦上Q",
            "source_date": "2026-06-21",
            "source_type": "视频",
            "extracted_at": "2026-10-31",
            "claim_type": "technical-knowledge",
            "subject": subject,
            "timeframe": tf,
            "statement": statement,
            "evidence_quote": "……".join(quotes),
            "interpretation": interp,
            "confidence": "high",
            "status": "active",
            "intensity": inten,
            "supersedes": olds,
            "contradicts": [],
            "supplements": [],
            "last_discovered": None,
            "links": {
                "wiki_pages": ["knowledge/wiki/投资方法论/技术分析.md"],
                "methodology_pages": ["framework/technical-analysis-framework.md"],
                "cases": [],
            },
            "topic": subject,
            "related_stocks": [],
            "tags": tags,
            "school": "qing",
        })

    dup = {i for i in used if used.count(i) > 1}
    if dup:
        print(f"old ids mapped more than once: {sorted(dup)}", file=sys.stderr)
        return 1
    uncovered = sorted(set(old) - set(used))
    if uncovered:
        print(f"old ids not covered ({len(uncovered)}): {uncovered}", file=sys.stderr)
        return 1

    header = f"""# 孕线课程 claim 合并（2026-10-31）
# 来源：{SOURCE_PATH}
# 104 条碎片（claim-20260621-002~005）→ {len(merged)} 条规则级 claim
# 旧 claim 保留原文，status 置 superseded；新 claim 的 supersedes 列全部原 id
"""
    NEW_FILE.write_text(header + yaml.safe_dump({"claims": merged}, allow_unicode=True,
                                                sort_keys=False, default_flow_style=False,
                                                width=1000), encoding="utf-8")

    # 旧 claim 标记 superseded
    flip = 0
    for oid, c in old.items():
        if c.get("status") != "superseded":
            c["status"] = "superseded"
            flip += 1
            # 回写所在文件
    by_file: dict[Path, list[dict]] = {}
    for f in OLD_FILES:
        d = yaml.safe_load(f.read_text(encoding="utf-8"))
        items = d if isinstance(d, list) else (d.get("claims") or [d])
        by_file[f] = items
        for c in items:
            if isinstance(c, dict) and c.get("status") != "superseded":
                c["status"] = "superseded"
    for f, items in by_file.items():
        head = "# 已合并：见 claim-20260621-007.yaml（2026-10-31）\n"
        f.write_text(head + yaml.safe_dump({"claims": items}, allow_unicode=True, sort_keys=False,
                                           default_flow_style=False, width=1000), encoding="utf-8")

    print(f"merged {len(old)} -> {len(merged)} claims")
    print(f"flipped to superseded: {flip}")
    print(f"new file: {NEW_FILE.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
