#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import tempfile
from datetime import date
from pathlib import Path

from qing_investment.glm_vendor import copy_glm_skill, write_vendor_metadata

UPSTREAM_URL = "https://github.com/zai-org/GLM-skills.git"
DEFAULT_COMMIT = "2ecd31c37e75671a4767342ba3a68a84c8f1b848"


def clone_upstream(target: Path, commit: str) -> None:
    subprocess.run(["git", "clone", UPSTREAM_URL, str(target)], check=True)
    subprocess.run(["git", "checkout", commit], cwd=target, check=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, help="Use an existing GLM-skills checkout instead of cloning")
    parser.add_argument("--commit", default=DEFAULT_COMMIT)
    args = parser.parse_args()

    repo = Path.cwd()
    third_party_root = repo / "third_party" / "GLM-skills"
    vendor_root = repo / "skills" / "qing-stock-analysis" / "vendor" / "glmv-stock-analyst"

    if args.source:
        source = args.source.resolve()
        copy_glm_skill(source, third_party_root, vendor_root)
    else:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "GLM-skills"
            clone_upstream(source, args.commit)
            copy_glm_skill(source, third_party_root, vendor_root)

    write_vendor_metadata(
        third_party_root,
        upstream_url="https://github.com/zai-org/GLM-skills",
        commit=args.commit,
        synced_date=date.today().isoformat(),
    )
    print(f"vendored glmv-stock-analyst at {args.commit}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
