#!/usr/bin/env python3
# 职责：唯一读取并校验 .ai-config/project_model.toml，提供模型和通用路径匹配语义。
# 不做什么：不扫描仓库、不运行检查、不解释 registry。
# 允许依赖层：标准库、pydantic。
# 谁不应该 import：正式业务代码、测试夹具、应用入口不应 import 本工具层模块。
"""Strict project model loader shared by repository tooling."""

from __future__ import annotations

import tomllib
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH = ROOT / ".ai-config" / "project_model.toml"
# managed 基线路径至少要有 "config/<name>.baseline.json" 两段，否则说明它没落在 .ai-config/config 下面。
MANAGED_BASELINE_MIN_PATH_PARTS = 2


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ZoneSelector(StrictModel):
    kind: Literal["dir", "file", "glob", "exclude"] = "dir"
    value: str
    priority: int = 0
    reason: str = ""
    revisit_when: str = ""


class Zone(StrictModel):
    id: str
    description: str = ""
    traits: list[str] = Field(default_factory=list)
    dirs: list[str] = Field(default_factory=list)
    files: list[str] = Field(default_factory=list)
    selectors: list[ZoneSelector] = Field(default_factory=list)
    import_roots: list[str] = Field(default_factory=list)
    may_import_zones: list[str] = Field(default_factory=list)
    requires_reason: bool = False
    revisit_required: bool = False
    reason: str = ""
    revisit_when: str = ""


class Metadata(StrictModel):
    version: int
    name: str = ""
    governance_mode: Literal["native", "managed", "foreign"] = "native"
    architecture: Literal["modular-monolith", "external"] = "modular-monolith"


class Language(StrictModel):
    """一门语言的源码范围。suffixes = "什么算源码"(走目录时的粗筛),include_globs = "其中哪些在管辖内"。"""

    id: str
    suffixes: list[str] = Field(default_factory=list)
    include_globs: list[str] = Field(default_factory=list)


class IgnoreConfig(StrictModel):
    patterns: list[str] = Field(default_factory=list)


class WorkspaceConfig(StrictModel):
    member_roots: list[str] = Field(default_factory=list)
    exclude_member_roots: bool = True


class GovernanceConfig(StrictModel):
    managed_baselines: list[str] = Field(default_factory=list)
    inventory_violation_baseline: str = ""


def managed_baseline_path(value: str) -> str:
    """把声明里的 managed baseline 路径转成**仓库相对**路径。

    声明里写的是 .ai-config 相对(如 `config/x.baseline.json`),因为 adopt_managed.sh
    按 `校准包/.ai-config/<值>` 找文件。但要读它就得补上 `.ai-config/` 前缀——
    inventory 的两处和 baseline_policy 的一处都曾漏了,导致 managed 档读错位置、
    且"这条基线有没有登记"的比对永远不成立。只在 managed 档触发,所以一直没被跑到。
    """
    return f".ai-config/{value}"


def is_safe_managed_baseline_path(value: str) -> bool:
    path = PurePosixPath(value)
    return (
        bool(value)
        and not path.is_absolute()
        and ".." not in path.parts
        and len(path.parts) >= MANAGED_BASELINE_MIN_PATH_PARTS
        # 值是 **.ai-config 相对**的(adopt_managed.sh 按 calibration/.ai-config/<值> 找文件),
        # 所以这里判 parts[0] == "config"。要拿它去读文件必须先过 managed_baseline_path()
        # 转成仓库相对——三个消费点曾漏了这一步,详见该函数注释。
        and path.parts[0] == "config"
        and path.name.endswith(".baseline.json")
    )


def is_safe_repository_path(value: str) -> bool:
    path = PurePosixPath(value)
    return bool(value) and not path.is_absolute() and ".." not in path.parts


class ArchitectureConfig(StrictModel):
    feature_root: str = "src/project/features"
    cross_feature_entrypoint: str = "api.py"


class ApiContract(StrictModel):
    schema_file: str
    export_command: str
    compatibility_command: str
    source_globs: list[str] = Field(default_factory=list)
    timeout_seconds: int = 120


class DatabaseContract(StrictModel):
    kind: Literal["alembic"]
    source_globs: list[str] = Field(default_factory=list)
    check_command: str
    heads_command: str
    isolated_upgrade_command: str
    timeout_seconds: int = 120


class HealthCheck(StrictModel):
    id: str
    source_globs: list[str] = Field(default_factory=list)
    command: str
    timeout_seconds: int = 120


class Contracts(StrictModel):
    contract_files: list[str] = Field(default_factory=list)
    dependency_files: list[str] = Field(default_factory=list)
    api: ApiContract | None = None
    database: DatabaseContract | None = None
    health_checks: list[HealthCheck] = Field(default_factory=list)


class RiskRule(StrictModel):
    id: str
    condition: str
    severity: str = "review"
    zone_trait: str = ""
    source_trait: str = ""
    companion_trait: str = ""
    violation_kind: str = ""


class ToolingConfig(StrictModel):
    fixed_quality_traits: list[str] = Field(default_factory=list)
    formal_traits: list[str] = Field(default_factory=list)
    support_traits: list[str] = Field(default_factory=list)
    test_traits: list[str] = Field(default_factory=list)
    informal_traits: list[str] = Field(default_factory=list)
    inactive_traits: list[str] = Field(default_factory=list)
    package_root_traits: list[str] = Field(default_factory=list)
    entrypoint_traits: list[str] = Field(default_factory=list)
    devtools_dir: str = ""


class AgentReview(StrictModel):
    id: str
    title: str = ""
    stages: list[Literal["stage", "cleanup"]]
    focus: list[str]
    questions: list[str]


class EntryPoint(StrictModel):
    id: str
    kind: Literal["cli", "gui", "web", "worker", "script", "test", "other"] = "script"
    member: str = "root"
    file: str = ""
    module: str = ""
    callable: str = ""
    command: str = ""
    cwd: str = "."
    owner: str = ""
    public_surface: list[str] = Field(default_factory=list)
    allowed_zones: list[str] = Field(default_factory=list)
    evidence: str = ""


class ProjectMember(StrictModel):
    id: str
    root: str
    description: str = ""
    exclude_from_parent: bool = False
    source_roots: list[str] = Field(default_factory=list)
    test_roots: list[str] = Field(default_factory=list)
    package_roots: list[str] = Field(default_factory=list)
    default_zones: list[str] = Field(default_factory=list)
    contract_files: list[str] = Field(default_factory=list)
    dependency_files: list[str] = Field(default_factory=list)
    entrypoints: list[EntryPoint] = Field(default_factory=list)


class ProjectModel(StrictModel):
    metadata: Metadata
    languages: list[Language] = Field(
        default_factory=lambda: [Language(id="python", suffixes=[".py"], include_globs=["**/*.py"])]
    )
    ignore: IgnoreConfig
    workspace: WorkspaceConfig = Field(default_factory=WorkspaceConfig)
    governance: GovernanceConfig = Field(default_factory=GovernanceConfig)
    architecture: ArchitectureConfig = Field(default_factory=ArchitectureConfig)
    members: list[ProjectMember] = Field(default_factory=list)
    entrypoints: list[EntryPoint] = Field(default_factory=list)
    tooling: ToolingConfig = Field(default_factory=ToolingConfig)
    zones: list[Zone]
    contracts: Contracts = Field(default_factory=Contracts)
    risk_rules: list[RiskRule] = Field(default_factory=list)
    agent_reviews: list[AgentReview] = Field(default_factory=list)

    @field_validator("zones")
    @classmethod
    def unique_zones(cls, zones: list[Zone]) -> list[Zone]:
        ids = [zone.id for zone in zones]
        if len(ids) != len(set(ids)):
            raise ValueError("zone ids must be unique")
        return zones

    @model_validator(mode="after")
    def validate_zone_references(self) -> ProjectModel:
        """按原顺序拼接各段校验错误；拆分只为控制单函数体量，错误文案与顺序不变。"""
        zone_ids = [zone.id for zone in self.zones]
        ids = set(zone_ids)
        entrypoint_ids: list[str] = []
        excluded_member_roots: list[str] = []
        errors: list[str] = []
        errors.extend(_governance_mode_errors(self))
        errors.extend(_architecture_shape_errors(self))
        errors.extend(_managed_governance_errors(self))
        duplicated = sorted({zone_id for zone_id in zone_ids if zone_ids.count(zone_id) > 1})
        errors.extend(f"zone id duplicated: {zone_id}" for zone_id in duplicated)
        errors.extend(_zone_reference_errors(self, ids))
        errors.extend(_feature_root_coverage_errors(self))
        errors.extend(_member_errors(self, ids, entrypoint_ids, excluded_member_roots))
        errors.extend(_root_entrypoint_errors(self, ids, entrypoint_ids))
        duplicated_entrypoints = sorted({item for item in entrypoint_ids if entrypoint_ids.count(item) > 1})
        errors.extend(f"entrypoint id duplicated: {entrypoint_id}" for entrypoint_id in duplicated_entrypoints)
        health_ids = [check.id for check in self.contracts.health_checks]
        errors.extend(
            f"contracts.health_checks id duplicated: {check_id}"
            for check_id in sorted({item for item in health_ids if health_ids.count(item) > 1})
        )
        errors.extend(_api_contract_errors(self))
        errors.extend(_database_contract_errors(self))
        errors.extend(_health_check_errors(self))
        legacy_member_roots = list(self.workspace.member_roots)
        if (
            legacy_member_roots
            and excluded_member_roots
            and sorted(legacy_member_roots) != sorted(excluded_member_roots)
        ):
            errors.append(
                "workspace.member_roots must match members.exclude_from_parent roots during migration"
            )
        if legacy_member_roots and self.members and not excluded_member_roots:
            errors.append("workspace.member_roots is legacy; declare those roots as members with exclude_from_parent=true")
        if errors:
            raise ValueError("; ".join(errors))
        return self


def _governance_mode_errors(model: ProjectModel) -> list[str]:
    errors: list[str] = []
    if model.metadata.governance_mode == "foreign" and model.metadata.architecture != "external":
        errors.append("foreign governance_mode requires metadata.architecture = `external`")
    if model.metadata.governance_mode != "foreign" and model.metadata.architecture == "external":
        errors.append("native/managed governance_mode cannot use metadata.architecture = `external`")
    return errors


def _architecture_shape_errors(model: ProjectModel) -> list[str]:
    errors: list[str] = []
    if model.metadata.governance_mode != "foreign":
        feature_root = model.architecture.feature_root
        api_name = model.architecture.cross_feature_entrypoint
        if not feature_root:
            errors.append("architecture.feature_root is required for native/managed modular-monolith projects")
        elif PurePosixPath(feature_root).is_absolute() or ".." in PurePosixPath(feature_root).parts:
            errors.append("architecture.feature_root must be a repository-relative directory")
        if not api_name:
            errors.append("architecture.cross_feature_entrypoint is required for native/managed modular-monolith projects")
        elif PurePosixPath(api_name).name != api_name:
            errors.append("architecture.cross_feature_entrypoint must be a bare filename, not a path")
        elif not api_name.endswith(tuple(source_suffixes(model))):
            # 正门文件名按**已声明语言**判,不写死 .py。三语言的正门形态各不相同:
            # Python 是 api.py、TS 是 index.ts、Go 根本没有正门文件(靠 internal/ 目录,编译器强制)。
            errors.append(
                f"architecture.cross_feature_entrypoint 必须以已声明语言的后缀结尾"
                f"(当前声明:{list(source_suffixes(model))}),实际:{api_name}"
            )
    return errors


def _managed_governance_errors(model: ProjectModel) -> list[str]:
    errors: list[str] = []
    if model.metadata.governance_mode == "managed":
        if "architecture" not in getattr(model, "model_fields_set", {"architecture"}):
            errors.append("managed governance_mode requires an explicit [architecture] section")
        if not model.governance.managed_baselines:
            errors.append("managed governance_mode requires governance.managed_baselines")
        if not model.governance.inventory_violation_baseline:
            errors.append("managed governance_mode requires governance.inventory_violation_baseline")
        baseline_paths = [*model.governance.managed_baselines, model.governance.inventory_violation_baseline]
        if len(baseline_paths) != len(set(baseline_paths)):
            errors.append("managed baseline paths must be unique")
        errors.extend(
            "managed baseline path must stay below .ai-config/config and end with .baseline.json: "
            f"{baseline_path}"
            for baseline_path in baseline_paths
            if not is_safe_managed_baseline_path(baseline_path)
        )
    return errors


def _zone_reference_errors(model: ProjectModel, ids: set[str]) -> list[str]:
    errors: list[str] = []
    import_roots: dict[str, str] = {}
    for zone in model.zones:
        errors.extend(
            f"zone.{zone.id}.may_import_zones references unknown zone `{target}`"
            for target in zone.may_import_zones
            if target not in ids
        )
        for selector in zone.selectors:
            if selector.kind in {"dir", "file"} and any(token in selector.value for token in "*?["):
                errors.append(f"zone.{zone.id}.selectors `{selector.value}` needs kind=glob")
            if selector.kind == "exclude" and not selector.value.strip():
                errors.append(f"zone.{zone.id}.selectors exclude value cannot be empty")
        for root in zone.import_roots:
            owner = import_roots.get(root)
            if owner and owner != zone.id:
                errors.append(f"import_root `{root}` owned by both zone.{owner} and zone.{zone.id}")
            import_roots[root] = zone.id
    return errors


def _feature_root_coverage_errors(model: ProjectModel) -> list[str]:
    errors: list[str] = []
    explicit_architecture = "architecture" in getattr(model, "model_fields_set", {"architecture"})
    if model.metadata.governance_mode != "foreign" and explicit_architecture and model.architecture.feature_root:
        feature_root = model.architecture.feature_root.strip("/")
        formal_coverage = any(
            "formal_like" in zone.traits
            and any(
                feature_root == directory.strip("/")
                or feature_root.startswith(f"{directory.strip('/')}/")
                or directory.strip("/").startswith(f"{feature_root}/")
                for directory in zone.dirs
            )
            for zone in model.zones
        )
        if not formal_coverage:
            errors.append("architecture.feature_root must be covered by a formal_like zone directory")
    return errors


def _member_errors(
    model: ProjectModel,
    ids: set[str],
    entrypoint_ids: list[str],
    excluded_member_roots: list[str],
) -> list[str]:
    """检查 members，并把入口 id 与被排除的 member root 累积回调用方传入的列表。"""
    errors: list[str] = []
    member_ids_seen: dict[str, str] = {}
    member_roots: dict[str, str] = {}
    for member in model.members:
        if member.id == "root":
            errors.append("member id `root` is reserved for repository root")
        if member.id in member_ids_seen:
            errors.append(f"member id duplicated: {member.id}")
        member_ids_seen[member.id] = member.root
        if member.root in member_roots:
            errors.append(f"member root `{member.root}` owned by both {member_roots[member.root]} and {member.id}")
        member_roots[member.root] = member.id
        if member.exclude_from_parent:
            excluded_member_roots.append(member.root)
        errors.extend(
            f"member.{member.id}.default_zones references unknown zone `{zone_id}`"
            for zone_id in member.default_zones
            if zone_id not in ids
        )
        for entrypoint in member.entrypoints:
            entrypoint_ids.append(entrypoint.id)
            if entrypoint.member not in {member.id, "root"}:
                errors.append(
                    f"member.{member.id}.entrypoint.{entrypoint.id}.member must be `{member.id}` or `root`"
                )
            if not (entrypoint.file or entrypoint.module or entrypoint.command):
                errors.append(f"member.{member.id}.entrypoint.{entrypoint.id} needs file, module, or command")
            errors.extend(
                f"member.{member.id}.entrypoint.{entrypoint.id}.allowed_zones unknown zone `{zone_id}`"
                for zone_id in entrypoint.allowed_zones
                if zone_id not in ids
            )
    return errors


def _root_entrypoint_errors(model: ProjectModel, ids: set[str], entrypoint_ids: list[str]) -> list[str]:
    errors: list[str] = []
    member_ids = {member.id for member in model.members} | {"root"}
    for entrypoint in model.entrypoints:
        entrypoint_ids.append(entrypoint.id)
        if entrypoint.member not in member_ids:
            errors.append(f"entrypoint.{entrypoint.id}.member references unknown member `{entrypoint.member}`")
        if not (entrypoint.file or entrypoint.module or entrypoint.command):
            errors.append(f"entrypoint.{entrypoint.id} needs file, module, or command")
        errors.extend(
            f"entrypoint.{entrypoint.id}.allowed_zones unknown zone `{zone_id}`"
            for zone_id in entrypoint.allowed_zones
            if zone_id not in ids
        )
    return errors


def _api_contract_errors(model: ProjectModel) -> list[str]:
    errors: list[str] = []
    if model.contracts.api:
        if not is_safe_repository_path(model.contracts.api.schema_file):
            errors.append("contracts.api.schema_file must be a repository-relative path")
        if not model.contracts.api.export_command.strip():
            errors.append("contracts.api.export_command cannot be blank")
        if not model.contracts.api.compatibility_command.strip():
            errors.append("contracts.api.compatibility_command cannot be blank")
        elif "{baseline}" not in model.contracts.api.compatibility_command or "{current}" not in model.contracts.api.compatibility_command:
            errors.append("contracts.api.compatibility_command must include {baseline} and {current}")
        if not model.contracts.api.source_globs:
            errors.append("contracts.api.source_globs is required to keep stage targeted")
        if model.contracts.api.timeout_seconds <= 0:
            errors.append("contracts.api.timeout_seconds must be positive")
    return errors


def _database_contract_errors(model: ProjectModel) -> list[str]:
    errors: list[str] = []
    if model.contracts.database:
        errors.extend(
            f"contracts.database.{field} cannot be blank"
            for field, command in (
                ("check_command", model.contracts.database.check_command),
                ("heads_command", model.contracts.database.heads_command),
                ("isolated_upgrade_command", model.contracts.database.isolated_upgrade_command),
            )
            if not command.strip()
        )
        if not model.contracts.database.source_globs:
            errors.append("contracts.database.source_globs is required to keep stage targeted")
        if model.contracts.database.timeout_seconds <= 0:
            errors.append("contracts.database.timeout_seconds must be positive")
    return errors


def _health_check_errors(model: ProjectModel) -> list[str]:
    errors: list[str] = []
    for check in model.contracts.health_checks:
        if not check.command.strip():
            errors.append(f"contracts.health_checks.{check.id}.command cannot be blank")
        if not check.source_globs:
            errors.append(f"contracts.health_checks.{check.id}.source_globs is required to keep stage targeted")
        if check.timeout_seconds <= 0:
            errors.append(f"contracts.health_checks.{check.id}.timeout_seconds must be positive")
    return errors


def source_suffixes(model: ProjectModel) -> tuple[str, ...]:
    """所有声明语言的源码后缀合集(走目录时的粗筛用)。"""
    return tuple(dict.fromkeys(suffix for lang in model.languages for suffix in lang.suffixes))


def source_include_globs(model: ProjectModel) -> list[str]:
    """所有声明语言的管辖 glob 合集。"""
    return [glob for lang in model.languages for glob in lang.include_globs]


def load_project_model(path: Path = MODEL_PATH) -> ProjectModel:
    # 下面几处 raise ValueError 是故意留在 try 里的：本函数唯一的对外失败形态是
    # SystemExit("[project-model] invalid: ...")，让文件系统校验和 pydantic 校验走同一个出口。
    # 抽成内部函数(TRY301 的建议)只会把同一个 ValueError 换个抛出位置，收益为零、改错风险为正。
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        metadata = data.get("metadata", {})
        if metadata.get("governance_mode", "native") != "foreign" and "architecture" not in data:
            raise ValueError("native/managed project_model requires an explicit [architecture] section")  # noqa: TRY301
        model = ProjectModel.model_validate(data)
        if model.metadata.governance_mode != "foreign":
            feature_root = path.parent.parent / model.architecture.feature_root
            if not feature_root.is_dir():
                raise ValueError(  # noqa: TRY301
                    f"architecture.feature_root must be an existing repository directory: {model.architecture.feature_root}"
                )
        if model.metadata.governance_mode == "managed":
            # 声明是 .ai-config 相对的,必须过 managed_baseline_path() 才是仓库相对路径。
            # 这是同族的第四处漏点(另三处在 inventory x2 与 baseline_policy),接管真实项目时才炸出来。
            missing = [
                item for item in model.governance.managed_baselines
                if not (path.parent.parent / managed_baseline_path(item)).is_file()
            ]
            if missing:
                raise ValueError(f"managed baseline files missing: {missing}")  # noqa: TRY301
            baseline = path.parent.parent / managed_baseline_path(model.governance.inventory_violation_baseline)
            if not baseline.is_file():
                raise ValueError(f"managed inventory violation baseline missing: {model.governance.inventory_violation_baseline}")  # noqa: TRY301
    except (OSError, tomllib.TOMLDecodeError, ValidationError, ValueError) as exc:
        raise SystemExit(f"[project-model] invalid: {exc}") from exc
    else:
        return model


def load_project_model_dict(path: Path = MODEL_PATH) -> dict:
    return project_model_dict(load_project_model(path))


def excluded_member_roots(model: ProjectModel) -> list[str]:
    roots = [member.root for member in model.members if member.exclude_from_parent]
    if roots:
        return sorted(set(roots))
    if model.workspace.exclude_member_roots:
        return sorted(set(model.workspace.member_roots))
    return []


def zone_traits_map(model: ProjectModel) -> dict[str, set[str]]:
    return {zone.id: set(zone.traits) for zone in model.zones}


def project_model_dict(model: ProjectModel) -> dict:
    data = model.model_dump(mode="python")
    workspace = data.setdefault("workspace", {})
    workspace["member_roots"] = excluded_member_roots(model)
    return data


def path_matches(path_name: str, patterns: list[str]) -> bool:
    path = PurePosixPath(path_name)
    return any(path.match(pattern) or (pattern.startswith("**/") and path.match(pattern[3:])) for pattern in patterns)
