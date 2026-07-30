#!/usr/bin/env python3
# 职责：比较 HEAD 与当前项目模型对实际 Python 文件的质量覆盖，阻止借改模型降标。
# 不做什么：不判断分区语义，不为旧项目自动生成豁免。
# 允许依赖层：标准库、pathspec、project_model。
# 谁不应该 import：正式业务代码、测试夹具、应用入口不应 import 本工具。
"""Detect project-model changes that remove existing Python from quality-fixed zones."""

from __future__ import annotations

import subprocess
import tomllib
from pathlib import Path, PurePosixPath

from pathspec import GitIgnoreSpec
from project_model import ProjectModel, excluded_member_roots, path_matches, source_include_globs, source_suffixes

# `git diff --name-status -M` 的重命名行恰好两列:旧路径 + 新路径。
RENAME_FIELD_COUNT = 2
# 永远不可能是本项目源码的目录:剪掉它们只为别空跑几千个文件,与模型的 ignore 是两回事。
PRUNED_DIRS = {".venv", "node_modules", "__pycache__", ".git", ".mypy_cache", ".pytest_cache", ".ruff_cache"}


def is_under(path_name: str, directory: str) -> bool:
    clean = directory.strip().strip("/")
    return bool(clean) and (path_name == clean or path_name.startswith(f"{clean}/"))


def source_names(root: Path, model: ProjectModel) -> set[str]:
    """磁盘上属于本项目声明语言的源码文件。

    写死 *.py 的后果实测过:纯 TS 项目里它扫出 3357 个 .py(连 .venv 都走),而进入候选的是 0 个,
    quality_fixed 区守住的也是 0 个 —— 这道"防止改模型降标"的闸在非 Python 项目里等于不存在,
    而且全程绿灯。

    刻意**不**用模型的 ignore 过滤:这道闸查的就是"有没有靠新加 ignore 把既有代码移出扫描",
    拿被测对象当过滤器等于自证清白。只剪掉框架级永不可能是源码的目录(.venv/node_modules/…)。
    """
    suffixes = set(source_suffixes(model))
    names: set[str] = set()
    for path in root.rglob("*"):
        if path.suffix not in suffixes or not path.is_file() or set(path.parts) & PRUNED_DIRS:
            continue
        names.add(path.relative_to(root).as_posix())
    return names


def candidate_names(names: set[str], model: ProjectModel) -> set[str]:
    ignored = GitIgnoreSpec.from_lines(model.ignore.patterns)
    member_roots = excluded_member_roots(model)
    candidates: set[str] = set()
    for name in names:
        if ignored.match_file(name) or any(is_under(name, member_root) for member_root in member_roots):
            continue
        if path_matches(name, source_include_globs(model)):
            candidates.add(name)
    return candidates


def head_source_names(root: Path, model: ProjectModel) -> set[str]:
    proc = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", "HEAD"], cwd=root, text=True, capture_output=True, check=False
    )
    if proc.returncode != 0:
        return set()
    return _with_declared_suffix(proc.stdout.splitlines(), model)


def renamed_source_destinations(root: Path, model: ProjectModel) -> dict[str, str]:
    proc = subprocess.run(
        ["git", "diff", "--name-status", "-M", "HEAD"], cwd=root, text=True, capture_output=True, check=False
    )
    if proc.returncode != 0:
        return {}
    renamed: dict[str, str] = {}
    for line in proc.stdout.splitlines():
        status, *names = line.split("\t")
        if status.startswith("R") and len(names) == RENAME_FIELD_COUNT and _has_declared_suffix(names[0], model):
            renamed[names[0]] = names[1]
    return renamed


def changed_source_names(root: Path, model: ProjectModel) -> set[str]:
    proc = subprocess.run(["git", "diff", "--name-only", "HEAD"], cwd=root, text=True, capture_output=True, check=False)
    changed = _with_declared_suffix(proc.stdout.splitlines() if proc.returncode == 0 else [], model)
    untracked = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard"], cwd=root, text=True, capture_output=True, check=False
    )
    if untracked.returncode == 0:
        changed |= _with_declared_suffix(untracked.stdout.splitlines(), model)
    return changed


def _has_declared_suffix(name: str, model: ProjectModel) -> bool:
    return PurePosixPath(name).suffix in set(source_suffixes(model))


def _with_declared_suffix(lines: list[str], model: ProjectModel) -> set[str]:
    return {line.strip() for line in lines if line.strip() and _has_declared_suffix(line.strip(), model)}


def model_changed(root: Path, model_path: Path) -> bool:
    name = model_path.relative_to(root).as_posix()
    proc = subprocess.run(["git", "diff", "--quiet", "HEAD", "--", name], cwd=root, check=False)
    return proc.returncode == 1


def zone_traits(path_name: str, model: ProjectModel) -> set[str]:
    matches: list[tuple[int, int, set[str]]] = []
    for zone in model.zones:
        matched = path_name in zone.files
        specificity = len(path_name) if matched else -1
        for directory in zone.dirs:
            if is_under(path_name, directory):
                matched, specificity = True, max(specificity, len(directory.strip("/")))
        if matched:
            matches.append((specificity, 0, set(zone.traits)))
    return max(matches, default=(-1, -1, set()))[2]


def prior_model(root: Path, model_path: Path) -> ProjectModel | None:
    name = model_path.relative_to(root).as_posix()
    proc = subprocess.run(["git", "show", f"HEAD:{name}"], cwd=root, text=True, capture_output=True, check=False)
    if proc.returncode != 0:
        return None
    return ProjectModel.model_validate(tomllib.loads(proc.stdout))


def quality_coverage_violations(root: Path, model_path: Path, current: ProjectModel) -> list[dict[str, object]]:
    prior = prior_model(root, model_path)
    if prior is None:
        return []
    violations: list[dict[str, object]] = []
    present = source_names(root, current)
    prior_candidates = candidate_names(head_source_names(root, prior), prior)
    current_candidates = candidate_names(present, current)
    renamed = renamed_source_destinations(root, current)
    unscanned_changed_python = (changed_source_names(root, current) & present) - current_candidates
    changed_model = model_changed(root, model_path)
    for prior_name in sorted(prior_candidates):
        if "quality_fixed" not in zone_traits(prior_name, prior):
            continue
        path_name = renamed.get(prior_name, prior_name)
        # A deletion is not a quality-standard reduction. When the model also changed,
        # a low-similarity move into an unscanned path is ambiguous and must be reviewed.
        if path_name not in present:
            if changed_model and unscanned_changed_python:
                violations.append(
                    {
                        "kind": "quality_coverage_regression",
                        "source": prior_name,
                        "message": (
                            f"{prior_name}: removed quality-fixed Python while adding unscanned Python; "
                            "make the destination quality_fixed or split a real deletion from the model change"
                        ),
                    }
                )
            continue
        if path_name not in current_candidates:
            violations.append(
                {
                    "kind": "quality_coverage_regression",
                    "source": prior_name,
                    "message": f"{prior_name}: project_model removed existing Python from the quality scan",
                }
            )
            continue
        if "quality_fixed" in zone_traits(path_name, current):
            continue
        violations.append(
            {
                "kind": "quality_coverage_regression",
                "source": prior_name,
                "message": f"{prior_name}: project_model removed existing Python from a quality_fixed zone",
            }
        )
    return violations
