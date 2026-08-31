"""knowledge/industry-chains/ 的读写。save/load 双向强制 schema 校验。"""
from __future__ import annotations

from pathlib import Path

import yaml

from investment_engine.industry_chain.schema import ChainSchemaError, validate_chain


def default_base_dir() -> Path:
    from qing_investment.paths import repo_root

    return repo_root() / "knowledge" / "industry-chains"


# 注入 LLM context 时的自描述说明（cron trigger 专属 prompt 不含字段文档，
# 数据自带用法说明保证所有触发路径都能正确使用）
CHAIN_STATES_NOTE = (
    "产业链知识库状态。分析板块异动/方向轮动时先查：该板块属于哪条链、"
    "链处于什么阶段、时机建议做哪个环节。阶段口径：阶段0-观察=不介入；"
    "阶段1-启动期=可右侧确认介入；阶段2-加速期=不追高等分歧回踩；"
    "阶段3-分歧期=等回踩确认；阶段4-见顶期=退出。available=false 时"
    "明确说明知识库不可用，不得编造链阶段。"
)


def _base(base_dir: Path | None) -> Path:
    return Path(base_dir) if base_dir is not None else default_base_dir()


def chain_dir(chain_id: str, *, base_dir: Path | None = None) -> Path:
    return _base(base_dir) / chain_id


def save_chain(
    chain: dict,
    *,
    base_dir: Path | None = None,
    expect_id: str | None = None,
) -> Path:
    """校验通过后落盘 chain.yaml；返回写入路径。"""
    if expect_id is not None and chain.get("chain_id") != expect_id:
        raise ChainSchemaError(
            f"chain_id 不一致: 文件内 {chain.get('chain_id')!r}，期望 {expect_id!r}"
        )
    validate_chain(chain)
    out_dir = chain_dir(chain["chain_id"], base_dir=base_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "chain.yaml"
    path.write_text(
        yaml.safe_dump(chain, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return path


def load_chain(chain_id: str, *, base_dir: Path | None = None) -> dict:
    path = chain_dir(chain_id, base_dir=base_dir) / "chain.yaml"
    if not path.exists():
        raise FileNotFoundError(f"产业链不存在: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return validate_chain(data)


def list_chains(*, base_dir: Path | None = None) -> list[str]:
    base = _base(base_dir)
    if not base.exists():
        return []
    return sorted(
        p.name for p in base.iterdir()
        if p.is_dir() and (p / "chain.yaml").exists()
    )


def stage0_only_codes(*, base_dir: Path | None = None) -> set[str]:
    """只属于阶段0-观察链的标的代码（6 位无后缀）——factor_rank 标的池过滤用。

    标的同属多条链时，只要有一条链不在阶段0就保留（宽容）。
    """
    active: set[str] = set()
    watch: set[str] = set()
    for cid in list_chains(base_dir=base_dir):
        try:
            c = load_chain(cid, base_dir=base_dir)
        except Exception:  # noqa: BLE001 - 单链损坏跳过
            continue
        codes = {str(m.get("code")).zfill(6) for m in c.get("mappings") or []
                 if m.get("code") is not None and str(m.get("code")).strip()}
        if (c.get("current_stage") or "阶段0-观察") == "阶段0-观察":
            watch |= codes
        else:
            active |= codes
    return watch - active


def chain_states_view(*, max_stocks: int = 3,
                      base_dir: Path | None = None) -> list[dict]:
    """19 链的 compact 状态视图（供 LLM context 注入）。

    每链只取 chain_id/name/current_stage/stage_confidence/时机建议/前 max_stocks
    个标的。单链损坏跳过，不阻断整体。代码兜底 zfill(6)（YAML 可能把 002409
    读成 int）。
    """
    out: list[dict] = []
    for cid in list_chains(base_dir=base_dir):
        try:
            c = load_chain(cid, base_dir=base_dir)
        except Exception:  # noqa: BLE001 - 单链损坏跳过
            continue
        timing = c.get("timing") if isinstance(c.get("timing"), dict) else {}
        stocks = [f"{m.get('name')}({str(m.get('code')).zfill(6)})"
                  for m in (c.get("mappings") or [])[:max_stocks]]
        out.append({
            "chain_id": c.get("chain_id"),
            "name": c.get("name"),
            "current_stage": c.get("current_stage") or "阶段0-观察",
            "stage_confidence": c.get("stage_confidence"),
            "timing": timing.get("current_recommendation"),
            "stocks": stocks,
        })
    return out

