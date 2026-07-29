#!/usr/bin/env python3
# 职责：执行 project_model 显式声明的后端 API、迁移和健康契约。
# 不做什么：不猜框架、不启动服务、不连接开发数据库、不更新正式契约文件。
# 允许依赖层：标准库、project_model、用户声明的命令。
# 谁不应该 import：业务代码、应用入口、测试夹具不应 import 本工具。
"""Run optional backend contracts declared by ``project_model.toml``."""

from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
import sys
import tempfile
import tomllib
from collections.abc import Iterable
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from project_model import Contracts, ProjectModel, load_project_model, path_matches

ROOT = Path(__file__).resolve().parents[1]


def changed_names(root: Path) -> set[str]:
    names: set[str] = set()
    for args in (
        ["diff", "--no-renames", "--name-only", "--diff-filter=ACMRD"],
        ["diff", "--cached", "--no-renames", "--name-only", "--diff-filter=ACMRD"],
    ):
        proc = subprocess.run(["git", *args], cwd=root, text=True, capture_output=True, check=False)
        if proc.returncode == 0:
            names.update(proc.stdout.splitlines())
    untracked = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard"], cwd=root, text=True, capture_output=True, check=False
    )
    if untracked.returncode == 0:
        names.update(untracked.stdout.splitlines())
    return {name for name in names if name}


def should_run(scope: str, globs: list[str], changed: set[str]) -> bool:
    return scope == "full" or ".ai-config/project_model.toml" in changed or any(path_matches(name, globs) for name in changed)


def run_command(
    label: str, command: str, *, timeout_seconds: int = 120, capture_output: bool = False
) -> subprocess.CompletedProcess[str] | None:
    print(f"[backend-contracts] {label}")
    try:
        return subprocess.run(
            shlex.split(command), cwd=ROOT, text=True, capture_output=capture_output, check=False, timeout=timeout_seconds
        )
    except subprocess.TimeoutExpired:
        print(f"[backend-contracts] {label}: timed out after {timeout_seconds}s", file=sys.stderr)
        return None


def canonical_json(value: object, key: str = "") -> object:
    if isinstance(value, dict):
        return {name: canonical_json(item, name) for name, item in sorted(value.items())}
    if isinstance(value, list):
        items = [canonical_json(item) for item in value]
        return sorted(items) if key == "required" else items
    return value


def normalized_json(text: str, label: str) -> str | None:
    try:
        return json.dumps(canonical_json(json.loads(text)), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except json.JSONDecodeError as exc:
        print(f"[backend-contracts] {label}: expected JSON, got invalid output: {exc}", file=sys.stderr)
        return None


def head_text(path: str) -> str | None:
    proc = subprocess.run(["git", "show", f"HEAD:{path}"], cwd=ROOT, text=True, capture_output=True, check=False)
    if proc.returncode != 0:
        return None
    return proc.stdout


def head_contracts() -> dict:
    proc = subprocess.run(
        ["git", "show", "HEAD:.ai-config/project_model.toml"], cwd=ROOT, text=True, capture_output=True, check=False
    )
    if proc.returncode != 0:
        return {}
    return as_mapping(tomllib.loads(proc.stdout).get("contracts"))


def declared_contracts(contracts: dict) -> bool:
    return bool(contracts.get("api") or contracts.get("database") or contracts.get("health_checks"))


def _api_regressions(previous: dict, current: Contracts) -> list[str]:
    current_api = current.api
    previous_api = as_mapping(previous.get("api"))
    regressions: list[str] = []
    if previous_api and current_api is None:
        regressions.append("contracts.api was removed")
    if previous_api and current_api and set(previous_api.get("source_globs", [])) - set(current_api.source_globs):
        regressions.append("contracts.api.source_globs was narrowed")
    if previous_api and current_api:
        for field in ("schema_file", "export_command", "compatibility_command", "timeout_seconds"):
            previous_value = previous_api.get(field, 120) if field == "timeout_seconds" else previous_api.get(field)
            if previous_value != getattr(current_api, field):
                regressions.append(f"contracts.api.{field} changed")
    return regressions


def _database_regressions(previous: dict, current: Contracts) -> list[str]:
    regressions: list[str] = []
    previous_database = as_mapping(previous.get("database"))
    if previous_database and current.database is None:
        regressions.append("contracts.database was removed")
    if previous_database and current.database and set(previous_database.get("source_globs", [])) - set(current.database.source_globs):
        regressions.append("contracts.database.source_globs was narrowed")
    if previous_database and current.database:
        for field in ("kind", "check_command", "heads_command", "isolated_upgrade_command", "timeout_seconds"):
            previous_value = previous_database.get(field, 120) if field == "timeout_seconds" else previous_database.get(field)
            if previous_value != getattr(current.database, field):
                regressions.append(f"contracts.database.{field} changed")
    return regressions


def _health_regressions(previous: dict, current: Contracts) -> list[str]:
    regressions: list[str] = []
    previous_health = {str(item.get("id")): item for item in previous.get("health_checks", []) if isinstance(item, dict)}
    current_health = {check.id: check for check in current.health_checks}
    for check_id, old in previous_health.items():
        new = current_health.get(check_id)
        if new is None:
            regressions.append(f"contracts.health_checks.{check_id} was removed")
        elif set(old.get("source_globs", [])) - set(new.source_globs):
            regressions.append(f"contracts.health_checks.{check_id}.source_globs was narrowed")
        else:
            for field in ("command", "timeout_seconds"):
                previous_value = old.get(field, 120) if field == "timeout_seconds" else old.get(field)
                if previous_value != getattr(new, field):
                    regressions.append(f"contracts.health_checks.{check_id}.{field} changed")
    return regressions


def contract_regressions(model: ProjectModel) -> list[str]:
    # 三段按 api → database → health 顺序拼接，与拆分前 append 的顺序逐字一致。
    previous, current = head_contracts(), model.contracts
    return [
        *_api_regressions(previous, current),
        *_database_regressions(previous, current),
        *_health_regressions(previous, current),
    ]


def as_mapping(value: object) -> dict:
    return value if isinstance(value, dict) else {}


def check_api(model: ProjectModel, scope: str, changed: set[str]) -> int:
    contract = model.contracts.api
    if contract is None or not should_run(scope, [*contract.source_globs, contract.schema_file], changed):
        return 0
    snapshot = ROOT / contract.schema_file
    if not snapshot.is_file():
        print(f"[backend-contracts] api: schema_file missing: {contract.schema_file}", file=sys.stderr)
        return 1
    exported = run_command("api export", contract.export_command, timeout_seconds=getattr(contract, "timeout_seconds", 120), capture_output=True)
    if exported is None:
        return 1
    if exported.returncode != 0:
        print(exported.stderr, file=sys.stderr, end="")
        return exported.returncode
    actual = normalized_json(exported.stdout, "api export")
    expected = normalized_json(snapshot.read_text(encoding="utf-8"), "api schema_file")
    if actual is None or expected is None:
        return 1
    if actual != expected:
        print(
            "[backend-contracts] api: exported schema differs from the committed schema_file; "
            "review the API change and update the snapshot explicitly",
            file=sys.stderr,
        )
        return 1
    previous_api = as_mapping(head_contracts().get("api"))
    baseline = head_text(str(previous_api.get("schema_file") or contract.schema_file))
    if baseline is not None:
        cache_dir = ROOT / ".cache"
        cache_dir.mkdir(exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".json", prefix="api-baseline-", dir=cache_dir) as handle:
            handle.write(baseline)
            handle.flush()
            try:
                command = contract.compatibility_command.format(baseline=handle.name, current=str(snapshot))
            except KeyError as exc:
                print(f"[backend-contracts] api: unknown compatibility placeholder: {exc}", file=sys.stderr)
                return 1
            compatibility = run_command("api compatibility", command, timeout_seconds=getattr(contract, "timeout_seconds", 120))
            if compatibility is None:
                return 1
            if compatibility.returncode != 0:
                return compatibility.returncode
    return 0


def check_database(model: ProjectModel, scope: str, changed: set[str]) -> int:
    contract = model.contracts.database
    if contract is None or not should_run(scope, contract.source_globs, changed):
        return 0
    check = run_command("database check", contract.check_command, timeout_seconds=getattr(contract, "timeout_seconds", 120), capture_output=True)
    if check is None:
        return 1
    if check.returncode != 0:
        print(check.stderr, file=sys.stderr, end="")
        return check.returncode
    heads = run_command("database heads", contract.heads_command, timeout_seconds=getattr(contract, "timeout_seconds", 120), capture_output=True)
    if heads is None:
        return 1
    if heads.returncode != 0:
        print(heads.stderr, file=sys.stderr, end="")
        return heads.returncode
    head_count = sum(
        bool(re.fullmatch(r"[A-Za-z0-9_]+(?:\s+\([^)]+\))*\s+\(head\)", line.strip(), flags=re.IGNORECASE))
        for line in heads.stdout.splitlines()
    )
    if head_count != 1:
        print(f"[backend-contracts] database: expected exactly one Alembic head, got {head_count}", file=sys.stderr)
        return 1
    upgrade = run_command("database isolated upgrade", contract.isolated_upgrade_command, timeout_seconds=getattr(contract, "timeout_seconds", 120))
    return 1 if upgrade is None else upgrade.returncode


def check_health(model: ProjectModel, scope: str, changed: set[str]) -> int:
    status = 0
    for contract in model.contracts.health_checks:
        if should_run(scope, contract.source_globs, changed):
            result = run_command(f"health {contract.id}", contract.command, timeout_seconds=getattr(contract, "timeout_seconds", 120))
            status = (1 if result is None else result.returncode) or status
    return status


def run(scope: str, model: ProjectModel, *, changed: set[str] | None = None) -> int:
    prior = head_contracts()
    if not declared_contracts(prior) and model.contracts.api is None and model.contracts.database is None and not model.contracts.health_checks:
        print("[backend-contracts] no backend contracts declared")
        return 0
    current_changed = changed if changed is not None else changed_names(ROOT)
    status = 0
    regressions = contract_regressions(model)
    if regressions:
        print("[backend-contracts] contract coverage regression since HEAD:", file=sys.stderr)
        for regression in regressions:
            print(f"  - {regression}", file=sys.stderr)
        status = 1
    for check in (check_api, check_database, check_health):
        result = check(model, scope, current_changed)
        if result != 0 and status == 0:
            status = result
    return status


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scope", choices=("changed", "full"), required=True)
    args = parser.parse_args(argv)
    return run(args.scope, load_project_model())


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
