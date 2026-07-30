#!/usr/bin/env python3
# 职责：按 project_model.agent_reviews 生成 stage/cleanup 子 agent 审查包和提示词。
# 不做什么：不自动修代码、不替子 agent 下结论、不强行启动外部 agent 进程。
# 允许依赖层：标准库、git、本仓 inventory/stage_packet/project_model。
# 谁不应该 import：正式业务代码、测试夹具、应用入口不应 import 本工具。
"""Build subagent review prompts from project_model and generated facts."""

from __future__ import annotations

import argparse
import json
import sys
import tomllib
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import inventory as inventory_tool
import project_bootstrap as bootstrap_tool
import project_discovery as discovery_tool
import stage_packet as stage_packet_tool
import tooling_registry
from project_model import load_project_model_dict
from review_fingerprint import cached_report

ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH = ROOT / ".ai-config" / "project_model.toml"
REGISTRY_PATH = ROOT / ".ai-config" / "config" / "tooling.registry.toml"
OUTPUT_ROOT = ROOT / ".cache" / "subagent-reviews"


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def load_toml(path: Path) -> dict[str, Any]:
    return tomllib.loads(path.read_text(encoding="utf-8"))


def stage_gate_groups(stage: str) -> dict[str, list[str]]:
    registry = tooling_registry.load_registry(REGISTRY_PATH)
    return tooling_registry.stage_gate_groups(stage, registry)


def zone_counts(inventory: dict[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for file_record in inventory.get("files", []):
        zone = str(file_record.get("zone", "unknown"))
        counts[zone] = counts.get(zone, 0) + 1
    return dict(sorted(counts.items()))


def compact_stage_packet(packet: dict[str, Any]) -> dict[str, Any]:
    changed_files = packet.get("changed_files", [])
    return {
        "risk_flags": packet.get("risk_flags", []),
        "changed_count": len(changed_files),
        "stage_tool_skips": packet.get("stage_tool_skips", []),
    }


def limited_items(value: Any) -> list[Any]:
    if isinstance(value, dict):
        items = value.get("items", [])
        return items if isinstance(items, list) else []
    return value if isinstance(value, list) else []


def capability_catalog() -> list[dict[str, Any]]:
    registry = tooling_registry.load_registry(REGISTRY_PATH)
    rows: list[dict[str, Any]] = []
    for tool in registry.get("tools", []):
        tool_id = str(tool.get("id", "")).strip()
        if not tool_id:
            continue
        rows.append(
            {
                "capability_id": str(tool.get("capability_id") or tool_id),
                "tool_id": tool_id,
                "parent_tool": str(tool.get("parent_tool") or ""),
                "changed_adapter": bool(tool.get("changed_adapter")),
                "stages": [str(item) for item in tool.get("stages", [])],
                "commands": [
                    str(command)
                    for field in ("entrypoint_commands", "ci_commands", "manual_commands")
                    for command in tool.get(field, [])
                ],
                "purpose": str(tool.get("purpose") or ""),
            }
        )
    return rows


def build_context(stage: str) -> dict[str, Any]:
    model = inventory_tool.load_project_model()
    out_dir = OUTPUT_ROOT / stage
    inventory_snapshot = out_dir / "inventory.json"
    bootstrap_snapshot = out_dir / "project-bootstrap.json"
    stage_packet_snapshot = out_dir / "stage-packet.json"
    discovery_snapshot = out_dir / "project-discovery.json"
    scope = "changed" if stage == "stage" else "full"
    inventory = cached_report(inventory_tool.INVENTORY_PATH, ROOT, scope=scope)
    discovery = cached_report(discovery_tool.OUTPUT_PATH, ROOT, scope=scope)
    stage_packet = cached_report(stage_packet_tool.PACKET_PATH, ROOT, scope="changed")
    if stage == "stage":
        bootstrap = None
    else:
        bootstrap = cached_report(bootstrap_tool.OUTPUT_PATH, ROOT, scope="full")
    if inventory is None:
        inventory = inventory_tool.build_inventory(scope=scope)
        inventory_tool.write_inventory(inventory)
    if discovery is None:
        discovery = discovery_tool.build_report(scope=scope)
        discovery_tool.write_report(discovery)
    if stage_packet is None:
        stage_packet = stage_packet_tool.build_packet()
        stage_packet_tool.write_packet(stage_packet)
    inventory_tool.write_inventory(inventory, inventory_snapshot)
    if bootstrap is not None:
        bootstrap_tool.write_report(bootstrap, bootstrap_snapshot)
    stage_packet_tool.write_packet(stage_packet, stage_packet_snapshot)
    discovery_tool.write_report(discovery, discovery_snapshot)
    bootstrap_suggestions = (bootstrap or {}).get("model_suggestions", {})
    bootstrap_detail_paths = (
        {
            key: rel(bootstrap_snapshot.with_name(f"{bootstrap_snapshot.stem}.{key}.json"))
            for key in bootstrap_tool.DETAIL_KEYS
        }
        if bootstrap is not None
        else {}
    )
    snapshot_paths = [rel(inventory_snapshot), rel(stage_packet_snapshot), rel(discovery_snapshot)]
    # 闸运行快照(`check.py all --report` 产出)只在存在时挂进来:它是"哪些闸红了、红在哪"的
    # 唯一一份汇总,子 agent 有它就不用去拼六份 log。没跑过 --report 就没有,不强求。
    gate_report_path = ROOT / ".cache" / "gate-report.json"
    if gate_report_path.is_file():
        snapshot_paths.append(rel(gate_report_path))
    if bootstrap is not None:
        snapshot_paths.append(rel(bootstrap_snapshot))
        snapshot_paths.extend(bootstrap_detail_paths.values())
    return {
        "stage": stage,
        "governance_mode": model.metadata.governance_mode,
        "project_model": rel(MODEL_PATH),
        "inventory_path": rel(inventory_snapshot),
        "project_bootstrap_path": rel(bootstrap_snapshot) if bootstrap is not None else "",
        "stage_packet_path": rel(stage_packet_snapshot),
        "project_discovery_path": rel(discovery_snapshot),
        "snapshot_paths": snapshot_paths,
        "review_dir": rel(out_dir),
        "stage_gate_groups": stage_gate_groups(stage),
        "zone_counts": zone_counts(inventory),
        "inventory": {
            "scope": inventory.get("scope"),
            "file_count": len(inventory.get("files", [])),
            "edge_count": len(inventory.get("edges", [])),
            "member_count": len(inventory.get("members", [])),
            "entrypoint_count": len(inventory.get("entrypoints", [])),
            "resolver_module_count": inventory.get("module_resolver", {}).get("module_count", 0),
            "violation_count": len(inventory.get("violations", [])),
        },
        "project_bootstrap": {
            "available": bootstrap is not None,
            "summary": (bootstrap or {}).get("summary", {}),
            "detail_paths": bootstrap_detail_paths,
            "reference_sources_sample": limited_items(bootstrap_suggestions.get("unmodeled_reference_sources"))[:30],
            "referenced_targets_sample": limited_items(bootstrap_suggestions.get("unmodeled_referenced_targets"))[:30],
        },
        "project_discovery": {
            "scope": discovery.get("scope"),
            "summary": discovery.get("summary", {}),
            "findings_sample": discovery.get("findings", [])[:30],
        },
        "stage_packet": compact_stage_packet(stage_packet),
        "capability_catalog": capability_catalog() if stage == "cleanup" else [],
    }


def review_items(model: dict[str, Any], stage: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for item in model.get("agent_reviews", []):
        if not isinstance(item, dict):
            continue
        stages = [str(value) for value in item.get("stages", [])]
        if stage in stages:
            items.append(item)
    return items


def bullet_list(values: list[Any]) -> str:
    if not values:
        return "- 无"
    return "\n".join(f"- {value}" for value in values)


def prompt_for(review: dict[str, Any], context: dict[str, Any]) -> str:
    stage = context["stage"]
    focus = [str(item) for item in review.get("focus", [])]
    questions = [str(item) for item in review.get("questions", [])]
    foreign = context.get("governance_mode", "native") == "foreign"
    stage_name = (
        "变更影响分析"
        if foreign and stage == "stage"
        else "项目理解与维护分析"
        if foreign
        else "阶段审查"
        if stage == "stage"
        else "大扫除审查"
    )
    mode_instruction = (
        "这是外部项目：只做理解和维护建议，不给合规结论、不要求改目录、不把未建模或旧债当缺陷；结论分为机器事实、高置信推断、待确认。"
        if foreign
        else "这是接管项目：按 native 同一标准审查；存量债只能通过已声明基线只减不增，不能自动豁免。"
        if context.get("governance_mode") == "managed"
        else "这是原生项目：按完整工程闸审查，机器事实和设计判断仍须分开。"
    )
    return f"""# {review.get("title", review.get("id", "subagent-review"))}

你是只读子 agent，任务是做{stage_name}。不要改文件，不要替用户批准放行。
{mode_instruction}

## 输入材料
- project_model: `{context["project_model"]}`
- inventory: `{context["inventory_path"]}`，scope={context["inventory"]["scope"]}
- project_bootstrap: `{context["project_bootstrap_path"] or "stage 不生成"}`，available={context["project_bootstrap"]["available"]}
- stage_packet: `{context["stage_packet_path"]}`
- project_discovery: `{context["project_discovery_path"]}`，scope={context["project_discovery"]["scope"]}
- 本审查包目录: `{context["review_dir"]}`
- 完整 snapshot 必读: `{json.dumps(context.get("snapshot_paths", []), ensure_ascii=False)}`（cleanup 含 bootstrap detail 明细）

## 当前机器摘要
- zone_counts: `{json.dumps(context["zone_counts"], ensure_ascii=False)}`
- inventory_files: {context["inventory"]["file_count"]}
- members: {context["inventory"]["member_count"]}
- entrypoints: {context["inventory"]["entrypoint_count"]}
- resolver_modules: {context["inventory"]["resolver_module_count"]}
- import_edges: {context["inventory"]["edge_count"]}
- inventory_violations: {context["inventory"]["violation_count"]}
- bootstrap_summary: `{json.dumps(context["project_bootstrap"]["summary"], ensure_ascii=False)}`
- bootstrap_detail_paths: `{json.dumps(context["project_bootstrap"].get("detail_paths", {}), ensure_ascii=False)}`
- bootstrap_reference_sources: `{json.dumps(context["project_bootstrap"]["reference_sources_sample"][:10], ensure_ascii=False)}`
- bootstrap_referenced_targets: `{json.dumps(context["project_bootstrap"]["referenced_targets_sample"][:10], ensure_ascii=False)}`
- discovery_summary: `{json.dumps(context["project_discovery"]["summary"], ensure_ascii=False)}`
- discovery_findings_sample: `{json.dumps(context["project_discovery"]["findings_sample"][:10], ensure_ascii=False)}`
- risk_flags: `{", ".join(context["stage_packet"]["risk_flags"]) or "none"}`
- stage_tool_skips: `{json.dumps(context["stage_packet"].get("stage_tool_skips", []), ensure_ascii=False)}`
- changed_count: {context["stage_packet"]["changed_count"]}
- stage_gate_groups: `{json.dumps(context["stage_gate_groups"], ensure_ascii=False)}`
- capability_catalog: `{json.dumps(context.get("capability_catalog", []), ensure_ascii=False)}`

## 本 agent 重点
{bullet_list(focus)}

## 必答问题
{bullet_list(questions)}

## 大清理能力重叠审查（仅 cleanup）
若提供 capability_catalog，逐对检查“目的、扫描范围、底层 CLI、阶段”是否重叠。候选必须说明各自独特反例；无法证明独特性时建议合并 owner、降为 adapter 或归档。不得据此自动删工具，结论必须标为待人裁定。

## 输出格式
1. 坐实问题或机器事实：必须给证据路径或材料字段。
2. 候选未坐实：说明还缺什么证据。
3. 反驳自证：至少反驳自己一轮，避免误杀。
4. 建议：只提根因改法；不要给项目特例补丁；优先核实 discovery 给出的 reasons/evidence，不要重新全仓漫游。

注意：prompt 里的 sample 只用来定位方向，不是完整证据；必须打开完整 snapshot 后再下结论。project_bootstrap.detail_paths 是 bootstrap 的完整明细，不读明细不能下“全量没有”的结论。project_bootstrap 里的 relation 只是文本/字符串里的路径提及，不证明运行时依赖、所有权或入口身份；必须结合 inventory/discovery 和人工语义反证。
"""


def write_packets(stage: str, context: dict[str, Any], reviews: list[dict[str, Any]]) -> dict[str, Any]:
    out_dir = OUTPUT_ROOT / stage
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[dict[str, str]] = []
    for review in reviews:
        review_id = str(review.get("id", "")).strip()
        if not review_id:
            continue
        path = out_dir / f"{review_id}.md"
        path.write_text(prompt_for(review, context), encoding="utf-8")
        written.append({"id": review_id, "path": rel(path), "title": str(review.get("title", review_id))})
    index = {
        "schema_version": 1,
        "stage": stage,
        "reviews": written,
        "context": context,
    }
    index_path = out_dir / "index.json"
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"index": rel(index_path), "reviews": written}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=["stage", "cleanup"])
    parser.add_argument("--print", action="store_true", dest="print_json")
    args = parser.parse_args(argv)

    model = load_project_model_dict(MODEL_PATH)
    reviews = review_items(model, args.stage)
    if not reviews:
        print(f"[subagent-review] no reviews configured for {args.stage}")
        return 0
    context = build_context(args.stage)
    result = write_packets(args.stage, context, reviews)
    if args.print_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    # 只打路径等于把材料丢进 .cache/ 让人自己想起来去翻——四步摩擦,习惯养不成。
    # 这里把"看什么"直接摊在终端上,并给一条可直接粘给 AI 的开审指令。
    focus_by_id = {str(item.get("id", "")): [str(f) for f in item.get("focus", [])] for item in reviews}
    print(f"[subagent-review] {len(result['reviews'])} 份审查材料已生成({args.stage}):")
    width = max((len(str(item.get("title") or item["id"])) for item in result["reviews"]), default=0)
    for item in result["reviews"]:
        first_focus = next(iter(focus_by_id.get(item["id"], [])), "")
        print(f"  · {item.get('title') or item['id']!s:<{width}}  {first_focus}")
    print(
        f"  → 开审(把这句发给 AI):读 {OUTPUT_ROOT.relative_to(ROOT)}/{args.stage}/ 下的 "
        f"{len(result['reviews'])} 份提示词并逐条执行,把未坐实的标成候选"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
