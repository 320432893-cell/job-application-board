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
# 摘要里每个工具最多留这么多条 finding,其余进 detail 文件。够看出"红在哪一类",
# 又不会让一个话痨工具吃掉整份报告。
SUMMARY_FINDING_LIMIT = 20
# 闸用这行把"我看了多少个单位"交回来。退出码只说"有没有违规",说不出"有没有看到东西" ——
# 而实测这套系统里的静默失效几乎全是后者:vulture 扫 3 行、0 条声明的风险评估、
# 语言不适用被跳过的闸,它们退出 0 的样子和真检查过一模一样。
# 必须带单位名:各闸的单位不是同一种东西(模块 / import / 符号 / 文件 / 环 / 契约 / 样本),
# 裸一个数字跨闸比较就是新的误导。
EXAMINED_LINE = re.compile(r"^\s*\[examined\]\s+(?P<unit>[a-z_]+)\s+(?P<count>\d+)\s*$")
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

    def examined(self) -> dict[str, Any] | None:
        """从输出里取 `[examined] <unit> <count>`;没报的闸返回 None(= 这道闸还没接线)。"""
        for line in self.output.splitlines():
            if match := EXAMINED_LINE.match(line):
                return {"unit": match["unit"], "count": int(match["count"])}
        return None

    def as_dict(self, *, keep_raw: bool, limit: int | None = None) -> dict[str, Any]:
        findings = parse_findings(self.tool, self.output)
        kept = findings if limit is None else findings[:limit]
        record: dict[str, Any] = {
            "tool": self.tool,
            "exit_code": self.exit_code,
            "ok": self.exit_code == 0,
            "skipped": self.skipped,
            "ms": round(self.seconds * 1000),
            "findings": [item.as_dict() for item in kept],
        }
        # 截断必须显式记账。省略号式的"还有更多"读起来像"就这些",而这份报告的读者
        # (人或子 agent)不会去数条目 —— 实测 basedpyright 一家吐 940KB 占整份 97%。
        if len(kept) < len(findings):
            record["findings_total"] = len(findings)
            record["findings_truncated"] = len(findings) - len(kept)
        if examined := self.examined():
            record["examined"] = examined
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
    # 全局视图过期比没有更危险:实测这份产物停在 7/28,而仓库已经推进到 8/02,
    # 拿它当现状就是在读假数据。指纹让读者能一眼判出"这份快照对不对得上当前工作树"。
    fingerprint: str = ""

    def record(self, tool: str, exit_code: int, seconds: float, output: str = "", **extra: Any) -> None:
        """记一次工具运行。extra 收 skipped/reason,让参数个数不随字段增长。"""
        self.runs.append(ToolRun(tool=tool, exit_code=exit_code, seconds=seconds, output=output, **extra))

    def as_dict(self, *, keep_raw: bool = True, limit: int | None = None) -> dict[str, Any]:
        records = [run.as_dict(keep_raw=keep_raw, limit=limit) for run in self.runs]
        failed = [item for item in records if not item["ok"] and not item["skipped"]]
        return {
            "schema": 1,
            "target": self.target,
            "summary": {
                "tools": len(records),
                "skipped": sum(1 for item in records if item["skipped"]),
                "failed": len(failed),
                "findings": sum(item.get("findings_total", len(item["findings"])) for item in records),
                # 覆盖率显式记账:红了却一条都没解析出来的工具,得去看它的 raw。
                "failed_without_findings": [item["tool"] for item in failed if not item["findings"]],
                # 绿灯但一个单位都没看到 —— 和红灯一样响。这是本仓静默失效的主形态:
                # 退出 0 说明"没违规",说不出"根本没看到东西"。
                "green_without_examining": [
                    item["tool"]
                    for item in records
                    if item["ok"] and not item["skipped"] and (item.get("examined") or {}).get("count") == 0
                ],
                # 还没接 [examined] 的闸:不接就无法区分上面那两种绿。
                "examined_not_reported": [
                    item["tool"] for item in records if not item["skipped"] and "examined" not in item
                ],
            },
            "tools": records,
        }

    def write(self, path: Path, *, keep_raw: bool = True) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.as_dict(keep_raw=keep_raw), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    def write_layered(self, path: Path, *, limit: int = SUMMARY_FINDING_LIMIT) -> list[Path]:
        """总分两层:摘要一份给人和子 agent 读,红了的工具各自一份全量详情按需取。

        为什么不塞一个文件:实测单文件 1.25MB,其中 basedpyright 一家 940KB(97%)——
        读者要的是"它红了、2419 条、九成是类型未知族",不是那 2419 条。而全量又不能丢,
        否则查具体某条时没有出处。
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        written: list[Path] = []
        summary = self.as_dict(keep_raw=False, limit=limit)
        summary["fingerprint"] = self.fingerprint
        summary["detail_paths"] = {}
        for run in self.runs:
            record = run.as_dict(keep_raw=False)
            if record["ok"] or record["skipped"] or not record["findings"]:
                continue
            detail = path.with_name(f"{path.stem}.{run.tool}{path.suffix}")
            detail.write_text(
                json.dumps(run.as_dict(keep_raw=True), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            summary["detail_paths"][run.tool] = detail.name
            written.append(detail)
        path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return [path, *written]

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
        if empty := summary["green_without_examining"]:
            lines.append(f"[report]   ⚠ 绿灯但一个单位都没看到(空闸):{', '.join(empty)}")
        if silent := summary["examined_not_reported"]:
            lines.append(f"[report]   · 未报 examined({len(silent)} 个):{', '.join(silent[:6])}")
        return lines


def finalize(report: GateReport, path: Path) -> None:
    """落盘 + 打印一屏汇总。放在这里而不是 check.py:那边有行数棘轮,逻辑该住实现层。"""
    written = report.write_layered(path)
    print("\n".join(report.summary_lines()))
    print(f"[report] 写入 {path}" + (f" + {len(written) - 1} 份详情" if len(written) > 1 else ""))
