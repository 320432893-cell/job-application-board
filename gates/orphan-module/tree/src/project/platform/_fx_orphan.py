# 职责：反向样本——一个没有任何调用方、也没有登记的模块。
# 不做什么：不被任何人 import,这正是它要触发的那条判据。
# 允许依赖层：标准库。
# 谁不应该 import：任何人(它就是要保持零消费者)。
"""Module with no consumer and no registration; the zero-consumer gate must reject it."""

VALUE = 1
