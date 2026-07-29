#!/usr/bin/env python3
# 职责：TypeScript/JavaScript 语言适配器——用 dependency-cruiser 取出文件级导入图。
# 不做什么：不判断 zone 归属、不做策略判定、不提取顶层导出符号(那需要 tree-sitter,按需再加)。
# 允许依赖层：标准库、Node 工具链(经 npx 调 dependency-cruiser)。
# 谁不应该 import：正式业务代码、测试夹具、应用入口不应 import 本工具层模块。
"""TypeScript adapter: 文件级导入图，取自 `dependency-cruiser --output-type json`。

**粒度**:TS 的 import 指向**文件**(解析后带扩展名),和 Python 一样是文件级;Go 是包级。
所以三门语言两种粒度,框架的边记录两者都吃(见 inventory 里的 go_package_edges 注释)。

**两个实测出来的必要条件**(照真实项目 job-application-board 验的,不是照文档猜的):
1. 必须传**显式文件清单**。传目录时 `totalCruised` 是 0——它需要配置才知道哪些扩展名
   算源码,而目录遍历发生在那之前。传文件则绕过这一步。
2. 必须给一份**最小配置**。`--no-config` 会连 `enhancedResolveOptions.extensions` 一起
   关掉,于是 `./components/AppLayout` 这种相对 import 解析不出真实路径(只回显原样)。
   给了配置之后实测 57/57 条边全部解析成带扩展名的仓库相对路径。
   注意 `--ts-config tsconfig.json` **不能**替代这份配置,实测无效。

Go 侧零配置(`go list` 自带全部语义)、Python 侧零配置(ast 是标准库);TS 是三者里唯一
需要适配器自己造配置的,这是工具链差异,不是设计选择。
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

LANGUAGE_ID = "typescript"
SUFFIXES = (".ts", ".tsx", ".js", ".jsx", ".mts", ".cts")

# 最小可用配置:只为让模块解析按 TS 规则走,不带任何 forbidden 规则(架构判据住 inventory)。
MINIMAL_CONFIG: dict = {
    "forbidden": [],
    "options": {
        "doNotFollow": {"path": "node_modules"},
        "tsPreCompilationDeps": True,
        "enhancedResolveOptions": {
            "extensions": [".ts", ".tsx", ".mts", ".cts", ".js", ".jsx", ".json"],
            "mainFields": ["module", "main", "types", "typings"],
        },
    },
}


class NodeToolchainError(RuntimeError):
    """dependency-cruiser 不可用或跑失败。刻意 raise 而不是返回空图:空图会让所有闸静默通过。"""


def cruise(root: Path, files: list[str], runner: tuple[str, ...] = ("npx", "--yes", "dependency-cruiser")) -> dict:
    """跑 dependency-cruiser,返回它的 JSON 报告。files 必须是仓库相对的显式文件清单。"""
    if not files:
        return {"modules": [], "summary": {"totalCruised": 0}}
    with tempfile.TemporaryDirectory() as tmp:
        config_path = Path(tmp) / "dependency-cruiser.json"
        config_path.write_text(json.dumps(MINIMAL_CONFIG), encoding="utf-8")
        command = [*runner, "--config", str(config_path), "--output-type", "json", *files]
        try:
            proc = subprocess.run(command, cwd=root, capture_output=True, text=True, check=False)
        except OSError as exc:
            raise NodeToolchainError(f"跑不起来 {command[0]}:{exc}") from exc
        if proc.returncode != 0 or not proc.stdout.strip():
            detail = proc.stderr.strip() or f"exit {proc.returncode},且无输出"
            raise NodeToolchainError(f"dependency-cruiser 在 {root} 失败:{detail}")
        try:
            return json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            raise NodeToolchainError(f"dependency-cruiser 输出不是合法 JSON:{exc}") from exc


def _is_local(path_name: str) -> bool:
    """本仓文件:不在 node_modules 下、且已被解析成相对仓库根的真实路径(不是回显的 ./x)。"""
    return bool(path_name) and not path_name.startswith(("node_modules/", ".", "/"))


def file_edges(report: dict) -> list[dict[str, object]]:
    """文件级导入边:(source, target, 原始 import 串)。标准库与外部依赖不进图。"""
    edges: list[dict[str, object]] = []
    for module in report.get("modules", []):
        source = str(module.get("source", ""))
        if not _is_local(source):
            continue
        for dependency in module.get("dependencies", []):
            if dependency.get("coreModule"):
                continue
            target = str(dependency.get("resolved", ""))
            if not _is_local(target):
                continue
            edges.append(
                {
                    "source": source,
                    "target": target,
                    "module": str(dependency.get("module") or target),
                    "dynamic": bool(dependency.get("dynamic")),
                }
            )
    return sorted(edges, key=lambda item: (str(item["source"]), str(item["target"])))
