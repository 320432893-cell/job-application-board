#!/usr/bin/env python3
# 职责：零消费者闸——新增的模块若没有任何调用方，MUST 同时登记"预期消费者 + 可判定的清除条件 + 日期"，否则阻塞。
# 不做什么：不判断符号级死码(那是 vulture/knip/deadcode 的活)、不自动删任何文件、不替人决定该不该留。
# 允许依赖层：标准库、inventory 产出的导入图、baseline_policy、registry。
# 谁不应该 import：正式业务代码、测试夹具、应用入口不应 import 本检查脚本。
"""Zero-consumer gate: a module nobody imports must declare who will use it and when it can go.

难点从来不是"发现零调用"，是"证明它可删"——入口点、晚绑定点、迁移路径都长得像死代码。
所以这道闸不猜：零入边且未登记 = 红；要留就写下预期消费者和可判定的清除条件，
事后清理按登记判，不靠考古。
"""

from __future__ import annotations

import json
import sys
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import baseline_policy
import inventory as inventory_tool

ROOT = Path(__file__).resolve().parents[1]
BASELINE_PATH = ROOT / ".ai-config" / "config" / "orphans.baseline.json"
REGISTRY_PATH = ROOT / ".ai-config" / "config" / "tooling.registry.toml"
REQUIRED_FIELDS = ("expected_consumer", "clear_when", "registered")


def registry_command_targets() -> set[str]:
    """registry 命令里点名要跑的脚本:它们是 CLI 入口,零入边是正常的。"""
    if not REGISTRY_PATH.exists():
        return set()
    registry = tomllib.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    targets: set[str] = set()
    # metadata 里点名的入口(实现入口 / 启动入口)同样是 CLI 入口,没人 import 它们是对的。
    metadata = registry.get("metadata", {})
    targets.update(str(metadata[key]) for key in ("unified_entrypoint", "launch_entrypoint") if metadata.get(key))
    for tool in registry.get("tools", []):
        for field in ("entrypoint_commands", "ci_commands", "manual_commands"):
            for command in tool.get(field, []):
                targets.update(token.strip("'\"") for token in str(command).split() if token.endswith(".py"))
    return targets


def orphan_modules(inventory: dict) -> list[tuple[str, str]]:
    """零入边且不属于任何正当"本来就没人 import"类别的模块 → (path, zone)。"""
    inbound = {str(edge.get("target_path")) for edge in inventory.get("edges", []) if edge.get("target_path")}
    entrypoints = {str(item.get("file")) for item in inventory.get("entrypoints", []) if item.get("file")}
    cli_targets = registry_command_targets()
    test_zones = {"test"}
    found: list[tuple[str, str]] = []
    for record in inventory.get("files", []):
        path, zone = str(record.get("path", "")), str(record.get("zone", ""))
        if not path or path in inbound or path in entrypoints or path in cli_targets:
            continue
        if zone in test_zones or Path(path).name == "__init__.py":
            continue  # 测试由 runner 收集、__init__.py 是包标记:两者天然零入边
        found.append((path, zone))
    return sorted(found)


def load_baseline() -> dict[str, dict]:
    if not BASELINE_PATH.exists():
        return {}
    try:
        data = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"[orphan] 登记表无法解析:{BASELINE_PATH}: {exc}") from exc
    entries = data.get("entries", {})
    return entries if isinstance(entries, dict) else {}


def registration_problems(path: str, entry: object) -> list[str]:
    if not isinstance(entry, dict):
        return [f"{path}: 登记项必须是对象"]
    problems = [f"{path}: 登记缺 {field}" for field in REQUIRED_FIELDS if not str(entry.get(field, "")).strip()]
    clear_when = str(entry.get("clear_when", "")).strip()
    if clear_when and (hits := baseline_policy.vague_hits(clear_when)):
        problems.append(f"{path}: clear_when 含糊词 {hits}(要能判出真假,不是『以后/待定』)")
    return problems


def main(argv: list[str]) -> int:
    inventory = inventory_tool.build_inventory(scope="full")
    orphans = dict(orphan_modules(inventory))
    baseline = load_baseline()

    unregistered = sorted(set(orphans) - set(baseline))
    problems = [msg for path, entry in sorted(baseline.items()) for msg in registration_problems(path, entry)]
    resolved = sorted(set(baseline) - set(orphans))

    if "--list" in argv:
        for path, zone in sorted(orphans.items()):
            print(f"{path}  zone={zone}  {'已登记' if path in baseline else '未登记'}")
        return 0

    if unregistered or problems:
        sys.stderr.write("[orphan] 零消费者闸失败:\n")
        for path in unregistered:
            sys.stderr.write(
                f"  X {path}(zone={orphans[path]}):没有任何模块 import 它。\n"
                f"    要留 → 在 {baseline_policy.relative(BASELINE_PATH)} 登记 "
                f"expected_consumer / clear_when(可判定) / registered(日期);要不留 → 删掉它。\n"
            )
        for msg in problems:
            sys.stderr.write(f"  X {msg}\n")
        return 1

    if resolved:
        print(f"[orphan] {len(resolved)} 条登记已有消费者,可从登记表删除锁战果:{', '.join(resolved[:5])}")
    print(f"[orphan] 零消费者模块 {len(orphans)} 个,全部已登记且清除条件可判定。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
