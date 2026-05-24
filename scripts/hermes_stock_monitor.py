#!/usr/bin/env python3

import subprocess
import sys
import os


REPO_ROOT = os.environ.get(
    "HERMES_REPO_ROOT",
    "/Users/cong.zhou/Documents/quantitative/learning-investment-strategies",
)


def main():
    command = ["uv", "run", "python", "scripts/stock_monitor.py"] + sys.argv[1:]
    return subprocess.call(command, cwd=REPO_ROOT)


if __name__ == "__main__":
    raise SystemExit(main())
