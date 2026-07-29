#!/usr/bin/env python3
# 职责：把一次闸运行的结果收成一份机器可读快照(哪些工具红了、各自报了什么)。
# 不做什么：不决定工具怎么跑、不改退出码、不替人判断问题真假;解析失败绝不影响门禁。
# 允许依赖层：标准库。
# 谁不应该 import：正式业务代码、测试夹具、应用入口不应 import 本工具。
"""闸运行快照:一个文件说清全貌,不用去解析六份 log。

为什么存在:阶段之间工具不重叠,只跑 quick 看不见 cleanup 的问题;而每个工具各自打
stdout,想知道全貌就得把六份输出拼起来读——人和子 agent 的复核成本都压在这上面。

为什么埋在 run_command 这一个点:所有工具最终都从那里起子进程,埋一处就全覆盖,新增
检查器不需要记得"也写进报告"。靠约定让每个检查器自己上报,是会烂掉的那种设计。

findings 的解析是**尽力而为**:识别得出的按 file/line/message 拆开,识别不出的原样留在
raw 里,一条都不丢。失败的工具里有几个一条 finding 都没解析出来,会显式记进 summary 的
`failed_without_findings`——覆盖率是报出来的,不是假设的。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# `[ERROR] xxx` / `[WARN] xxx` / `[error] xxx`:本仓检查器最常用的行首标记。
SEVERITY_LINE = re.compile(r"^\s*\[(?P<severity>ERROR|WARNING|WARN|error|warning)\]\s*(?P<message>.+?)\s*$")
# `path/to/file.py:12:3: MSG` / `path/to/file.py:12 MSG`:ruff、mypy 一类工具的标准形状。
FILE_LINE = re.compile(r"^\s*(?P<file>[^\s:][^:]*\.[A-Za-z0-9_]+):(?P<line>\d+)(?::\d+)?[:\s]\s*(?P<message>.+?)\s*$")
# 消息体开头就是个路径时(本仓检查器常见:`[ERROR] .gitignore missing ...`)顺手把文件摘出来。
# 三种形状,按"更具体优先"排:带扩展名的 / 无扩展名的点文件(.gitignore、.importlinter)/ 带斜杠的。
# 只认这三种是刻意的:否则 `project_model tooling.x references ...` 里的首词也会被当成文件名,
# 快照里就会多出一批假的 file 字段,比留空更误导。
LEADING_PATH = re.compile(
    r"^(?P<file>[\w./@-]*[\w-]\.[A-Za-z0-9_]+|\.[\w-]+|[\w@-]+(?:/[\w.@-]+)+)(?::(?P<line>\d+))?(?=[\s:,]|$)"
)


@dataclass
class Finding:
    tool: str
    severity: str
    message: str
    file: str | None = None
    line: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "tool": self.tool,
            "severity": self.severity,
            "file": self.file,
            "line": self.line,
            "message": self.message,
        }


def parse_findings(tool: str, text: str) -> list[Finding]:
    """从一个工具的输出里尽力摘出结构化 finding;摘不出不报错,原始输出另存。"""
    findings: list[Finding] = []
    for raw_line in text.splitlines():
        if match := SEVERITY_LINE.match(raw_line):
            message = match.group("message")
            severity = match.group("severity").upper().replace("WARNING", "WARN")
            path, line = _leading_location(message)
            findings.append(Finding(tool=tool, severity=severity, message=message, file=path, line=line))
            continue
        if match := FILE_LINE.match(raw_line):
            findings.append(
                Finding(
                    tool=tool,
                    severity="ERROR",
                    message=match.group("message"),
                    file=match.group("file"),
                    line=int(match.group("line")),
                )
            )
    return findings


def _leading_location(message: str) -> tuple[str | None, int | None]:
    match = LEADING_PATH.match(message)
    if not match:
        return None, None
    line = match.group("line")
    return match.group("file"), int(line) if line else None


@dataclass
class ToolRun:
    tool: str
    exit_code: int
    seconds: float
    output: str = ""
    skipped: bool = False
    reason: str = ""

    def as_dict(self, *, keep_raw: bool) -> dict[str, Any]:
        findings = parse_findings(self.tool, self.output)
        record: dict[str, Any] = {
            "tool": self.tool,
            "exit_code": self.exit_code,
            "ok": self.exit_code == 0,
            "skipped": self.skipped,
            "ms": round(self.seconds * 1000),
            "findings": [item.as_dict() for item in findings],
        }
        if self.reason:
            record["reason"] = self.reason
        if keep_raw and self.output.strip():
            record["raw"] = self.output
        return record


@dataclass
class GateReport:
    """一次运行的累加器。check.py 全程只持有一个实例。"""

    target: str = ""
    runs: list[ToolRun] = field(default_factory=list)

    def record(self, tool: str, exit_code: int, seconds: float, output: str = "", **extra: Any) -> None:
        """记一次工具运行。extra 收 skipped/reason,让参数个数不随字段增长。"""
        self.runs.append(ToolRun(tool=tool, exit_code=exit_code, seconds=seconds, output=output, **extra))

    def as_dict(self, *, keep_raw: bool = True) -> dict[str, Any]:
        records = [run.as_dict(keep_raw=keep_raw) for run in self.runs]
        failed = [item for item in records if not item["ok"] and not item["skipped"]]
        return {
            "schema": 1,
            "target": self.target,
            "summary": {
                "tools": len(records),
                "skipped": sum(1 for item in records if item["skipped"]),
                "failed": len(failed),
                "findings": sum(len(item["findings"]) for item in records),
                # 覆盖率显式记账:红了却一条都没解析出来的工具,得去看它的 raw。
                "failed_without_findings": [item["tool"] for item in failed if not item["findings"]],
            },
            "tools": records,
        }

    def write(self, path: Path, *, keep_raw: bool = True) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.as_dict(keep_raw=keep_raw), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    def summary_lines(self) -> list[str]:
        """人看的一屏汇总:只列红的和跳过的,绿的不占地方。"""
        data = self.as_dict(keep_raw=False)
        summary = data["summary"]
        lines = [
            f"[report] {summary['tools']} 个工具:{summary['failed']} 红 / "
            f"{summary['skipped']} 跳过 / 共 {summary['findings']} 条 finding"
        ]
        for item in data["tools"]:
            if item["ok"] or item["skipped"]:
                continue
            lines.append(f"[report]   ✗ {item['tool']} (exit {item['exit_code']}, {len(item['findings'])} 条)")
        if blind := summary["failed_without_findings"]:
            lines.append(f"[report]   ⚠ 红了但没解析出 finding,需看 raw:{', '.join(blind)}")
        return lines


def finalize(report: GateReport, path: Path) -> None:
    """落盘 + 打印一屏汇总。放在这里而不是 check.py:那边有行数棘轮,逻辑该住实现层。"""
    report.write(path)
    print("\n".join(report.summary_lines()))
    print(f"[report] 写入 {path}")
