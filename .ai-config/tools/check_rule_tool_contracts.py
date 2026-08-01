#!/usr/bin/env python3
"""Check rule/tool contracts without a full manual scan."""
# 职责：静态校验规则/工具契约一致(registry↔实现↔pre-commit↔CI)，免人工全扫。
# 不做什么：不改规则/工具；不评判规则内容是否合理(只查契约一致)。
# 允许依赖层：标准库(tomllib 等)、registry/规则/工具源文件。
# 谁不应该 import：业务/应用/测试不应 import 本检查脚本。

from __future__ import annotations

import argparse
import ast
import importlib.util
import pathlib
import re
import sys
import tomllib
from dataclasses import dataclass
from types import ModuleType
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[2]
TOOLS_DIR = ROOT / "tools"
RULE_TOOLS_DIR = ROOT / ".ai-config" / "tools"
for path in (TOOLS_DIR, RULE_TOOLS_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
import rule_tool_registry_contracts  # noqa: E402
from tooling_registry import applies_to_languages  # noqa: E402

REGISTRY = ROOT / ".ai-config" / "config" / "tooling.registry.toml"
PROJECT_MODEL = ROOT / ".ai-config" / "project_model.toml"
REQUIRED_GITIGNORE_ENTRIES = (
    ".venv/",
    ".cache/",
    ".uv-cache/",
    ".ruff_cache/",
    ".pytest_cache/",
    ".mypy_cache/",
    "__pycache__/",
    "scratch/",
    "tmp/",
    "node_modules/",
    "dist/",
    "build/",
    "htmlcov/",
    "coverage/",
    ".coverage",
    ".tox/",
    ".nox/",
    ".env",
    ".env.*",
    "!.env.example",
    "!.env.template",
    "!.env.sample",
    "*.pyc",
    "*.pyo",
    ".DS_Store",
)
# 文档/配置里对规则与 semgrep 文件的引用:必须真的存在(替掉手工维护的历史黑名单)。
RULE_REFERENCE_RE = re.compile(r"(?:rules|\.semgrep|process|engineering|delivery)/[\w./-]+\.(?:md|ya?ml)")
RISKY_TREE_SCAN_PATTERNS = (
    re.compile(r"(^|\s)detect-secrets\s+scan(?=.*(^|\s)(--all-files|\.\/?)(\s|$))"),
    re.compile(r"(^|\s)find\s+\.\/?(\s|$)"),
    re.compile(r"(^|\s)rg(\s+\S+)*\s+\.\/?(\s|$)"),
    re.compile(r"(^|\s)grep\s+-[A-Za-z]*R[A-Za-z]*(\s+\S+)*\s+\.\/?(\s|$)"),
)
REQUIRED_SCAN_EXCLUDE_TOKENS = (".venv", ".cache", "node_modules")
COMMAND_FIELDS = ("entrypoint_commands", "ci_commands", "manual_commands")
LAYOUT_LIST_FIELDS = (
    "fixed_quality_dirs",
    "formal_dirs",
    "support_dirs",
    "test_dirs",
    "ignored_dirs",
    "informal_zone_dirs",
    "inactive_dirs",
    "entrypoint_files",
    "package_roots",
)
LAYOUT_STRING_FIELDS = ("devtools_dir",)
PATH_HARDCODE_ASSIGNMENTS = {
    "SCAN_DIRS",
    "PROD_DIRS",
    "DEFAULT_SCAN_DIRS",
    "FULL_SCAN_DIRS",
    "SCHEMA_FILES",
    "INFORMAL_ZONE_DIRS",
    "DEVTOOLS_DIR",
}
DEFAULT_LAYOUT_LITERALS = {"app", "scripts", "tests", "tools"}


@dataclass
class Issue:
    severity: str
    message: str


def read_text(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def rel(path: pathlib.Path) -> str:
    return str(path.relative_to(ROOT))


def load_toml(path: pathlib.Path) -> dict:
    return tomllib.loads(read_text(path))


def load_project_model() -> dict:
    if not PROJECT_MODEL.exists():
        return {}
    from project_model import load_project_model_dict

    return load_project_model_dict(PROJECT_MODEL)


def load_tooling_layout_module() -> ModuleType:
    path = ROOT / "tools" / "tooling_layout.py"
    spec = importlib.util.spec_from_file_location("tooling_layout_contract_check", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load tools/tooling_layout.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def derived_code_layout() -> dict:
    module = load_tooling_layout_module()
    return module.code_layout()


def known_risk_conditions() -> set[str]:
    path = ROOT / "tools" / "stage_packet.py"
    spec = importlib.util.spec_from_file_location("stage_packet_contract_check", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load tools/stage_packet.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return {str(value) for value in getattr(module, "KNOWN_RISK_CONDITIONS", set())}


def parse_dev_packages(pyproject: dict) -> set[str]:
    packages: set[str] = set()
    for item in pyproject.get("dependency-groups", {}).get("dev", []):
        if isinstance(item, str):
            packages.add(re.split(r"[<>=!~\[]", item, maxsplit=1)[0].lower())
    return packages


def parse_pre_commit_hooks(path: pathlib.Path) -> set[str]:
    text = read_text(path)
    return set(re.findall(r"^\s*-\s+id:\s*([A-Za-z0-9_.-]+)\s*$", text, flags=re.MULTILINE))


def load_pre_commit_config(path: pathlib.Path) -> dict[str, Any]:
    try:
        import yaml
    except Exception as exc:  # pragma: no cover - PyYAML is provided by pre-commit.
        raise RuntimeError("PyYAML is required to validate pre-commit hook wiring") from exc
    data = yaml.safe_load(read_text(path))
    return data if isinstance(data, dict) else {}


def find_pre_commit_hook(config: dict[str, Any], hook_id: str) -> dict[str, Any] | None:
    for repo in config.get("repos", []):
        for hook in repo.get("hooks", []):
            if hook.get("id") == hook_id:
                return hook
    return None


def stage_items(registry: dict, stage: str) -> list[str]:
    return rule_tool_registry_contracts.stage_items(registry, stage)


def registry_stages(registry: dict) -> dict[str, list[str]]:
    return rule_tool_registry_contracts.registry_stages(registry)


def check_path_exists(root: pathlib.Path, path_str: str, issues: list[Issue], field: str) -> None:
    path = root / path_str
    if not path.exists():
        issues.append(Issue("ERROR", f"{field} points to missing path: {path_str}"))


def check_relative_path_literal(path_str: str, issues: list[Issue], field: str) -> None:
    path = pathlib.PurePosixPath(path_str)
    if path.is_absolute() or ".." in path.parts or not path_str.strip():
        issues.append(Issue("ERROR", f"{field} must be a non-empty repository-relative path: {path_str}"))


def check_gitignore(root: pathlib.Path, issues: list[Issue]) -> None:
    path = root / ".gitignore"
    if not path.exists():
        issues.append(Issue("ERROR", ".gitignore is missing; artifact hygiene must be explicit"))
        return
    entries = {
        line.strip() for line in read_text(path).splitlines() if line.strip() and not line.lstrip().startswith("#")
    }
    missing = [entry for entry in REQUIRED_GITIGNORE_ENTRIES if entry not in entries]
    issues.extend(Issue("ERROR", f".gitignore missing required artifact entry: {entry}") for entry in missing)


def iter_registered_commands(registry: dict) -> list[tuple[str, str, str]]:
    commands: list[tuple[str, str, str]] = []
    for tool in registry.get("tools", []):
        tool_id = tool.get("id", "<missing>")
        for field in COMMAND_FIELDS:
            for command in tool.get(field, []):
                commands.append((tool_id, field, command))
    return commands


def is_risky_tree_scan(command: str) -> bool:
    return any(pattern.search(command) for pattern in RISKY_TREE_SCAN_PATTERNS)


def check_scan_command_hygiene(registry: dict, issues: list[Issue]) -> None:
    for tool_id, field, command in iter_registered_commands(registry):
        if not is_risky_tree_scan(command):
            continue
        missing = [token for token in REQUIRED_SCAN_EXCLUDE_TOKENS if token not in command]
        if missing:
            issues.append(
                Issue(
                    "ERROR",
                    f"tool {tool_id}.{field}: risky whole-tree scan must exclude generated dirs {missing}: {command}",
                )
            )


def check_tools(root: pathlib.Path, registry: dict, issues: list[Issue]) -> None:
    # 没有 pyproject.toml 说明这个项目根本不用 Python 打包(比如纯 TS/Node 仓)。
    # 那些声明了 package 的工具本来就会因为 languages=["python"] 被跳过,所以这条
    # "dev 依赖是否登记"的核对对它无意义;硬读会直接 FileNotFoundError。
    pyproject = root / "pyproject.toml"
    dev_packages = parse_dev_packages(load_toml(pyproject)) if pyproject.is_file() else None
    pre_commit_hooks = parse_pre_commit_hooks(root / ".pre-commit-config.yaml")
    pre_commit_config = load_pre_commit_config(root / ".pre-commit-config.yaml")
    # 只核对"这个项目真会跑到"的工具。声明了 languages 的工具在没声明那门语言的项目里根本不会
    # 被调用(见 check.py 的同一条判据),再去追问它的 .ruff.toml / pyproject.toml 在不在,报的是
    # 纯噪音——这类误报会成片刷出来,把真问题淹掉。
    # 只裁这里:本函数问的是"这个工具在本项目里接好线了吗",对不适用的工具无意义;而 registry
    # 自身一致性那几条(检查脚本有没有登记、扫描命令卫生)与语言无关,不能跟着裁。
    declared = {str(lang.get("id", "")) for lang in load_project_model().get("languages", [])}
    for tool in registry.get("tools", []):
        if not applies_to_languages(tool, declared):
            continue
        tool_id = tool["id"]
        package = tool.get("package")
        required_paths = {str(path) for path in tool.get("required_paths", [])}
        if package and dev_packages is not None and package.lower() not in dev_packages:
            issues.append(Issue("ERROR", f"tool {tool_id}: dev dependency missing: {package}"))
        for path_str in tool.get("configured_in", []):
            if path_str not in required_paths:
                check_path_exists(root, path_str, issues, f"tool {tool_id}.configured_in")
        for path_str in required_paths:
            check_relative_path_literal(path_str, issues, f"tool {tool_id}.required_paths")
        rule = tool.get("rule")
        if rule:
            check_path_exists(root, rule, issues, f"tool {tool_id}.rule")
        if pre_commit_hook := tool.get("pre_commit_hook"):
            if pre_commit_hook not in pre_commit_hooks:
                issues.append(Issue("ERROR", f"tool {tool_id}: pre-commit hook missing: {pre_commit_hook}"))
            hook = find_pre_commit_hook(pre_commit_config, str(pre_commit_hook))
            hook_entry = str((hook or {}).get("entry") or "")
            launcher = registry.get("metadata", {}).get("launch_entrypoint") or "tools/check.py"
            if hook_entry and f"{launcher} {tool_id}" not in hook_entry:
                issues.append(
                    Issue(
                        "ERROR",
                        f"tool {tool_id}: pre-commit hook `{pre_commit_hook}` entry must call {launcher} {tool_id}",
                    )
                )
        pre_commit_hook_bundle = tool.get("pre_commit_hooks", [])
        for hook_id in pre_commit_hook_bundle:
            if hook_id not in pre_commit_hooks:
                issues.append(Issue("ERROR", f"tool {tool_id}: pre-commit hook missing: {hook_id}"))
        # 不再逐条比对 registry 命令是否字面出现在 entrypoint 里:统一 runner 由 registry 驱动，
        # 且 rule_tool_registry_contracts 的 required_markers 已强制 entrypoint 走 registry_tool_commands(
        # command_mode) + load_stages()。旧的 registry_runner 守卫判的是空括号那个字符串，为真纯靠偶然
        # 的无参调用点——重构调用点就会让两个循环突然激活并要求"命令字面出现"，对 registry 驱动不可能满足。


def check_rule_tool_contracts_trigger(root: pathlib.Path, issues: list[Issue]) -> None:
    config = load_pre_commit_config(root / ".pre-commit-config.yaml")
    hook = find_pre_commit_hook(config, "rule-tool-contracts")
    if not hook:
        issues.append(Issue("ERROR", "pre-commit rule-tool-contracts hook is missing"))
        return
    pattern = hook.get("files")
    if not isinstance(pattern, str) or not pattern:
        issues.append(Issue("ERROR", "pre-commit rule-tool-contracts hook must define a files regex"))
        return

    samples = [
        ".ai-config/tools/check_rule_tool_contracts.py",
        ".ai-config/tools/rule_tool_registry_contracts.py",
        ".ai-config/config/tooling.registry.toml",
        ".ai-config/rules/engineering/code.index.md",
        ".semgrep/no-raw-sleep.yml",
        ".github/workflows/ci.yml",
        ".pre-commit-config.yaml",
        ".ruff.toml",
        ".importlinter",
        ".gitignore",
        ".ai-config/AGENTS.md",
        ".ai-config/project_model.toml",
        "tools/check.py",
        "tools/check_changed.py",
        "tools/inventory.py",
        "tools/stage_packet.py",
        "tools/subagent_review_packet.py",
        "tools/tooling_layout.py",
        "tools/tooling_registry.py",
        "pyproject.toml",
        "uv.lock",
    ]
    model = load_project_model()
    contract_files = model.get("contracts", {}).get("contract_files", [])
    samples.extend(sample_path_from_model_pattern(str(pattern)) for pattern in contract_files)
    try:
        compiled = re.compile(pattern)
    except re.error as exc:
        issues.append(Issue("ERROR", f"pre-commit rule-tool-contracts files regex is invalid: {exc}"))
        return

    for sample in samples:
        if not compiled.search(sample):
            issues.append(
                Issue("ERROR", f"pre-commit rule-tool-contracts files regex does not match required path: {sample}")
            )

    dependency_hook = find_pre_commit_hook(config, "dependency-change-approval")
    dependency_pattern = dependency_hook.get("files") if dependency_hook else None
    if not isinstance(dependency_pattern, str) or not dependency_pattern:
        issues.append(Issue("ERROR", "pre-commit dependency-change-approval hook must define a files regex"))
        return
    try:
        dependency_compiled = re.compile(dependency_pattern)
    except re.error as exc:
        issues.append(Issue("ERROR", f"pre-commit dependency-change-approval files regex is invalid: {exc}"))
        return
    for pattern in model.get("contracts", {}).get("dependency_files", []):
        sample = sample_path_from_model_pattern(str(pattern))
        if not dependency_compiled.search(sample):
            issues.append(Issue("ERROR", f"pre-commit dependency-change-approval files regex does not match: {sample}"))


def sample_path_from_model_pattern(pattern: str) -> str:
    value = pattern.strip().strip("/")
    if not value:
        return "placeholder"
    value = value.replace("**/", "")
    value = value.replace("**", "nested/path")
    value = value.replace("*", "sample")
    return value.replace("[", "").replace("]", "")


def check_ci_semantics(root: pathlib.Path, issues: list[Issue]) -> None:
    ci = read_text(root / ".github" / "workflows" / "ci.yml")
    if "detect-secrets scan --list-all-plugins" in ci:
        issues.append(Issue("ERROR", "CI detect-secrets uses --list-all-plugins instead of scanning files"))
    if "uv run pytest tests/" in ci:
        issues.append(Issue("ERROR", "CI pytest only runs tests/ instead of project pytest configuration"))
    if re.search(r"if:\s*hashFiles\('tests/'\)", ci):
        issues.append(Issue("ERROR", "CI pytest can be skipped when tests/ is absent"))


def _check_pre_commit_enforcement_wiring(root: pathlib.Path, launcher: str, issues: list[Issue]) -> None:
    pre_commit = read_text(root / ".pre-commit-config.yaml")
    required_pre_commit_patterns = [
        r"id:\s*rule-tool-contracts",
        # 只卡"喊的是启动入口 + 这个 tool id",不卡前面的 uv 参数:环境怎么挑是 launcher 的职责,
        # 写进这里就等于把同一个事实抄第二遍,改一处必漏另一处。
        rf"entry:.*{re.escape(launcher)} rule-tool-contracts",
        re.escape(launcher),
        r"\.semgrep/",
        r"id:\s*ruff-staged",
        r"id:\s*dependency-change-approval",
    ]
    for pattern in required_pre_commit_patterns:
        if not re.search(pattern, pre_commit):
            issues.append(Issue("ERROR", f"pre-commit enforcement wiring missing pattern: {pattern}"))
    # 这里原来还有两圈"正则里必须逐字出现某某路径"的子串核对,删了:
    # 它查的是**拼写**,而 check_rule_tool_contracts_trigger 直接把正则编译出来拿样本路径试匹配,
    # 查的是**行为**——后者严格更强。留着子串核对的代价是正则不能写成语言无关的形状
    # (`[^/]+` 能匹配 .ruff.toml,但字面上没有"\.ruff\.toml"),纯 TS 仓因此必红。


def check_enforcement_wiring(root: pathlib.Path, registry: dict, issues: list[Issue]) -> None:
    metadata = registry.get("metadata", {})
    entrypoint = metadata.get("unified_entrypoint", "tools/check.py")
    launcher = metadata.get("launch_entrypoint", entrypoint)
    _check_pre_commit_enforcement_wiring(root, launcher, issues)
    ci = read_text(root / ".github" / "workflows" / "ci.yml")

    if f"{launcher} ci" not in ci:
        issues.append(Issue("ERROR", f"CI must call launch entrypoint: {launcher} ci"))

    entrypoint_text = read_text(root / entrypoint)
    if "ONCALL_ALLOW_DEPENDENCY_CHANGE" not in entrypoint_text:
        issues.append(Issue("ERROR", "dependency-change approval env gate missing from unified entrypoint"))
    if "ruff-staged" not in entrypoint_text:
        issues.append(Issue("ERROR", "ruff-staged changed-file check missing from unified entrypoint"))
    if "project_contract_patterns" not in entrypoint_text:
        issues.append(Issue("ERROR", "unified entrypoint must read contract triggers from project_model.contracts"))
    contract_files = set(load_project_model().get("contracts", {}).get("contract_files", []))
    # 这里只列语言无关的闸自身接线。`.importlinter`/`.ruff.toml` 这类语言专属配置不列:
    # 它们是各自工具的 configured_in,已经被逐工具那条覆盖检查管着(且已按语言过滤),
    # 在这里再写一遍就是同一个事实的第二份拷贝,纯 TS 仓会被它误报。
    for path in (".pre-commit-config.yaml", entrypoint, launcher):
        if path not in contract_files:
            issues.append(Issue("ERROR", f"project_model.contracts.contract_files missing trigger: {path}"))

    ci_items = set(stage_items(registry, "ci"))
    tools_by_id = {tool["id"]: tool for tool in registry.get("tools", [])}
    for tool_id, tool in tools_by_id.items():
        if tool.get("ci_commands") and tool_id not in ci_items:
            issues.append(Issue("ERROR", f"tool {tool_id}: registry declares CI commands but tool is not in ci stage"))


def check_semgrep_rulesets(root: pathlib.Path, registry: dict, issues: list[Issue]) -> None:
    semgrep_dir = root / ".semgrep"
    registered = {item["path"] for item in registry.get("semgrep_rulesets", [])}
    actual = {rel(path) for path in semgrep_dir.glob("*.yml")}

    issues.extend(
        Issue("ERROR", f"semgrep ruleset exists but is not registered: {missing}")
        for missing in sorted(actual - registered)
    )
    issues.extend(
        Issue("ERROR", f"semgrep ruleset registered but missing: {stale}") for stale in sorted(registered - actual)
    )

    for ruleset in registry.get("semgrep_rulesets", []):
        owner = ruleset.get("owner_rule")
        if owner:
            check_path_exists(root, owner, issues, f"semgrep {ruleset['path']}.owner_rule")


def check_no_repository_ai_hooks(root: pathlib.Path, registry: dict, issues: list[Issue]) -> None:
    if (root / ".ai-hooks").exists():
        issues.append(Issue("ERROR", "repository-level .ai-hooks is retired; use global session hooks only"))
    if registry.get("hooks"):
        issues.append(Issue("ERROR", "tooling registry must not declare repository-level hooks"))
    if registry.get("hook_tests"):
        issues.append(Issue("ERROR", "tooling registry must not declare repository-level hook_tests"))

    template_path = root / ".ai-config" / "config" / "settings.json.template"
    if template_path.exists() and ".ai-hooks" in read_text(template_path):
        issues.append(Issue("ERROR", "settings.json.template must not wire repository-level .ai-hooks"))


def check_path_triggers(root: pathlib.Path, registry: dict, issues: list[Issue]) -> None:
    entrypoint = read_text(root / registry.get("metadata", {}).get("unified_entrypoint", "tools/check.py"))
    tools = {tool["id"] for tool in registry.get("tools", [])}
    for trigger in registry.get("path_triggers", []):
        trigger_id = trigger.get("id", "<missing>")
        tool_id = trigger.get("tool")
        if not trigger.get("paths"):
            issues.append(Issue("ERROR", f"path trigger {trigger_id}: paths missing"))
        if tool_id not in tools:
            issues.append(Issue("ERROR", f"path trigger {trigger_id}: tool is not registered: {tool_id}"))
        for required_path in trigger.get("required_paths", []):
            check_relative_path_literal(required_path, issues, f"path trigger {trigger_id}.required_paths")
    if registry.get("path_triggers", []) and "path_triggers" not in entrypoint:
        issues.append(Issue("ERROR", "unified entrypoint does not evaluate path_triggers"))


def check_declarative_stages(root: pathlib.Path, registry: dict, issues: list[Issue]) -> None:
    rule_tool_registry_contracts.check(root, registry, issues, Issue)


def check_metadata(root: pathlib.Path, registry: dict, issues: list[Issue]) -> None:
    metadata = registry.get("metadata", {})
    for key in ("owner_rule", "human_doc", "checker"):
        value = metadata.get(key)
        if value:
            check_path_exists(root, value, issues, f"metadata.{key}")


def _check_project_model_zones(model: dict, issues: list[Issue]) -> tuple[set[str], list[str]]:
    """收 zone 的 trait 集合与 id 列表，顺带查 dirs/files 的相对路径合法性。"""
    trait_ids: set[str] = set()
    zone_ids: list[str] = []
    for zone in model.get("zones", []):
        zone_id = str(zone.get("id", "")).strip()
        if not zone_id:
            issues.append(Issue("ERROR", "project_model zone missing id"))
            continue
        zone_ids.append(zone_id)
        trait_ids.update(str(trait) for trait in zone.get("traits", []))
        for key in ("dirs", "files"):
            for value in zone.get(key, []):
                check_relative_path_literal(str(value), issues, f"project_model zone.{zone_id}.{key}")
    return trait_ids, zone_ids


def _check_project_model_tooling(model: dict, trait_ids: set[str], issues: list[Issue]) -> None:
    tooling = model.get("tooling", {})
    for field, values in tooling.items():
        if not field.endswith("_traits"):
            continue
        for trait in values:
            if str(trait) not in trait_ids:
                issues.append(Issue("ERROR", f"project_model tooling.{field} references unused trait: {trait}"))
    devtools_dir = str(tooling.get("devtools_dir", "")).strip()
    if not devtools_dir:
        issues.append(Issue("ERROR", "project_model tooling.devtools_dir must be a non-empty string"))
    else:
        check_relative_path_literal(devtools_dir, issues, "project_model tooling.devtools_dir")


def _check_project_model_members(model: dict, issues: list[Issue]) -> None:
    for member in model.get("members", []):
        member_id = str(member.get("id", "")).strip()
        if not member_id:
            issues.append(Issue("ERROR", "project_model member missing id"))
            continue
        root_value = str(member.get("root", "")).strip()
        if not root_value:
            issues.append(Issue("ERROR", f"project_model member.{member_id}.root must be a non-empty string"))
        else:
            check_relative_path_literal(root_value, issues, f"project_model member.{member_id}.root")
        for field in ("source_roots", "test_roots", "package_roots", "contract_files", "dependency_files"):
            for value in member.get(field, []):
                check_relative_path_literal(str(value), issues, f"project_model member.{member_id}.{field}")


def _check_project_model_risk_rules(model: dict, trait_ids: set[str], issues: list[Issue]) -> None:
    # 空表和"每条都合法"是两回事:一条都不声明时下面整个循环零轮,恒真通过,而 stage-packet
    # 的 risk_flags 从此恒为空 —— 看着像"这次很干净"。缺失型判据必须单独写,循环查不出来。
    if str(model.get("metadata", {}).get("governance_mode", "native")) != "foreign" and not model.get("risk_rules"):
        issues.append(Issue("ERROR", "project_model 没有声明任何 [[risk_rules]]:风险评估会恒为空"))
    try:
        risk_conditions = known_risk_conditions()
    except Exception as exc:  # noqa: BLE001
        issues.append(Issue("ERROR", f"cannot load stage_packet risk conditions: {exc}"))
        risk_conditions = set()
    for rule in model.get("risk_rules", []):
        rule_id = rule.get("id", "<missing>")
        condition = str(rule.get("condition", "")).strip()
        if condition not in risk_conditions:
            issues.append(Issue("ERROR", f"project_model risk_rule.{rule_id} unknown condition: {condition}"))
        for field in ("zone_trait", "source_trait", "companion_trait"):
            trait = str(rule.get(field, "")).strip()
            if trait and trait not in trait_ids:
                issues.append(Issue("ERROR", f"project_model risk_rule.{rule_id}.{field} unknown trait: {trait}"))


def _check_project_model_agent_reviews(model: dict, issues: list[Issue]) -> None:
    # 同上:0 个模板时 subagent-review 无材料可生成,审查链没有起点。
    if str(model.get("metadata", {}).get("governance_mode", "native")) != "foreign" and not model.get("agent_reviews"):
        issues.append(Issue("ERROR", "project_model 没有声明任何 [[agent_reviews]]:子 agent 审查链没有起点"))
    review_ids: list[str] = []
    for review in model.get("agent_reviews", []):
        review_id = str(review.get("id", "")).strip()
        if not review_id:
            issues.append(Issue("ERROR", "project_model agent_review missing id"))
            continue
        review_ids.append(review_id)
        for field in ("focus", "questions"):
            if not review.get(field, []):
                issues.append(
                    Issue("ERROR", f"project_model agent_review.{review_id}.{field} must be a non-empty list")
                )
    issues.extend(
        Issue("ERROR", f"project_model agent_review id duplicated: {review_id}")
        for review_id in sorted({rid for rid in review_ids if review_ids.count(rid) > 1})
    )


def check_project_model(_root: pathlib.Path, issues: list[Issue]) -> None:
    """Only what pydantic cannot see.

    load_project_model_dict() validates through ProjectModel and raises SystemExit on any
    shape/type/duplication error, so re-checking those here is unreachable. What is left is
    (a) fields pydantic types but does not constrain (empty ids, empty required lists,
    devtools_dir), (b) repository-path safety on fields the model never path-checks, and
    (c) cross-module agreement (traits declared by zones, risk conditions owned by
    stage_packet).

    `_root` 保留只为对齐 main() 里 check_*(ROOT, ...) 的统一调用形状；模型路径来自模块级
    PROJECT_MODEL 常量，不走参数。
    """
    model = load_project_model()
    if not model:
        issues.append(Issue("ERROR", ".ai-config/project_model.toml missing; project model is the layout source"))
        return

    trait_ids, zone_ids = _check_project_model_zones(model, issues)
    if not zone_ids:
        issues.append(Issue("ERROR", "project_model.zones must declare at least one zone with an id"))
        return

    _check_project_model_tooling(model, trait_ids, issues)
    _check_project_model_members(model, issues)
    _check_project_model_risk_rules(model, trait_ids, issues)
    _check_project_model_agent_reviews(model, issues)


def check_code_layout(root: pathlib.Path, registry: dict, issues: list[Issue]) -> None:
    try:
        layout = derived_code_layout()
    except Exception as exc:  # noqa: BLE001
        issues.append(Issue("ERROR", f"cannot derive code layout from project_model: {exc}"))
        return

    entrypoint_path = root / registry.get("metadata", {}).get("unified_entrypoint", "tools/check.py")
    entrypoint = read_text(entrypoint_path)
    if "tooling_layout" not in entrypoint:
        issues.append(Issue("ERROR", "unified entrypoint must use tools/tooling_layout.py for project_model layout"))

    if not (root / "tools" / "tooling_layout.py").exists():
        issues.append(Issue("ERROR", "tools/tooling_layout.py missing; project_model layout needs one shared reader"))

    for key in LAYOUT_LIST_FIELDS:
        values = layout.get(key)
        if not isinstance(values, list):
            issues.append(Issue("ERROR", f"derived code_layout.{key} must be a list"))
            continue
        for value in values:
            check_relative_path_literal(str(value), issues, f"derived code_layout.{key}")
    for key in LAYOUT_STRING_FIELDS:
        value = layout.get(key)
        if not isinstance(value, str) or not value.strip():
            issues.append(Issue("ERROR", f"derived code_layout.{key} must be a non-empty string"))
            continue
        check_relative_path_literal(value, issues, f"derived code_layout.{key}")


def _literal_strings(node: ast.AST) -> list[str]:
    return [item.value for item in ast.walk(node) if isinstance(item, ast.Constant) and isinstance(item.value, str)]


def _layout_path_values(_registry: dict | None = None) -> set[str]:
    # `_registry` 保留只为兼容既有调用点的形状；布局全部来自 project_model 推导，与 registry 无关。
    try:
        layout = derived_code_layout()
    except Exception:  # noqa: BLE001  布局推导会 exec 外部模块，任何异常都只当"拿不到布局"，交由调用方的其他检查报错。
        return set()
    keys = (
        "fixed_quality_dirs",
        "formal_dirs",
        "support_dirs",
        "test_dirs",
        "informal_zone_dirs",
        "inactive_dirs",
        "entrypoint_files",
        "package_roots",
    )
    values: set[str] = set()
    for key in keys:
        raw = layout.get(key, [])
        if isinstance(raw, list):
            values.update(str(value).strip().strip("/") for value in raw if str(value).strip())
    return values


def _hardcoded_layout_nodes(tree: ast.AST, layout_values: set[str]) -> list[str]:
    hits: list[str] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.BinOp)
            and isinstance(node.op, ast.Div)
            and isinstance(node.right, ast.Constant)
            and isinstance(node.right.value, str)
            and node.right.value.strip("/") in layout_values
        ):
            hits.append(f"ROOT / {node.right.value!r}")
        if (
            isinstance(node, ast.Compare)
            and isinstance(node.left, ast.Subscript)
            and any(
                isinstance(comp, ast.Constant) and isinstance(comp.value, str) and comp.value in layout_values
                for comp in node.comparators
            )
        ):
            hits.append("path-parts string comparison")
    return hits


def check_code_layout_consumers(root: pathlib.Path, registry: dict, issues: list[Issue]) -> None:
    layout_tool = root / "tools" / "tooling_layout.py"
    layout_values = _layout_path_values(registry)
    hardcode_values = layout_values | DEFAULT_LAYOUT_LITERALS
    consumer_paths = [
        *sorted((root / "tools").glob("check*.py")),
        root / "tools" / "import_cycles.py",
    ]
    for path in consumer_paths:
        if path == layout_tool or not path.exists():
            continue
        try:
            tree = ast.parse(read_text(path))
        except SyntaxError as exc:
            issues.append(Issue("ERROR", f"{rel(path)} cannot be parsed for code_layout consumer check: {exc}"))
            continue
        hardcoded_nodes = _hardcoded_layout_nodes(tree, hardcode_values)
        if hardcoded_nodes:
            issues.append(
                Issue(
                    "ERROR",
                    f"{rel(path)} hardcodes layout path expressions {hardcoded_nodes}; read project_model layout via tools/tooling_layout.py",
                )
            )
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            targets = [target.id for target in node.targets if isinstance(target, ast.Name)]
            risky = sorted(set(targets) & PATH_HARDCODE_ASSIGNMENTS)
            if not risky:
                continue
            strings = _literal_strings(node.value)
            if strings:
                issues.append(
                    Issue(
                        "ERROR",
                        f"{rel(path)} hardcodes layout assignment {risky}; read project_model layout via tools/tooling_layout.py",
                    )
                )

    for tool in registry.get("tools", []):
        for field in COMMAND_FIELDS:
            for command in tool.get(field, []):
                if " app scripts" in f" {command}" and "{fixed_quality_dirs}" not in command:
                    issues.append(
                        Issue(
                            "ERROR",
                            f"tool {tool.get('id')}.{field}: command hardcodes layout paths; use {{fixed_quality_dirs}}",
                        )
                    )


def check_registered_check_scripts(root: pathlib.Path, registry: dict, issues: list[Issue]) -> None:
    configured = {str(path) for tool in registry.get("tools", []) for path in tool.get("configured_in", [])}
    for path in sorted((root / "tools").glob("check_*.py")):
        relative = rel(path)
        if relative not in configured:
            issues.append(
                Issue(
                    "ERROR",
                    f"{relative} is a check script but is not registered in tooling.registry.toml configured_in",
                )
            )


def _semgrep_rule_applies(text: str, declared: set[str]) -> bool:
    """semgrep 规则文件声明了 languages 时,项目至少要声明其中一门才适用;不是 semgrep 文件就一律适用。

    只认 `languages: [a, b]` 这一种写法(本仓规则统一这么写)。写成多行列表就解析不出来,
    那时退回"适用"——判不准就多查一遍,别静默跳过一条本该跑的检查。
    """
    if match := re.search(r"(?m)^\s*languages:\s*\[([^\]]*)\]", text):
        needs = {item.strip().strip("\"'") for item in match.group(1).split(",") if item.strip()}
        return not needs or bool(needs & declared)
    return True


def check_layout_literals_in_side_configs(root: pathlib.Path, _registry: dict, issues: list[Issue]) -> None:
    # `_registry` 保留只为对齐 main() 里 check_*(ROOT, registry, issues) 的统一调用形状。
    allowed = _layout_path_values()
    risky_literals = DEFAULT_LAYOUT_LITERALS - allowed
    if not risky_literals:
        return
    side_configs = [
        root / ".importlinter",
        root / ".ruff.toml",
        root / ".pre-commit-config.yaml",
        *sorted((root / ".semgrep").glob("*.yml")),
        *sorted((root / ".semgrep").glob("*.yaml")),
    ]
    declared = {str(lang.get("id", "")) for lang in load_project_model().get("languages", [])}
    for path in side_configs:
        if not path.exists():
            continue
        text = read_text(path)
        # semgrep 规则自己就写着 `languages: [python]`。项目没声明那门语言时这条规则永远不会命中,
        # 再去挑它排除路径里的 `tests` 字面量是纯噪音——判据从文件里读,不靠维护一张文件名清单。
        if not _semgrep_rule_applies(text, declared):
            continue
        for literal in sorted(risky_literals):
            patterns = (
                rf"(?m)(^|[\s\"'/.*^-]){re.escape(literal)}([/.\s\"'$-]|$)",
                rf"(?m)\b{re.escape(literal)}\.",
            )
            if any(re.search(pattern, text) for pattern in patterns):
                issues.append(
                    Issue(
                        "ERROR",
                        f"{rel(path)} contains layout literal `{literal}` not present in project_model-derived layout",
                    )
                )
                break


def check_detect_secrets_exclusions_agree(root: pathlib.Path, registry: dict, issues: list[Issue]) -> None:
    """detect-secrets 的排除表在两处各写了一份(全量扫的 registry 命令 / 只扫暂存区的 pre-commit),
    两处都必须列同一批路径。

    为什么不合并成一份:一处是 TOML 里的 shell 参数,一处是 YAML 里的多行正则,没有共同的宿主。
    合不了就至少别让它们静默分叉——分叉的后果是 pre-commit 绿、全量扫红,同一份文件两种结论。
    """
    command = " ".join(
        str(item)
        for tool in registry.get("tools", [])
        if tool.get("id") == "detect-secrets"
        for item in tool.get("entrypoint_commands", [])
    )
    hook = find_pre_commit_hook(load_pre_commit_config(root / ".pre-commit-config.yaml"), "detect-secrets")
    excluded = str((hook or {}).get("exclude") or "")
    # 抹掉反斜杠再做子串比对,不要 re.escape:它会把 `-` 也转义成 `\-`,而两份正则里写的都是裸 `-`,
    # 于是"两边都找不到"→ 两边一致 → 恒真通过,这道闸就没牙了。
    for path in (".ai-config/template-state.json", "uv.lock", ".ai-config/config/settings.json"):
        in_command, in_hook = path in command.replace("\\", ""), path in excluded.replace("\\", "")
        if in_command != in_hook:
            where = "registry 命令" if in_command else "pre-commit exclude"
            issues.append(Issue("ERROR", f"detect-secrets 排除表分叉:`{path}` 只在 {where} 里排除了,另一处没有"))


def check_side_config_ownership(root: pathlib.Path, registry: dict, issues: list[Issue]) -> None:
    """受管的边车配置必须被 registry 里某个工具 configured_in 认领。

    为什么是硬断言:project_gate_state 靠 configured_in × languages 派生"这份配置归哪门语言私有",
    从而决定纯 TS 项目该不该装 `.ruff.toml`。没人认领的文件会静默落到"所有项目都装",
    多语言接管时就变成又一堆死配置——这正是本次要根除的那类漂移。
    """
    claimed = {str(name) for tool in registry.get("tools", []) for name in tool.get("configured_in", [])}
    for name in (".ruff.toml", ".importlinter", ".pre-commit-config.yaml"):
        if not (root / name).exists():
            continue
        if name not in claimed:
            issues.append(
                Issue(
                    "ERROR",
                    f"{name} 是受管边车配置但没有任何工具在 configured_in 里认领它;"
                    "语言归属无从派生,它会被装进所有项目(在 tooling.registry.toml 里补 configured_in)",
                )
            )


def check_rule_references(root: pathlib.Path, issues: list[Issue]) -> None:
    target_roots = [
        root / ".ai-config",
        root / ".semgrep",
        root / "docs",
        root / "scripts",
        root / "tools",
    ]
    targets = [root / "README.md"]
    checker_path = root / ".ai-config" / "tools" / "check_rule_tool_contracts.py"
    # 必须跳过被忽略的目录:.ai-config 下可能有闸层自己的 .venv(uv --project .ai-config),
    # 里面第三方包的文档里满是 `rules/xxx.md` 这类字符串,不跳会刷屏误报。
    # 判据取自 project_model.ignore.patterns 的静态目录名,不另立一份清单。
    # 框架级兜底:闸层自己会在 .ai-config/.venv 建虚拟环境,不能指望每个项目的校准模型都记得
    # 把它写进 ignore.patterns。
    # 这几个名字任何语言下都不是源码,由框架兜住;项目模型只做补充。
    ignored_names = {".venv", "node_modules", "__pycache__", ".git"}
    ignored_names |= {
        part
        for pattern in load_project_model().get("ignore", {}).get("patterns", [])
        for part in str(pattern).split("/")
        if part and not any(token in part for token in "*?[")
    }
    for target_root in target_roots:
        if target_root.exists():
            targets.extend(
                path
                for path in target_root.rglob("*")
                if path.is_file()
                and not (set(path.parts) & ignored_names)
                and path.suffix.lower() in {".md", ".py", ".sh", ".toml", ".yaml", ".yml", ".json", ".template"}
            )
    # 通用判据而不是"历史已删规则路径"黑名单:黑名单要求退休规则时有人记得往表里加,漏了
    # 没人会发现。这里的判据是"凡在文档/配置里被引用的规则或 semgrep 文件必须真的存在",
    # 覆盖所有过期引用且不会腐化。`*.details.md` 那类结构禁令由 check_rule_structure 管。
    for path in targets:
        if not path.exists() or path == checker_path:
            continue
        text = read_text(path)
        for match in RULE_REFERENCE_RE.finditer(text):
            ref = match.group(0)
            if any(token in ref for token in "*<>{}") or (root / ref).exists():
                continue
            if (root / ".ai-config" / ref).exists():
                continue
            issues.append(Issue("ERROR", f"{rel(path)} 引用了不存在的规则/配置文件:{ref}"))


def check_rule_structure(root: pathlib.Path, issues: list[Issue]) -> None:
    rules_dir = root / ".ai-config" / "rules"
    details = {rel(path) for path in rules_dir.rglob("*.details.md")}
    issues.extend(Issue("ERROR", f"details file must be merged into index: {path}") for path in sorted(details))

    for path in [root / ".ai-config" / "AGENTS.md", *rules_dir.rglob("*.md")]:
        text = read_text(path)
        relative_path = rel(path)
        for match in re.finditer(r"[\w./-]+\.details\.md", text):
            target = match.group(0)
            issues.append(Issue("ERROR", f"{relative_path} directly references details file: {target}"))

    for path in rules_dir.rglob("*.index.md"):
        content_lines = [
            line.strip() for line in read_text(path).splitlines() if line.strip() and not line.lstrip().startswith("#")
        ]
        if len(content_lines) < 3:
            issues.append(Issue("ERROR", f"{rel(path)} appears to be an empty or placeholder index"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", type=pathlib.Path, default=REGISTRY)
    args = parser.parse_args()

    registry_path = args.registry if args.registry.is_absolute() else ROOT / args.registry
    registry = load_toml(registry_path)
    issues: list[Issue] = []

    check_metadata(ROOT, registry, issues)
    check_project_model(ROOT, issues)
    check_code_layout(ROOT, registry, issues)
    check_code_layout_consumers(ROOT, registry, issues)
    check_registered_check_scripts(ROOT, registry, issues)
    check_layout_literals_in_side_configs(ROOT, registry, issues)
    check_side_config_ownership(ROOT, registry, issues)
    check_detect_secrets_exclusions_agree(ROOT, registry, issues)
    check_gitignore(ROOT, issues)
    check_tools(ROOT, registry, issues)
    check_scan_command_hygiene(registry, issues)
    check_ci_semantics(ROOT, issues)
    check_enforcement_wiring(ROOT, registry, issues)
    check_rule_tool_contracts_trigger(ROOT, issues)
    check_semgrep_rulesets(ROOT, registry, issues)
    check_no_repository_ai_hooks(ROOT, registry, issues)
    check_path_triggers(ROOT, registry, issues)
    check_declarative_stages(ROOT, registry, issues)
    check_rule_references(ROOT, issues)
    check_rule_structure(ROOT, issues)

    if issues:
        sys.stderr.write("Rule/tool contract check failed:\n")
        for issue in issues:
            sys.stderr.write(f"[{issue.severity}] {issue.message}\n")
        return 1

    sys.stdout.write("Rule/tool contract check passed.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
