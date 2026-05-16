#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: run_glm_fetch.py <stock-code> [extra args...]", file=sys.stderr)
        return 2
    skill_root = Path(__file__).resolve().parents[1]
    fetch_script = skill_root / "vendor" / "glmv-stock-analyst" / "scripts" / "fetch_all.py"
    python_bin = skill_root / "vendor" / "glmv-stock-analyst" / "scripts" / "venv" / "bin" / "python"
    command = [str(python_bin if python_bin.exists() else sys.executable), str(fetch_script), *sys.argv[1:]]
    return subprocess.run(command, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
