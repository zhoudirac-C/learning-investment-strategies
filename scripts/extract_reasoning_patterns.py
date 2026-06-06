#!/usr/bin/env python3
"""批量从 UP raw 文件中抽取推理模式，归入现有通用框架。

策略（Phase 6 改造）：
1. 快速扫描：按文件名关键词 + 文件大小筛选候选文件
2. LLM 提取：对候选文件调用 LLM，识别推理链
3. 框架归类：LLM 判断归入哪个通用框架（upstream_cycle/ai_industry_chain/...）
4. 合并入框架：作为对应框架的 example 追加，合并 themes 和 source_raw

用法：
    # 预览模式：只扫描不提取
    .venv/bin/python scripts/extract_reasoning_patterns.py --dry-run

    # 单篇测试
    .venv/bin/python scripts/extract_reasoning_patterns.py --single "复盘：26-05-31：科技震荡消化拥挤，被动元件全面进入周期上行.md"

    # 全量提取（后台运行）
    nohup .venv/bin/python scripts/extract_reasoning_patterns.py --max 50 > logs/reasoning_extraction.log 2>&1 &

    # 增量提取（只处理新文件）
    .venv/bin/python scripts/extract_reasoning_patterns.py --incremental
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml

# 项目根目录
REPO_ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = REPO_ROOT / "sources" / "raw" / "财经"
PATTERNS_FILE = REPO_ROOT / "framework" / "reasoning-patterns.yaml"
STATE_FILE = REPO_ROOT / ".reasoning_extraction_state.json"

# 候选文件筛选关键词
PRIORITY_KEYWORDS = [
    "复盘", "视频", "早盘", "午盘", "周复盘",
    "产业链", "拆解", "BOM", "深度",
]

# 通用框架列表（用于LLM判断归入）
FRAMEWORKS = [
    {"id": "upstream_cycle", "name": "上游涨价周期分析框架", "desc": "用于上游周期品（MLCC、PCB、存储、有色、化工等）涨价逻辑、周期位置判断"},
    {"id": "mainline_identification", "name": "市场主线识别与切换判断框架", "desc": "用于判断市场主线、板块强度、主线切换"},
    {"id": "sector_rotation", "name": "板块轮动与扩散分析框架", "desc": "用于分析板块轮动、补涨、高低切、题材持续性"},
    {"id": "macro_transmission", "name": "宏观传导链分析框架", "desc": "用于分析宏观事件、海外映射、政策变化对A股影响"},
    {"id": "sentiment_cycle", "name": "市场情绪周期分析框架", "desc": "用于判断市场情绪周期阶段、冰点/高潮、仓位策略"},
    {"id": "technical_timing", "name": "技术择时分析框架", "desc": "用于技术面买卖点、支撑压力、K线形态、波浪结构"},
    {"id": "earnings_analysis", "name": "个股业绩拆解与定性分析框架", "desc": "用于个股财报、业绩分析、估值判断"},
    {"id": "ai_industry_chain", "name": "AI产业链传导分析框架", "desc": "用于AI技术突破/新产品对产业链各环节的传导"},
    {"id": "operation_strategy", "name": "操作策略与仓位管理框架", "desc": "用于具体操作建议、仓位、风控、止盈止损"},
    {"id": "others", "name": "其他独立分析框架", "desc": "用于无法归入上述框架的独立场景"},
]

# LLM 提取 prompt（Phase 6：增加 matched_framework 字段）
EXTRACTION_PROMPT = """你是投资分析专家。以下是一位A股博主（青枫浦上Q）的分析文章。
请从这篇文章中提取**可复用的推理模式**（即：博主如何从A推到B的思维步骤，而非结论观点）。

判断标准：
- 博主的分析是否有明确的推理步骤（≥3步）
- 推理步骤是否涉及板块/产业/个股的分析逻辑
- 这些推理步骤是否可复用于同类主题

提取完成后，必须判断该推理模式应该**归入哪个现有通用框架**。

现有10个通用框架：
- upstream_cycle: 上游涨价周期分析框架 — 用于上游周期品（MLCC、PCB、存储、有色、化工等）涨价逻辑、周期位置判断
- mainline_identification: 市场主线识别与切换判断框架 — 用于判断市场主线、板块强度、主线切换
- sector_rotation: 板块轮动与扩散分析框架 — 用于分析板块轮动、补涨、高低切、题材持续性
- macro_transmission: 宏观传导链分析框架 — 用于分析宏观事件、海外映射、政策变化对A股影响
- sentiment_cycle: 市场情绪周期分析框架 — 用于判断市场情绪周期阶段、冰点/高潮、仓位策略
- technical_timing: 技术择时分析框架 — 用于技术面买卖点、支撑压力、K线形态、波浪结构
- earnings_analysis: 个股业绩拆解与定性分析框架 — 用于个股财报、业绩分析、估值判断
- ai_industry_chain: AI产业链传导分析框架 — 用于AI技术突破/新产品对产业链各环节的传导
- operation_strategy: 操作策略与仓位管理框架 — 用于具体操作建议、仓位、风控、止盈止损
- others: 其他独立分析框架 — 用于无法归入上述框架的独立场景

如果**没有**清晰的推理模式，返回：{"has_pattern": false, "reason": "原因"}

如果**有**推理模式，返回以下JSON（严格格式）：

{
  "has_pattern": true,
  "pattern_id": "简短的英文ID（小写+下划线），如 mlcc_price_cycle_20260531",
  "name": "中文名称（20字以内），概括这个具体推理案例",
  "matched_framework": "从上述10个框架ID中选择最匹配的一个",
  "merge_suggestion": "解释为什么归入这个框架（30字以内）",
  "applicable_themes": ["主题1", "主题2", "最多5个核心主题"],
  "reasoning_chain": [
    {
      "step": 1,
      "name": "步骤名称（15字以内）",
      "question": "这个步骤要回答的核心问题",
      "UP_logic": "博主在这个步骤中的典型思考方式（引用原文核心逻辑，60字以内）",
      "evidence_sources": ["数据来源1", "数据来源2"]
    }
  ],
  "risk_factors": ["证伪条件1", "证伪条件2"],
  "confidence_indicators": ["增强信心的信号1", "增强信心的信号2"]
}

注意：
- 只抽取【推理模式】，不要抽取结论观点
- reasoning_chain 中的步骤必须来自原文，不要编造
- 如果原文只有观点没有推理步骤，返回 has_pattern: false
- matched_framework 必须且只能从10个框架ID中选择，不能自创
- applicable_themes 只保留最相关的3-5个核心主题，不要罗列过多

原文内容：
---
{content}
---"""


def load_state() -> dict:
    """加载提取状态（已处理的文件列表）。"""
    if STATE_FILE.exists():
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {"processed_files": [], "last_run": None, "total_patterns_found": 0}


def save_state(state: dict) -> None:
    state["last_run"] = datetime.now(timezone.utc).isoformat()
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def load_existing_patterns() -> tuple[list[dict], dict]:
    """加载已有推理模式和原始 YAML 数据。"""
    if not PATTERNS_FILE.exists():
        return [], {"patterns": [], "updated_at": ""}
    with open(PATTERNS_FILE, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data.get("patterns", []), data


def get_llm_client():
    """获取 LLM 客户端。"""
    sys.path.insert(0, str(REPO_ROOT / "src"))
    from qing_investment.agent.tools.llm_client import get_llm_client as _get
    return _get()


def scan_candidates(state: dict, incremental: bool = False) -> list[Path]:
    """扫描候选文件，返回待处理的文件路径列表（按优先级排序）。"""
    if not RAW_DIR.exists():
        print(f"[scan] Raw directory not found: {RAW_DIR}")
        return []

    all_files = sorted(RAW_DIR.glob("*.md"))
    processed = set(state.get("processed_files", []))

    # 筛选候选文件
    candidates: list[tuple[int, Path]] = []
    for f in all_files:
        fname = f.name
        fstat = f.stat()

        # 跳过已处理的
        if incremental and fname in processed:
            continue

        # 跳过太小的文件（大概率是动态转发，没有推理链）
        if fstat.st_size < 500:
            continue

        # 计算优先级分数
        score = 0
        for kw in PRIORITY_KEYWORDS:
            if kw in fname:
                score += 10
        # 文件越大越可能包含推理（复盘类通常 3000-15000 字节）
        score += min(fstat.st_size // 1000, 5)

        if score > 0:
            candidates.append((score, f))

    # 按分数降序
    candidates.sort(key=lambda x: x[0], reverse=True)

    files = [f for _, f in candidates]
    print(f"[scan] Total raw files: {len(all_files)}, "
          f"candidates: {len(files)}, already processed: {len(processed)}")
    return files


def extract_pattern_from_file(filepath: Path, llm_client) -> dict | None:
    """对单个文件提取推理模式（Phase 6 版）。"""
    try:
        content = filepath.read_text(encoding="utf-8")
    except Exception as e:
        print(f"[extract] Failed to read {filepath.name}: {e}")
        return None

    # 截断到 8000 字符
    content = content[:8000]

    # 跳过纯动态/简讯类
    first_500 = content[:500]
    analysis_indicators = ["因为", "所以", "判断", "逻辑", "周期", "主线", "板块", "策略"]
    if not any(w in first_500 for w in analysis_indicators):
        print(f"  [skip] {filepath.name}: no analysis indicators in first 500 chars")
        return None

    prompt = EXTRACTION_PROMPT.replace("{content}", content)

    try:
        response = llm_client.invoke(prompt).content
    except Exception as e:
        print(f"  [error] LLM call failed for {filepath.name}: {e}")
        return None

    # 提取 JSON
    try:
        result = json.loads(response)
    except json.JSONDecodeError:
        match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', response, re.DOTALL)
        if match:
            try:
                result = json.loads(match.group(1))
            except json.JSONDecodeError:
                print(f"  [warn] {filepath.name}: JSON parse failed in code block")
                return None
        else:
            print(f"  [warn] {filepath.name}: no JSON found in response")
            return None

    if not result.get("has_pattern"):
        print(f"  [skip] {filepath.name}: {result.get('reason', 'no pattern detected')}")
        return None

    # 验证必要字段
    required = ["pattern_id", "name", "matched_framework", "reasoning_chain"]
    for field in required:
        if field not in result:
            print(f"  [warn] {filepath.name}: missing required field '{field}'")
            return None

    chain = result["reasoning_chain"]
    if not isinstance(chain, list) or len(chain) < 2:
        print(f"  [warn] {filepath.name}: reasoning_chain too short")
        return None

    # 验证 matched_framework 是否合法
    valid_framework_ids = {fw["id"] for fw in FRAMEWORKS}
    matched_fw = result.get("matched_framework", "").strip()
    if matched_fw not in valid_framework_ids:
        print(f"  [warn] {filepath.name}: invalid matched_framework '{matched_fw}', using 'others'")
        result["matched_framework"] = "others"

    # 添加 source_raw 和 source_date
    result["source_raw"] = [str(filepath.relative_to(REPO_ROOT))]
    date_match = re.search(r'(?:20)?(\d{2}-\d{2}-\d{2})', filepath.name)
    result["source_date"] = date_match.group(0) if date_match else "unknown"

    print(f"  [found] {filepath.name}: pattern '{result['pattern_id']}' -> framework '{result['matched_framework']}' "
          f"({len(chain)} steps)")
    return result


def merge_pattern_into_framework(existing_patterns: list[dict], new_pattern: dict) -> list[dict]:
    """将新提取的pattern合并到对应的通用框架中（Phase 6 核心逻辑）。

    策略：
    1. 如果 matched_framework 存在且匹配现有框架 → 作为example加入
    2. 如果 matched_framework 不存在或为 null → 作为独立pattern保留
    3. 合并 applicable_themes（去重）
    4. 更新 source_raw 记录
    """
    matched_fw = new_pattern.get("matched_framework", "").strip()
    if not matched_fw:
        # 无匹配框架，作为独立pattern保留
        clean = {k: v for k, v in new_pattern.items() if k not in ("has_pattern",)}
        return existing_patterns + [clean]

    # 找到匹配的框架
    for p in existing_patterns:
        if p.get("pattern_id") == matched_fw:
            # 构建example
            example = {
                "pattern_id": new_pattern.get("pattern_id", ""),
                "name": new_pattern.get("name", ""),
                "source_raw": new_pattern.get("source_raw", []),
                "key_themes": new_pattern.get("applicable_themes", []),
                "reasoning_chain": new_pattern.get("reasoning_chain", []),
                "risk_factors": new_pattern.get("risk_factors", []),
                "confidence_indicators": new_pattern.get("confidence_indicators", []),
                "merge_suggestion": new_pattern.get("merge_suggestion", ""),
            }

            # 添加到examples
            if "examples" not in p:
                p["examples"] = []
            p["examples"].append(example)

            # 合并applicable_themes
            existing_themes = set(p.get("applicable_themes", []))
            new_themes = set(new_pattern.get("applicable_themes", []))
            p["applicable_themes"] = sorted(existing_themes | new_themes)

            # 合并source_raw
            existing_sources = set(p.get("source_raw", []))
            new_sources = set(new_pattern.get("source_raw", []))
            p["source_raw"] = sorted(existing_sources | new_sources)

            print(f"    [merge] -> framework '{matched_fw}' (now {len(p['examples'])} examples)")
            return existing_patterns

    # 如果matched_framework找不到对应框架，作为独立pattern保留
    print(f"    [warn] matched_framework '{matched_fw}' not found, keeping as standalone")
    clean = {k: v for k, v in new_pattern.items() if k not in ("has_pattern",)}
    return existing_patterns + [clean]


def main():
    parser = argparse.ArgumentParser(description="从 UP raw 文件批量抽取推理模式（Phase 6 框架归类版）")
    parser.add_argument("--dry-run", action="store_true", help="只扫描预览，不提取")
    parser.add_argument("--single", type=str, help="处理单篇文件（文件名或路径）")
    parser.add_argument("--max", type=int, default=20, help="最多处理的文件数（默认20）")
    parser.add_argument("--incremental", action="store_true", help="增量模式（跳过已处理）")
    args = parser.parse_args()

    state = load_state()
    existing_patterns, yaml_data = load_existing_patterns()

    print(f"=== 推理模式批量抽取（Phase 6: 框架归类）===")
    print(f"已有框架: {len(existing_patterns)} 个")
    print(f"已处理文件: {len(state['processed_files'])} 个")

    # 单篇模式
    if args.single:
        single_path = RAW_DIR / args.single
        if not single_path.exists():
            matches = list(RAW_DIR.glob(f"*{args.single}*"))
            if not matches:
                print(f"[error] File not found: {args.single}")
                return 1
            single_path = matches[0]

        print(f"\n处理: {single_path.name}")
        llm = get_llm_client()
        result = extract_pattern_from_file(single_path, llm)
        if result:
            print(f"\n--- 发现推理模式 ---")
            print(json.dumps(result, ensure_ascii=False, indent=2))

            # 合并到框架
            merged = merge_pattern_into_framework(existing_patterns, result)
            yaml_data["patterns"] = merged
            yaml_data["updated_at"] = datetime.now().strftime("%Y-%m-%d")
            with open(PATTERNS_FILE, "w", encoding="utf-8") as f:
                yaml.dump(yaml_data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
            print(f"\n已写入 {PATTERNS_FILE}")
        else:
            print("未发现推理模式")
        return 0

    # 扫描候选文件
    candidates = scan_candidates(state, incremental=args.incremental)

    if args.dry_run:
        print(f"\n=== 预览模式（--dry-run）===")
        for i, f in enumerate(candidates[:args.max], 1):
            print(f"  {i:3d}. {f.name} ({f.stat().st_size}B)")
        print(f"\n共 {min(len(candidates), args.max)} 个候选文件（总数 {len(candidates)}）")
        return 0

    # 全量/增量提取
    to_process = candidates[:args.max]
    print(f"\n开始提取，共 {len(to_process)} 个文件")

    llm = get_llm_client()
    new_examples = 0
    new_standalone = 0
    processed_count = 0

    for i, filepath in enumerate(to_process, 1):
        print(f"\n[{i}/{len(to_process)}] {filepath.name}")
        result = extract_pattern_from_file(filepath, llm)

        # 标记已处理
        state["processed_files"].append(filepath.name)
        processed_count += 1

        if result:
            existing_patterns = merge_pattern_into_framework(existing_patterns, result)
            if result.get("matched_framework") in {p.get("pattern_id") for p in existing_patterns}:
                new_examples += 1
            else:
                new_standalone += 1

            # 每发现一个新模式就写入（防止中断丢失）
            yaml_data["patterns"] = existing_patterns
            yaml_data["updated_at"] = datetime.now().strftime("%Y-%m-%d")
            with open(PATTERNS_FILE, "w", encoding="utf-8") as f:
                yaml.dump(yaml_data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

        # 保存状态
        state["total_patterns_found"] = len(existing_patterns)
        save_state(state)

        # 避免 API 限流
        if i < len(to_process):
            time.sleep(2)

    print(f"\n=== 完成 ===")
    print(f"处理文件: {processed_count}")
    print(f"新增examples: {new_examples}")
    print(f"新增独立pattern: {new_standalone}")
    print(f"总框架数: {len(existing_patterns)}")
    print(f"输出文件: {PATTERNS_FILE}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
