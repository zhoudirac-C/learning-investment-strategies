#!/usr/bin/env python3
"""批量从 UP raw 文件中抽取推理模式，写入 framework/reasoning-patterns.yaml。

策略：
1. 快速扫描：按文件名关键词（复盘/视频）+ 文件大小筛选候选文件
2. LLM 提取：对候选文件逐个调用 LLM，识别推理链
3. 去重合并：新发现的模式与已有模式比对，避免重复

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

# 候选文件筛选关键词（文件名中包含这些词的优先处理）
PRIORITY_KEYWORDS = [
    "复盘", "视频", "早盘", "午盘", "周复盘",
    "产业链", "拆解", "BOM", "深度",
]

# 已有的 pattern_ids（用于去重）
EXISTING_PATTERNS = {
    "upstream_price_cycle_qualify",
    "upstream_beneficiary_screening",
    "sector_mainline_judgment",
    "bom_value_migration",
}

# LLM 提取 prompt
EXTRACTION_PROMPT = """你是投资分析专家。以下是一位A股博主（青枫浦上Q）的分析文章。
请判断这篇内容中是否包含**可复用的推理模式**（即：博主如何从A推到B的思维步骤，而非结论观点）。

判断标准：
- 博主的分析是否有明确的推理步骤（≥3步）
- 推理步骤是否涉及板块/产业/个股的分析逻辑
- 这些推理步骤是否可复用于同类主题

如果**没有**清晰的推理模式，返回：{"has_pattern": false, "reason": "原因"}

如果**有**推理模式，返回以下JSON（严格格式）：

{
  "has_pattern": true,
  "pattern_id": "简短的英文ID（小写+下划线）",
  "name": "中文名称（15字以内）",
  "description": "一句话描述这个推理模式",
  "applicable_themes": ["主题1", "主题2"],
  "reasoning_chain": [
    {
      "step": 1,
      "name": "步骤名称（10字以内）",
      "question": "这个步骤要回答的核心问题",
      "UP_logic": "博主在这个步骤中的典型思考方式（引用原文核心逻辑，50字以内）",
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
- pattern_id 不要与已有重复：upstream_price_cycle_qualify, upstream_beneficiary_screening, sector_mainline_judgment, bom_value_migration

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
    """对单个文件提取推理模式。"""
    try:
        content = filepath.read_text(encoding="utf-8")
    except Exception as e:
        print(f"[extract] Failed to read {filepath.name}: {e}")
        return None

    # 截断到 8000 字符（复盘类文章核心在前半部分）
    content = content[:8000]

    # 跳过纯动态/简讯类（标题或正文开头没有分析性语言）
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
        # 尝试直接解析
        result = json.loads(response)
    except json.JSONDecodeError:
        # 尝试从 markdown 代码块中提取
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
    required = ["pattern_id", "name", "reasoning_chain"]
    for field in required:
        if field not in result:
            print(f"  [warn] {filepath.name}: missing required field '{field}'")
            return None

    chain = result["reasoning_chain"]
    if not isinstance(chain, list) or len(chain) < 2:
        print(f"  [warn] {filepath.name}: reasoning_chain too short ({len(chain) if isinstance(chain, list) else 'not list'})")
        return None

    # 去重检查
    pid = result["pattern_id"]
    if pid in EXISTING_PATTERNS:
        print(f"  [skip] {filepath.name}: pattern_id '{pid}' already exists")
        return None

    # 添加 source_raw 和 source_date
    result["source_raw"] = [str(filepath.relative_to(REPO_ROOT))]
    # 从文件名提取日期
    date_match = re.search(r'(?:20)?(\d{2}-\d{2}-\d{2})', filepath.name)
    result["source_date"] = date_match.group(0) if date_match else "unknown"

    print(f"  [found] {filepath.name}: pattern '{pid}' - {result['name']} "
          f"({len(chain)} steps)")
    return result


def merge_patterns(existing: list[dict], new: dict) -> list[dict]:
    """将新推理模式合并到已有列表（去重）。"""
    existing_ids = {p.get("pattern_id", "") for p in existing}
    new_id = new.get("pattern_id", "")
    if new_id in existing_ids:
        return existing
    # 移除提取时添加的临时字段
    clean = {k: v for k, v in new.items()
             if k not in ("has_pattern", "source_date")}
    return existing + [clean]


def main():
    parser = argparse.ArgumentParser(description="从 UP raw 文件批量抽取推理模式")
    parser.add_argument("--dry-run", action="store_true", help="只扫描预览，不提取")
    parser.add_argument("--single", type=str, help="处理单篇文件（文件名或路径）")
    parser.add_argument("--max", type=int, default=20, help="最多处理的文件数（默认20）")
    parser.add_argument("--incremental", action="store_true", help="增量模式（跳过已处理）")
    args = parser.parse_args()

    state = load_state()
    existing_patterns, yaml_data = load_existing_patterns()

    print(f"=== 推理模式批量抽取 ===")
    print(f"已有模式: {len(existing_patterns)} 条")
    print(f"已处理文件: {len(state['processed_files'])} 个")

    # 单篇模式
    if args.single:
        single_path = RAW_DIR / args.single
        if not single_path.exists():
            # 尝试模糊匹配
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

            # 写入 YAML
            merged = merge_patterns(existing_patterns, result)
            yaml_data["patterns"] = merged
            yaml_data["updated_at"] = datetime.now().strftime("%Y-%m-%d")
            with open(PATTERNS_FILE, "w", encoding="utf-8") as f:
                yaml.dump(yaml_data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
            print(f"\n已写入 {PATTERNS_FILE}，当前共 {len(merged)} 条推理模式")
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
    new_patterns = 0
    processed_count = 0

    for i, filepath in enumerate(to_process, 1):
        print(f"\n[{i}/{len(to_process)}] {filepath.name}")
        result = extract_pattern_from_file(filepath, llm)

        # 标记已处理
        state["processed_files"].append(filepath.name)
        processed_count += 1

        if result:
            existing_patterns = merge_patterns(existing_patterns, result)
            new_patterns += 1

            # 每发现一个新模式就写入（防止中断丢失）
            yaml_data["patterns"] = existing_patterns
            yaml_data["updated_at"] = datetime.now().strftime("%Y-%m-%d")
            with open(PATTERNS_FILE, "w", encoding="utf-8") as f:
                yaml.dump(yaml_data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

        # 保存状态
        state["total_patterns_found"] = len(existing_patterns) - 4  # 减去最初4条
        save_state(state)

        # 避免 API 限流
        if i < len(to_process):
            time.sleep(2)

    print(f"\n=== 完成 ===")
    print(f"处理文件: {processed_count}")
    print(f"新模式: {new_patterns}")
    print(f"总模式: {len(existing_patterns)}")
    print(f"输出文件: {PATTERNS_FILE}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
