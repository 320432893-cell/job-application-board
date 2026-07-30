#!/usr/bin/env python3
# 职责：为未校准项目生成接生地图：文件清单、引用关系、入口/资产候选、模型建议。
# 不做什么：不修改 project_model，不判定 formal/test/tool 身份，不把候选直接当阻塞结论。
# 允许依赖层：标准库、本仓 inventory/project_model。
# 谁不应该 import：正式业务代码、测试夹具、应用入口不应 import 本工具。
"""Build a bootstrap evidence map before normal stage/cleanup gates."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import evidence_extractors as evidence
import inventory as inventory_tool
from review_fingerprint import report_fingerprint

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = ROOT / ".cache" / "project-bootstrap.json"
MAX_TEXT_BYTES = 512_000
DETAIL_KEYS = ("files", "reference_edges", "reference_text_scan_skips")


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def display_path(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.name


def stable_id(kind: str, *parts: object) -> str:
    raw = ":".join(str(part) for part in (kind, *parts))
    return raw.replace("/", ":").replace(" ", "_")


def is_global_scaffold_path(path_name: str) -> bool:
    return path_name == "pyproject.toml" or path_name.startswith((".ai-config/", "tools/"))


def limited(values: list[Any], limit: int) -> dict[str, object]:
    return {
        "total": len(values),
        "shown": min(len(values), limit),
        "truncated": len(values) > limit,
        "items": values[:limit],
    }


def summarize_ignored_dir(path: Path, path_name: str, limit: int = 10_000) -> dict[str, object]:
    file_count = 0
    dir_count = 0
    truncated = False
    for _, dirnames, filenames in os.walk(path):
        dir_count += len(dirnames)
        file_count += len(filenames)
        if file_count >= limit:
            truncated = True
            break
    return {
        "path": path_name,
        "file_count": file_count,
        "dir_count": dir_count,
        "truncated": truncated,
        "role": "ignored_artifact_or_cache",
    }


def iter_repo_files(model: inventory_tool.ProjectModel) -> tuple[list[Path], list[dict[str, object]]]:
    ignored = inventory_tool.pathspec_from(model.ignore.patterns)
    files: list[Path] = []
    ignored_dirs: list[dict[str, object]] = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        directory = Path(dirpath)
        rel_dir = "" if directory == ROOT else rel(directory)
        kept_dirs: list[str] = []
        for dirname in dirnames:
            child_name = dirname if not rel_dir else f"{rel_dir}/{dirname}"
            if inventory_tool.is_ignored_directory(child_name, ignored):
                ignored_dirs.append(summarize_ignored_dir(directory / dirname, child_name))
                continue
            kept_dirs.append(dirname)
        dirnames[:] = kept_dirs
        for filename in filenames:
            path = directory / filename
            path_name = rel(path)
            if ignored.match_file(path_name):
                continue
            files.append(path)
    return sorted(files), ignored_dirs


def reference_edges(files: list[Path]) -> list[dict[str, object]]:
    known_files = {rel(path) for path in files}
    ranked: dict[tuple[str, str, str], dict[str, object]] = {}
    confidence_rank = {"weak": 0, "medium": 1}
    for path in files:
        source = rel(path)
        tokens: list[tuple[str, str, str]] = []
        if path.suffix.lower() == ".py":
            tokens.extend(
                (token, "python_ast_string_literal", "medium")
                for token in evidence.string_tokens_from_python(path, filename=source)
            )
        text = evidence.read_small_text(path, max_bytes=MAX_TEXT_BYTES)
        if text:
            tokens.extend(
                (token, "small_text_or_comment_token", "weak") for token in evidence.string_tokens_from_text(text)
            )
        for token, token_source, confidence in tokens:
            target = evidence.resolve_reference(source, token, known_files)
            if not target:
                continue
            kind = "literal_path_reference"
            key = (source, target, kind)
            existing = ranked.get(key)
            if existing and confidence_rank[str(existing["confidence"])] >= confidence_rank[confidence]:
                continue
            ranked[key] = {
                "id": stable_id(kind, source, target),
                "kind": kind,
                "source": source,
                "target": target,
                "source_kind": evidence.path_kind(source),
                "target_kind": evidence.path_kind(target),
                "token": token[:120],
                "token_source": token_source,
                "resolution_mode": "known_file_literal_match",
                "confidence": confidence,
                "evidence_role": "bootstrap_relation",
                "decision_role": "evidence_only",
                "blocking": False,
            }
    return sorted(ranked.values(), key=lambda item: (str(item["source"]), str(item["target"])))


def large_text_scan_skips(files: list[Path]) -> list[dict[str, object]]:
    skipped: list[dict[str, object]] = []
    for path in files:
        try:
            size = path.stat().st_size
        except OSError:
            continue
        if size <= MAX_TEXT_BYTES:
            continue
        skipped.append(
            {
                "path": rel(path),
                "size": size,
                "max_text_bytes": MAX_TEXT_BYTES,
                "reason": "text_token_scan_skipped_large_file",
            }
        )
    return skipped


def python_entry_hints(files: list[Path], model: inventory_tool.ProjectModel | None = None) -> list[dict[str, object]]:
    hints: list[dict[str, object]] = []
    for path in files:
        path_name = rel(path)
        if path.suffix != ".py":
            continue
        reasons = evidence.python_entrypoint_reasons(path_name, path)
        if not reasons:
            continue
        hints.append(
            {
                "path": path_name,
                "reasons": reasons,
                "zone": inventory_tool.classify(path_name, model)[0] if model is not None else "",
                "decision_role": "evidence_only",
                "blocking": False,
            }
        )
    return hints


def top_level_roots(files: list[Path]) -> list[dict[str, object]]:
    counts: Counter[str] = Counter()
    kinds: dict[str, Counter[str]] = {}
    for path in files:
        path_name = rel(path)
        parts = PurePosixPath(path_name).parts
        root = parts[0] if len(parts) > 1 else path_name
        counts[root] += 1
        kinds.setdefault(root, Counter())[evidence.path_kind(path_name)] += 1
    return [
        {"root": root, "file_count": count, "kinds": dict(sorted(kinds[root].items()))}
        for root, count in sorted(counts.items())
    ]


def build_report() -> dict[str, object]:
    model = inventory_tool.load_project_model()
    files, ignored_dirs = iter_repo_files(model)
    records = [
        {
            "path": rel(path),
            "kind": evidence.path_kind(rel(path)),
            "zone": inventory_tool.classify(rel(path), model)[0],
            "size": path.stat().st_size if path.exists() else 0,
        }
        for path in files
    ]
    edges = reference_edges(files)
    text_scan_skips = large_text_scan_skips(files)
    python_files = [record for record in records if record["kind"] == "python"]
    unmodeled_python = [record for record in python_files if record["zone"] == "unclassified"]
    reference_sources = Counter(str(edge["source"]) for edge in edges)
    referenced_targets = Counter(str(edge["target"]) for edge in edges)
    zones_by_path = {str(record["path"]): str(record["zone"]) for record in records}
    entry_hints = python_entry_hints(files, model)
    project_entry_hints = []
    for hint in entry_hints:
        path_name = str(hint["path"])
        if hint.get("zone") != "unclassified" or is_global_scaffold_path(path_name):
            continue
        project_entry_hints.append(
            {**hint, "tier": evidence.entrypoint_tier(path_name, [str(item) for item in _reasons(hint)])}
        )
    unmodeled_reference_sources = [
        {"path": path, "outgoing_reference_count": count}
        for path, count in reference_sources.most_common()
        if zones_by_path.get(path) == "unclassified" and not is_global_scaffold_path(path)
    ]
    unmodeled_referenced_targets = [
        {"path": path, "incoming_reference_count": count}
        for path, count in referenced_targets.most_common()
        if zones_by_path.get(path) == "unclassified" and not is_global_scaffold_path(path)
    ]
    ranked_unmodeled_reference_sources = sorted(
        unmodeled_reference_sources,
        key=lambda item: (
            evidence.is_low_signal_history_path(str(item["path"])),
            -int(item["outgoing_reference_count"]),
            str(item["path"]),
        ),
    )
    unmodeled_python_paths = [
        str(record["path"]) for record in unmodeled_python if not is_global_scaffold_path(str(record["path"]))
    ]
    referenced_unmodeled_python_targets = sorted(
        {
            str(edge["target"])
            for edge in edges
            if edge.get("target_kind") == "python"
            and zones_by_path.get(str(edge["target"])) == "unclassified"
            and not is_global_scaffold_path(str(edge["target"]))
        }
    )
    suggestions = {
        "unmodeled_python": limited(unmodeled_python_paths, 30),
        "entrypoint_hints": limited(entry_hints, 30),
        "project_entrypoint_hints": limited(project_entry_hints, 30),
        "referenced_python_targets": limited(
            sorted({str(edge["target"]) for edge in edges if edge.get("target_kind") == "python"}), 50
        ),
        "referenced_unmodeled_python_targets": limited(referenced_unmodeled_python_targets, 50),
        "reference_sources": limited(
            [{"path": path, "outgoing_reference_count": count} for path, count in reference_sources.most_common()],
            20,
        ),
        "referenced_targets": limited(
            [{"path": path, "incoming_reference_count": count} for path, count in referenced_targets.most_common()],
            20,
        ),
        "unmodeled_reference_sources": limited(ranked_unmodeled_reference_sources, 20),
        "unmodeled_referenced_targets": limited(unmodeled_referenced_targets, 20),
        "ignored_dirs": limited(ignored_dirs, 30),
    }
    return {
        "schema_version": 1,
        "scope": "full",
        "input_fingerprint": report_fingerprint(ROOT, "full"),
        "summary": {
            "file_count": len(records),
            "python_file_count": len(python_files),
            "unmodeled_python_count": len(unmodeled_python),
            "reference_edge_count": len(edges),
            "reference_text_scan_skipped_large_file_count": len(text_scan_skips),
            "ignored_dir_count": len(ignored_dirs),
        },
        "top_level_roots": top_level_roots(files),
        "files": records,
        "reference_edges": edges,
        "reference_text_scan_skips": text_scan_skips,
        "model_suggestions": suggestions,
    }


def write_report(report: dict[str, object], path: Path = OUTPUT_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    public_report = dict(report)
    detail_paths: dict[str, str] = {}
    for key in DETAIL_KEYS:
        popped = public_report.pop(key, [])
        items = list(popped) if isinstance(popped, list) else []
        detail_path = path.with_name(f"{path.stem}.{key}.json")
        detail_path.write_text(
            json.dumps(
                {"schema_version": 1, "kind": key, "total": len(items), "items": items}, ensure_ascii=False, indent=2
            )
            + "\n",
            encoding="utf-8",
        )
        detail_paths[key] = display_path(detail_path)
    public_report["detail_paths"] = detail_paths
    path.write_text(json.dumps(public_report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _section(report: dict[str, object], key: str) -> dict[str, object]:
    """从 JSON 报告里取一小节并窄化。

    report 是别的进程(或上一次运行)写下的异质 JSON,读的时候形状只能现场确认 —— 这不是
    能靠标注消掉的事,是边界处的事实。不窄化的话 `report["summary"]["file_count"]` 静态上
    就是在 object 上取下标(basedpyright 在本文件报了 9 条,大半是这一个原因)。
    """
    value = report.get(key)
    return value if isinstance(value, dict) else {}


def _items(section: dict[str, object], key: str) -> list[object]:
    """取 `{key: {"items": [...]}}` 里的那个列表;形状不对就当空。"""
    nested = _section(section, key)
    value = nested.get("items")
    return value if isinstance(value, list) else []


def print_summary(report: dict[str, object]) -> None:
    summary = _section(report, "summary")
    print(
        "[project-bootstrap] "
        f"files={summary['file_count']} python={summary['python_file_count']} "
        f"unmodeled_python={summary['unmodeled_python_count']} "
        f"references={summary['reference_edge_count']} ignored_dirs={summary['ignored_dir_count']}"
    )
    suggestions = _section(report, "model_suggestions")
    for hint in _items(suggestions, "project_entrypoint_hints")[:10]:
        row = hint if isinstance(hint, dict) else {}
        print(f"  - entrypoint-hint {row.get('path')}: {', '.join(str(x) for x in _reasons(row))}")
    for hub in _items(suggestions, "unmodeled_reference_sources")[:10]:
        row = hub if isinstance(hub, dict) else {}
        print(f"  - reference-hub {row.get('path')}: {row.get('outgoing_reference_count')} outgoing references")


def _reasons(row: dict[str, object]) -> list[object]:
    value = row.get("reasons")
    return value if isinstance(value, list) else []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["build", "print"], nargs="?", default="build")
    args = parser.parse_args(argv)
    report = build_report()
    if args.command == "print":
        printable = dict(report)
        for key in DETAIL_KEYS:
            printable.pop(key, None)
        print(json.dumps(printable, ensure_ascii=False, indent=2))
        return 0
    write_report(report)
    print(f"[project-bootstrap] wrote {OUTPUT_PATH.relative_to(ROOT)}")
    print_summary(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
