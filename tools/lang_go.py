#!/usr/bin/env python3
# 职责：Go 语言适配器——用 `go list -json` 取出包级导入图与每包的文件清单。
# 不做什么：不判断 zone 归属、不做任何策略判定(语言无关的判据住 inventory)、不提取符号级信息。
# 允许依赖层：标准库、go 工具链(经子进程)。
# 谁不应该 import：正式业务代码、测试夹具、应用入口不应 import 本工具层模块。
"""Go source adapter: 包级导入图与文件归属，取自 `go list -json ./...`。

**粒度**:Go 的导入是**包级(目录级)**的——`import "a/b/pkg"` 指向整个目录,`go list`
不告诉你是哪个文件满足了这次 import。所以本适配器产出的边,target 是**包目录**(仓库
相对路径),不是文件。这跟 Python 适配器的文件级粒度不同,是语言本身的差异,不是简化:
zone 归属本来就是按目录判的,包目录足够;而"哪个文件"这个信息 Go 根本不提供。

由此产生的一个已知影响:"import 了已删模块"这条判据在 Python 侧是拿 target 文件跟
已删文件清单比,Go 侧只能判"整个包消失了"。差异登记在此,不假装等价。

**为什么用 `go list` 而不是自己解析**:它是官方工具链的一部分,一条命令给出完整的
包依赖图 + 每包文件清单 + 模块根,比手写解析器准且不用维护。Python 侧之所以手写
ast 访问器,是因为 Python 没有对等的原生工具。
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

LANGUAGE_ID = "go"
SUFFIXES = (".go",)


class GoToolchainError(RuntimeError):
    """go 工具链不可用或 go list 失败。刻意 raise 而不是返回空:空图会让所有闸静默通过。"""


def _decode_stream(raw: str) -> list[dict]:
    """`go list -json` 输出的是**连续拼接**的 JSON 对象流,不是 JSON 数组。"""
    decoder, index, out = json.JSONDecoder(), 0, []
    while index < len(raw):
        while index < len(raw) and raw[index] in " \r\n\t":
            index += 1
        if index >= len(raw):
            break
        obj, index = decoder.raw_decode(raw, index)
        out.append(obj)
    return out


def list_packages(root: Path, pattern: str = "./...", go_binary: str = "go") -> list[dict]:
    """跑 `go list -json <pattern>`;工具链缺失或失败一律抛错(fail-closed)。"""
    try:
        proc = subprocess.run(
            [go_binary, "list", "-json", pattern], cwd=root, capture_output=True, text=True, check=False
        )
    except OSError as exc:
        raise GoToolchainError(f"找不到 go 可执行文件({go_binary}):{exc}") from exc
    if proc.returncode != 0:
        detail = proc.stderr.strip() or f"exit {proc.returncode}"
        raise GoToolchainError(f"go list -json {pattern} 在 {root} 失败:{detail}")
    return _decode_stream(proc.stdout)


def module_root(packages: list[dict]) -> tuple[str, Path] | None:
    """从任一包记录里取模块声明:(module path, module 所在目录)。"""
    for package in packages:
        module = package.get("Module") or {}
        if module.get("Path") and module.get("Dir"):
            return str(module["Path"]), Path(str(module["Dir"]))
    return None


def _relative(path: Path, root: Path) -> str | None:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return None


def package_records(packages: list[dict], root: Path) -> list[dict[str, object]]:
    """每个包一条:仓库相对的包目录 + 它的 .go 文件 + import 路径。"""
    records: list[dict[str, object]] = []
    for package in packages:
        directory = _relative(Path(str(package.get("Dir", ""))), root)
        if directory is None:
            continue  # 模块缓存里的外部依赖,不在本仓
        records.append(
            {
                "import_path": str(package.get("ImportPath", "")),
                "dir": directory,
                "files": [f"{directory}/{name}" for name in package.get("GoFiles", [])],
            }
        )
    return sorted(records, key=lambda item: str(item["dir"]))


def package_edges(packages: list[dict], root: Path) -> list[dict[str, object]]:
    """包级导入边。只保留本模块内的 import(外部依赖不进图,与 Python 侧一致)。"""
    records = package_records(packages, root)
    dir_by_import = {str(item["import_path"]): str(item["dir"]) for item in records}
    edges: list[dict[str, object]] = []
    for package in packages:
        source_dir = _relative(Path(str(package.get("Dir", ""))), root)
        if source_dir is None:
            continue
        for import_path in package.get("Imports", []):
            target_dir = dir_by_import.get(str(import_path))
            if target_dir is None:
                continue  # 标准库或外部模块
            edges.append({"source_dir": source_dir, "target_dir": target_dir, "import_path": str(import_path)})
    return sorted(edges, key=lambda item: (str(item["source_dir"]), str(item["target_dir"])))
