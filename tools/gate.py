#!/usr/bin/env python3
# 职责：决定这次闸跑在哪个 Python 环境里,然后把参数原样转给 check.py。
# 不做什么：不解析闸的参数、不判断检查结果、不装依赖、不改退出码。
# 允许依赖层：只许标准库——它必须能在闸的依赖装好之前就跑起来。
# 谁不应该 import：任何东西。这是进程入口,只被命令行调用。
"""闸的统一入口:环境在一处决定,53 个调用点不用各自知道。

为什么存在:`uv run python tools/check.py` 在自有 Python 仓库里能跑——根 pyproject 的 dev 组里
就有闸的依赖;但接管态的纯 TS/Go 仓库根目录没有 pyproject,uv 给的是裸 python,check.py 第一行
import 就 ModuleNotFoundError: pydantic。

为什么不是"全部改成 --project .ai-config":那样会把 Python 项目跑坏——
  uv run python tools/check.py import-linter                 → Contracts: 1 kept, 0 broken.
  UV_PROJECT=.ai-config uv run python tools/check.py import-linter
                                                             → Could not find package 'project'
import-linter/basedpyright 这类要 import 到项目自己包的工具,只有在项目环境里才工作。
"用哪个环境"是每个项目不同的事实,不是一个可以写死的常量。

怎么决定:根目录有 pyproject.toml 就用项目自己的环境(行为与改动前逐字节一致);没有就用
闸自带的 .ai-config 环境。

为什么设 UV_PROJECT 而不是传 --project:registry 里 43 条 entrypoint_commands 写的都是裸
`uv run ...`,由 check.py 起子进程执行。环境变量会被继承,那 43 条一个字都不用改,新增检查器
也不需要记得"我要加个 --project"——靠约定让每处调用点自己记住,是会烂掉的那种设计。
"""

from __future__ import annotations

import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
GATE_PROJECT = ROOT / ".ai-config"


def gate_environment() -> str | None:
    """返回要用的 uv 项目目录;None 表示照旧交给 uv 自己找(项目自带 Python 环境)。"""
    if (ROOT / "pyproject.toml").is_file():
        return None
    if not (GATE_PROJECT / "pyproject.toml").is_file():
        # 两边都没有:不在这里编一个新错误,让 uv 按它原来的方式报,线索更准。
        return None
    return str(GATE_PROJECT)


def main(argv: list[str]) -> None:
    if project := gate_environment():
        os.environ["UV_PROJECT"] = project
    # execvp 不留中间进程:退出码和信号原样透传,闸红了就是红了。
    # S606(不经 shell 起进程)在这里正是要的:参数是我们自己拼的,过 shell 只会多一层转义风险。
    os.execvp("uv", ["uv", "run", "python", str(ROOT / "tools" / "check.py"), *argv])  # noqa: S606


if __name__ == "__main__":
    main(sys.argv[1:])
