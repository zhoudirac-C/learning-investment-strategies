#!/usr/bin/env python3
"""每日刷新 Hermes fallback_providers 为 OpenRouter 当前最优免费模型。

思路（借鉴 free-ai-models / hermes-openrouter-free-rotator / free-llm-api-resources）：
1. 拉取公开接口 https://openrouter.ai/api/v1/models（免认证，无需前端 cookie）。
2. 筛选可用作 agent fallback 的免费模型：pricing 全 0、文本输出、支持 tools、
   context >= MIN_CONTEXT，并排除当前 model.default。
3. 排序（智力优先）：
   - 主键：Artificial Analysis intelligence_index 降序。数据源是 OpenRouter 前端
     接口 /api/frontend/v1/models/find（实测免认证可用）返回的 benchmarks 字段，
     经 canonical_slug 与公开接口模型对应；该接口失败/缺分时自动退化；
   - 智力分并列时 agentic_index（agent 场景）降序；
   - 无分模型排在有分模型之后，按 context_length 降序、created 降序兜底。
4. 可用性探测（"免费"≠"可用"）：对智力序前 K 名（默认 count+2）用 provider 的
   key 发 1-token 实测请求；最终排序 = 探测成功（保持智力序）> 未探测 > 探测失败；
   全部失败时维持智力序（大概率是本机限流/网络问题，而非模型不可用）。
4. 重写 ~/.hermes/config.yaml 的 fallback_providers：
   - 受管条目 = provider == PROVIDER（默认 custom_nex-n25），整体替换并置顶；
   - 用户手工添加的其他 provider 条目原样保留；
   - 同时把 default + 新 fallback 并入 providers.<PROVIDER>.available_models_json；
   - API key 不落盘——fallback 条目只引用 provider 名，运行时自动复用
     custom_nex-n25 的 key_env/api_key。
5. 写前自动备份 config.yaml.bak_YYYYMMDD_HHMMSS；内容无变化时不写文件。

使用方式：
    python -m hermes_openrouter_free_fallback            # 正常执行
    python -m hermes_openrouter_free_fallback --dry-run  # 只打印不落盘
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

import yaml

MODELS_URL = "https://openrouter.ai/api/v1/models"
BENCHMARKS_URL = ("https://openrouter.ai/api/frontend/v1/models/find"
                  "?active=true&fmt=cards&output_modalities=text&variant=free")
DEFAULT_CONFIG = Path.home() / ".hermes" / "config.yaml"
DEFAULT_PROVIDER = "custom_nex-n25"
TOP_N = 3
# 置顶名单：名单内模型在同组（探测通过/未探测/失败）内按此顺序优先。
# 注意：置顶救不了探测失败的模型——坏的第一 fallback 没有意义。
PREFER = ["thinkingmachines/inkling:free"]
MIN_CONTEXT = 32768
LOG_FILE = Path(__file__).resolve().parent.parent / "logs" / "openrouter_free_fallback.jsonl"


# ---------------------------------------------------------------- 筛选与排序

def fetch_models(url: str = MODELS_URL, timeout: int = 30) -> list[dict]:
    req = urllib.request.Request(url, headers={"User-Agent": "hermes-free-fallback/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)["data"]


def fetch_benchmarks(url: str = BENCHMARKS_URL, timeout: int = 30) -> dict[str, dict]:
    """拉 OpenRouter 前端接口附带的 Artificial Analysis 指数。

    返回 {permaslug(=canonical_slug): {"intelligence_index": float|None,
    "agentic_index": float|None, ...}}。任何失败都返回 {}，由排序逻辑退化为
    context/created 兜底——benchmark 是增强信号，不是硬依赖。
    """
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "hermes-free-fallback/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.load(resp)["data"]
        out = {}
        for slug, entry in (data.get("benchmarks") or {}).items():
            aa = (entry or {}).get("aa") or {}
            out[slug] = {k: aa.get(k) for k in
                         ("intelligence_index", "coding_index", "agentic_index")}
        return out
    except Exception as e:
        print(f"WARN: benchmark 拉取失败，退化为 context 排序 ({e})", file=sys.stderr)
        return {}


# ---------------------------------------------------------------- 可用性探测

def resolve_api_key(prov_cfg: dict, env_files: list[Path] | None = None) -> str | None:
    """按优先级取 key：环境变量（key_env 指定）→ provider 内联 api_key → env_files。"""
    key_env = prov_cfg.get("key_env")
    if key_env:
        import os
        if os.environ.get(key_env):
            return os.environ[key_env]
    if prov_cfg.get("api_key"):
        return prov_cfg["api_key"]
    if key_env:
        for env_file in env_files or []:
            if not env_file.exists():
                continue
            for line in env_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                if k.strip() == key_env:
                    return v.strip().strip('"').strip("'")
    return None


def probe_model(base_url: str, api_key: str, model_id: str,
                timeout: int = 20) -> dict:
    """发 1-token 请求实测可用性。返回 {ok, status, latency_ms}。

    必须带 HTTP-Referer/X-Title：OpenRouter 会把部分 :free 模型 gate 在
    "agentic harness" 之后（无 Referer 返回 403 "only available on agentic
    harnesses"），而 Hermes 实际请求是带这些头的——探测要模拟真实消费方。
    """
    import time
    body = json.dumps({
        "model": model_id,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 1,
    }).encode()
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}/chat/completions", data=body,
        headers={"Authorization": f"Bearer {api_key}",
                 "Content-Type": "application/json",
                 "HTTP-Referer": "https://hermes-agent.nousresearch.com",
                 "X-Title": "Hermes Agent",
                 "User-Agent": "hermes-free-fallback/1.0"})
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            resp.read()
            return {"ok": True, "status": resp.status,
                    "latency_ms": int((time.monotonic() - t0) * 1000)}
    except urllib.error.HTTPError as e:
        return {"ok": False, "status": e.code,
                "latency_ms": int((time.monotonic() - t0) * 1000)}
    except Exception as e:
        return {"ok": False, "status": None, "error": str(e),
                "latency_ms": int((time.monotonic() - t0) * 1000)}


def select_fallbacks(ranked: list[dict], probes: dict[str, dict],
                     count: int, prefer: list[str] | None = None) -> list[dict]:
    """probe-ok > 未探测 > probe-failed，取前 count。

    组内顺序：PREFER 名单内的模型按名单顺序置顶（只对同组生效——置顶救不了
    探测失败的模型），其余保持 ranked（智力）顺序。
    """
    ok, unknown, failed = [], [], []
    for m in ranked:
        p = probes.get(m["id"])
        if p is None:
            unknown.append(m)
        elif p.get("ok"):
            ok.append(m)
        else:
            failed.append(m)

    def prefer_first(group: list[dict]) -> list[dict]:
        order = {mid: i for i, mid in enumerate(prefer or [])}
        return sorted(group, key=lambda m: (m["id"] not in order,
                                            order.get(m["id"], 0)))

    ordered = prefer_first(ok) + prefer_first(unknown) + prefer_first(failed)
    if not ok and failed:  # 全部探测失败（大概率本机限流/网络问题）→ 维持智力序
        ordered = ranked
    return ordered[:count]


def _is_zero(value) -> bool:
    try:
        return float(value) == 0.0
    except (TypeError, ValueError):
        return False


def filter_eligible(models: list[dict], default_id: str,
                    min_context: int = MIN_CONTEXT) -> list[dict]:
    """免费 + 文本输出 + 支持 tools + 上下文达标，且不是当前 default。"""
    out = []
    for m in models:
        pricing = m.get("pricing") or {}
        if not (_is_zero(pricing.get("prompt")) and _is_zero(pricing.get("completion"))):
            continue
        if not (m.get("architecture") or {}).get("modality", "").endswith("->text"):
            continue
        if "tools" not in (m.get("supported_parameters") or []):
            continue
        if (m.get("context_length") or 0) < min_context:
            continue
        if m.get("id") == default_id:
            continue
        out.append(m)
    return out


def rank_models(models: list[dict], benchmarks: dict[str, dict] | None = None) -> list[dict]:
    """智力优先：AA intelligence_index 降序 → agentic_index 降序；
    无分模型垫底，按 context_length 降序、created 降序兜底。"""
    bench = benchmarks or {}

    def key(m):
        aa = bench.get(m.get("canonical_slug") or "") or {}
        intel = aa.get("intelligence_index")
        agentic = aa.get("agentic_index")
        return (
            intel is not None,
            intel if intel is not None else 0.0,
            agentic if agentic is not None else 0.0,
            m.get("context_length") or 0,
            m.get("created") or 0,
        )

    return sorted(models, key=key, reverse=True)


def build_fallback_entries(models: list[dict], provider: str, base_url: str) -> list[dict]:
    return [{"provider": provider, "base_url": base_url, "model": m["id"]}
            for m in models]


# ---------------------------------------------------------------- 配置更新

def sync_available_models(prov_cfg: dict, model_ids: list[str]) -> bool:
    """把 model_ids 并入 provider 的 available_models_json（保留已有，顺序去重）。"""
    existing = prov_cfg.get("available_models_json") or []
    if isinstance(existing, str):  # 部分 provider 存的是 JSON 字符串
        existing = json.loads(existing)
    seen = {e.get("id") for e in existing}
    changed = False
    for mid in model_ids:
        if mid not in seen:
            existing.append({"id": mid, "name": mid})
            seen.add(mid)
            changed = True
    if changed or "available_models_json" not in prov_cfg:
        prov_cfg["available_models_json"] = existing
    return changed


def apply_updates(cfg: dict, picked: list[dict], provider: str = DEFAULT_PROVIDER) -> bool:
    """把受管 fallback 条目替换为 picked，返回是否有变化。直接原地修改 cfg。"""
    prov = (cfg.get("providers") or {}).get(provider)
    if prov is None:
        raise KeyError(f"providers.{provider} 不存在于 config.yaml")
    base_url = prov.get("base_url") or "https://openrouter.ai/api/v1"

    new_entries = build_fallback_entries(picked, provider=provider, base_url=base_url)
    old = cfg.get("fallback_providers") or []
    user_entries = [e for e in old if e.get("provider") != provider]
    old_managed = [e for e in old if e.get("provider") == provider]

    changed = old_managed != new_entries
    if changed:
        cfg["fallback_providers"] = new_entries + user_entries

    default_id = (cfg.get("model") or {}).get("default") or ""
    ids = ([default_id] if default_id else []) + [m["id"] for m in picked]
    if sync_available_models(prov, ids):
        changed = True
    return changed


def write_config(cfg: dict, config_path: Path) -> Path:
    backup = config_path.with_suffix(
        f".yaml.bak_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    shutil.copy2(config_path, backup)
    config_path.write_text(yaml.dump(cfg, allow_unicode=True, sort_keys=True),
                           encoding="utf-8")
    return backup


def append_log(record: dict) -> None:
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as e:
        print(f"WARN: 写日志失败 {e}", file=sys.stderr)


# ---------------------------------------------------------------- main

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    ap.add_argument("--provider", default=DEFAULT_PROVIDER,
                    help="复用其凭据的 provider 名（默认 custom_nex-n25）")
    ap.add_argument("--count", type=int, default=TOP_N, help="写入的 fallback 数量")
    ap.add_argument("--min-context", type=int, default=MIN_CONTEXT)
    ap.add_argument("--probe-k", type=int, default=0,
                    help="实际探测的候选数（默认 count+2；0 = 默认）")
    ap.add_argument("--no-probe", action="store_true", help="跳过实测探测")
    ap.add_argument("--dry-run", action="store_true", help="只打印，不写 config")
    args = ap.parse_args()

    cfg = yaml.safe_load(args.config.read_text(encoding="utf-8"))
    default_id = (cfg.get("model") or {}).get("default") or ""

    models = fetch_models()
    benchmarks = fetch_benchmarks()
    eligible = filter_eligible(models, default_id=default_id, min_context=args.min_context)
    ranked = rank_models(eligible, benchmarks)

    # 可用性探测：对智力序前 K 名发 1-token 实测请求（复用 provider 的 key）
    probes: dict[str, dict] = {}
    prov = (cfg.get("providers") or {}).get(args.provider) or {}
    api_key = resolve_api_key(prov, env_files=[
        Path(__file__).resolve().parent.parent / ".env",
        Path.home() / ".hermes" / ".env",
    ])
    probe_k = args.probe_k or (args.count + 2)
    if args.no_probe:
        print("跳过探测（--no-probe）")
    elif not api_key:
        print(f"WARN: 找不到 {args.provider} 的 api key，跳过探测", file=sys.stderr)
    else:
        base_url = prov.get("base_url") or "https://openrouter.ai/api/v1"
        for m in ranked[:probe_k]:
            r = probe_model(base_url, api_key, m["id"])
            probes[m["id"]] = r
            mark = "ok" if r["ok"] else f"FAIL({r.get('status') or r.get('error')})"
            print(f"  probe {mark:<12} {r['latency_ms']:>6}ms  {m['id']}")

    picked = select_fallbacks(ranked, probes, args.count, prefer=PREFER)
    if not picked:
        print("ERROR: 没有满足条件的免费模型，config 未改动", file=sys.stderr)
        append_log({"ts": datetime.now().isoformat(), "ok": False,
                    "error": "no eligible models"})
        return 1

    changed = apply_updates(cfg, picked, provider=args.provider)
    ids = [m["id"] for m in picked]
    record = {"ts": datetime.now().isoformat(), "ok": True, "changed": changed,
              "provider": args.provider,
              "fallbacks": [{"id": m["id"],
                             "probe": probes.get(m["id"]),
                             **(benchmarks.get(m.get("canonical_slug") or "") or {})}
                            for m in picked],
              "probes": probes,
              "eligible_total": len(eligible),
              "scored_total": sum(1 for m in eligible
                                  if (benchmarks.get(m.get("canonical_slug") or "") or {})
                                  .get("intelligence_index") is not None)}
    append_log(record)

    print(f"免费候选 {len(eligible)} 个（含 AA 智力分 {record['scored_total']} 个），取前 {len(ids)}：")
    for m in picked:
        aa = benchmarks.get(m.get("canonical_slug") or "") or {}
        intel = aa.get("intelligence_index")
        agentic = aa.get("agentic_index")
        score = (f"intel={intel:>5} agentic={agentic:>5}" if intel is not None
                 else "intel=  无分（按 context 兜底）")
        p = probes.get(m["id"])
        probe = "" if p is None else ("  [实测ok]" if p["ok"] else f"  [实测失败:{p.get('status')}]")
        print(f"  {score}  ctx={m.get('context_length'):>8}  {m['id']}{probe}")
    if args.dry_run:
        print("dry-run：config 未改动")
        return 0
    if not changed:
        print("fallback 链无变化，跳过写入")
        return 0
    backup = write_config(cfg, args.config)
    print(f"config 已更新（备份 {backup.name}）；如 gateway 在运行，需重启/重载后生效")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
