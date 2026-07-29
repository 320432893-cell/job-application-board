#!/usr/bin/env python3
# 职责：把 tooling.registry.toml 编译成检查入口和审查包共用的阶段/命令事实。
# 不做什么：不运行检查、不解释项目目录身份、不修改 registry。
# 允许依赖层：标准库、.ai-config/config/tooling.registry.toml。
# 谁不应该 import：正式业务代码、测试夹具、应用入口不应 import 本工具层模块。
"""Shared registry projection helpers for tooling."""

from __future__ import annotations

import shlex
import tomllib
from collections.abc import Callable, Sequence
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / ".ai-config" / "config" / "tooling.registry.toml"
GOVERNANCE_CONFIG_PREFIXES = (".ai-config/", ".github/", ".semgrep/", "tools/")
UV_RUN_OPTION_WITH_VALUE = {"--with", "--with-editable", "--python", "--project", "--directory", "--env-file"}
PYTHON_OPTION_WITH_VALUE = {"-W", "-X"}
# `uv run python <script>` 最短形态就是 4 个 token，少于这个数不可能是 python 脚本调用。
UV_RUN_PYTHON_SCRIPT_MIN_TOKENS = 4


def _dedupe(items: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def load_registry(path: Path = REGISTRY_PATH) -> dict:
    if not path.exists():
        return {}
    return tomllib.loads(path.read_text(encoding="utf-8"))


def stage_items(stage: str, registry: dict | None = None) -> list[str]:
    source = registry if registry is not None else load_registry()
    items = [
        str(tool.get("id", "")).strip()
        for tool in source.get("tools", [])
        if str(tool.get("id", "")).strip() and stage in [str(item) for item in tool.get("stages", [])]
    ]
    return _dedupe(items)


def stages(registry: dict | None = None) -> dict[str, list[str]]:
    source = registry if registry is not None else load_registry()
    names = {str(stage) for tool in source.get("tools", []) for stage in tool.get("stages", [])}
    return {stage: stage_items(stage, source) for stage in sorted(names)}


def tool_ids(registry: dict | None = None) -> set[str]:
    source = registry if registry is not None else load_registry()
    return {str(tool.get("id", "")).strip() for tool in source.get("tools", []) if str(tool.get("id", "")).strip()}


def tool_commands(registry: dict | None = None, *, command_mode: str = "entrypoint") -> dict[str, list[str]]:
    source = registry if registry is not None else load_registry()
    commands: dict[str, list[str]] = {}
    for tool in source.get("tools", []):
        tool_id = str(tool.get("id", "")).strip()
        if not tool_id:
            continue
        ci_commands = [str(command) for command in tool.get("ci_commands", [])]
        entrypoint_commands = [str(command) for command in tool.get("entrypoint_commands", [])]
        manual_commands = [str(command) for command in tool.get("manual_commands", [])]
        if command_mode == "ci" and ci_commands:
            commands[tool_id] = ci_commands
        elif entrypoint_commands:
            commands[tool_id] = entrypoint_commands
        elif manual_commands:
            commands[tool_id] = manual_commands
    return commands


def uv_run_python_script_target(command: str) -> str | None:
    try:
        tokens = shlex.split(command)
    except ValueError:
        return None
    if len(tokens) < UV_RUN_PYTHON_SCRIPT_MIN_TOKENS or tokens[:2] != ["uv", "run"]:
        return None
    index = 2
    while index < len(tokens) and tokens[index].startswith("-"):
        index += 2 if tokens[index] in UV_RUN_OPTION_WITH_VALUE else 1
    if index >= len(tokens) or tokens[index] not in {"python", "python3"}:
        return None
    index += 1
    while index < len(tokens) and tokens[index].startswith("-"):
        if tokens[index] in {"-c", "-m"}:
            return None
        index += 2 if tokens[index] in PYTHON_OPTION_WITH_VALUE else 1
    if index >= len(tokens):
        return None
    target = tokens[index].strip().strip("/")
    return target if target.endswith(".py") else None


def applies_to_languages(tool: dict, declared: set[str]) -> bool:
    """工具声明了 languages 时,项目必须至少声明其中一门,否则这道闸不适用。

    不标的默认语言无关。标了的好处是把"不适用"从**静默通过**变成**显式跳过**:
    比如 module-boundary 过滤 .py,在纯 TS 项目里会扫零个文件然后绿灯——那是最坏的状态。
    """
    required = {str(item) for item in tool.get("languages", [])}
    return not required or bool(required & declared)


def tool_by_id(tool_id: str, registry: dict | None = None) -> dict:
    source = registry if registry is not None else load_registry()
    return next((tool for tool in source.get("tools", []) if str(tool.get("id", "")).strip() == tool_id), {})


def missing_required_paths(tool_id: str, root: Path, registry: dict | None = None) -> list[str]:
    return [path for path in tool_by_id(tool_id, registry).get("required_paths", []) if not (root / str(path)).exists()]


def changed_when_items(event: str, registry: dict | None = None) -> list[str]:
    source = registry if registry is not None else load_registry()
    return [
        str(tool["id"])
        for tool in source.get("tools", [])
        if event in [str(item) for item in tool.get("changed_when", [])]
        and tool.get("entrypoint_commands")
    ]


def path_trigger_name_matches(name: str, patterns: Sequence[str]) -> bool:
    clean_name = name.strip().strip("/")
    for pattern in [str(item).strip().strip("/") for item in patterns]:
        if not pattern:
            continue
        path = PurePosixPath(clean_name)
        if path.match(pattern) or (pattern.startswith("**/") and path.match(pattern[3:])):
            return True
        if not any(char in pattern for char in "*?[") and clean_name.startswith(f"{pattern}/"):
            return True
    return False


def effective_path_triggers(registry: dict | None = None, *, is_code_name: Callable[[str], bool]) -> list[dict]:
    source = registry if registry is not None else load_registry()
    triggers = list(source.get("path_triggers", []))
    for tool in source.get("tools", []):
        if (
            tool.get("changed_adapter")
            or not tool.get("trigger_on_configured_in")
            or not (tool.get("entrypoint_commands") or tool.get("manual_commands"))
        ):
            continue
        for path in [str(item) for item in tool.get("configured_in", [])]:
            if not path or is_code_name(path) or path.startswith(GOVERNANCE_CONFIG_PREFIXES):
                continue
            triggers.append({"id": f"configured-in:{tool['id']}:{path}", "tool": tool["id"], "paths": [path], "run_mode": "changed"})
    return triggers


def stage_gate_groups(stage: str, registry: dict | None = None) -> dict[str, list[str]]:
    source = registry if registry is not None else load_registry()
    groups: dict[str, list[str]] = {}
    for tool in source.get("tools", []):
        tool_id = str(tool.get("id", "")).strip()
        if not tool_id or stage not in [str(item) for item in tool.get("stages", [])]:
            continue
        gate = str(tool.get("stage_gate") or "unclassified")
        groups.setdefault(gate, []).append(tool_id)
    return dict(sorted(groups.items()))
