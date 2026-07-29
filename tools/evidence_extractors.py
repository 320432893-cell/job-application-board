#!/usr/bin/env python3
# 职责：集中放“只产证据、不判身份”的轻量发现器，供 bootstrap/discovery 复用。
# 不做什么：不阻塞提交、不修改 project_model、不猜 formal/test/tool 身份。
# 允许依赖层：标准库。
# 谁不应该 import：正式业务代码、测试夹具、应用入口不应 import 本工具。
"""Shared evidence-only extractors for repository bootstrap/discovery."""

from __future__ import annotations

import ast
import mimetypes
import re
from pathlib import Path, PurePosixPath

PROJECT_MARKER_NAMES = (
    "pyproject.toml",
    "package.json",
    "requirements.txt",
    "requirements.lock",
    "setup.py",
    "setup.cfg",
    "Pipfile",
    ".git",
)
PYTHON_ENTRYPOINT_NAMES = ("main.py", "__main__.py", "app.py", "manage.py", "cli.py")
GENERIC_ENTRYPOINT_NAMES = (
    "app.js",
    "app.ts",
    "index.html",
    "index.js",
    "index.ts",
    "main.go",
    "main.java",
    "main.js",
    "main.rs",
    "main.ts",
    "server.js",
    "server.ts",
)
SOURCE_LIKE_SUFFIXES = {
    ".c",
    ".cc",
    ".cpp",
    ".cs",
    ".css",
    ".go",
    ".h",
    ".hpp",
    ".html",
    ".java",
    ".js",
    ".jsx",
    ".mjs",
    ".php",
    ".rb",
    ".rs",
    ".svelte",
    ".ts",
    ".tsx",
    ".vue",
}
CONFIG_MIME_TYPES = {
    "application/json",
    "application/toml",
    "application/xml",
    "text/xml",
    "text/yaml",
}
REFERENCE_TOKEN_RE = re.compile(r"[\w\u4e00-\u9fff./\\-]{1,240}\.[A-Za-z0-9]{1,12}")
QUOTED_TOKEN_RE = re.compile(r"""["']([^"'\r\n]{1,240})["']""")
ASCII_PRINTABLE_MIN = 32
ASCII_PRINTABLE_MAX = 126
NON_ASCII_MIN = 128
TEXT_RATIO_THRESHOLD = 0.85


def path_kind(path_name: str) -> str:
    path = PurePosixPath(path_name)
    suffix = path.suffix.lower()
    name = path.name
    mime, _ = mimetypes.guess_type(path_name)
    if suffix == ".py":
        return "python"
    if name in PROJECT_MARKER_NAMES or suffix in {".lock", ".spec"}:
        return "build_contract"
    if suffix in {".cfg", ".conf", ".ini", ".toml", ".yaml", ".yml"} or mime in CONFIG_MIME_TYPES:
        return "config"
    # 显式后缀表必须先判：mimetypes 是为别的用途维护的共享猜测表，会把 `.ts` 猜成 video/mp2t，
    # 排在前面会让 TypeScript 全被判成 asset，changed 调度对整个前端失明(模板测试早已抓到这条)。
    if suffix in SOURCE_LIKE_SUFFIXES:
        return "source"
    if mime and mime.split("/", maxsplit=1)[0] in {"image", "audio", "video", "font"}:
        return "asset"
    if mime and mime.startswith("text/"):
        return "text"
    if suffix in {".bat", ".sh", ".ps1"}:
        return "script"
    return "other"


def is_probable_source_file(path_name: str) -> bool:
    return path_kind(path_name) == "source"


def is_low_signal_history_path(path_name: str) -> bool:
    lower = path_name.lower()
    return lower.startswith(("logs/", "archive/")) or "/archive/" in lower or "/logs/" in lower


def looks_like_text_bytes(raw: bytes) -> bool:
    if not raw:
        return True
    if b"\x00" in raw:
        return False
    sample = raw[:4096]
    printable = sum(
        byte in b"\t\n\r" or ASCII_PRINTABLE_MIN <= byte <= ASCII_PRINTABLE_MAX or byte >= NON_ASCII_MIN
        for byte in sample
    )
    return printable / max(len(sample), 1) >= TEXT_RATIO_THRESHOLD


def read_small_text(path: Path, *, max_bytes: int) -> str:
    try:
        if path.stat().st_size > max_bytes:
            return ""
        raw = path.read_bytes()
    except OSError:
        return ""
    if not looks_like_text_bytes(raw):
        return ""
    return raw.decode("utf-8", errors="ignore")


def string_tokens_from_python(path: Path, *, filename: str) -> list[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=filename)
    except (OSError, SyntaxError, UnicodeDecodeError):
        return []
    return [node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)]


def string_tokens_from_text(text: str) -> list[str]:
    tokens = [match.group(1) for match in QUOTED_TOKEN_RE.finditer(text)]
    tokens.extend(match.group(0) for match in REFERENCE_TOKEN_RE.finditer(text))
    return tokens


def clean_token(token: str) -> str:
    token = token.strip().strip("`\"'()[]{}<>,;:")
    return token.replace("\\", "/")


def normalize_repo_path(path_name: str) -> str:
    parts: list[str] = []
    for part in PurePosixPath(path_name).parts:
        if part in {"", "."}:
            continue
        if part == "..":
            if not parts:
                return ""
            parts.pop()
            continue
        parts.append(part)
    return "/".join(parts)


def resolve_reference(source: str, token: str, known_files: set[str]) -> str:
    clean = clean_token(token)
    parts = PurePosixPath(clean).parts
    if not clean or not parts or "://" in clean or ":" in parts[0]:
        return ""
    candidates: list[str] = []
    source_parent = PurePosixPath(source).parent
    if source_parent.as_posix() != ".":
        candidates.append(normalize_repo_path((source_parent / clean).as_posix()))
    candidates.append(normalize_repo_path(clean))
    candidates.append(PurePosixPath(clean).name)
    for candidate in candidates:
        candidate = candidate.strip("/")
        if candidate in known_files and candidate != source:
            return candidate
    return ""


def has_python_main_guard(path: Path, *, filename: str) -> bool:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=filename)
    except (OSError, SyntaxError, UnicodeDecodeError):
        return False
    for node in tree.body:
        if not isinstance(node, ast.If):
            continue
        test = node.test
        if (
            isinstance(test, ast.Compare)
            and isinstance(test.left, ast.Name)
            and test.left.id == "__name__"
            and len(test.ops) == 1
            and isinstance(test.ops[0], ast.Eq)
            and len(test.comparators) == 1
            and isinstance(test.comparators[0], ast.Constant)
            and test.comparators[0].value == "__main__"
        ):
            return True
    return False


def python_entrypoint_reason(path_name: str, path: Path | None = None) -> str:
    name = PurePosixPath(path_name).name
    if name in PYTHON_ENTRYPOINT_NAMES:
        return f"filename:{name}"
    if path is not None and has_python_main_guard(path, filename=path_name):
        return "python_main_guard"
    return ""


def python_entrypoint_reasons(path_name: str, path: Path) -> list[str]:
    reasons: list[str] = []
    name = PurePosixPath(path_name).name
    if name in PYTHON_ENTRYPOINT_NAMES:
        reasons.append("entrypoint-like filename")
    if has_python_main_guard(path, filename=path_name):
        reasons.append("python __main__ guard")
    return reasons


def generic_entrypoint_reason(path_name: str) -> str:
    name = PurePosixPath(path_name).name
    if name in GENERIC_ENTRYPOINT_NAMES:
        return f"filename:{name}"
    return ""


def entrypoint_tier(path_name: str, reasons: list[str]) -> str:
    name = PurePosixPath(path_name).name
    lower = path_name.lower()
    if is_low_signal_history_path(path_name) or any(part in lower for part in ("probe", "tmp", "debug", "diagnose")):
        return "probe_or_archive"
    if name in {"main.py", "__main__.py", "app.py"}:
        return "primary_candidate"
    if "entrypoint-like filename" in reasons:
        return "primary_candidate"
    return "script_candidate"
