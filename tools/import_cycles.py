# lifecycle: tool（import 环检测闸;grimp 建图 + 最小 SCC）
# 职责：用 grimp 建生产包的模块级 import 图(含函数内延迟 import),找强连通分量>1=循环依赖簇。
#   为什么仍留手写 SCC：grimp 3.x 只给图与邻接、不提供全图环枚举(仅 nominate_cycle_breakers),
#   故"建图"整块交 grimp(替掉原手写 ast 图),仅保留最小 Tarjan——依赖给不了的残渣、稳定教科书算法、不随语法漂移。
#   import-linter independence 只查指定模块两两独立、查不到全图任意环;本闸补这个洞。
# 不做什么：不改文件;只报环、不判谁该让步(边界划错=人裁)。
# 允许依赖层：标准库、grimp、.importlinter 配置(取 root package)、git(--scope changed)。
# 谁不应该 import：正式业务代码、测试夹具、应用入口不应 import 本检查脚本。
# 运行：python tools/import_cycles.py [--scope full|changed]

from __future__ import annotations

import argparse
import configparser
import subprocess
import sys
from pathlib import Path

import grimp

ROOT = Path(__file__).resolve().parents[1]
IMPORTLINTER_CFG = ROOT / ".importlinter"

# grimp 用 importlib 定位 root package,需仓库根在 sys.path 上
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def root_packages() -> list[str]:
    """从 .importlinter 复用 root_packages(单一事实源,不再另配图源)。"""
    parser = configparser.ConfigParser()
    parser.read(IMPORTLINTER_CFG, encoding="utf-8")
    raw = parser.get("importlinter", "root_packages", fallback="")
    return [line.strip() for line in raw.splitlines() if line.strip()]


def build_adjacency(packages: list[str]) -> dict[str, set[str]]:
    """grimp 建图 → {模块: {它直接 import 的内部模块}}。grimp 天然含函数内延迟 import。"""
    adjacency: dict[str, set[str]] = {}
    for package in packages:
        graph = grimp.build_graph(package)
        internal = set(graph.modules)
        for module in graph.modules:
            adjacency.setdefault(module, set())
            for target in graph.find_modules_directly_imported_by(module):
                if target in internal and target != module:
                    adjacency[module].add(target)
    for targets in list(adjacency.values()):
        for target in targets:
            adjacency.setdefault(target, set())
    return adjacency


def tarjan(adjacency: dict[str, set[str]]) -> list[list[str]]:
    """最小 Tarjan 强连通分量(>1=环)——grimp 不提供全图环枚举,唯一残留手写。"""
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    on_stack: dict[str, bool] = {}
    stack: list[str] = []
    counter = [0]
    sccs: list[list[str]] = []

    def strongconnect(v: str) -> None:
        index[v] = low[v] = counter[0]
        counter[0] += 1
        stack.append(v)
        on_stack[v] = True
        for w in adjacency.get(v, ()):
            if w not in index:
                strongconnect(w)
                low[v] = min(low[v], low[w])
            elif on_stack.get(w):
                low[v] = min(low[v], index[w])
        if low[v] == index[v]:
            component: list[str] = []
            while True:
                w = stack.pop()
                on_stack[w] = False
                component.append(w)
                if w == v:
                    break
            if len(component) > 1:
                sccs.append(component)

    sys.setrecursionlimit(max(sys.getrecursionlimit(), 5000))
    for v in adjacency:
        if v not in index:
            strongconnect(v)
    return sccs


def changed_modules(packages: list[str]) -> set[str]:
    """--scope changed:git 取改动/暂存/未跟踪 .py → 模块名(纯 git,不碰图)。"""
    pkgset = set(packages)
    names: set[str] = set()
    for git_args in (
        ["git", "diff", "--name-only", "HEAD", "--", "*.py"],
        ["git", "diff", "--name-only", "--cached", "--", "*.py"],
        ["git", "ls-files", "--others", "--exclude-standard", "--", "*.py"],
    ):
        try:
            out = subprocess.run(git_args, cwd=ROOT, capture_output=True, text=True, check=False).stdout
        except OSError:
            continue
        for name in out.splitlines():
            stripped = name.strip()
            if stripped.endswith(".py"):
                names.add(stripped)
    modules: set[str] = set()
    for name in names:
        # 从第一个命中 root package 的路径段起截取:src-layout(src/project/x.py)与平铺布局都能落到
        # 正确的模块名。早先直接 replace("/", ".") 会把 src/ 前缀留在首段，导致 src-layout 项目
        # 的所有改动都被 pkgset 过滤掉，这道 changed 闸永不触发。
        segments = name.removesuffix(".py").split("/")
        start = next((index for index, segment in enumerate(segments) if segment in pkgset), None)
        if start is None:
            continue
        modules.add(".".join(segments[start:]).removesuffix(".__init__"))
    return modules


def find_cycles(scope: str = "full") -> tuple[list[list[str]], int]:
    """对外可测入口:返回 (SCC 列表, 模块数)。"""
    packages = root_packages()
    if not packages:
        return [], 0
    adjacency = build_adjacency(packages)
    sccs = tarjan(adjacency)
    if scope == "changed":
        changed = changed_modules(packages)
        sccs = [comp for comp in sccs if changed.intersection(comp)]
    return sccs, len(adjacency)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scope", choices=["full", "changed"], default="full")
    parser.add_argument("paths", nargs="*")  # 兼容旧签名,grimp 按 root package 建图,忽略
    args = parser.parse_args(argv)
    sccs, module_count = find_cycles(args.scope)
    print(f"[examined] module {module_count}")
    print(f"模块 {module_count} | 循环依赖簇 {len(sccs)}\n")
    for comp in sccs:
        print("  环:", " ↔ ".join(sorted(comp)))
    if not sccs:
        print("  (无环)")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
