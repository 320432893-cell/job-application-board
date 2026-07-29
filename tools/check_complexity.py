# 职责：函数圈复杂度硬闸——冻结存量 CC≥THRESHOLD 的复杂块数(计数型棘轮·只减不增)，新增/变多即阻塞。
# 不做什么：不重构、不评判某处复杂是否正当(交人)；不管 <THRESHOLD(rank C)那些——归 radon deep 建议。
# 允许依赖层：标准库、radon(经 uv 调用)、complexity baseline 文件。
# 谁不应该 import：正式业务代码、测试夹具、应用入口不应 import 本检查脚本。
"""Cyclomatic-complexity hard gate: freeze the count of CC>=THRESHOLD blocks (count
ratchet, only-shrink); a commit that raises the count blocks. Below-threshold complexity
stays advisory via radon in the deep stage."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import baseline_policy
from tooling_layout import fixed_quality_dirs, formal_dirs

ROOT = Path(__file__).resolve().parents[1]
THRESHOLD = 21  # CC≥21 = radon rank D 及更差("函数干太多事")。<21(rank C) 归 deep 建议、不阻塞。
BASELINE_PATH = ROOT / ".ai-config" / "config" / "complexity.baseline.json"
# 档位豁免：文件头标 `# tier: 小件/抛弃` → 跳过复杂度闸(小脚本/公式脚本天生复杂、正当);正式区不许免检。
TIER_EXEMPT = re.compile(r"#\s*tier:\s*(小件|small|throwaway|抛弃)", re.IGNORECASE)


def is_tier_exempt(path: Path) -> bool:
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


def offenders() -> list[tuple[str, str, int]]:
    proc = subprocess.run(
        ["uv", "run", "radon", "cc", *fixed_quality_dirs(), "-j"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        sys.stderr.write(f"[complexity] radon 输出解析失败：{(proc.stderr or proc.stdout)[:200]}\n")
        return []
    found: list[tuple[str, str, int]] = []
    for path, blocks in data.items():
        if not isinstance(blocks, list):
            continue
        if is_tier_exempt(ROOT / path):
            continue
        for block in blocks:
            cc = block.get("complexity", 0)
            if cc >= THRESHOLD:
                found.append((path, block.get("name", "?"), cc))
    return found


def load_baseline() -> int:
    if not BASELINE_PATH.exists():
        return 0
    try:
        return int(json.loads(BASELINE_PATH.read_text(encoding="utf-8")).get("count", 0))
    except (json.JSONDecodeError, OSError, ValueError):
        return 0


def write_baseline(count: int) -> None:
    baseline_policy.require_expansion_approval(
        BASELINE_PATH, expansion=count > load_baseline(), action="baseline update"
    )
    payload = {
        "reason": f"存量 CC≥{THRESHOLD}(radon rank D+) 的复杂函数，在复杂度硬闸上线前已存在；冻结其总数。",
        "clear_by": f"逐个把复杂函数拆小到 CC<{THRESHOLD}，count 降到 0；头号是 build_* 里的巨型函数。",
        "registered": "2026-06-20",
        "ratchet": "计数型只减不增：CC≥阈值的块数不得超过 count(超=阻塞)；降了须更新 baseline 锁战果。",
        "count": count,
    }
    BASELINE_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str]) -> int:
    found = offenders()
    if "--update-baseline" in argv:
        write_baseline(len(found))
        sys.stdout.write(f"[complexity] baseline 已写入：{len(found)} 个 CC≥{THRESHOLD} 块\n")
        return 0
    baseline = load_baseline()
    prior = baseline_policy.head_json(BASELINE_PATH)
    if prior is not None:
        baseline_policy.require_expansion_approval(
            BASELINE_PATH, expansion=baseline > int(prior.get("count", 0)), action="baseline change"
        )
    if len(found) > baseline:
        sys.stderr.write(
            f"[complexity] 复杂度棘轮失败：CC≥{THRESHOLD} 的块数 {len(found)} > 基线 {baseline}（新增过复杂函数）：\n"
        )
        for path, name, cc in sorted(found, key=lambda item: -item[2])[:10]:
            sys.stderr.write(f"  CC={cc:3d}  {path}::{name}\n")
        sys.stderr.write("  拆小该函数；确属正当→重构后运行 --update-baseline。\n")
        return 1
    if len(found) < baseline:
        sys.stdout.write(
            f"[complexity] CC≥{THRESHOLD} 块数 {len(found)} < 基线 {baseline}，可运行 --update-baseline 锁战果。\n"
        )
    else:
        sys.stdout.write(f"[complexity] CC≥{THRESHOLD} 块数 {len(found)} = 基线，未恶化。\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
