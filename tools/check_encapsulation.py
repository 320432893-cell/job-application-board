#!/usr/bin/env python3
# 职责：检查跨模块 import 是否偷用私有名或内部实现；相对 import 交 Ruff TID252。
# 不做什么：不判断业务边界、不猜深 import/门面/__all__/顶层副作用，不自动改名或搬文件。
# 允许依赖层：标准库(ast/pathlib)、被扫描源码、tooling_layout。
# 谁不应该 import：正式业务代码、测试夹具、应用入口不应 import 本检查脚本。
"""Block imports of private symbols and internal implementation modules."""

from __future__ import annotations

import ast
import pathlib
import sys
from dataclasses import dataclass

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from tooling_layout import fixed_quality_dirs, is_relative_path_ignored

ROOT = pathlib.Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Finding:
    path: pathlib.Path
    line: int
    message: str


def rel(path: pathlib.Path) -> str:
    return path.relative_to(ROOT).as_posix()


def is_private_name(name: str) -> bool:
    return name.startswith("_") and not name.startswith("__")


def is_internal_module(module: str | None) -> bool:
    return bool(
        module
        and any(
            part in {"internal", "impl"} or part.endswith(("_impl", "_internal")) or is_private_name(part)
            for part in module.split(".")
        )
    )


def python_files() -> list[pathlib.Path]:
    paths: list[pathlib.Path] = []
    for directory in fixed_quality_dirs():
        root = ROOT / directory
        if root.exists():
            paths.extend(path for path in sorted(root.rglob("*.py")) if not is_relative_path_ignored(rel(path)))
    return paths


def run() -> list[Finding]:
    findings: list[Finding] = []
    for path in python_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel(path))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if is_internal_module(node.module):
                    findings.append(Finding(path, node.lineno, f"禁止 import 内部实现模块 `{node.module}`"))
                findings.extend(
                    Finding(path, node.lineno, f"禁止跨模块 import 私有名 `{alias.name}`")
                    for alias in node.names
                    if is_private_name(alias.name)
                )
            elif isinstance(node, ast.Import):
                findings.extend(
                    Finding(path, node.lineno, f"禁止 import 内部实现模块 `{alias.name}`")
                    for alias in node.names
                    if is_internal_module(alias.name)
                )
    return findings


def main() -> int:
    findings = run()
    for finding in findings:
        sys.stderr.write(f"[encapsulation] {rel(finding.path)}:{finding.line}: {finding.message}\n")
    if findings:
        return 1
    sys.stdout.write("[encapsulation] 未发现私有/内部 import 越界\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
