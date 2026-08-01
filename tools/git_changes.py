#!/usr/bin/env python3
# 职责：把 git 的变更清单(改动/删除/重命名/未跟踪)按项目声明的语言取出来,供 inventory 与各检查器复用。
# 不做什么：不解释 zone、不建导入图、不判断检查结果。
# 允许依赖层：标准库、project_model。
# 谁不应该 import：正式业务代码、测试夹具、应用入口不应 import 本工具层模块。
"""Git change lists, scoped to the languages the project declares.

从 inventory.py 拆出来:那份文件顶到了超行数棘轮,而 `ruff format` 还要再加 19 行 —— 棘轮登记的
split_when 要的就是这类外迁,不是把基线放大。这一族(git 调用 + 变更清单)本身也是独立关注点。

后缀一律跟着 project_model 走。写死 *.py 会让非 Python 项目的清单恒空,所有 *-changed 闸
看到零个文件、一律绿灯 —— 整档静默不检查。
"""

from __future__ import annotations

import functools
import subprocess
from pathlib import Path, PurePosixPath

from project_model import load_project_model, source_suffixes

ROOT = Path(__file__).resolve().parents[1]
# `git diff --name-status -M` 的重命名行有三列:状态 + 旧路径 + 新路径。
RENAME_NAME_STATUS_FIELDS = 3


def git(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-c", "core.quotePath=false", *args], cwd=ROOT, text=True, capture_output=True, check=False
    )


@functools.cache
def git_prefix() -> str:
    proc = git(["rev-parse", "--show-prefix"])
    return proc.stdout.strip().strip("/")


def strip_git_prefix(path_name: str) -> str:
    prefix = git_prefix()
    if prefix and path_name.startswith(f"{prefix}/"):
        return path_name[len(prefix) + 1 :]
    return path_name


def changed_file_names(pathspecs: list[str] | tuple[str, ...] = ()) -> set[str]:
    names: set[str] = set()
    path_args = ["--", *pathspecs] if pathspecs else []
    for args in (
        ["diff", "--relative", "--name-only", "--diff-filter=ACMR", *path_args],
        ["diff", "--relative", "--cached", "--name-only", "--diff-filter=ACMR", *path_args],
        ["ls-files", "--others", "--exclude-standard", *path_args],
    ):
        proc = git(args)
        if proc.returncode != 0:
            continue
        names.update(strip_git_prefix(line.strip()) for line in proc.stdout.splitlines() if line.strip())
    return {name for name in names if (ROOT / name).exists()}


def changed_source_names() -> set[str]:
    """改动过的源码文件名。后缀按模型声明取,写死 *.py 会让非 Python 项目的整个 changed 档
    静默不检查(候选清单恒空 → 每道 *-changed 闸都绿)。判据与证据见 tests/test_changed_scope_languages.py。"""
    suffixes = source_suffixes(load_project_model())
    names = changed_file_names(tuple(f"*{suffix}" for suffix in suffixes))
    return {name for name in names if PurePosixPath(name).suffix in suffixes}


def removed_source_names() -> set[str]:
    suffixes = source_suffixes(load_project_model())  # 同理:不写死 *.py,后缀跟着模型走
    globs = [f"*{suffix}" for suffix in suffixes]
    names: set[str] = set()
    for scope in ([], ["--cached"]):
        base = ["diff", "--relative", *scope]
        proc = git([*base, "--name-only", "--diff-filter=D", "--", *globs])
        if proc.returncode == 0:
            names.update(strip_git_prefix(line.strip()) for line in proc.stdout.splitlines() if line.strip())
        proc = git([*base, "--name-status", "--diff-filter=R", "--", *globs])
        if proc.returncode == 0:
            for line in proc.stdout.splitlines():
                parts = line.split("\t")
                if len(parts) >= RENAME_NAME_STATUS_FIELDS:
                    names.add(strip_git_prefix(parts[1].strip()))
    return {name for name in names if PurePosixPath(name).suffix in suffixes}
