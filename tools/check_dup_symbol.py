# 职责：顶层符号碰撞检测——正式代码里新增 def/class 若与别处完全同名则阻塞，去版本后缀后同词根则报复核，
#       把"已有同类"摆到台面；历史名字仅 cleanup 提示，避免接管项目改旧文件被误拦。不靠语义，靠名字给信号。
# 不做什么：不删、不判取代/重复(交人);不查类内方法名(同名合法);不管模型标记的测试/临时/非活跃区。
# 允许依赖层：标准库(ast/re/subprocess)、git 工作区状态、被扫描的正式代码。
# 谁不应该 import：正式业务代码、测试夹具、应用入口不应 import 本检查脚本。
"""Top-level symbol collision detector.

Changed mode considers only names added since ``HEAD`` (following Git renames): an exact collision blocks, while a
version-suffix-stripped stem collision is review material. This keeps an adopted repository
usable: editing a legacy file must not be treated as introducing its pre-existing names.
Full mode reports all legacy collisions as cleanup candidates and never decides semantics.
"""

from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import inventory as inventory_tool
from project_model import zone_traits_map

ROOT = Path(__file__).resolve().parents[1]
SUFFIX = re.compile(r"_(v?\d+|new|old|legacy|copy|bak|tmp|fix\d*)$", re.IGNORECASE)
# 通用入口/钩子名:多文件同名是常态、非重复嫌疑,排除以压误报。
GENERIC = {"main", "run", "cli", "setup", "build", "parse_args", "lifespan", "health", "index"}
# 同一词根出现在 ≥2 个文件才算碰撞:同文件内重名不成立(定义顺序覆盖,非双源)。
MIN_COLLISION_FILES = 2
# 短词根(<4 字符)命中率高但信息量低,按噪声压掉。
MIN_STEM_LENGTH = 4
# `git diff --name-status -M` 的重命名行恰好两列:旧路径 + 新路径。
RENAME_FIELD_COUNT = 2


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def prod_files() -> list[Path]:
    return inventory_files("full", required_trait="formal_like")


def inventory_files(scope: str, *, required_trait: str) -> list[Path]:
    model = inventory_tool.load_project_model()
    traits = zone_traits_map(model)
    inventory = inventory_tool.build_inventory(scope=scope)
    paths: list[Path] = []
    for file_record in inventory.get("files", []):
        zone_id = str(file_record.get("zone") or "")
        if required_trait not in traits.get(zone_id, set()):
            continue
        path = ROOT / str(file_record.get("path") or "")
        if path.exists() and not path.name.startswith("test_"):
            paths.append(path)
    return sorted(paths)


def symbols_in_text(text: str) -> set[str]:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return set()
    return {node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}


def top_symbols(path: Path) -> set[str]:
    try:
        return symbols_in_text(path.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return set()


def stem(name: str) -> str:
    return SUFFIX.sub("", name)


def changed_files() -> set[Path]:
    return set(inventory_files("changed", required_trait="formal_like"))


def renamed_sources(paths: set[Path]) -> dict[Path, str]:
    """Map current paths to their HEAD paths so a pure rename keeps its history."""
    if not paths:
        return {}
    proc = subprocess.run(
        ["git", "diff", "HEAD", "--name-status", "-M"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        return {}
    sources: dict[Path, str] = {}
    for line in proc.stdout.splitlines():
        status, *names = line.split("\t")
        if status.startswith("R") and len(names) == RENAME_FIELD_COUNT:
            old_name, new_name = names
            new_path = ROOT / new_name
            if new_path in paths:
                sources[new_path] = old_name
    return sources


def head_symbols(path: Path, *, head_path: str | None = None) -> set[str]:
    """Return symbols at HEAD; a missing path is a newly added/untracked module."""
    proc = subprocess.run(
        ["git", "show", f"HEAD:{head_path or rel(path)}"], cwd=ROOT, text=True, capture_output=True, check=False
    )
    return symbols_in_text(proc.stdout) if proc.returncode == 0 else set()


def added_symbols(paths: set[Path]) -> dict[Path, set[str]]:
    sources = renamed_sources(paths)
    return {path: top_symbols(path) - head_symbols(path, head_path=sources.get(path)) for path in paths}


def changed_hits(
    index: dict[str, list[tuple[str, Path]]], added: dict[Path, set[str]]
) -> tuple[list[tuple[str, list[str], str]], list[tuple[str, list[str], str]]]:
    """Return (exact blocking, near-name review) hits caused by newly added symbols only."""
    exact: list[tuple[str, list[str], str]] = []
    near: list[tuple[str, list[str], str]] = []
    newly_added = {(symbol, path) for path, symbols in added.items() for symbol in symbols}
    for stem_name, occurrences in index.items():
        files = {path for _, path in occurrences}
        if len(files) < MIN_COLLISION_FILES:
            continue
        names = sorted({symbol for symbol, _ in occurrences})
        locations = ", ".join(sorted(rel(path) for path in files))
        exact_names = {
            symbol
            for symbol, path in newly_added
            if any(other == symbol and other_path != path for other, other_path in occurrences)
        }
        if exact_names:
            exact.append((stem_name, sorted(exact_names), locations))
        if len(names) > 1 and any((symbol, path) in newly_added for symbol, path in occurrences):
            near.append((stem_name, names, locations))
    return sorted(exact), sorted(near)


def main(argv: list[str]) -> int:
    changed_mode = "--changed" in argv
    index: dict[str, list[tuple[str, Path]]] = {}
    for path in prod_files():
        for sym in top_symbols(path):
            if sym.startswith("__") or sym in GENERIC or len(stem(sym)) < MIN_STEM_LENGTH:
                continue
            index.setdefault(stem(sym), []).append((sym, path))

    changed = changed_files() if changed_mode else None
    hits: list[tuple[str, list[str], str]] = []
    for stem_name, occ in index.items():
        files = {p for _, p in occ}
        if len(files) < MIN_COLLISION_FILES:
            continue
        names = sorted({s for s, _ in occ})
        hits.append((stem_name, names, ", ".join(sorted(rel(p) for p in files))))

    if changed_mode:
        exact, near = changed_hits(index, added_symbols(changed))
        for stem_name, names, locs in exact:
            sys.stderr.write(
                f"X [dup-symbol] 新增完全同名符号 {names}（词根 '{stem_name}'）: {locs} —— 必须取代、改名或由人明确裁决。\n"
            )
        for stem_name, names, locs in near:
            sys.stderr.write(
                f"! [dup-symbol] 新增近似命名 {names}（词根 '{stem_name}'）: {locs} —— 机器只给信号，交子 agent/人判是否同一能力。\n"
            )
        if not exact and not near:
            sys.stdout.write("[dup-symbol] 无新增顶层符号碰撞（changed 范围）\n")
        return 1 if exact else 0

    for stem_name, names, locs in sorted(hits):
        sys.stderr.write(f"! [dup-symbol] 词根 '{stem_name}'(符号 {names})出现在多处: {locs} —— 清理候选，取代还是重复?\n")
    if hits:
        sys.stderr.write(
            f"[dup-symbol] {len(hits)} 处历史/近似顶层符号碰撞（cleanup 提示）：同一能力两处=SSOT 双源嫌疑，"
            "由子 agent/人判断取代、保留边界或删。\n"
        )
    else:
        sys.stdout.write("[dup-symbol] 无近似重复顶层符号\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
