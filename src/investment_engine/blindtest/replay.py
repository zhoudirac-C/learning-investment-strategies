"""盲测推理回放：逐日组装 prompt 调 DeepSeek，JSONL 落盘，断点续跑。"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime
from pathlib import Path

from investment_engine.blindtest.dataset import build_daily_pack, pack_to_prompt
from investment_engine.blindtest.truth import STAGES

DEFAULT_MODEL = "deepseek-chat"
_BASE_URL = "https://api.deepseek.com"
_MAX_DIRECTIONS = 3
_MAX_STOCKS_PER_DIR = 2
_POSTURES = ("趋势", "波段", "右侧确认", "回避")
# 性质定性（P1-1）：定性今日量价性质，区别于阶段二分（market_stage）
_NATURES = ("放量攻击", "缩量企稳", "主动降速", "内生瓦解", "外力扰动", "方向转折")
# 方向连续性（P0-3）：相对昨日该方向的加强/退潮/新增/维持
_TRENDS = ("加强", "退潮", "新增", "维持")
_MAX_SCENARIOS = 3
_MAX_LIST = 5

PROMPT_VERSION = "v5"

_LLM_CALL_LOG = Path(__file__).resolve().parents[3] / "log" / "llm_calls.jsonl"


def _int_or_none(v) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _log_llm_call(entry: dict) -> None:
    """LLM 调用台账（log/llm_calls.jsonl）。尽力而为，永不阻断主流程。"""
    try:
        _LLM_CALL_LOG.parent.mkdir(parents=True, exist_ok=True)
        with _LLM_CALL_LOG.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001 - 台账失败不影响调用
        pass

SYSTEM_PROMPT = """你是一个执行已验证方法论的市场分析引擎。基于给定的当日客观数据，独立完成市场复盘判断。
要求：
1. 每个判断必须声明所用的数据项；不得引用任何人物的言论或观点。
2. core_patterns 为全量判据框架（含推理步骤与证伪条件）：判定市场阶段（sentiment_cycle）、方向主线（mainline_identification）与操作建议（position_by_cycle）时必须逐条对照其步骤，并在 stage_reason / directions 的 reason / operation 中体现对照结果；patterns 仅为扩展框架索引。实际用到的框架 id 登记在 used_patterns。
3. 严格输出 JSON（不要输出其他文字）：
{"market_stage": "主升|震荡|调整|恐慌（四选一）",
 "nature": "放量攻击|缩量企稳|主动降速|内生瓦解|外力扰动|方向转折（六选一，定性今日量价性质：放量攻击=放量上涨进攻；缩量企稳=缩量止跌；主动降速=放量阴线但主动换手消化浮盈、非方向转折；内生瓦解=高位抱团断板情绪内部瓦解；外力扰动=消息面/外部利空；方向转折=趋势反转）",
 "stage_reason": "一句话依据（必须引用当日量能/情绪数据）",
 "scenarios": [{"name": "情形A", "condition": "触发条件", "conclusion": "应对结论", "key": "区分关键变量"}],
 "watch_next": ["下一交易日可观察、可证伪的验证变量"],
 "invalidation": ["本判断的失效条件"],
 "directions": [{"direction_id": "从给定方向池选择，1-3个", "reason": "一句话依据",
                "posture": "趋势|波段|右侧确认|回避（四选一）",
                "trend": "加强|退潮|新增|维持（四选一，标注相对昨日该方向的连续性）",
                "stocks": ["该方向下给定股票池中的代码，每方向1-2个"]}],
 "used_patterns": ["pattern_id"],
 "operation": {"position": "周期位置（反弹初期|反弹中段|反弹超预期|高位兑现|趋势下跌|磨底期|震荡调整，七选一）",
                "action": "该位置对应的操作动作（仓位/买卖节奏/克制），由 position 推导，不由看多看空决定",
                "basis": "定位该 position 的证据（引用量能/情绪/反弹天数/连续性）"},
 "cycle_state": {"rebound_day": "反弹第几天（整数或 null，从底部结构形成日算起）",
                "bottom_level": "底部结构级别（30/60/90/120min/daily 或空）",
                "bottom_date": "底部结构形成日（YYYY-MM-DD 或空）",
                "theoretical_window": "理论反弹窗口（如 '6-8天' 或空）",
                "note": "周期状态备注（是否接近窗口末期/结构证伪/上级别压制）"}}
4. 没有把握的方向可以不选，宁缺毋滥。scenarios 给 1-2 个互斥情形即可。
5. 若 user 内容含 prior_day（上一交易日盲判摘要），必须体现连续判断：在 stage_reason 中对照昨日判断说明今日是否兑现/证伪昨日 watch_next，并在 directions 的 trend 字段标注方向加强/退潮；不得把单日当作孤立快照。
6. 数据单位约定：成交额以「亿」计（数据键名如「两市成交额_亿」），成交量以「万手」计（键名「成交量万手」），两者不可混用；watch_next/scenarios 里的量能阈值必须写「成交额(亿)」或「成交量(万手)」，禁止出现「成交额突破X万手」这类跨单位表述。
7. operation 必须用 position_by_cycle 推导：先定位周期位置(position)，再按「状态→动作」映射匹配 action，并用三条元规则（仓位纪律高于判断/确定性决定力度/特定状态最优动作是克制）校验；禁止脱离状态写「逢低关注/降低仓位」这类无状态依赖的套话。
8. cycle_state 追踪反弹/调整的连续天数（不要每天孤立判断）：若 user 数据含 structure（上证多级别顶底结构），结合 prior_day 的 cycle_state——①找 structure 中 state=formed/divergence 的 bottom 结构，其 time 即反弹起点、级别对应 theoretical_days 即理论窗口；②rebound_day = 起点到今日的交易日数（prior_day 已有 rebound_day 则 +1）；③无 bottom 结构时 rebound_day 填 null，note 说明处于调整/无明确周期；若 structure 与 prior_day 均无周期信息，输出空对象 {}。"""


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
                  max_retries: int = 3, client=None, tag: str | None = None) -> str:
    client = client or _default_client()
    last_err: Exception | None = None
    prompt_chars = sum(len(str(m.get("content", ""))) for m in messages)
    for attempt in range(1, max_retries + 1):
        t0 = time.monotonic()
        try:
            resp = client.chat.completions.create(
                model=model, messages=messages, temperature=0,
                response_format={"type": "json_object"},
            )
            content = resp.choices[0].message.content
            usage = getattr(resp, "usage", None)
            _log_llm_call({
                "ts": datetime.now().isoformat(timespec="seconds"),
                "event": "ok", "tag": tag, "model": model, "attempt": attempt,
                "latency_s": round(time.monotonic() - t0, 2),
                "prompt_chars": prompt_chars,
                "prompt_tokens": _int_or_none(getattr(usage, "prompt_tokens", None)),
                "completion_tokens": _int_or_none(getattr(usage, "completion_tokens", None)),
                "reply_chars": len(content or ""),
            })
            return content
        except Exception as e:  # noqa: BLE001 - 重试后如实记录
            last_err = e
            _log_llm_call({
                "ts": datetime.now().isoformat(timespec="seconds"),
                "event": "error", "tag": tag, "model": model, "attempt": attempt,
                "latency_s": round(time.monotonic() - t0, 2),
                "prompt_chars": prompt_chars,
                "error": str(e)[:200],
            })
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
    nature = str(data.get("nature", ""))
    if nature not in _NATURES:
        nature = ""  # nature 非评分字段，非法值清空（不阻断）
    directions = []
    for d in (data.get("directions") or [])[:_MAX_DIRECTIONS]:
        if not isinstance(d, dict) or not d.get("direction_id"):
            continue
        posture = str(d.get("posture", ""))
        trend = str(d.get("trend", ""))
        directions.append({
            "direction_id": str(d["direction_id"]),
            "reason": str(d.get("reason", "")),
            "posture": posture if posture in _POSTURES else "",
            "trend": trend if trend in _TRENDS else "",
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
    op = data.get("operation")
    if not isinstance(op, dict):
        op = {}
    operation = {
        "position": str(op.get("position", "")),
        "action": str(op.get("action", "")),
        "basis": str(op.get("basis", "")),
    }
    cs = data.get("cycle_state")
    if not isinstance(cs, dict):
        cs = {}
    cycle_state = {
        "rebound_day": cs.get("rebound_day"),
        "bottom_level": str(cs.get("bottom_level", "")),
        "bottom_date": str(cs.get("bottom_date", "")),
        "theoretical_window": str(cs.get("theoretical_window", "")),
        "note": str(cs.get("note", "")),
    }
    return {
        "market_stage": stage,
        "nature": nature,
        "stage_reason": str(data.get("stage_reason", "")),
        "scenarios": scenarios,
        "watch_next": [str(w) for w in (data.get("watch_next") or [])[:_MAX_LIST]],
        "invalidation": [str(w) for w in (data.get("invalidation") or [])[:_MAX_LIST]],
        "directions": directions,
        "used_patterns": [str(p) for p in (data.get("used_patterns") or [])],
        "operation": operation,
        "cycle_state": cycle_state,
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
                raw = call_deepseek(build_messages(text), model=model, client=client,
                                    tag="blindtest_replay")
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
