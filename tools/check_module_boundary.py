#!/usr/bin/env python3
"""检查 Python 文件是否有职责声明注释块，并对文件行数硬闸把关。

新文件/本次改动文件要求当前四项职责格式：
  # 职责：...
  # 不做什么：...
  # 允许依赖层：...
  # 谁不应该 import：...

行数硬闸：changed 模式下 ≥ LINE_THRESHOLD 行的文件阻塞（拆分）；存量超限文件挂 oversized
baseline（计数型棘轮·只减不增：在册且未长大 → 挂账，长大或新增超限 → 阻塞）。full 模式仅 WARNING。
全量扫描仍兼容旧字段名，避免存量文件因纯规则迁移被迫 churn。测试文件用更高阈值且只 WARNING。
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import baseline_policy
import inventory as inventory_tool
from project_model import zone_traits_map
from tooling_layout import formal_dirs, inactive_dirs, is_relative_path_ignored, test_dirs

ROOT = pathlib.Path(__file__).resolve().parents[1]
EXCLUDE_NAMES = {"__init__.py", "conftest.py"}
EXCLUDE_PREFIXES = ("test_",)
EXCLUDE_SUFFIXES = ("_test.py",)

CURRENT_MARKERS = ("# 职责：", "# 不做什么：", "# 允许依赖层：", "# 谁不应该 import：")
FULL_SCAN_MARKER_GROUPS = (
    ("# 职责：",),
    ("# 不做什么：", "# 不负责："),
    ("# 允许依赖层：", "# 依赖层："),
    ("# 谁不应该 import：",),
)
LINE_THRESHOLD = 600
TEST_DIRS = set(test_dirs())  # 测试天然长：用更高阈值只报"膨胀候选"，不强加四项职责块（测试归 test-meta）。
TEST_LINE_THRESHOLD = 600
# 存量超限文件计数型棘轮(只减不增)：登记 {path: 行数}。超限但在册且未长大 → 挂账(WARN)；新增超限或继续长大 → 阻塞。
OVERSIZED_BASELINE_PATH = ROOT / ".ai-config" / "config" / "oversized.baseline.json"
# 档位豁免：文件头标 `# tier: 小件/抛弃` → 跳过职责块+行数闸(小脚本);正式区不许免检。
TIER_EXEMPT = re.compile(r"#\s*tier:\s*(小件|small|throwaway|抛弃)", re.IGNORECASE)


def rel(path: pathlib.Path) -> str:
    return path.relative_to(ROOT).as_posix()


def is_tier_exempt(path: pathlib.Path) -> bool:
    try:
        path_name = path.relative_to(ROOT).as_posix()
    except ValueError:
        return False
    if any(path_name == directory or path_name.startswith(f"{directory}/") for directory in formal_dirs()):
        return False
    try:
        head = "\n".join(path.read_text(encoding="utf-8", errors="replace").splitlines()[:8])
    except OSError:
        return False
    return bool(TIER_EXEMPT.search(head))


def should_scan(path: pathlib.Path) -> bool:
    name = path.name
    if path.suffix != ".py" or not path.is_file():
        return False
    if is_tier_exempt(path):
        return False
    if is_relative_path_ignored(rel(path)):
        return False
    path_str = rel(path)
    if any(path_str == directory or path_str.startswith(f"{directory}/") for directory in inactive_dirs()):
        return False
    if name in EXCLUDE_NAMES:
        return False
    if any(name.startswith(p) for p in EXCLUDE_PREFIXES):
        return False
    return not any(name.endswith(s) for s in EXCLUDE_SUFFIXES)


def read_file(path: pathlib.Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def missing_current_markers(path: pathlib.Path) -> list[str]:
    text = read_file(path)
    if not text:
        return []
    return [marker for marker in CURRENT_MARKERS if marker not in text]


def missing_full_scan_markers(path: pathlib.Path) -> list[str]:
    text = read_file(path)
    if not text:
        return []
    return [" 或 ".join(group) for group in FULL_SCAN_MARKER_GROUPS if not any(marker in text for marker in group)]


def line_count(path: pathlib.Path) -> int:
    try:
        return sum(1 for _ in path.open("r", encoding="utf-8", errors="ignore"))
    except OSError:
        return 0


def inventory_scan_files(scope: str, *, tests: bool = False) -> list[pathlib.Path]:
    model = inventory_tool.load_project_model()
    traits = zone_traits_map(model)
    inventory = inventory_tool.build_inventory(scope=scope)
    paths: list[pathlib.Path] = []
    for file_record in inventory.get("files", []):
        zone_id = str(file_record.get("zone") or "")
        zone = traits.get(zone_id, set())
        is_test_zone = "test_like" in zone
        if tests != is_test_zone:
            continue
        # managed 项目的历史正式区可能尚未补 quality_fixed；只要标 formal_like，
        # 本次触碰就同样必须补职责声明，不能把它静默当成观察区。
        if not tests and not ({"formal_like", "quality_fixed", "support_like"} & zone):
            continue
        if "inactive" in zone or "archive_like" in zone:
            continue
        path = ROOT / str(file_record.get("path") or "")
        if path.exists() and (is_test_module(path) if tests else should_scan(path)):
            paths.append(path)
    return sorted(paths)


def iter_full_scan_files() -> list[pathlib.Path]:
    return inventory_scan_files("full")


def iter_changed_scan_files() -> tuple[int, list[pathlib.Path]]:
    return 0, inventory_scan_files("changed")


def is_test_module(path: pathlib.Path) -> bool:
    path_str = rel(path)
    return (
        path.suffix == ".py"
        and path.is_file()
        and any(path_str == test_dir or path_str.startswith(f"{test_dir}/") for test_dir in TEST_DIRS)
        and path.name not in EXCLUDE_NAMES
    )


def iter_full_test_files() -> list[pathlib.Path]:
    return inventory_scan_files("full", tests=True)


def iter_changed_test_files() -> tuple[int, list[pathlib.Path]]:
    return 0, inventory_scan_files("changed", tests=True)


def load_oversized_baseline() -> dict[str, dict[str, object]]:
    if not OVERSIZED_BASELINE_PATH.exists():
        return {}
    try:
        data = json.loads(OVERSIZED_BASELINE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    entries = data.get("entries", {})
    if not isinstance(entries, dict):
        return {}
    normalized: dict[str, dict[str, object]] = {}
    for path, value in entries.items():
        if isinstance(value, dict):
            normalized[str(path)] = value
        else:
            normalized[str(path)] = {
                "lines": int(value),
                "reason": "legacy oversized baseline",
                "split_when": "next cleanup",
            }
    return normalized


def oversized_baseline_expands(current: dict[str, dict[str, object]], prior: dict[str, object]) -> bool:
    entries = prior.get("entries", {})
    if not isinstance(entries, dict):
        return True
    for path, entry in current.items():
        previous = entries.get(path)
        if not isinstance(previous, dict):
            return True
        try:
            if int(entry.get("lines", 0)) > int(previous.get("lines", 0)):
                return True
        except (TypeError, ValueError):
            return True
    return False


def enforce_oversized_baseline_policy(baseline: dict[str, dict[str, object]]) -> None:
    prior = baseline_policy.head_json(OVERSIZED_BASELINE_PATH)
    if prior is not None:
        baseline_policy.require_expansion_approval(
            OVERSIZED_BASELINE_PATH,
            expansion=oversized_baseline_expands(baseline, prior),
            action="baseline change",
        )


def oversized_limit(entry: dict[str, object] | None) -> int | None:
    if not entry:
        return None
    try:
        return int(entry.get("lines", 0))
    except (TypeError, ValueError):
        return None


def classify_oversized(
    paths: list[pathlib.Path], threshold: int, baseline: dict[str, dict[str, object]]
) -> tuple[list[str], list[str]]:
    """超限文件分流：返回 (阻塞消息, 挂账WARNING消息)。计数型棘轮只减不增。"""
    blocking: list[str] = []
    warn: list[str] = []
    for path in paths:
        count = line_count(path)
        if count < threshold:
            continue
        rp = rel(path)
        entry = baseline.get(rp)
        base = oversized_limit(entry)
        if base is None:
            blocking.append(
                f"{rp}  {count} 行 ≥ {threshold}（新增超限：拆分；确需保留→登记 oversized baseline 并写拆分时机）"
            )
        elif count > base:
            blocking.append(
                f"{rp}  {count} 行 > 登记基线 {base}（超限文件继续长大，棘轮只减不增——拆分或降回 {base} 内）"
            )
        else:
            split_when = str((entry or {}).get("split_when") or "next cleanup")
            warn.append(f"{rp}  {count} 行（oversized baseline 挂账·只减不增·待拆：{split_when}）")
    return blocking, warn


def report_oversized(paths: list[pathlib.Path], threshold: int = LINE_THRESHOLD) -> None:
    """full 模式仅 WARNING（不阻塞）。"""
    oversized = [(path, count) for path in paths if (count := line_count(path)) >= threshold]
    if not oversized:
        return
    sys.stderr.write(f"[module-boundary] WARNING：{len(oversized)} 个文件 ≥ {threshold} 行（拆分候选）：\n")
    for path, lines in oversized:
        sys.stderr.write(f"  {rel(path)}  {lines} 行\n")


def run_changed() -> int:
    rc, paths = iter_changed_scan_files()
    if rc != 0:
        return rc
    rc_test, test_paths = iter_changed_test_files()
    if rc_test != 0:
        return rc_test

    baseline = load_oversized_baseline()
    enforce_oversized_baseline_policy(baseline)
    block, warn = classify_oversized(paths, LINE_THRESHOLD, baseline)
    _, test_warn = classify_oversized(test_paths, TEST_LINE_THRESHOLD, baseline)
    for line in warn + test_warn:
        sys.stderr.write(f"! [module-boundary] {line}\n")
    for line in block:
        sys.stderr.write(f"X [module-boundary] 超行数硬闸：{line}\n")

    failures = [(path, missing) for path in paths if (missing := missing_current_markers(path))]
    if failures:
        sys.stderr.write(f"[module-boundary] changed: {len(failures)} 个本次改动文件缺少当前四项职责声明：\n")
        for path, missing in failures:
            sys.stderr.write(f"  {rel(path)}  缺失: {', '.join(missing)}\n")
        sys.stderr.write(
            "\n在文件顶部添加：\n"
            "  # 职责：[做什么]\n"
            "  # 不做什么：[不做什么，至少一项]\n"
            "  # 允许依赖层：[允许 import 的层/模块]\n"
            "  # 谁不应该 import：[不应 import 本文件的层/模块]\n",
        )

    if not paths and not block:
        sys.stdout.write("[module-boundary] changed: no changed Python module files\n")
    elif not failures and not block:
        sys.stdout.write("[module-boundary] changed: 本次改动文件均有四项职责声明 + 未触发行数硬闸\n")
    return 1 if (failures or block) else 0


def run_full() -> int:
    failures: list[tuple[pathlib.Path, list[str]]] = []
    paths = iter_full_scan_files()
    for path in paths:
        missing = missing_full_scan_markers(path)
        if missing:
            failures.append((path, missing))

    report_oversized(paths)
    report_oversized(iter_full_test_files(), TEST_LINE_THRESHOLD)

    if not failures:
        sys.stdout.write("[module-boundary] 全部文件均有职责声明注释块\n")
        return 0

    sys.stderr.write(f"[module-boundary] {len(failures)} 个文件缺少职责声明注释块：\n")
    for path, missing in failures:
        sys.stderr.write(f"  {rel(path)}  缺失: {', '.join(missing)}\n")
    sys.stderr.write(
        "\n推荐使用当前格式：\n"
        "  # 职责：[做什么]\n"
        "  # 不做什么：[不做什么，至少一项]\n"
        "  # 允许依赖层：[允许 import 的层/模块]\n"
        "  # 谁不应该 import：[不应 import 本文件的层/模块]",
    )
    sys.stderr.write("\n")
    return 1


def run_ci() -> int:
    baseline = load_oversized_baseline()
    enforce_oversized_baseline_policy(baseline)
    block, warn = classify_oversized(iter_full_scan_files(), LINE_THRESHOLD, baseline)
    _, test_warn = classify_oversized(iter_full_test_files(), TEST_LINE_THRESHOLD, baseline)
    for line in warn + test_warn:
        sys.stderr.write(f"! [module-boundary] {line}\n")
    if not block:
        sys.stdout.write("[module-boundary] CI oversized baseline ok\n")
        return 0
    for line in block:
        sys.stderr.write(f"X [module-boundary] CI oversized hard gate: {line}\n")
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--changed", action="store_true", help="Only check changed, staged, and untracked Python files."
    )
    parser.add_argument(
        "--ci", action="store_true", help="Enforce oversized baseline ratchet across all quality files."
    )
    args = parser.parse_args()
    if args.changed:
        return run_changed()
    if args.ci:
        return run_ci()
    return run_full()


if __name__ == "__main__":
    sys.exit(main())
