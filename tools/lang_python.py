#!/usr/bin/env python3
# 职责：Python 语言适配器——用 ast 从 .py 源码里取出 import 关系与顶层公开符号。
# 不做什么：不判断 zone 归属、不建跨文件的图、不做任何策略判定(那些语言无关,住 inventory)。
# 允许依赖层：标准库(ast/pathlib)。
# 谁不应该 import：正式业务代码、测试夹具、应用入口不应 import 本工具层模块。
"""Python source adapter: `import` 关系与顶层公开符号的提取。

框架把"每门语言怎么读自己的源码"隔在适配器里:Go 靠 `go list -json` 一条命令拿包级
导入图,TS 靠 dependency-cruiser,Python 没有原生工具所以这里手写 ast 访问器。
zone 归属、有向许可、跨边界正门这些判据是语言无关的,留在 inventory 里,不进适配器。
"""

from __future__ import annotations

import ast
from pathlib import Path, PurePosixPath

LANGUAGE_ID = "python"
SUFFIXES = (".py",)


class ImportCollector(ast.NodeVisitor):
    def __init__(self) -> None:
        self.imports: list[dict[str, object]] = []
        self.public_symbols: list[dict[str, object]] = []

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            name = alias.name
            self.imports.append({"module": name, "root": name.split(".", maxsplit=1)[0], "kind": "import"})

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.level:
            self.imports.append(
                {
                    "module": node.module or "",
                    "root": "",
                    "kind": "relative",
                    "level": node.level,
                    "names": [alias.name for alias in node.names],
                }
            )
            return
        if node.module is None:
            return
        module = node.module
        self.imports.append({"module": module, "root": module.split(".", maxsplit=1)[0], "kind": "from"})

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        if not node.name.startswith("_"):
            self.public_symbols.append({"kind": "function", "name": node.name})

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        if not node.name.startswith("_"):
            self.public_symbols.append({"kind": "function", "name": node.name})

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        if not node.name.startswith("_"):
            self.public_symbols.append({"kind": "class", "name": node.name})


def parse_source(path: Path, display_name: str) -> tuple[list[dict[str, object]], list[dict[str, object]], str | None]:
    """读一个 .py:返回 (imports, public_symbols, parse_error)。display_name 只用于报错文案。"""
    try:
        module = ast.parse(path.read_text(encoding="utf-8"), filename=display_name)
    except (OSError, SyntaxError, UnicodeDecodeError) as exc:
        return [], [], str(exc)
    collector = ImportCollector()
    collector.visit(module)
    return collector.imports, collector.public_symbols, None


def relative_import_target(source_name: str, item: dict[str, object], root: Path) -> str:
    """相对 import 落到仓库内的路径。root 由调用方注入:适配器不该自己知道仓库根在哪。"""
    level = int(item.get("level") or 0)
    module = str(item.get("module") or "")
    source_parent = PurePosixPath(source_name).parent
    base = source_parent
    for _ in range(max(level - 1, 0)):
        base = base.parent
    module_parts = [part for part in module.split(".") if part]
    names = [str(name) for name in item.get("names", []) if str(name) and str(name) != "*"]
    targets = [base.joinpath(*module_parts)]
    if not module_parts:
        targets.extend(base / name for name in names)
    candidates: list[str] = []
    for target in targets:
        candidates.extend((f"{target.as_posix()}.py", f"{target.as_posix()}/__init__.py"))
    for candidate in candidates:
        if (root / candidate).exists():
            return candidate
    return targets[0].as_posix()


def module_name_for(path_name: str, root: str) -> str | None:
    """path 相对某个 package root 的 Python 模块名;算不出来返回 None。

    只做 Python 的模块名语义(`__init__.py` 代表包本身、点号分隔层级)。
    "path 是否真在这个 root 下"是纯路径运算、语言无关,由调用方判。
    """
    clean = root.strip().strip("/")
    rel_name = path_name[len(clean) + 1 :] if clean else path_name
    if not rel_name.endswith(".py"):
        return None
    if rel_name == "__init__.py":
        return clean.replace("/", ".") or None
    if rel_name.endswith("/__init__.py"):
        return rel_name[: -len("/__init__.py")].replace("/", ".") or None
    return rel_name[:-3].replace("/", ".") or None


def longest_known_module(module: str, known: object) -> str | None:
    """Python 的点号层级语义:a.b.c 找不到就退 a.b、再退 a。known 是任何支持 `in` 的容器。"""
    parts = [part for part in module.split(".") if part]
    for end in range(len(parts), 0, -1):
        candidate = ".".join(parts[:end])
        if candidate in known:
            return candidate
    return None
