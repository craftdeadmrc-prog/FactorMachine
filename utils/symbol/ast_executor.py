# FactorMachine/utils/symbol/ast_executor.py

import ast
import pandas as pd
import os
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
    精简安全 AST 执行器：
    支持节点：
      - Constant / Num
      - Name
      - Call
      - UnaryOp (仅负号)

    注意：
    - 不再支持基础二元运算符（+ - * / ** 等）
    - 所有基础运算需通过算子（如 add/sub/mul/div/pow）实现
    """

    def __init__(self, operators: dict) -> None:
        self.operators = operators

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
            func = self._eval(node.func, df)
            args = [self._eval(arg, df) for arg in node.args]
            kwargs = {kw.arg: self._eval(kw.value, df) for kw in node.keywords}
            return func(*args, **kwargs)

        # 一元运算（仅支持负号）
        if isinstance(node, ast.UnaryOp):
            operand = self._eval(node.operand, df)
            if isinstance(node.op, ast.USub):
                return -operand
            raise TypeError(f"不支持的一元操作: {type(node.op).__name__}")

        # 其他形式（包括 BinOp）统统不支持
        raise TypeError(f"不支持的节点类型: {type(node).__name__}")