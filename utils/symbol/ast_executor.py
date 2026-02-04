# FactorMachine/utils/symbol/ast_executor.py

import ast
import pandas as pd
import os
import inspect
from pathlib import Path
import importlib.util


def load_operators(operators_dir: str) -> dict:
    """
    动态加载算子目录下所有可调用对象：
    - 递归扫描 operators_dir 目录下的 .py 文件
    - 排除 __init__.py 和以下划线开头的文件
    - 将模块中所有非下划线开头且 callable 的对象视为算子
    """
    operators = {}
    base = Path(operators_dir)

    if not base.exists():
        return operators

    for root, _, files in os.walk(base):
        for file in files:
            if not file.endswith(".py") or file.startswith("__"):
                continue

            module_path = Path(root) / file
            module_name = module_path.stem

            spec = importlib.util.spec_from_file_location(module_name, str(module_path))
            if not spec or not spec.loader:
                continue

            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            for name, obj in module.__dict__.items():
                if callable(obj) and not name.startswith("_"):
                    operators[name] = obj

    return operators


class SafeASTExecutor:
    """
    精简安全 AST 执行器，支持在执行时动态添加分组参数。

    支持节点：
      - Constant / Num
      - Name
      - Call
      - UnaryOp (仅负号)

    分组规则（仅对带有 group_by 参数的算子生效）：
      1. 默认使用 group_by='code'。
      2. 若函数调用的最后一个位置参数是字符串常量，且为 'code' 或 'date'，
         则移除该位置参数，并作为 group_by 关键字参数传入。
      3. 若已通过关键字参数显式提供 group_by（例如 group_by='date'），
         则完全按调用者指定，不做任何覆盖。
    """

    # 允许作为分组字段的字符串字面量
    ALLOWED_GROUP_FIELDS = {"code", "date"}

    def __init__(self, operators: dict) -> None:
        self.operators = operators
        # 动态确定哪些函数具有 group_by 参数（无硬编码算子名）
        self._groupable_functions = self._determine_groupable_functions()

    def _determine_groupable_functions(self) -> set:
        """
        检查每个已动态加载的算子函数签名，找出带有 group_by 参数的函数名集合。
        这些算子被视为“支持分组”的算子。
        """
        groupable = set()
        for name, func in self.operators.items():
            try:
                sig = inspect.signature(func)
                if "group_by" in sig.parameters:
                    groupable.add(name)
            except ValueError:
                # 无法获取签名的函数（如某些内建对象），直接跳过
                continue
        return groupable

    def execute(self, expression: str, df: pd.DataFrame):
        """
        将字符串表达式解析为 AST，并在给定 df 上执行
        """
        if not expression:
            return None

        try:
            tree = ast.parse(expression, mode="eval")
        except SyntaxError:
            return None

        return self._eval(tree.body, df)

    def _eval(self, node: ast.AST, df: pd.DataFrame):
        # 常量
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Num):  # 兼容旧版本 AST
            return node.n

        # 名字：优先当列名，否则当算子名
        if isinstance(node, ast.Name):
            if node.id in df.columns:
                return df[node.id]
            if node.id in self.operators:
                return self.operators[node.id]
            raise NameError(f"未识别的标识符: {node.id}")

        # 函数调用
        if isinstance(node, ast.Call):
            # 只支持以 Name 形式直接调用的算子（保持原有约束）
            if not isinstance(node.func, ast.Name):
                raise TypeError(f"不支持的函数调用形式: {type(node.func).__name__}")

            func_name = node.func.id
            if func_name not in self.operators:
                raise TypeError(f"不支持的函数调用: {func_name}")

            func = self.operators[func_name]

            # 先递归计算所有位置参数和关键字参数的值
            args = [self._eval(arg, df) for arg in node.args]
            kwargs = {kw.arg: self._eval(kw.value, df) for kw in node.keywords}

            # —— 统一分组逻辑：仅对带 group_by 的算子生效 —— #
            if func_name in self._groupable_functions:
                # 1. 如果已经显式传了 group_by 关键字参数，则尊重调用者，不改动
                if "group_by" in kwargs:
                    pass
                else:
                    # 2. 检查 AST 上最后一个“原始位置参数”是否是字符串字面量
                    #    注意：这里用 node.args 判断，而不是已求值的 args
                    if node.args and isinstance(node.args[-1], ast.Constant) and isinstance(node.args[-1].value, str):
                        last_val = node.args[-1].value
                        if last_val in self.ALLOWED_GROUP_FIELDS:
                            # 最后一个参数是分组字段名：从位置参数中剔除，将其作为 group_by
                            args = args[:-1]
                            kwargs["group_by"] = last_val
                        else:
                            # 字符串不是允许的分组字段，则使用默认 'code'
                            kwargs["group_by"] = "code"
                    else:
                        # 没有显式分组字符串，默认按 'code' 分组
                        kwargs["group_by"] = "code"

            # 执行函数调用
            return func(*args, **kwargs)

        # 一元运算（仅支持负号）
        if isinstance(node, ast.UnaryOp):
            operand = self._eval(node.operand, df)
            if isinstance(node.op, ast.USub):
                return -operand
            raise TypeError(f"不支持的一元操作: {type(node.op).__name__}")

        # 其他形式（包括 BinOp）统统不支持（保持原有限制）
        raise TypeError(f"不支持的节点类型: {type(node).__name__}")