#!/usr/bin/env python3
# 职责：发现 project_model 没覆盖但有承重证据的异常结构，生成审查材料。
# 不做什么：不猜 formal/test/tool 身份，不自动修改 project_model，不批准放行。
# 允许依赖层：标准库、本仓 project_model/inventory/tooling registry。
# 谁不应该 import：正式业务代码、测试夹具、应用入口不应 import 本工具。
"""Find unmodeled project structures that deserve human review."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path, PurePosixPath
from typing import TypedDict

sys.path.insert(0, str(Path(__file__).resolve().parent))
import evidence_extractors as evidence
import git_changes
import inventory as inventory_tool
import tooling_registry
from project_model import zone_traits_map
from review_fingerprint import cached_report, report_fingerprint

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = ROOT / ".cache" / "project-discovery.json"
MIN_CODE_ISLAND_FILES = 3


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def structure_key(path_name: str, project_roots: tuple[str, ...] = ()) -> str:
    for root in sorted(project_roots, key=len, reverse=True):
        if inventory_tool.is_under(path_name, root):
            return root
    parts = PurePosixPath(path_name).parts
    if not parts:
        return path_name
    if len(parts) == 1:
        return path_name
    return parts[0]


def entrypoint_candidate_reason(path_name: str) -> str:
    return evidence.python_entrypoint_reason(path_name, ROOT / path_name)


def is_generic_entrypoint_candidate(path_name: str) -> bool:
    return generic_entrypoint_candidate_reason(path_name) != ""


def generic_entrypoint_candidate_reason(path_name: str) -> str:
    return evidence.generic_entrypoint_reason(path_name)


def registry_command_targets() -> set[str]:
    registry = tooling_registry.load_registry()
    targets: set[str] = set()
    for tool in registry.get("tools", []):
        for field in ("entrypoint_commands", "ci_commands", "manual_commands"):
            for command in tool.get(field, []):
                target = tooling_registry.uv_run_python_script_target(str(command))
                if target and target.startswith("tools/"):
                    targets.add(target)
    return targets


def is_orphan_tool_path(path_name: str) -> bool:
    path = PurePosixPath(path_name)
    return (
        path.parent == PurePosixPath("tools")
        and path.suffix == ".py"
        and path.name != "__init__.py"
        and evidence.has_python_main_guard(ROOT / path_name, filename=path_name)
    )


def project_marker_groups(model: inventory_tool.ProjectModel | None = None) -> dict[str, list[str]]:
    source_model = model or inventory_tool.load_project_model()
    ignored = inventory_tool.pathspec_from(source_model.ignore.patterns)
    groups: dict[str, list[str]] = {}
    for dirpath, dirnames, filenames in os.walk(ROOT):
        directory = Path(dirpath)
        rel_dir = "" if directory == ROOT else rel(directory)
        kept_dirs: list[str] = []
        for dirname in dirnames:
            child_name = dirname if not rel_dir else f"{rel_dir}/{dirname}"
            if inventory_tool.is_ignored_directory(child_name, ignored):
                continue
            kept_dirs.append(dirname)
        dirnames[:] = kept_dirs
        for marker in evidence.PROJECT_MARKER_NAMES:
            if marker not in filenames:
                continue
            path = directory / marker
            if path == ROOT / marker:
                continue
            path_name = rel(path)
            if ignored.match_file(path_name):
                continue
            groups.setdefault(str(PurePosixPath(path_name).parent), []).append(path_name)
    return {key: sorted(values) for key, values in sorted(groups.items())}


def iter_project_markers(groups: dict[str, list[str]]) -> list[dict[str, object]]:
    findings: list[dict[str, object]] = []
    for root, markers in groups.items():
        findings.append(
            review_evidence_finding(
                "embedded_project_candidate",
                root,
                f"{root}: nested project marker needs member/workspace review",
                [f"{len(markers)} nested project markers found below repository root"],
                {"markers": markers, "marker_count": len(markers)},
            )
        )
    return findings


def finding(  # noqa: PLR0913  这 7 个参数就是 finding 记录的 7 个固定字段，合并成对象只是把同样的字段换个地方填，还会改动产物 schema 与全部调用方
    kind: str,
    path: str,
    severity: str,
    message: str,
    reasons: list[str] | None = None,
    evidence: dict[str, object] | None = None,
    status: str = "needs_human_decision",
) -> dict[str, object]:
    return {
        "kind": kind,
        "path": path,
        "severity": severity,
        "message": message,
        "reasons": reasons or [],
        "evidence": evidence or {},
        "status": status,
    }


def review_evidence_finding(
    kind: str,
    path: str,
    message: str,
    reasons: list[str] | None = None,
    evidence: dict[str, object] | None = None,
) -> dict[str, object]:
    payload = dict(evidence or {})
    payload.setdefault("evidence_role", "subagent_review_hint")
    payload.setdefault("decision_role", "evidence_only")
    payload.setdefault("blocking", False)
    payload.setdefault("heuristic", True)
    return finding(
        kind,
        path,
        "observed",
        message,
        reasons,
        payload,
        status="needs_subagent_review",
    )


class IslandGroup(TypedDict):
    """一个"代码孤岛"分组的累加器。

    原来是 dict[str, object]:值类型退化成 object 后,`group["paths"].append(...)` 这类写法
    静态上全都不合法 —— basedpyright 在本文件报了 31 条,其中一多半就是这一个根因。
    写成 TypedDict 不是为了让类型检查器闭嘴:字段名和元素类型本来就是这份结构的契约,
    退化成 object 等于把契约从代码里删掉,改错了也没人拦。
    """

    paths: list[str]
    entrypoints: list[str]
    entrypoint_reasons: dict[str, str]
    imported_by: list[str]
    test_imported_by: list[str]
    parse_errors: list[str]
    unresolved_import_evidence: list[dict[str, object]]


def _new_island_group() -> IslandGroup:
    return {
        "paths": [],
        "entrypoints": [],
        "entrypoint_reasons": {},
        "imported_by": [],
        "test_imported_by": [],
        "parse_errors": [],
        "unresolved_import_evidence": [],
    }


def _island_groups_from_files(inventory: dict, project_roots: tuple[str, ...]) -> dict[str, dict[str, object]]:
    groups: dict[str, dict[str, object]] = {}
    for file_record in inventory.get("files", []):
        if file_record.get("zone") != "unclassified":
            continue
        path_name = str(file_record.get("path", ""))
        key = structure_key(path_name, project_roots)
        group = groups.setdefault(key, _new_island_group())
        group["paths"].append(path_name)
        if reason := entrypoint_candidate_reason(path_name):
            group["entrypoints"].append(path_name)
            group["entrypoint_reasons"][path_name] = reason
        if file_record.get("parse_error"):
            group["parse_errors"].append(path_name)
    return groups


def _add_island_import_edges(
    inventory: dict, project_roots: tuple[str, ...], groups: dict[str, dict[str, object]]
) -> None:
    def group_for_unresolved_import(root: str) -> str:
        matches = [
            key
            for key, group in groups.items()
            if any(
                path == f"{key}/{root}.py"
                or path.startswith(f"{key}/{root}/")
                or (key == root and (path == f"{root}.py" or path.startswith(f"{root}/")))
                for path in group["paths"]
            )
        ]
        return matches[0] if len(matches) == 1 else ""

    for edge in inventory.get("edges", []):
        target_path = str(edge.get("target_path") or "")
        if not target_path:
            target_root = str(edge.get("target_root") or "")
            key = group_for_unresolved_import(target_root) if target_root else ""
            if not key:
                continue
            group = groups[key]
            source = str(edge.get("source") or "")
            group["imported_by"].append(source)
            group["unresolved_import_evidence"].append(
                {"source": source, "target_root": target_root, "module": edge.get("module")}
            )
            if edge.get("source_zone") == "test":
                group["test_imported_by"].append(source)
            continue
        if edge.get("target_zone") != "unclassified":
            continue
        key = structure_key(target_path, project_roots)
        group = groups.setdefault(key, _new_island_group())
        source = str(edge.get("source") or "")
        group["imported_by"].append(source)
        if edge.get("source_zone") == "test":
            group["test_imported_by"].append(source)


def _island_finding(key: str, group: IslandGroup) -> dict[str, object] | None:
    paths = sorted({str(item) for item in group["paths"]})
    imported_by = sorted({str(item) for item in group["imported_by"]})
    entrypoints = sorted({str(item) for item in group["entrypoints"]})
    entrypoint_reasons = {path: str(group["entrypoint_reasons"].get(path, "unknown")) for path in entrypoints}
    test_imported_by = sorted({str(item) for item in group["test_imported_by"]})
    parse_errors = sorted({str(item) for item in group["parse_errors"]})
    unresolved_import_evidence = group["unresolved_import_evidence"]
    has_review_signal = bool(imported_by or entrypoints or parse_errors or test_imported_by)
    has_review_signal = has_review_signal or len(paths) >= MIN_CODE_ISLAND_FILES
    if not (has_review_signal or paths):
        return None
    reasons: list[str] = [f"{len(paths)} Python files outside project_model"]
    if imported_by:
        reasons.append(f"imported by {len(imported_by)} files")
    if entrypoints:
        reasons.append(f"{len(entrypoints)} entrypoint candidates")
    if test_imported_by:
        reasons.append(f"referenced by {len(test_imported_by)} test files")
    if parse_errors:
        reasons.append(f"{len(parse_errors)} parse errors")
    return review_evidence_finding(
        "unmodeled_code_structure",
        key,
        f"{key}: {'; '.join(reasons)}; identity is unknown and must be declared or ignored",
        reasons,
        {
            "paths_sample": paths[:30],
            "file_count": len(paths),
            "imported_by_sample": imported_by[:30],
            "entrypoint_candidates": entrypoints[:30],
            "entrypoint_reasons": entrypoint_reasons,
            "test_imported_by_sample": test_imported_by[:30],
            "parse_error_paths": parse_errors[:30],
            "unresolved_import_evidence_sample": unresolved_import_evidence[:30],
            "source": "inventory_plus_discovery_heuristics",
        },
    )


def unclassified_islands(inventory: dict, project_roots: tuple[str, ...] = ()) -> list[dict[str, object]]:
    groups = _island_groups_from_files(inventory, project_roots)
    _add_island_import_edges(inventory, project_roots, groups)
    candidates = (_island_finding(key, group) for key, group in sorted(groups.items()))
    return [item for item in candidates if item is not None]


def iter_unmodeled_source_files(model: inventory_tool.ProjectModel, candidates: set[str] | None = None) -> list[str]:
    ignored = inventory_tool.pathspec_from(model.ignore.patterns)
    paths: list[str] = []
    if candidates is not None:
        for path_name in sorted(candidates):
            path = ROOT / path_name
            if not path.exists() or path.suffix == ".py" or not evidence.is_probable_source_file(path_name):
                continue
            if ignored.match_file(path_name):
                continue
            if inventory_tool.classify(path_name, model)[0] != "unclassified":
                continue
            paths.append(path_name)
        return paths
    for dirpath, dirnames, filenames in os.walk(ROOT):
        directory = Path(dirpath)
        rel_dir = "" if directory == ROOT else rel(directory)
        kept_dirs: list[str] = []
        for dirname in dirnames:
            child_name = dirname if not rel_dir else f"{rel_dir}/{dirname}"
            if inventory_tool.is_workspace_member_path(child_name, model) or inventory_tool.is_ignored_directory(
                child_name, ignored
            ):
                continue
            kept_dirs.append(dirname)
        dirnames[:] = kept_dirs
        for filename in filenames:
            path = directory / filename
            if path.suffix == ".py" or not evidence.is_probable_source_file(rel(path)):
                continue
            path_name = rel(path)
            if ignored.match_file(path_name):
                continue
            if inventory_tool.classify(path_name, model)[0] != "unclassified":
                continue
            paths.append(path_name)
    return sorted(paths)


def unmodeled_source_structures(
    model: inventory_tool.ProjectModel, candidates: set[str] | None = None
) -> list[dict[str, object]]:
    groups: dict[str, list[str]] = {}
    for path_name in iter_unmodeled_source_files(model, candidates=candidates):
        groups.setdefault(structure_key(path_name), []).append(path_name)
    findings: list[dict[str, object]] = []
    for key, paths in sorted(groups.items()):
        entrypoints = [path for path in paths if is_generic_entrypoint_candidate(path)]
        entrypoint_reasons = {path: generic_entrypoint_candidate_reason(path) for path in entrypoints}
        has_review_signal = bool(entrypoints) or len(paths) >= MIN_CODE_ISLAND_FILES
        if not has_review_signal:
            continue
        reasons = [f"{len(paths)} source files outside project_model"]
        if entrypoints:
            reasons.append(f"{len(entrypoints)} generic entrypoint candidates")
        findings.append(
            review_evidence_finding(
                "unmodeled_source_structure",
                key,
                f"{key}: {'; '.join(reasons)}; identity is unknown and must be declared or ignored",
                reasons,
                {
                    "paths_sample": paths[:30],
                    "file_count": len(paths),
                    "entrypoint_candidates": entrypoints[:30],
                    "entrypoint_reasons": entrypoint_reasons,
                    "source": "source_suffix_plus_filename_heuristics",
                },
            )
        )
    return findings


def orphan_tool_findings(inventory: dict) -> list[dict[str, object]]:
    command_targets = registry_command_targets()
    findings: list[dict[str, object]] = []
    for file_record in inventory.get("files", []):
        path_name = str(file_record.get("path") or "")
        if not is_orphan_tool_path(path_name):
            continue
        if path_name in command_targets:
            continue
        findings.append(
            review_evidence_finding(
                "orphan_tool",
                path_name,
                f"{path_name}: top-level tool script has no registry consumer",
                ["top-level tools/*.py path is not a registry Python command target"],
                {
                    "rule": "top-level tools/*.py must be registered, utility, renamed private, or archived",
                    "path": path_name,
                    "registry_command_target_present": False,
                    "registry_command_target_count": len(command_targets),
                    "decision_needed": "register it, rename it as utility/private, or delete/archive it",
                    "source": "registry_cross_check",
                },
            )
        )
    return findings


def temp_weight_bearing_findings(inventory: dict, model: inventory_tool.ProjectModel) -> list[dict[str, object]]:
    traits = zone_traits_map(model)
    findings: list[dict[str, object]] = []
    for edge in inventory.get("edges", []):
        source_zone = str(edge.get("source_zone") or "")
        target_zone = str(edge.get("target_zone") or "")
        if "formal_like" not in traits.get(source_zone, set()):
            continue
        if "ephemeral" not in traits.get(target_zone, set()):
            continue
        findings.append(
            review_evidence_finding(
                "temp_becomes_weight_bearing",
                str(edge.get("target_path") or edge.get("module") or ""),
                (
                    f"{edge.get('source')}: formal-like code imports ephemeral zone "
                    f"{target_zone} via {edge.get('module')}"
                ),
                ["formal-like source imports ephemeral target"],
                {
                    "edge": edge,
                    "source": "inventory_import_edge",
                    "note": "Evidence only here; blocking belongs to inventory import_policy_violation.",
                },
            )
        )
    return findings


def as_evidence_only(item: dict[str, object]) -> dict[str, object]:
    normalized = dict(item)
    evidence_payload = dict(normalized.get("evidence") or {})
    evidence_payload.setdefault("evidence_role", "subagent_review_hint")
    evidence_payload.setdefault("decision_role", "evidence_only")
    evidence_payload["blocking"] = False
    normalized["evidence"] = evidence_payload
    severity = str(normalized.get("severity") or "observed")
    if severity != "observed":
        normalized["original_severity"] = severity
        normalized["severity"] = "observed"
        reasons = [str(reason) for reason in normalized.get("reasons", [])]
        reasons.append(
            f"downgraded from {severity}: project_discovery is evidence-only; "
            "blocking belongs to inventory/model policy"
        )
        normalized["reasons"] = reasons
    return normalized


def declared_empty_findings(inventory: dict, model: inventory_tool.ProjectModel) -> list[dict[str, object]]:
    files = [str(item.get("path", "")) for item in inventory.get("files", [])]
    findings: list[dict[str, object]] = []
    for zone in model.zones:
        for directory in zone.dirs:
            if not (ROOT / directory).is_dir():
                continue
            if any(inventory_tool.is_under(path, directory) for path in files):
                continue
            findings.append(
                finding(
                    "declared_but_empty",
                    directory,
                    "observed",
                    f"{directory}: declared in zone.{zone.id}.dirs but no Python files were found",
                    ["declared directory has no Python files in inventory"],
                    {
                        "zone": zone.id,
                        "declared_in": f"zone.{zone.id}.dirs",
                        "directory_exists": (ROOT / directory).exists(),
                    },
                )
            )
        for path_name in zone.files:
            if path_name in files or (ROOT / path_name).exists():
                continue
            findings.append(
                finding(
                    "declared_file_missing",
                    path_name,
                    "suspicious",
                    f"{path_name}: declared in zone.{zone.id}.files but file is missing",
                    ["declared file path does not exist"],
                    {
                        "zone": zone.id,
                        "declared_in": f"zone.{zone.id}.files",
                        "file_exists": False,
                    },
                )
            )
    return findings


def build_report(scope: str = "full") -> dict[str, object]:
    model = inventory_tool.load_project_model()
    inventory = cached_report(inventory_tool.INVENTORY_PATH, ROOT, scope=scope)
    if inventory is None:
        inventory = inventory_tool.build_inventory(scope=scope)
        inventory_tool.write_inventory(inventory)
    findings: list[dict[str, object]] = []
    marker_groups = project_marker_groups(model) if scope == "full" else {}
    findings.extend(unclassified_islands(inventory, tuple(marker_groups)))
    source_candidates = None if scope == "full" else git_changes.changed_file_names()
    findings.extend(unmodeled_source_structures(model, candidates=source_candidates))
    if scope == "full":
        findings.extend(iter_project_markers(marker_groups))
        findings.extend(orphan_tool_findings(inventory))
        findings.extend(declared_empty_findings(inventory, model))
    findings.extend(temp_weight_bearing_findings(inventory, model))
    findings = [as_evidence_only(item) for item in findings]
    severity_order = {"critical": 0, "suspicious": 1, "observed": 2}
    findings = sorted(
        findings, key=lambda item: (severity_order.get(str(item["severity"]), 9), str(item["kind"]), str(item["path"]))
    )
    counts: dict[str, int] = {}
    for item in findings:
        severity = str(item["severity"])
        counts[severity] = counts.get(severity, 0) + 1
    return {
        "schema_version": 1,
        "scope": scope,
        "input_fingerprint": report_fingerprint(ROOT, scope),
        "summary": {
            "finding_count": len(findings),
            "critical": counts.get("critical", 0),
            "suspicious": counts.get("suspicious", 0),
            "observed": counts.get("observed", 0),
        },
        "findings": findings,
    }


def write_report(report: dict[str, object], path: Path = OUTPUT_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def print_human_summary(report: dict[str, object]) -> None:
    summary = report["summary"]
    print(
        "[project-discovery] "
        f"findings={summary['finding_count']} critical={summary['critical']} "
        f"suspicious={summary['suspicious']} observed={summary['observed']} scope={report['scope']}"
    )
    for item in report["findings"][:30]:
        print(f"  - [{item['severity']}] {item['kind']} {item['path']}: {item['message']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["scan", "anomalies", "check", "print"], nargs="?", default="check")
    parser.add_argument("--scope", choices=["full", "changed"], default="full")
    args = parser.parse_args(argv)

    report = build_report(scope=args.scope)
    if args.command in {"scan", "anomalies", "check"}:
        write_report(report)
        print(f"[project-discovery] wrote {OUTPUT_PATH.relative_to(ROOT)}")
        print_human_summary(report)
    if args.command == "print":
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    if args.command == "scan":
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
