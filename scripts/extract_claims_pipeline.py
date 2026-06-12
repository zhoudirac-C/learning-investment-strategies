#!/usr/bin/env python3
"""
extract_claims_pipeline.py — C2 编排控制器

不调用 LLM，只做：
1. 检查当前状态（step progress）
2. 告诉 Agent 下一步做什么 + 具体要求
3. 跑验证门禁

用法：
  # 启动新流程
  python scripts/extract_claims_pipeline.py start --raw sources/raw/财经/文件名.md

  # 继续流程（Agent 完成一步后调用）
  python scripts/extract_claims_pipeline.py continue

  # 只跑验证（不触发编排）
  python scripts/extract_claims_pipeline.py validate --file temp/claims/step1_raw.json

  # 清理临时文件
  python scripts/extract_claims_pipeline.py done <session_id>

工作流目录: temp/claims/<session_id>/
  session.json     — 会话状态
  step1_raw.json   — Step 1: 提取草稿（宽松格式）
  gate1_result.json — Gate 1 校验结果
  step2_enriched.json — Step 2: 补全股票代码
  gate2_result.json  — Gate 2 校验结果
  step3_yaml/       — Step 3: YAML 文件
  gate3_result.json — Gate 3 校验结果
"""

import json, sys, os, re, uuid, shutil, subprocess
from pathlib import Path
from datetime import datetime

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMP_DIR = REPO_ROOT / "temp" / "claims"
GATE_SCRIPT = REPO_ROOT / "scripts" / "gate_validate_claims.py"

# ── 状态管理 ──────────────────────────────────────────

STATES = {
    "init": "初始化",
    "step1_done": "Step 1 完成，待 Gate 1",
    "gate1_fail": "Gate 1 失败，退回 Step 1",
    "gate1_pass": "Gate 1 通过，待 Step 2",
    "step2_done": "Step 2 完成，待 Gate 2",
    "gate2_fail": "Gate 2 失败，退回 Step 2",
    "gate2_pass": "Gate 2 通过，待 Step 3 (自动)",
    "step3_done": "Step 3 完成，待 Gate 3",
    "gate3_fail": "Gate 3 失败，退回 Step 1",
    "gate3_pass": "Gate 3 通过，待 Step 4",
    "done": "完成",
}


def create_session(raw_path: str) -> str:
    """创建新会话，返回 session_id"""
    session_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]
    sess_dir = TEMP_DIR / session_id
    sess_dir.mkdir(parents=True, exist_ok=True)

    raw_path = str(raw_path)
    if not raw_path.startswith("/"):
        raw_path = str(REPO_ROOT / raw_path)

    session = {
        "session_id": session_id,
        "raw_path": raw_path,
        "raw_basename": Path(raw_path).name,
        "state": "init",
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
        "attempts_step1": 0,
        "attempts_step2": 0,
        "claim_ids": [],
    }
    with open(sess_dir / "session.json", "w") as f:
        json.dump(session, f, ensure_ascii=False, indent=2)
    return session_id


def load_session(session_id: str) -> dict:
    sess_dir = TEMP_DIR / session_id
    with open(sess_dir / "session.json") as f:
        return json.load(f)


def save_session(session: dict):
    sess_dir = TEMP_DIR / session["session_id"]
    session["updated_at"] = datetime.now().isoformat()
    with open(sess_dir / "session.json", "w") as f:
        json.dump(session, f, ensure_ascii=False, indent=2)


# ── 门禁运行 ──────────────────────────────────────────

def run_gate(file_path: str, step: int = 2) -> tuple[bool, str]:
    """运行验证门禁，返回 (通过?, 输出文本)"""
    result = subprocess.run(
        [sys.executable, str(GATE_SCRIPT), "--step", str(step), file_path],
        capture_output=True, text=True, cwd=REPO_ROOT, timeout=30,
    )
    output = result.stdout + result.stderr
    return result.returncode == 0, output


# ── 下一步指令生成 ──────────────────────────────────

def next_action(session: dict) -> dict:
    """根据当前状态，生成 Agent 的下一步指令"""
    state = session["state"]
    sess_dir = TEMP_DIR / session["session_id"]
    raw_name = session["raw_basename"]

    if state == "init":
        return {
            "step": "step1_extract",
            "title": "Step 1: 提取 Claims 草稿",
            "prompt": f"""读取 raw 文件: {session['raw_path']}

逐段阅读全文后，提取核心观点为 claims。

**要求：**
1. 每条 claim 包含 18 个必需字段（id, source_path, source_date, source_type, extracted_at, claim_type, subject, timeframe, statement, evidence_quote, interpretation, confidence, status, intensity, supersedes, contradicts, links, topic）
2. 不要包含 `related_stocks` 和 `tags`（Step 2 补）
3. 宽松格式，先关注内容完整性
4. 写入后运行编排脚本: `python scripts/extract_claims_pipeline.py continue`

**输出位置**: tools 的 write_file 写入 {sess_dir / 'step1_raw.json'}
**格式**: JSON 格式的 claims 列表
""",
            "output_file": str(sess_dir / "step1_raw.json"),
        }

    elif state == "gate1_fail":
        session["attempts_step1"] += 1
        save_session(session)
        result = load_json(sess_dir / "gate1_result.json")
        errors = result.get("errors", [])
        return {
            "step": "step1_retry",
            "title": f"❌ Gate 1 未通过（第 {session['attempts_step1']} 次）— 请修正",
            "prompt": f"""修正以下字段错误，然后重新写入 {sess_dir / 'step1_raw.json'}:

{chr(10).join(errors)}

修正后运行: `python scripts/extract_claims_pipeline.py continue`
""",
            "output_file": str(sess_dir / "step1_raw.json"),
        }

    elif state == "gate1_pass":
        return {
            "step": "step2_enrich",
            "title": "Step 2: 补全股票代码 + related_stocks + tags",
            "prompt": f"""读取 {sess_dir / 'step1_raw.json'}

对每条 claim：

1. **补股票代码**：statement/interpretation 中提到的每家公司，用 6 位数字代码标注 `公司名(6位代码)`
   查询 API: curl -s "https://searchapi.eastmoney.com/api/suggest/get?input=$(python3 -c 'import urllib.parse; print(urllib.parse.quote(\"公司名\"))')&type=14&count=1"
   返回 JSON 中的 `QuotationCodeTable.Data[0].Code` 即为代码

2. **补 related_stocks**：结构化对象格式（不在 links 下，在 claim 顶级）：
   ```yaml
   related_stocks:
   - code: 600118
     name: 中国卫星
     role: 卫星链龙头-主板可交易
   ```
   无标的必须写 `related_stocks: []`

3. **补 tags**：从 subject/statement 提取 3-5 个关键词标签

4. **补 topic**：一句话主题（如果之前没填）

**重要**：
- related_stocks 放在 claim 顶级，不在 links 块内部
- 无标的 claim 写 `related_stocks: []`（标记"已检查"）
- 非主板标的在 role 中标注（如"创业板不可交易/科创板不可交易"）

写入后运行: `python scripts/extract_claims_pipeline.py continue`
""",
            "output_file": str(sess_dir / "step2_enriched.json"),
        }

    elif state == "gate2_fail":
        session["attempts_step2"] += 1
        save_session(session)
        result = load_json(sess_dir / "gate2_result.json")
        errors = result.get("errors", [])
        return {
            "step": "step2_retry",
            "title": f"❌ Gate 2 未通过（第 {session['attempts_step2']} 次）— 请修正",
            "prompt": f"""修正以下错误，然后重新写入 {sess_dir / 'step2_enriched.json'}:

{chr(10).join(errors)}

修正后运行: `python scripts/extract_claims_pipeline.py continue`
""",
            "output_file": str(sess_dir / "step2_enriched.json"),
        }

    elif state == "gate2_pass":
        return {
            "step": "step3_format",
            "title": "Step 3: Python 确定性格式化 → YAML",
            "prompt": f"""编排脚本将自动格式化。运行: `python scripts/extract_claims_pipeline.py continue`
""",
            "auto": True,
        }

    elif state == "gate3_pass":
        return {
            "step": "step4_postprocess",
            "title": "Step 4: 后处理 — 移动 YAML + 更新 wiki / index / commit",
            "prompt": f"""YAML 已生成在 {sess_dir / 'step3_yaml/'}。请完成以下后处理：

1. **核对编号**：检查 knowledge/claims/ 下已有最大编号，将 YAML 移动到正确编号
2. **更新 wiki**：对应的每日复盘 wiki + 专题 wiki（如有）
3. **更新索引**：claims/index.md + wiki/index.md
4. **更新 log**：knowledge/wiki/log.md
5. **Git 提交**：git add 并 commit
6. **汇报**：告诉用户完成了什么
7. **清理**：完成后运行 `python scripts/extract_claims_pipeline.py done {session["session_id"]}` 删除临时文件
""",
            "auto": False,
        }

    elif state == "step3_done":
        return {
            "step": "step4_postprocess",
            "title": "Step 4: 后处理 — 更新 wiki / index / commit",
            "prompt": f"""YAML 已写入 knowledge/claims/。请完成以下后处理：

1. **更新 wiki**：对应的每日复盘 wiki + 专题 wiki（如有）
2. **更新索引**：claims/index.md + wiki/index.md
3. **更新 log**：knowledge/wiki/log.md
4. **Git 提交**：git add 并 commit
5. **汇报**：告诉用户完成了什么
""",
            "auto": False,
        }

    elif state == "done":
        return {
            "step": "done",
            "title": "✅ 全部完成",
            "prompt": "编排流程已完成。",
        }

    return {"step": "error", "title": "未知状态", "prompt": f"state={state}"}


def load_json(path: Path) -> dict:
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"errors": []}


# ── 主流程 ──────────────────────────────────────────

def cmd_start(raw_path: str):
    session_id = create_session(raw_path)
    session = load_session(session_id)
    action = next_action(session)
    print(f"🔨 会话: {session_id}")
    print(f"📄 raw: {session['raw_basename']}")
    print(f"⏭  下一步:")
    print(json.dumps(action, ensure_ascii=False, indent=2))


def cmd_continue(session_id: str = None):
    if session_id:
        sess_dir = TEMP_DIR / session_id
    else:
        # 找最新的未完成会话
        sessions = sorted(TEMP_DIR.glob("*"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not sessions:
            print("❌ 没有找到进行中的会话")
            sys.exit(1)
        sess_dir = sessions[0]
        session_id = sess_dir.name

    session = load_session(session_id)

    # 判断当前应该跑哪个 Gate
    step1_file = sess_dir / "step1_raw.json"
    step2_file = sess_dir / "step2_enriched.json"
    yaml_dir = sess_dir / "step3_yaml"

    # Gate 1: step1 存在且未验过（仅查字段完整性+枚举+原子性）
    if step1_file.exists() and not (sess_dir / "gate1_result.json").exists():
        print(f"🔍 运行 Gate 1（字段完整性+枚举+原子性）...")
        ok, output = run_gate(str(step1_file), step=1)
        with open(sess_dir / "gate1_result.json", "w") as f:
            json.dump({"passed": ok, "output": output, "errors": _parse_errors(output)}, f, ensure_ascii=False)
        if ok:
            print(f"✅ Gate 1 通过")
            session["state"] = "gate1_pass"
        else:
            print(f"❌ Gate 1 失败")
            session["state"] = "gate1_fail"
        save_session(session)
        _print_next(session)
        return

    # Gate 2: step2 存在且未验过
    if step2_file.exists() and not (sess_dir / "gate2_result.json").exists():
        print(f"🔍 运行 Gate 2...")
        ok, output = run_gate(str(step2_file))
        with open(sess_dir / "gate2_result.json", "w") as f:
            json.dump({"passed": ok, "output": output, "errors": _parse_errors(output)}, f, ensure_ascii=False)
        if ok:
            print(f"✅ Gate 2 通过")
            session["state"] = "gate2_pass"
        else:
            print(f"❌ Gate 2 失败")
            session["state"] = "gate2_fail"
        save_session(session)
        _print_next(session)
        return

    # Gate 3: YAML 存在
    if any(yaml_dir.glob("*.yaml")) and not (sess_dir / "gate3_result.json").exists():
        # 对所有 YAML 文件跑门禁
        all_ok = True
        all_errors = []
        for yf in sorted(yaml_dir.glob("*.yaml")):
            ok, output = run_gate(str(yf))
            if not ok:
                all_ok = False
                all_errors.append(f"{yf.name}: {output}")
        with open(sess_dir / "gate3_result.json", "w") as f:
            json.dump({"passed": all_ok, "errors": all_errors}, f, ensure_ascii=False)
        if all_ok:
            print(f"✅ Gate 3 通过")
            session["state"] = "gate3_pass"
        else:
            print(f"❌ Gate 3 失败")
            session["state"] = "gate3_fail"
        save_session(session)
        _print_next(session)
        return

    # Auto Step 3: Step 2 通过，自动格式化
    if session["state"] == "gate2_pass":
        print(f"🔨 自动执行 Step 3: 格式化 YAML...")
        yaml_dir.mkdir(exist_ok=True)
        _auto_format_yaml(str(step2_file), str(yaml_dir))
        session["state"] = "step3_done"
        save_session(session)
        # 递归继续
        cmd_continue(session_id)
        return

    # 检查所有 gate 都过了 → 到 Step 4（Agent 后处理）
    if session["state"] == "gate3_pass":
        _print_next(session)
        return

    # 否则输出当前 next_action
    _print_next(session)


def _print_next(session: dict):
    action = next_action(session)
    print(f"\n⏭  下一步指令:")
    print(json.dumps(action, ensure_ascii=False, indent=2))


def _parse_errors(output: str) -> list[str]:
    lines = output.strip().split("\n")
    errors = [l.strip() for l in lines if l.strip().startswith("-") or "缺" in l or "不在" in l]
    return errors if errors else [output]


def _auto_format_yaml(json_path: str, yaml_out_dir: str):
    """Step 3: 确定性将 JSON claim 格式化为 YAML"""
    import yaml

    with open(json_path) as f:
        enriched = json.load(f)

    yaml_out = Path(yaml_out_dir)
    yaml_out.mkdir(parents=True, exist_ok=True)

    # 按 claim_id 的文件名规则写入
    # 从第一个 claim 的 source_date 推断文件名
    if enriched:
        src_date = enriched[0].get("source_date", datetime.now().strftime("%Y%m%d"))
        # 找到已有最大编号
        existing = list((REPO_ROOT / "knowledge" / "claims").glob(f"claim-{src_date}*.yaml"))
        existing_basenames = [f.name for f in existing]
        # 如果有 session 文件映射，复用编号
        yaml_path = yaml_out / f"claim-{src_date}-output.yaml"
        with open(yaml_path, "w") as f:
            yaml.dump({"claims": enriched}, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

        # Post-process: quote YAML stock codes with leading zeros
        # yaml.dump outputs code: 002971 as bare number → YAML parser sees octal int 2971
        raw = yaml_path.read_text(encoding="utf-8")
        fixed = re.sub(
            r'(?m)^(  - code: )0(\d{5})\s*$',
            r"\1'0\2'",
            raw,
        )
        # Also catch non-leading-zero 6-digit codes that got output as ints
        fixed = re.sub(
            r'(?m)^(  - code: )([1-9]\d{5})\s*$',
            lambda m: f"  - code: '{m.group(2)}'",
            fixed,
        )
        if fixed != raw:
            yaml_path.write_text(fixed, encoding="utf-8")
            print(f"  🔧 自动引号修复: 处理了 stock codes")

        print(f"  📄 YAML 暂存到: {yaml_path}")
        print(f"  ℹ️  最终编号由 Agent 在 Step 4 核对后确认")


def cmd_validate(file: str):
    ok, output = run_gate(file)
    print(output.strip())
    sys.exit(0 if ok else 1)


def cmd_done(session_id: str):
    """清理指定会话的临时文件"""
    sess_dir = TEMP_DIR / session_id
    if not sess_dir.exists():
        print(f"⚠️  会话目录不存在: {sess_dir}")
        sys.exit(1)

    # 确认 YAML 已移动到正式位置
    yaml_dir = sess_dir / "step3_yaml"
    yamls_left = list(yaml_dir.glob("*.yaml")) if yaml_dir.exists() else []
    if yamls_left:
        print(f"⚠️  YAML 尚未移走: {[y.name for y in yamls_left]}")
        print("   请先完成 Step 4（移动 YAML 到 knowledge/claims/）再清理")
        sys.exit(1)

    shutil.rmtree(sess_dir)
    print(f"🧹 临时文件已清理: {sess_dir.name}")

    # 如果 temp/claims/ 为空，连父目录也删
    if TEMP_DIR.exists() and not any(TEMP_DIR.iterdir()):
        TEMP_DIR.rmdir()
        TEMP_DIR.parent.rmdir()  # temp/


def main():
    if len(sys.argv) < 2:
        print("用法:")
        print("  python scripts/extract_claims_pipeline.py start --raw <path>")
        print("  python scripts/extract_claims_pipeline.py continue [session_id]")
        print("  python scripts/extract_claims_pipeline.py validate --file <path>")
        print("  python scripts/extract_claims_pipeline.py done <session_id>")
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "start":
        if "--raw" not in sys.argv:
            print("❌ 缺少 --raw <path>")
            sys.exit(1)
        raw_idx = sys.argv.index("--raw") + 1
        if raw_idx >= len(sys.argv):
            print("❌ --raw 后缺少路径")
            sys.exit(1)
        cmd_start(sys.argv[raw_idx])

    elif cmd == "continue":
        session_id = sys.argv[2] if len(sys.argv) > 2 else None
        cmd_continue(session_id)

    elif cmd == "validate":
        if "--file" not in sys.argv:
            print("❌ 缺少 --file <path>")
            sys.exit(1)
        file_idx = sys.argv.index("--file") + 1
        cmd_validate(sys.argv[file_idx])

    elif cmd == "done":
        if len(sys.argv) < 3:
            print("❌ 缺少 session_id")
            sys.exit(1)
        cmd_done(sys.argv[2])

    else:
        print(f"❌ 未知命令: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    main()
