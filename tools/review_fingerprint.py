#!/usr/bin/env python3
# 职责：为审查事实包绑定当前 Git 状态，防止复用过期缓存。
# 不做什么：不修改工作树、不解释改动风险。
# 允许依赖层：标准库、Git。
# 谁不应该 import：正式业务代码、测试夹具、应用入口不应 import 本工具。
"""Stable input fingerprint for generated review facts."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any


def command_bytes(root: Path, args: list[str]) -> bytes:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, check=False).stdout


def untracked_content(root: Path) -> bytes:
    payload = bytearray()
    for raw_name in command_bytes(root, ["ls-files", "--others", "--exclude-standard", "-z"]).split(b"\0"):
        if not raw_name:
            continue
        name = os.fsdecode(raw_name)
        path = root / name
        payload.extend(raw_name)
        payload.extend(b"\0")
        try:
            # 保留 os.readlink 的理由：指纹要哈希 symlink 目标的原始字符串。Path.readlink() 会归一化(`./x`→`x`、去尾斜杠)，
            # 让两个可区分的目标算出同一指纹，改软链后缓存不失效——这是闸被悄悄放宽，不是风格问题。
            payload.extend(os.readlink(path).encode("utf-8") if path.is_symlink() else path.read_bytes())  # noqa: PTH115
        except OSError:
            payload.extend(b"<unreadable>")
        payload.extend(b"\0")
    return bytes(payload)


def report_fingerprint(root: Path, scope: str) -> str:
    digest = hashlib.sha256()
    digest.update(scope.encode("utf-8"))
    digest.update(b"\0")
    digest.update(command_bytes(root, ["rev-parse", "HEAD"]))
    # Git diff covers staged and unstaged tracked edits; untracked files need explicit content hashing.
    digest.update(command_bytes(root, ["diff", "--binary", "HEAD"]))
    digest.update(untracked_content(root))
    return digest.hexdigest()


def cached_report(path: Path, root: Path, *, scope: str = "") -> dict[str, Any] | None:
    if command_bytes(root, ["rev-parse", "--is-inside-work-tree"]).strip() != b"true":
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if (
        not isinstance(data, dict)
        or (scope and data.get("scope") != scope)
        or (scope and data.get("input_fingerprint") != report_fingerprint(root, scope))
    ):
        return None
    return data
