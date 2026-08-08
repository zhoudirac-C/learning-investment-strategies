"""knowledge/industry-chains/ 的读写。save/load 双向强制 schema 校验。"""
from __future__ import annotations

from pathlib import Path

import yaml

from investment_engine.industry_chain.schema import ChainSchemaError, validate_chain


def default_base_dir() -> Path:
    from qing_investment.paths import repo_root

    return repo_root() / "knowledge" / "industry-chains"


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
