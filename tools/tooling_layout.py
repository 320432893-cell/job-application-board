#!/usr/bin/env python3
# 职责：从 project_model 派生项目代码布局并展开 registry 命令占位符，供各检查脚本复用同一套扫描边界。
# 不做什么：不决定阶段编排、不运行检查、不修改 project_model/registry。
# 允许依赖层：标准库、.ai-config/project_model.toml、repo_files(git 文件清单)。
# 谁不应该 import：正式业务代码、测试夹具、应用入口不应 import 本工具层模块。
"""Shared code-layout helpers for repository tooling."""

from __future__ import annotations

import pathlib
from collections.abc import Iterable, Sequence
from functools import lru_cache

import tooling_registry
from project_model import load_project_model_dict
from repo_files import scannable_files

ROOT = pathlib.Path(__file__).resolve().parents[1]
PROJECT_MODEL = ROOT / ".ai-config" / "project_model.toml"

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


def rel(path: pathlib.Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _dedupe(items: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        value = str(item).strip().strip("/")
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return tuple(result)


@lru_cache(maxsize=1)
def load_project_model() -> dict:
    if not PROJECT_MODEL.exists():
        raise RuntimeError(".ai-config/project_model.toml missing; project_model is the layout source")
    return load_project_model_dict(PROJECT_MODEL)


def zone_has_any_trait(zone: dict, traits: Sequence[str]) -> bool:
    zone_traits = {str(trait) for trait in zone.get("traits", [])}
    return bool(zone_traits & {str(trait) for trait in traits})


def zone_dirs_for_traits(model: dict, traits: Sequence[str]) -> tuple[str, ...]:
    return _dedupe(
        directory
        for zone in model.get("zones", [])
        if isinstance(zone, dict) and zone_has_any_trait(zone, traits)
        for directory in zone.get("dirs", [])
    )


def zone_files_for_traits(model: dict, traits: Sequence[str]) -> tuple[str, ...]:
    return _dedupe(
        file_name
        for zone in model.get("zones", [])
        if isinstance(zone, dict) and zone_has_any_trait(zone, traits)
        for file_name in zone.get("files", [])
    )


def zone_import_roots_for_traits(model: dict, traits: Sequence[str]) -> tuple[str, ...]:
    return _dedupe(
        root
        for zone in model.get("zones", [])
        if isinstance(zone, dict) and zone_has_any_trait(zone, traits)
        for root in zone.get("import_roots", [])
    )


def _entrypoint_file_names(entrypoints: Iterable[object]) -> list[str]:
    return [
        str(entrypoint["file"]) for entrypoint in entrypoints if isinstance(entrypoint, dict) and entrypoint.get("file")
    ]


def model_entrypoint_files(model: dict) -> tuple[str, ...]:
    files: list[str] = _entrypoint_file_names(model.get("entrypoints", []))
    for member in model.get("members", []):
        if not isinstance(member, dict):
            continue
        files.extend(_entrypoint_file_names(member.get("entrypoints", [])))
    return _dedupe(files)


def ignore_dirs_from_patterns(patterns: Sequence[str]) -> tuple[str, ...]:
    values: list[str] = []
    for pattern in patterns:
        clean = str(pattern).strip().strip("/")
        if not clean:
            continue
        prefix: list[str] = []
        for segment in clean.split("/"):
            if not segment or any(token in segment for token in "*?["):
                break
            prefix.append(segment)
        static_segments: list[str] = [
            segment for segment in clean.split("/") if segment and not any(token in segment for token in "*?[")
        ]
        if prefix:
            values.append("/".join(prefix))
        elif static_segments:
            values.append(static_segments[0])
    return _dedupe(values)


def project_model_code_layout() -> dict:  # 不会返回 None:缺字段就 raise,标 | None 是旧签名没跟上
    model = load_project_model()
    tooling = model.get("tooling")
    if not isinstance(tooling, dict):
        # TRY004 豁免理由：这是 project_model.toml 配置不合契约，不是调用方传错参数类型；
        # 本模块所有 project_model 校验统一 RuntimeError，改 TypeError 会误导成编程错误并打散错误族。
        raise RuntimeError("project_model must define [tooling]")  # noqa: TRY004
    ignore = model.get("ignore", {})
    patterns = ignore.get("patterns", []) if isinstance(ignore, dict) else []
    return {
        "fixed_quality_dirs": list(zone_dirs_for_traits(model, tooling.get("fixed_quality_traits", []))),
        "formal_dirs": list(zone_dirs_for_traits(model, tooling.get("formal_traits", []))),
        "support_dirs": list(zone_dirs_for_traits(model, tooling.get("support_traits", []))),
        "test_dirs": list(zone_dirs_for_traits(model, tooling.get("test_traits", []))),
        "ignored_dirs": list(ignore_dirs_from_patterns(patterns)),
        "informal_zone_dirs": list(zone_dirs_for_traits(model, tooling.get("informal_traits", []))),
        "inactive_dirs": list(zone_dirs_for_traits(model, tooling.get("inactive_traits", []))),
        "entrypoint_files": list(
            model_entrypoint_files(model) or zone_files_for_traits(model, tooling.get("entrypoint_traits", []))
        ),
        "package_roots": list(zone_import_roots_for_traits(model, tooling.get("package_root_traits", []))),
        "devtools_dir": str(tooling.get("devtools_dir", "")).strip().strip("/"),
    }


def architecture_settings() -> tuple[str, str]:
    architecture = load_project_model().get("architecture", {})
    if not isinstance(architecture, dict):
        # TRY004 豁免理由：同上，配置契约错误而非调用方类型错误，保持 RuntimeError 错误族一致。
        raise RuntimeError("project_model must define [architecture]")  # noqa: TRY004
    feature_root = str(architecture.get("feature_root", "")).strip().strip("/")
    cross_feature_entrypoint = str(architecture.get("cross_feature_entrypoint", "")).strip()
    if not feature_root or not cross_feature_entrypoint:
        raise RuntimeError("project_model architecture.feature_root and cross_feature_entrypoint must be non-empty")
    return feature_root, cross_feature_entrypoint


@lru_cache(maxsize=1)
def code_layout() -> dict:
    layout = project_model_code_layout()
    missing = [key for key in (*LAYOUT_LIST_FIELDS, *LAYOUT_STRING_FIELDS) if key not in layout]
    if missing:
        raise RuntimeError(f"project_model-derived layout missing fields: {', '.join(missing)}")
    return layout


def layout_list(key: str) -> tuple[str, ...]:
    values = code_layout().get(key)
    if not isinstance(values, list):
        # TRY004 豁免理由：同上，配置派生结果不合契约而非调用方类型错误；
        # 邻近的 layout_str 也是 RuntimeError，两者必须同族才好在上层统一处理。
        raise RuntimeError(f"project_model-derived layout.{key} must be a list")  # noqa: TRY004
    return _dedupe(values)


def layout_str(key: str) -> str:
    value = code_layout().get(key)
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"project_model-derived layout.{key} must be a non-empty string")
    return value.strip().strip("/")


def fixed_quality_dirs() -> tuple[str, ...]:
    return layout_list("fixed_quality_dirs")


def formal_dirs() -> tuple[str, ...]:
    return layout_list("formal_dirs")


def support_dirs() -> tuple[str, ...]:
    return layout_list("support_dirs")


def test_dirs() -> tuple[str, ...]:
    return layout_list("test_dirs")


def ignored_dirs() -> tuple[str, ...]:
    return layout_list("ignored_dirs")


def is_changed_ruff_path(path: pathlib.Path) -> bool:
    """这个改动过的文件该不该过 ruff。

    从 check.py 搬过来:它是纯布局判据(rel / fixed_quality_dirs / support_dirs 都住这儿),
    留在统一入口里只是让那份文件继续变胖——超行数棘轮的 split_when 要的就是这类外迁。

    第一行的语言闸是补的:changed 档直接起 argv,绕开了 run_item 的语言过滤。漏了它,
    纯 TS 仓会拿 ruff 的默认规则去挑闸自带的那批 tools/*.py(那儿连 .ruff.toml 都没装)。
    """
    if not path.is_relative_to(ROOT):
        return False  # 仓库外的文件不归本仓的 ruff 管;rel() 对它会直接抛 ValueError
    path_str = rel(path)
    if path_str.startswith(".") or "python" not in tooling_registry.declared_language_ids(load_project_model_dict()):
        return False
    if "/" not in path_str:
        return path.suffix == ".py"
    return any(
        path_str == directory or path_str.startswith(f"{directory}/")
        for directory in set(fixed_quality_dirs()) | set(support_dirs())
    )


def informal_zone_dirs() -> tuple[str, ...]:
    return layout_list("informal_zone_dirs")


def inactive_dirs() -> tuple[str, ...]:
    return layout_list("inactive_dirs")


def entrypoint_files() -> tuple[str, ...]:
    return layout_list("entrypoint_files")


def devtools_dir() -> str:
    return layout_str("devtools_dir")


def package_roots() -> tuple[str, ...]:
    return layout_list("package_roots")


def all_code_dirs() -> tuple[str, ...]:
    return _dedupe((*fixed_quality_dirs(), *support_dirs()))


def fixed_quality_paths() -> tuple[str, ...]:
    return _dedupe((*fixed_quality_dirs(), *entrypoint_files()))


def all_code_paths() -> tuple[str, ...]:
    return _dedupe((*all_code_dirs(), *entrypoint_files()))


def existing_paths(paths: Sequence[str]) -> list[str]:
    return [name for name in paths if (ROOT / name).exists()]


def workspace_member_roots() -> tuple[str, ...]:
    model = load_project_model()
    workspace = model.get("workspace", {})
    if not isinstance(workspace, dict) or not workspace.get("exclude_member_roots", True):
        return ()
    roots = workspace.get("member_roots", [])
    return _dedupe(roots if isinstance(roots, list) else [])


def is_relative_path_ignored(path_str: str) -> bool:
    if any(path_str == root or path_str.startswith(f"{root}/") for root in workspace_member_roots()):
        return True
    parts = path_str.split("/")
    for ignored in ignored_dirs():
        if "/" in ignored:
            if path_str == ignored or path_str.startswith(f"{ignored}/"):
                return True
            continue
        if ignored in parts:
            return True
    return any(part == "__pycache__" for part in parts)


def is_ignored_path(path: pathlib.Path) -> bool:
    return is_relative_path_ignored(rel(path))


def first_party_modules() -> tuple[str, ...]:
    """支撑区里那批走 sys.path 导入的顶层模块名。

    deptry 只把打包声明里的源码目录当第一方,于是 tools/ 与 .ai-config/tools/ 里的模块被报成
    "imported but missing from the dependency definitions" —— 实测 78 条里 67 条都是这个假阳。
    名单从磁盘派生,不写进 pyproject:枚举的那份每加一个检查器就会漏一次,而漏了没人会发现。
    """
    names: set[str] = set()
    for directory in support_dirs():
        base = ROOT / directory
        if not base.is_dir():
            continue
        names.update(path.stem for path in base.glob("*.py") if path.stem != "__init__")
    return tuple(sorted(names))


def known_first_party_flags() -> tuple[str, ...]:
    return tuple(flag for name in first_party_modules() for flag in ("--known-first-party", name))


PLACEHOLDER_VALUES = {
    "{fixed_quality_dirs}": fixed_quality_dirs,
    "{fixed_quality_paths}": fixed_quality_paths,
    "{formal_dirs}": formal_dirs,
    "{support_dirs}": support_dirs,
    "{test_dirs}": test_dirs,
    "{entrypoint_files}": entrypoint_files,
    "{all_code_dirs}": all_code_dirs,
    "{all_code_paths}": all_code_paths,
    # per-file 扫描器(detect-secrets-hook 等)不递归目录，必须拿到显式文件清单
    "{scannable_files}": scannable_files,
}


# 展开成 CLI 参数(不是路径)的占位符:不能过 existing_paths —— 那一层是给路径清单去掉不存在项用的,
# 拿它筛 `--known-first-party` 这种旗标会把整串吃掉。
PLACEHOLDER_FLAGS = {
    "{known_first_party_flags}": known_first_party_flags,
}


def expand_args(args: Sequence[str]) -> list[str]:
    expanded: list[str] = []
    for arg in args:
        if flags := PLACEHOLDER_FLAGS.get(arg):
            expanded.extend(flags())
            continue
        getter = PLACEHOLDER_VALUES.get(arg)
        if getter is None:
            expanded.append(arg)
            continue
        expanded.extend(existing_paths(getter()))
    return expanded
