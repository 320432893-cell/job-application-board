#!/usr/bin/env python3
# 职责：统一承载本仓库手动检查、pre-commit、CI 复用的静态检查入口。
# 不做什么：不替代业务语义审查，不直接修改源码或自动修复检查结果。
# 允许依赖层：标准库、项目工具脚本、.ai-config 工具契约配置、外部静态检查 CLI。
# 谁不应该 import：正式业务代码、测试夹具、一次性数据处理脚本不应 import 本入口。
"""Unified static-check entrypoint for manual runs, pre-commit, and CI."""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import pathlib
import shlex
import subprocess
import sys
import time
import tomllib
from collections.abc import Sequence
from datetime import UTC, datetime

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import baseline_policy
import check_changed
import evidence_extractors as evidence
import gate_report
import tooling_registry
from project_model import load_project_model_dict
from project_model import path_matches as model_path_matches
from tooling_layout import (
    architecture_settings,
    entrypoint_files,
    expand_args,
    is_changed_ruff_path,  # noqa: F401 —— 经 check_changed.env_from(globals()) 按名字取用,ruff 看不见
    test_dirs,
)
from tooling_layout import (
    is_ignored_path as layout_ignored_path,
)

ROOT = pathlib.Path(__file__).resolve().parents[1]
REGISTRY = ROOT / ".ai-config" / "config" / "tooling.registry.toml"
PROJECT_MODEL = ROOT / ".ai-config" / "project_model.toml"
LOCAL_UV_CACHE = ROOT / ".uv-cache"
LOCAL_HOME = ROOT / ".cache" / "home"
RUN_LOG = ROOT / ".cache" / "check-runs.jsonl"  # 度量日志（.gitignore 内），每次检查记一行供 `check.py debt` 汇总
REPORT_PATH = ROOT / ".cache" / "gate-report.json"
REPORT = gate_report.GateReport()
CODE_PATH_KINDS = {"python", "source", "config", "build_contract", "script"}

BUILTIN_ITEMS = {"changed", "dependency-change-approval", "debt", "ruff-staged", "test-meta"}


def rel(path: pathlib.Path) -> str:
    return path.relative_to(ROOT).as_posix()


def load_stages() -> dict[str, list[str]]:
    return tooling_registry.stages(load_registry())


def is_ignored_path(path: pathlib.Path) -> bool:
    return layout_ignored_path(path)


def is_code_file(path: pathlib.Path) -> bool:
    return path.is_file() and is_code_name(rel(path)) and not is_ignored_path(path)


def is_code_name(name: str) -> bool:
    return evidence.path_kind(name) in CODE_PATH_KINDS


def is_source_name(name: str) -> bool:
    return evidence.path_kind(name) in {"python", "source"}


def git_changed_names(args: Sequence[str]) -> tuple[int, list[str], str]:
    proc = subprocess.run(
        ["git", "-c", "core.quotePath=false", *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    names = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    return proc.returncode, names, proc.stderr.strip()


def load_pytest_file_patterns() -> tuple[list[str], list[str]]:
    manifest = ROOT / "pyproject.toml"  # 非 Python 项目没有这份清单,缺了就用默认值,不能崩
    options = tomllib.loads(manifest.read_text(encoding="utf-8")) if manifest.is_file() else {}
    options = options.get("tool", {}).get("pytest", {}).get("ini_options", {})
    testpaths = options.get("testpaths", ["tests"])
    python_files = options.get("python_files", ["test_*.py"])
    return list(testpaths), list(python_files)


def is_direct_pytest_file(name: str) -> bool:
    testpaths, python_files = load_pytest_file_patterns()
    if not name.endswith(".py"):
        return False
    return any(
        name.startswith(f"{testpath.rstrip('/')}/")
        and any(fnmatch.fnmatch(pathlib.PurePosixPath(name).name, pattern) for pattern in python_files)
        for testpath in testpaths
    )


def collect_test_file_names() -> set[str]:
    testpaths, python_files = load_pytest_file_patterns()
    names: set[str] = set()
    for testpath in testpaths:
        base = ROOT / testpath.rstrip("/")
        if not base.exists():
            continue
        for path in base.rglob("*.py"):
            name = pathlib.PurePosixPath(rel(path)).name
            if any(fnmatch.fnmatch(name, pattern) for pattern in python_files):
                names.add(rel(path))
    return names


def collect_changed_names() -> tuple[int, list[str]]:
    commands = [
        ["diff", "--name-only", "--diff-filter=ACMRD"],
        ["diff", "--cached", "--name-only", "--diff-filter=ACMRD"],
        ["ls-files", "--others", "--exclude-standard"],
    ]
    names: list[str] = []
    for args in commands:
        rc, batch, err = git_changed_names(args)
        if rc != 0:
            print(f"[check] changed: git {' '.join(args)} failed: {err}", file=sys.stderr)
            return rc, []
        names.extend(batch)
    return 0, sorted(set(names))


def load_project_model() -> dict:
    return load_project_model_dict(PROJECT_MODEL)


def governance_mode() -> str:
    metadata = load_project_model().get("metadata", {})
    return str(metadata.get("governance_mode", "native")) if isinstance(metadata, dict) else "native"


def project_contract_patterns() -> list[str]:
    return [str(item) for item in load_project_model().get("contracts", {}).get("contract_files", [])]


def backend_contract_changed(changed_names: Sequence[str]) -> bool:
    contracts = load_project_model().get("contracts", {})
    if not isinstance(contracts, dict):
        contracts = {}

    def patterns_for(source: dict) -> list[str]:
        patterns: list[str] = []
        api = source.get("api")
        if isinstance(api, dict):
            patterns.extend(str(item) for item in api.get("source_globs", []))
            if api.get("schema_file"):
                patterns.append(str(api["schema_file"]))
        database = source.get("database")
        if isinstance(database, dict):
            patterns.extend(str(item) for item in database.get("source_globs", []))
        for health in source.get("health_checks", []):
            if isinstance(health, dict):
                patterns.extend(str(item) for item in health.get("source_globs", []))
        return patterns

    patterns = patterns_for(contracts)
    if ".ai-config/project_model.toml" in changed_names:
        proc = subprocess.run(
            ["git", "show", "HEAD:.ai-config/project_model.toml"], cwd=ROOT, text=True, capture_output=True, check=False
        )
        if proc.returncode == 0:
            try:
                prior = tomllib.loads(proc.stdout).get("contracts", {})
            except tomllib.TOMLDecodeError:
                prior = {}
            if isinstance(prior, dict):
                patterns.extend(patterns_for(prior))
    return (bool(patterns) and any(name_matches(name, patterns) for name in changed_names)) or (
        bool(patterns) and ".ai-config/project_model.toml" in changed_names
    )


def project_dependency_patterns() -> list[str]:
    return [str(item) for item in load_project_model().get("contracts", {}).get("dependency_files", [])]


def load_registry() -> dict:
    return tooling_registry.load_registry(REGISTRY)


def registry_tool_commands(command_mode: str = "entrypoint") -> dict[str, list[str]]:
    return tooling_registry.tool_commands(load_registry(), command_mode=command_mode)


def changed_when_items(event: str) -> list[str]:
    return tooling_registry.changed_when_items(event, load_registry())


def run_dependency_change_approval() -> int:
    rc, names, err = git_changed_names(["diff", "--cached", "--name-only", "--diff-filter=ACMR"])
    if rc != 0:
        print(f"[check] dependency-change-approval: git diff failed: {err}", file=sys.stderr)
        return rc
    names = [name for name in names if name_matches(name, project_dependency_patterns())]
    if not names:
        print("[check] dependency-change-approval: no staged dependency or lock changes")
        return 0
    if os.environ.get("ONCALL_ALLOW_DEPENDENCY_CHANGE") in {"1", "true", "TRUE", "yes", "YES"}:
        print("[check] dependency-change-approval: explicit approval env present")
        return 0

    print("[check] dependency-change-approval blocked staged dependency/tooling files:", file=sys.stderr)
    for name in names:
        print(f"  - {name}", file=sys.stderr)
    print(
        "[check] confirm purpose, install/download scope, lock/CI/pre-commit impact, and fallback first; "
        "then rerun with ONCALL_ALLOW_DEPENDENCY_CHANGE=1.",
        file=sys.stderr,
    )
    return 1


def run_ruff_staged() -> int:
    rc, names, err = git_changed_names(["diff", "--cached", "--name-only", "--diff-filter=ACMR", "--", "*.py"])
    if rc != 0:
        print(f"[check] ruff-staged: git diff failed: {err}", file=sys.stderr)
        return rc
    if not names:
        print("[check] ruff-staged: no staged Python files")
        return 0
    return run_command("ruff-staged", ["uv", "run", "ruff", "check", "--no-fix", "--force-exclude", *names])


def name_matches(name: str, patterns: Sequence[str]) -> bool:
    return model_path_matches(name, [str(pattern) for pattern in patterns])


def path_trigger_name_matches(name: str, patterns: Sequence[str]) -> bool:
    return tooling_registry.path_trigger_name_matches(name, patterns)


def effective_path_triggers() -> list[dict]:
    return tooling_registry.effective_path_triggers(load_registry(), is_code_name=is_code_name)


def run_path_triggers(changed_paths: Sequence[pathlib.Path]) -> int:
    status = 0
    for trigger in effective_path_triggers():
        if not any(path_trigger_name_matches(rel(path), trigger.get("paths", [])) for path in changed_paths):
            continue
        run_mode = trigger.get("run_mode", "manual")
        if run_mode == "manual":
            print(f"[check] path-trigger:{trigger['id']}: manual only")
            continue
        if run_mode == "changed":
            result = run_item(trigger["tool"])
            if result != 0 and status == 0:
                status = result
            continue
        tool_id = trigger.get("tool")
        if not tool_id:
            print(f"[check] path-trigger:{trigger['id']}: missing tool", file=sys.stderr)
            status = status or 2
            continue
        result = run_item(tool_id)
        if result != 0 and status == 0:
            status = result
    return status


def path_trigger_matches(changed_names: Sequence[str]) -> bool:
    for trigger in effective_path_triggers():
        if any(path_trigger_name_matches(name, trigger.get("paths", [])) for name in changed_names):
            return True
    return False


def run_registered_item(item: str) -> int:
    if item not in registry_tool_commands():
        print(f"[check] changed:{item}: skipped, tool not registered")
        return 0
    return run_item(item)


def run_changed() -> int:
    return check_changed.run(check_changed.env_from(globals()))


def run_test_meta() -> int:
    # 新增/改动测试阻塞，存量测试只 WARNING，避免历史 backlog 淹没新增 oracle 质量。
    rc, changed_names = collect_changed_names()
    if rc != 0:
        return rc
    changed = set(changed_names)
    test_files = sorted(collect_test_file_names())
    required_markers = (
        ("生命周期", "缺生命周期说明（T0 删除条件或持久维护）"),
        ("覆盖的业务场景", "缺覆盖的业务场景说明"),
        ("依赖的服务/环境", "缺依赖的服务/环境说明"),
        ("运行方式", "缺运行方式说明"),
    )
    oracle_markers = ("用时", "耗时", "elapsed", "duration", "期望:", "实际:", "[ENV_ERROR]", "[LOGIC_ERROR]")
    blocking: list[str] = []
    warnings: list[str] = []
    for name in test_files:
        path = ROOT / name
        text = path.read_text(encoding="utf-8", errors="ignore")
        missing = [message for marker, message in required_markers if marker not in text]
        if not any(marker in text for marker in oracle_markers):
            missing.append("缺 oracle 输出形状（用时/期望实际/ENV_ERROR/LOGIC_ERROR 至少一类）")
        if not missing:
            continue
        target = blocking if name in changed else warnings
        target.extend(f"{name}: {message}" for message in missing)

    if warnings:
        print("[check] test-meta WARNING（存量测试不阻塞）：", file=sys.stderr)
        for warning in warnings:
            print(f"  - {warning}", file=sys.stderr)
    if blocking:
        print("[check] test-meta failed（本次新增/改动测试必须可复现）：", file=sys.stderr)
        for issue in blocking:
            print(f"  - {issue}", file=sys.stderr)
        print(
            "\n在测试文件顶部添加：\n"
            "  # 生命周期：T0 一次性（删除条件：XXX）/ 持久维护\n"
            "  # 覆盖的业务场景：\n"
            "  # 依赖的服务/环境：\n"
            "  # 运行方式：\n"
            "并让输出或断言信息包含用时、期望/实际或 ENV/LOGIC 错误分类。",
            file=sys.stderr,
        )
        return 1
    if warnings:
        return 0
    print("[check] test-meta: 测试文件均声明复现元信息和 oracle 输出形状")
    return 0


def log_run(label: str, returncode: int, seconds: float) -> None:
    # 度量：把每次检查的 过/挂/耗时 记一行 JSONL，供 `check.py debt` 汇总通过率。
    # best-effort：日志失败绝不影响检查本身（检查是门禁，度量是旁路）。
    try:
        RUN_LOG.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "ts": datetime.now(UTC).isoformat(timespec="seconds"),
            "label": label,
            "ok": returncode == 0,
            "ms": round(seconds * 1000),
        }
        with RUN_LOG.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        pass


def run_command(label: str, command: Sequence[str] | str) -> int:
    print(f"[check] {label}", flush=True)
    env = os.environ.copy()
    env["HOME"] = str(LOCAL_HOME)
    env["UV_CACHE_DIR"] = str(LOCAL_UV_CACHE)
    if label == "pytest" or label.startswith("changed:pytest"):
        env["DEBUG"] = "false"
    args = expand_args(shlex.split(command) if isinstance(command, str) else list(command))
    start = time.monotonic()
    # tee 而不是 capture_output:边流边收。捕获是为了报告,但 pytest 这类跑几十秒的
    # 工具如果全程无输出、结束才一次吐出来,交互体验会明显变差。
    proc = subprocess.Popen(args, cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    captured: list[str] = []
    for line in proc.stdout or []:
        sys.stdout.write(line)
        captured.append(line)
    sys.stdout.flush()
    returncode, seconds = proc.wait(), time.monotonic() - start
    log_run(label, returncode, seconds)
    REPORT.record(label, returncode, seconds, "".join(captured))
    return returncode


def run_item(item: str, command_mode: str = "entrypoint") -> int:
    registry = load_registry()
    registry_commands = registry_tool_commands(command_mode)
    tool = tooling_registry.tool_by_id(item, registry)
    if not tooling_registry.applies_to_languages(tool, tooling_registry.declared_language_ids(load_project_model())):
        needs = ", ".join(str(x) for x in tool.get("languages", []))
        print(f"[check] {item}: skipped, 本项目未声明 {needs}(在 project_model 的 [[languages]] 里声明才会跑)")
        REPORT.record(item, 0, 0.0, skipped=True, reason=f"未声明语言 {needs}")
        return 0
    if missing := tooling_registry.missing_required_paths(item, ROOT, registry):
        blocking = tool.get("enforcement") == "blocking"
        label = "missing required paths" if blocking else "skipped, required paths absent"
        print(f"[check] {item}: {label}: {', '.join(missing)}", file=sys.stderr if blocking else sys.stdout)
        REPORT.record(item, 1 if blocking else 0, 0.0, skipped=not blocking, reason=f"缺必需路径: {', '.join(missing)}")
        return 1 if blocking else 0
    if command_mode == "ci" and item in registry_commands:
        return run_many((item, command) for command in registry_commands[item])
    if item == "changed":
        return run_changed()
    if item == "test-meta":
        return run_test_meta()
    if item == "debt":
        return run_debt()
    if item == "dependency-change-approval":
        return run_dependency_change_approval()
    if item == "ruff-staged":
        return run_ruff_staged()
    if item in registry_commands:
        status = 0
        for index, command in enumerate(registry_commands[item], start=1):
            label = item if len(registry_commands[item]) == 1 else f"{item}:{index}"
            status = run_command(label, command) or status
        return status
    print(f"[check] unknown item: {item}", file=sys.stderr)
    return 2


def run_many(items: Sequence[tuple[str, Sequence[str] | str]] | list[tuple[str, Sequence[str] | str]]) -> int:
    status = 0
    for label, command in items:
        result = run_command(label, command)
        if result != 0 and status == 0:
            status = result
    return status


def print_pass_rates(limit: int = 200) -> None:
    # 从度量日志汇总每个检查的通过率（近 limit 条运行），低通过率=AI 在这类检查上反复返工。
    if not RUN_LOG.exists():
        print("  检查通过率: 暂无日志（跑几次 check.py 后再看）")
        return
    lines = RUN_LOG.read_text(encoding="utf-8").splitlines()[-limit:]
    stats: dict[str, list[bool]] = {}
    active_labels = tooling_registry.tool_ids(load_registry())
    for line in lines:
        try:
            record = json.loads(line)
        except ValueError:
            continue
        label = str(record.get("label"))
        if label.split(":", maxsplit=1)[0] not in active_labels:
            continue
        stats.setdefault(label, []).append(bool(record.get("ok")))
    if not stats:
        print("  检查通过率: 日志为空")
        return
    print(f"  检查通过率（近 {len(lines)} 条运行，低=反复返工的检查）:")
    for label in sorted(stats):
        runs = stats[label]
        rate = round(100 * sum(runs) / len(runs))
        print(f"    {label:26} {rate:3d}%  ({sum(runs)}/{len(runs)})")


# 放行登记里"清除条件"禁用的含糊词：它们让 reopen_when 不可判定，等于无限期拖。


def _debt_registrations(registry: dict) -> list[tuple[str, dict]]:
    # 放行登记 = relaxed 的工具 + relaxed 的 semgrep ruleset（都属"green-now/ratchet-later"的欠债）。
    items: list[tuple[str, dict]] = [
        (f"tool:{tool['id']}", tool) for tool in registry.get("tools", []) if tool.get("relaxed")
    ]
    items.extend(
        (f"semgrep:{rs.get('path', '?')}", rs) for rs in registry.get("semgrep_rulesets", []) if rs.get("relaxed")
    )
    return items


def run_debt() -> int:
    # 放行登记校验（门禁）+ 健康度汇总。把"放行机制=欠债登记"从纸面升成机器闸：
    # 每条 relaxed 放行 MUST 有 ①原因(relaxed_reason) ②可判定的清除条件(reopen_when，禁含糊词)，否则非0。
    registry = tomllib.loads(REGISTRY.read_text(encoding="utf-8"))
    registrations = _debt_registrations(registry)
    violations: list[str] = []
    for name, item in registrations:
        reason = (item.get("relaxed_reason") or "").strip()
        clear = (item.get("reopen_when") or "").strip()
        if not reason:
            violations.append(f"{name}: 缺 relaxed_reason（放行必须写原因）")
        if not clear:
            violations.append(f"{name}: 缺 reopen_when（放行必须写可判定的清除条件 + 目标时机）")
        elif hits := baseline_policy.vague_hits(clear):
            violations.append(f"{name}: reopen_when 含糊词 {hits}（须给可判定条件，非『暂时/以后/待定』）")

    print(f"[debt] 放行登记 {len(registrations)} 条，校验原因 + 可判定清除条件…", flush=True)

    print_pass_rates()

    if violations:
        sys.stderr.write("\n[debt] 放行登记校验失败：\n")
        for v in violations:
            sys.stderr.write(f"  X {v}\n")
        sys.stderr.write("  放行=欠债登记：每条 relaxed MUST 带 原因 + 可判定清除条件(reopen_when)，禁裸词。\n")
        return 1
    print(f"[debt] 放行登记校验通过（{len(registrations)} 条均有原因 + 可判定清除条件）。")
    return 0


def _single_layout_root(label: str, values: Sequence[str]) -> str:
    existing = [value for value in values if value]
    if len(existing) == 1:
        return existing[0]
    raise ValueError(f"{label} 需要恰好一个目录；当前是 {existing or '空'}，请先在 project_model 明确生成目标")


def _module_scaffold(name: str, feature_root: str, api_filename: str, test_root: str) -> dict[str, str]:
    header = (
        f"# 职责：TODO {name} 功能切片。\n"
        "# 不做什么：不承载应用入口、不直接耦合其他 feature 的实现。\n"
        f"# 允许依赖层：本 feature；跨 feature 仅导入 {feature_root}/<feature>/{api_filename}。\n"
        f"# 谁不应该 import：{test_root}/ 与基础设施不得反向依赖本功能实现。\n"
    )
    return {
        api_filename: header + f'"""{name} 对外窄接口。"""\n\nfrom __future__ import annotations\n',
        "models.py": header + f'"""{name} 的领域数据。"""\n\nfrom __future__ import annotations\n',
        "use_cases.py": header + f'"""{name} 的业务用例。"""\n\nfrom __future__ import annotations\n',
        "ports.py": header + f'"""{name} 对基础设施的依赖接口。"""\n\nfrom __future__ import annotations\n',
        "__init__.py": f'"""{name} feature slice."""\n',
    }


def _test_scaffold(name: str, test_root: str) -> str:
    # 生成：吐出带 test-meta 头 + oracle 标记的回归测试骨架，默认 skip 不污染套件，填完去掉 skip。
    return (
        "# 生命周期：持久维护\n"
        f"# 覆盖的业务场景：TODO {name} 验证什么业务行为\n"
        "# 依赖的服务/环境：TODO 本地 Python / 需要的服务\n"
        f"# 运行方式：uv run pytest {test_root}/test_{name}.py\n"
        "# oracle 输出形状：断言失败给出 期望/实际；pytest 汇总用时。\n"
        f'"""TODO: {name} 的回归测试。"""\n\n'
        "import pytest\n\n\n"
        f'@pytest.mark.skip(reason="TODO: 实现 {name} 业务场景测试")\n'
        f"def test_{name}_placeholder() -> None:\n"
        '    raise AssertionError("期望: TODO | 实际: 尚未实现")\n'
    )


def _entrypoint_scaffold(name: str) -> str:
    return (
        f"# 职责：{name} 应用入口，仅负责组装和启动。\n"
        "# 不做什么：不承载业务规则、不被 feature 或 platform 反向导入。\n"
        "# 允许依赖层：features 的 api.py、platform。\n"
        "# 谁不应该 import：features 内部实现、测试不应依赖此启动副作用。\n"
        f'"""{name} application entrypoint."""\n\n'
        "from __future__ import annotations\n\n\n"
        "def main() -> None:\n"
        '    """Assemble the application and start its delivery mechanism."""\n'
        '    raise NotImplementedError("TODO: assemble application")\n\n\n'
        'if __name__ == "__main__":\n'
        "    main()\n"
    )


def _ensure_feature_local_api_filename(api_filename: str) -> None:
    # 从 run_new 的 try 块里抽出 raise(TRY301)：判定条件与错误消息一字不动，仍由同一个 except ValueError 捕获。
    if pathlib.PurePosixPath(api_filename).name != api_filename or not api_filename.endswith(".py"):
        raise ValueError("architecture.cross_feature_entrypoint 必须是 feature 内的 Python 文件名")


def run_new(rest: list[str]) -> int:
    usage = "用法: uv run python tools/check.py new <feature|entrypoint|test> <name>"
    try:
        kind, name = rest
    except ValueError:
        print(usage, file=sys.stderr)
        return 2
    if kind not in {"feature", "entrypoint", "test"} or not name.isidentifier():
        print(usage, file=sys.stderr)
        return 2
    try:
        test_root = _single_layout_root("test_dirs", test_dirs())
        feature_root, api_filename = architecture_settings()
        _ensure_feature_local_api_filename(api_filename)
        entrypoint_root = _single_layout_root(
            "entrypoint_files", [str(pathlib.PurePosixPath(value).parent) for value in entrypoint_files()]
        )
    except ValueError as exc:
        print(f"[new] {exc}", file=sys.stderr)
        return 2
    targets: list[tuple[pathlib.Path, str]] = []
    if kind == "test":
        targets.append(
            (ROOT / test_root / "features" / f"test_{name}.py", _test_scaffold(name, f"{test_root}/features"))
        )
    elif kind == "entrypoint":
        targets.append((ROOT / entrypoint_root / f"{name}.py", _entrypoint_scaffold(name)))
    else:
        targets.extend(
            (ROOT / feature_root / name / filename, content)
            for filename, content in _module_scaffold(name, feature_root, api_filename, test_root).items()
        )
        targets.append(
            (ROOT / test_root / "features" / f"test_{name}.py", _test_scaffold(name, f"{test_root}/features"))
        )
    for path, _ in targets:
        if path.exists():
            print(f"[new] 已存在，拒绝覆盖：{path.relative_to(ROOT)}", file=sys.stderr)
            return 1
    for path, content in targets:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        print(f"[new] 生成 {path.relative_to(ROOT)}")
    print(f"[new] 已生成 feature 切片或入口；跨 feature 只经 {api_filename}。")
    return 0


def run_stage(stage: str, stages: dict[str, list[str]]) -> int:
    status = 0
    command_mode, registry = ("ci" if stage == "ci" else "entrypoint"), load_registry()
    for item in stages[stage]:
        tool = tooling_registry.tool_by_id(item, registry)
        result = run_item(item, command_mode)
        nonblocking = command_mode != "ci" and (
            tool.get("relaxed") or tool.get("enforcement") in {"advisory", "material"}
        )
        if result != 0 and status == 0 and not nonblocking:
            status = result
    return status


def run_all(stages: dict[str, list[str]]) -> int:
    """所有阶段的工具去重跑一遍:阶段之间工具不重叠,只跑 quick 看不见 cleanup 的问题。
    advisory/material/relaxed 红了不改退出码,判据与 run_stage 一致。"""
    registry, seen = load_registry(), []
    for items in stages.values():
        seen.extend(item for item in items if item not in seen)
    status = 0
    for item in seen:
        result = run_item(item)
        tool = tooling_registry.tool_by_id(item, registry)
        soft = tool.get("relaxed") or tool.get("enforcement") in {"advisory", "material"}
        if result != 0 and status == 0 and not soft:
            status = result
    return status


def print_dry_run(stage: str, stages: dict[str, list[str]]) -> None:
    for item in stages[stage]:
        print(item)


def print_list(stages: dict[str, list[str]]) -> None:
    print("Stages:")
    for stage, items in stages.items():
        print(f"  {stage}: {', '.join(items)}")
    print("Registry tools:")
    for name, commands in registry_tool_commands().items():
        print(f"  {name}: {' && '.join(commands)}")
    print("Builtin items:")
    for name in sorted(BUILTIN_ITEMS):
        print(f"  {name}")


def main() -> int:
    stages = load_stages()
    registry_items = registry_tool_commands()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="print the items a stage would run")
    parser.add_argument("--report", nargs="?", const=str(REPORT_PATH), help="把这次运行写成机器可读快照")
    parser.add_argument(
        "target",
        nargs="?",
        default="quick",
        choices=[*stages, *registry_items, *BUILTIN_ITEMS, "list", "new", "all"],
    )
    parser.add_argument("rest", nargs="*", help="`new <kind> <name>` 的额外参数")
    args = parser.parse_args()

    os.chdir(ROOT)
    if args.target == "list":
        print_list(stages)
        return 0
    if governance_mode() == "foreign":
        print(
            "[check] foreign 项目不运行工程闸；请使用 ai-global/template/audit_legacy.sh 生成只读维护材料。",
            file=sys.stderr,
        )
        return 2
    if args.target == "new":
        return run_new(args.rest)
    if args.dry_run:
        if args.target not in stages:
            print("[check] --dry-run only accepts a stage target", file=sys.stderr)
            return 2
        print_dry_run(args.target, stages)
        return 0
    REPORT.target = args.target
    if args.target == "all":
        status = run_all(stages)
    else:
        status = run_stage(args.target, stages) if args.target in stages else run_item(args.target)
    if args.report:
        gate_report.finalize(REPORT, pathlib.Path(args.report))
    return status


if __name__ == "__main__":
    sys.exit(main())
