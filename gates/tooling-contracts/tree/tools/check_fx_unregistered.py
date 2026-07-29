#!/usr/bin/env python3
# 职责：反向样本——一个没在 registry 登记的检查器，用来证明契约闸能抓出僵尸工具。
# 不做什么：不做任何真实检查。
# 允许依赖层：标准库。
# 谁不应该 import：任何人。
"""Unregistered checker used as a negative sample for the tooling-contract gate."""

from __future__ import annotations

import sys


def main() -> int:
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
