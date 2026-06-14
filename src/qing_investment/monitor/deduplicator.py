"""B站动态增量 diff 与 claims 去重.

功能:
1. 对比本地缓存，仅新内容入 claims pipeline
2. 内存缓存最近 50 条 claims，已处理的跳过
3. 日志记录每次 diff 结果

设计参考: docs/task/T20260614-004-architecture-remaining-v2.md §2.3.3
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class DiffResult:
    """Diff 结果."""

    has_new: bool
    new_claims: list[dict] = field(default_factory=list)
    skipped_claims: list[dict] = field(default_factory=list)
    diff_log: str = ""


class BilibiliClaimsDeduplicator:
    """B站 claims 去重器.

    使用方式:
        dedup = BilibiliClaimsDeduplicator(cache_dir=Path("temp/bilibili_diff"))
        result = dedup.diff(new_claims)
        if result.has_new:
            process(result.new_claims)
    """

    # 内存缓存最近 50 条 claims 的指纹
    MEMORY_CACHE_SIZE: int = 50

    def __init__(self, cache_dir: Path | None = None) -> None:
        self._cache_dir = cache_dir or Path("temp/bilibili_diff")
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._cache_file = self._cache_dir / "processed_claims.json"

        # 内存缓存: claim_fingerprint -> claim_dict
        self._memory_cache: dict[str, dict] = {}
        self._load_cache()

    def diff(self, claims: list[dict]) -> DiffResult:
        """对比新 claims，返回需要去重的结果.

        Args:
            claims: 从 B站动态提取的 claims 列表

        Returns:
            DiffResult: 包含 new_claims（新）和 skipped_claims（重复）
        """
        new_claims: list[dict] = []
        skipped_claims: list[dict] = []
        diff_lines: list[str] = []

        for claim in claims:
            fingerprint = self._fingerprint(claim)

            if fingerprint in self._memory_cache:
                skipped_claims.append(claim)
                diff_lines.append(f"  SKIP: {self._claim_summary(claim)} (指纹匹配)")
            else:
                new_claims.append(claim)
                self._memory_cache[fingerprint] = claim
                diff_lines.append(f"  NEW:  {self._claim_summary(claim)}")

        # 限制内存缓存大小
        if len(self._memory_cache) > self.MEMORY_CACHE_SIZE:
            # 保留最近 50 条（按插入顺序）
            items = list(self._memory_cache.items())
            self._memory_cache = dict(items[-self.MEMORY_CACHE_SIZE:])

        # 保存缓存
        self._save_cache()

        diff_log = (
            f"B站 Claims Diff 结果:\n"
            f"  输入: {len(claims)} 条\n"
            f"  新:   {len(new_claims)} 条\n"
            f"  跳过: {len(skipped_claims)} 条\n"
            + "\n".join(diff_lines)
        )
        logger.info(diff_log)

        return DiffResult(
            has_new=len(new_claims) > 0,
            new_claims=new_claims,
            skipped_claims=skipped_claims,
            diff_log=diff_log,
        )

    def _fingerprint(self, claim: dict) -> str:
        """生成 claim 指纹（用于去重）.

        基于: claim_type + 核心陈述内容（去除空格和标点）
        """
        claim_type = claim.get("claim_type", "")
        statement = claim.get("statement", "")
        # 规范化：去除空格、标点，取前 80 字符
        normalized = re.sub(r"\s+|[，。！？、；：\"'（）【】]", "", statement)[:80]
        content = f"{claim_type}:{normalized}"
        return hashlib.md5(content.encode("utf-8")).hexdigest()[:16]

    def _claim_summary(self, claim: dict) -> str:
        """生成 claim 摘要（用于日志）."""
        claim_type = claim.get("claim_type", "unknown")
        statement = claim.get("statement", "")[:40]
        return f"[{claim_type}] {statement}..."

    def _load_cache(self) -> None:
        """从文件加载缓存."""
        if self._cache_file.exists():
            try:
                data = json.loads(self._cache_file.read_text(encoding="utf-8"))
                self._memory_cache = data.get("fingerprints", {})
                logger.info(f"Loaded {len(self._memory_cache)} cached claim fingerprints")
            except Exception as e:
                logger.warning(f"Failed to load cache: {e}")
                self._memory_cache = {}

    def _save_cache(self) -> None:
        """保存缓存到文件."""
        try:
            data = {
                "fingerprints": self._memory_cache,
                "updated_at": datetime.now().isoformat(),
            }
            self._cache_file.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            logger.warning(f"Failed to save cache: {e}")

    def clear_cache(self) -> None:
        """清空缓存."""
        self._memory_cache.clear()
        if self._cache_file.exists():
            self._cache_file.unlink()
        logger.info("Cache cleared")


# ── 便捷函数 ──────────────────────────────────────────────────────

def deduplicate_bilibili_claims(
    claims: list[dict],
    cache_dir: Path | None = None,
) -> DiffResult:
    """一键去重函数."""
    dedup = BilibiliClaimsDeduplicator(cache_dir=cache_dir)
    return dedup.diff(claims)
