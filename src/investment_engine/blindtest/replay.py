"""盲测推理回放：逐日组装 prompt 调 DeepSeek，JSONL 落盘，断点续跑。"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from investment_engine.blindtest.dataset import build_daily_pack, pack_to_prompt
from investment_engine.blindtest.truth import STAGES

DEFAULT_MODEL = "deepseek-chat"
_BASE_URL = "https://api.deepseek.com"
_MAX_DIRECTIONS = 3
_MAX_STOCKS_PER_DIR = 2
_POSTURES = ("趋势", "波段", "右侧确认", "回避")
_MAX_SCENARIOS = 3
_MAX_LIST = 5

PROMPT_VERSION = "v2"

SYSTEM_PROMPT = """你是一个执行已验证方法论的市场分析引擎。基于给定的当日客观数据，独立完成市场复盘判断。
要求：
1. 每个判断必须声明所用的数据项；不得引用任何人物的言论或观点。
2. 可参考给定的推理框架索引（patterns）与术语词典组织推理，在 used_patterns 中登记实际用到的框架 id。
3. 严格输出 JSON（不要输出其他文字）：
{"market_stage": "主升|震荡|调整|恐慌（四选一）",
 "stage_reason": "一句话依据（必须引用当日量能/情绪数据）",
 "scenarios": [{"name": "情形A", "condition": "触发条件", "conclusion": "应对结论", "key": "区分关键变量"}],
 "watch_next": ["下一交易日可观察、可证伪的验证变量"],
 "invalidation": ["本判断的失效条件"],
 "directions": [{"direction_id": "从给定方向池选择，1-3个", "reason": "一句话依据",
                "posture": "趋势|波段|右侧确认|回避（四选一）",
                "stocks": ["该方向下给定股票池中的代码，每方向1-2个"]}],
 "used_patterns": ["pattern_id"]}
4. 没有把握的方向可以不选，宁缺毋滥。scenarios 给 1-2 个互斥情形即可。"""


def build_messages(pack_text: str) -> list[dict]:
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": pack_text},
    ]


def _default_client():
    from openai import OpenAI

    # 兼容仓库 .env 的小写命名（qing_investment Settings 用 deepseek_api_key）
    key = os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("deepseek_api_key")
    if not key:
        raise RuntimeError("缺少 DEEPSEEK_API_KEY 环境变量")
    return OpenAI(api_key=key, base_url=_BASE_URL)


def call_deepseek(messages: list[dict], *, model: str = DEFAULT_MODEL,
                  max_retries: int = 3, client=None) -> str:
    client = client or _default_client()
    last_err: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            resp = client.chat.completions.create(
                model=model, messages=messages, temperature=0,
                response_format={"type": "json_object"},
            )
            return resp.choices[0].message.content
        except Exception as e:  # noqa: BLE001 - 重试后如实记录
            last_err = e
            if attempt < max_retries:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"DeepSeek 调用失败（{max_retries} 次）: {last_err}")


def parse_result(raw: str) -> dict:
    """解析模型输出为规范结构；fence 容忍、字段校验、超限截断。"""
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"输出非 JSON: {raw[:80]!r}") from e
    stage = data.get("market_stage")
    if stage not in STAGES:
        raise ValueError(f"market_stage 非法: {stage!r}")
    directions = []
    for d in (data.get("directions") or [])[:_MAX_DIRECTIONS]:
        if not isinstance(d, dict) or not d.get("direction_id"):
            continue
        posture = str(d.get("posture", ""))
        directions.append({
            "direction_id": str(d["direction_id"]),
            "reason": str(d.get("reason", "")),
            "posture": posture if posture in _POSTURES else "",
            "stocks": [str(s).split(".")[0] for s in (d.get("stocks") or [])[:_MAX_STOCKS_PER_DIR]],
        })
    scenarios = []
    for s in (data.get("scenarios") or [])[:_MAX_SCENARIOS]:
        if not isinstance(s, dict):
            continue
        scenarios.append({
            "name": str(s.get("name", "")),
            "condition": str(s.get("condition", "")),
            "conclusion": str(s.get("conclusion", "")),
            "key": str(s.get("key", "")),
        })
    return {
        "market_stage": stage,
        "stage_reason": str(data.get("stage_reason", "")),
        "scenarios": scenarios,
        "watch_next": [str(w) for w in (data.get("watch_next") or [])[:_MAX_LIST]],
        "invalidation": [str(w) for w in (data.get("invalidation") or [])[:_MAX_LIST]],
        "directions": directions,
        "used_patterns": [str(p) for p in (data.get("used_patterns") or [])],
    }


def _done_dates(out_path: Path) -> set[str]:
    """断点续跑：只把成功（ok=True）的日期视为已完成；error 日期会重跑。"""
    if not out_path.exists():
        return set()
    done = set()
    for line in out_path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("ok"):
            done.add(row["date"])
    return done


def run_replay(days: list[str], *, config_dir, out_path: Path, db_path=None,
               model: str = DEFAULT_MODEL, client=None, sleep_s: float = 0.5) -> dict:
    """逐日回放。已完成日期跳过（断点续跑）；单日失败记 error 继续。"""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    done = _done_dates(out_path)
    stats = {"done": 0, "skipped": 0, "error": 0}
    with out_path.open("a", encoding="utf-8") as fh:
        for day in days:
            if day in done:
                stats["skipped"] += 1
                continue
            try:
                pack = build_daily_pack(day, config_dir=Path(config_dir), db_path=db_path)
                text = pack_to_prompt(pack)  # 内含防泄漏断言
                raw = call_deepseek(build_messages(text), model=model, client=client)
                result = parse_result(raw)
                fh.write(json.dumps(
                    {"date": day, "ok": True, "result": result, "raw": raw,
                     "prompt_version": PROMPT_VERSION},
                    ensure_ascii=False) + "\n")
                stats["done"] += 1
            except Exception as e:  # noqa: BLE001 - 单日失败不阻断全量
                fh.write(json.dumps(
                    {"date": day, "ok": False, "error": str(e)[:200]},
                    ensure_ascii=False) + "\n")
                stats["error"] += 1
            fh.flush()
            time.sleep(sleep_s)
    return stats
