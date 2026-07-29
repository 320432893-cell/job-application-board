"""反向样本 fixture：beta 绕过 alpha 的 api.py，直接 import 它的内部实现。"""

from project.features.fxalpha.use_cases import compute

VALUE = compute()
