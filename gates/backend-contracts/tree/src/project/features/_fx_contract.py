# 职责：反向样本——被 contracts.api.source_globs 覆盖的源文件，用来触发 backend-contracts 的 changed 判定。
# 不做什么：不实现任何真实 API。
# 允许依赖层：标准库。
# 谁不应该 import：任何人。
"""Source file covered by the fixture's declared API contract globs."""

VERSION = "1"
