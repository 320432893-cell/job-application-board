#!/usr/bin/env python3
# 职责：承载 `check.py changed` 的 git 改动调度逻辑。
# 不做什么：不运行独立 CLI；不保存检查结果；不决定 registry 阶段。
# 允许依赖层：标准库、由 tools/check.py 传入的薄回调。
# 谁不应该 import：正式业务代码、测试夹具、应用入口不应 import 本工具。
"""Changed-scope dispatcher used by tools/check.py."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

REQUIRED_ENV_KEYS = (
    "ROOT",
    "backend_contract_changed",
    "changed_when_items",
    "collect_changed_names",
    "is_changed_ruff_path",
    "is_code_file",
    "is_code_name",
    "is_direct_pytest_file",
    "is_source_name",
    "name_matches",
    "path_trigger_matches",
    "project_contract_patterns",
    "rel",
    "run_command",
    "run_path_triggers",
    "run_registered_item",
)


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def env_from(source: Mapping[str, Any]) -> dict[str, Any]:
    missing = [key for key in REQUIRED_ENV_KEYS if key not in source]
    if missing:
        raise RuntimeError(f"check_changed env missing keys: {', '.join(missing)}")
    return {key: source[key] for key in REQUIRED_ENV_KEYS}


def _run_stage_items(env: Mapping[str, Any], event: str) -> int:
    """跑某个 changed_when 事件下的 registry 条目，返回最后一个非零返回码。"""
    status = 0
    for item in env["changed_when_items"](event):
        status = env["run_registered_item"](item) or status
    return status


def _run_python_and_source_items(
    env: Mapping[str, Any],
    changed_python_names: list[str],
    changed_source_names: list[str],
) -> int:
    status = 0
    registry_items: list[str] = []
    if changed_python_names:
        registry_items.extend(env["changed_when_items"]("python"))
    if changed_source_names:
        registry_items.extend(env["changed_when_items"]("source"))
    for item in _dedupe(registry_items):
        status = env["run_registered_item"](item) or status
    return status


def _run_ruff_items(env: Mapping[str, Any], ruff_python_paths: list[Any]) -> int:
    status = 0
    status = env["run_command"](
        "changed:ruff-check",
        ["uv", "run", "ruff", "check", "--no-fix", "--force-exclude", *[env["rel"](path) for path in ruff_python_paths]],
    ) or status
    status = env["run_command"](
        "changed:ruff-format",
        ["uv", "run", "ruff", "format", "--check", *[env["rel"](path) for path in ruff_python_paths]],
    ) or status
    return _run_stage_items(env, "ruff_python") or status


def run(env: Mapping[str, Any]) -> int:
    rc, changed_names = env["collect_changed_names"]()
    if rc != 0:
        return rc
    root = env["ROOT"]
    changed_paths = [root / name for name in changed_names]
    existing_changed_paths = [path for path in changed_paths if path.exists()]
    code_paths = [path for path in changed_paths if env["is_code_file"](path)]
    changed_python_names = [name for name in changed_names if name.endswith(".py")]
    changed_source_names = [name for name in changed_names if env["is_source_name"](name)]
    ruff_python_paths = [path for path in code_paths if path.suffix == ".py" and env["is_changed_ruff_path"](path)]
    contract_changed = any(env["name_matches"](name, env["project_contract_patterns"]()) for name in changed_names)
    backend_contract_changed = env["backend_contract_changed"](changed_names)
    code_names_for_triggers = [name for name in changed_names if env["is_code_name"](name)]
    trigger_changed = env["path_trigger_matches"](changed_names)
    if (
        not code_names_for_triggers
        and not changed_python_names
        and not changed_source_names
        and not contract_changed
        and not backend_contract_changed
        and not trigger_changed
    ):
        print("[check] changed: no changed code files")
        return 0

    status = _run_python_and_source_items(env, changed_python_names, changed_source_names)
    if ruff_python_paths:
        status = _run_ruff_items(env, ruff_python_paths) or status

    existing_code_paths = [path for path in existing_changed_paths if env["is_code_file"](path)]
    if existing_code_paths:
        status = _run_stage_items(env, "code") or status

    code_names = {env["rel"](path) for path in existing_code_paths}
    direct_tests = sorted(name for name in code_names if env["is_direct_pytest_file"](name))
    if direct_tests:
        status = _run_stage_items(env, "test") or status
        status = env["run_command"]("changed:pytest", ["uv", "run", "pytest", *direct_tests]) or status
    if contract_changed:
        status = _run_stage_items(env, "contract") or status
    if backend_contract_changed:
        status = _run_stage_items(env, "backend_contract") or status

    return env["run_path_triggers"](changed_paths) or status
