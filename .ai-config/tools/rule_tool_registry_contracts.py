#!/usr/bin/env python3
# 职责：校验 tooling.registry 的 stage/changed 声明和 check.py dry-run 是否一致。
# 不做什么：不检查规则正文、不检查 project_model 布局、不运行真实检查。
# 允许依赖层：标准库、tools/tooling_registry.py、tools/check.py --dry-run。
# 谁不应该 import：业务/应用/测试不应 import 本检查脚本。
"""Registry projection contract checks for check_rule_tool_contracts.py."""

from __future__ import annotations

import ast
import pathlib
import shlex
import subprocess
import sys
import tomllib
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[2]
TOOLS_DIR = ROOT / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

# tooling_registry 住在 tools/ 下，必须等上面 sys.path.insert 完才 import 得到，所以这里豁免 E402。
import tooling_registry  # noqa: E402

# `uv run <target>` 最短形态是 3 个 token，少于这个数就谈不上"uv run 起了什么"。
UV_RUN_MIN_TOKENS = 3
ALLOWED_STAGE_GATES = {
    "agent-review",
    "dependency",
    "double-source",
    "drift",
    "identity",
    "review-material",
    "reversibility",
}
ALLOWED_ENFORCEMENTS = {"advisory", "blocking", "material"}
MATERIAL_STAGE_GATES = {"agent-review", "review-material"}
BLOCKING_STAGE_GATES = ALLOWED_STAGE_GATES - MATERIAL_STAGE_GATES
COMMAND_FIELDS = ("entrypoint_commands", "ci_commands", "manual_commands")
AUTOMATED_STAGES = {"quick", "stage", "cleanup", "ci", "deep"}
UNIFIED_CLI_DISPATCHERS = {"tools/check.py", "tools/check_changed.py"}
GOVERNANCE_PREFIXES = (".ai-config/", ".github/", ".semgrep/", "tools/")
GOVERNANCE_FILES = {
    ".gitignore",
    ".importlinter",
    ".pre-commit-config.yaml",
    ".ruff.toml",
    "pyproject.toml",
    "uv.lock",
}


def read_text(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def load_project_model(root: pathlib.Path) -> dict:
    path = root / ".ai-config" / "project_model.toml"
    if not path.exists():
        return {}
    return tomllib.loads(path.read_text(encoding="utf-8"))


def issue(issue_type: type, severity: str, message: str) -> Any:
    return issue_type(severity, message)


def stage_items(registry: dict, stage: str) -> list[str]:
    return tooling_registry.stage_items(stage, registry)


def registry_stages(registry: dict) -> dict[str, list[str]]:
    return tooling_registry.stages(registry)


def dry_run_stage(root: pathlib.Path, stage: str, issues: list[Any], issue_type: type) -> list[str]:
    proc = subprocess.run(
        [sys.executable, "tools/check.py", "--dry-run", stage],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        issues.append(issue(issue_type, "ERROR", f"tools/check.py --dry-run {stage} failed: {proc.stderr.strip()}"))
        return []
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def command_python_target(command: str) -> str | None:
    try:
        tokens = shlex.split(command)
    except ValueError:
        return None
    if len(tokens) >= UV_RUN_MIN_TOKENS and tokens[:2] == ["uv", "run"]:
        tokens = tokens[2:]
    if not tokens or tokens[0] not in {"python", "python3"}:
        return None
    if tokens[0] == "python3":
        return "__PYTHON3__"
    for token in tokens[1:]:
        if token.startswith("-"):
            return None
        if token.endswith(".py"):
            return token.strip("/")
        return None
    return None


def is_governance_config_path(path: str) -> bool:
    value = path.strip().strip("/")
    return value in GOVERNANCE_FILES or any(value.startswith(prefix) for prefix in GOVERNANCE_PREFIXES)


def path_matches_any(path: str, patterns: set[str]) -> bool:
    posix_path = pathlib.PurePosixPath(path)
    for pattern in patterns:
        if pattern.endswith("/**"):
            prefix = pattern[:-3]
            if path == prefix or path.startswith(f"{prefix}/"):
                return True
            continue
        if posix_path.match(pattern):
            return True
    return False


def uv_run_executable(tokens: list[str | None]) -> str | None:
    if len(tokens) < UV_RUN_MIN_TOKENS or tokens[:2] != ["uv", "run"]:
        return None
    option_with_value = {"--with", "--with-editable", "--python", "--project", "--directory", "--env-file"}
    index = 2
    while index < len(tokens):
        token = tokens[index]
        if token is None:
            return None
        if token in option_with_value:
            index += 2
            continue
        if token.startswith("-"):
            index += 1
            continue
        if token in {"python", "python3"} and index + 2 < len(tokens) and tokens[index + 1] == "-m":
            module = tokens[index + 2]
            return module if module else None
        return token
    return None


def is_process_runner(node: ast.expr) -> bool:
    return isinstance(node, ast.Attribute) and node.attr in {
        "run",
        "Popen",
        "call",
        "check_call",
        "check_output",
        "system",
    }


def command_literals(path: pathlib.Path) -> set[str]:
    try:
        tree = ast.parse(read_text(path), filename=str(path))
    except SyntaxError:
        return set()
    commands: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args or not is_process_runner(node.func):
            continue
        command = node.args[0]
        if isinstance(command, ast.Constant) and isinstance(command.value, str):
            executable = uv_run_executable(shlex.split(command.value))
        elif isinstance(command, (ast.List, ast.Tuple)):
            values = [
                item.value if isinstance(item, ast.Constant) and isinstance(item.value, str) else None
                for item in command.elts
            ]
            executable = uv_run_executable(values)
        else:
            executable = None
        if executable:
            commands.add(executable)
    return commands


def command_declares_executable(command: str, executable: str) -> bool:
    try:
        tokens = shlex.split(command)
    except ValueError:
        return False
    return uv_run_executable(tokens) == executable


def check_capability_ownership(root: pathlib.Path, registry: dict, issues: list[Any], issue_type: type) -> None:
    """按原顺序依次跑四段 capability 归属检查；拆分只为控制单函数体量。"""
    tools = {str(tool.get("id", "")).strip(): tool for tool in registry.get("tools", [])}
    _check_capability_declarations(tools, issues, issue_type)
    _check_changed_adapter_ownership(tools, issues, issue_type)
    _check_stage_capability_duplicates(registry, tools, issues, issue_type)
    _check_capability_cli_dispatch(root, registry, tools, issues, issue_type)


def _check_capability_declarations(tools: dict, issues: list[Any], issue_type: type) -> None:
    for tool_id, tool in tools.items():
        stages = {str(stage) for stage in tool.get("stages", [])}
        if tool.get("utility") and stages & AUTOMATED_STAGES:
            issues.append(issue(issue_type, "ERROR", f"utility tool {tool_id} must not declare automated stages"))
        if not tool.get("utility") and stages & AUTOMATED_STAGES and not str(tool.get("capability_id", "")).strip():
            issues.append(issue(issue_type, "ERROR", f"stage tool {tool_id} must declare capability_id"))


def _check_changed_adapter_ownership(tools: dict, issues: list[Any], issue_type: type) -> None:
    for tool_id, tool in tools.items():
        if not tool_id or not tool.get("changed_adapter"):
            continue
        parent_id = str(tool.get("parent_tool", "")).strip()
        capability = str(tool.get("capability_id", "")).strip()
        parent_capability = str(tools.get(parent_id, {}).get("capability_id", "")).strip()
        if not capability:
            issues.append(issue(issue_type, "ERROR", f"changed adapter {tool_id} must declare capability_id"))
        elif capability != parent_capability:
            issues.append(
                issue(issue_type, "ERROR", f"changed adapter {tool_id} capability_id must equal parent {parent_id}")
            )
        parent = tools.get(parent_id, {})
        if parent.get("changed_adapter"):
            issues.append(
                issue(
                    issue_type,
                    "ERROR",
                    f"changed adapter {tool_id} parent {parent_id} must be a full owner, not another adapter",
                )
            )
        elif "cleanup" not in {str(stage) for stage in parent.get("stages", [])}:
            replacement_id = str(tool.get("cleanup_replacement", "")).strip()
            replacement = tools.get(replacement_id, {})
            same_capability = str(replacement.get("capability_id", "")).strip() == capability
            if (
                not replacement_id
                or "cleanup" not in {str(stage) for stage in replacement.get("stages", [])}
                or not same_capability
            ):
                issues.append(
                    issue(
                        issue_type,
                        "ERROR",
                        f"changed adapter {tool_id} parent {parent_id} must own cleanup or declare same-capability cleanup_replacement",
                    )
                )


def _check_stage_capability_duplicates(registry: dict, tools: dict, issues: list[Any], issue_type: type) -> None:
    for stage, item_ids in registry_stages(registry).items():
        seen: dict[str, str] = {}
        for tool_id in item_ids:
            capability = str(tools[tool_id].get("capability_id", "")).strip()
            if not capability:
                continue
            if capability in seen:
                issues.append(
                    issue(
                        issue_type,
                        "ERROR",
                        f"stage {stage} runs capability `{capability}` twice: {seen[capability]}, {tool_id}",
                    )
                )
            else:
                seen[capability] = tool_id


def _check_capability_cli_dispatch(
    root: pathlib.Path,
    registry: dict,
    tools: dict,
    issues: list[Any],
    issue_type: type,
) -> None:
    """owners/adapters 表坏了就地返回：后面的 adapter 白名单和直呼扫描都以它为前提。"""
    owners = registry.get("metadata", {}).get("capability_cli_owners", {})
    if not isinstance(owners, dict):
        issues.append(issue(issue_type, "ERROR", "metadata.capability_cli_owners must be a table"))
        return
    _check_declared_cli_owners(tools, owners, issues, issue_type)

    adapters_by_cli = registry.get("metadata", {}).get("capability_cli_adapters", {})
    if not isinstance(adapters_by_cli, dict):
        issues.append(issue(issue_type, "ERROR", "metadata.capability_cli_adapters must be a table"))
        return
    allowed_adapter_sources = _allowed_adapter_sources(tools, owners, adapters_by_cli, issues, issue_type)
    _check_direct_owner_cli_runs(root, owners, allowed_adapter_sources, issues, issue_type)


def _check_declared_cli_owners(tools: dict, owners: dict, issues: list[Any], issue_type: type) -> None:
    for executable, owner_id in owners.items():
        owner = tools.get(str(owner_id))
        if not owner:
            issues.append(issue(issue_type, "ERROR", f"CLI `{executable}` owner `{owner_id}` is not registered"))
            continue
        commands = [str(command) for field in COMMAND_FIELDS for command in owner.get(field, [])]
        if not any(command_declares_executable(command, str(executable)) for command in commands):
            issues.append(
                issue(issue_type, "ERROR", f"CLI `{executable}` owner `{owner_id}` does not declare the command")
            )


def _allowed_adapter_sources(
    tools: dict,
    owners: dict,
    adapters_by_cli: dict,
    issues: list[Any],
    issue_type: type,
) -> dict[str, set[str]]:
    allowed_adapter_sources: dict[str, set[str]] = {str(executable): set() for executable in owners}
    for executable, adapter_ids in adapters_by_cli.items():
        executable = str(executable)
        if executable not in owners:
            issues.append(issue(issue_type, "ERROR", f"CLI adapter `{executable}` has no declared owner"))
            continue
        if not isinstance(adapter_ids, list):
            issues.append(issue(issue_type, "ERROR", f"CLI adapter `{executable}` must be a list of tool ids"))
            continue
        for adapter_id in adapter_ids:
            adapter = tools.get(str(adapter_id), {})
            if not adapter:
                issues.append(
                    issue(issue_type, "ERROR", f"CLI adapter `{executable}` references unknown tool `{adapter_id}`")
                )
                continue
            allowed_adapter_sources[executable].update(
                str(path).strip() for path in adapter.get("configured_in", []) if str(path).strip().endswith(".py")
            )
    return allowed_adapter_sources


def _check_direct_owner_cli_runs(
    root: pathlib.Path,
    owners: dict,
    allowed_adapter_sources: dict[str, set[str]],
    issues: list[Any],
    issue_type: type,
) -> None:
    protected = {str(executable) for executable in owners}
    protected_roots = [root / "tools", root / ".ai-config" / "tools"]
    for directory in protected_roots:
        if not directory.exists():
            continue
        for path in sorted(directory.rglob("*.py")):
            if path.relative_to(root).as_posix() in UNIFIED_CLI_DISPATCHERS:
                continue
            direct = command_literals(path) & protected
            unexpected = sorted(
                executable
                for executable in direct
                if path.relative_to(root).as_posix() not in allowed_adapter_sources[executable]
            )
            if unexpected:
                issues.append(
                    issue(
                        issue_type,
                        "ERROR",
                        f"{path.relative_to(root)} directly runs owner CLI {unexpected}; dispatch through tools/check.py owner",
                    )
                )


def _check_unified_entrypoint_markers(
    root: pathlib.Path,
    registry: dict,
    issues: list[Any],
    issue_type: type,
) -> None:
    entrypoint = read_text(root / registry.get("metadata", {}).get("unified_entrypoint", "tools/check.py"))
    required_markers = [
        ("load_stages()", "unified entrypoint must derive stages from registry tool.stages"),
        ("changed_when_items(", "unified entrypoint must derive changed gates from registry changed_when events"),
        ("path_trigger_matches(", "unified entrypoint must let declared path triggers wake changed mode"),
        ("registry_tool_commands(command_mode)", "unified entrypoint must execute ci_commands in ci stage"),
        ("check_changed.env_from(", "changed dispatcher must use an explicit callback interface"),
    ]
    issues.extend(
        issue(issue_type, "ERROR", message) for marker, message in required_markers if marker not in entrypoint
    )
    registry_text = read_text(root / ".ai-config" / "config" / "tooling.registry.toml")
    if "load_profiles()" in entrypoint or "[profiles]" in registry_text:
        issues.append(issue(issue_type, "ERROR", "profiles are retired; use per-tool stages instead"))


def _check_tool_command_targets(
    root: pathlib.Path,
    tool: dict,
    contract_patterns: set[str],
    issues: list[Any],
    issue_type: type,
) -> None:
    tool_id = tool.get("id")
    for field in COMMAND_FIELDS:
        for command in tool.get(field, []):
            target = command_python_target(str(command))
            if target == "__PYTHON3__":
                issues.append(
                    issue(
                        issue_type,
                        "ERROR",
                        f"tool {tool_id}: registry command uses python3; use uv run python for cross-platform CI",
                    )
                )
                continue
            if target and not (root / target).exists():
                issues.append(issue(issue_type, "ERROR", f"tool {tool_id}: command target missing: {target}"))
    for configured_path in tool.get("configured_in", []):
        value = str(configured_path).strip().strip("/")
        if value and is_governance_config_path(value) and not path_matches_any(value, contract_patterns):
            issues.append(
                issue(
                    issue_type,
                    "ERROR",
                    f"tool {tool_id}: configured_in `{value}` is not covered by project_model.contracts.contract_files",
                )
            )


def _check_tool_changed_declarations(
    tool: dict,
    changed_event_kinds: set[str],
    issues: list[Any],
    issue_type: type,
) -> None:
    tool_id = tool.get("id")
    enforcement = str(tool.get("enforcement", "")).strip()
    if enforcement and enforcement not in ALLOWED_ENFORCEMENTS:
        issues.append(issue(issue_type, "ERROR", f"tool {tool_id}: unknown enforcement `{enforcement}`"))
    legacy_changed_fields = [key for key in ("changed_python", "changed_source", "changed_triggers") if key in tool]
    issues.extend(
        issue(issue_type, "ERROR", f"tool {tool_id}: legacy changed field `{key}` is retired; use changed_when")
        for key in legacy_changed_fields
    )
    if tool.get("changed_when") and not tool.get("entrypoint_commands"):
        issues.append(issue(issue_type, "ERROR", f"tool {tool_id} changed_when requires entrypoint_commands"))
    unknown_events = sorted({str(item) for item in tool.get("changed_when", [])} - changed_event_kinds)
    issues.extend(
        issue(issue_type, "ERROR", f"tool {tool_id} unknown changed_when event `{event}`") for event in unknown_events
    )
    if tool.get("trigger_on_configured_in") and not tool.get("configured_in"):
        issues.append(issue(issue_type, "ERROR", f"tool {tool_id} trigger_on_configured_in requires configured_in"))


def _check_changed_adapter_declarations(
    tool: dict,
    known_items: set[str],
    tools_by_id: dict,
    issues: list[Any],
    issue_type: type,
) -> None:
    if not tool.get("changed_adapter"):
        return
    tool_id = str(tool.get("id", "")).strip()
    tool_stages = [str(stage) for stage in tool.get("stages", [])]
    enforcement = str(tool.get("enforcement", "")).strip()
    if not tool.get("changed_when"):
        issues.append(issue(issue_type, "ERROR", f"changed adapter {tool_id} must declare changed_when"))
    if enforcement == "blocking" and "stage" not in tool_stages:
        issues.append(issue(issue_type, "ERROR", f"changed adapter {tool_id} must be available in stage"))
    parent_tool = str(tool.get("parent_tool", "")).strip()
    if not parent_tool:
        issues.append(issue(issue_type, "ERROR", f"tool {tool_id}: changed_adapter must declare parent_tool"))
    elif parent_tool not in known_items:
        issues.append(issue(issue_type, "ERROR", f"tool {tool_id}: parent_tool `{parent_tool}` is not registered"))
    parent_stages = [str(stage) for stage in tools_by_id.get(parent_tool, {}).get("stages", [])]
    invalid_stages = sorted(set(tool_stages) - {"quick", "stage"})
    issues.extend(
        issue(issue_type, "ERROR", f"tool {tool_id}: changed_adapter cannot declare stage `{stage}`")
        for stage in invalid_stages
    )
    if "stage" in parent_stages:
        issues.append(
            issue(
                issue_type,
                "ERROR",
                f"tool {tool_id}: parent_tool `{parent_tool}` must not be in stage; stage should run the changed adapter",
            )
        )


def _check_cleanup_coverage(
    tool: dict,
    tool_stages: list[str],
    tools_by_id: dict,
    issues: list[Any],
    issue_type: type,
) -> None:
    if "stage" in tool_stages and not tool.get("changed_adapter") and "cleanup" not in tool_stages:
        tool_id = str(tool.get("id", "")).strip()
        replacement_id = str(tool.get("cleanup_replacement", "")).strip()
        replacement = tools_by_id.get(replacement_id, {})
        same_capability = replacement.get("capability_id") == tool.get("capability_id")
        if not replacement_id or "cleanup" not in replacement.get("stages", []) or not same_capability:
            issues.append(
                issue(
                    issue_type,
                    "ERROR",
                    f"tool {tool_id}: stage checks must also be in cleanup or declare same-capability cleanup_replacement",
                )
            )


def _check_stage_gate_declarations(
    tool: dict,
    tool_stages: list[str],
    issues: list[Any],
    issue_type: type,
) -> None:
    tool_id = str(tool.get("id", "")).strip()
    enforcement = str(tool.get("enforcement", "")).strip()
    if "stage" in tool_stages:
        stage_gate = str(tool.get("stage_gate", "")).strip()
        if enforcement not in ALLOWED_ENFORCEMENTS:
            issues.append(
                issue(
                    issue_type,
                    "ERROR",
                    f"tool {tool_id}: stage tools must declare enforcement in {sorted(ALLOWED_ENFORCEMENTS)}",
                )
            )
        if enforcement == "advisory":
            issues.append(issue(issue_type, "ERROR", f"tool {tool_id}: advisory tools must not run in stage"))
        if stage_gate not in ALLOWED_STAGE_GATES:
            issues.append(
                issue(
                    issue_type,
                    "ERROR",
                    f"tool {tool_id}: stage tools need stage_gate in {sorted(ALLOWED_STAGE_GATES)}, got `{stage_gate}`",
                )
            )
        elif enforcement == "blocking" and stage_gate not in BLOCKING_STAGE_GATES:
            issues.append(
                issue(
                    issue_type,
                    "ERROR",
                    f"tool {tool_id}: blocking stage tools need a blocking stage_gate, got `{stage_gate}`",
                )
            )
        elif enforcement == "material" and stage_gate not in MATERIAL_STAGE_GATES:
            issues.append(
                issue(
                    issue_type,
                    "ERROR",
                    f"tool {tool_id}: material stage tools need stage_gate in {sorted(MATERIAL_STAGE_GATES)}, got `{stage_gate}`",
                )
            )
    elif tool.get("stage_gate"):
        issues.append(issue(issue_type, "ERROR", f"tool {tool_id}: stage_gate set but tool is not in stage"))


def _check_blocking_capability_reachability(tools_by_id: dict, issues: list[Any], issue_type: type) -> None:
    # blocking ⇒ 必须够得着：enforcement 说的是"跑了多严"，stages 说的是"哪个手动档含它"，
    # 两者合起来不蕴含"会被自动跑到"。按 capability 判定，让 changed adapter 能靠全量 owner 兜底。
    automated_capabilities: set[str] = set()
    blocking_capabilities: dict[str, list[str]] = {}
    for tool_id, tool in tools_by_id.items():
        capability = str(tool.get("capability_id", "")).strip()
        if not capability:
            continue
        if (
            tool.get("pre_commit_hook")
            or tool.get("pre_commit_hooks")
            or "ci" in [str(s) for s in tool.get("stages", [])]
        ):
            automated_capabilities.add(capability)
        if str(tool.get("enforcement", "")).strip() == "blocking":
            blocking_capabilities.setdefault(capability, []).append(tool_id)
    for capability, owner_ids in sorted(blocking_capabilities.items()):
        if capability not in automated_capabilities:
            issues.append(
                issue(
                    issue_type,
                    "ERROR",
                    f"capability `{capability}` is blocking ({', '.join(sorted(owner_ids))}) but has no automatic trigger; some tool of this capability needs pre_commit_hook or the ci stage",
                )
            )


def check(root: pathlib.Path, registry: dict, issues: list[Any], issue_type: type) -> None:
    """按原顺序跑完各段 registry 契约检查；拆分只为控制单函数体量，issue 文案与顺序不变。"""
    _check_unified_entrypoint_markers(root, registry, issues, issue_type)

    stages = registry_stages(registry)
    check_capability_ownership(root, registry, issues, issue_type)
    changed_event_kinds = {str(item) for item in registry.get("metadata", {}).get("changed_event_kinds", [])}
    contract_patterns = {
        str(item).strip().strip("/")
        for item in load_project_model(root).get("contracts", {}).get("contract_files", [])
        if str(item).strip()
    }
    # 只核对本项目真会跑到的工具:声明了 languages 的工具在没声明那门语言的项目里根本不会被调用,
    # 追问它的 .ruff.toml / pyproject.toml 有没有进 contract_files 是成片的纯噪音。
    # 判据复用 check.py 跳过工具时用的同一个,不另写一份。
    declared = {str(lang.get("id", "")) for lang in load_project_model(root).get("languages", [])}
    for tool in registry.get("tools", []):
        if not tooling_registry.applies_to_languages(tool, declared):
            continue
        _check_tool_command_targets(root, tool, contract_patterns, issues, issue_type)
        _check_tool_changed_declarations(tool, changed_event_kinds, issues, issue_type)

    allowed_stages = {"bootstrap", "quick", "changed", "stage", "deep", "ci", "cleanup"}
    missing_stages = sorted({"quick", "changed", "stage", "cleanup", "ci"} - set(stages))
    issues.extend(issue(issue_type, "ERROR", f"registry stage missing: {stage}") for stage in missing_stages)
    known_items = {
        str(tool["id"])
        for tool in registry.get("tools", [])
        if tool.get("entrypoint_commands") or tool.get("manual_commands") or tool.get("ci_commands")
    }
    tools_by_id = {str(tool.get("id", "")).strip(): tool for tool in registry.get("tools", [])}
    for tool in registry.get("tools", []):
        tool_id = str(tool.get("id", "")).strip()
        tool_stages = [str(stage) for stage in tool.get("stages", [])]
        issues.extend(
            issue(issue_type, "ERROR", f"tool {tool_id}: unknown stage `{stage}`")
            for stage in sorted(set(tool_stages) - allowed_stages)
        )
        is_changed_adapter = bool(tool.get("changed_adapter"))
        if tool_id in known_items and not tool_stages and not tool.get("utility") and not is_changed_adapter:
            issues.append(
                issue(
                    issue_type,
                    "ERROR",
                    f"tool {tool_id}: runnable tools need stages, utility=true, or changed_adapter=true",
                )
            )
        _check_changed_adapter_declarations(tool, known_items, tools_by_id, issues, issue_type)
        if not tool_id or not tool_stages:
            continue
        if tool_id not in known_items:
            issues.append(issue(issue_type, "ERROR", f"tool {tool_id}: stages set but no runnable command"))
        _check_cleanup_coverage(tool, tool_stages, tools_by_id, issues, issue_type)
        if is_changed_adapter and "cleanup" in tool_stages:
            issues.append(
                issue(
                    issue_type,
                    "ERROR",
                    f"changed adapter {tool_id} must not run in cleanup; its full owner owns that stage",
                )
            )
        _check_stage_gate_declarations(tool, tool_stages, issues, issue_type)
        if tool_id == "import-linter" and "stage" not in tool_stages:
            issues.append(
                issue(
                    issue_type,
                    "ERROR",
                    "import-linter must be available in stage because review rules rely on it for L1",
                )
            )
        if tool.get("ci_commands") and "ci" not in tool_stages:
            issues.append(issue(issue_type, "ERROR", f"tool {tool_id}: ci_commands declared but ci stage missing"))

    _check_blocking_capability_reachability(tools_by_id, issues, issue_type)

    for stage, expected in stages.items():
        actual = dry_run_stage(root, stage, issues, issue_type)
        if actual and actual != expected:
            issues.append(
                issue(
                    issue_type,
                    "ERROR",
                    f"dry-run {stage} differs from registry stages: expected {expected}, got {actual}",
                )
            )
