#!/usr/bin/env python3
"""
Qdrant 索引脚本的监控包装器。
在每次 index_claims_to_qdrant.py 运行前后记录：
- 时间戳
- 系统可用内存
- 运行耗时
- 完整异常堆栈（如果出错）

用法：
  PYTHONUNBUFFERED=1 .venv/bin/python scripts/index_claims_to_qdrant_monitored.py

位置：scripts/index_claims_to_qdrant_monitored.py
日志：logs/qdrant-index-monitor.log（自动轮转，保留最近 50 条）
"""
import os
import sys
import time
import json
import subprocess
from datetime import datetime
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
LOG_FILE = LOG_DIR / "qdrant-index-monitor.log"
MAX_ENTRIES = 50  # 保留的日志条数

def get_free_memory_mb() -> int:
    """读取 /proc/meminfo 获取可用内存 (MB)。"""
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    parts = line.split()
                    return int(parts[1]) // 1024
    except Exception:
        pass
    return -1

def get_total_memory_mb() -> int:
    """读取总内存 (MB)。"""
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    parts = line.split()
                    return int(parts[1]) // 1024
    except Exception:
        pass
    return -1

def load_log() -> list[dict]:
    """读取已有日志。"""
    if LOG_FILE.exists():
        try:
            with open(LOG_FILE, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, Exception):
            pass
    return []

def save_log(entries: list[dict]):
    """写入日志（保持 MAX_ENTRIES）。"""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    # 保留最近的 MAX_ENTRIES 条
    if len(entries) > MAX_ENTRIES:
        entries = entries[-MAX_ENTRIES:]
    with open(LOG_FILE, "w") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)

def record_entry(result: dict):
    """记录单次运行并写文件。"""
    log = load_log()
    log.append({
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        **result,
    })
    save_log(log)

def tail_log(n: int = 10) -> str:
    """查看最近 N 条日志。"""
    log = load_log()
    if not log:
        return "（无日志）"
    lines = []
    for entry in log[-n:]:
        ts = entry.get("timestamp", "?")
        status = entry.get("status", "?")
        mem = entry.get("mem_free_mb", "?")
        total = entry.get("mem_total_mb", "?")
        elapsed = entry.get("elapsed_sec", "?")
        claims = entry.get("claims_indexed", "?")
        error = entry.get("error", "")
        line = f"[{ts}] {status} | mem={mem}/{total}MB | {elapsed}s | claims={claims}"
        if error:
            line += f" | ERROR: {error[:120]}"
        lines.append(line)
    return "\n".join(lines)


if __name__ == "__main__":
    # 解析参数
    args = sys.argv[1:]
    # 如果直接运行此脚本，自动添加 --monitor 标志
    if "--tail" in args:
        idx = args.index("--tail")
        n = int(args[idx + 1]) if idx + 1 < len(args) else 10
        print(tail_log(n))
        sys.exit(0)
    
    is_analyze = "--analyze" in args
    if is_analyze:
        log = load_log()
        total = len(log)
        errors = [e for e in log if e.get("status") == "error"]
        successes = [e for e in log if e.get("status") == "success"]
        print(f"总运行次数: {total}")
        print(f"  成功: {len(successes)}")
        print(f"  失败: {len(errors)}")
        if successes:
            avg_time = sum(e.get("elapsed_sec", 0) for e in successes) / len(successes)
            avg_mem = sum(e.get("mem_free_mb", 0) for e in successes) / len(successes)
            print(f"  平均耗时: {avg_time:.1f}s")
            print(f"  平均可用内存: {avg_mem:.0f}MB")
        if errors:
            print(f"\n最近 5 次失败:")
            for e in errors[-5:]:
                print(f"  [{e['timestamp']}] {e.get('error','?')[:200]}")
        sys.exit(0)

    # 构造真实命令
    script_dir = Path(__file__).resolve().parent
    index_script = script_dir / "index_claims_to_qdrant.py"
    cmd = [sys.executable, str(index_script)] + [a for a in args if a not in ("--monitor",)]

    # 记录开始
    t0 = time.time()
    mem_before = get_free_memory_mb()
    mem_total = get_total_memory_mb()
    print(f"[monitor] 开始索引 | 可用内存: {mem_before}/{mem_total}MB")
    print(f"[monitor] 命令: {' '.join(cmd)}\n")

    # 运行
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        elapsed = time.time() - t0
        mem_after = get_free_memory_mb()

        stdout = result.stdout.strip()
        stderr = result.stderr.strip()

        # 打印输出
        if stdout:
            print(stdout)
        if stderr:
            print("STDERR:", stderr, file=sys.stderr)

        if result.returncode == 0:
            # 尝试解析索引数量
            claims_count = "?"
            for line in stdout.split("\n"):
                if "Indexed" in line and "/" in line:
                    parts = line.split("/")
                    if len(parts) >= 2:
                        claims_count = parts[0].replace("Indexed ", "").strip()
                        break
                if "✅ Indexed" in line:
                    parts = line.split("✅ Indexed ")
                    if len(parts) >= 2:
                        claims_count = parts[1].split()[0]

            entry = {
                "status": "success",
                "elapsed_sec": round(elapsed, 1),
                "mem_free_mb": mem_after,
                "mem_total_mb": mem_total,
                "claims_indexed": claims_count,
                "error": "",
            }
            print(f"\n[monitor] ✅ 成功 | {elapsed:.1f}s | 可用内存: {mem_after}/{mem_total}MB | claims: {claims_count}")
        else:
            # 提取最后一段错误信息
            error_msgs = []
            for line in stderr.split("\n")[-20:]:
                if "Error" in line or "error" in line or "Exception" in line or "Traceback" in line:
                    error_msgs.append(line)
            error_detail = " | ".join(error_msgs[-5:]) if error_msgs else stderr[-300:]

            entry = {
                "status": "error",
                "elapsed_sec": round(elapsed, 1),
                "mem_free_mb": mem_after,
                "mem_total_mb": mem_total,
                "claims_indexed": "?",
                "error": error_detail[:300],
                "full_stderr": stderr[-1000:],
            }
            print(f"\n[monitor] ❌ 失败 | {elapsed:.1f}s | 可用内存: {mem_after}/{mem_total}MB", file=sys.stderr)
            if error_detail:
                print(f"[monitor] 错误: {error_detail[:200]}", file=sys.stderr)

    except subprocess.TimeoutExpired:
        elapsed = time.time() - t0
        entry = {
            "status": "timeout",
            "elapsed_sec": round(elapsed, 1),
            "mem_free_mb": get_free_memory_mb(),
            "mem_total_mb": mem_total,
            "claims_indexed": "?",
            "error": "超时(>300s)",
        }
        print(f"[monitor] ⏰ 超时 | {elapsed:.1f}s")
    except Exception as e:
        elapsed = time.time() - t0
        entry = {
            "status": "crash",
            "elapsed_sec": round(elapsed, 1),
            "mem_free_mb": get_free_memory_mb(),
            "mem_total_mb": mem_total,
            "claims_indexed": "?",
            "error": str(e)[:300],
        }
        print(f"[monitor] 💥 崩溃 | {elapsed:.1f}s | {e}")

    # 记录
    record_entry(entry)
    print(f"[monitor] 日志已写入: {LOG_FILE}")
