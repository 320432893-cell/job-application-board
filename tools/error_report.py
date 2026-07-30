#!/usr/bin/env python3
# 职责：五字段报错的统一格式(步骤/原因/预期vs现状/修复提示/受众),供各检查脚本复用同一份写法。
# 不做什么：不决定何时报错、不捕获异常、不打印(返回字符串或异常对象,由调用方决定怎么用)。
# 允许依赖层：标准库。
# 谁不应该 import：正式业务代码、测试夹具、应用入口不应 import 本工具层模块。
"""五字段报错:AGENTS.md §4 对所有工具的硬要求,所以格式住在一处而不是各写各的。"""

from __future__ import annotations


def five_field(step: str, reason: str, expect_actual: str, fix: str, audience: str = "开发 / CI") -> str:
    return f"{step}\n  原因:{reason}\n  预期 vs 现状:{expect_actual}\n  修复:{fix}\n  受众:{audience}"


def abort(step: str, reason: str, expect_actual: str, fix: str, audience: str = "开发 / CI") -> SystemExit:
    """构造一个带五字段的 SystemExit;调用方 `raise ... from exc` 保留原始栈。"""
    return SystemExit(five_field(step, reason, expect_actual, fix, audience))
