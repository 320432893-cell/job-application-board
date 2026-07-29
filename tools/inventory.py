#!/usr/bin/env python3
# 职责：把项目模型编译成文件/工具/依赖边 inventory，并检查“身份、消费者、越界依赖”闭包。
# 不做什么：不判断抽象好坏；不自动修项目结构；不替代业务语义审查。
# 允许依赖层：标准库、pydantic、pathspec、.ai-config/project_model.toml、tooling registry。
# 谁不应该 import：正式业务代码、测试夹具、应用入口不应 import 本工具。
"""Build and check repository inventory from the project model."""

from __future__ import annotations

import argparse
import functools
import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path, PurePosixPath

sys.path.insert(0, str(Path(__file__).resolve().parent))
import baseline_policy
import error_report
import lang_go
import lang_python
import lang_typescript
from inventory_model_coverage import quality_coverage_violations
from pathspec import GitIgnoreSpec, PathSpec
from project_model import (
    EntryPoint,
    ProjectModel,
    Zone,
    ZoneSelector,
    excluded_member_roots,
    load_project_model,
    managed_baseline_path,
    path_matches,
    source_include_globs,
    source_suffixes,
    zone_traits_map,
)
from review_fingerprint import report_fingerprint

ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH = ROOT / ".ai-config" / "project_model.toml"
REGISTRY_PATH = ROOT / ".ai-config" / "config" / "tooling.registry.toml"
INVENTORY_PATH = ROOT / ".cache" / "inventory.json"
# `git diff --name-status --diff-filter=R` 一行是 status/old/new 三列，少于三列说明不是可用的改名记录。
RENAME_NAME_STATUS_FIELDS = 3
# feature 路径至少要有 <feature>/<文件> 两段，才能判定它属于某个 feature。
FEATURE_PATH_MIN_PARTS = 2


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def load_registry() -> dict:
    if not REGISTRY_PATH.exists():
        return {}
    return tomllib.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def git(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", "-c", "core.quotePath=false", *args], cwd=ROOT, text=True, capture_output=True, check=False)


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


def changed_python_names() -> set[str]:
    return {name for name in changed_file_names(("*.py",)) if name.endswith(".py")}


def removed_python_names() -> set[str]:
    names: set[str] = set()
    for args in (
        ["diff", "--relative", "--name-only", "--diff-filter=D", "--", "*.py"],
        ["diff", "--relative", "--cached", "--name-only", "--diff-filter=D", "--", "*.py"],
    ):
        proc = git(args)
        if proc.returncode != 0:
            continue
        names.update(strip_git_prefix(line.strip()) for line in proc.stdout.splitlines() if line.strip())
    for args in (
        ["diff", "--relative", "--name-status", "--diff-filter=R", "--", "*.py"],
        ["diff", "--relative", "--cached", "--name-status", "--diff-filter=R", "--", "*.py"],
    ):
        proc = git(args)
        if proc.returncode != 0:
            continue
        for line in proc.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) >= RENAME_NAME_STATUS_FIELDS:
                names.add(strip_git_prefix(parts[1].strip()))
    return {name for name in names if name.endswith(".py")}


def pathspec_from(patterns: list[str]) -> PathSpec:
    return GitIgnoreSpec.from_lines(patterns)


def is_under(path_name: str, directory: str) -> bool:
    clean = directory.strip().strip("/")
    return bool(clean) and (path_name == clean or path_name.startswith(f"{clean}/"))


def is_under_any(path_name: str, prefixes: list[str] | tuple[str, ...] | set[str]) -> bool:
    clean_prefixes = [prefix.strip().strip("/") for prefix in prefixes if str(prefix).strip().strip("/")]
    return not clean_prefixes or any(is_under(path_name, prefix) for prefix in clean_prefixes)


def is_workspace_member_path(path_name: str, model: ProjectModel) -> bool:
    return any(is_under(path_name, root) for root in excluded_member_roots(model))


def member_for_path(path_name: str, model: ProjectModel) -> str:
    matches = [
        (len(member.root.strip().strip("/")), member.id)
        for member in model.members
        if is_under(path_name, member.root)
    ]
    if not matches:
        return "root"
    return max(matches, key=lambda item: item[0])[1]


def member_records(model: ProjectModel) -> list[dict[str, object]]:
    root_member = {
        "id": "root",
        "root": ".",
        "description": "repository root",
        "exclude_from_parent": False,
        "source_roots": [],
        "test_roots": [],
        "package_roots": [],
        "default_zones": [],
        "contract_files": model.contracts.contract_files,
        "dependency_files": model.contracts.dependency_files,
    }
    return [
        root_member,
        *[
            {
                "id": member.id,
                "root": member.root,
                "description": member.description,
                "exclude_from_parent": member.exclude_from_parent,
                "source_roots": member.source_roots,
                "test_roots": member.test_roots,
                "package_roots": member.package_roots,
                "default_zones": member.default_zones,
                "contract_files": member.contract_files,
                "dependency_files": member.dependency_files,
            }
            for member in model.members
        ],
    ]


def selector_matches(path_name: str, selector: ZoneSelector) -> bool:
    if selector.kind == "file":
        return path_name == selector.value.strip().strip("/")
    if selector.kind == "dir":
        return is_under(path_name, selector.value)
    pattern = selector.value.strip().strip("/")
    return path_matches(path_name, [pattern])


def classify(path_name: str, model: ProjectModel) -> tuple[str, str]:
    matches: list[tuple[int, int, Zone, str]] = []
    for zone in model.zones:
        excluded = any(
            selector.kind == "exclude" and selector_matches(path_name, selector)
            for selector in zone.selectors
        )
        if excluded:
            continue
        if path_name in zone.files:
            matches.append((1000, len(path_name), zone, f"zone.{zone.id}.files"))
        matches.extend(
            (100, len(directory), zone, f"zone.{zone.id}.dirs:{directory}")
            for directory in zone.dirs
            if is_under(path_name, directory)
        )
        for selector in zone.selectors:
            if selector.kind == "exclude" or not selector_matches(path_name, selector):
                continue
            base_priority = {"file": 1000, "dir": 100, "glob": 200}.get(selector.kind, 0)
            matches.append(
                (
                    base_priority + selector.priority,
                    len(selector.value),
                    zone,
                    f"zone.{zone.id}.selectors:{selector.kind}:{selector.value}",
                )
            )
    if matches:
        _, _, zone, matched_by = max(matches, key=lambda item: (item[0], item[1]))
        return zone.id, matched_by
    return "unclassified", "no matching zone"


def zone_by_import_root(model: ProjectModel) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for zone in model.zones:
        for root in zone.import_roots:
            mapping[root] = zone.id
    return mapping


def zones_by_id(model: ProjectModel) -> dict[str, Zone]:
    return {zone.id: zone for zone in model.zones}


def select_python_files(  # noqa: PLR0913  四个 trait/前缀过滤维度是彼此独立的筛选条件，合并成配置对象会改掉所有调用方签名，且提取函数不减少参数个数
    inventory: dict,
    model: ProjectModel,
    *,
    require_any_trait: tuple[str, ...] = (),
    require_all_traits: tuple[str, ...] = (),
    exclude_any_trait: tuple[str, ...] = (),
    path_prefixes: tuple[str, ...] = (),
) -> list[dict[str, object]]:
    traits_by_zone = zone_traits_map(model)
    selected: list[dict[str, object]] = []
    for file_record in inventory.get("files", []):
        path_name = str(file_record.get("path") or "")
        if not path_name.endswith(".py") or not is_under_any(path_name, path_prefixes):
            continue
        traits = traits_by_zone.get(str(file_record.get("zone") or ""), set())
        if require_any_trait and not traits.intersection(require_any_trait):
            continue
        if require_all_traits and not set(require_all_traits).issubset(traits):
            continue
        if exclude_any_trait and traits.intersection(exclude_any_trait):
            continue
        selected.append(file_record)
    return selected


def all_entrypoints(model: ProjectModel) -> list[EntryPoint]:
    items = list(model.entrypoints)
    for member in model.members:
        items.extend(member.entrypoints)
    if items:
        return items
    generated: list[EntryPoint] = []
    for zone in model.zones:
        if "entrypoint" not in zone.traits:
            continue
        generated.extend(
            EntryPoint(id=path_name.replace("/", ":"), kind="script", file=path_name) for path_name in zone.files
        )
    return generated


def entrypoint_records(model: ProjectModel) -> list[dict[str, object]]:
    return [
        {
            "id": entrypoint.id,
            "kind": entrypoint.kind,
            "member": entrypoint.member,
            "file": entrypoint.file,
            "module": entrypoint.module,
            "callable": entrypoint.callable,
            "command": entrypoint.command,
            "cwd": entrypoint.cwd,
            "owner": entrypoint.owner,
            "public_surface": entrypoint.public_surface,
            "allowed_zones": entrypoint.allowed_zones,
            "evidence": entrypoint.evidence,
        }
        for entrypoint in all_entrypoints(model)
    ]


class ModuleResolver:
    def __init__(self, model: ProjectModel, file_records: list[dict[str, object]]) -> None:
        self.model = model
        self.by_module: dict[str, dict[str, object]] = {}
        self.by_path = {str(item["path"]): item for item in file_records}
        for record in file_records:
            path_name = str(record["path"])
            for module in self.modules_for_path(path_name, str(record.get("member", "root"))):
                self.by_module.setdefault(
                    module,
                    {
                        "module": module,
                        "path": path_name,
                        "member": record.get("member"),
                        "zone": record.get("zone"),
                    },
                )

    def modules_for_path(self, path_name: str, member_id: str) -> list[str]:
        # "在哪些 root 下"由这里判(纯路径运算);"在这个 root 下叫什么模块名"交语言适配器。
        modules: list[str] = []
        for root in self.package_roots_for_member(member_id):
            clean = root.strip().strip("/")
            if clean and not is_under(path_name, clean):
                continue
            module = lang_python.module_name_for(path_name, root)
            if module:
                modules.append(module)
        return modules

    def package_roots_for_member(self, member_id: str) -> list[str]:
        roots: list[str] = []
        for member in self.model.members:
            if member.id == member_id:
                roots.extend(member.package_roots or member.source_roots)
        roots.extend(root for zone in self.model.zones for root in zone.import_roots)
        roots.append("")
        return sorted(set(roots), key=len, reverse=True)

    def resolve_absolute(self, module: str) -> dict[str, object] | None:
        hit = lang_python.longest_known_module(module, self.by_module)
        return {**self.by_module[hit], "resolved_by": "module"} if hit else None

    def resolve_relative(self, source_name: str, item: dict[str, object]) -> dict[str, object] | None:
        target_path = lang_python.relative_import_target(source_name, item, ROOT)
        record = self.by_path.get(target_path)
        if not record:
            return {"path": target_path, "member": member_for_path(target_path, self.model), "zone": classify(target_path, self.model)[0], "resolved_by": "relative-path"}
        return {
            "path": target_path,
            "member": record.get("member"),
            "zone": record.get("zone"),
            "resolved_by": "relative-path",
        }

    def dump(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "module_count": len(self.by_module),
            "modules": dict(sorted(self.by_module.items())),
        }


def is_ignored_directory(path_name: str, ignored: PathSpec) -> bool:
    return (
        ignored.match_file(path_name)
        or ignored.match_file(f"{path_name}/")
        or ignored.match_file(f"{path_name}/__probe__.py")
    )


def full_python_candidates(model: ProjectModel, ignored: PathSpec) -> list[Path]:
    suffixes = source_suffixes(model)
    paths: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        directory = Path(dirpath)
        rel_dir = "" if directory == ROOT else rel(directory)
        kept_dirs: list[str] = []
        for dirname in dirnames:
            child_name = dirname if not rel_dir else f"{rel_dir}/{dirname}"
            if is_workspace_member_path(child_name, model) or is_ignored_directory(child_name, ignored):
                continue
            kept_dirs.append(dirname)
        dirnames[:] = kept_dirs
        # 只做走目录时省事的粗筛(后缀);workspace/ignore/include_globs 三项由
        # iter_python_files 统一判——它对 changed 档也必须判,所以这里再判一遍是纯重复。
        paths.extend(directory / f for f in filenames if f.endswith(suffixes))
    return paths


def iter_python_files(model: ProjectModel, scope: str = "full") -> list[Path]:
    ignored = pathspec_from(model.ignore.patterns)
    paths: list[Path] = []
    candidates = [ROOT / name for name in changed_python_names()] if scope == "changed" else full_python_candidates(model, ignored)
    for path in candidates:
        if not path.exists() or path.suffix not in source_suffixes(model):
            continue
        name = rel(path)
        if is_workspace_member_path(name, model):
            continue
        if ignored.match_file(name):
            continue
        if not path_matches(name, source_include_globs(model)):
            continue
        paths.append(path)
    return sorted(paths)


def file_record_for_path(path: Path, model: ProjectModel, *, parse: bool) -> dict[str, object]:
    name = rel(path)
    zone, matched_by = classify(name, model)
    member = member_for_path(name, model)
    imports: list[dict[str, object]] = []
    public_symbols: list[dict[str, object]] = []
    parse_error = None
    if parse and path.suffix in lang_python.SUFFIXES:
        imports, public_symbols, parse_error = lang_python.parse_source(path, name)
    # Go 没有"逐文件取 import"这回事(go list 是整模块、包级的),它的边由 go_package_edges 补;
    # 顶层符号也暂不提取(需要 tree-sitter 或 go doc,未坐实),所以这里保持空而不是假装有。
    return {
        "path": name,
        "member": member,
        "zone": zone,
        "matched_by": matched_by,
        "parse_error": parse_error,
        "imports": imports,
        "public_symbols": public_symbols,
    }


def deleted_file_record(path_name: str, model: ProjectModel) -> dict[str, object]:
    zone, matched_by = classify(path_name, model)
    return {
        "path": path_name,
        "member": member_for_path(path_name, model),
        "zone": zone,
        "matched_by": matched_by,
        "parse_error": None,
        "imports": [],
        "public_symbols": [],
        "deleted": True,
    }


def edges_for_records(
    file_records: list[dict[str, object]],
    resolver: ModuleResolver,
    import_zones: dict[str, str],
) -> list[dict[str, object]]:
    edges: list[dict[str, object]] = []
    for file_record in file_records:
        name = str(file_record["path"])
        zone = str(file_record["zone"])
        for item in file_record.get("imports", []):
            root = str(item.get("root") or "")
            target_zone = import_zones.get(root)
            target_member = ""
            target_path = ""
            resolved_by = ""
            if item.get("kind") == "relative":
                resolved = resolver.resolve_relative(name, item)
                target_path = str(resolved.get("path", "")) if resolved else ""
                target_zone = str(resolved.get("zone", "")) if resolved else None
                target_member = str(resolved.get("member", "")) if resolved else ""
                resolved_by = str(resolved.get("resolved_by", "")) if resolved else ""
            else:
                resolved = resolver.resolve_absolute(str(item.get("module") or ""))
                if resolved:
                    target_path = str(resolved.get("path", ""))
                    target_zone = str(resolved.get("zone", "")) or target_zone
                    target_member = str(resolved.get("member", ""))
                    resolved_by = str(resolved.get("resolved_by", ""))
            edges.append(
                {
                    "kind": "import",
                    "source": name,
                    "source_member": file_record.get("member"),
                    "source_zone": zone,
                    "target_path": target_path,
                    "target_member": target_member,
                    "target_root": root,
                    "target_zone": target_zone,
                    "resolved_by": resolved_by,
                    "import_kind": item.get("kind"),
                    "module": item.get("module"),
                }
            )
    return edges


def declared_language_ids(model: ProjectModel) -> set[str]:
    return {lang.id for lang in model.languages}


def go_package_edges(model: ProjectModel, file_records: list[dict[str, object]]) -> list[dict[str, object]]:
    """Go 的包级边扇出成"源包每个文件 -> 目标包目录"。

    粒度差异是语言本身的:go list 不告诉你哪个文件满足了 import,所以 target 是包目录。
    source 仍扇出到文件,这样违规消息指得到具体位置、changed 档也能按文件过滤。
    """
    go_files = [r for r in file_records if str(r["path"]).endswith(lang_go.SUFFIXES)]
    if "go" not in declared_language_ids(model) or not go_files:
        return []
    try:
        packages = lang_go.list_packages(ROOT)
    except lang_go.GoToolchainError as exc:
        raise error_report.abort(
            "[inventory] 取 Go 导入图失败",
            str(exc),
            "预期能取到该语言的导入图;实际取不到 —— 依赖它的闸(zone 越界/未知依赖/零消费者)"
            "不敢在没有图的情况下放行,所以整体停下",
            "装好 go 工具链、并确认仓库是有效的 go module(go.mod 存在);"
            "若本项目其实没有 Go 代码,把 project_model 的 [[languages]] 里 id=\"go\" 那段删掉",
        ) from exc
    files_by_dir: dict[str, list[dict[str, object]]] = {}
    for record in go_files:
        files_by_dir.setdefault(PurePosixPath(str(record["path"])).parent.as_posix(), []).append(record)
    edges: list[dict[str, object]] = []
    for edge in lang_go.package_edges(packages, ROOT):
        source_dir, target_dir = str(edge["source_dir"]), str(edge["target_dir"])
        edges.extend(
            {
                    "kind": "import",
                    "source": record["path"],
                    "source_member": record.get("member"),
                    "source_zone": record.get("zone"),
                    "target_path": target_dir,
                    "target_member": member_for_path(target_dir, model),
                    "target_root": str(edge["import_path"]),
                    "target_zone": classify(target_dir, model)[0],
                    "resolved_by": "go-package",
                    "import_kind": "import",
                "module": str(edge["import_path"]),
            }
            for record in files_by_dir.get(source_dir, [])
        )
    return edges


def typescript_file_edges(model: ProjectModel, file_records: list[dict[str, object]]) -> list[dict[str, object]]:
    """TS/JS 的文件级导入边。粒度和 Python 一样是文件->文件,所以两端都能直接查 zone。"""
    ts_files = [r for r in file_records if str(r["path"]).endswith(lang_typescript.SUFFIXES)]
    if "typescript" not in declared_language_ids(model) or not ts_files:
        return []
    names = [str(record["path"]) for record in ts_files]
    zone_by_path = {str(r["path"]): r for r in file_records}
    try:
        report = lang_typescript.cruise(ROOT, names)
    except lang_typescript.NodeToolchainError as exc:
        raise error_report.abort(
            "[inventory] 取 TypeScript/JS 导入图失败",
            str(exc),
            "预期能取到该语言的导入图;实际取不到 —— 依赖它的闸(zone 越界/未知依赖/零消费者)"
            "不敢在没有图的情况下放行,所以整体停下",
            "装好 Node 与 npx;若报 EACCES 且提到 root-owned files,那是 npm 缓存被 root 占了,"
            "跑 `sudo chown -R $(id -u):$(id -g) ~/.npm` 修;"
            "若本项目其实没有 TS/JS 代码,把 [[languages]] 里 id=\"typescript\" 那段删掉",
        ) from exc
    edges: list[dict[str, object]] = []
    for edge in lang_typescript.file_edges(report):
        source, target = str(edge["source"]), str(edge["target"])
        source_record = zone_by_path.get(source)
        if source_record is None:
            continue
        target_record = zone_by_path.get(target)
        edges.append(
            {
                "kind": "import",
                "source": source,
                "source_member": source_record.get("member"),
                "source_zone": source_record.get("zone"),
                "target_path": target,
                "target_member": (target_record or {}).get("member") or member_for_path(target, model),
                "target_root": str(edge["module"]),
                "target_zone": (target_record or {}).get("zone") or classify(target, model)[0],
                "resolved_by": "ts-module",
                "import_kind": "dynamic-import" if edge.get("dynamic") else "import",
                "module": str(edge["module"]),
            }
        )
    return edges


def build_inventory(scope: str = "full") -> dict:
    model = load_project_model()
    registry = load_registry()
    import_zones = zone_by_import_root(model)
    zones = zones_by_id(model)
    files: list[dict[str, object]] = [
        file_record_for_path(path, model, parse=True) for path in iter_python_files(model, scope=scope)
    ]
    edges: list[dict[str, object]] = []
    resolver_files = files
    removed_paths = sorted(removed_python_names()) if scope == "changed" else []
    deleted_records = [deleted_file_record(path_name, model) for path_name in removed_paths]
    if scope == "changed":
        scoped_paths = {str(item["path"]) for item in files}
        resolver_files = [
            file_record_for_path(path, model, parse=False)
            for path in iter_python_files(model, scope="full")
            if rel(path) not in scoped_paths
        ] + files
    resolver = ModuleResolver(model, resolver_files)
    edges.extend(edges_for_records(files, resolver, import_zones))
    edges.extend(go_package_edges(model, files))
    edges.extend(typescript_file_edges(model, files))
    violations = import_policy_violations(edges, zones)
    violations.extend(feature_api_violations(edges, model))
    if scope == "changed":
        violations.extend(unknown_dependency_violations(edges, zones))
        if removed_paths:
            full_records = [file_record_for_path(path, model, parse=True) for path in iter_python_files(model, scope="full")]
            resolver_with_deleted = ModuleResolver(model, [*full_records, *deleted_records])
            full_edges = edges_for_records(full_records, resolver_with_deleted, import_zones)
            violations.extend(deleted_dependency_violations(full_edges, set(removed_paths), zones))
    violations = apply_managed_violation_baseline(violations, model)
    violations.extend(quality_coverage_violations(ROOT, MODEL_PATH, model))
    tools = [
        {
            "id": tool.get("id"),
            "configured_in": tool.get("configured_in", []),
            "stages": tool.get("stages", []),
            "changed_adapter": bool(tool.get("changed_adapter")),
            "utility": bool(tool.get("utility")),
            "has_command": bool(tool.get("entrypoint_commands") or tool.get("manual_commands") or tool.get("ci_commands")),
        }
        for tool in registry.get("tools", [])
    ]
    return {
        "schema_version": 1,
        "scope": scope,
        "input_fingerprint": report_fingerprint(ROOT, scope),
        "model": MODEL_PATH.relative_to(ROOT).as_posix(),
        "members": member_records(model),
        "entrypoints": entrypoint_records(model),
        "module_resolver": resolver.dump(),
        "files": files,
        "tools": tools,
        "edges": edges,
        "removed_python": removed_paths,
        "violations": violations,
    }


VIOLATION_FIELDS = (
    "source", "source_member", "source_zone", "target_path", "target_member", "target_root", "target_zone", "module",
)
EDGE_DEDUPE_FIELDS = ("source", "target_path", "target_root", "target_zone", "module")
PATH_DEDUPE_FIELDS = ("source", "target_path", "module")


def edge_violation(edge: dict[str, object], kind: str, message: str, **overrides: object) -> dict[str, object]:
    """One record shape for every edge-derived violation; only kind/message/overrides differ."""
    record: dict[str, object] = {"kind": kind}
    record.update({field: edge.get(field) for field in VIOLATION_FIELDS})
    record.update(overrides)
    record["message"] = message
    return record


def dedupe_key(edge: dict[str, object], fields: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(str(edge.get(field) or "") for field in fields)


def import_policy_violations(edges: list[dict[str, object]], zones: dict[str, Zone]) -> list[dict[str, object]]:
    violations: list[dict[str, object]] = []
    seen: set[tuple[str, str, str, str, str]] = set()
    for edge in edges:
        source_zone_id = str(edge.get("source_zone") or "")
        target_zone_id = edge.get("target_zone")
        if not target_zone_id:
            continue
        source_zone = zones.get(source_zone_id)
        if source_zone is None:
            continue
        if str(target_zone_id) not in zones:
            continue
        if str(target_zone_id) in source_zone.may_import_zones:
            continue
        key = dedupe_key(edge, EDGE_DEDUPE_FIELDS)
        if key in seen:
            continue
        seen.add(key)
        violations.append(
            edge_violation(
                edge,
                "import_policy_violation",
                f"{edge.get('source')}: zone `{source_zone_id}` may not import "
                f"zone `{target_zone_id}` via `{edge.get('target_root')}`",
                source_zone=source_zone_id,
                target_zone=target_zone_id,
            )
        )
    return violations


def feature_api_violations(edges: list[dict[str, object]], model: ProjectModel) -> list[dict[str, object]]:
    feature_root = model.architecture.feature_root.strip().strip("/")
    if not feature_root or model.metadata.architecture != "modular-monolith":
        return []

    def feature_for(path_name: str) -> str:
        if not is_under(path_name, feature_root):
            return ""
        parts = PurePosixPath(path_name).relative_to(feature_root).parts
        return parts[0] if len(parts) >= FEATURE_PATH_MIN_PARTS else ""

    violations: list[dict[str, object]] = []
    for edge in edges:
        # 这条判据("跨 feature 必经对方的 api 文件")是**按文件**比的,只对文件级导入图成立。
        # Go 的导入是包级的(target 是目录),而 Go 的跨边界正门是 `internal/` —— 编译器直接
        # 拒绝外部包引用它,不需要框架再判一遍。所以这里显式跳过包级边:之前它是被
        # feature_for() 的"至少两段路径"检查偶然挡掉的,偶然不生效等于静默失效。
        if edge.get("resolved_by") == "go-package":
            continue
        source = str(edge.get("source") or "")
        target = str(edge.get("target_path") or "")
        source_feature = feature_for(source)
        target_feature = feature_for(target)
        if not source_feature or not target_feature or source_feature == target_feature:
            continue
        expected_api = f"{feature_root}/{target_feature}/{model.architecture.cross_feature_entrypoint}"
        if target == expected_api:
            continue
        violations.append(
            edge_violation(
                edge,
                "import_policy_violation",
                f"{source}: cross-feature import of `{target}` must use `{expected_api}`",
                source=source,
                target_path=target,
            )
        )
    return violations


def managed_violation_key(violation: dict[str, object]) -> dict[str, str]:
    return {
        "kind": str(violation.get("kind") or ""),
        "source": str(violation.get("source") or ""),
        "target_path": str(violation.get("target_path") or ""),
        "target_root": str(violation.get("target_root") or ""),
        "module": str(violation.get("module") or ""),
    }


def apply_managed_violation_baseline(violations: list[dict[str, object]], model: ProjectModel) -> list[dict[str, object]]:
    if model.metadata.governance_mode != "managed":
        return violations
    baseline_name = managed_baseline_path(model.governance.inventory_violation_baseline)
    try:
        data = json.loads((ROOT / baseline_name).read_text(encoding="utf-8"))
        allowed = data["allowed"]
        if not isinstance(allowed, list):
            raise ValueError("allowed must be a list")  # noqa: TRY004, TRY301  这个 raise 就是为了被下面同一个 except 收成 SystemExit：换 TypeError 会漏出 except 元组、抽成内层函数会丢掉这层转换
    except (OSError, ValueError, json.JSONDecodeError, KeyError) as exc:
        raise SystemExit(f"[inventory] invalid managed violation baseline: {exc}") from exc
    current_keys = {json.dumps(item, ensure_ascii=False, sort_keys=True) for item in allowed if isinstance(item, dict)}
    committed = subprocess.run(
        ["git", "show", f"HEAD:{baseline_name}"], cwd=ROOT, text=True, capture_output=True, check=False
    )
    if committed.returncode == 0:
        try:
            prior_data = json.loads(committed.stdout)
            prior_allowed = prior_data["allowed"]
            if not isinstance(prior_allowed, list):
                raise ValueError("allowed must be a list")  # noqa: TRY004, TRY301  同上：靠本地 raise 复用同一个 except 拼出 committed baseline 的 SystemExit 文案
            prior_keys = {json.dumps(item, ensure_ascii=False, sort_keys=True) for item in prior_allowed if isinstance(item, dict)}
        except (ValueError, json.JSONDecodeError, KeyError) as exc:
            raise SystemExit(f"[inventory] invalid committed managed violation baseline: {exc}") from exc
    else:
        prior_keys = set()
    baseline_policy.require_expansion_approval(
        ROOT / baseline_name,
        expansion=bool(current_keys - prior_keys),
        action="inventory violation baseline change",
        model=model,
        root=ROOT,
    )
    return [
        violation
        for violation in violations
        if json.dumps(managed_violation_key(violation), ensure_ascii=False, sort_keys=True) not in current_keys
    ]


def unknown_dependency_violations(edges: list[dict[str, object]], zones: dict[str, Zone]) -> list[dict[str, object]]:
    violations: list[dict[str, object]] = []
    seen: set[tuple[str, str, str]] = set()
    for edge in edges:
        source_zone_id = str(edge.get("source_zone") or "")
        if source_zone_id not in zones:
            continue
        if str(edge.get("target_zone") or "") != "unclassified":
            continue
        target_path = str(edge.get("target_path") or "")
        if not target_path:
            continue
        key = dedupe_key(edge, PATH_DEDUPE_FIELDS)
        if key in seen:
            continue
        seen.add(key)
        violations.append(
            edge_violation(
                edge,
                "unknown_dependency_violation",
                f"{edge.get('source')}: changed modeled code imports unmodeled "
                f"Python `{target_path}` via `{edge.get('module')}`",
                source_zone=source_zone_id,
                target_path=target_path,
            )
        )
    return violations


def deleted_dependency_violations(
    edges: list[dict[str, object]], deleted_paths: set[str], zones: dict[str, Zone]
) -> list[dict[str, object]]:
    violations: list[dict[str, object]] = []
    seen: set[tuple[str, str, str]] = set()
    for edge in edges:
        source_zone_id = str(edge.get("source_zone") or "")
        if source_zone_id not in zones:
            continue
        target_path = str(edge.get("target_path") or "")
        if target_path not in deleted_paths:
            continue
        key = dedupe_key(edge, PATH_DEDUPE_FIELDS)
        if key in seen:
            continue
        seen.add(key)
        violations.append(
            edge_violation(
                edge,
                "deleted_dependency_violation",
                f"{edge.get('source')}: imports deleted Python module "
                f"`{target_path}` via `{edge.get('module')}`",
                source_zone=source_zone_id,
                target_path=target_path,
            )
        )
    return violations


def check_closure(inventory: dict) -> list[str]:
    issues: list[str] = []
    for file_record in inventory["files"]:
        if file_record["zone"] == "unclassified":
            issues.append(f"{file_record['path']}: Python file has no zone")
        if file_record.get("parse_error"):
            issues.append(f"{file_record['path']}: Python parse failed: {file_record['parse_error']}")
    issues.extend(str(violation["message"]) for violation in inventory.get("violations", []))
    return issues


def check_model_health(inventory: dict) -> list[str]:
    model = load_project_model()
    issues: list[str] = []
    zone_counts: dict[str, int] = {}
    for file_record in inventory["files"]:
        zone_counts[str(file_record["zone"])] = zone_counts.get(str(file_record["zone"]), 0) + 1
    watched_counts: list[str] = []
    for zone in model.zones:
        has_entries = bool(zone.dirs or zone.files or zone.import_roots)
        if not has_entries:
            continue
        if zone.traits:
            watched_counts.append(
                f"{zone.id}={zone_counts.get(zone.id, 0)} traits={','.join(sorted(zone.traits))}"
            )
        if zone.requires_reason and not zone.reason.strip():
            issues.append(f"zone.{zone.id}: requires_reason zone needs reason")
        if not zone.revisit_required:
            continue
        revisit = zone.revisit_when.strip()
        if not revisit:
            issues.append(f"zone.{zone.id}: revisit_required zone needs revisit_when")
        elif baseline_policy.vague_hits(revisit):
            issues.append(f"zone.{zone.id}: revisit_when is vague: {revisit}")
    if watched_counts:
        print(f"[inventory] model-health: zone counts: {'; '.join(watched_counts)}")
    return issues


def write_inventory(inventory: dict, path: Path = INVENTORY_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(inventory, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["build", "check", "health", "print"], nargs="?", default="check")
    parser.add_argument("--scope", choices=["full", "changed"], default="full")
    args = parser.parse_args(argv)

    inventory = build_inventory(scope=args.scope)
    if args.command in {"build", "check", "health"}:
        write_inventory(inventory)
        print(
            f"[inventory] wrote {INVENTORY_PATH.relative_to(ROOT)} "
            f"({len(inventory['files'])} Python files, scope={args.scope})"
        )
    if args.command == "print":
        print(json.dumps(inventory, ensure_ascii=False, indent=2))
    if args.command not in {"check", "health"}:
        return 0
    issues = check_closure(inventory)
    if args.command == "health":
        issues.extend(check_model_health(inventory))
    if not issues:
        print("[inventory] closure ok" if args.command == "check" else "[inventory] model health ok")
        return 0
    print(f"[inventory] {args.command} failed:", file=sys.stderr)
    for issue in issues:
        print(f"  - {issue}", file=sys.stderr)
    return 1

if __name__ == "__main__":
    raise SystemExit(main())
