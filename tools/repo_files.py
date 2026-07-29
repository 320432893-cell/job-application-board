#!/usr/bin/env python3
# 职责：枚举仓库内可被逐文件扫描的文件清单(已跟踪 + 未忽略的未跟踪)，供 per-file 扫描器展开命令行。
# 不做什么：不按 zone/trait 过滤、不判断文件该不该扫、不运行任何检查。
# 允许依赖层：标准库、git CLI。
# 谁不应该 import：正式业务代码、测试夹具、应用入口不应 import 本工具层模块。
"""Repository file enumeration for scanners that require explicit filenames."""

from __future__ import annotations

import pathlib
import subprocess
from functools import lru_cache

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _git_names(args: list[str]) -> list[str]:
    """Run a NUL-separated git listing; raise instead of degrading to an empty list.

    Fail-closed on purpose: a scanner handed zero filenames exits 0 and looks green,
    which is exactly the silent-pass failure this module exists to prevent.
    """
    proc = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, check=False)
    if proc.returncode != 0:
        detail = proc.stderr.decode(errors="replace").strip() or f"exit {proc.returncode}"
        raise RuntimeError(f"git {' '.join(args)} failed in {ROOT}: {detail}")
    return [chunk.decode(errors="replace") for chunk in proc.stdout.split(b"\0") if chunk]


@lru_cache(maxsize=1)
def scannable_files() -> tuple[str, ...]:
    """Tracked files plus untracked-but-not-ignored files, deduped and sorted."""
    tracked = _git_names(["ls-files", "-z"])
    untracked = _git_names(["ls-files", "--others", "--exclude-standard", "-z"])
    return tuple(sorted({*tracked, *untracked}))
