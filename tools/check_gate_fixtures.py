#!/usr/bin/env python3
# 职责：反向样本闸——每道会拦人的闸必须配一段"应当被拦住"的代码，跑它必须退非 0；并强制完备性(新增闸没配样本即红)。
# 不做什么：不判断闸的判据是否合理、不看输出文本(只看退出码)、不替人决定豁免。
# 允许依赖层：标准库、registry、gates/ 样本目录、tools/check.py(经子进程)。
# 谁不应该 import：正式业务代码、测试夹具、应用入口不应 import 本检查脚本。
"""Negative-fixture gate: every blocking check must still block its own bad sample.

Each fixture runs ONLY its own tool (`check.py <tool>`), never a whole stage, so a
different gate cannot mask a rotted one. Assertion is the exit code alone -- no output
parsing -- so fixtures do not rot when a tool changes its wording.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GATES_DIR = ROOT / "gates"
REGISTRY = ROOT / ".ai-config" / "config" / "tooling.registry.toml"


def load_registry() -> dict:
    return tomllib.loads(REGISTRY.read_text(encoding="utf-8"))


def required_tools(registry: dict) -> dict[str, str]:
    """Tools that can fail a commit or CI run, so they owe a negative fixture."""
    required: dict[str, str] = {}
    for tool in registry.get("tools", []):
        tool_id = str(tool.get("id", "")).strip()
        if not tool_id or tool.get("fixture_exempt"):
            continue
        stages = [str(stage) for stage in tool.get("stages", [])]
        if str(tool.get("enforcement", "")).strip() == "blocking":
            required[tool_id] = "enforcement=blocking"
        elif "ci" in stages:
            required[tool_id] = "runs in ci stage"
        elif tool.get("pre_commit_hook") or tool.get("pre_commit_hooks"):
            required[tool_id] = "wired into pre-commit"
    return required


class Fixture:
    """One bad sample plus the set of tools that must all reject it."""

    def __init__(self, directory: Path, tools: list[str], violates: str, *, needs_index: bool) -> None:
        self.directory, self.tools, self.violates = directory, tools, violates
        self.needs_index = needs_index

    @property
    def tree(self) -> Path:
        return self.directory / "tree"

    @property
    def appends(self) -> Path:
        """Fragments appended to same-named repo files; for gates whose criterion reads config itself."""
        return self.directory / "append"


def load_fixtures() -> list[Fixture]:
    fixtures: list[Fixture] = []
    claimed: dict[str, list[Path]] = {}
    if not GATES_DIR.is_dir():
        return fixtures
    for spec_path in sorted(GATES_DIR.glob("*/fixture.toml")):
        spec = tomllib.loads(spec_path.read_text(encoding="utf-8"))
        tools = [str(name).strip() for name in spec.get("tools", []) if str(name).strip()]
        if not tools:
            raise SystemExit(f"[fixtures] {spec_path} missing `tools` (要断言哪些工具必须拦住这个样本)")
        violates = str(spec.get("violates", "")).strip()
        if not violates:
            raise SystemExit(f"[fixtures] {spec_path} missing `violates` (一句话说明这个样本违反什么)")
        # 一个工具可以有多个样本:多判据的闸(元闸有 18 项检查)靠一个样本只证明了 1/18。
        # 完备性仍然要求每个能拦人的工具至少出现在一个样本里,这里只是允许覆盖得更深。
        for tool in tools:
            claimed.setdefault(tool, []).append(spec_path)
        fixtures.append(Fixture(spec_path.parent, tools, violates, needs_index=bool(spec.get("stage"))))
    return fixtures


def covered_tools(fixtures: list[Fixture]) -> set[str]:
    return {tool for fixture in fixtures for tool in fixture.tools}


def plant(tree: Path) -> list[Path]:
    """Copy a fixture tree into the repo; return touched paths (deepest first) for teardown."""
    created: list[Path] = []
    if not tree.is_dir():
        return created
    for source in sorted(tree.rglob("*")):
        target = ROOT / source.relative_to(tree)
        if source.is_dir():
            # 目录常与仓库既有结构重叠(src/、src/project/…)；只记录我们真正新建的，teardown 才敢删。
            if not target.exists():
                target.mkdir(parents=True)
                created.append(target)
            continue
        if target.exists():
            raise SystemExit(
                f"[fixtures] refuse to overwrite existing file: {source.relative_to(tree).as_posix()} "
                f"(要改既有配置请用 append/ 追加片段，不要整份替换——复本会与真本漂移)"
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        created.append(target)
    return list(reversed(created))


def backup_for(target: Path) -> Path:
    return target.with_name(f"{target.name}.fixture-backup")


def append_fragments(appends: Path) -> list[Path]:
    """Append each fragment to its same-named repo file, backing up the original first."""
    touched: list[Path] = []
    if not appends.is_dir():
        return touched
    for source in sorted(appends.rglob("*")):
        if source.is_dir():
            continue
        target = ROOT / source.relative_to(appends)
        if not target.is_file():
            raise SystemExit(f"[fixtures] append target does not exist: {target.relative_to(ROOT)}")
        shutil.copy2(target, backup_for(target))
        with target.open("a", encoding="utf-8") as handle:
            handle.write("\n" + source.read_text(encoding="utf-8"))
        touched.append(target)
    return touched


def uproot(created: list[Path]) -> None:
    for path in created:
        if path.is_dir():
            if not any(path.iterdir()):
                path.rmdir()
            continue
        backup = backup_for(path)
        if backup.exists():
            shutil.move(str(backup), str(path))
        elif path.exists():
            path.unlink()


def run_tool(tool: str) -> int:
    proc = subprocess.run(
        ["uv", "run", "python", "tools/check.py", tool], cwd=ROOT, capture_output=True, text=True, check=False
    )
    return proc.returncode


def git(args: list[str]) -> int:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, check=False).returncode


def index_is_clean() -> bool:
    """Gates that read `git diff --cached` need staging; only touch the index if it is empty."""
    return git(["diff", "--cached", "--quiet"]) == 0


def main() -> int:
    registry = load_registry()
    fixtures, required = load_fixtures(), required_tools(registry)
    covered = covered_tools(fixtures)
    known = {str(tool.get("id", "")).strip() for tool in registry.get("tools", [])}
    failures: list[str] = []

    failures.extend(f"fixture targets unknown tool `{tool}`" for tool in sorted(covered - known))
    failures.extend(
        f"`{tool}` can block ({why}) but has no negative fixture; add it to a gates/*/fixture.toml "
        f"`tools` list, or set fixture_exempt + fixture_exempt_reason in the registry"
        for tool, why in sorted(required.items())
        if tool not in covered
    )

    for fixture in fixtures:
        label = fixture.directory.name
        if not fixture.tree.is_dir() and not fixture.appends.is_dir():
            failures.append(f"fixture {label} has neither tree/ nor append/")
            continue
        if fixture.needs_index and not index_is_clean():
            sys.stdout.write(f"[fixtures] {label}: SKIPPED (需要暂存样本但 git 索引非空;先提交或 stash 后重跑)\n")
            continue
        created: list[Path] = []
        results: dict[str, int] = {}
        try:
            created = plant(fixture.tree) + append_fragments(fixture.appends)
            files = [str(path.relative_to(ROOT)) for path in created if path.is_file()]
            if fixture.needs_index:
                git(["add", "--", *files])
            results = {tool: run_tool(tool) for tool in fixture.tools}
        finally:
            if fixture.needs_index and created:
                git(["reset", "-q", "--", *[str(path.relative_to(ROOT)) for path in created if path.is_file()]])
            uproot(created)
        for tool, code in sorted(results.items()):
            sys.stdout.write(f"[fixtures] {tool}: {'blocked' if code else 'LET IT THROUGH'} ({fixture.violates})\n")
            if code == 0:
                failures.append(f"`{tool}` exited 0 on a sample that violates: {fixture.violates}")

    if failures:
        sys.stderr.write("[fixtures] negative-fixture gate failed:\n")
        for line in failures:
            sys.stderr.write(f"  - {line}\n")
        return 1
    sys.stdout.write(f"[fixtures] {len(fixtures)} samples rejected by {len(covered)} tools; {len(required)} blocking tools covered.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
