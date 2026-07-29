# 协作规则 — AI 执行规范(设施绑定层)

通用交互/判断规则(输出·循环纪律·决策·产物意图·连续性)住全局自足层 `~/ai-global/AGENTS.md`(Claude 经全局 `~/.claude/CLAUDE.md` 自动加载,Codex 经 `~/.codex/AGENTS.md` 软链),两层互不复述、一概念一处。本文件只装**绑定本仓库设施**的规则:目录区制/四门/机器闸触发面/登记细则。供 AI 执行,非阅读材料。可机械判定→机器闸(registry/check.py/semgrep/import-linter/CI),细节→route。

级别:`[机器]`=工具/hook/CI 硬拦 · `[复核]`=子agent复核(见 `rules/engineering/code.index.md`) · `[强制产物]`=状态转移必交、缺=未完成 · `[启发]`=判断/意图/NL(大头在全局层)。能升 `[机器]` 别停 `[启发]`;`[启发]` 定期复审→升闸或删;死规则(无工具+无人执行)直接删。

## §1 代码档位(随赌注×寿命缩放)
- **抛弃**(跑完即删)→ scratch/tmp 零规则 · **小件**(单/几文件小脚本)→ 标 `# tier: 小件`,只留 py_compile+ruff+密钥+全局层§1 · **正式**(多模块·长寿·被依赖)→ 全套;小件长成被依赖→晋升正式;`# tier: 小件` 不适用于 `src/<package>/features` 与 `platform`。

## §2 输出(指针)
全部在全局层 §1(简略/一句话/表/说人话/知识扩展/给人命令/视图类/大内容不进上下文/Python 默认)。本仓库无补充;会话 hooks 只管会话层,全局唯一份,住 `~/ai-global/hooks/`。

## §3 操作循环 + 四门
循环纪律(承重/多路/不可逆先谋划,小修/明确可逆可直接执行;闭包/异常四项/失败两级·方案级二次停手/redirect·augment)在全局层 §2。以下为本仓库四门与触发面:

四门(审查分层、每门只查本层,报"哪门/查啥/过没过"):
| 门 | 触发 | 查 |
|---|---|---|
| ①入库 | scratch→`git add` | `[机器]` 声明身份(哪区)+ 非正式区带 `# lifecycle:` |
| ②切片 | 区内切片闭包 | `[机器]`+`[复核]` 按区严格度(下)+ `check.py changed` 退0 |
| ③晋升 | feature/platform 长出新符号 | `[机器]`+`[复核]` 全套生产标 + 源头探针/测试副本清掉没 + 出三段总结·硬拦等拍板 |
| ④阶段 | 阶段/分支功能闭包 | `[机器]` 承重/可逆性/身份/双源(`check.py stage`)+ `[复核]` 全分支 diff(`main...HEAD`)查废弃逻辑/动态分发僵尸/跨切片双源(见 `rules/engineering/code.index.md` §5) |

严格度按目的地:
| 区 | 查 |
|---|---|
| `scratch/`·`tmp/`(gitignore) | 零检查;铁律:禁被正式 import |
| `probes/` | 仅 `# lifecycle:` + 隔离 |
| `tests/` | 能跑且有业务断言;不上类型/复杂度 |
| `tools/` 入口 | 边界块 + ≤600 行 + 无业务逻辑 |
| `features/`·`platform/` | 全套:身份/边界/类型/复杂度/死码/双轨复核/真测试 |

触发与范围(避免全盘慢):改完 → AI 按风险自跑轻量检查(py_compile/ruff/相关测试/`check.py changed`);commit → pre-commit 自动(staged 范围);阶段闭包/CI → `check.py stage`/`ci`(全量·少跑)。**禁每轮 deep/全盘扫**;scratch/ 一次性件零检查。**机器闸**稳定触发靠 check.py/pre-commit/CI,会话 hooks 只管会话层;**`[复核]`(子agent审查)触发挂"人按进度触发的体检"**(见 `rules/review/review.index.md`:阶段/优化/大清理),非"察觉闭包"——判断审需进度知识、机器拿不到,故由人锚定,非机器失职。承重识别由机器证据包辅助(见 §4)、放行登记批准归人(见 §5)、行为安全归测试。

## §4 决策(指针+设施补充)
决策纪律(摆分叉+每路标脆弱点/契约/假设/AI 强弱/早锁不变量/对抗证伪/归因链)在全局层 §3。本仓库设施补充:
- 依赖方向(entrypoints→features/platform；跨 feature 仅经项目模型声明的接口文件；platform 不反向依赖 feature)由 `[机器]` inventory+import-linter+Ruff TID252+encapsulation 守(**前提:import 必须绝对·按包名(`from pkg.x import Y`),禁相对(`from .`/`from ..`)——相对 import 按文件地址、绕过分层分析=盲区;Ruff 对相对 import 报红;encapsulation 对偷 import `_private`/`internal`/`impl` 报红**)。
- 承重识别靠机器证据包辅助(stage-packet/inventory/import-cycles/dup-symbol);扇入需探针/后续工具补强,不是当前硬闸。语义级 blast(少调用大影响)扇入抓不到→归测试。细则 `rules/review/`。

## §5 产物质量(机器闸细则;意图类判断在全局层 §4)
- 查双轨靠状态:`[机器]` vulture+dup-symbol 名字碰撞+复杂度棘轮+晋升门查源头;`[复核]` 切片闭包查机器判不了的重复业务逻辑/双轨/死测试。
- **放行登记批准权归用户**(白名单/skip/debt 等"明知接受违规"):AI 只提议+证据,**闸保持红逼审**,被闸管者不自批(职责分离)。白名单基线一次性批、注明日期,此后只审增量;老条目用 git 年龄回炉复核(非到期自动删)。
- `[机器]` dup-symbol 切片闭包反查命名兜底——stage 只看相对 HEAD 新增的顶层名:完全同名阻塞、同词根只出复核材料；full 命中只提示。这样 managed 项目改旧文件不被历史名字卡住；AI MUST 对近名逐条摆分叉交你拍(取代旧 X / 意外·边缘 / 备选·fallback / 删 / 确非同类)，**禁静默另写并存**;裁决是你的评判权,AI 只提议+给证据。意外/备选 SHOULD 配可达性测试+放行登记,否则容易长成僵尸。
- 机器闸细则(一概念一处):代码身份与分区依赖→inventory/import-linter;边界块/行数(≥600 棘轮)→module-boundary;非正式区身份→check_lifecycle;放行登记→`check.py debt`;复杂度棘轮→check_complexity;时机/工具 SSOT→registry。

## §6 交接
- 指针:通用层→`~/ai-global/AGENTS.md`;可验证检查→`config/tooling.registry.toml`;设计模式+复核→`rules/engineering/code.index.md`;命名/查重→`rules/engineering/naming.index.md`。
- 连续性/体力活外包在全局层 §5。
