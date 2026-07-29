#!/usr/bin/env python3
# 职责：统一托管旧项目的基线扩张审批，避免每个检查器各开一条更新后门。
# 不做什么：不替人判断债务是否合理，不把能直接写仓库的人当作安全边界。
# 允许依赖层：标准库、project_model、Git HEAD。
# 谁不应该 import：正式业务代码、测试夹具、应用入口不应 import 本工具。
"""Shared baseline-ratchet policy for native and managed projects."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

from project_model import ProjectModel, load_project_model, managed_baseline_path

ROOT = Path(__file__).resolve().parents[1]

# "可判定的清除条件"的共同判据:凡是登记债务/放行/零消费者的地方都用这一份,不各写一份。
VAGUE_WORDS = ("暂时", "以后", "待定", "回头", "慢慢", "再说", "未定", "看情况", "tbd", "todo")


def vague_hits(text: str) -> list[str]:
    """清除条件里出现的含糊词;非空 = 这条件判不出真假,不算登记。"""
    return [word for word in VAGUE_WORDS if word in text.lower()]


def relative(path: Path, *, root: Path = ROOT) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def head_json(path: Path, *, root: Path = ROOT) -> dict[str, Any] | None:
    proc = subprocess.run(
        ["git", "show", f"HEAD:{relative(path, root=root)}"], cwd=root, text=True, capture_output=True, check=False
    )
    if proc.returncode != 0:
        return None
    try:
        value = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"[baseline] committed baseline is invalid: {relative(path, root=root)}: {exc}") from exc
    if not isinstance(value, dict):
        raise SystemExit(f"[baseline] committed baseline must be a JSON object: {relative(path, root=root)}")
    return value


def require_expansion_approval(
    path: Path, *, expansion: bool, action: str, model: ProjectModel | None = None, root: Path = ROOT
) -> None:
    """Native projects can only tighten; managed expansion needs explicit owner intent."""
    if not expansion:
        return
    model = model or load_project_model(root / ".ai-config" / "project_model.toml")
    mode = model.metadata.governance_mode
    baseline_name = relative(path, root=root)
    if mode == "foreign":
        raise SystemExit(f"[baseline] foreign project cannot {action} baselines")
    if mode == "native":
        raise SystemExit(
            f"[baseline] native project cannot expand {baseline_name}; fix the new debt or keep the prior baseline"
        )
    declared = [*model.governance.managed_baselines, model.governance.inventory_violation_baseline]
    registered = {managed_baseline_path(value) for value in declared}  # 声明是 .ai-config 相对,这里比的是仓库相对
    if baseline_name not in registered:
        raise SystemExit(f"[baseline] managed baseline is not declared in project_model: {baseline_name}")
    reason = os.environ.get("ONCALL_MANAGED_BASELINE_REASON", "").strip()
    if os.environ.get("ONCALL_ALLOW_MANAGED_BASELINE_UPDATE") != "1" or not reason:
        raise SystemExit(
            f"[baseline] managed {action} expands {baseline_name}; requires ONCALL_ALLOW_MANAGED_BASELINE_UPDATE=1 "
            "and ONCALL_MANAGED_BASELINE_REASON"
        )
