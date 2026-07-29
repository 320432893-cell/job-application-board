# 职责：扫生命周期身份标注——报 非正式区(scripts/devtools/tmp/probes)文件缺 # lifecycle: 身份标注
#       (存量挂 baseline 棘轮·新增阻塞)、标 devtool 却不在 devtools/。
# 不做什么：不删文件、不归档；不再管 expires 日期/superseded 标记那套（理想情况设计·0 使用，已删——
#           旧码清理交「取代纪律」的状态推导：死码 vulture + 重复块 + 晋升门，不靠自愿写日期/贴标）。
# 允许依赖层：标准库、本仓库 git 工作区状态、被扫描的源码注释、lifecycle baseline 文件。
# 谁不应该 import：正式业务代码、测试夹具、应用入口不应 import 本检查脚本。
"""Lifecycle identity-tag check: informal-zone files must carry a `# lifecycle:` tag;
untagged stock is pinned by an only-shrink cleanup baseline, but a touched file must be fixed. The expires-date machinery was
removed — it was an ideal-case design (needs a voluntary, unrewarded `# expires:`) with
zero real usage; stale-code cleanup is handled by supersession discipline (state-derived)."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import baseline_policy
import inventory as inventory_tool
from project_model import zone_traits_map
from tooling_layout import devtools_dir, support_dirs

ROOT = Path(__file__).resolve().parents[1]
HEAD_LINES = 15

# 仅保留"身份标注"识别：temp/t0、devtool、兼容别名——用于判断文件是否已声明身份(has_tag)。
# 注释符两种都认(`#` 与 `//`)：只认 `#` 的话,TypeScript/JS 文件永远标注不上,这道闸在前端项目里
# 会对每个非正式区文件稳定误报——而误报的修法(往 .ts 里写 `#`)本身是语法错误。
COMMENT = r"(?:#|//)"
TEMP = re.compile(rf"{COMMENT}\s*lifecycle:\s*(t0|temp)\b", re.IGNORECASE)
DEVTOOL = re.compile(rf"{COMMENT}\s*lifecycle:\s*devtool\b", re.IGNORECASE)
ALIAS = re.compile(rf"{COMMENT}\s*兼容别名")

# 存量未标注清单(只减不增的条目型 baseline)：新增不在册的未标注文件 → 阻塞；在册的 → 挂账提醒。
BASELINE_PATH = ROOT / ".ai-config" / "config" / "lifecycle_untagged.baseline.json"

# 与项目其它工具同口径排除；scratch/ 是零检查草稿区，一并跳过。
SKIP_DIRS = {
    *support_dirs(),
    "node_modules",
    ".ai-config",
    "scratch",
    ".venv-causal",
    "site-packages",
}


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def changed_py_files() -> list[Path]:
    return inventory_py_files("changed")


def all_py_files() -> list[Path]:
    return inventory_py_files("full")


def inventory_py_files(scope: str) -> list[Path]:
    model = inventory_tool.load_project_model()
    traits = zone_traits_map(model)
    inventory = inventory_tool.build_inventory(scope=scope)
    paths: list[Path] = []
    for file_record in inventory.get("files", []):
        zone_id = str(file_record.get("zone") or "")
        path = ROOT / str(file_record.get("path") or "")
        if not path.exists():
            continue
        if "support_like" in traits.get(zone_id, set()) and "ephemeral" not in traits.get(zone_id, set()):
            continue
        if set(path.parts) & SKIP_DIRS:
            continue
        paths.append(path)
    return sorted(paths)


def in_informal_zone(path: Path) -> bool:
    model = inventory_tool.load_project_model()
    zone_id, _ = inventory_tool.classify(rel(path), model)
    return "ephemeral" in zone_traits_map(model).get(zone_id, set())


def scan(path: Path) -> list[tuple[str, str]]:
    text = path.read_text(encoding="utf-8", errors="replace")
    head = "\n".join(text.splitlines()[:HEAD_LINES])
    is_temp = bool(TEMP.search(head)) or bool(ALIAS.search(text))
    is_devtool = bool(DEVTOOL.search(head))
    has_tag = is_temp or is_devtool
    findings: list[tuple[str, str]] = []
    if is_devtool and devtools_dir() not in path.relative_to(ROOT).parts:
        findings.append(("DEVTOOL-MISPLACED", "标 `# lifecycle: devtool`(TS 用 //)必须住 devtools/，否则上提或改标 temp"))
    if in_informal_zone(path) and not has_tag and not path.name.startswith("__"):
        findings.append(("UNTAGGED", "非正式区文件缺 `# lifecycle:` 身份标注(TS 用 //；temp/t0 临时件，或 devtool 住 devtools/)"))
    return findings


def load_baseline() -> set[str]:
    if not BASELINE_PATH.exists():
        return set()
    try:
        data = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return set()
    return set(data.get("entries", []))


def write_baseline(entries: set[str]) -> None:
    baseline_policy.require_expansion_approval(
        BASELINE_PATH, expansion=not entries.issubset(load_baseline()), action="baseline update"
    )
    payload = {
        "reason": "存量非正式区(scripts/ 等)文件在身份规则上线前未标 # lifecycle:",
        "clear_by": "各文件随其切片闭包或项目收尾补标 temp/devtool 或删除，目标降到 0 条",
        "registered": "2026-06-15",
        "ratchet": "只减不增：新增未标注文件不得入册(CI 阻塞)；修好的条目应从此清单移除",
        "entries": sorted(entries),
    }
    BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
    BASELINE_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str]) -> int:
    if "--update-baseline" in argv:
        untagged = {rel(p) for p in all_py_files() for kind, _ in scan(p) if kind == "UNTAGGED"}
        write_baseline(untagged)
        sys.stdout.write(f"[lifecycle] baseline 已写入 {rel(BASELINE_PATH)}：{len(untagged)} 条存量未标注\n")
        return 0

    changed_mode = "--changed" in argv
    targets = changed_py_files() if changed_mode else all_py_files()
    baseline = load_baseline()
    prior = baseline_policy.head_json(BASELINE_PATH)
    if prior is not None:
        prior_entries = set(prior.get("entries", []))
        baseline_policy.require_expansion_approval(
            BASELINE_PATH, expansion=not baseline.issubset(prior_entries), action="baseline change"
        )
    findings = [(path, kind, msg) for path in targets for kind, msg in scan(path)]

    # 阻塞项：① devtool 错位 ② 未标注。baseline 只保护 cleanup 的历史盘点；
    # 本次触碰到旧文件也必须补身份，不能借历史债把新修改带过去。
    blocking = 0
    seen_untagged: set[str] = set()
    for path, kind, msg in findings:
        relp = rel(path)
        if kind == "UNTAGGED":
            seen_untagged.add(relp)
        baselined = kind == "UNTAGGED" and relp in baseline and not changed_mode
        is_block = kind == "DEVTOOL-MISPLACED" or (kind == "UNTAGGED" and not baselined)
        if is_block:
            blocking += 1
        suffix = "（baseline 挂账·只减不增）" if baselined else ""
        stream = sys.stderr if is_block else sys.stdout
        stream.write(f"{'X' if is_block else '!'} [{kind}] {relp}: {msg}{suffix}\n")

    # 棘轮收紧提醒(仅全量)：在册却已修好/已删的条目应从 baseline 移除。
    stale = sorted(b for b in baseline if b not in seen_untagged) if not changed_mode else []
    for entry in stale:
        sys.stdout.write(
            f"! [BASELINE-STALE] {entry}: 已不再未标注，可从 lifecycle baseline 移除（运行 --update-baseline）\n"
        )

    if blocking:
        sys.stderr.write(
            "\n[lifecycle] 阻塞项必须修复：\n"
            "  长寿开发工具  → 移入 devtools/ + # lifecycle: devtool\n"
            "  非正式区新文件 → 补 # lifecycle: 身份标注（勿塞进 baseline；存量挂账只减不增）\n"
        )
        return 1
    if not findings and not stale:
        sys.stdout.write(
            "[lifecycle] 无身份标注债务" + ("（changed 范围）" if changed_mode else "（全量 sweep）") + "\n"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
