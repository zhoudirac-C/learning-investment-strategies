#!/usr/bin/env python3

import subprocess


REPO_ROOT = "/Users/cong.zhou/Documents/quantitative/learning-investment-strategies"


def main():
    command = [
        "uv",
        "run",
        "python",
        "scripts/stock_monitor.py",
        "--live-analysis-context",
        "--ignore-trading-time",
    ]
    return subprocess.call(command, cwd=REPO_ROOT)


if __name__ == "__main__":
    raise SystemExit(main())
