#!/usr/bin/env python3
# 职责：生成 stage 承重材料包：改动文件、契约/依赖/入口/API/删除改名风险。
# 不做什么：不修复问题；不替人判断设计优劣；不把候选风险直接当结论。
# 允许依赖层：标准库、git、本仓 project_model/inventory。
# 谁不应该 import：正式业务代码、测试夹具、应用入口不应 import 本工具。
"""Build the stage review packet from git diff plus inventory."""

from __future__ import annotations

import argparse
import ast
import functools
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import inventory as inventory_tool
import lang_python
import tooling_registry
from project_model import load_project_model, load_project_model_dict, path_matches, source_suffixes
from review_fingerprint import report_fingerprint

ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / ".ai-config" / "config" / "tooling.registry.toml"
PACKET_PATH = ROOT / ".cache" / "stage-packet.json"
KNOWN_RISK_CONDITIONS = {
    "changed_contract_files",
    "changed_dependency_files",
    "zone_trait_changed",
    "python_deleted_or_renamed",
    "public_api_changed",
    "inventory_violation",
    "changed_python_unclassified",
    "zone_trait_changed_without_trait",
}
# `git diff --name-status` 一行的最少字段数：改名是 status/old/new 三列，其余是 status/path 两列。
RENAME_NAME_STATUS_FIELDS = 3
NAME_STATUS_FIELDS = 2
# `git diff --numstat` 一行是 added/removed/path 三列。
NUMSTAT_FIELDS = 3


def git(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", "-c", "core.quotePath=false", *args], cwd=ROOT, text=True, capture_output=True, check=False)


@functools.cache
def git_prefix() -> str:
    proc = git(["rev-parse", "--show-prefix"])
    return proc.stdout.strip().strip("/")


def git_blob_path(path_name: str) -> str:
    prefix = git_prefix()
    return f"{prefix}/{path_name}" if prefix else path_name


def strip_git_prefix(path_name: str) -> str:
    prefix = git_prefix()
    if prefix and path_name.startswith(f"{prefix}/"):
        return path_name[len(prefix) + 1 :]
    return path_name


def changed_name_status(*, include_untracked: bool = True) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for args in (
        ["diff", "--relative", "--name-status", "--diff-filter=ACMRD"],
        ["diff", "--relative", "--cached", "--name-status", "--diff-filter=ACMRD"],
    ):
        proc = git(args)
        if proc.returncode != 0:
            continue
        for line in proc.stdout.splitlines():
            parts = line.split("\t")
            if not parts:
                continue
            status = parts[0]
            if status.startswith("R") and len(parts) >= RENAME_NAME_STATUS_FIELDS:
                rows.append({"status": "R", "old_path": strip_git_prefix(parts[1]), "path": strip_git_prefix(parts[2])})
            elif len(parts) >= NAME_STATUS_FIELDS:
                rows.append({"status": status[:1], "path": strip_git_prefix(parts[1])})
    if include_untracked:
        other = git(["ls-files", "--others", "--exclude-standard", "--", "."])
        rows.extend(
            {"status": "A", "path": strip_git_prefix(name.strip()), "untracked": "true"}
            for name in other.stdout.splitlines()
            if name.strip()
        )
    seen: set[tuple[str, str, str]] = set()
    deduped: list[dict[str, str]] = []
    for row in rows:
        key = (row.get("status", ""), row.get("old_path", ""), row.get("path", ""))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return sorted(deduped, key=lambda item: (item.get("path", ""), item.get("old_path", "")))


def diff_stats() -> dict[str, dict[str, int]]:
    stats: dict[str, dict[str, int]] = {}
    for args in (
        ["diff", "--relative", "--numstat"],
        ["diff", "--relative", "--cached", "--numstat"],
    ):
        proc = git(args)
        if proc.returncode != 0 or not proc.stdout:
            continue
        for line in proc.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) < NUMSTAT_FIELDS:
                continue
            added, removed, path = parts[0], parts[1], strip_git_prefix(parts[2])
            row = stats.setdefault(path, {"added_lines": 0, "removed_lines": 0})
            row["added_lines"] += int(added) if added.isdigit() else 0
            row["removed_lines"] += int(removed) if removed.isdigit() else 0
    return stats


@functools.cache
def current_public_symbols(path_name: str) -> frozenset[str]:
    path = ROOT / path_name
    if not path.exists() or path.suffix != ".py":
        return frozenset()
    try:
        module = ast.parse(path.read_text(encoding="utf-8"), filename=path_name)
    except (OSError, SyntaxError, UnicodeDecodeError):
        return frozenset()
    collector = lang_python.ImportCollector()
    collector.visit(module)
    return frozenset(f"{item['kind']}:{item['name']}" for item in collector.public_symbols)


@functools.cache
def old_public_symbols(path_name: str) -> frozenset[str]:
    proc = git(["show", f"HEAD:{git_blob_path(path_name)}"])
    if proc.returncode != 0:
        return frozenset()
    try:
        module = ast.parse(proc.stdout, filename=path_name)
    except SyntaxError:
        return frozenset()
    collector = lang_python.ImportCollector()
    collector.visit(module)
    return frozenset(f"{item['kind']}:{item['name']}" for item in collector.public_symbols)


def zone_has_trait(model: inventory_tool.ProjectModel, zone_id: object, trait: str) -> bool:
    if not trait:
        return False
    for zone in model.zones:
        if zone.id == zone_id:
            return trait in zone.traits
    return False


def changed_entrypoints(changed: list[dict], inventory: dict, model: inventory_tool.ProjectModel) -> list[dict[str, object]]:
    changed_paths = {str(item.get("path", "")) for item in changed}
    results: list[dict[str, object]] = []
    entrypoints = inventory.get("entrypoints", [])
    if not entrypoints:
        return [
            {"id": item["path"], "file": item["path"], "kind": "legacy", "member": "root"}
            for item in changed
            if zone_has_trait(model, item["zone"], "entrypoint")
        ]
    for entrypoint in entrypoints:
        file_name = str(entrypoint.get("file", ""))
        if file_name and file_name in changed_paths:
            results.append(entrypoint)
    return results


def evaluate_risk_rules(packet: dict, model: inventory_tool.ProjectModel, inventory: dict) -> list[str]:
    flags: list[str] = []
    changed = packet["changed_files"]
    for rule in model.risk_rules:
        if rule.condition not in KNOWN_RISK_CONDITIONS:
            raise SystemExit(f"[stage-packet] unknown risk condition in {rule.id}: {rule.condition}")
        matched = False
        if rule.condition == "changed_contract_files":
            matched = bool(packet["contract_files"])
        elif rule.condition == "changed_dependency_files":
            matched = bool(packet["dependency_files"])
        elif rule.condition == "zone_trait_changed":
            matched = any(zone_has_trait(model, item["zone"], rule.zone_trait) for item in changed)
        elif rule.condition == "python_deleted_or_renamed":
            matched = bool(packet["deleted_or_renamed_python"])
        elif rule.condition == "public_api_changed":
            matched = bool(packet["public_symbols_added"] or packet["public_symbols_removed"])
        elif rule.condition == "inventory_violation":
            matched = any(
                violation.get("kind") == rule.violation_kind for violation in inventory.get("violations", [])
            )
        elif rule.condition == "changed_python_unclassified":
            matched = any(item["zone"] == "unclassified" and is_declared_source(item["path"]) for item in changed)
        elif rule.condition == "zone_trait_changed_without_trait":
            source_changed = any(zone_has_trait(model, item["zone"], rule.source_trait) for item in changed)
            companion_changed = any(zone_has_trait(model, item["zone"], rule.companion_trait) for item in changed)
            matched = source_changed and not companion_changed
        if matched:
            flags.append(rule.id)
    return sorted(set(flags))


def declared_language_ids() -> set[str]:
    return tooling_registry.declared_language_ids(load_project_model_dict())


def is_declared_source(path_name: str) -> bool:
    """这个路径是不是本项目声明语言的源码。

    写死 `.py` 的后果是**错标而不是漏报**:实测纯 TS 项目里 src/utils/x.ts 被打成 zone=non_python,
    而它明明在 formal 区 —— 提交前给人和子 agent 看的就是这份 packet,标错等于把复核引到沟里。
    """
    return Path(path_name).suffix in set(source_suffixes(load_project_model()))


def skipped_stage_tools() -> list[dict[str, object]]:
    registry = tooling_registry.load_registry(REGISTRY_PATH)
    skipped: list[dict[str, object]] = []
    for tool in registry.get("tools", []):
        tool_id = str(tool.get("id", "")).strip()
        if not tool_id or "stage" not in [str(stage) for stage in tool.get("stages", [])]:
            continue
        # 语言不适用的工具本来就不该跑,把它记成"必需工具被跳过"会让纯 TS 项目每次提交都举一面
        # 假风险旗(实测:import-linter 缺 .importlinter —— 而那份配置正是按语言故意不装的)。
        if not tooling_registry.applies_to_languages(tool, declared_language_ids()):
            continue
        missing = tooling_registry.missing_required_paths(tool_id, ROOT, registry)
        if missing:
            skipped.append(
                {
                    "tool": tool_id,
                    "stage_gate": str(tool.get("stage_gate") or "unclassified"),
                    "missing_required_paths": missing,
                }
            )
    return skipped


def build_packet() -> dict:
    model = inventory_tool.load_project_model()
    inventory = inventory_tool.build_inventory(scope="changed")
    zone_by_path = {file["path"]: file["zone"] for file in inventory["files"]}
    symbols_by_path = {
        str(file["path"]): frozenset(f"{item['kind']}:{item['name']}" for item in file.get("public_symbols", []))
        for file in inventory["files"]
    }
    stats = diff_stats()
    changed = []
    public_added = []
    public_removed = []
    foreign = model.metadata.governance_mode == "foreign"
    for row in changed_name_status(include_untracked=not foreign):
        path = row.get("path", "")
        if row.get("status") == "D":
            zone = "deleted"
        elif not is_declared_source(path):
            zone = "non_source"
        else:
            zone = zone_by_path.get(path, "unclassified")
        changed.append({**row, "zone": zone, **stats.get(path, {})})
        if path.endswith(".py") and row.get("status") != "D":
            current_symbols = symbols_by_path.get(path, current_public_symbols(path))
            old_symbols = old_public_symbols(str(row.get("old_path") or path))
            added = sorted(current_symbols - old_symbols)
            removed = sorted(old_symbols - current_symbols)
            public_added.extend({"path": path, "symbol": symbol} for symbol in added)
            public_removed.extend({"path": path, "symbol": symbol} for symbol in removed)
    contract_files = [
        item["path"]
        for item in changed
        if path_matches(item["path"], model.contracts.contract_files)
    ]
    dependency_files = [
        item["path"]
        for item in changed
        if path_matches(item["path"], model.contracts.dependency_files)
    ]
    entrypoints_changed = changed_entrypoints(changed, inventory, model)
    deleted_or_renamed_python = [
        item for item in changed if item["path"].endswith(".py") and item["status"] in {"D", "R"}
    ]
    packet = {
        "schema_version": 1,
        "scope": "changed",
        "input_fingerprint": report_fingerprint(ROOT, "changed"),
        "governance_mode": model.metadata.governance_mode,
        "managed_baselines": model.governance.managed_baselines,
        "purpose": "maintenance_impact" if foreign else "quality_review",
        "changed_files": changed,
        "contract_files": contract_files,
        "dependency_files": dependency_files,
        "entrypoints_changed": entrypoints_changed,
        "deleted_or_renamed_python": deleted_or_renamed_python,
        "public_symbols_added": public_added,
        "public_symbols_removed": public_removed,
        "import_policy_violations": [
            violation
            for violation in inventory.get("violations", [])
            if violation.get("kind") == "import_policy_violation"
        ],
        "stage_tool_skips": skipped_stage_tools(),
    }
    packet["risk_flags"] = [] if foreign else evaluate_risk_rules(packet, model, inventory)
    if not foreign and packet["stage_tool_skips"]:
        packet["risk_flags"].append("stage_required_tool_skipped")
    if not foreign and any(item.get("stage_gate") == "dependency" for item in packet["stage_tool_skips"]):
        packet["risk_flags"].append("stage_dependency_tool_skipped")
    packet["risk_flags"] = sorted(set(packet["risk_flags"]))
    return packet


def write_packet(packet: dict, path: Path = PACKET_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(packet, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["build", "print"], nargs="?", default="build")
    args = parser.parse_args(argv)
    packet = build_packet()
    if args.command == "print":
        print(json.dumps(packet, ensure_ascii=False, indent=2))
        return 0
    write_packet(packet)
    print(f"[stage-packet] wrote {PACKET_PATH.relative_to(ROOT)}")
    print(f"[stage-packet] risk_flags: {', '.join(packet['risk_flags']) or 'none'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
